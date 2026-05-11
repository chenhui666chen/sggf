from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, Sequence

from sqlalchemy.orm import Session

from app.models.admin_log import AdminOperationLog
from app.models.audiobook import AudiobookProject
from app.models.dreamweaver import DreamweaverProject
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.points_pricing_policy import (
    build_points_business_settlement_snapshot,
    get_points_pricing_policy_snapshot,
)
from app.services.user_center_task_billing import build_user_center_task_billing_overview
from app.utils.datetime_utils import ensure_utc_datetime, utc_now


POINTS_BILLING_RESOURCE_TYPE = "USER_POINTS_BILLING"

POINTS_BILLING_FREEZE_OPERATION_TYPE = "POINTS_BILLING_FREEZE"
POINTS_BILLING_SETTLE_OPERATION_TYPE = "POINTS_BILLING_SETTLE"
POINTS_BILLING_RELEASE_OPERATION_TYPE = "POINTS_BILLING_RELEASE"
POINTS_BILLING_OPERATION_TYPES = (
    POINTS_BILLING_FREEZE_OPERATION_TYPE,
    POINTS_BILLING_SETTLE_OPERATION_TYPE,
    POINTS_BILLING_RELEASE_OPERATION_TYPE,
)

POINTS_BILLING_EVENT_KIND_FREEZE = "freeze"
POINTS_BILLING_EVENT_KIND_SETTLE = "settle"
POINTS_BILLING_EVENT_KIND_RELEASE = "release"

POINTS_BILLING_MODULE_AUDIOBOOK = "audiobook"
POINTS_BILLING_MODULE_DREAMWEAVER = "dreamweaver"
POINTS_BILLING_MODULE_NOVEL = "novel"
POINTS_BILLING_MODULE_BOOK_PARSER = "book_parser"
POINTS_BILLING_MODULE_ASSET_STUDIO = "asset_studio"

AUDIOBOOK_BILLING_FREEZE_TRACE_PAYLOAD_KEYS = {
    "trace_id",
    "celery_task_id",
    "task_db_id",
    "task_type",
    "stage",
    "status",
    "progress",
    "tts_model",
    "cost_precheck_id",
    "billing_freeze_event_id",
}


def build_points_billing_key(module_key: str, business_key: str) -> str:
    normalized_module = str(module_key or "").strip().lower() or "unknown"
    normalized_business_key = str(business_key or "").strip()
    return f"{normalized_module}:{normalized_business_key}" if normalized_business_key else f"{normalized_module}:"


def build_audiobook_billing_key(audiobook_project_id: int) -> str:
    return f"audiobook:{max(int(audiobook_project_id or 0), 0)}"


def build_dreamweaver_billing_key(run_id: str) -> str:
    normalized_run_id = str(run_id or "").strip()
    return f"dreamweaver:{normalized_run_id}" if normalized_run_id else "dreamweaver:"


def _safe_text(value: object | None, fallback: str) -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _to_non_negative_float(value: object | None) -> float:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(amount):
        return 0.0
    return max(amount, 0.0)


def _event_log_rank(log: object) -> tuple[float, int]:
    created_at = ensure_utc_datetime(getattr(log, "created_at", None))
    return (
        created_at.timestamp() if created_at else 0.0,
        int(getattr(log, "id", 0) or 0),
    )


def _extract_event_kind(log: object) -> str:
    payload = getattr(log, "request_params", None) or {}
    return str(payload.get("event_kind") or "").strip().lower()


def _resolve_request_ip(request_context: object | None) -> str:
    client = getattr(request_context, "client", None)
    host = getattr(client, "host", None)
    return str(host or "").strip()


def _resolve_request_user_agent(request_context: object | None) -> str | None:
    headers = getattr(request_context, "headers", None)
    if headers is None:
        return None
    try:
        user_agent = headers.get("user-agent")
    except Exception:
        return None
    normalized = str(user_agent or "").strip()
    return normalized or None


def _resolve_request_method(request_context: object | None, fallback: str) -> str:
    method = str(getattr(request_context, "method", "") or "").strip().upper()
    return method or fallback


def _resolve_request_path(request_context: object | None, fallback: str) -> str:
    url = getattr(request_context, "url", None)
    path = str(getattr(url, "path", "") or "").strip()
    return path or fallback


def list_user_points_billing_logs(
    *,
    db: Session,
    target_user_id: int,
    limit: int | None = None,
) -> list[AdminOperationLog]:
    query = (
        db.query(AdminOperationLog)
        .filter(
            AdminOperationLog.operation_type.in_(POINTS_BILLING_OPERATION_TYPES),
            AdminOperationLog.resource_type == POINTS_BILLING_RESOURCE_TYPE,
            AdminOperationLog.resource_id == target_user_id,
            AdminOperationLog.response_status < 400,
        )
        .order_by(AdminOperationLog.created_at.desc(), AdminOperationLog.id.desc())
    )

    if limit is not None and int(limit) > 0:
        query = query.limit(int(limit))

    return query.all()


def get_active_points_billing_freeze_amount(
    *,
    db: Session,
    target_user_id: int,
    billing_key: str,
) -> float:
    if not str(billing_key or "").strip():
        return 0.0

    existing_logs = _list_billing_logs_for_key(
        db=db,
        target_user_id=target_user_id,
        billing_key=billing_key,
    )
    active_freeze_log = _resolve_active_freeze_log(existing_logs, billing_key=billing_key)
    if active_freeze_log is None:
        return 0.0

    payload = getattr(active_freeze_log, "request_params", None) or {}
    return round(_to_non_negative_float(payload.get("amount_points")), 2)


