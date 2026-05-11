"""
Helpers for persisting Celery audiobook job progress.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.audiobook import ChapterAudioRun
from app.models.audiobook_task import AudiobookTask
from app.services.audiobook.sse_progress import sse_tracker
from app.services.audiobook.task_trace import (
    build_audiobook_trace_context,
    merge_audiobook_trace_context,
)
from app.utils.datetime_utils import utc_now


class AudiobookJobTracker:
    """Lightweight DB helper used by Celery tasks/background jobs."""

    _TERMINAL_CHAPTER_RUN_STATUSES = {"completed", "failed", "cancelled", "canceled"}

    def __init__(self, task_db_id: int):
        self.task_db_id = task_db_id

    def _with_session(self) -> Session:
        return SessionLocal()

    @staticmethod
    def _extract_total_segments(detail: Optional[Dict[str, Any]]) -> int:
        if not isinstance(detail, dict):
            return 0

        stages = detail.get("stages")
        if not isinstance(stages, dict):
            return 0

        for stage_data in stages.values():
            if not isinstance(stage_data, dict):
                continue
            metrics = stage_data.get("metrics")
            if not isinstance(metrics, dict):
                continue
            for key in ("total_segments", "segments_count"):
                value = metrics.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    return int(value)
        return 0

    def _update(self, **changes) -> Optional[Dict[str, Any]]:
        session = self._with_session()
        try:
            task = session.query(AudiobookTask).filter(AudiobookTask.id == self.task_db_id).first()
            if not task:
                return None
            for key, value in changes.items():
                setattr(task, key, value)
            task.updated_at = utc_now()
            session.commit()
            return {
                "celery_task_id": task.celery_task_id,
                "status": task.status,
                "current_stage": task.current_stage,
                "progress": task.progress,
                "detail_json": task.detail_json or {},
                "error_message": task.error_message,
            }
        finally:
            session.close()

    def _merge_task_trace_context(
        self,
        *,
        task: AudiobookTask,
        stage: str,
        progress: float,
        detail: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(detail, dict):
            return detail
        return merge_audiobook_trace_context(
            detail,
            build_audiobook_trace_context(
                celery_task_id=task.celery_task_id,
                task_db_id=task.id,
                task_type=task.task_type,
                audiobook_project_id=task.audiobook_project_id,
                chapter_id=detail.get("chapter_id") or task.chapter_id,
                stage=stage,
                status=detail.get("status") or task.status,
                progress=progress,
            ),
        )

    @staticmethod
    def _emit_sse_progress(task_snapshot: Optional[Dict[str, Any]]) -> None:
        if not task_snapshot:
            return
        task_id = task_snapshot.get("celery_task_id")
        if not task_id:
            return
        sse_tracker.emit_progress(
            str(task_id),
            {
                "stage": task_snapshot.get("current_stage"),
                "progress": task_snapshot.get("progress"),
                "detail": task_snapshot.get("detail_json") or {},
                "status": task_snapshot.get("status"),
                "error_message": task_snapshot.get("error_message"),
            },
        )

    def _update_chapter_run(
        self,
        *,
        stage: str,
        progress: float,
        detail: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
        finished: bool = False,
    ) -> None:
        if not isinstance(detail, dict):
            return

        chapter_id = detail.get("chapter_id")
        if chapter_id is None:
            return

        session = self._with_session()
        try:
            task = session.query(AudiobookTask).filter(AudiobookTask.id == self.task_db_id).first()
            if not task:
                return

            run_query = session.query(ChapterAudioRun).filter(
                ChapterAudioRun.audiobook_project_id == task.audiobook_project_id,
                ChapterAudioRun.chapter_id == chapter_id,
                ChapterAudioRun.run_type == task.task_type,
            )
            run = None
            if task.celery_task_id:
                run = (
                    run_query.filter(ChapterAudioRun.celery_task_id == task.celery_task_id)
                    .order_by(ChapterAudioRun.created_at.desc(), ChapterAudioRun.id.desc())
                    .first()
                )
            if not run:
                run = (
                    run_query
                    .order_by(ChapterAudioRun.created_at.desc(), ChapterAudioRun.id.desc())
                    .first()
                )
            if not run:
                run = ChapterAudioRun(
                    audiobook_project_id=task.audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type=task.task_type,
                    celery_task_id=task.celery_task_id,
                    status=status or task.status or "running",
                    current_stage=stage,
                    progress=progress,
                    resumable=True,
                    started_at=utc_now(),
                    checkpoint_json={},
                )
                session.add(run)

            checkpoint_payload = dict(run.checkpoint_json or {})
            checkpoint_payload["tracker_detail"] = detail
            total_segments = self._extract_total_segments(detail)
            if total_segments > 0 and (run.total_segment_count or 0) < total_segments:
                run.total_segment_count = total_segments

            run.celery_task_id = task.celery_task_id
            run.current_stage = stage
            run.progress = max(float(progress or 0.0), float(run.progress or 0.0))
            run.status = status or detail.get("status") or task.status or run.status or "running"
            run.error_message = error_message
            checkpoint_payload["schema_version"] = checkpoint_payload.get("schema_version") or 1
            checkpoint_payload["status"] = run.status
            checkpoint_payload["current_stage"] = stage
            checkpoint_payload["total_segments"] = max(
                int(checkpoint_payload.get("total_segments") or 0),
                int(run.total_segment_count or 0),
            )
            checkpoint_payload["checkpoint_updated_at"] = utc_now().isoformat()
            if error_message:
                checkpoint_payload["last_error"] = error_message
            run.checkpoint_json = checkpoint_payload

            if run.started_at is None:
                run.started_at = utc_now()
            if finished:
                run.finished_at = utc_now()
            run.updated_at = utc_now()
            session.commit()
        finally:
            session.close()

    def _mark_unfinished_chapter_runs_failed(self, error_message: str) -> None:
        from app.services.audiobook.task_support import (
            RESUME_WINDOW_HOURS,
            build_run_checkpoint_document,
        )

        session = self._with_session()
        try:
            task = session.query(AudiobookTask).filter(AudiobookTask.id == self.task_db_id).first()
            if not task or not task.celery_task_id:
                return

            run_query = session.query(ChapterAudioRun).filter(
                ChapterAudioRun.audiobook_project_id == task.audiobook_project_id,
                ChapterAudioRun.run_type == task.task_type,
                ChapterAudioRun.celery_task_id == task.celery_task_id,
                ~ChapterAudioRun.status.in_(self._TERMINAL_CHAPTER_RUN_STATUSES),
            )
            if task.chapter_id is not None:
                run_query = run_query.filter(ChapterAudioRun.chapter_id == task.chapter_id)

            runs = run_query.all()
            if not runs:
                return

            failed_at = utc_now()
            for run in runs:
                if run.expires_at is None:
                    run.expires_at = failed_at + timedelta(hours=RESUME_WINDOW_HOURS)
                checkpoint_payload = build_run_checkpoint_document(
                    session,
                    run=run,
                    chapter_id=run.chapter_id,
                    audiobook_project_id=run.audiobook_project_id,
                    status="failed",
                    current_stage="failed",
                    error_message=error_message,
                )
                run.status = "failed"
                run.current_stage = "failed"
                run.error_message = error_message
                run.finished_at = failed_at
                run.updated_at = failed_at
                run.checkpoint_json = checkpoint_payload
                session.add(run)

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
        self._emit_sse_progress(self._update(**changes))

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
        if isinstance(detail, dict):
            session = self._with_session()
            try:
                task = session.query(AudiobookTask).filter(AudiobookTask.id == self.task_db_id).first()
                detail = (
                    self._merge_task_trace_context(
                        task=task,
                        stage=stage,
                        progress=progress,
                        detail=detail,
                    )
                    if task
                    else detail
                )
            finally:
                session.close()
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
        task_snapshot = self._update(**payload)
        run_status = "running"
        run_finished = False
        if isinstance(payload.get("detail_json"), dict):
            detail_status = payload["detail_json"].get("status")
            if isinstance(detail_status, str) and detail_status:
                run_status = detail_status
                run_finished = detail_status in {"completed", "failed"}
        self._update_chapter_run(
            stage=stage,
            progress=progress,
            detail=payload.get("detail_json"),
            status=run_status,
            finished=run_finished,
        )
        self._emit_sse_progress(task_snapshot)

    def mark_completed(self, detail: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "status": "completed",
            "finished_at": utc_now(),
            "progress": 1.0,
            "current_stage": "completed",
        }
        if detail is not None:
            payload["detail_json"] = detail
        task_snapshot = self._update(**payload)
        self._update_chapter_run(
            stage="completed",
            progress=1.0,
            detail=detail,
            status="completed",
            finished=True,
        )
        self._emit_sse_progress(task_snapshot)

    def mark_failed(self, error_message: str) -> None:
        task_snapshot = self._update(
            status="failed",
            error_message=error_message,
            finished_at=utc_now(),
            current_stage="failed",
            progress=1.0,
        )
        self._mark_unfinished_chapter_runs_failed(error_message)
        self._emit_sse_progress(task_snapshot)
