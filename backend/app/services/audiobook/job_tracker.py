"""
Helpers for persisting Celery audiobook job progress.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.audiobook_task import AudiobookTask
from app.utils.datetime_utils import utc_now


class AudiobookJobTracker:
    """Lightweight DB helper used by Celery tasks/background jobs."""

    def __init__(self, task_db_id: int):
        self.task_db_id = task_db_id

    def _with_session(self) -> Session:
        return SessionLocal()

    def _update(self, **changes) -> None:
        session = self._with_session()
        try:
            task = session.query(AudiobookTask).filter(AudiobookTask.id == self.task_db_id).first()
            if not task:
                return
            for key, value in changes.items():
                setattr(task, key, value)
            task.updated_at = utc_now()
            session.commit()
        finally:
            session.close()

    def mark_running(self, celery_task_id: Optional[str] = None) -> None:
        """Persist the running state."""
        changes = {
            "status": "running",
            "started_at": utc_now(),
            "error_message": None,
        }
        if celery_task_id:
            changes["celery_task_id"] = celery_task_id
        self._update(**changes)

    def update_stage(
        self,
        stage: str,
        completed: int,
        total: int,
        message: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update current stage and numeric progress."""
        progress = float(completed) / float(total) if total else 0.0
        payload: Dict[str, Any] = {
            "current_stage": stage,
            "progress": progress,
            "completed_units": completed,
            "total_units": total,
        }
        if detail is not None:
            payload["detail_json"] = detail
        if message:
            payload.setdefault("detail_json", detail or {})
            payload["detail_json"] = {**payload.get("detail_json", {}), "message": message}
        self._update(**payload)

    def mark_completed(self, detail: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "status": "completed",
            "finished_at": utc_now(),
            "progress": 1.0,
            "current_stage": "completed",
        }
        if detail is not None:
            payload["detail_json"] = detail
        self._update(**payload)

    def mark_failed(self, error_message: str) -> None:
        self._update(
            status="failed",
            error_message=error_message,
            finished_at=utc_now(),
            current_stage="failed",
        )
