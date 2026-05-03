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

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Helper to execute async jobs from Celery."""
    return asyncio.run(coro)


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
    tracker.mark_running(self.request.id if self.request else None)
    tracker.update_stage(
        "initializing",
        0,
        max(len(chapter_ids), 1),
        "准备生成完整有声书",
        {"audiobook_project_id": audiobook_project_id},
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
    tracker.mark_running(self.request.id if self.request else None)
    tracker.update_stage(
        "script_adaptation",
        0,
        max(len(chapter_ids), 1),
        "准备剧本改写任务",
        {"audiobook_project_id": audiobook_project_id},
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
) -> None:
    """Generate audio from previously approved scripts."""
    tracker = AudiobookJobTracker(task_db_id)
    tracker.mark_running(self.request.id if self.request else None)
    tracker.update_stage(
        "tts_synthesis",
        0,
        max(len(chapter_ids), 1),
        "准备基于剧本的音频生成",
        {"audiobook_project_id": audiobook_project_id},
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
