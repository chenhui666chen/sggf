from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def build_audiobook_trace_context(
    *,
    trace_id: Optional[str] = None,
    celery_task_id: Optional[str] = None,
    task_db_id: Optional[int] = None,
    task_type: Optional[str] = None,
    audiobook_project_id: Optional[int] = None,
    chapter_id: Optional[int] = None,
    run_id: Optional[int] = None,
    stage: Optional[str] = None,
    status: Optional[str] = None,
    progress: Optional[float] = None,
    tts_model: Optional[str] = None,
    cost_precheck_id: Optional[str] = None,
    billing_freeze_event_id: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_trace_id = trace_id or celery_task_id
    values: Dict[str, Any] = {
        "trace_id": resolved_trace_id,
        "celery_task_id": celery_task_id,
        "task_db_id": task_db_id,
        "task_type": task_type,
        "audiobook_project_id": audiobook_project_id,
        "chapter_id": chapter_id,
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "progress": progress,
        "tts_model": tts_model,
        "cost_precheck_id": cost_precheck_id,
        "billing_freeze_event_id": billing_freeze_event_id,
    }
    return {key: value for key, value in values.items() if value is not None}


def merge_audiobook_trace_context(
    detail: Mapping[str, Any],
    trace_context: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    merged = dict(detail)
    for key, value in (trace_context or {}).items():
        if value is not None and key not in merged:
            merged[key] = value
    return merged
