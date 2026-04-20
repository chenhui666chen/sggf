from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.audiobook import ChapterAudio
from app.models.audiobook_task import AudiobookTask
from app.schemas.audiobook import AudiobookTaskStatus
from app.services.audiobook.repository import ChapterAudioRunRepository
from app.services.points_task_precheck import build_task_points_precheck_error_detail
from app.utils.datetime_utils import utc_now


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
    ChapterAudioRunRepository.create_runs(
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

    checkpoint_json = dict(run.checkpoint_json or {})
    if checkpoint_patch:
        checkpoint_json.update(checkpoint_patch)

    changes: Dict[str, Any] = {
        "status": status,
        "current_stage": current_stage,
        "progress": progress,
        "celery_task_id": celery_task_id or run.celery_task_id,
        "checkpoint_json": checkpoint_json,
        "error_message": error_message,
    }
    if total_segment_count is not None:
        changes["total_segment_count"] = total_segment_count
    if completed_segment_count is not None:
        changes["completed_segment_count"] = completed_segment_count
    if status == "running" and run.started_at is None:
        changes["started_at"] = utc_now()
    if status in {"completed", "failed"}:
        changes["finished_at"] = utc_now()
    ChapterAudioRunRepository.update_run(db, run, **changes)


def _safe_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


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
    elif chapter_audio and chapter_audio.generation_progress_json:
        checkpoint_data = _safe_json_dict(chapter_audio.generation_progress_json)
        if checkpoint_data:
            checkpoint_source = "legacy_chapter_audio"

    completed_indices = checkpoint_data.get("completed_segment_indices") or []
    cached_paths = checkpoint_data.get("cached_audio_paths") or {}

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

    has_resume_material = bool(completed_indices or cached_paths)
    can_resume = bool(
        has_resume_material
        and (total_segments == 0 or completed_count < total_segments)
        and (chapter_run.resumable if chapter_run else True)
        and (not chapter_run or chapter_run.status not in {"completed", "failed"})
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
        "current_stage": chapter_run.current_stage if chapter_run else None,
        "celery_task_id": chapter_run.celery_task_id if chapter_run else None,
        "checkpoint_source": checkpoint_source,
    }
