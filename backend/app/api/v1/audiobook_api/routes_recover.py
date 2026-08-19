"""Phase 2: 统一片段恢复端点（retry_missing / replace_voice_all / replace_voice_missing）"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request

from app.schemas.audiobook import RecoverSegmentsRequest, VoiceOverride
from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_active_chapter_audio_for_project,
    get_owned_audiobook_project,
)
from app.services.audiobook.repository import (
    ChapterAudioRunRepository,
)
from app.services.audiobook.task_support import (
    build_generation_checkpoint_payload as _build_generation_checkpoint_payload,
    build_run_checkpoint_document as _build_run_checkpoint_document,
    enqueue_audiobook_task as _enqueue_audiobook_task,
    ensure_audiobook_points_precheck_passed as _ensure_audiobook_points_precheck_passed,
    resolve_audiobook_billing_pricing_context as _resolve_audiobook_billing_pricing_context,
    safe_record_audiobook_billing_freeze as _safe_record_audiobook_billing_freeze,
)
from app.services.audiobook.task_trace import build_audiobook_trace_context
from app.services.audiobook.tts_model_ids import normalize_audiobook_tts_model
from app.services.audiobook.project_audio_config import (
    get_characters_for_model,
    set_characters_for_model,
    parse_project_audio_config,
)
from app.services.audiobook.project_audio_runtime import (
    validate_project_voice_references,
)
from app.services.points_task_precheck import (
    build_audiobook_task_points_precheck,
)
from app.utils.datetime_utils import utc_now

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)


# ─── 辅助函数 ────────────────────────────────────────────────────────────────


def _extract_missing_speakers(checkpoint: Dict[str, Any]) -> set:
    """从 checkpoint 的 missing_segments / render_plan 中提取缺失片段涉及的角色集合。"""
    speakers: set = set()
    missing_segments = checkpoint.get("missing_segments")
    if isinstance(missing_segments, list):
        for seg in missing_segments:
            if isinstance(seg, dict) and seg.get("speaker"):
                speakers.add(str(seg["speaker"]))
    # 降级：从 failed_segment_indices + render_plan 推导
    if not speakers:
        failed_indices = set(checkpoint.get("failed_segment_indices") or [])
        render_plan = checkpoint.get("render_plan") or []
        if isinstance(render_plan, list):
            for item in render_plan:
                if not isinstance(item, dict):
                    continue
                try:
                    idx = int(item.get("index", -1))
                except (TypeError, ValueError, OverflowError):
                    continue
                if idx in failed_indices and item.get("speaker"):
                    speakers.add(str(item["speaker"]))
    return speakers


def _apply_voice_overrides_to_project_config(
    project,
    *,
    tts_model: str,
    voice_overrides: Dict[str, VoiceOverride],
) -> None:
    """将 voice_overrides 持久化写入 project.audio_config（replace_voice_all 使用）。"""
    raw_config = parse_project_audio_config(project.audio_config or "")
    characters = get_characters_for_model(raw_config, tts_model)

    override_names = set(voice_overrides.keys())
    updated_names: set = set()
    for item in characters:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name not in override_names:
            continue
        override = voice_overrides[name]
        item["voice_id"] = override.voice_id
        if override.tts_model:
            item["tts_model"] = override.tts_model
        if override.reference_source:
            item["reference_source"] = override.reference_source
        if override.reference_audio_url:
            item["reference_audio_url"] = override.reference_audio_url
        if override.voice_reference_asset_id:
            item["voice_reference_asset_id"] = override.voice_reference_asset_id
        if override.voice_pool_publication_id:
            item["voice_pool_publication_id"] = override.voice_pool_publication_id
        updated_names.add(name)

    # 对 voice_overrides 中存在但 characters 列表中不存在的角色，追加新条目
    for name in override_names - updated_names:
        override = voice_overrides[name]
        new_item: Dict[str, Any] = {"name": name, "voice_id": override.voice_id}
        if override.tts_model:
            new_item["tts_model"] = override.tts_model
        if override.reference_source:
            new_item["reference_source"] = override.reference_source
        if override.reference_audio_url:
            new_item["reference_audio_url"] = override.reference_audio_url
        if override.voice_reference_asset_id:
            new_item["voice_reference_asset_id"] = override.voice_reference_asset_id
        if override.voice_pool_publication_id:
            new_item["voice_pool_publication_id"] = override.voice_pool_publication_id
        characters.append(new_item)

    set_characters_for_model(raw_config, tts_model, characters)
    project.audio_config = json.dumps(raw_config, ensure_ascii=False)


def _build_segment_voice_overrides(
    checkpoint: Dict[str, Any],
    voice_overrides: Dict[str, VoiceOverride],
) -> Dict[str, Any]:
    """为 replace_voice_missing 构建 segment_voice_overrides（源片段索引 -> 新音色信息）。

    由 checkpoint.render_plan[].source_segment_indices 把 failed_segment_indices（render chunk 索引）
    映射回源剧本片段索引集合，再关联角色 -> 新音色。
    """
    failed_indices = set(checkpoint.get("failed_segment_indices") or [])
    render_plan = checkpoint.get("render_plan") or []
    # render chunk index -> (speaker, voice_id)
    segment_overrides: Dict[str, Any] = {}
    if isinstance(render_plan, list):
        for item in render_plan:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("index", -1))
            except (TypeError, ValueError, OverflowError):
                continue
            if idx not in failed_indices:
                continue
            speaker = str(item.get("speaker") or "")
            if speaker not in voice_overrides:
                continue
            override = voice_overrides[speaker]
            source_indices = item.get("source_segment_indices") or []
            for src_idx in source_indices:
                try:
                    src_int = int(src_idx)
                except (TypeError, ValueError, OverflowError):
                    continue
                segment_overrides[str(src_int)] = {
                    "speaker": override.voice_id,
                    "original_speaker": speaker,
                    "voice_id": override.voice_id,
                    "tts_model": override.tts_model,
                    "reference_source": override.reference_source,
                    "reference_audio_url": override.reference_audio_url,
                    "voice_reference_asset_id": override.voice_reference_asset_id,
                    "voice_pool_publication_id": override.voice_pool_publication_id,
                }
    return segment_overrides


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/recover-segments")
async def recover_segments(
    audiobook_project_id: int,
    chapter_id: int,
    body: RecoverSegmentsRequest,
    raw_request: Request,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """统一片段恢复：retry_missing / replace_voice_all / replace_voice_missing"""
    db = owned.db
    project = owned.project
    current_user = owned.current_user
    action = body.action

    # ── 公共前置：获取 checkpoint 并验证片段失败状态 ──
    chapter_audio = get_active_chapter_audio_for_project(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    checkpoint_payload = _build_generation_checkpoint_payload(
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        run_type=None,
        db=db,
        audiobook_project_id=audiobook_project_id,
    )

    checkpoint_doc = checkpoint_payload.get("checkpoint_document") or {}
    failed_indices = checkpoint_doc.get("failed_segment_indices") or []
    cached_paths = checkpoint_doc.get("cached_audio_paths") or {}

    if not failed_indices or not cached_paths:
        raise HTTPException(
            status_code=400,
            detail="当前章节不处于可恢复的片段失败状态（需同时存在 failed_segment_indices 和 cached_audio_paths）",
        )

    tts_model = normalize_audiobook_tts_model(checkpoint_payload.get("tts_model"))
    output_format = checkpoint_payload.get("output_format")
    narration_style = checkpoint_payload.get("narration_style")
    narration_style_prompt = checkpoint_payload.get("narration_style_prompt")
    generate_subtitle = checkpoint_payload.get("generate_subtitle", True) is not False

    # ── 换音色动作额外校验 ──
    if action in ("replace_voice_missing", "replace_voice_all"):
        if not body.voice_overrides:
            raise HTTPException(
                status_code=400,
                detail="换音色恢复必须提供 voice_overrides（角色名 -> 新音色）",
            )
        # 验证覆盖角色确实出现在缺失片段中
        missing_speakers = _extract_missing_speakers(checkpoint_doc)
        override_names = set(body.voice_overrides.keys())
        irrelevant = override_names - missing_speakers if missing_speakers else set()
        if irrelevant and missing_speakers:
            raise HTTPException(
                status_code=400,
                detail=f"以下角色不在缺失片段中，换音色无意义: {', '.join(sorted(irrelevant))}",
            )
        # 校验新音色引用可用性
        voice_mapping_for_validation: Dict[str, Dict[str, Any]] = {}
        for name, override in body.voice_overrides.items():
            entry: Dict[str, Any] = {"voice_id": override.voice_id}
            if override.reference_source:
                entry["reference_source"] = override.reference_source
            if override.voice_reference_asset_id:
                entry["voice_reference_asset_id"] = override.voice_reference_asset_id
            if override.voice_pool_publication_id:
                entry["voice_pool_publication_id"] = override.voice_pool_publication_id
            voice_mapping_for_validation[name] = entry
        try:
            validate_project_voice_references(
                db,
                owner_user_id=int(project.user_id),
                voice_mapping=voice_mapping_for_validation,
            )
        except (ValueError, Exception) as exc:
            raise HTTPException(status_code=400, detail=f"音色引用校验失败: {exc}")

    # ── 计费 precheck ──
    billing_context = _resolve_audiobook_billing_pricing_context(
        project=project,
        tts_pricing_key=tts_model,
    )
    precheck = build_audiobook_task_points_precheck(
        db=db,
        user_id=current_user.id,
        project_id=project.id,
        project_title=project.title,
        chapter_ids=[chapter_id],
        tts_provider=tts_model,
        audio_engine_mode=billing_context.audio_engine_mode,
    )
    _ensure_audiobook_points_precheck_passed(precheck)

    # ── 分支执行 ──
    if action == "retry_missing":
        return await _handle_retry_missing(
            db=db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            chapter_audio=chapter_audio,
            checkpoint_payload=checkpoint_payload,
            tts_model=tts_model,
            output_format=output_format,
            narration_style=narration_style,
            narration_style_prompt=narration_style_prompt,
            generate_subtitle=generate_subtitle,
            billing_context=billing_context,
            precheck=precheck,
            current_user=current_user,
            raw_request=raw_request,
        )

    if action == "replace_voice_all":
        return await _handle_replace_voice_all(
            db=db,
            project=project,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            chapter_audio=chapter_audio,
            checkpoint_payload=checkpoint_payload,
            checkpoint_doc=checkpoint_doc,
            body=body,
            tts_model=tts_model,
            output_format=output_format,
            narration_style=narration_style,
            narration_style_prompt=narration_style_prompt,
            generate_subtitle=generate_subtitle,
            billing_context=billing_context,
            precheck=precheck,
            current_user=current_user,
            raw_request=raw_request,
        )

    # action == "replace_voice_missing"
    return await _handle_replace_voice_missing(
        db=db,
        project=project,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        checkpoint_payload=checkpoint_payload,
        checkpoint_doc=checkpoint_doc,
        body=body,
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
        generate_subtitle=generate_subtitle,
        billing_context=billing_context,
        precheck=precheck,
        current_user=current_user,
        raw_request=raw_request,
    )


# ─── action handlers ──────────────────────────────────────────────────────────


async def _handle_retry_missing(
    *,
    db,
    audiobook_project_id: int,
    chapter_id: int,
    chapter_audio,
    checkpoint_payload: Dict[str, Any],
    tts_model: str,
    output_format: Optional[str],
    narration_style: Optional[str],
    narration_style_prompt: Optional[str],
    generate_subtitle: bool,
    billing_context,
    precheck,
    current_user,
    raw_request: Request,
) -> Dict[str, Any]:
    """retry_missing: 同音色重试，等价 resume-generation。"""
    if not checkpoint_payload.get("can_resume"):
        blockers = checkpoint_payload.get("resume_blockers") or []
        detail = "当前不可恢复"
        if blockers:
            detail = f"当前不可恢复: {', '.join(blockers)}"
        raise HTTPException(status_code=400, detail=detail)

    resume_task_type = str(checkpoint_payload.get("resume_task_type") or "audio_from_scripts").strip().lower()

    def bind_resume_checkpoint_before_dispatch(_task_record, celery_task_id: str) -> None:
        latest_run = ChapterAudioRunRepository.get_latest_run(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type=resume_task_type,
        )
        if not latest_run or latest_run.celery_task_id != celery_task_id:
            return
        resumed_checkpoint_json = _build_run_checkpoint_document(
            db,
            run=latest_run,
            chapter_id=chapter_id,
            audiobook_project_id=audiobook_project_id,
            chapter_audio=chapter_audio,
            status=latest_run.status,
            current_stage="recover_retry_missing",
            checkpoint_patch={
                "voice_recovery_action": "retry_missing",
                "resumed_from_run_id": checkpoint_payload.get("run_id"),
                "resume_requested_at": utc_now().isoformat(),
                "source_checkpoint": checkpoint_payload.get("checkpoint_document") or {},
                "source_checkpoint_source": checkpoint_payload.get("checkpoint_source"),
                "completed_segment_indices": checkpoint_payload.get("completed_segment_indices") or [],
                "cached_audio_paths": checkpoint_payload.get("cached_audio_paths") or {},
            },
        )
        ChapterAudioRunRepository.update_run(
            db,
            latest_run,
            current_stage="recover_retry_missing",
            checkpoint_json=resumed_checkpoint_json,
        )

    # R11/P0-2：入队 + 冻结同事务（账户锁 → enqueue → freeze → 统一 commit）
    from app.services.audiobook.task_support import lock_billing_account as _lock_billing_account

    _lock_billing_account(db, current_user.id)
    _, async_result = _enqueue_audiobook_task(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=[chapter_id],
        job_type=resume_task_type,
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
        generate_subtitle=generate_subtitle,
        before_dispatch=bind_resume_checkpoint_before_dispatch,
        commit_result=False,
    )

    _safe_record_audiobook_billing_freeze(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=[chapter_id],
        raw_request=raw_request,
        tts_pricing_key=billing_context.pricing_key,
        estimated_yuan_override=precheck.estimated_yuan,
        trace_context=build_audiobook_trace_context(
            celery_task_id=str(async_result.id),
            task_type=resume_task_type,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            status="queued",
            progress=0.0,
            tts_model=tts_model,
            cost_precheck_id=precheck.cost_precheck_id,
        ),
        raise_on_error=True,
    )
    db.commit()
    # 提交后即时派发（best-effort；失败由 dispatcher beat 兜底，R11/P0-1）
    try:
        from app.services.audiobook.task_support import (
            dispatch_pending_runs as _dispatch_pending_runs,
        )

        _dispatch_pending_runs(db, async_result.runs)
    except Exception as _exc:
        logger.warning("提交后派发失败（dispatcher 兜底）: %s", _exc)

    logger.info(
        "Recover retry_missing queued: audiobook_project_id=%s chapter_id=%s job_id=%s",
        audiobook_project_id,
        chapter_id,
        async_result.id,
    )
    return {
        "message": "同音色重试任务已进入队列",
        "action": "retry_missing",
        "job_id": async_result.id,
        "resumed_from_run_id": checkpoint_payload.get("run_id"),
    }


async def _handle_replace_voice_all(
    *,
    db,
    project,
    audiobook_project_id: int,
    chapter_id: int,
    chapter_audio,
    checkpoint_payload: Dict[str, Any],
    checkpoint_doc: Dict[str, Any],
    body: RecoverSegmentsRequest,
    tts_model: str,
    output_format: Optional[str],
    narration_style: Optional[str],
    narration_style_prompt: Optional[str],
    generate_subtitle: bool,
    billing_context,
    precheck,
    current_user,
    raw_request: Request,
) -> Dict[str, Any]:
    """replace_voice_all: 持久化新音色配置 → 新 run 嵌入 source_checkpoint → cache_key 机制自动重生成。"""
    # 1. 持久化音色配置
    _apply_voice_overrides_to_project_config(
        project,
        tts_model=tts_model,
        voice_overrides=body.voice_overrides,
    )
    db.commit()

    # 2. 入队新 run，嵌入旧 checkpoint 为 source_checkpoint
    source_run_id = checkpoint_payload.get("run_id")

    def bind_voice_recovery_checkpoint(_task_record, celery_task_id: str) -> None:
        latest_run = ChapterAudioRunRepository.get_latest_run(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type="audio_from_scripts",
        )
        if not latest_run or latest_run.celery_task_id != celery_task_id:
            return
        recovery_checkpoint_json = _build_run_checkpoint_document(
            db,
            run=latest_run,
            chapter_id=chapter_id,
            audiobook_project_id=audiobook_project_id,
            chapter_audio=chapter_audio,
            status=latest_run.status,
            current_stage="recover_replace_voice_all",
            checkpoint_patch={
                "voice_recovery_action": "replace_voice_all",
                "voice_recovery_overrides": {
                    name: {"voice_id": ov.voice_id, "tts_model": ov.tts_model}
                    for name, ov in body.voice_overrides.items()
                },
                "resumed_from_run_id": source_run_id,
                "resume_requested_at": utc_now().isoformat(),
                "source_checkpoint": checkpoint_doc,
                "source_checkpoint_source": checkpoint_payload.get("checkpoint_source"),
                "completed_segment_indices": checkpoint_payload.get("completed_segment_indices") or [],
                "cached_audio_paths": checkpoint_payload.get("cached_audio_paths") or {},
            },
        )
        ChapterAudioRunRepository.update_run(
            db,
            latest_run,
            current_stage="recover_replace_voice_all",
            checkpoint_json=recovery_checkpoint_json,
        )

    # R11/P0-2：入队 + 冻结同事务（账户锁 → enqueue → freeze → 统一 commit）
    from app.services.audiobook.task_support import lock_billing_account as _lock_billing_account

    _lock_billing_account(db, current_user.id)
    _, async_result = _enqueue_audiobook_task(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=[chapter_id],
        job_type="audio_from_scripts",
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
        generate_subtitle=generate_subtitle,
        before_dispatch=bind_voice_recovery_checkpoint,
        commit_result=False,
    )

    _safe_record_audiobook_billing_freeze(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=[chapter_id],
        raw_request=raw_request,
        tts_pricing_key=billing_context.pricing_key,
        estimated_yuan_override=precheck.estimated_yuan,
        trace_context=build_audiobook_trace_context(
            celery_task_id=str(async_result.id),
            task_type="audio_from_scripts",
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            status="queued",
            progress=0.0,
            tts_model=tts_model,
            cost_precheck_id=precheck.cost_precheck_id,
        ),
        raise_on_error=True,
    )
    db.commit()
    # 提交后即时派发（best-effort；失败由 dispatcher beat 兜底，R11/P0-1）
    try:
        from app.services.audiobook.task_support import (
            dispatch_pending_runs as _dispatch_pending_runs,
        )

        _dispatch_pending_runs(db, async_result.runs)
    except Exception as _exc:
        logger.warning("提交后派发失败（dispatcher 兜底）: %s", _exc)

    logger.info(
        "Recover replace_voice_all queued: audiobook_project_id=%s chapter_id=%s overrides=%s job_id=%s",
        audiobook_project_id,
        chapter_id,
        list(body.voice_overrides.keys()),
        async_result.id,
    )
    return {
        "message": "换音色全角色重生成任务已进入队列",
        "action": "replace_voice_all",
        "job_id": async_result.id,
        "voice_overrides_applied": list(body.voice_overrides.keys()),
        "resumed_from_run_id": source_run_id,
    }


async def _handle_replace_voice_missing(
    *,
    db,
    project,
    audiobook_project_id: int,
    chapter_id: int,
    chapter_audio,
    checkpoint_payload: Dict[str, Any],
    checkpoint_doc: Dict[str, Any],
    body: RecoverSegmentsRequest,
    tts_model: str,
    output_format: Optional[str],
    narration_style: Optional[str],
    narration_style_prompt: Optional[str],
    generate_subtitle: bool,
    billing_context,
    precheck,
    current_user,
    raw_request: Request,
) -> Dict[str, Any]:
    """replace_voice_missing: 仅缺失片段临时换音色（不持久化全局配置）。"""
    # 构建 segment_voice_overrides（源片段索引 -> 新音色信息）
    segment_voice_overrides = _build_segment_voice_overrides(checkpoint_doc, body.voice_overrides)
    if not segment_voice_overrides:
        raise HTTPException(
            status_code=400,
            detail="无法从 checkpoint render_plan 映射缺失片段到源剧本索引，请改用 replace_voice_all",
        )

    source_run_id = checkpoint_payload.get("run_id")

    def bind_voice_recovery_checkpoint(_task_record, celery_task_id: str) -> None:
        latest_run = ChapterAudioRunRepository.get_latest_run(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type="audio_from_scripts",
        )
        if not latest_run or latest_run.celery_task_id != celery_task_id:
            return
        recovery_checkpoint_json = _build_run_checkpoint_document(
            db,
            run=latest_run,
            chapter_id=chapter_id,
            audiobook_project_id=audiobook_project_id,
            chapter_audio=chapter_audio,
            status=latest_run.status,
            current_stage="recover_replace_voice_missing",
            checkpoint_patch={
                "voice_recovery_action": "replace_voice_missing",
                "temporary_voice_substitution": True,
                "voice_recovery_overrides": {
                    name: {"voice_id": ov.voice_id, "tts_model": ov.tts_model}
                    for name, ov in body.voice_overrides.items()
                },
                "segment_voice_overrides": segment_voice_overrides,
                "resumed_from_run_id": source_run_id,
                "resume_requested_at": utc_now().isoformat(),
                "source_checkpoint": checkpoint_doc,
                "source_checkpoint_source": checkpoint_payload.get("checkpoint_source"),
                "completed_segment_indices": checkpoint_payload.get("completed_segment_indices") or [],
                "cached_audio_paths": checkpoint_payload.get("cached_audio_paths") or {},
            },
        )
        ChapterAudioRunRepository.update_run(
            db,
            latest_run,
            current_stage="recover_replace_voice_missing",
            checkpoint_json=recovery_checkpoint_json,
        )

    # R11/P0-2：入队 + 冻结同事务（账户锁 → enqueue → freeze → 统一 commit）
    from app.services.audiobook.task_support import lock_billing_account as _lock_billing_account

    _lock_billing_account(db, current_user.id)
    _, async_result = _enqueue_audiobook_task(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=[chapter_id],
        job_type="audio_from_scripts",
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
        generate_subtitle=generate_subtitle,
        before_dispatch=bind_voice_recovery_checkpoint,
        commit_result=False,
    )

    _safe_record_audiobook_billing_freeze(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=[chapter_id],
        raw_request=raw_request,
        tts_pricing_key=billing_context.pricing_key,
        estimated_yuan_override=precheck.estimated_yuan,
        trace_context=build_audiobook_trace_context(
            celery_task_id=str(async_result.id),
            task_type="audio_from_scripts",
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            status="queued",
            progress=0.0,
            tts_model=tts_model,
            cost_precheck_id=precheck.cost_precheck_id,
        ),
        raise_on_error=True,
    )
    db.commit()
    # 提交后即时派发（best-effort；失败由 dispatcher beat 兜底，R11/P0-1）
    try:
        from app.services.audiobook.task_support import (
            dispatch_pending_runs as _dispatch_pending_runs,
        )

        _dispatch_pending_runs(db, async_result.runs)
    except Exception as _exc:
        logger.warning("提交后派发失败（dispatcher 兜底）: %s", _exc)

    logger.info(
        "Recover replace_voice_missing queued: audiobook_project_id=%s chapter_id=%s overrides=%s segments=%s job_id=%s",
        audiobook_project_id,
        chapter_id,
        list(body.voice_overrides.keys()),
        list(segment_voice_overrides.keys()),
        async_result.id,
    )
    return {
        "message": "缺失片段临时换音色任务已进入队列（同角色可能出现两种声音）",
        "action": "replace_voice_missing",
        "job_id": async_result.id,
        "voice_overrides_applied": list(body.voice_overrides.keys()),
        "affected_segment_indices": sorted(segment_voice_overrides.keys(), key=lambda x: int(x)),
        "temporary_voice_substitution": True,
        "resumed_from_run_id": source_run_id,
    }
