"""
Helpers for persisting Celery audiobook job progress.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

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

logger = logging.getLogger(__name__)

# 任务级暂停状态：API 将 running 任务标记为 pause_requested，
# Worker 在章节循环边界检测到后调用 mark_paused 落库为 paused。
PAUSE_REQUESTED_STATUS = "pause_requested"
PAUSED_STATUS = "paused"


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
            if (
                run is not None
                and str(run.status or "").strip().lower() in {"cancelled", "canceled"}
                and not bool(run.resumable)
                and str(run.error_message or "").strip() == "chapter_output_deleted"
            ):
                return
            if not run:
                # Contract 收窄后 chapter_audio_id NOT NULL：兜底创建时解析 active ChapterAudio
                from app.services.audiobook.task_support import _ensure_active_chapter_audio

                _chapter_audio = _ensure_active_chapter_audio(
                    session,
                    audiobook_project_id=task.audiobook_project_id,
                    chapter_id=chapter_id,
                )
                run = ChapterAudioRun(
                    audiobook_project_id=task.audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type=task.task_type,
                    celery_task_id=task.celery_task_id,
                    chapter_audio_id=_chapter_audio.id,
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

    def is_pause_requested(self) -> bool:
        """检查任务是否被 API 标记为请求暂停。"""
        session = self._with_session()
        try:
            task = session.query(AudiobookTask).filter(AudiobookTask.id == self.task_db_id).first()
            if not task:
                return False
            return str(task.status or "").strip().lower() == PAUSE_REQUESTED_STATUS
        finally:
            session.close()

    def mark_paused(
        self,
        *,
        remaining_chapter_ids: Optional[Sequence[int]] = None,
        stage: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        """将任务落库为暂停状态，并记录剩余待生成章节以便恢复。"""
        session = self._with_session()
        try:
            task = session.query(AudiobookTask).filter(AudiobookTask.id == self.task_db_id).first()
            if not task:
                return
            detail = dict(task.detail_json or {})
            if remaining_chapter_ids is not None:
                detail["remaining_chapter_ids"] = [int(chapter_id) for chapter_id in remaining_chapter_ids]
            if message:
                detail["message"] = message
            task.detail_json = detail
            task.status = PAUSED_STATUS
            task.current_stage = stage or PAUSED_STATUS
            task.updated_at = utc_now()
            session.commit()
            task_snapshot = {
                "celery_task_id": task.celery_task_id,
                "status": task.status,
                "current_stage": task.current_stage,
                "progress": task.progress,
                "detail_json": task.detail_json or {},
                "error_message": task.error_message,
            }
        finally:
            session.close()
        self._mark_unfinished_chapter_runs_paused()
        self._emit_sse_progress(task_snapshot)

    def _mark_unfinished_chapter_runs_paused(self) -> None:
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

            paused_at = utc_now()
            for run in runs:
                if run.expires_at is None:
                    run.expires_at = paused_at + timedelta(hours=RESUME_WINDOW_HOURS)
                checkpoint_payload = build_run_checkpoint_document(
                    session,
                    run=run,
                    chapter_id=run.chapter_id,
                    audiobook_project_id=run.audiobook_project_id,
                    status=PAUSED_STATUS,
                    current_stage=run.current_stage or PAUSED_STATUS,
                )
                run.status = PAUSED_STATUS
                run.error_message = None
                run.finished_at = paused_at
                run.updated_at = paused_at
                run.checkpoint_json = checkpoint_payload
                session.add(run)

            session.commit()
        finally:
            session.close()


def handle_pause_checkpoint(
    tracker: Optional[Any],
    *,
    chapter_ids: Sequence[int],
    current_index: int,
    stage: Optional[str] = None,
) -> bool:
    """在章节循环边界检查并处理任务级暂停。

    应在每个章节迭代开始、尚未对该章节做任何工作前调用。
    若检测到暂停请求，则将任务落库为 paused（记录剩余章节）并返回 True，
    调用者应立即 return 停止后续章节处理。

    tracker 以鸭子类型方式使用（StageTracker Protocol 仅约束 update_stage），
    传入 None 或不支持暂停的 tracker 时安全返回 False。
    """
    if tracker is None:
        return False
    check = getattr(tracker, "is_pause_requested", None)
    if not callable(check):
        return False
    try:
        if not check():
            return False
    except Exception as exc:  # pragma: no cover - 暂停检查失败不应中断生成
        logger.warning("暂停状态检查失败，忽略并继续生成: %s", exc)
        return False

    remaining = list(chapter_ids)[max(current_index - 1, 0):] if current_index >= 1 else list(chapter_ids)
    mark = getattr(tracker, "mark_paused", None)
    if callable(mark):
        try:
            mark(remaining_chapter_ids=remaining, stage=stage)
        except Exception as exc:  # pragma: no cover - 落库失败不阻断 Worker 退出
            logger.exception("标记任务暂停失败: %s", exc)
    logger.info("⏸️ 检测到暂停请求，任务已在章节边界暂停，剩余章节数=%s", len(remaining))
    return True
