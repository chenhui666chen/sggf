from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def build_dreamweaver_trace_context(
    *,
    trace_id: Optional[str] = None,
    celery_task_id: Optional[str] = None,
    project_id: Optional[int] = None,
    user_id: Optional[int] = None,
    run_id: Optional[str] = None,
    stage: Optional[str] = None,
    state: Optional[str] = None,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    queue: Optional[str] = None,
    source_chapter_count: Optional[int] = None,
    quality_mode: Optional[str] = None,
    video_engine: Optional[str] = None,
    billing_freeze_event_id: Optional[str] = None,
    billing_settle_event_id: Optional[str] = None,
    billing_release_event_id: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_trace_id = trace_id or celery_task_id
    values: Dict[str, Any] = {
        "trace_id": resolved_trace_id,
        "celery_task_id": celery_task_id,
        "project_id": project_id,
        "user_id": user_id,
        "run_id": run_id,
        "stage": stage,
        "state": state,
        "status": status,
        "progress": progress,
        "error_type": error_type,
        "error_message": error_message,
        "queue": queue,
        "source_chapter_count": source_chapter_count,
        "quality_mode": quality_mode,
        "video_engine": video_engine,
        "billing_freeze_event_id": billing_freeze_event_id,
        "billing_settle_event_id": billing_settle_event_id,
        "billing_release_event_id": billing_release_event_id,
    }
    return {key: value for key, value in values.items() if value is not None}


def merge_dreamweaver_trace_context(
    detail: Mapping[str, Any],
    trace_context: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    merged = dict(detail)
    for key, value in (trace_context or {}).items():
        if value is not None and key not in merged:
            merged[key] = value
    return merged
