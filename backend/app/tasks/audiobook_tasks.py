"""
Celery tasks that wrap the asynchronous audiobook background jobs.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.celery_app import celery_app
from app.services.audiobook.job_tracker import AudiobookJobTracker
from app.services.audiobook.project_export_jobs import (
    PROJECT_EXPORT_STAGE,
    build_project_export_task_detail,
)
from app.services.audiobook.project_exporter import AudiobookExportError
from app.services.audiobook.prompt_audio_transcript_queue import (
    PROMPT_AUDIO_ASR_TRANSCRIPT_COMPLETED_STAGE,
    PROMPT_AUDIO_ASR_TRANSCRIPT_PROVIDER_CHECK_STAGE,
    PROMPT_AUDIO_ASR_TRANSCRIPT_SKIPPED_STAGE,
    build_prompt_audio_transcript_task_detail,
)
from app.services.audiobook.task_trace import build_audiobook_trace_context

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Helper to execute async jobs from Celery."""
    return asyncio.run(coro)


def _build_project_export_trace_context(
    *,
    task_db_id: int,
    celery_task_id: Optional[str],
    audiobook_project_id: int,
    export_type: str,
    status: str,
    progress: float,
) -> Dict[str, Any]:
    return build_audiobook_trace_context(
        celery_task_id=celery_task_id,
        task_db_id=task_db_id,
        task_type=f"export_{export_type}",
        audiobook_project_id=audiobook_project_id,
        stage=PROJECT_EXPORT_STAGE,
        status=status,
        progress=progress,
    )


def _build_initial_generation_task_detail(
    *,
    task_db_id: int,
    celery_task_id: Optional[str],
    task_type: str,
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str,
    stage: str,
    status: str,
    progress: float,
) -> Dict[str, Any]:
    return {
        **build_audiobook_trace_context(
            celery_task_id=celery_task_id,
            task_db_id=task_db_id,
            task_type=task_type,
            audiobook_project_id=audiobook_project_id,
            stage=stage,
            status=status,
            progress=progress,
            tts_model=tts_model,
        ),
        "chapter_ids": list(chapter_ids or []),
        "chapter_total": len(chapter_ids or []),
    }


@celery_app.task(name="audiobook.run_full", bind=True)
def run_full_audiobook_task(
    self,
    task_db_id: int,
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str,
) -> None:
    """Full pipeline: generate audio directly from chapter content."""
    tracker = AudiobookJobTracker(task_db_id)
    celery_task_id = self.request.id if self.request else None
    tracker.mark_running(celery_task_id)
    tracker.update_stage(
        "initializing",
        0,
        max(len(chapter_ids), 1),
        "准备生成完整有声书",
        _build_initial_generation_task_detail(
            task_db_id=task_db_id,
            celery_task_id=celery_task_id,
            task_type="full",
            audiobook_project_id=audiobook_project_id,
            chapter_ids=chapter_ids,
            tts_model=tts_model,
            stage="initializing",
            status="running",
            progress=0.0,
        ),
    )
    try:
        from app.services.audiobook.background_jobs import generate_audiobook_background

        _run_async(
            generate_audiobook_background(
                audiobook_project_id=audiobook_project_id,
                chapter_ids=chapter_ids,
                tts_model=tts_model,
                tracker=tracker,
            )
        )
        tracker.mark_completed()
    except Exception as exc:  # pragma: no cover - safety
        logger.exception("Full audiobook task failed: %s", exc)
        tracker.mark_failed(str(exc))
        raise


@celery_app.task(name="audiobook.run_script_only", bind=True)
def run_script_generation_task(
    self,
    task_db_id: int,
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str,
    force_regenerate: bool,
) -> None:
    """Generate narrations/scripts only."""
    tracker = AudiobookJobTracker(task_db_id)
    celery_task_id = self.request.id if self.request else None
    tracker.mark_running(celery_task_id)
    tracker.update_stage(
        "script_adaptation",
        0,
        max(len(chapter_ids), 1),
        "准备剧本改写任务",
        _build_initial_generation_task_detail(
            task_db_id=task_db_id,
            celery_task_id=celery_task_id,
            task_type="script_only",
            audiobook_project_id=audiobook_project_id,
            chapter_ids=chapter_ids,
            tts_model=tts_model,
            stage="script_adaptation",
            status="running",
            progress=0.0,
        ),
    )
    try:
        from app.services.audiobook.background_jobs import (
            generate_audiobook_scripts_background,
        )

        _run_async(
            generate_audiobook_scripts_background(
                audiobook_project_id=audiobook_project_id,
                chapter_ids=chapter_ids,
                tts_model=tts_model,
                force_regenerate=force_regenerate,
                tracker=tracker,
            )
        )
        tracker.mark_completed()
    except Exception as exc:  # pragma: no cover
        logger.exception("Script generation task failed: %s", exc)
        tracker.mark_failed(str(exc))
        raise


