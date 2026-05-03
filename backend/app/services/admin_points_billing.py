from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.admin_log import AdminOperationLog
from app.schemas.admin import (
    AdminPointsBillingModuleSummaryResponse,
    AdminPointsBillingSummaryResponse,
    SystemPointsPricingOperatingSnapshotResponse,
    UserPointsBillingEventResponse,
)
from app.services.user_center_points_events import (
    POINTS_BILLING_EVENT_KIND_FREEZE,
    POINTS_BILLING_EVENT_KIND_RELEASE,
    POINTS_BILLING_EVENT_KIND_SETTLE,
    POINTS_BILLING_MODULE_ASSET_STUDIO,
    POINTS_BILLING_MODULE_AUDIOBOOK,
    POINTS_BILLING_MODULE_BOOK_PARSER,
    POINTS_BILLING_MODULE_DREAMWEAVER,
    POINTS_BILLING_MODULE_NOVEL,
    POINTS_BILLING_OPERATION_TYPES,
    POINTS_BILLING_RESOURCE_TYPE,
)


POINTS_BILLING_MODULE_LABELS = {
    POINTS_BILLING_MODULE_AUDIOBOOK: "有声书",
    POINTS_BILLING_MODULE_DREAMWEAVER: "短剧",
    POINTS_BILLING_MODULE_NOVEL: "小说协同",
    POINTS_BILLING_MODULE_BOOK_PARSER: "拆书分析",
    POINTS_BILLING_MODULE_ASSET_STUDIO: "资产生成",
}

POINTS_BILLING_EVENT_LABELS = {
    POINTS_BILLING_EVENT_KIND_FREEZE: "冻结",
    POINTS_BILLING_EVENT_KIND_SETTLE: "结算",
    POINTS_BILLING_EVENT_KIND_RELEASE: "释放",
}

POINTS_BILLING_EVENT_KINDS = {
    POINTS_BILLING_EVENT_KIND_FREEZE,
    POINTS_BILLING_EVENT_KIND_SETTLE,
    POINTS_BILLING_EVENT_KIND_RELEASE,
}

POINTS_BILLING_MARGIN_STATUSES = {"healthy", "warning", "negative"}
POINTS_BILLING_SUMMARY_RECENT_DAYS = 7


def _safe_text(value: object | None, fallback: str = "") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _optional_int(value: object | None) -> int | None:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _optional_float(value: object | None) -> float | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount


def _request_payload(log: AdminOperationLog) -> Mapping[str, object]:
    payload = log.request_params or {}
    return payload if isinstance(payload, Mapping) else {}


def _normalize_module_key(value: object | None) -> str | None:
    normalized = _safe_text(value).lower()
    return normalized or None


def _normalize_event_kind(value: object | None) -> str | None:
    normalized = _safe_text(value).lower()
    if normalized not in POINTS_BILLING_EVENT_KINDS:
        return None
    return normalized


def _normalize_margin_status(value: object | None) -> str | None:
    normalized = _safe_text(value).lower()
    if normalized not in POINTS_BILLING_MARGIN_STATUSES:
        return None
    return normalized


def _normalize_created_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _compute_blended_margin_rate(
    total_user_billed_yuan: float,
    total_platform_gross_profit_yuan: float,
) -> float | None:
    if total_user_billed_yuan <= 0:
        return None
    return total_platform_gross_profit_yuan / total_user_billed_yuan


def points_billing_module_label(module_key: object | None) -> str:
    normalized = _normalize_module_key(module_key)
    if normalized is None:
        return "未分类模块"
    return POINTS_BILLING_MODULE_LABELS.get(normalized, normalized)


def points_billing_event_label(event_kind: object | None) -> str:
    normalized = _normalize_event_kind(event_kind)
    if normalized is None:
        return "未知事件"
    return POINTS_BILLING_EVENT_LABELS.get(normalized, normalized)


def build_points_billing_operating_snapshot_response(
    payload: Mapping[str, object] | None,
    *,
    fallback_module_key: str | None = None,
) -> SystemPointsPricingOperatingSnapshotResponse | None:
    if not isinstance(payload, Mapping):
        return None

    normalized_payload = dict(payload)
    module_key = _normalize_module_key(normalized_payload.get("module_key")) or _normalize_module_key(fallback_module_key) or "unknown"
    normalized_payload["module_key"] = module_key
    normalized_payload["module_label"] = points_billing_module_label(module_key)

    try:
        return SystemPointsPricingOperatingSnapshotResponse.model_validate(normalized_payload)
    except Exception:
        return None


def _log_operating_snapshot(log: AdminOperationLog) -> SystemPointsPricingOperatingSnapshotResponse | None:
    payload = _request_payload(log)
    module_key = _normalize_module_key(payload.get("module_key"))
    return build_points_billing_operating_snapshot_response(
        payload.get("operating_snapshot") if isinstance(payload, Mapping) else None,
        fallback_module_key=module_key,
    )


