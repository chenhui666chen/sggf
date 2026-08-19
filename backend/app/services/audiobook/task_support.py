from __future__ import annotations

import hashlib
import json
import logging
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.models.audiobook import (
    AudiobookProject,
    AudiobookTaskDispatch,
    ChapterAudio,
    ChapterAudioRun,
)
from app.models.audiobook_task import AudiobookTask
from app.models.user import User
from app.schemas.audiobook import AudiobookTaskStatus
from app.services.audiobook.billing_snapshot_builder import build_billing_snapshot
from app.services.audiobook.project_audio_config import (
    build_run_input_snapshot,
    parse_engine_config_snapshot,
    parse_project_audio_config,
    resolve_engine_mode,
)
from app.services.audiobook.repository import AudiobookTaskRepository, ChapterAudioRunRepository
from app.services.audiobook.scene_engine.scene_billing import SEED_AUDIO_MODEL
from app.services.audiobook.temp_segment_store import extract_cached_segment_paths, temp_segment_asset_exists
from app.services.points_task_precheck import build_task_points_precheck_error_detail
from app.services.user_center_points_events import record_audiobook_billing_freeze
from app.utils.datetime_utils import utc_now

CHECKPOINT_SCHEMA_VERSION = 1
RESUME_WINDOW_HOURS = 72
RESUMABLE_RUN_STATUSES = {"", "failed", "paused", "cancelled", "canceled"}
RESUME_RUN_TYPE_PRIORITY = {
    "audio_from_scripts": 3,
    "full": 2,
    "script_only": 1,
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudiobookBillingPricingContext:
    audio_engine_mode: str
    pricing_key: str


def resolve_audiobook_billing_pricing_context(
    *,
    project: Any,
    tts_pricing_key: str,
) -> AudiobookBillingPricingContext:
    config = parse_project_audio_config(
        str(getattr(project, "audio_config", "") or "")
    )
    audio_engine_mode = resolve_engine_mode(config)
    pricing_key = (
        SEED_AUDIO_MODEL
        if audio_engine_mode == "seed_scene"
        else str(tts_pricing_key or "").strip()
    )
    return AudiobookBillingPricingContext(
        audio_engine_mode=audio_engine_mode,
        pricing_key=pricing_key,
    )


class StageTracker(Protocol):
    def update_stage(
        self,
        stage: str,
        completed: int,
        total: int,
        message: Optional[str] = None,
        detail: Optional[dict] = None,
    ) -> None:
        ...


def ensure_audiobook_points_precheck_passed(precheck: object) -> None:
    if bool(getattr(precheck, "allowed", False)):
        return
    detail = build_task_points_precheck_error_detail(
        precheck=precheck,
        module_key="audiobook",
        module_label="有声书",
        default_message="有声书积分预检未通过",
    )
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def lock_billing_account(db: Session, user_id: int) -> None:
    """R11/P0-2：入队事务开头取账户 advisory 锁（锁序最前端）。

    与冻结/结算/finalizer 使用同一锁键，串行化同账户的并发入队冻结裁决。
    非 PostgreSQL 方言（SQLite 测试环境）降级为 no-op——并发账户锁语义
    由真实 PG 保证（E2E/生产均为 PG）。
    """
    from sqlalchemy import text

    dialect = str(getattr(getattr(db, "bind", None), "dialect", None))
    if dialect and not dialect.startswith("postgresql"):
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": int(user_id)},
    )


def safe_record_audiobook_billing_freeze(
    *,
    db: Session,
    current_user: User,
    audiobook_project_id: int,
    chapter_ids: list[int],
    raw_request: Any,
    tts_pricing_key: str,
    trace_context: Optional[Dict[str, Any]] = None,
    estimated_yuan_override: Optional[float] = None,
    raise_on_error: bool = False,
) -> None:
    try:
        payload = {
            "db": db,
            "actor_user_id": current_user.id,
            "actor_username": current_user.username,
            "audiobook_project_id": audiobook_project_id,
            "chapter_ids": chapter_ids,
            "request_context": raw_request,
            "tts_pricing_key": tts_pricing_key,
        }
        if trace_context is not None:
            payload["extra_payload"] = trace_context
        if estimated_yuan_override is not None:
            payload["estimated_yuan_override"] = estimated_yuan_override
        record_audiobook_billing_freeze(**payload)
    except Exception as exc:
        logger.warning(
            "记录有声书积分冻结失败 audiobook_project_id=%s chapter_ids=%s: %s",
            audiobook_project_id,
            chapter_ids,
            exc,
        )
        if raise_on_error:
            # R11/P0-2 同事务冻结：失败向上抛使整个入队事务回滚
            # （run/指针/快照/冻结一并消失，不产生"未冻结先执行"残留）
            raise


def serialize_dataclass_to_dict(obj: Any):
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, list):
        return [serialize_dataclass_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {key: serialize_dataclass_to_dict(value) for key, value in obj.items()}
    return obj


def build_task_status_response(task: AudiobookTask) -> AudiobookTaskStatus:
    return AudiobookTaskStatus(
        celery_task_id=task.celery_task_id,
        audiobook_project_id=task.audiobook_project_id,
        chapter_id=task.chapter_id,
        task_type=task.task_type,
        status=task.status,
        current_stage=task.current_stage,
        progress=task.progress or 0.0,
        completed_units=task.completed_units or 0,
        total_units=task.total_units or 0,
        detail=task.detail_json or {},
        error_message=task.error_message,
        created_at=task.created_at.isoformat() if task.created_at else None,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        finished_at=task.finished_at.isoformat() if task.finished_at else None,
        # R13/P1-a：job_id = task:{AudiobookTask.id} 命名空间字符串
        job_id=f"task:{task.id}",
    )


def _safe_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _safe_json_value(item) for key, item in value.items()}
    return value