def _list_billing_logs_for_key(
    *,
    db: Session,
    target_user_id: int,
    billing_key: str,
) -> list[AdminOperationLog]:
    if not billing_key:
        return []

    return (
        db.query(AdminOperationLog)
        .filter(
            AdminOperationLog.operation_type.in_(POINTS_BILLING_OPERATION_TYPES),
            AdminOperationLog.resource_type == POINTS_BILLING_RESOURCE_TYPE,
            AdminOperationLog.resource_id == target_user_id,
            AdminOperationLog.response_status < 400,
        )
        .order_by(AdminOperationLog.created_at.asc(), AdminOperationLog.id.asc())
        .all()
    )


def _filter_logs_by_billing_key(logs: Sequence[AdminOperationLog], *, billing_key: str) -> list[AdminOperationLog]:
    normalized_key = str(billing_key or "").strip()
    if not normalized_key:
        return []

    matched: list[AdminOperationLog] = []
    for log in logs:
        payload = getattr(log, "request_params", None) or {}
        if str(payload.get("billing_key") or "").strip() != normalized_key:
            continue
        matched.append(log)
    return matched


def _has_active_freeze(logs: Sequence[AdminOperationLog], *, billing_key: str) -> bool:
    active_freeze = False
    for log in _filter_logs_by_billing_key(logs, billing_key=billing_key):
        event_kind = _extract_event_kind(log)
        if event_kind == POINTS_BILLING_EVENT_KIND_FREEZE:
            active_freeze = True
            continue
        if event_kind in {POINTS_BILLING_EVENT_KIND_SETTLE, POINTS_BILLING_EVENT_KIND_RELEASE}:
            active_freeze = False
    return active_freeze


def _latest_event_kind(logs: Sequence[AdminOperationLog], *, billing_key: str) -> str | None:
    matched_logs = _filter_logs_by_billing_key(logs, billing_key=billing_key)
    if not matched_logs:
        return None
    latest_log = max(matched_logs, key=_event_log_rank)
    event_kind = _extract_event_kind(latest_log)
    return event_kind or None


def _resolve_active_freeze_log(
    logs: Sequence[AdminOperationLog],
    *,
    billing_key: str,
) -> AdminOperationLog | None:
    active_log: AdminOperationLog | None = None
    for log in _filter_logs_by_billing_key(logs, billing_key=billing_key):
        event_kind = _extract_event_kind(log)
        if event_kind == POINTS_BILLING_EVENT_KIND_FREEZE:
            active_log = log
            continue
        if event_kind in {POINTS_BILLING_EVENT_KIND_SETTLE, POINTS_BILLING_EVENT_KIND_RELEASE}:
            active_log = None
    return active_log