@celery_app.task(name="audiobook.run_audio_from_scripts", bind=True)
def run_audio_from_scripts_task(
    self,
    task_db_id: int,
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str,
    timeline_edits_by_chapter: Optional[Dict[int, Dict[str, Dict[str, float]]]] = None,
) -> None:
    """Generate audio from previously approved scripts."""
    tracker = AudiobookJobTracker(task_db_id)
    celery_task_id = self.request.id if self.request else None
    tracker.mark_running(celery_task_id)
    tracker.update_stage(
        "tts_synthesis",
        0,
        max(len(chapter_ids), 1),
        "准备基于剧本的音频生成",
        _build_initial_generation_task_detail(
            task_db_id=task_db_id,
            celery_task_id=celery_task_id,
            task_type="audio_from_scripts",
            audiobook_project_id=audiobook_project_id,
            chapter_ids=chapter_ids,
            tts_model=tts_model,
            stage="tts_synthesis",
            status="running",
            progress=0.0,
        ),
    )
    try:
        from app.services.audiobook.background_jobs import (
            generate_audiobook_audio_from_scripts_background,
        )

        _run_async(
            generate_audiobook_audio_from_scripts_background(
                audiobook_project_id=audiobook_project_id,
                chapter_ids=chapter_ids,
                tts_model=tts_model,
                timeline_edits_by_chapter=timeline_edits_by_chapter or {},
                tracker=tracker,
            )
        )
        tracker.mark_completed()
    except Exception as exc:  # pragma: no cover
        logger.exception("Audio-from-scripts task failed: %s", exc)
        tracker.mark_failed(str(exc))
        raise