def _stable_json_dumps(value: Any) -> str:
    return json.dumps(
        _safe_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256_payload(value: Any) -> Optional[str]:
    normalized = _safe_json_value(value)
    if normalized in (None, "", [], {}):
        return None
    return hashlib.sha256(_stable_json_dumps(normalized).encode("utf-8")).hexdigest()


def _parse_iso_datetime(value: Any):
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _checkpoint_path_exists(path_value: str) -> bool:
    return temp_segment_asset_exists(path_value)


def _classify_temp_asset_storage_driver(asset_ref: str) -> str:
    raw = str(asset_ref or "").strip().lower()
    if raw.startswith("oss://") or raw.startswith("http://") or raw.startswith("https://"):
        return "dashscope_oss"
    return "local_fs"


def _normalize_segment_index(value: Any) -> Optional[int]:
    try:
        index = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if index < 0:
        return None
    return index


def _extract_checkpoint_segment_indices(checkpoint_data: Optional[Dict[str, Any]]) -> List[int]:
    checkpoint = dict(checkpoint_data or {})
    indices: List[int] = []
    seen: set[int] = set()

    completed_segment_indices = checkpoint.get("completed_segment_indices") or []
    if isinstance(completed_segment_indices, list):
        for raw_index in completed_segment_indices:
            index = _normalize_segment_index(raw_index)
            if index is None or index in seen:
                continue
            seen.add(index)
            indices.append(index)

    cached_audio_paths = checkpoint.get("cached_audio_paths") or {}
    if isinstance(cached_audio_paths, dict):
        for raw_index in cached_audio_paths.keys():
            index = _normalize_segment_index(raw_index)
            if index is None or index in seen:
                continue
            seen.add(index)
            indices.append(index)

    segments = checkpoint.get("segments") or {}
    if isinstance(segments, dict):
        for raw_index, payload in segments.items():
            if isinstance(payload, dict):
                candidate = payload.get("index", raw_index)
            else:
                candidate = raw_index
            index = _normalize_segment_index(candidate)
            if index is None or index in seen:
                continue
            seen.add(index)
            indices.append(index)

    indices.sort()
    return indices


def _collect_checkpoint_temp_asset_checks(checkpoint_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    checkpoint = dict(checkpoint_data or {})
    candidates: Dict[Tuple[int, str], Dict[str, Any]] = {}

    def add_candidate(raw_index: Any, raw_path: Any, source: str) -> None:
        index = _normalize_segment_index(raw_index)
        path_value = str(raw_path or "").strip()
        if index is None or not path_value:
            return
        key = (index, path_value)
        item = candidates.setdefault(
            key,
            {
                "index": index,
                "asset_ref": path_value,
                "storage_driver": _classify_temp_asset_storage_driver(path_value),
                "sources": [],
            },
        )
        if source not in item["sources"]:
            item["sources"].append(source)

    cached_audio_paths = checkpoint.get("cached_audio_paths") or {}
    if isinstance(cached_audio_paths, dict):
        for raw_index, raw_path in cached_audio_paths.items():
            add_candidate(raw_index, raw_path, "cached_audio_paths")

    segments = checkpoint.get("segments") or {}
    if isinstance(segments, dict):
        for raw_index, segment_payload in segments.items():
            if not isinstance(segment_payload, dict):
                continue
            add_candidate(
                segment_payload.get("index", raw_index),
                segment_payload.get("temp_object_key"),
                "segments",
            )

    checks: List[Dict[str, Any]] = []
    for item in sorted(candidates.values(), key=lambda value: (value["index"], value["asset_ref"])):
        exists = _checkpoint_path_exists(item["asset_ref"])
        checks.append(
            {
                **item,
                "exists": bool(exists),
                "reason": None if exists else "missing_temp_asset",
            }
        )
    return checks


def _find_inconsistent_temp_asset_refs(
    segment_asset_checks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    refs_by_index: Dict[int, List[Dict[str, Any]]] = {}
    for item in segment_asset_checks or []:
        if not isinstance(item, dict):
            continue
        index = _normalize_segment_index(item.get("index"))
        if index is None:
            continue
        asset_ref = str(item.get("asset_ref") or "").strip()
        if not asset_ref:
            continue
        refs_by_index.setdefault(index, []).append(item)

    inconsistent_refs: List[Dict[str, Any]] = []
    for index, items in sorted(refs_by_index.items(), key=lambda value: value[0]):
        refs = []
        seen_refs: set[str] = set()
        for item in items:
            asset_ref = str(item.get("asset_ref") or "").strip()
            if not asset_ref or asset_ref in seen_refs:
                continue
            seen_refs.add(asset_ref)
            refs.append(
                {
                    "asset_ref": asset_ref,
                    "storage_driver": item.get("storage_driver"),
                    "sources": list(item.get("sources") or []),
                    "exists": item.get("exists"),
                }
            )
        if len(refs) > 1:
            inconsistent_refs.append(
                {
                    "index": index,
                    "asset_refs": refs,
                    "reason": "multiple_asset_refs_for_segment",
                }
            )

    return inconsistent_refs


def _mark_checkpoint_recorded_segment_statuses(checkpoint_document: Dict[str, Any]) -> None:
    segment_statuses = checkpoint_document.get("segment_statuses")
    if not isinstance(segment_statuses, dict) or not segment_statuses:
        return

    cached_indices = set(extract_cached_segment_paths(checkpoint_document).keys())
    if not cached_indices:
        return

    updated: Dict[str, Any] = {}
    for raw_key, raw_status in segment_statuses.items():
        key = str(raw_key)
        if not isinstance(raw_status, dict):
            updated[key] = raw_status
            continue

        status = dict(raw_status)
        index = _normalize_segment_index(status.get("index", raw_key))
        if index is None:
            updated[key] = status
            continue

        if index in cached_indices and status.get("status") == "cached":
            status["recovery_stage"] = "checkpoint_recorded"
        updated[key] = status

    checkpoint_document["segment_statuses"] = updated


def _parse_run_input_snapshot(raw: Any) -> Optional[Dict[str, Any]]:
    """解析 run_input_snapshot JSON；缺失/损坏返回 None（历史 run 回退实时解析）。"""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw if raw.get("signed_payload") else None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("signed_payload"):
        return None
    return data


def _read_revision_heads_projection(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
) -> Optional[Dict[str, Any]]:
    """读三条编辑链 head 投影（创建运行同一事务内，验收 19）。"""
    try:
        from app.services.audiobook.scene_edit_revision_service import (
            compute_revision_set_hash,
            get_revision_heads_projection,
        )

        heads = get_revision_heads_projection(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        )
        if not any(heads.values()):
            return None
        return {
            "revision_set_hash": compute_revision_set_hash(heads),
            "dialogue": heads.get("dialogue"),
            "director_override": heads.get("director_override"),
            "voice_binding": heads.get("voice_binding"),
            "projection": heads,
        }
    except Exception:
        logger.warning(
            "读取场景编辑基线投影失败，快照不带 revision_heads: batch=%s chapter=%s",
            audiobook_project_id,
            chapter_id,
        )
        return None


def build_run_input_snapshot_for_chapter(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    run_type: str,
    tts_model: Optional[str] = None,
    output_format: Optional[str] = None,
    narration_style: Optional[str] = None,
    narration_style_prompt: Optional[str] = None,
    generate_subtitle: Optional[bool] = True,
    timeline_edits: Optional[Dict[str, Any]] = None,
    revision_heads: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建章节 run 的 run_input_snapshot（GUIDE 验收 8/19，方案 A 自包含正文）。

    full/script_only 冻结原章正文（script_facts=None）；audio_from_scripts/场景
    重渲染在创建运行同一事务内读已审批 script_json 为 script_facts 正文，并携带
    编辑基线投影（revision_heads）。批量构建可传入预读的 revision_heads。
    """
    from app.models.audiobook import AudiobookProject
    from app.models.project import Chapter

    audiobook_project = (
        db.query(AudiobookProject)
        .filter(AudiobookProject.id == audiobook_project_id)
        .first()
    )
    batch_snapshot = (
        parse_engine_config_snapshot(
            getattr(audiobook_project, "engine_config_snapshot", None)
        )
        if audiobook_project is not None
        else None
    )
    if not batch_snapshot:
        # 无批次快照（legacy_unverified 等）：退化为空配置，快照仍携带正文
        batch_snapshot = {"engine_mode": "legacy_stems", "engine_branch_config": {}}

    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    chapter_audio = (
        db.query(ChapterAudio)
        .filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.chapter_id == chapter_id,
            ChapterAudio.deleted_at.is_(None),
        )
        .first()
    )

    normalized_run_type = str(run_type or "").strip().lower()
    script_facts = None
    source_chapter_content = None
    if normalized_run_type == "audio_from_scripts":
        script_facts = _safe_json_value(
            getattr(chapter_audio, "script_json", None)
            if chapter_audio is not None
            else None
        )
        if revision_heads is None:
            revision_heads = _read_revision_heads_projection(
                db,
                audiobook_project_id=audiobook_project_id,
                chapter_id=chapter_id,
            )
    else:
        # full/script_only 按 run_type 合同冻结原章输入，不携带编辑基线投影
        revision_heads = None
        source_chapter_content = getattr(chapter, "content", None) if chapter is not None else None

    return build_run_input_snapshot(
        batch_snapshot,
        {
            "tts_model": tts_model,
            "output_format": output_format or "mp3",
            "narration_style": narration_style,
            "narration_style_prompt": narration_style_prompt,
            "generate_subtitle": generate_subtitle is not False,
            "timeline_edits": timeline_edits,
            "source_chapter_content": source_chapter_content,
        },
        revision_heads=revision_heads,
        script_facts=script_facts,
    )


def _build_resume_input_context(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    chapter_run,
    chapter_audio: Optional[ChapterAudio] = None,
) -> Dict[str, Any]:
    from app.models.audiobook import AudiobookProject
    from app.models.project import Chapter, Project
    from app.services.audiobook.project_audio_runtime import (
        resolve_from_run_input,
        resolve_project_audio_runtime_config,
    )

    audiobook_project = (
        db.query(AudiobookProject)
        .filter(AudiobookProject.id == audiobook_project_id)
        .first()
    )
    project = (
        db.query(Project)
        .filter(Project.id == audiobook_project.project_id)
        .first()
        if audiobook_project
        else None
    )
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()

    if chapter_audio is None:
        chapter_audio = (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id == audiobook_project_id,
                ChapterAudio.chapter_id == chapter_id,
            )
            .first()
        )

    resolved_tts_model = str(
        getattr(chapter_run, "tts_model", None) or "qwen3-tts-instruct-flash"
    ).strip() or "qwen3-tts-instruct-flash"
    resolved_output_format = str(
        getattr(chapter_run, "output_format", None) or "mp3"
    ).strip() or "mp3"

    run_type = str(getattr(chapter_run, "run_type", "") or "").strip().lower()

    # 验收 8/19：恢复只消费 run_input_snapshot（方案 A 自包含正文），不读取
    # 项目当前活跃引擎与实时配置；无快照的历史 run 回退实时解析（向后兼容）
    run_input_snapshot = _parse_run_input_snapshot(
        getattr(chapter_run, "run_input_snapshot", None)
    )
    if run_input_snapshot is not None:
        signed = run_input_snapshot.get("signed_payload") or {}
        run_options = signed.get("run_options") or {}
        resolved_narration_style = (
            run_options.get("narration_style")
            or getattr(chapter_run, "narration_style", None)
            or getattr(chapter_audio, "narration_style", None)
        )
        resolved_narration_style_prompt = (
            run_options.get("narration_style_prompt")
            or getattr(chapter_run, "narration_style_prompt", None)
            or getattr(chapter_audio, "narration_style_prompt", None)
        )
        resolved_output_format = str(
            run_options.get("output_format") or resolved_output_format
        ).strip() or "mp3"
        # 运行期消费快照冻结的规范化配置（不读实时 audio_config）
        runtime_config = resolve_from_run_input(
            run_input_snapshot,
            tts_model=resolved_tts_model,
        )
        voice_config_payload = {
            "model": resolved_tts_model,
            "characters": runtime_config.character_items,
        }
        audio_fx_payload = runtime_config.audio_fx
        if run_type == "audio_from_scripts":
            script_facts = signed.get("script_facts")
            script_source_payload = (
                script_facts
                if script_facts is not None
                else _safe_json_value(getattr(chapter_audio, "script_json", None))
            )
        else:
            script_source_payload = {
                "chapter_title": getattr(chapter, "title", None),
                "chapter_content": signed.get("source_chapter_content")
                or getattr(chapter, "content", None),
                "chapter_summary": getattr(chapter, "summary", None),
                "summary_data": _safe_json_value(getattr(chapter, "summary_data", None)),
            }
    else:
        resolved_narration_style = (
            getattr(chapter_run, "narration_style", None)
            or getattr(chapter_audio, "narration_style", None)
        )
        resolved_narration_style_prompt = (
            getattr(chapter_run, "narration_style_prompt", None)
            or getattr(chapter_audio, "narration_style_prompt", None)
        )

        runtime_config = resolve_project_audio_runtime_config(
            project,
            tts_model=resolved_tts_model,
        )
        voice_config_payload = {
            "model": resolved_tts_model,
            "characters": runtime_config.character_items,
        }
        audio_fx_payload = runtime_config.audio_fx

        if run_type == "audio_from_scripts":
            script_source_payload = _safe_json_value(getattr(chapter_audio, "script_json", None))
        else:
            script_source_payload = {
                "chapter_title": getattr(chapter, "title", None),
                "chapter_content": getattr(chapter, "content", None),
                "chapter_summary": getattr(chapter, "summary", None),
                "summary_data": _safe_json_value(getattr(chapter, "summary_data", None)),
            }

    return {
        "tts_model": resolved_tts_model,
        "output_format": resolved_output_format,
        "narration_style": resolved_narration_style,
        "narration_style_prompt": resolved_narration_style_prompt,
        "script_hash": _sha256_payload(script_source_payload),
        "voice_config_hash": _sha256_payload(voice_config_payload),
        "audio_fx_hash": _sha256_payload(audio_fx_payload),
    }


def build_run_checkpoint_document(
    db: Session,
    *,
    run,
    chapter_id: int,
    audiobook_project_id: int,
    status: Optional[str] = None,
    current_stage: Optional[str] = None,
    total_segment_count: Optional[int] = None,
    completed_segment_count: Optional[int] = None,
    checkpoint_patch: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    chapter_audio: Optional[ChapterAudio] = None,
) -> Dict[str, Any]:
    existing_checkpoint = dict(run.checkpoint_json or {})
    context = _build_resume_input_context(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        chapter_run=run,
        chapter_audio=chapter_audio,
    )

    resolved_status = str(status or run.status or existing_checkpoint.get("status") or "pending")
    resolved_stage = current_stage or run.current_stage or existing_checkpoint.get("current_stage")
    resolved_total_segments = int(
        total_segment_count
        if total_segment_count is not None
        else run.total_segment_count or existing_checkpoint.get("total_segments") or 0
    )
    completed_segment_indices = _extract_checkpoint_segment_indices(existing_checkpoint)
    resolved_completed_segments = int(
        completed_segment_count
        if completed_segment_count is not None
        else run.completed_segment_count
        or existing_checkpoint.get("completed_segment_count")
        or len(completed_segment_indices)
        or 0
    )

    failed_segment_indices = existing_checkpoint.get("failed_segment_indices") or []
    if not isinstance(failed_segment_indices, list):
        failed_segment_indices = []

    cached_audio_paths = extract_cached_segment_paths(existing_checkpoint)

    segments = existing_checkpoint.get("segments") or {}
    if not isinstance(segments, dict):
        segments = {}

    checkpoint_document: Dict[str, Any] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "run_db_id": run.id,
        "run_type": run.run_type,
        "status": resolved_status,
        "current_stage": resolved_stage,
        "tts_model": context["tts_model"],
        "output_format": context["output_format"],
        "narration_style": context["narration_style"],
        "narration_style_prompt": context["narration_style_prompt"],
        "script_hash": context["script_hash"],
        "voice_config_hash": context["voice_config_hash"],
        "audio_fx_hash": context["audio_fx_hash"],
        "total_segments": resolved_total_segments,
        "completed_segment_count": resolved_completed_segments,
        "completed_segment_indices": list(completed_segment_indices),
        "failed_segment_indices": list(failed_segment_indices),
        "cached_audio_paths": dict(cached_audio_paths),
        "segments": dict(segments),
        "last_error": error_message or existing_checkpoint.get("last_error"),
        "checkpoint_updated_at": utc_now().isoformat(),
        "expires_at": run.expires_at.isoformat() if getattr(run, "expires_at", None) else existing_checkpoint.get("expires_at"),
    }

    for key, value in existing_checkpoint.items():
        checkpoint_document.setdefault(key, value)

    if checkpoint_patch:
        for key, value in checkpoint_patch.items():
            if key == "segments" and isinstance(value, dict):
                checkpoint_document["segments"] = {
                    **dict(checkpoint_document.get("segments") or {}),
                    **value,
                }
            elif key == "cached_audio_paths" and isinstance(value, dict):
                checkpoint_document["cached_audio_paths"] = {
                    **dict(checkpoint_document.get("cached_audio_paths") or {}),
                    **value,
                }
            elif key == "scene_checkpoints" and isinstance(value, dict):
                checkpoint_document["scene_checkpoints"] = {
                    **dict(checkpoint_document.get("scene_checkpoints") or {}),
                    **value,
                }
            elif key in {"completed_segment_indices", "failed_segment_indices"} and isinstance(value, list):
                checkpoint_document[key] = list(value)
            else:
                checkpoint_document[key] = value

    checkpoint_document["total_segments"] = int(checkpoint_document.get("total_segments") or 0)
    checkpoint_document["completed_segment_indices"] = _extract_checkpoint_segment_indices(checkpoint_document)
    checkpoint_document["completed_segment_count"] = max(
        int(checkpoint_document.get("completed_segment_count") or 0),
        len(checkpoint_document.get("completed_segment_indices") or []),
    )
    _mark_checkpoint_recorded_segment_statuses(checkpoint_document)

    if (
        resolved_status == "completed"
        and resolved_total_segments > 0
        and not checkpoint_document.get("completed_segment_indices")
        and resolved_total_segments <= 512
    ):
        checkpoint_document["completed_segment_indices"] = list(range(resolved_total_segments))
        checkpoint_document["completed_segment_count"] = resolved_total_segments

    return checkpoint_document


def _tracker_update(
    tracker: StageTracker | None,
    stage: str,
    completed: int,
    total: int,
    message: Optional[str] = None,
    detail: Optional[dict] = None,
) -> None:
    if tracker is None:
        return
    tracker.update_stage(stage, completed, total, message, detail)


def build_progress_handler(
    tracker: StageTracker | None,
    chapter_ids: List[int],
) -> Optional[Callable[[Dict[str, Any]], None]]:
    if tracker is None:
        return None

    total = max(len(chapter_ids) or 0, 1)
    chapter_positions: Dict[int, int] = {chapter_id: idx + 1 for idx, chapter_id in enumerate(chapter_ids)}
    chapter_completed: Dict[int, bool] = {}

    def handle_progress(snapshot: Dict[str, Any]) -> None:
        stage = snapshot.get("current_stage")
        chapter_id = snapshot.get("chapter_id")
        if not stage or chapter_id is None:
            return

        if snapshot.get("status") == "completed":
            chapter_completed[chapter_id] = True
        completed_units = sum(1 for finished in chapter_completed.values() if finished)

        detail_payload = {
            "chapter_id": chapter_id,
            "run_id": snapshot.get("run_id"),
            "task_id": snapshot.get("task_id"),
            "overall_progress": snapshot.get("overall_progress"),
            "stages": snapshot.get("stages"),
            "status": snapshot.get("status"),
            "chapter_index": chapter_positions.get(chapter_id),
            "chapter_total": total,
        }
        stage_name = stage if isinstance(stage, str) else str(stage)
        message = f"章节 {chapter_positions.get(chapter_id, '?')}/{total} · {stage_name}"
        _tracker_update(tracker, stage_name, completed_units, total, message, detail_payload)

    return handle_progress


def _ensure_active_chapter_audio(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
) -> ChapterAudio:
    """查/建唯一 active ChapterAudio（R10/P0-4）。

    部分唯一索引 ``UNIQUE (audiobook_project_id, chapter_id) WHERE deleted_at IS NULL``
    保护：并发首次创建仅一个成功，loser 按 SAVEPOINT 协议回滚重读复用。
    """
    audio = (
        db.query(ChapterAudio)
        .filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.chapter_id == chapter_id,
            ChapterAudio.deleted_at.is_(None),
        )
        .first()
    )
    if audio is not None:
        return audio
    try:
        with db.begin_nested():
            audio = ChapterAudio(
                audiobook_project_id=audiobook_project_id,
                chapter_id=chapter_id,
            )
            db.add(audio)
            db.flush()
        return audio
    except IntegrityError:
        # 并发 loser：回滚到 SAVEPOINT 后重读复用（R10/P0-4）
        return (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id == audiobook_project_id,
                ChapterAudio.chapter_id == chapter_id,
                ChapterAudio.deleted_at.is_(None),
            )
            .first()
        )


def _freeze_billing_snapshot_into_run(
    db: Session,
    *,
    run: ChapterAudioRun,
    engine_mode: str,
    billing_account_user_id: Optional[int],
) -> None:
    """冻结不可变计价快照进 run_input_snapshot（验收 19/23，六步闭环①）。

    billing_snapshot 已存在（重渲染/恢复等场景）时不覆盖——冻结事实不可变。
    """
    snapshot_payload = (
        json.loads(run.run_input_snapshot) if run.run_input_snapshot else {}
    )
    if not isinstance(snapshot_payload, dict):
        snapshot_payload = {}
    signed = snapshot_payload.setdefault("signed_payload", {})
    if not isinstance(signed, dict):
        signed = {}
        snapshot_payload["signed_payload"] = signed
    billing_ctx = signed.setdefault("billing_context", {})
    if not isinstance(billing_ctx, dict):
        billing_ctx = {}
        signed["billing_context"] = billing_ctx

    changed = False
    if billing_ctx.get("billing_snapshot") is None:
        billing_ctx["billing_snapshot"] = build_billing_snapshot(
            db,
            audiobook_project_id=run.audiobook_project_id,
            run_type=run.run_type or "full",
            tts_model=run.tts_model,
            engine_mode=engine_mode,
        )
        changed = True
    if billing_ctx.get("billing_account_user_id") is None and billing_account_user_id is not None:
        billing_ctx["billing_account_user_id"] = int(billing_account_user_id)
        changed = True
    if changed:
        run.run_input_snapshot = json.dumps(snapshot_payload, ensure_ascii=False)
        run.billing_account_user_id = int(billing_account_user_id) if billing_account_user_id is not None else None


def _compensate_failed_enqueue_dispatch(db: Session, runs: List[ChapterAudioRun]) -> None:
    """批量派发明确失败后的条件补偿（R11/P1-4）。

    锁定 ChapterAudio + CAS 回退 desired_run_id（仅当仍指向失败 run），
    run 置 cancelled、dispatch_status='cancelled'。
    """
    now = utc_now()
    for run in runs:
        if run.chapter_audio_id:
            db.query(ChapterAudio).filter(
                ChapterAudio.id == run.chapter_audio_id,
                ChapterAudio.desired_run_id == run.id,
            ).update(
                {ChapterAudio.desired_run_id: run.predecessor_run_id},
                synchronize_session=False,
            )
        run.status = "cancelled"
        run.dispatch_status = "cancelled"
        run.finished_at = now
        run.error_message = "dispatch_failed: Celery apply_async raised exception"
    db.flush()


def enqueue_chapter_runs(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_ids: List[int],
    run_type: str,
    celery_task_id: Optional[str],
    tts_model: Optional[str] = None,
    output_format: Optional[str] = None,
    narration_style: Optional[str] = None,
    narration_style_prompt: Optional[str] = None,
    generate_subtitle: Optional[bool] = True,
    timeline_edits_by_chapter: Optional[Dict[int, Dict[str, Dict[str, float]]]] = None,
    revision_heads_by_chapter: Optional[Dict[int, Dict[str, Any]]] = None,
    task_id: Optional[int] = None,
) -> List[ChapterAudioRun]:
    normalized_ids = [chapter_id for chapter_id in dict.fromkeys(chapter_ids or []) if chapter_id is not None]
    if not normalized_ids:
        return []
    # Contract 收窄后 chapter_audio_id NOT NULL：创建 run 前先解析/创建唯一 active
    # ChapterAudio（运行作用域，R9/P0-3/R10/P0-4），随 INSERT 一并落库
    chapter_audio_by_chapter: Dict[int, ChapterAudio] = {}
    for chapter_id in normalized_ids:
        chapter_audio_by_chapter[chapter_id] = _ensure_active_chapter_audio(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        )
    runs = ChapterAudioRunRepository.create_runs(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=normalized_ids,
        run_type=run_type,
        celery_task_id=celery_task_id,
        chapter_audio_ids={
            chapter_id: audio.id
            for chapter_id, audio in chapter_audio_by_chapter.items()
        },
        status="queued",
        current_stage="queued",
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
        resumable=True,
    )
    # 批次引擎模式与计费账户（billing_snapshot 冻结用）
    audiobook_project = (
        db.query(AudiobookProject)
        .filter(AudiobookProject.id == audiobook_project_id)
        .first()
    )
    batch_snapshot = parse_engine_config_snapshot(
        getattr(audiobook_project, "engine_config_snapshot", None)
        if audiobook_project is not None
        else None
    )
    engine_mode = (
        str((batch_snapshot or {}).get("engine_mode") or "")
        or (getattr(audiobook_project, "engine_mode", None) or "legacy_stems")
    )
    billing_account_user_id = None
    if audiobook_project is not None:
        from app.models.project import Project
        project = (
            db.query(Project)
            .filter(Project.id == audiobook_project.project_id)
            .first()
        )
        if project is not None:
            billing_account_user_id = getattr(project, "user_id", None)

    for run in runs:
        checkpoint_patch: Dict[str, Any] = {"generate_subtitle": generate_subtitle is not False}
        chapter_timeline_edits = (
            timeline_edits_by_chapter.get(run.chapter_id)
            if timeline_edits_by_chapter
            else None
        )
        if chapter_timeline_edits:
            checkpoint_patch["timeline_edits"] = chapter_timeline_edits
        run.checkpoint_json = build_run_checkpoint_document(
            db,
            run=run,
            chapter_id=run.chapter_id,
            audiobook_project_id=audiobook_project_id,
            status=run.status,
            current_stage=run.current_stage,
            checkpoint_patch=checkpoint_patch,
        )
        # 验收 8/19：创建运行同一事务内构建 run_input_snapshot（方案 A 自包含正文）
        run_input_snapshot = build_run_input_snapshot_for_chapter(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=run.chapter_id,
            run_type=run_type,
            tts_model=tts_model,
            output_format=output_format,
            narration_style=narration_style,
            narration_style_prompt=narration_style_prompt,
            generate_subtitle=generate_subtitle,
            timeline_edits=chapter_timeline_edits,
            revision_heads=(
                (revision_heads_by_chapter or {}).get(run.chapter_id)
                if revision_heads_by_chapter
                else None
            ),
        )
        run.run_input_snapshot = json.dumps(run_input_snapshot, ensure_ascii=False)

        # 运行作用域（R9/P0-3，R10/P0-4）：创建时已携带 chapter_audio_id，
        # 此处复用预解析的 active ChapterAudio（Contract 收窄后非空）
        chapter_audio = chapter_audio_by_chapter.get(run.chapter_id)
        if chapter_audio is None:
            chapter_audio = _ensure_active_chapter_audio(
                db,
                audiobook_project_id=audiobook_project_id,
                chapter_id=run.chapter_id,
            )
        run.chapter_audio_id = chapter_audio.id
        run.predecessor_run_id = chapter_audio.desired_run_id
        # 先落库 run 的 chapter_audio_id：双指针复合外键与 TaskDispatch 复合外键
        # 都要求 (run_id, chapter_audio_id) 在 chapter_audio_runs 中可匹配，
        # 必须在 desired_run_id 更新之前保证 run 行已带正确作用域
        db.flush()
        chapter_audio.desired_run_id = run.id
        db.flush()

        # 派发意图 outbox（R11/P0-1）：每 run 独立固定 celery_task_id + 意图字段
        run.celery_task_id = str(uuid4())
        run.dispatch_status = "pending"
        run.dispatch_attempts = 0
        run.next_dispatch_at = utc_now()

        # 任务-派发父子关系（R11/P0-3）
        if task_id is not None:
            db.add(
                AudiobookTaskDispatch(
                    task_id=int(task_id),
                    run_id=run.id,
                    chapter_audio_id=chapter_audio.id,
                )
            )

        # 计费事实冻结（验收 19/23）：不可变计价快照 + 计费账户
        _freeze_billing_snapshot_into_run(
            db,
            run=run,
            engine_mode=engine_mode,
            billing_account_user_id=billing_account_user_id,
        )
        db.add(run)
    if runs:
        # R10/P0-3：内部不 commit（只 flush）——事务所有权归最外层应用服务，
        # 由调用方与计费冻结在同一事务内统一提交（R11/P0-2 同事务冻结）
        db.flush()
    return runs


def enqueue_audiobook_task(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_ids: List[int],
    job_type: str,
    tts_model: str,
    output_format: Optional[str] = None,
    narration_style: Optional[str] = None,
    narration_style_prompt: Optional[str] = None,
    generate_subtitle: Optional[bool] = True,
    timeline_edits_by_chapter: Optional[Dict[int, Dict[str, Dict[str, float]]]] = None,
    force_regenerate_script: bool = False,
    revision_heads_by_chapter: Optional[Dict[int, Dict[str, Any]]] = None,
    before_dispatch: Optional[Callable[[AudiobookTask, str], None]] = None,
    commit_result: bool = True,
) -> Tuple[AudiobookTask, Any]:
    normalized_chapter_ids = [chapter_id for chapter_id in dict.fromkeys(chapter_ids or []) if chapter_id is not None]
    if not normalized_chapter_ids:
        raise ValueError("chapter_ids 不能为空")

    if job_type not in {"full", "script_only", "audio_from_scripts"}:
        raise ValueError(f"不支持的 audiobook job_type: {job_type}")

    task_record = AudiobookTaskRepository.create_task(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=normalized_chapter_ids[0] if len(normalized_chapter_ids) == 1 else None,
        task_type=job_type,
        total_units=len(normalized_chapter_ids),
    )

    celery_task_id = str(uuid4())
    AudiobookTaskRepository.attach_celery_id(db, task_record.id, celery_task_id)
    runs = enqueue_chapter_runs(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=normalized_chapter_ids,
        run_type=job_type,
        celery_task_id=celery_task_id,
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
        generate_subtitle=generate_subtitle,
        timeline_edits_by_chapter=timeline_edits_by_chapter,
        revision_heads_by_chapter=revision_heads_by_chapter,
        task_id=task_record.id,
    )

    if before_dispatch is not None:
        before_dispatch(task_record, celery_task_id)

    # R11/P0-1（outbox）：run 即派发意图——事务提交后由 dispatcher beat /
    # 调用方显式 dispatch_pending_runs 投递（严禁在事务内 send_task：worker
    # 消费时 run 尚未提交为 dispatched，租约认领必失败）。
    if runs and commit_result:
        # 无同事务冻结要求的调用方：内部提交（提交后 run 可见为 pending）
        db.commit()

    # 兼容调用方：async_result.id = 父任务 celery_task_id（job_id/审计占位）；
    # runs 随结果返回，供调用方在统一 commit 后显式派发（dispatch_pending_runs）
    from types import SimpleNamespace as _SimpleNamespace

    async_result = _SimpleNamespace(id=celery_task_id, runs=runs)
    return task_record, async_result


def dispatch_pending_runs(db: Session, runs: List[ChapterAudioRun]) -> Dict[str, int]:
    """事务提交后逐 run 即时派发（best-effort，R11/P0-1 先落库后投递）。

    调用方在统一 commit（入队+冻结同事务）后调用；失败由 dispatcher beat
    stale-pending 扫描兜底重放，不阻塞响应。
    返回 ``{"dispatched": int, "failed": int, "unknown": int}``。
    """
    from app.services.audiobook.dispatch_service import try_dispatch_run

    summary = {"dispatched": 0, "failed": 0, "unknown": 0}
    for run in runs:
        try:
            outcome = try_dispatch_run(db, run_id=run.id)
        except Exception as exc:
            logger.error("逐 run 派发异常 run_id=%s: %s", run.id, exc)
            outcome = "unknown"
        if outcome not in summary:
            outcome = "unknown"
        summary[outcome] += 1
    if runs:
        db.commit()
    logger.info("逐 run 派发结果 runs=%d: %s", len(runs), summary)
    return summary


def update_chapter_run_state(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    run_type: str,
    status: str,
    current_stage: str,
    progress: float,
    celery_task_id: Optional[str] = None,
    total_segment_count: Optional[int] = None,
    completed_segment_count: Optional[int] = None,
    checkpoint_patch: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    run_id: Optional[int] = None,
    result_render_status: Optional[str] = None,
    result_render_detail: Optional[Dict[str, Any]] = None,
) -> None:
    # 优先按具体 run_id 定位，避免早启动、晚完成的任务覆盖新任务状态；
    # 未提供 run_id 时兼容旧行为（同类型最新 run）
    run = None
    if run_id is not None:
        run = ChapterAudioRunRepository.get_run_by_id(db, run_id=run_id)
        if run is not None and (
            run.audiobook_project_id != audiobook_project_id
            or run.chapter_id != chapter_id
        ):
            run = None
    if run is None:
        run = ChapterAudioRunRepository.get_latest_run(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type=run_type,
        )
    if (
        run is not None
        and status not in {"cancelled", "canceled"}
        and str(run.status or "").strip().lower() in {"cancelled", "canceled"}
        and not bool(run.resumable)
        and str(run.error_message or "").strip() == "chapter_output_deleted"
    ):
        logger.info(
            "章节产物已删除，忽略后台任务状态回写: run_id=%s requested_status=%s",
            getattr(run, "id", None),
            status,
        )
        return
    if not run:
        # Contract 收窄后 chapter_audio_id NOT NULL：兜底创建时解析 active ChapterAudio
        _chapter_audio = _ensure_active_chapter_audio(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        )
        run = ChapterAudioRunRepository.create_run(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type=run_type,
            # Contract 收窄后 celery_task_id NOT NULL + UNIQUE（§5.27）：
            # 调用方未携带时生成每 run 独立 uuid 占位，避免写路径撞约束
            celery_task_id=celery_task_id or str(uuid4()),
            chapter_audio_id=_chapter_audio.id,
            status=status,
            current_stage=current_stage,
            progress=progress,
        )

    if status in {"failed", "paused", "cancelled", "canceled"} and run.expires_at is None:
        run.expires_at = utc_now() + timedelta(hours=RESUME_WINDOW_HOURS)
    elif status == "completed":
        run.expires_at = None
    if status in {"cancelled", "canceled"} and error_message in {
        "chapter_audio_not_found",
        "chapter_output_deleted",
    }:
        # 章节产物已被删除时，这次 run 不应再出现在可恢复任务列表中。
        run.resumable = False

    checkpoint_json = build_run_checkpoint_document(
        db,
        run=run,
        chapter_id=chapter_id,
        audiobook_project_id=audiobook_project_id,
        status=status,
        current_stage=current_stage,
        total_segment_count=total_segment_count,
        completed_segment_count=completed_segment_count,
        checkpoint_patch=checkpoint_patch,
        error_message=error_message,
    )

    changes: Dict[str, Any] = {
        "status": status,
        "current_stage": current_stage,
        "progress": progress,
        "celery_task_id": celery_task_id or run.celery_task_id,
        "checkpoint_json": checkpoint_json,
        "error_message": error_message,
        "expires_at": run.expires_at,
    }
    temp_asset_prefix = checkpoint_json.get("temp_asset_prefix")
    if isinstance(temp_asset_prefix, str) and temp_asset_prefix:
        changes["temp_asset_prefix"] = temp_asset_prefix
    if total_segment_count is not None:
        changes["total_segment_count"] = total_segment_count
    if completed_segment_count is not None:
        changes["completed_segment_count"] = completed_segment_count
    if status == "running" and run.started_at is None:
        changes["started_at"] = utc_now()
    if status in {"completed", "failed", "cancelled", "canceled"}:
        changes["finished_at"] = utc_now()
        # 派发协议状态机收敛：终态 run 不得再留在 pending/dispatched，
        # 否则 beat 扫描（未认领重投）会把已完成 run 反复重投/再派发。
        # 收敛值沿用 cancelled（先例：synthetic_migration_run_backfill）
        if run.dispatch_status in {"pending", "dispatched"}:
            changes["dispatch_status"] = "cancelled"
    # §2.5 三维投影：本次运行结果（无论是否发布）随终态一并写入
    if result_render_status is not None:
        changes["result_render_status"] = result_render_status
    if result_render_detail is not None:
        changes["result_render_detail"] = result_render_detail
    ChapterAudioRunRepository.update_run(db, run, **changes)

    # 域 3/4（R18/P0）：run 终态时清空 worker 租约 + 按证据关账全部 pending ledger。
    # 关账只处理 pending 行（CAS 语义），与人工收敛路径不产生双写；
    # 真正的 finalizer 结算由逐 run 任务外层 / beat 扫描器在账户锁内执行。
    if status in {"completed", "failed", "cancelled", "canceled"}:
        try:
            from app.services.audiobook.dispatch_service import clear_worker_lease
            from app.services.audiobook.ledger_transition_service import (
                close_accounting_on_run_terminal,
            )

            clear_worker_lease(db, run_id=run.id)
            close_accounting_on_run_terminal(db, run_id=run.id)
        except Exception:
            logger.exception(
                "run 终态关账异常 run_id=%s status=%s", run.id, status,
            )


def _resolve_resume_task_type(
    *,
    chapter_audio: Optional[ChapterAudio],
    chapter_run,
) -> str:
    if chapter_run and chapter_run.run_type in {"full", "script_only", "audio_from_scripts"}:
        return str(chapter_run.run_type)

    script_status = str(getattr(chapter_audio, "script_status", "") or "").strip().lower()
    if chapter_audio and chapter_audio.script_json:
        if script_status == "approved":
            return "audio_from_scripts"
        return "script_only"
    return "full"


def _validate_resume_checkpoint(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    chapter_run,
    chapter_audio: Optional[ChapterAudio],
    checkpoint_source: str,
    checkpoint_data: Dict[str, Any],
    total_segments: int,
    completed_count: int,
) -> Dict[str, Any]:
    run_status = str(getattr(chapter_run, "status", "") or "").strip().lower() or None
    blockers: List[str] = []
    checks: Dict[str, Any] = {}

    if chapter_run and not bool(getattr(chapter_run, "resumable", True)):
        blockers.append("run_marked_non_resumable")

    if run_status not in {None, "", "failed", "paused", "cancelled", "canceled"}:
        blockers.append("run_status_not_resumable")

    if total_segments > 0 and completed_count >= total_segments:
        blockers.append("already_completed")

    schema_version_raw = checkpoint_data.get("schema_version")
    schema_version: Optional[int]
    try:
        schema_version = int(schema_version_raw) if schema_version_raw is not None else None
    except (TypeError, ValueError, OverflowError):
        schema_version = None

    if checkpoint_source == "chapter_audio_run":
        validation_mode = "legacy_degraded"
        if schema_version == CHECKPOINT_SCHEMA_VERSION:
            validation_mode = "strict"
    else:
        validation_mode = "none"

    checks["schema_version"] = schema_version
    if checkpoint_source == "chapter_audio_run" and schema_version not in {None, CHECKPOINT_SCHEMA_VERSION}:
        blockers.append("checkpoint_schema_version_mismatch")

    current_context = _build_resume_input_context(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        chapter_run=chapter_run,
        chapter_audio=chapter_audio,
    )

    for field_name in ("script_hash", "voice_config_hash", "audio_fx_hash", "tts_model", "output_format"):
        checkpoint_value = checkpoint_data.get(field_name)
        current_value = current_context.get(field_name)
        match = None
        if checkpoint_value is not None:
            match = bool(current_value) and checkpoint_value == current_value
            if not match:
                blockers.append(f"{field_name}_mismatch")
        checks[field_name] = {
            "checkpoint": checkpoint_value,
            "current": current_value,
            "match": match,
        }

    expires_at_raw = checkpoint_data.get("expires_at")
    expires_at = _parse_iso_datetime(expires_at_raw)
    checks["expires_at"] = expires_at_raw
    if expires_at and expires_at <= utc_now():
        blockers.append("checkpoint_expired")

    segment_asset_checks = _collect_checkpoint_temp_asset_checks(checkpoint_data)
    unique_missing_assets = list(
        dict.fromkeys(
            item["asset_ref"]
            for item in segment_asset_checks
            if item.get("exists") is False
        )
    )
    checks["segment_asset_checks"] = segment_asset_checks
    checks["missing_temp_assets"] = unique_missing_assets
    inconsistent_temp_asset_refs = _find_inconsistent_temp_asset_refs(segment_asset_checks)
    checks["inconsistent_temp_asset_refs"] = inconsistent_temp_asset_refs
    if validation_mode == "strict" and inconsistent_temp_asset_refs:
        blockers.append("inconsistent_temp_asset_refs")
    if unique_missing_assets:
        blockers.append("missing_temp_assets")

    if checkpoint_source == "none":
        blockers.append("no_checkpoint_material")

    return {
        "mode": validation_mode,
        "schema_version": schema_version,
        "blockers": list(dict.fromkeys(blockers)),
        "checks": checks,
    }


def _run_created_sort_value(chapter_run) -> float:
    created_at = getattr(chapter_run, "created_at", None)
    if isinstance(created_at, datetime):
        return created_at.timestamp()
    return 0.0


def _run_status_value(chapter_run) -> str:
    return str(getattr(chapter_run, "status", "") or "").strip().lower()


def _run_completed_count(chapter_run, checkpoint_data: Dict[str, Any]) -> int:
    completed_indices = _extract_checkpoint_segment_indices(checkpoint_data)
    completed_count = len(completed_indices)
    if chapter_run and (chapter_run.completed_segment_count or 0) > completed_count:
        completed_count = int(chapter_run.completed_segment_count or 0)
    return completed_count


def _run_total_count(chapter_run, checkpoint_data: Dict[str, Any]) -> int:
    if chapter_run and (chapter_run.total_segment_count or 0) > 0:
        return int(chapter_run.total_segment_count or 0)
    return int(checkpoint_data.get("total_segments") or 0)


def _run_has_potential_resume_material(chapter_run) -> bool:
    checkpoint_data = (
        dict(chapter_run.checkpoint_json)
        if chapter_run and isinstance(chapter_run.checkpoint_json, dict)
        else {}
    )
    completed_indices = _extract_checkpoint_segment_indices(checkpoint_data)
    cached_paths = extract_cached_segment_paths(checkpoint_data)
    completed_count = _run_completed_count(chapter_run, checkpoint_data)
    total_count = _run_total_count(chapter_run, checkpoint_data)
    status_allows_resume = _run_status_value(chapter_run) in RESUMABLE_RUN_STATUSES
    not_completed = total_count == 0 or completed_count < total_count
    return bool(
        (completed_indices or cached_paths or checkpoint_data)
        and bool(getattr(chapter_run, "resumable", True))
        and status_allows_resume
        and not_completed
    )


def _sort_resume_candidate_runs(runs: List[Any]) -> List[Any]:
    def sort_key(chapter_run) -> Tuple[int, int, float, int, int]:
        status = _run_status_value(chapter_run)
        status_priority = 2 if status in RESUMABLE_RUN_STATUSES and status else 0
        return (
            1 if _run_has_potential_resume_material(chapter_run) else 0,
            status_priority,
            _run_created_sort_value(chapter_run),
            RESUME_RUN_TYPE_PRIORITY.get(str(getattr(chapter_run, "run_type", "") or ""), 0),
            int(getattr(chapter_run, "id", 0) or 0),
        )

    return sorted(runs or [], key=sort_key, reverse=True)


def _get_resume_candidate_runs(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    run_type: Optional[str],
) -> List[Any]:
    if run_type:
        latest_run = ChapterAudioRunRepository.get_latest_run(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type=run_type,
        )
        return [latest_run] if latest_run else []

    runs = ChapterAudioRunRepository.list_runs_for_chapter(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        limit=20,
    )
    return _sort_resume_candidate_runs(runs)


def _build_generation_checkpoint_payload_for_run(
    *,
    chapter_id: int,
    chapter_audio: Optional[ChapterAudio],
    db: Session,
    audiobook_project_id: int,
    chapter_run,
) -> Dict[str, Any]:
    checkpoint_source = "none"
    checkpoint_data: Dict[str, Any] = {}
    if chapter_run and isinstance(chapter_run.checkpoint_json, dict) and chapter_run.checkpoint_json:
        checkpoint_data = dict(chapter_run.checkpoint_json)
        checkpoint_source = "chapter_audio_run"

    completed_indices = _extract_checkpoint_segment_indices(checkpoint_data)
    cached_paths = extract_cached_segment_paths(checkpoint_data)

    raw_failed_indices = checkpoint_data.get("failed_segment_indices")
    failed_segment_indices: List[int] = []
    if isinstance(raw_failed_indices, list):
        for raw_index in raw_failed_indices:
            try:
                failed_index = int(raw_index)
            except Exception:
                continue
            if failed_index >= 0:
                failed_segment_indices.append(failed_index)
        failed_segment_indices = sorted(set(failed_segment_indices))
    failed_segment_errors = checkpoint_data.get("failed_segment_errors")
    if not isinstance(failed_segment_errors, dict):
        failed_segment_errors = {}
    missing_segments = checkpoint_data.get("missing_segments")
    if not isinstance(missing_segments, list):
        missing_segments = []

    if chapter_run and (chapter_run.total_segment_count or 0) > 0:
        total_segments = int(chapter_run.total_segment_count or 0)
    elif chapter_audio and (chapter_audio.segment_count or 0) > 0:
        total_segments = int(chapter_audio.segment_count or 0)
    else:
        total_segments = int(checkpoint_data.get("total_segments") or 0)

    completed_count = len(completed_indices)
    if chapter_run and (chapter_run.completed_segment_count or 0) > completed_count:
        completed_count = int(chapter_run.completed_segment_count or 0)
    if chapter_run and chapter_run.status == "completed" and total_segments > 0:
        completed_count = total_segments

    estimated_remaining = None
    if chapter_audio and chapter_audio.generation_time and total_segments > 0 and completed_count < total_segments:
        avg_time_per_segment = chapter_audio.generation_time / total_segments
        remaining_segments = total_segments - completed_count
        estimated_remaining = avg_time_per_segment * remaining_segments

    resume_task_type = _resolve_resume_task_type(
        chapter_audio=chapter_audio,
        chapter_run=chapter_run,
    )
    has_resume_material = bool(completed_indices or cached_paths or checkpoint_data)
    run_status = str(chapter_run.status or "").strip().lower() if chapter_run and chapter_run.status else None
    status_allows_resume = run_status in {None, "", "failed", "paused", "cancelled", "canceled"}
    resume_validation = _validate_resume_checkpoint(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        chapter_run=chapter_run,
        chapter_audio=chapter_audio,
        checkpoint_source=checkpoint_source,
        checkpoint_data=checkpoint_data,
        total_segments=total_segments,
        completed_count=completed_count,
    )
    resume_blockers = resume_validation.get("blockers") or []
    can_resume = bool(
        has_resume_material
        and (total_segments == 0 or completed_count < total_segments)
        and (chapter_run.resumable if chapter_run else True)
        and status_allows_resume
        and not resume_blockers
    )

    return {
        "chapter_id": chapter_id,
        "total_segments": total_segments,
        "completed_segments": completed_count,
        "completed_segment_indices": completed_indices,
        "cached_audio_paths": cached_paths,
        "failed_segment_indices": failed_segment_indices,
        "failed_segment_errors": failed_segment_errors,
        "missing_segments": missing_segments,
        "can_resume": can_resume,
        "estimated_remaining_time": estimated_remaining,
        "run_id": chapter_run.id if chapter_run else None,
        "run_status": chapter_run.status if chapter_run else None,
        "run_type": chapter_run.run_type if chapter_run else None,
        "current_stage": chapter_run.current_stage if chapter_run else None,
        "celery_task_id": chapter_run.celery_task_id if chapter_run else None,
        "tts_model": chapter_run.tts_model if chapter_run else None,
        "output_format": chapter_run.output_format if chapter_run else None,
        "narration_style": chapter_run.narration_style if chapter_run else None,
        "narration_style_prompt": chapter_run.narration_style_prompt if chapter_run else None,
        "generate_subtitle": checkpoint_data.get("generate_subtitle", True) is not False,
        "resume_task_type": resume_task_type,
        "checkpoint_source": checkpoint_source,
        "checkpoint_schema_version": resume_validation.get("schema_version"),
        "checkpoint_updated_at": checkpoint_data.get("checkpoint_updated_at"),
        "checkpoint_expires_at": checkpoint_data.get("expires_at"),
        "resume_validation_mode": resume_validation.get("mode"),
        "resume_blockers": resume_blockers,
        "resume_validation": resume_validation.get("checks") or {},
        "checkpoint_document": checkpoint_data,
    }


def build_generation_checkpoint_payload(
    *,
    chapter_id: int,
    chapter_audio: Optional[ChapterAudio],
    run_type: Optional[str],
    db: Session,
    audiobook_project_id: int,
) -> Dict[str, Any]:
    candidate_runs = _get_resume_candidate_runs(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
    )

    if not candidate_runs:
        return _build_generation_checkpoint_payload_for_run(
            chapter_id=chapter_id,
            chapter_audio=chapter_audio,
            db=db,
            audiobook_project_id=audiobook_project_id,
            chapter_run=None,
        )

    fallback_payload: Optional[Dict[str, Any]] = None
    for candidate_run in candidate_runs:
        payload = _build_generation_checkpoint_payload_for_run(
            chapter_id=chapter_id,
            chapter_audio=chapter_audio,
            db=db,
            audiobook_project_id=audiobook_project_id,
            chapter_run=candidate_run,
        )
        if fallback_payload is None:
            fallback_payload = payload
        if payload.get("can_resume"):
            return payload

    return fallback_payload or _build_generation_checkpoint_payload_for_run(
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_run=None,
    )
