from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.services.audiobook.repository import ChapterAudioRunRepository
from app.services.audiobook.task_support import CHECKPOINT_SCHEMA_VERSION
from app.services.audiobook.temp_segment_store import (
    delete_temp_segment_prefix,
    inspect_temp_segment_cleanup_flags,
)
from app.utils.datetime_utils import utc_now

_UNSET = object()


def _is_after(candidate: Any, reference: datetime) -> bool:
    """比较两个时间戳；部分驱动（如 SQLite）会把时区感知时间读成 naive，
    直接比较会抛 TypeError，此时退化为视为不晚于参考时间。"""
    if candidate is None:
        return False
    try:
        return candidate > reference
    except TypeError:
        return False


def _build_checkpoint_temp_cleanup_document(
    checkpoint_json: Optional[Dict[str, Any]],
    *,
    cleanup_reason: str,
    cleanup_time: datetime,
    removed_files: int = 0,
    status: str,
    current_stage: str,
    expires_at: Any = _UNSET,
    expired_at: Any = _UNSET,
    last_error: Any = _UNSET,
    cleanup_flags: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    document = dict(checkpoint_json or {})
    cleanup_meta = dict(document.get("cleanup") or {}) if isinstance(document.get("cleanup"), dict) else {}

    cleanup_meta.update(
        {
            "cleanup_reason": cleanup_reason,
            "removed_temp_files": int(max(removed_files, 0)),
            "cleanup_executed_at": cleanup_time.isoformat(),
        }
    )

    if cleanup_flags:
        best_effort = bool(cleanup_flags.get("best_effort"))
        credentials_missing = bool(cleanup_flags.get("oss_delete_credentials_missing"))
        oss_candidate_count = int(cleanup_flags.get("oss_candidate_count") or 0)
        cleanup_meta["oss_delete_credentials_missing"] = credentials_missing
        cleanup_meta["oss_candidate_count"] = oss_candidate_count
        if best_effort:
            cleanup_meta["removed_temp_files_best_effort"] = True

    document["schema_version"] = int(document.get("schema_version") or CHECKPOINT_SCHEMA_VERSION)
    document["status"] = status
    document["current_stage"] = current_stage
    document["temp_asset_prefix"] = None
    document["cached_audio_paths"] = {}
    document["segments"] = {}
    document["cleanup"] = cleanup_meta
    document["checkpoint_updated_at"] = cleanup_time.isoformat()

    if expires_at is not _UNSET:
        document["expires_at"] = expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at
    if expired_at is not _UNSET:
        document["expired_at"] = expired_at.isoformat() if isinstance(expired_at, datetime) else expired_at
    if last_error is not _UNSET:
        document["last_error"] = last_error

    return document


def build_expired_checkpoint_cleanup_document(
    checkpoint_json: Optional[Dict[str, Any]],
    *,
    expired_at: Optional[datetime] = None,
    removed_files: int = 0,
    cleanup_flags: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cleanup_time = expired_at or utc_now()
    existing_document = dict(checkpoint_json or {})
    return _build_checkpoint_temp_cleanup_document(
        existing_document,
        cleanup_reason="expired_temp_assets",
        cleanup_time=cleanup_time,
        removed_files=removed_files,
        status="expired",
        current_stage="expired",
        expires_at=cleanup_time,
        expired_at=cleanup_time,
        last_error=existing_document.get("last_error") or "checkpoint_expired",
        cleanup_flags=cleanup_flags,
    )


def build_completed_checkpoint_cleanup_document(
    checkpoint_json: Optional[Dict[str, Any]],
    *,
    cleaned_at: Optional[datetime] = None,
    removed_files: int = 0,
    cleanup_flags: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cleanup_time = cleaned_at or utc_now()
    return _build_checkpoint_temp_cleanup_document(
        checkpoint_json,
        cleanup_reason="completed_temp_assets_pruned",
        cleanup_time=cleanup_time,
        removed_files=removed_files,
        status="completed",
        current_stage="completed",
        expires_at=None,
        expired_at=None,
        last_error=None,
        cleanup_flags=cleanup_flags,
    )


def expire_chapter_run_temp_assets(
    run: Any,
    *,
    now: Optional[datetime] = None,
    delete_prefix_fn: Callable[[Optional[str], Optional[Dict[str, Any]]], int] = delete_temp_segment_prefix,
) -> Dict[str, Any]:
    cleanup_time = now or utc_now()
    checkpoint_json = dict(getattr(run, "checkpoint_json", None) or {})
    temp_asset_prefix = (
        getattr(run, "temp_asset_prefix", None)
        or checkpoint_json.get("temp_asset_prefix")
    )
    removed_files = int(max(delete_prefix_fn(temp_asset_prefix, checkpoint_json), 0))
    cleanup_flags = inspect_temp_segment_cleanup_flags(temp_asset_prefix, checkpoint_json)

    run.checkpoint_json = build_expired_checkpoint_cleanup_document(
        checkpoint_json,
        expired_at=cleanup_time,
        removed_files=removed_files,
        cleanup_flags=cleanup_flags,
    )
    run.status = "expired"
    run.current_stage = "expired"
    run.resumable = False
    run.temp_asset_prefix = None
    if not getattr(run, "error_message", None):
        run.error_message = "checkpoint_expired"
    if getattr(run, "expires_at", None) is None or _is_after(run.expires_at, cleanup_time):
        run.expires_at = cleanup_time
    if getattr(run, "finished_at", None) is None:
        run.finished_at = cleanup_time

    return {
        "run_id": getattr(run, "id", None),
        "chapter_id": getattr(run, "chapter_id", None),
        "removed_temp_files": removed_files,
        "expired_at": cleanup_time.isoformat(),
    }


def finalize_completed_chapter_run_temp_assets(
    run: Any,
    *,
    now: Optional[datetime] = None,
    delete_prefix_fn: Callable[[Optional[str], Optional[Dict[str, Any]]], int] = delete_temp_segment_prefix,
) -> Dict[str, Any]:
    cleanup_time = now or utc_now()
    checkpoint_json = dict(getattr(run, "checkpoint_json", None) or {})
    temp_asset_prefix = (
        getattr(run, "temp_asset_prefix", None)
        or checkpoint_json.get("temp_asset_prefix")
    )
    removed_files = int(max(delete_prefix_fn(temp_asset_prefix, checkpoint_json), 0))
    cleanup_flags = inspect_temp_segment_cleanup_flags(temp_asset_prefix, checkpoint_json)

    run.checkpoint_json = build_completed_checkpoint_cleanup_document(
        checkpoint_json,
        cleaned_at=cleanup_time,
        removed_files=removed_files,
        cleanup_flags=cleanup_flags,
    )
    run.status = "completed"
    run.current_stage = "completed"
    run.resumable = False
    run.temp_asset_prefix = None
    run.error_message = None
    run.expires_at = None
    if getattr(run, "finished_at", None) is None:
        run.finished_at = cleanup_time

    return {
        "run_id": getattr(run, "id", None),
        "chapter_id": getattr(run, "chapter_id", None),
        "removed_temp_files": removed_files,
        "cleanup_executed_at": cleanup_time.isoformat(),
    }


def cleanup_expired_temp_segments_in_session(
    db: Session,
    *,
    limit: int = 100,
) -> Dict[str, Any]:
    runs = ChapterAudioRunRepository.list_expired_resumable_runs(db, limit=limit)
    now = utc_now()
    summaries = []

    for run in runs:
        summaries.append(expire_chapter_run_temp_assets(run, now=now))
        db.add(run)

    if runs:
        db.commit()

    return {
        "processed_runs": len(runs),
        "removed_temp_files": sum(int(item.get("removed_temp_files") or 0) for item in summaries),
        "runs": summaries,
        "cleanup_executed_at": now.isoformat(),
    }


def cleanup_expired_temp_segments(
    *,
    limit: int = 100,
) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        return cleanup_expired_temp_segments_in_session(db, limit=limit)
    finally:
        db.close()


__all__ = [
    "build_completed_checkpoint_cleanup_document",
    "build_expired_checkpoint_cleanup_document",
    "cleanup_expired_temp_segments",
    "cleanup_expired_temp_segments_in_session",
    "expire_chapter_run_temp_assets",
    "finalize_completed_chapter_run_temp_assets",
]