def _run_project_export_task(
    *,
    task_db_id: int,
    celery_task_id: Optional[str],
    audiobook_project_id: int,
    export_type: str,
    metadata: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    tracker = AudiobookJobTracker(task_db_id)
    tracker.mark_running(celery_task_id)
    start_message = "正在导出整本 M4B" if export_type == "m4b" else "正在导出 Audacity ZIP"
    tracker.update_stage(
        PROJECT_EXPORT_STAGE,
        0,
        1,
        start_message,
        build_project_export_task_detail(
            audiobook_project_id=audiobook_project_id,
            export_type=export_type,
            status="running",
            progress=0.05,
            message=start_message,
            force=force,
            metadata=metadata,
            trace_context=_build_project_export_trace_context(
                task_db_id=task_db_id,
                celery_task_id=celery_task_id,
                audiobook_project_id=audiobook_project_id,
                export_type=export_type,
                status="running",
                progress=0.05,
            ),
        ),
    )

    try:
        from app.db.base import SessionLocal
        from app.services.audiobook.project_export_jobs import (
            build_project_export_download_url,
            load_project_export_context,
        )
        from app.services.audiobook.project_exporter import (
            build_project_audacity_export,
            build_project_m4b_export,
        )

        db = SessionLocal()
        try:
            audiobook_project, project = load_project_export_context(
                db,
                audiobook_project_id=audiobook_project_id,
            )
            if export_type == "m4b":
                result = build_project_m4b_export(
                    db,
                    audiobook_project=audiobook_project,
                    project=project,
                    metadata=metadata or {},
                    force=force,
                )
            else:
                result = build_project_audacity_export(
                    db,
                    audiobook_project=audiobook_project,
                    project=project,
                    force=force,
                )
        finally:
            db.close()

        result = {
            **result,
            "download_url": build_project_export_download_url(
                audiobook_project_id,
                export_type,
            ),
        }
        finish_message = "整本 M4B 导出完成" if export_type == "m4b" else "Audacity ZIP 导出完成"
        finish_detail = build_project_export_task_detail(
            audiobook_project_id=audiobook_project_id,
            export_type=export_type,
            status="completed",
            progress=1.0,
            message=finish_message,
            force=force,
            metadata=metadata,
            result=result,
            trace_context=_build_project_export_trace_context(
                task_db_id=task_db_id,
                celery_task_id=celery_task_id,
                audiobook_project_id=audiobook_project_id,
                export_type=export_type,
                status="completed",
                progress=1.0,
            ),
        )
        tracker.update_stage(PROJECT_EXPORT_STAGE, 1, 1, finish_message, finish_detail)
        tracker.mark_completed(finish_detail)
        return result
    except AudiobookExportError as exc:
        message = str(exc)
        logger.exception("Project %s export failed: %s", export_type, message)
        tracker.update_stage(
            PROJECT_EXPORT_STAGE,
            0,
            1,
            message,
            build_project_export_task_detail(
                audiobook_project_id=audiobook_project_id,
                export_type=export_type,
                status="failed",
                progress=0.0,
                message=message,
                force=force,
                metadata=metadata,
                error_message=message,
                trace_context=_build_project_export_trace_context(
                    task_db_id=task_db_id,
                    celery_task_id=celery_task_id,
                    audiobook_project_id=audiobook_project_id,
                    export_type=export_type,
                    status="failed",
                    progress=0.0,
                ),
            ),
        )
        tracker.mark_failed(f"{exc.code}: {message}")
        raise
    except Exception as exc:  # pragma: no cover - safety
        message = str(exc)
        logger.exception("Project %s export task failed: %s", export_type, message)
        tracker.update_stage(
            PROJECT_EXPORT_STAGE,
            0,
            1,
            message,
            build_project_export_task_detail(
                audiobook_project_id=audiobook_project_id,
                export_type=export_type,
                status="failed",
                progress=0.0,
                message=message,
                force=force,
                metadata=metadata,
                error_message=message,
                trace_context=_build_project_export_trace_context(
                    task_db_id=task_db_id,
                    celery_task_id=celery_task_id,
                    audiobook_project_id=audiobook_project_id,
                    export_type=export_type,
                    status="failed",
                    progress=0.0,
                ),
            ),
        )
        tracker.mark_failed(message)
        raise


@celery_app.task(name="audiobook.export_m4b", bind=True)
def export_project_m4b_task(
    self,
    task_db_id: int,
    audiobook_project_id: int,
    metadata: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Export a whole audiobook project to M4B in the background."""
    return _run_project_export_task(
        task_db_id=task_db_id,
        celery_task_id=self.request.id if self.request else None,
        audiobook_project_id=audiobook_project_id,
        export_type="m4b",
        metadata=metadata,
        force=force,
    )


@celery_app.task(name="audiobook.export_audacity", bind=True)
def export_project_audacity_task(
    self,
    task_db_id: int,
    audiobook_project_id: int,
    force: bool = False,
) -> Dict[str, Any]:
    """Export a whole audiobook project to an Audacity ZIP in the background."""
    return _run_project_export_task(
        task_db_id=task_db_id,
        celery_task_id=self.request.id if self.request else None,
        audiobook_project_id=audiobook_project_id,
        export_type="audacity",
        force=force,
    )


def _run_prompt_audio_asr_transcript_task_body(
    *,
    task_db_id: int,
    celery_task_id: Optional[str],
    audiobook_project_id: int,
    chapter_audio_id: int,
    provider: Optional[str] = None,
    target_model: Optional[str] = None,
    confirm_cost: bool = False,
) -> Dict[str, Any]:
    tracker = AudiobookJobTracker(task_db_id)

    from app.db.base import SessionLocal
    from app.services.audiobook.prompt_audio_asr_provider import create_prompt_audio_asr_provider
    from app.services.audiobook.prompt_audio_transcript_runner import (
        execute_prompt_audio_transcript,
        normalize_prompt_audio_transcript_error,
    )
    from app.services.audiobook.repository import ChapterAudioRepository

    db = SessionLocal()
    chapter_id: Optional[int] = None
    try:
        chapter_audio = ChapterAudioRepository.get_active_by_id(db, chapter_audio_id)
        chapter_id = chapter_audio.chapter_id if chapter_audio else None

        start_message = "正在检查 ASR 转写配置"
        tracker.update_stage(
            PROMPT_AUDIO_ASR_TRANSCRIPT_PROVIDER_CHECK_STAGE,
            0,
            1,
            start_message,
            build_prompt_audio_transcript_task_detail(
                task_db_id=task_db_id,
                celery_task_id=celery_task_id,
                audiobook_project_id=audiobook_project_id,
                chapter_audio_id=chapter_audio_id,
                chapter_id=chapter_id,
                status="running",
                stage=PROMPT_AUDIO_ASR_TRANSCRIPT_PROVIDER_CHECK_STAGE,
                progress=0.0,
                message=start_message,
                provider=provider,
                target_model=target_model,
                provider_call_allowed=confirm_cost,
            ),
        )

        if chapter_audio is None:
            raise RuntimeError("chapter_audio_not_found")

        result = execute_prompt_audio_transcript(
            db,
            chapter_audio=chapter_audio,
            provider=create_prompt_audio_asr_provider(provider),
            target_model=target_model,
            provider_call_allowed=confirm_cost,
        )
    except Exception as exc:
        error = normalize_prompt_audio_transcript_error(exc)
        if error["reason"] in {"asr_provider_not_configured", "asr_cost_not_confirmed"}:
            finish_message = error["message"]
            detail = build_prompt_audio_transcript_task_detail(
                task_db_id=task_db_id,
                celery_task_id=celery_task_id,
                audiobook_project_id=audiobook_project_id,
                chapter_audio_id=chapter_audio_id,
                chapter_id=chapter_id,
                status="completed",
                stage=PROMPT_AUDIO_ASR_TRANSCRIPT_SKIPPED_STAGE,
                progress=1.0,
                message=finish_message,
                reason=error["reason"],
                provider=provider,
                target_model=target_model,
                provider_call_allowed=confirm_cost,
            )
            detail["transcript_status"] = "skipped"
            detail["provider_configured"] = error["reason"] != "asr_provider_not_configured"
            tracker.update_stage(
                PROMPT_AUDIO_ASR_TRANSCRIPT_SKIPPED_STAGE,
                1,
                1,
                finish_message,
                detail,
            )
            tracker.mark_completed(detail)
            return detail

        finish_message = error["message"]
        detail = build_prompt_audio_transcript_task_detail(
            task_db_id=task_db_id,
            celery_task_id=celery_task_id,
            audiobook_project_id=audiobook_project_id,
            chapter_audio_id=chapter_audio_id,
            chapter_id=chapter_id,
            status="failed",
            stage="asr_transcript_failed",
            progress=1.0,
            message=finish_message,
            reason=error["reason"],
            provider=provider,
            target_model=target_model,
            provider_call_allowed=confirm_cost,
        )
        detail["transcript_status"] = "failed"
        tracker.update_stage("asr_transcript_failed", 1, 1, finish_message, detail)
        tracker.mark_failed(f"{error['reason']}: {finish_message}")
        raise
    finally:
        db.close()

    finish_message = "ASR 转写完成，已回填人工验收辅助字段"
    detail = build_prompt_audio_transcript_task_detail(
        task_db_id=task_db_id,
        celery_task_id=celery_task_id,
        audiobook_project_id=audiobook_project_id,
        chapter_audio_id=chapter_audio_id,
        chapter_id=chapter_id,
        status="completed",
        stage=PROMPT_AUDIO_ASR_TRANSCRIPT_COMPLETED_STAGE,
        progress=1.0,
        message=finish_message,
        provider=str(result.get("provider") or provider or ""),
        target_model=str(result.get("model") or target_model or ""),
        provider_call_allowed=confirm_cost,
    )
    detail.update(result)
    tracker.update_stage(
        PROMPT_AUDIO_ASR_TRANSCRIPT_COMPLETED_STAGE,
        1,
        1,
        finish_message,
        detail,
    )
    tracker.mark_completed(detail)
    return detail


@celery_app.task(name="audiobook.prompt_audio_asr_transcript", bind=True)
def run_prompt_audio_asr_transcript_task(
    self,
    task_db_id: int,
    audiobook_project_id: int,
    chapter_audio_id: int,
    provider: Optional[str] = None,
    target_model: Optional[str] = None,
    confirm_cost: bool = False,
) -> Dict[str, Any]:
    """Run a manual prompt/audio ASR transcript job and write review assistance."""
    tracker = AudiobookJobTracker(task_db_id)
    celery_task_id = self.request.id if self.request else None
    tracker.mark_running(celery_task_id)
    return _run_prompt_audio_asr_transcript_task_body(
        task_db_id=task_db_id,
        celery_task_id=celery_task_id,
        audiobook_project_id=audiobook_project_id,
        chapter_audio_id=chapter_audio_id,
        provider=provider,
        target_model=target_model,
        confirm_cost=confirm_cost,
    )


@celery_app.task(name="audiobook.cleanup_expired_temp_assets")
def cleanup_expired_temp_assets_task(limit: int = 100) -> dict:
    """Clean expired resumable temp segment assets and invalidate their checkpoints."""
    from app.services.audiobook.temp_segment_janitor import cleanup_expired_temp_segments

    result = cleanup_expired_temp_segments(limit=limit)
    logger.info(
        "Expired audiobook temp assets cleanup finished: runs=%s, files=%s",
        result.get("processed_runs"),
        result.get("removed_temp_files"),
    )
    return result
