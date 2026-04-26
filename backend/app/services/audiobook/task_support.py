from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.models.audiobook import ChapterAudio
from app.models.audiobook_task import AudiobookTask
from app.schemas.audiobook import AudiobookTaskStatus
from app.services.audiobook.repository import AudiobookTaskRepository, ChapterAudioRunRepository
from app.services.audiobook.temp_segment_store import extract_cached_segment_paths, temp_segment_asset_exists
from app.services.points_task_precheck import build_task_points_precheck_error_detail
from app.utils.datetime_utils import utc_now

CHECKPOINT_SCHEMA_VERSION = 1
RESUME_WINDOW_HOURS = 72


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
    )


def _safe_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
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
    except Exception:
        return None


def _checkpoint_path_exists(path_value: str) -> bool:
    return temp_segment_asset_exists(path_value)


def _normalize_segment_index(value: Any) -> Optional[int]:
    try:
        index = int(value)
    except Exception:
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
    from app.services.audiobook.project_audio_config import (
        get_audio_fx,
        get_characters_for_model,
        parse_project_audio_config,
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
    resolved_narration_style = (
        getattr(chapter_run, "narration_style", None)
        or getattr(chapter_audio, "narration_style", None)
    )
    resolved_narration_style_prompt = (
        getattr(chapter_run, "narration_style_prompt", None)
        or getattr(chapter_audio, "narration_style_prompt", None)
    )

    project_audio_config = (
        parse_project_audio_config(project.audio_config or "")
        if project and project.audio_config
        else {}
    )
    voice_config_payload = {
        "model": resolved_tts_model,
        "characters": get_characters_for_model(project_audio_config, resolved_tts_model),
    }
    audio_fx_payload = get_audio_fx(project_audio_config) or {}

    run_type = str(getattr(chapter_run, "run_type", "") or "").strip().lower()
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
) -> None:
    normalized_ids = [chapter_id for chapter_id in dict.fromkeys(chapter_ids or []) if chapter_id is not None]
    if not normalized_ids:
        return
    runs = ChapterAudioRunRepository.create_runs(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=normalized_ids,
        run_type=run_type,
        celery_task_id=celery_task_id,
        status="queued",
        current_stage="queued",
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
        resumable=True,
    )
    for run in runs:
        run.checkpoint_json = build_run_checkpoint_document(
            db,
            run=run,
            chapter_id=run.chapter_id,
            audiobook_project_id=audiobook_project_id,
            status=run.status,
            current_stage=run.current_stage,
        )
        db.add(run)
    if runs:
        db.commit()


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
    force_regenerate_script: bool = False,
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

    if job_type == "script_only":
        signature = celery_app.signature(
            "audiobook.run_script_only",
            args=[
                task_record.id,
                audiobook_project_id,
                normalized_chapter_ids,
                tts_model,
                force_regenerate_script,
            ],
        )
    elif job_type == "audio_from_scripts":
        signature = celery_app.signature(
            "audiobook.run_audio_from_scripts",
            args=[
                task_record.id,
                audiobook_project_id,
                normalized_chapter_ids,
                tts_model,
            ],
        )
    else:
        signature = celery_app.signature(
            "audiobook.run_full",
            args=[
                task_record.id,
                audiobook_project_id,
                normalized_chapter_ids,
                tts_model,
            ],
        )

    async_result = signature.delay()
    AudiobookTaskRepository.attach_celery_id(db, task_record.id, async_result.id)
    enqueue_chapter_runs(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=normalized_chapter_ids,
        run_type=job_type,
        celery_task_id=async_result.id,
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
    )
    return task_record, async_result


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
) -> None:
    run = ChapterAudioRunRepository.get_latest_run(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
    )
    if not run:
        run = ChapterAudioRunRepository.create_run(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type=run_type,
            celery_task_id=celery_task_id,
            status=status,
            current_stage=current_stage,
            progress=progress,
        )

    if status in {"failed", "paused", "cancelled", "canceled"} and run.expires_at is None:
        run.expires_at = utc_now() + timedelta(hours=RESUME_WINDOW_HOURS)
    elif status == "completed":
        run.expires_at = None

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
    if status in {"completed", "failed"}:
        changes["finished_at"] = utc_now()
    ChapterAudioRunRepository.update_run(db, run, **changes)


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
    except Exception:
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

    missing_temp_assets: List[str] = []
    cached_audio_paths = checkpoint_data.get("cached_audio_paths") or {}
    if isinstance(cached_audio_paths, dict):
        for path_value in cached_audio_paths.values():
            if isinstance(path_value, str) and path_value and not _checkpoint_path_exists(path_value):
                missing_temp_assets.append(path_value)

    segments = checkpoint_data.get("segments") or {}
    if isinstance(segments, dict):
        for segment_payload in segments.values():
            if not isinstance(segment_payload, dict):
                continue
            temp_object_key = segment_payload.get("temp_object_key")
            if isinstance(temp_object_key, str) and temp_object_key and not _checkpoint_path_exists(temp_object_key):
                missing_temp_assets.append(temp_object_key)

    unique_missing_assets = list(dict.fromkeys(missing_temp_assets))
    checks["missing_temp_assets"] = unique_missing_assets
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


def build_generation_checkpoint_payload(
    *,
    chapter_id: int,
    chapter_audio: Optional[ChapterAudio],
    run_type: Optional[str],
    db: Session,
    audiobook_project_id: int,
) -> Dict[str, Any]:
    chapter_run = ChapterAudioRunRepository.get_latest_run(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
    )

    checkpoint_source = "none"
    checkpoint_data: Dict[str, Any] = {}
    if chapter_run and isinstance(chapter_run.checkpoint_json, dict) and chapter_run.checkpoint_json:
        checkpoint_data = dict(chapter_run.checkpoint_json)
        checkpoint_source = "chapter_audio_run"

    completed_indices = _extract_checkpoint_segment_indices(checkpoint_data)
    cached_paths = extract_cached_segment_paths(checkpoint_data)

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
