"""
Celery tasks that wrap the asynchronous audiobook background jobs.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List

from app.celery_app import celery_app
from app.services.audiobook.job_tracker import AudiobookJobTracker

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
        from app.api.v1.audiobook import generate_audiobook_background

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
        from app.api.v1.audiobook import generate_audiobook_scripts_background

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
        from app.api.v1.audiobook import generate_audiobook_audio_from_scripts_background

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