def points_billing_log_to_response(log: AdminOperationLog) -> UserPointsBillingEventResponse:
    payload = _request_payload(log)
    module_key = _normalize_module_key(payload.get("module_key")) or "unknown"
    event_kind = _normalize_event_kind(payload.get("event_kind")) or POINTS_BILLING_EVENT_KIND_FREEZE
    operating_snapshot = _log_operating_snapshot(log)

    return UserPointsBillingEventResponse(
        id=log.id,
        target_user_id=int(log.resource_id or payload.get("target_user_id") or 0),
        operator_user_id=log.user_id,
        operator_username=_safe_text(log.username, "system"),
        operation_type=_safe_text(log.operation_type),
        module_key=module_key,
        module_label=points_billing_module_label(module_key),
        event_kind=event_kind,
        event_label=points_billing_event_label(event_kind),
        billing_key=_safe_text(payload.get("billing_key")),
        title=_safe_text(payload.get("title"), _safe_text(log.operation_desc)),
        summary=_safe_text(payload.get("summary")),
        amount_points=float(payload.get("amount_points") or 0),
        amount_yuan=_optional_float(payload.get("amount_yuan")),
        pricing_status=_safe_text(payload.get("pricing_status")) or None,
        task_status=_safe_text(payload.get("task_status")) or None,
        project_id=_optional_int(payload.get("project_id")),
        audiobook_project_id=_optional_int(payload.get("audiobook_project_id")),
        run_id=_safe_text(payload.get("run_id")) or None,
        stage=_safe_text(payload.get("stage")) or None,
        action_path=_safe_text(payload.get("action_path")) or None,
        action_label=_safe_text(payload.get("action_label")) or None,
        created_at=log.created_at,
        operating_snapshot=operating_snapshot,
    )


def list_all_points_billing_logs(
    *,
    db: Session,
    limit: int | None = None,
) -> list[AdminOperationLog]:
    query = (
        db.query(AdminOperationLog)
        .filter(
            AdminOperationLog.operation_type.in_(POINTS_BILLING_OPERATION_TYPES),
            AdminOperationLog.resource_type == POINTS_BILLING_RESOURCE_TYPE,
            AdminOperationLog.response_status < 400,
        )
        .order_by(AdminOperationLog.created_at.desc(), AdminOperationLog.id.desc())
    )

    if limit is not None and int(limit) > 0:
        query = query.limit(int(limit))

    return query.all()


def filter_points_billing_logs(
    logs: Sequence[AdminOperationLog],
    *,
    user_id: int | None = None,
    module_key: str | None = None,
    event_kind: str | None = None,
    margin_status: str | None = None,
    keyword: str | None = None,
) -> list[AdminOperationLog]:
    normalized_module_key = _normalize_module_key(module_key)
    normalized_event_kind = _normalize_event_kind(event_kind)
    normalized_margin_status = _normalize_margin_status(margin_status)
    normalized_keyword = _safe_text(keyword).lower()

    filtered: list[AdminOperationLog] = []
    for log in logs:
        payload = _request_payload(log)
        target_user_id = _optional_int(log.resource_id or payload.get("target_user_id"))
        if user_id is not None and target_user_id != int(user_id):
            continue

        log_module_key = _normalize_module_key(payload.get("module_key"))
        if normalized_module_key and log_module_key != normalized_module_key:
            continue

        log_event_kind = _normalize_event_kind(payload.get("event_kind"))
        if normalized_event_kind and log_event_kind != normalized_event_kind:
            continue

        log_margin_status = None
        operating_snapshot = _log_operating_snapshot(log)
        if operating_snapshot is not None:
            log_margin_status = _normalize_margin_status(operating_snapshot.margin_status)
        if normalized_margin_status and log_margin_status != normalized_margin_status:
            continue

        if normalized_keyword:
            haystacks = [
                _safe_text(log.username).lower(),
                _safe_text(payload.get("billing_key")).lower(),
                _safe_text(payload.get("title")).lower(),
                _safe_text(payload.get("summary")).lower(),
                _safe_text(payload.get("run_id")).lower(),
            ]
            if not any(normalized_keyword in haystack for haystack in haystacks if haystack):
                continue

        filtered.append(log)

    return filtered


def paginate_points_billing_logs(
    logs: Sequence[AdminOperationLog],
    *,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[AdminOperationLog]]:
    normalized_page = max(int(page or 1), 1)
    normalized_page_size = min(max(int(page_size or 20), 1), 100)
    start = (normalized_page - 1) * normalized_page_size
    end = start + normalized_page_size
    paginated_logs = list(logs[start:end])
    return len(logs), paginated_logs


