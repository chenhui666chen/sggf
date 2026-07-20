from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.models.audiobook import ChapterAudio
from app.services.audiobook.repository import AudiobookTaskRepository
from app.services.audiobook.task_trace import build_audiobook_trace_context

PROMPT_AUDIO_ASR_TRANSCRIPT_TASK_TYPE = "prompt_audio_asr_transcript"
PROMPT_AUDIO_ASR_TRANSCRIPT_TASK_NAME = "audiobook.prompt_audio_asr_transcript"
PROMPT_AUDIO_ASR_TRANSCRIPT_QUEUED_STAGE = "asr_transcript_queued"
PROMPT_AUDIO_ASR_TRANSCRIPT_PROVIDER_CHECK_STAGE = "asr_transcript_provider_check"
PROMPT_AUDIO_ASR_TRANSCRIPT_SKIPPED_STAGE = "asr_transcript_skipped"
PROMPT_AUDIO_ASR_TRANSCRIPT_COMPLETED_STAGE = "asr_transcript_completed"
PROMPT_AUDIO_ASR_TRANSCRIPT_QUEUED_MESSAGE = "ASR 转写任务已进入队列"


def build_prompt_audio_transcript_task_detail(
    *,
    task_db_id: Optional[int],
    celery_task_id: Optional[str],
    audiobook_project_id: int,
    chapter_audio_id: int,
    chapter_id: Optional[int],
    status: str,
    stage: str,
    progress: float,
    message: str,
    reason: Optional[str] = None,
    provider: Optional[str] = None,
    target_model: Optional[str] = None,
    provider_call_allowed: bool = False,
) -> Dict[str, Any]:
    detail: Dict[str, Any] = {
        **build_audiobook_trace_context(
            celery_task_id=celery_task_id,
            task_db_id=task_db_id,
            task_type=PROMPT_AUDIO_ASR_TRANSCRIPT_TASK_TYPE,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            stage=stage,
            status=status,
            progress=progress,
        ),
        "chapter_audio_id": chapter_audio_id,
        "manual_triggered": True,
        "message": message,
        "current_stage": stage,
        "provider": provider,
        "model": target_model,
        "cost_control": {
            "manual_trigger_required": True,
            "auto_asr_in_generation": False,
            "provider_call_allowed": bool(provider_call_allowed),
        },
        "stages": {
            stage: {
                "status": "completed" if status == "completed" else "pending",
                "progress": progress,
                "message": message,
                "metrics": {
                    "chapter_audio_id": chapter_audio_id,
                    "manual_triggered": True,
                    "provider": provider,
                    "model": target_model,
                },
            },
        },
    }
    if reason:
        detail["reason"] = reason
        detail["stages"][stage]["metrics"]["reason"] = reason
    return detail


def queue_prompt_audio_transcript_task(
    db: Session,
    *,
    chapter_audio: ChapterAudio,
    provider: Optional[str] = None,
    target_model: Optional[str] = None,
    confirm_cost: bool = False,
) -> Dict[str, Any]:
    task_record = AudiobookTaskRepository.create_task(
        db,
        audiobook_project_id=chapter_audio.audiobook_project_id,
        chapter_id=chapter_audio.chapter_id,
        task_type=PROMPT_AUDIO_ASR_TRANSCRIPT_TASK_TYPE,
        total_units=1,
    )
    celery_task_id = str(uuid4())
    AudiobookTaskRepository.attach_celery_id(db, task_record.id, celery_task_id)

    task_record.status = "queued"
    task_record.current_stage = PROMPT_AUDIO_ASR_TRANSCRIPT_QUEUED_STAGE
    task_record.detail_json = build_prompt_audio_transcript_task_detail(
        task_db_id=task_record.id,
        celery_task_id=celery_task_id,
        audiobook_project_id=chapter_audio.audiobook_project_id,
        chapter_audio_id=chapter_audio.id,
        chapter_id=chapter_audio.chapter_id,
        status="queued",
        stage=PROMPT_AUDIO_ASR_TRANSCRIPT_QUEUED_STAGE,
        progress=0.0,
        message=PROMPT_AUDIO_ASR_TRANSCRIPT_QUEUED_MESSAGE,
        provider=provider,
        target_model=target_model,
        provider_call_allowed=confirm_cost,
    )
    db.add(task_record)
    db.commit()
    db.refresh(task_record)

    async_result = celery_app.signature(
        PROMPT_AUDIO_ASR_TRANSCRIPT_TASK_NAME,
        args=[
            task_record.id,
            chapter_audio.audiobook_project_id,
            chapter_audio.id,
            provider,
            target_model,
            confirm_cost,
        ],
    ).apply_async(task_id=celery_task_id)

    return {
        "success": True,
        "audiobook_project_id": chapter_audio.audiobook_project_id,
        "chapter_audio_id": chapter_audio.id,
        "job_id": async_result.id,
        "task_id": async_result.id,
        "task_db_id": task_record.id,
        "task_type": PROMPT_AUDIO_ASR_TRANSCRIPT_TASK_TYPE,
        "status": "queued",
        "message": PROMPT_AUDIO_ASR_TRANSCRIPT_QUEUED_MESSAGE,
        "provider": provider,
        "model": target_model,
        "cost_control": task_record.detail_json["cost_control"],
    }