def _create_points_billing_event_log(
    *,
    db: Session,
    actor_user_id: int,
    actor_username: str,
    target_user_id: int,
    billing_key: str,
    module_key: str,
    event_kind: str,
    operation_type: str,
    amount_points: float,
    amount_yuan: float | None,
    title: str,
    summary: str,
    action_path: str | None,
    action_label: str | None,
    request_context: object | None,
    default_request_method: str,
    default_request_path: str,
    operation_desc: str,
    extra_payload: dict[str, Any] | None = None,
) -> AdminOperationLog:
    payload: dict[str, Any] = {
        "billing_key": billing_key,
        "module_key": module_key,
        "event_kind": event_kind,
        "target_user_id": int(target_user_id),
        "amount_points": round(amount_points, 2),
        "amount_yuan": round(amount_yuan, 2) if amount_yuan is not None else None,
        "title": title,
        "summary": summary,
        "action_path": action_path,
        "action_label": action_label,
    }
    if extra_payload:
        for key, value in extra_payload.items():
            if value is None:
                continue
            payload[key] = value

    log = AdminOperationLog(
        user_id=actor_user_id,
        username=actor_username,
        operation_type=operation_type,
        resource_type=POINTS_BILLING_RESOURCE_TYPE,
        resource_id=target_user_id,
        operation_desc=operation_desc,
        request_method=_resolve_request_method(request_context, default_request_method),
        request_path=_resolve_request_path(request_context, default_request_path),
        request_params=payload,
        response_status=201,
        ip_address=_resolve_request_ip(request_context),
        user_agent=_resolve_request_user_agent(request_context),
        duration_ms=0,
        error_message=None,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def _filter_audiobook_billing_freeze_trace_payload(
    extra_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if not extra_payload:
        return {}
    return {
        key: extra_payload[key]
        for key in AUDIOBOOK_BILLING_FREEZE_TRACE_PAYLOAD_KEYS
        if key in extra_payload and extra_payload[key] is not None
    }


def _build_operating_snapshot_payload(
    *,
    pricing_snapshot: object,
    module_key: str,
    basis_yuan: float,
    provider_key: str | None = None,
) -> dict[str, object]:
    config = getattr(pricing_snapshot, "config", None)
    if config is None:
        return {}

    snapshot = build_points_business_settlement_snapshot(
        pricing_config=config,
        module_key=module_key,
        basis_yuan=max(float(basis_yuan), 0.0),
        provider_key=provider_key,
    )
    return snapshot.to_payload()


def _build_generic_pricing_payload(
    *,
    pricing_snapshot: object,
    module_key: str,
    basis_yuan: float | None,
    provider_key: str | None,
    include_freeze_buffer_rate: bool = False,
) -> dict[str, object]:
    config = getattr(pricing_snapshot, "config", None)
    if config is None:
        return {}

    payload: dict[str, object] = {
        "points_per_yuan": int(config.points_per_yuan),
        "user_price_basis": config.user_price_basis,
        "user_price_rate": round(float(config.user_price_rate), 4),
    }
    if include_freeze_buffer_rate:
        payload["freeze_buffer_rate"] = round(float(config.freeze_buffer_rate), 4)

    if basis_yuan is not None:
        payload["operating_snapshot"] = _build_operating_snapshot_payload(
            pricing_snapshot=pricing_snapshot,
            module_key=module_key,
            basis_yuan=_to_non_negative_float(basis_yuan),
            provider_key=provider_key,
        )
    return payload


def record_points_billing_freeze(
    *,
    db: Session,
    actor_user_id: int,
    actor_username: str,
    target_user_id: int,
    billing_key: str,
    module_key: str,
    amount_points: float,
    amount_yuan: float | None,
    title: str,
    summary: str,
    action_path: str | None,
    action_label: str | None,
    request_context: object | None = None,
    default_request_method: str = "SYSTEM",
    default_request_path: str = "/internal/points-billing/freeze",
    operation_desc: str | None = None,
    provider_key: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> AdminOperationLog | None:
    normalized_billing_key = _safe_text(billing_key, "")
    normalized_module_key = _safe_text(module_key, "unknown")
    normalized_amount_points = _to_non_negative_float(amount_points)
    if not normalized_billing_key or normalized_amount_points <= 0:
        return None

    existing_logs = _list_billing_logs_for_key(
        db=db,
        target_user_id=int(target_user_id or 0),
        billing_key=normalized_billing_key,
    )
    if _has_active_freeze(existing_logs, billing_key=normalized_billing_key):
        return None

    pricing_snapshot = get_points_pricing_policy_snapshot(db=db)
    payload = _build_generic_pricing_payload(
        pricing_snapshot=pricing_snapshot,
        module_key=normalized_module_key,
        basis_yuan=amount_yuan,
        provider_key=provider_key,
        include_freeze_buffer_rate=True,
    )
    if extra_payload:
        payload.update(extra_payload)

    return _create_points_billing_event_log(
        db=db,
        actor_user_id=int(actor_user_id or 0),
        actor_username=_safe_text(actor_username, "system"),
        target_user_id=int(target_user_id or 0),
        billing_key=normalized_billing_key,
        module_key=normalized_module_key,
        event_kind=POINTS_BILLING_EVENT_KIND_FREEZE,
        operation_type=POINTS_BILLING_FREEZE_OPERATION_TYPE,
        amount_points=normalized_amount_points,
        amount_yuan=_to_non_negative_float(amount_yuan) if amount_yuan is not None else None,
        title=_safe_text(title, "任务积分冻结"),
        summary=_safe_text(summary, "任务已冻结积分。"),
        action_path=action_path,
        action_label=action_label,
        request_context=request_context,
        default_request_method=default_request_method,
        default_request_path=default_request_path,
        operation_desc=operation_desc
        or f"{_safe_text(title, '任务')} 冻结积分 {normalized_amount_points:.2f}",
        extra_payload=payload,
    )


def record_points_billing_settle(
    *,
    db: Session,
    actor_user_id: int,
    actor_username: str,
    target_user_id: int,
    billing_key: str,
    module_key: str,
    amount_points: float,
    amount_yuan: float | None,
    title: str | None = None,
    summary: str | None = None,
    action_path: str | None = None,
    action_label: str | None = None,
    default_request_method: str = "SYSTEM",
    default_request_path: str = "/internal/points-billing/settle",
    operation_desc: str | None = None,
    provider_key: str | None = None,
    extra_payload: dict[str, Any] | None = None,
    require_active_freeze: bool = True,
) -> AdminOperationLog | None:
    normalized_billing_key = _safe_text(billing_key, "")
    normalized_module_key = _safe_text(module_key, "unknown")
    normalized_amount_points = _to_non_negative_float(amount_points)
    if not normalized_billing_key:
        return None

    existing_logs = _list_billing_logs_for_key(
        db=db,
        target_user_id=int(target_user_id or 0),
        billing_key=normalized_billing_key,
    )
    if _latest_event_kind(existing_logs, billing_key=normalized_billing_key) == POINTS_BILLING_EVENT_KIND_SETTLE:
        return None

    active_freeze_log = _resolve_active_freeze_log(existing_logs, billing_key=normalized_billing_key)
    if require_active_freeze and active_freeze_log is None:
        return None

    if normalized_amount_points <= 0:
        return record_points_billing_release(
            db=db,
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            target_user_id=target_user_id,
            billing_key=normalized_billing_key,
            module_key=normalized_module_key,
            reason=_safe_text(summary, "任务完成但未产生可结算成本，已释放冻结积分。"),
            default_request_path=default_request_path.replace("settle", "release"),
            extra_payload=extra_payload,
        )

    freeze_payload = getattr(active_freeze_log, "request_params", None) or {}
    merged_extra_payload: dict[str, Any] = {}
    if isinstance(freeze_payload, dict):
        for key in (
            "project_id",
            "audiobook_project_id",
            "book_id",
            "task_id",
            "run_id",
            "stage",
            "asset_kind",
            "asset_mode",
        ):
            if freeze_payload.get(key) is not None:
                merged_extra_payload[key] = freeze_payload.get(key)
        if getattr(active_freeze_log, "id", None) is not None:
            merged_extra_payload["settled_from_billing_log_id"] = int(active_freeze_log.id)
    if extra_payload:
        merged_extra_payload.update(extra_payload)

    pricing_snapshot = get_points_pricing_policy_snapshot(db=db)
    merged_extra_payload.update(
        _build_generic_pricing_payload(
            pricing_snapshot=pricing_snapshot,
            module_key=normalized_module_key,
            basis_yuan=amount_yuan,
            provider_key=provider_key,
            include_freeze_buffer_rate=False,
        )
    )

    resolved_title = _safe_text(title, _safe_text(freeze_payload.get("title") if isinstance(freeze_payload, dict) else None, "任务积分结算"))
    resolved_summary = _safe_text(
        summary,
        _safe_text(
            freeze_payload.get("summary") if isinstance(freeze_payload, dict) else None,
            "任务已按实际成本完成积分结算。",
        ),
    )
    resolved_action_path = action_path or (
        _safe_text(freeze_payload.get("action_path"), "") if isinstance(freeze_payload, dict) else ""
    ) or None
    resolved_action_label = action_label or (
        _safe_text(freeze_payload.get("action_label"), "") if isinstance(freeze_payload, dict) else ""
    ) or None

    return _create_points_billing_event_log(
        db=db,
        actor_user_id=int(actor_user_id or 0),
        actor_username=_safe_text(actor_username, "system"),
        target_user_id=int(target_user_id or 0),
        billing_key=normalized_billing_key,
        module_key=normalized_module_key,
        event_kind=POINTS_BILLING_EVENT_KIND_SETTLE,
        operation_type=POINTS_BILLING_SETTLE_OPERATION_TYPE,
        amount_points=normalized_amount_points,
        amount_yuan=_to_non_negative_float(amount_yuan) if amount_yuan is not None else None,
        title=resolved_title,
        summary=resolved_summary,
        action_path=resolved_action_path,
        action_label=resolved_action_label,
        request_context=None,
        default_request_method=default_request_method,
        default_request_path=default_request_path,
        operation_desc=operation_desc or f"{resolved_title} 结算积分 {normalized_amount_points:.2f}",
        extra_payload=merged_extra_payload,
    )


def record_points_billing_release(
    *,
    db: Session,
    actor_user_id: int,
    actor_username: str,
    target_user_id: int,
    billing_key: str,
    module_key: str,
    reason: str,
    default_request_method: str = "SYSTEM",
    default_request_path: str = "/internal/points-billing/release",
    operation_desc: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> AdminOperationLog | None:
    normalized_billing_key = _safe_text(billing_key, "")
    normalized_module_key = _safe_text(module_key, "unknown")
    if not normalized_billing_key:
        return None

    existing_logs = _list_billing_logs_for_key(
        db=db,
        target_user_id=int(target_user_id or 0),
        billing_key=normalized_billing_key,
    )
    active_freeze_log = _resolve_active_freeze_log(existing_logs, billing_key=normalized_billing_key)
    if active_freeze_log is None:
        return None

    freeze_payload = getattr(active_freeze_log, "request_params", None) or {}
    amount_points = _to_non_negative_float(freeze_payload.get("amount_points") if isinstance(freeze_payload, dict) else 0)
    amount_yuan = _to_non_negative_float(freeze_payload.get("amount_yuan") if isinstance(freeze_payload, dict) else 0)
    resolved_title = _safe_text(freeze_payload.get("title") if isinstance(freeze_payload, dict) else None, "任务积分冻结")
    action_path = _safe_text(freeze_payload.get("action_path") if isinstance(freeze_payload, dict) else None, "") or None
    action_label = _safe_text(freeze_payload.get("action_label") if isinstance(freeze_payload, dict) else None, "") or None

    payload: dict[str, Any] = {}
    if isinstance(freeze_payload, dict):
        for key in (
            "project_id",
            "audiobook_project_id",
            "book_id",
            "task_id",
            "run_id",
            "stage",
            "asset_kind",
            "asset_mode",
        ):
            if freeze_payload.get(key) is not None:
                payload[key] = freeze_payload.get(key)
    payload["released_from_billing_log_id"] = int(getattr(active_freeze_log, "id", 0) or 0)
    if extra_payload:
        payload.update(extra_payload)

    return _create_points_billing_event_log(
        db=db,
        actor_user_id=int(actor_user_id or 0),
        actor_username=_safe_text(actor_username, "system"),
        target_user_id=int(target_user_id or 0),
        billing_key=normalized_billing_key,
        module_key=normalized_module_key,
        event_kind=POINTS_BILLING_EVENT_KIND_RELEASE,
        operation_type=POINTS_BILLING_RELEASE_OPERATION_TYPE,
        amount_points=amount_points,
        amount_yuan=amount_yuan,
        title=resolved_title,
        summary=_safe_text(reason, "任务已释放冻结积分。"),
        action_path=action_path,
        action_label=action_label,
        request_context=None,
        default_request_method=default_request_method,
        default_request_path=default_request_path,
        operation_desc=operation_desc or f"{resolved_title} 释放冻结积分 {amount_points:.2f}",
        extra_payload=payload,
    )


def record_audiobook_billing_freeze(
    *,
    db: Session,
    actor_user_id: int,
    actor_username: str,
    audiobook_project_id: int,
    chapter_ids: Sequence[int] | None,
    request_context: object | None = None,
    tts_pricing_key: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> AdminOperationLog | None:
    row = (
        db.query(
            AudiobookProject.id.label("id"),
            AudiobookProject.project_id.label("project_id"),
            AudiobookProject.tts_provider.label("tts_provider"),
            AudiobookProject.total_chapters.label("total_chapters"),
            AudiobookProject.created_at.label("created_at"),
            AudiobookProject.updated_at.label("updated_at"),
            Project.user_id.label("target_user_id"),
            Project.title.label("project_title"),
        )
        .join(Project, Project.id == AudiobookProject.project_id)
        .filter(AudiobookProject.id == audiobook_project_id)
        .first()
    )
    if row is None:
        return None

    billing_key = build_audiobook_billing_key(row.id)
    existing_logs = _list_billing_logs_for_key(
        db=db,
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
    )
    if _has_active_freeze(existing_logs, billing_key=billing_key):
        return None

    normalized_chapter_ids = [int(chapter_id) for chapter_id in (chapter_ids or []) if int(chapter_id or 0) > 0]
    chapter_query = (
        db.query(
            Chapter.project_id.label("project_id"),
            Chapter.word_count.label("word_count"),
            Chapter.content.label("content"),
        )
        .filter(
            Chapter.project_id == row.project_id,
            Chapter.deleted_at.is_(None),
        )
    )
    if normalized_chapter_ids:
        chapter_query = chapter_query.filter(Chapter.id.in_(normalized_chapter_ids))
    chapter_rows = chapter_query.all()

    selected_chapter_count = len(chapter_rows) if chapter_rows else len(normalized_chapter_ids)
    if selected_chapter_count <= 0:
        selected_chapter_count = int(row.total_chapters or 0)

    effective_tts_pricing_key = _safe_text(tts_pricing_key, "") or row.tts_provider
    synthetic_row = SimpleNamespace(
        id=row.id,
        project_id=row.project_id,
        project_title=row.project_title,
        status="pending",
        tts_provider=effective_tts_pricing_key,
        total_chapters=selected_chapter_count,
        completed_chapters=0,
        total_cost=0.0,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    pricing_snapshot = get_points_pricing_policy_snapshot(db=db)
    task_billing = build_user_center_task_billing_overview(
        audiobook_rows=[synthetic_row],
        dreamweaver_rows=[],
        chapter_rows=list(chapter_rows),
        pricing_config=pricing_snapshot.config,
    )
    if not task_billing.items:
        return None

    item = task_billing.items[0]
    amount_points = _to_non_negative_float(item.suggested_frozen_points)
    if amount_points <= 0:
        return None

    billing_payload = {
        "project_id": int(row.project_id or 0),
        "audiobook_project_id": int(row.id or 0),
        "pricing_status": item.pricing_status,
        "task_status": item.task_status,
        "chapter_ids": normalized_chapter_ids,
        "points_per_yuan": int(pricing_snapshot.config.points_per_yuan),
        "user_price_basis": pricing_snapshot.config.user_price_basis,
        "user_price_rate": round(float(pricing_snapshot.config.user_price_rate), 4),
        "freeze_buffer_rate": round(float(pricing_snapshot.config.freeze_buffer_rate), 4),
        "operating_snapshot": _build_operating_snapshot_payload(
            pricing_snapshot=pricing_snapshot,
            module_key=POINTS_BILLING_MODULE_AUDIOBOOK,
            basis_yuan=_to_non_negative_float(item.estimated_yuan),
            provider_key=_safe_text(effective_tts_pricing_key, "") or None,
        ),
    }
    billing_payload.update(_filter_audiobook_billing_freeze_trace_payload(extra_payload))

    return _create_points_billing_event_log(
        db=db,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
        module_key=POINTS_BILLING_MODULE_AUDIOBOOK,
        event_kind=POINTS_BILLING_EVENT_KIND_FREEZE,
        operation_type=POINTS_BILLING_FREEZE_OPERATION_TYPE,
        amount_points=amount_points,
        amount_yuan=_to_non_negative_float(item.estimated_yuan),
        title=_safe_text(item.title, f"有声书项目 #{row.id}"),
        summary=_safe_text(item.summary, "\u6709\u58f0\u4e66\u4efb\u52a1\u5df2\u751f\u6210\u6b63\u5f0f\u51bb\u7ed3\u79ef\u5206\u3002"),
        action_path=item.action_path,
        action_label=item.action_label,
        request_context=request_context,
        default_request_method="POST",
        default_request_path=f"/api/v1/audiobook/projects/{row.id}/billing-freeze",
        operation_desc=f"有声书任务正式冻结积分 {amount_points:.2f}",
        extra_payload=billing_payload,
    )


def record_audiobook_billing_settle(
    *,
    db: Session,
    audiobook_project_id: int,
) -> AdminOperationLog | None:
    row = (
        db.query(
            AudiobookProject.id.label("id"),
            AudiobookProject.project_id.label("project_id"),
            AudiobookProject.status.label("status"),
            AudiobookProject.tts_provider.label("tts_provider"),
            AudiobookProject.total_chapters.label("total_chapters"),
            AudiobookProject.completed_chapters.label("completed_chapters"),
            AudiobookProject.total_cost.label("total_cost"),
            AudiobookProject.created_at.label("created_at"),
            AudiobookProject.updated_at.label("updated_at"),
            Project.user_id.label("target_user_id"),
            Project.title.label("project_title"),
            User.username.label("target_username"),
        )
        .join(Project, Project.id == AudiobookProject.project_id)
        .join(User, User.id == Project.user_id)
        .filter(AudiobookProject.id == audiobook_project_id)
        .first()
    )
    if row is None:
        return None

    billing_key = build_audiobook_billing_key(row.id)
    existing_logs = _list_billing_logs_for_key(
        db=db,
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
    )
    if _latest_event_kind(existing_logs, billing_key=billing_key) == POINTS_BILLING_EVENT_KIND_SETTLE:
        return None

    pricing_snapshot = get_points_pricing_policy_snapshot(db=db)
    task_billing = build_user_center_task_billing_overview(
        audiobook_rows=[row],
        dreamweaver_rows=[],
        chapter_rows=[],
        pricing_config=pricing_snapshot.config,
    )
    if not task_billing.items:
        return record_audiobook_billing_release(
            db=db,
            audiobook_project_id=audiobook_project_id,
            reason="\u6709\u58f0\u4e66\u4efb\u52a1\u5b8c\u6210\u4f46\u672a\u4ea7\u751f\u53ef\u7ed3\u7b97\u6210\u672c\uff0c\u5df2\u91ca\u653e\u51bb\u7ed3\u79ef\u5206\u3002",
        )

    item = task_billing.items[0]
    amount_points = _to_non_negative_float(item.actual_points)
    amount_yuan = _to_non_negative_float(item.actual_yuan)
    if amount_points <= 0 or amount_yuan <= 0:
        return record_audiobook_billing_release(
            db=db,
            audiobook_project_id=audiobook_project_id,
            reason="\u6709\u58f0\u4e66\u4efb\u52a1\u5b8c\u6210\u4f46\u672a\u4ea7\u751f\u53ef\u7ed3\u7b97\u6210\u672c\uff0c\u5df2\u91ca\u653e\u51bb\u7ed3\u79ef\u5206\u3002",
        )

    return _create_points_billing_event_log(
        db=db,
        actor_user_id=int(row.target_user_id or 0),
        actor_username=_safe_text(row.target_username, "system"),
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
        module_key=POINTS_BILLING_MODULE_AUDIOBOOK,
        event_kind=POINTS_BILLING_EVENT_KIND_SETTLE,
        operation_type=POINTS_BILLING_SETTLE_OPERATION_TYPE,
        amount_points=amount_points,
        amount_yuan=amount_yuan,
        title=_safe_text(item.title, f"有声书项目 #{row.id}"),
        summary=_safe_text(item.summary, "\u6709\u58f0\u4e66\u4efb\u52a1\u5df2\u6309\u5b9e\u9645\u6210\u672c\u5b8c\u6210\u79ef\u5206\u7ed3\u7b97\u3002"),
        action_path=item.action_path,
        action_label=item.action_label,
        request_context=None,
        default_request_method="SYSTEM",
        default_request_path=f"/internal/audiobook/{row.id}/billing-settle",
        operation_desc=f"有声书任务完成积分结算 {amount_points:.2f}",
        extra_payload={
            "project_id": int(row.project_id or 0),
            "audiobook_project_id": int(row.id or 0),
            "pricing_status": item.pricing_status,
            "task_status": item.task_status,
            "points_per_yuan": int(pricing_snapshot.config.points_per_yuan),
            "user_price_basis": pricing_snapshot.config.user_price_basis,
            "user_price_rate": round(float(pricing_snapshot.config.user_price_rate), 4),
            "operating_snapshot": _build_operating_snapshot_payload(
                pricing_snapshot=pricing_snapshot,
                module_key=POINTS_BILLING_MODULE_AUDIOBOOK,
                basis_yuan=amount_yuan,
                provider_key=_safe_text(row.tts_provider, "") or None,
            ),
        },
    )


def record_audiobook_billing_release(
    *,
    db: Session,
    audiobook_project_id: int,
    reason: str,
) -> AdminOperationLog | None:
    row = (
        db.query(
            AudiobookProject.id.label("id"),
            AudiobookProject.project_id.label("project_id"),
            Project.user_id.label("target_user_id"),
            Project.title.label("project_title"),
            User.username.label("target_username"),
        )
        .join(Project, Project.id == AudiobookProject.project_id)
        .join(User, User.id == Project.user_id)
        .filter(AudiobookProject.id == audiobook_project_id)
        .first()
    )
    if row is None:
        return None

    billing_key = build_audiobook_billing_key(row.id)
    existing_logs = _list_billing_logs_for_key(
        db=db,
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
    )
    active_freeze_log = _resolve_active_freeze_log(existing_logs, billing_key=billing_key)
    if active_freeze_log is None:
        return None

    freeze_payload = getattr(active_freeze_log, "request_params", None) or {}
    amount_points = _to_non_negative_float(freeze_payload.get("amount_points"))
    amount_yuan = _to_non_negative_float(freeze_payload.get("amount_yuan"))
    action_path = _safe_text(freeze_payload.get("action_path"), "") or f"/audiobook/{int(row.project_id or 0)}"
    action_label = _safe_text(freeze_payload.get("action_label"), "") or "\u67e5\u770b\u6709\u58f0\u4e66\u9879\u76ee"

    return _create_points_billing_event_log(
        db=db,
        actor_user_id=int(row.target_user_id or 0),
        actor_username=_safe_text(row.target_username, "system"),
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
        module_key=POINTS_BILLING_MODULE_AUDIOBOOK,
        event_kind=POINTS_BILLING_EVENT_KIND_RELEASE,
        operation_type=POINTS_BILLING_RELEASE_OPERATION_TYPE,
        amount_points=amount_points,
        amount_yuan=amount_yuan,
        title=_safe_text(freeze_payload.get("title"), f"有声书项目 #{row.id}"),
        summary=_safe_text(reason, "\u6709\u58f0\u4e66\u4efb\u52a1\u5df2\u91ca\u653e\u51bb\u7ed3\u79ef\u5206\u3002"),
        action_path=action_path,
        action_label=action_label,
        request_context=None,
        default_request_method="SYSTEM",
        default_request_path=f"/internal/audiobook/{row.id}/billing-release",
        operation_desc=f"有声书任务释放冻结积分 {amount_points:.2f}",
        extra_payload={
            "project_id": int(row.project_id or 0),
            "audiobook_project_id": int(row.id or 0),
        },
    )


def record_dreamweaver_billing_freeze(
    *,
    db: Session,
    run_id: str,
) -> AdminOperationLog | None:
    row = (
        db.query(
            DreamweaverProject.id.label("id"),
            DreamweaverProject.run_id.label("run_id"),
            DreamweaverProject.source_project_id.label("source_project_id"),
            DreamweaverProject.user_id.label("target_user_id"),
            DreamweaverProject.status.label("status"),
            DreamweaverProject.stage.label("stage"),
            DreamweaverProject.contract_json.label("contract_json"),
            DreamweaverProject.created_at.label("created_at"),
            DreamweaverProject.updated_at.label("updated_at"),
            Project.title.label("project_title"),
            User.username.label("target_username"),
        )
        .join(Project, Project.id == DreamweaverProject.source_project_id)
        .join(User, User.id == DreamweaverProject.user_id)
        .filter(DreamweaverProject.run_id == run_id)
        .first()
    )
    if row is None:
        return None

    billing_key = build_dreamweaver_billing_key(_safe_text(row.run_id, ""))
    existing_logs = _list_billing_logs_for_key(
        db=db,
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
    )
    if _has_active_freeze(existing_logs, billing_key=billing_key):
        return None

    pricing_snapshot = get_points_pricing_policy_snapshot(db=db)
    task_billing = build_user_center_task_billing_overview(
        audiobook_rows=[],
        dreamweaver_rows=[row],
        chapter_rows=[],
        pricing_config=pricing_snapshot.config,
    )
    if not task_billing.items:
        return None

    item = task_billing.items[0]
    amount_points = _to_non_negative_float(item.suggested_frozen_points)
    if amount_points <= 0:
        return None

    return _create_points_billing_event_log(
        db=db,
        actor_user_id=int(row.target_user_id or 0),
        actor_username=_safe_text(row.target_username, "system"),
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
        module_key=POINTS_BILLING_MODULE_DREAMWEAVER,
        event_kind=POINTS_BILLING_EVENT_KIND_FREEZE,
        operation_type=POINTS_BILLING_FREEZE_OPERATION_TYPE,
        amount_points=amount_points,
        amount_yuan=_to_non_negative_float(item.estimated_yuan),
        title=_safe_text(item.title, f"短剧运行 {row.run_id}"),
        summary=_safe_text(item.summary, "\u77ed\u5267\u4efb\u52a1\u5df2\u751f\u6210\u6b63\u5f0f\u51bb\u7ed3\u79ef\u5206\u3002"),
        action_path=item.action_path,
        action_label=item.action_label,
        request_context=None,
        default_request_method="SYSTEM",
        default_request_path=f"/internal/dreamweaver/{row.run_id}/billing-freeze",
        operation_desc=f"短剧任务正式冻结积分 {amount_points:.2f}",
        extra_payload={
            "project_id": int(row.source_project_id or 0),
            "run_id": _safe_text(row.run_id, ""),
            "pricing_status": item.pricing_status,
            "task_status": item.task_status,
            "stage": _safe_text(row.stage, ""),
            "points_per_yuan": int(pricing_snapshot.config.points_per_yuan),
            "user_price_basis": pricing_snapshot.config.user_price_basis,
            "user_price_rate": round(float(pricing_snapshot.config.user_price_rate), 4),
            "freeze_buffer_rate": round(float(pricing_snapshot.config.freeze_buffer_rate), 4),
            "operating_snapshot": _build_operating_snapshot_payload(
                pricing_snapshot=pricing_snapshot,
                module_key=POINTS_BILLING_MODULE_DREAMWEAVER,
                basis_yuan=_to_non_negative_float(item.estimated_yuan),
                provider_key=None,
            ),
        },
    )


def record_dreamweaver_billing_settle(
    *,
    db: Session,
    run_id: str,
) -> AdminOperationLog | None:
    row = (
        db.query(
            DreamweaverProject.id.label("id"),
            DreamweaverProject.run_id.label("run_id"),
            DreamweaverProject.source_project_id.label("source_project_id"),
            DreamweaverProject.user_id.label("target_user_id"),
            DreamweaverProject.status.label("status"),
            DreamweaverProject.stage.label("stage"),
            DreamweaverProject.contract_json.label("contract_json"),
            DreamweaverProject.created_at.label("created_at"),
            DreamweaverProject.updated_at.label("updated_at"),
            Project.title.label("project_title"),
            User.username.label("target_username"),
        )
        .join(Project, Project.id == DreamweaverProject.source_project_id)
        .join(User, User.id == DreamweaverProject.user_id)
        .filter(DreamweaverProject.run_id == run_id)
        .first()
    )
    if row is None:
        return None

    billing_key = build_dreamweaver_billing_key(_safe_text(row.run_id, ""))
    existing_logs = _list_billing_logs_for_key(
        db=db,
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
    )
    if _latest_event_kind(existing_logs, billing_key=billing_key) == POINTS_BILLING_EVENT_KIND_SETTLE:
        return None

    pricing_snapshot = get_points_pricing_policy_snapshot(db=db)
    task_billing = build_user_center_task_billing_overview(
        audiobook_rows=[],
        dreamweaver_rows=[row],
        chapter_rows=[],
        pricing_config=pricing_snapshot.config,
    )
    if not task_billing.items:
        return None

    item = task_billing.items[0]
    amount_points = _to_non_negative_float(item.actual_points)
    amount_yuan = _to_non_negative_float(item.actual_yuan)
    if amount_points <= 0 or amount_yuan <= 0:
        return record_dreamweaver_billing_release(
            db=db,
            run_id=run_id,
            reason="\u77ed\u5267\u4efb\u52a1\u5b8c\u6210\u4f46\u672a\u4ea7\u751f\u53ef\u7ed3\u7b97\u6210\u672c\uff0c\u5df2\u91ca\u653e\u51bb\u7ed3\u79ef\u5206\u3002",
        )

    return _create_points_billing_event_log(
        db=db,
        actor_user_id=int(row.target_user_id or 0),
        actor_username=_safe_text(row.target_username, "system"),
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
        module_key=POINTS_BILLING_MODULE_DREAMWEAVER,
        event_kind=POINTS_BILLING_EVENT_KIND_SETTLE,
        operation_type=POINTS_BILLING_SETTLE_OPERATION_TYPE,
        amount_points=amount_points,
        amount_yuan=amount_yuan,
        title=_safe_text(item.title, f"短剧运行 {row.run_id}"),
        summary=_safe_text(item.summary, "\u77ed\u5267\u4efb\u52a1\u5df2\u6309\u6700\u7ec8\u5feb\u7167\u5b8c\u6210\u79ef\u5206\u7ed3\u7b97\u3002"),
        action_path=item.action_path,
        action_label=item.action_label,
        request_context=None,
        default_request_method="SYSTEM",
        default_request_path=f"/internal/dreamweaver/{row.run_id}/billing-settle",
        operation_desc=f"短剧任务完成积分结算 {amount_points:.2f}",
        extra_payload={
            "project_id": int(row.source_project_id or 0),
            "run_id": _safe_text(row.run_id, ""),
            "pricing_status": item.pricing_status,
            "task_status": item.task_status,
            "stage": _safe_text(row.stage, ""),
            "points_per_yuan": int(pricing_snapshot.config.points_per_yuan),
            "user_price_basis": pricing_snapshot.config.user_price_basis,
            "user_price_rate": round(float(pricing_snapshot.config.user_price_rate), 4),
            "operating_snapshot": _build_operating_snapshot_payload(
                pricing_snapshot=pricing_snapshot,
                module_key=POINTS_BILLING_MODULE_DREAMWEAVER,
                basis_yuan=amount_yuan,
                provider_key=None,
            ),
        },
    )


def record_dreamweaver_billing_release(
    *,
    db: Session,
    run_id: str,
    reason: str,
) -> AdminOperationLog | None:
    row = (
        db.query(
            DreamweaverProject.id.label("id"),
            DreamweaverProject.run_id.label("run_id"),
            DreamweaverProject.source_project_id.label("source_project_id"),
            DreamweaverProject.user_id.label("target_user_id"),
            Project.title.label("project_title"),
            User.username.label("target_username"),
        )
        .join(Project, Project.id == DreamweaverProject.source_project_id)
        .join(User, User.id == DreamweaverProject.user_id)
        .filter(DreamweaverProject.run_id == run_id)
        .first()
    )
    if row is None:
        return None

    billing_key = build_dreamweaver_billing_key(_safe_text(row.run_id, ""))
    existing_logs = _list_billing_logs_for_key(
        db=db,
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
    )
    active_freeze_log = _resolve_active_freeze_log(existing_logs, billing_key=billing_key)
    if active_freeze_log is None:
        return None

    freeze_payload = getattr(active_freeze_log, "request_params", None) or {}
    amount_points = _to_non_negative_float(freeze_payload.get("amount_points"))
    amount_yuan = _to_non_negative_float(freeze_payload.get("amount_yuan"))
    action_path = _safe_text(freeze_payload.get("action_path"), "") or f"/drama/{int(row.source_project_id or 0)}"
    action_label = _safe_text(freeze_payload.get("action_label"), "") or "\u67e5\u770b\u77ed\u5267\u6a21\u5757"

    return _create_points_billing_event_log(
        db=db,
        actor_user_id=int(row.target_user_id or 0),
        actor_username=_safe_text(row.target_username, "system"),
        target_user_id=int(row.target_user_id or 0),
        billing_key=billing_key,
        module_key=POINTS_BILLING_MODULE_DREAMWEAVER,
        event_kind=POINTS_BILLING_EVENT_KIND_RELEASE,
        operation_type=POINTS_BILLING_RELEASE_OPERATION_TYPE,
        amount_points=amount_points,
        amount_yuan=amount_yuan,
        title=_safe_text(freeze_payload.get("title"), f"短剧运行 {row.run_id}"),
        summary=_safe_text(reason, "\u77ed\u5267\u4efb\u52a1\u5df2\u91ca\u653e\u51bb\u7ed3\u79ef\u5206\u3002"),
        action_path=action_path,
        action_label=action_label,
        request_context=None,
        default_request_method="SYSTEM",
        default_request_path=f"/internal/dreamweaver/{row.run_id}/billing-release",
        operation_desc=f"短剧任务释放冻结积分 {amount_points:.2f}",
        extra_payload={
            "project_id": int(row.source_project_id or 0),
            "run_id": _safe_text(row.run_id, ""),
        },
    )