def summarize_points_billing_logs(
    logs: Sequence[AdminOperationLog],
    *,
    user_id: int | None = None,
    module_key: str | None = None,
    keyword: str | None = None,
) -> AdminPointsBillingSummaryResponse:
    settle_logs = filter_points_billing_logs(
        logs,
        user_id=user_id,
        module_key=module_key,
        event_kind=POINTS_BILLING_EVENT_KIND_SETTLE,
        keyword=keyword,
    )

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=POINTS_BILLING_SUMMARY_RECENT_DAYS)
    recent_7d_settle_count = 0
    warning_event_count = 0
    negative_event_count = 0
    total_user_billed_yuan = 0.0
    total_platform_gross_profit_yuan = 0.0
    module_buckets: dict[str, dict[str, float | int | str]] = {}

    for log in settle_logs:
        payload = _request_payload(log)
        current_module_key = _normalize_module_key(payload.get("module_key")) or "unknown"
        module_bucket = module_buckets.setdefault(
            current_module_key,
            {
                "module_key": current_module_key,
                "module_label": points_billing_module_label(current_module_key),
                "settle_event_count": 0,
                "warning_event_count": 0,
                "negative_event_count": 0,
                "total_user_billed_yuan": 0.0,
                "total_platform_gross_profit_yuan": 0.0,
            },
        )
        module_bucket["settle_event_count"] = int(module_bucket["settle_event_count"]) + 1

        created_at = _normalize_created_at(log.created_at)
        if created_at is not None and created_at >= recent_cutoff:
            recent_7d_settle_count += 1

        operating_snapshot = _log_operating_snapshot(log)
        if operating_snapshot is None:
            continue

        billed_yuan = float(operating_snapshot.user_billed_yuan)
        gross_profit_yuan = float(operating_snapshot.platform_gross_profit_yuan)
        total_user_billed_yuan += billed_yuan
        total_platform_gross_profit_yuan += gross_profit_yuan
        module_bucket["total_user_billed_yuan"] = float(module_bucket["total_user_billed_yuan"]) + billed_yuan
        module_bucket["total_platform_gross_profit_yuan"] = (
            float(module_bucket["total_platform_gross_profit_yuan"]) + gross_profit_yuan
        )

        if operating_snapshot.margin_status == "warning":
            warning_event_count += 1
            module_bucket["warning_event_count"] = int(module_bucket["warning_event_count"]) + 1
        elif operating_snapshot.margin_status == "negative":
            negative_event_count += 1
            module_bucket["negative_event_count"] = int(module_bucket["negative_event_count"]) + 1

    module_summaries = sorted(
        (
            AdminPointsBillingModuleSummaryResponse(
                module_key=str(bucket["module_key"]),
                module_label=str(bucket["module_label"]),
                settle_event_count=int(bucket["settle_event_count"]),
                warning_event_count=int(bucket["warning_event_count"]),
                negative_event_count=int(bucket["negative_event_count"]),
                total_user_billed_yuan=float(bucket["total_user_billed_yuan"]),
                total_platform_gross_profit_yuan=float(bucket["total_platform_gross_profit_yuan"]),
                blended_margin_rate=_compute_blended_margin_rate(
                    float(bucket["total_user_billed_yuan"]),
                    float(bucket["total_platform_gross_profit_yuan"]),
                ),
            )
            for bucket in module_buckets.values()
        ),
        key=lambda item: (
            -item.negative_event_count,
            -item.warning_event_count,
            -item.total_user_billed_yuan,
            item.module_key,
        ),
    )

    return AdminPointsBillingSummaryResponse(
        recent_7d_settle_count=recent_7d_settle_count,
        settle_event_count=len(settle_logs),
        warning_event_count=warning_event_count,
        negative_event_count=negative_event_count,
        total_user_billed_yuan=total_user_billed_yuan,
        total_platform_gross_profit_yuan=total_platform_gross_profit_yuan,
        blended_margin_rate=_compute_blended_margin_rate(
            total_user_billed_yuan,
            total_platform_gross_profit_yuan,
        ),
        module_summaries=module_summaries,
    )


def query_points_billing_logs_page_from_logs(
    logs: Sequence[AdminOperationLog],
    *,
    page: int = 1,
    page_size: int = 20,
    user_id: int | None = None,
    module_key: str | None = None,
    event_kind: str | None = None,
    margin_status: str | None = None,
    keyword: str | None = None,
) -> tuple[int, list[AdminOperationLog]]:
    filtered_logs = filter_points_billing_logs(
        logs,
        user_id=user_id,
        module_key=module_key,
        event_kind=event_kind,
        margin_status=margin_status,
        keyword=keyword,
    )
    return paginate_points_billing_logs(
        filtered_logs,
        page=page,
        page_size=page_size,
    )


def query_points_billing_logs_page(
    *,
    db: Session,
    page: int = 1,
    page_size: int = 20,
    user_id: int | None = None,
    module_key: str | None = None,
    event_kind: str | None = None,
    margin_status: str | None = None,
    keyword: str | None = None,
) -> tuple[int, list[AdminOperationLog]]:
    logs = list_all_points_billing_logs(db=db)
    return query_points_billing_logs_page_from_logs(
        logs,
        page=page,
        page_size=page_size,
        user_id=user_id,
        module_key=module_key,
        event_kind=event_kind,
        margin_status=margin_status,
        keyword=keyword,
    )
