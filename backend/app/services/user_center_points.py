from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

from sqlalchemy.orm import Session

from app.models.admin_log import AdminOperationLog
from app.utils.datetime_utils import ensure_utc_datetime, parse_datetime_utc, utc_now


RUNNING_STATUSES = {"queued", "running", "waiting", "pending", "processing"}
COMPLETED_STATUSES = {"completed", "success", "approved"}

POINTS_BILLING_EVENT_KIND_FREEZE = "freeze"
POINTS_BILLING_EVENT_KIND_SETTLE = "settle"
POINTS_BILLING_EVENT_KIND_RELEASE = "release"

POINTS_RULES_OPERATION_TYPE = "POINTS_RULES_UPDATE"
POINTS_RULES_RESOURCE_TYPE = "SYSTEM_POINTS_RULES"
POINTS_RULES_RESOURCE_ID = 0

POINTS_RULE_FLOAT_FIELDS = {
    "reusable_asset_reward",
    "deliverable_asset_reward",
    "audiobook_completion_reward",
    "dreamweaver_completion_reward",
    "running_audiobook_frozen",
    "running_dreamweaver_frozen",
}


def build_audiobook_billing_key(audiobook_project_id: int) -> str:
    return f"audiobook:{max(int(audiobook_project_id or 0), 0)}"


def build_dreamweaver_billing_key(run_id: str) -> str:
    normalized_run_id = str(run_id or "").strip()
    return f"dreamweaver:{normalized_run_id}" if normalized_run_id else "dreamweaver:"


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _normalize_status(value: object | None) -> str:
    return str(value or "").strip().lower()


def _to_non_negative_float(value: object | None, fallback: float) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(amount):
        return fallback
    return max(amount, 0.0)


def _to_int_with_minimum(value: object | None, fallback: int, *, minimum: int) -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(amount, minimum)


def _safe_text(value: object | None, fallback: str) -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


@dataclass(frozen=True)
class UserCenterPointsRuleConfig:
    reusable_asset_reward: float = _env_float("USER_CENTER_POINTS_REUSABLE_ASSET_REWARD", 3.0)
    deliverable_asset_reward: float = _env_float("USER_CENTER_POINTS_DELIVERABLE_ASSET_REWARD", 10.0)
    audiobook_completion_reward: float = _env_float("USER_CENTER_POINTS_AUDIOBOOK_COMPLETION_REWARD", 8.0)
    dreamweaver_completion_reward: float = _env_float("USER_CENTER_POINTS_DREAMWEAVER_COMPLETION_REWARD", 5.0)
    running_audiobook_frozen: float = _env_float("USER_CENTER_POINTS_RUNNING_AUDIOBOOK_FROZEN", 2.0)
    running_dreamweaver_frozen: float = _env_float("USER_CENTER_POINTS_RUNNING_DREAMWEAVER_FROZEN", 2.0)
    reward_ttl_days: int = _env_int("USER_CENTER_POINTS_REWARD_TTL_DAYS", 30)
    expiring_notice_days: int = _env_int("USER_CENTER_POINTS_EXPIRING_NOTICE_DAYS", 7)

    def to_payload(self) -> dict[str, float | int]:
        return {
            "reusable_asset_reward": round(float(self.reusable_asset_reward), 2),
            "deliverable_asset_reward": round(float(self.deliverable_asset_reward), 2),
            "audiobook_completion_reward": round(float(self.audiobook_completion_reward), 2),
            "dreamweaver_completion_reward": round(float(self.dreamweaver_completion_reward), 2),
            "running_audiobook_frozen": round(float(self.running_audiobook_frozen), 2),
            "running_dreamweaver_frozen": round(float(self.running_dreamweaver_frozen), 2),
            "reward_ttl_days": int(self.reward_ttl_days),
            "expiring_notice_days": int(self.expiring_notice_days),
        }


@dataclass(frozen=True)
class UserCenterPointsRuleSnapshot:
    config: UserCenterPointsRuleConfig
    source: str
    updated_at: datetime | None = None
    updated_by_user_id: int | None = None
    updated_by_username: str | None = None
    operation_log_id: int | None = None


@dataclass(frozen=True)
class UserCenterPointsAccountSnapshot:
    balance: float
    frozen: float
    expiring_soon: float
    connected_source_count: int
    connected_source_keys: tuple[str, ...]


@dataclass(frozen=True)
class UserCenterPointsEntrySnapshot:
    key: str
    source_key: str
    title: str
    summary: str
    amount: float
    direction: str
    status: str
    occurred_at: datetime | None
    expires_at: datetime | None = None
    action_path: str | None = None
    action_label: str | None = None


@dataclass(frozen=True)
class UserCenterPointsBundleSnapshot:
    account: UserCenterPointsAccountSnapshot
    entries: tuple[UserCenterPointsEntrySnapshot, ...]


@dataclass(frozen=True)
class _RewardEvent:
    key: str
    source_key: str
    title: str
    summary: str
    amount: float
    occurred_at: datetime | None
    expires_at: datetime | None = None
    action_path: str | None = None
    action_label: str | None = None


@dataclass(frozen=True)
class _FrozenEvent:
    key: str
    source_key: str
    title: str
    summary: str
    amount: float
    occurred_at: datetime | None
    action_path: str | None = None
    action_label: str | None = None


@dataclass(frozen=True)
class _PointsBillingEventBundle:
    expense_events: tuple[_RewardEvent, ...]
    frozen_entry_events: tuple[_FrozenEvent, ...]
    active_frozen_events: tuple[_FrozenEvent, ...]
    formal_billing_keys: tuple[str, ...]


def normalize_user_center_points_rule_payload(
    payload: Mapping[str, object] | None,
    *,
    base_config: UserCenterPointsRuleConfig | None = None,
) -> dict[str, float | int]:
    config = base_config or UserCenterPointsRuleConfig()
    normalized = config.to_payload()

    if not isinstance(payload, Mapping):
        return normalized

    for field_name in POINTS_RULE_FLOAT_FIELDS:
        if field_name not in payload:
            continue
        normalized[field_name] = round(
            _to_non_negative_float(payload.get(field_name), float(normalized[field_name])),
            2,
        )

    if "reward_ttl_days" in payload:
        normalized["reward_ttl_days"] = _to_int_with_minimum(
            payload.get("reward_ttl_days"),
            int(normalized["reward_ttl_days"]),
            minimum=1,
        )

    if "expiring_notice_days" in payload:
        normalized["expiring_notice_days"] = _to_int_with_minimum(
            payload.get("expiring_notice_days"),
            int(normalized["expiring_notice_days"]),
            minimum=0,
        )

    return normalized


def resolve_user_center_points_rule_config(
    payload: Mapping[str, object] | None,
    *,
    base_config: UserCenterPointsRuleConfig | None = None,
) -> UserCenterPointsRuleConfig:
    normalized = normalize_user_center_points_rule_payload(payload, base_config=base_config)
    return UserCenterPointsRuleConfig(**normalized)


def _points_rule_log_rank(log: object) -> tuple[float, int]:
    created_at = ensure_utc_datetime(getattr(log, "created_at", None))
    return (
        created_at.timestamp() if created_at else 0.0,
        int(getattr(log, "id", 0) or 0),
    )


def _resolve_latest_points_rule_log(
    *,
    db: Session | None = None,
    logs: list[object] | None = None,
) -> object | None:
    if logs:
        return max(logs, key=_points_rule_log_rank)

    if db is None:
        return None

    return (
        db.query(AdminOperationLog)
        .filter(
            AdminOperationLog.operation_type == POINTS_RULES_OPERATION_TYPE,
            AdminOperationLog.resource_type == POINTS_RULES_RESOURCE_TYPE,
            AdminOperationLog.resource_id == POINTS_RULES_RESOURCE_ID,
            AdminOperationLog.response_status < 400,
        )
        .order_by(AdminOperationLog.created_at.desc(), AdminOperationLog.id.desc())
        .first()
    )


def get_user_center_points_rule_snapshot(
    *,
    db: Session | None = None,
    logs: list[object] | None = None,
) -> UserCenterPointsRuleSnapshot:
    default_config = UserCenterPointsRuleConfig()
    latest_log = _resolve_latest_points_rule_log(db=db, logs=logs)

    if latest_log is None:
        return UserCenterPointsRuleSnapshot(
            config=default_config,
            source="default",
        )

    config = resolve_user_center_points_rule_config(
        getattr(latest_log, "request_params", None) or {},
        base_config=default_config,
    )
    return UserCenterPointsRuleSnapshot(
        config=config,
        source="admin_log",
        updated_at=ensure_utc_datetime(getattr(latest_log, "created_at", None)),
        updated_by_user_id=getattr(latest_log, "user_id", None),
        updated_by_username=str(getattr(latest_log, "username", "") or "").strip() or None,
        operation_log_id=getattr(latest_log, "id", None),
    )


def _resolve_asset_reward(asset: object, config: UserCenterPointsRuleConfig) -> float:
    asset_class = str(getattr(asset, "asset_class", "") or "").strip().lower()
    if asset_class == "deliverable":
        return config.deliverable_asset_reward
    return config.reusable_asset_reward


def _resolve_occurred_at(row: object) -> datetime | None:
    return ensure_utc_datetime(
        getattr(row, "updated_at", None) or getattr(row, "created_at", None),
    )


def _resolve_asset_occurred_at(asset: object) -> datetime | None:
    # Asset rewards should expire from their first availability, not from later metadata edits.
    return ensure_utc_datetime(
        getattr(asset, "created_at", None) or getattr(asset, "updated_at", None),
    )


def _to_finite_float(value: object | None) -> float:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return amount if math.isfinite(amount) else 0.0


def _build_user_asset_reward_events(
    *,
    user_assets: list[object],
    config: UserCenterPointsRuleConfig,
) -> list[_RewardEvent]:
    events: list[_RewardEvent] = []
    for index, asset in enumerate(user_assets, start=1):
        if ensure_utc_datetime(getattr(asset, "archived_at", None)) is not None:
            continue

        reward_amount = _resolve_asset_reward(asset, config)
        if reward_amount <= 0:
            continue

        asset_id = int(getattr(asset, "id", 0) or 0)
        asset_class = str(getattr(asset, "asset_class", "") or "").strip().lower()
        asset_kind = str(getattr(asset, "asset_kind", "") or "").strip()
        asset_class_label = "交付资产" if asset_class == "deliverable" else "复用资产"
        asset_kind_summary = f" · 类型 {asset_kind}" if asset_kind else ""

        events.append(
            _RewardEvent(
                key=f"user-asset-{asset_id or index}",
                source_key="user_assets",
                title=_safe_text(getattr(asset, "title", None), f"{asset_class_label} #{asset_id or index}"),
                summary=f"{asset_class_label}沉淀奖励{asset_kind_summary}",
                amount=reward_amount,
                occurred_at=_resolve_asset_occurred_at(asset),
            )
        )
    return events


def _build_audiobook_events(
    *,
    audiobook_rows: list[object],
    config: UserCenterPointsRuleConfig,
    skip_frozen_billing_keys: set[str] | None = None,
) -> tuple[list[_RewardEvent], list[_FrozenEvent]]:
    reward_events: list[_RewardEvent] = []
    frozen_events: list[_FrozenEvent] = []
    formal_billing_keys = skip_frozen_billing_keys or set()

    for index, row in enumerate(audiobook_rows, start=1):
        row_id = int(getattr(row, "id", 0) or 0)
        project_id = int(getattr(row, "project_id", 0) or 0)
        title = _safe_text(getattr(row, "project_title", None), f"有声书项目 #{row_id or index}")
        status = _normalize_status(getattr(row, "status", None))
        completed_chapters = int(getattr(row, "completed_chapters", 0) or 0)
        total_chapters = int(getattr(row, "total_chapters", 0) or 0)
        occurred_at = _resolve_occurred_at(row)

        if status in COMPLETED_STATUSES and completed_chapters > 0:
            reward_events.append(
                _RewardEvent(
                    key=f"audiobook-reward-{row_id or index}",
                    source_key="audiobook",
                    title=title,
                    summary=f"有声书完成奖励，已完成 {completed_chapters}/{total_chapters} 章节",
                    amount=config.audiobook_completion_reward,
                    occurred_at=occurred_at,
                    action_path=f"/audiobook/{project_id}" if project_id > 0 else "/audiobook-dashboard",
                    action_label="查看有声书项目",
                )
            )
            continue

        if (
            status in RUNNING_STATUSES
            and config.running_audiobook_frozen > 0
            and build_audiobook_billing_key(row_id or index) not in formal_billing_keys
        ):
            frozen_events.append(
                _FrozenEvent(
                    key=f"audiobook-frozen-{row_id or index}",
                    source_key="audiobook",
                    title=title,
                    summary="有声书任务运行中，积分已预留冻结",
                    amount=config.running_audiobook_frozen,
                    occurred_at=occurred_at,
                    action_path=f"/audiobook/{project_id}" if project_id > 0 else "/audiobook-dashboard",
                    action_label="查看有声书项目",
                )
            )

    return reward_events, frozen_events


def _build_dreamweaver_events(
    *,
    dreamweaver_rows: list[object],
    config: UserCenterPointsRuleConfig,
    skip_frozen_billing_keys: set[str] | None = None,
) -> tuple[list[_RewardEvent], list[_FrozenEvent]]:
    reward_events: list[_RewardEvent] = []
    frozen_events: list[_FrozenEvent] = []
    formal_billing_keys = skip_frozen_billing_keys or set()

    for index, row in enumerate(dreamweaver_rows, start=1):
        row_id = int(getattr(row, "id", 0) or 0)
        run_id = _safe_text(getattr(row, "run_id", None), f"run-{row_id or index}")
        project_title = str(getattr(row, "project_title", "") or "").strip()
        title = project_title or f"短剧运行 {run_id}"
        stage = str(getattr(row, "stage", "") or "").strip()
        stage_summary = f" · 阶段 {stage}" if stage else ""
        status = _normalize_status(getattr(row, "status", None))
        occurred_at = _resolve_occurred_at(row)

        if status in COMPLETED_STATUSES:
            reward_events.append(
                _RewardEvent(
                    key=f"dreamweaver-reward-{run_id}",
                    source_key="dreamweaver",
                    title=title,
                    summary=f"短剧完成奖励{stage_summary}",
                    amount=config.dreamweaver_completion_reward,
                    occurred_at=occurred_at,
                    action_path="/drama",
                    action_label="查看短剧模块",
                )
            )
            continue

        if (
            status in RUNNING_STATUSES
            and config.running_dreamweaver_frozen > 0
            and build_dreamweaver_billing_key(run_id) not in formal_billing_keys
        ):
            frozen_events.append(
                _FrozenEvent(
                    key=f"dreamweaver-frozen-{run_id}",
                    source_key="dreamweaver",
                    title=title,
                    summary=f"短剧任务运行中，积分已预留冻结{stage_summary}",
                    amount=config.running_dreamweaver_frozen,
                    occurred_at=occurred_at,
                    action_path="/drama",
                    action_label="查看短剧模块",
                )
            )

    return reward_events, frozen_events


def _manual_adjustment_type_label(adjustment_type: object | None) -> str:
    normalized = str(adjustment_type or "").strip().lower()
    if normalized == "manual_grant":
        return "人工补发"
    if normalized == "recharge":
        return "人工充值"
    if normalized == "manual_deduction":
        return "人工扣减"
    if normalized == "compensation":
        return "补偿调整"
    return "人工调整"


def _build_manual_adjustment_events(*, manual_adjustment_logs: list[object]) -> list[_RewardEvent]:
    events: list[_RewardEvent] = []
    for index, log in enumerate(manual_adjustment_logs, start=1):
        payload = getattr(log, "request_params", None) or {}
        delta = _to_finite_float(payload.get("delta"))
        if delta == 0:
            continue

        log_id = int(getattr(log, "id", 0) or 0)
        adjustment_title = _manual_adjustment_type_label(payload.get("adjustment_type"))
        reason = _safe_text(payload.get("reason"), "管理员进行了积分调整")

        events.append(
            _RewardEvent(
                key=f"manual-adjustment-{log_id or index}",
                source_key="manual_adjustment",
                title=adjustment_title,
                summary=reason,
                amount=delta,
                occurred_at=ensure_utc_datetime(getattr(log, "created_at", None)),
                expires_at=parse_datetime_utc(payload.get("expires_at")),
            )
        )
    return events


def _build_points_billing_bundle(*, billing_event_logs: list[object] | None) -> _PointsBillingEventBundle:
    if not billing_event_logs:
        return _PointsBillingEventBundle(
            expense_events=(),
            frozen_entry_events=(),
            active_frozen_events=(),
            formal_billing_keys=(),
        )

    expense_events: list[_RewardEvent] = []
    frozen_entry_events: list[_FrozenEvent] = []
    active_frozen_events_by_key: dict[str, _FrozenEvent] = {}
    formal_billing_keys: set[str] = set()

    for index, log in enumerate(sorted(billing_event_logs, key=_points_rule_log_rank), start=1):
        payload = getattr(log, "request_params", None) or {}
        billing_key = str(payload.get("billing_key") or "").strip()
        if not billing_key:
            continue

        event_kind = str(payload.get("event_kind") or "").strip().lower()
        if event_kind not in {
            POINTS_BILLING_EVENT_KIND_FREEZE,
            POINTS_BILLING_EVENT_KIND_SETTLE,
            POINTS_BILLING_EVENT_KIND_RELEASE,
        }:
            continue

        formal_billing_keys.add(billing_key)

        source_key = _safe_text(payload.get("module_key"), "billing")
        title = _safe_text(payload.get("title"), "任务积分事件")
        summary = _safe_text(payload.get("summary"), "已记录任务积分事件")
        action_path = _safe_text(payload.get("action_path"), "") or None
        action_label = _safe_text(payload.get("action_label"), "") or None
        occurred_at = ensure_utc_datetime(getattr(log, "created_at", None))
        amount_points = round(_to_finite_float(payload.get("amount_points")), 2)
        log_id = int(getattr(log, "id", 0) or index)

        if event_kind == POINTS_BILLING_EVENT_KIND_FREEZE:
            if amount_points <= 0:
                continue
            frozen_event = _FrozenEvent(
                key=f"points-billing-freeze-{log_id}",
                source_key=source_key,
                title=title,
                summary=summary,
                amount=amount_points,
                occurred_at=occurred_at,
                action_path=action_path,
                action_label=action_label,
            )
            frozen_entry_events.append(frozen_event)
            active_frozen_events_by_key[billing_key] = frozen_event
            continue

        active_frozen_events_by_key.pop(billing_key, None)

        if event_kind == POINTS_BILLING_EVENT_KIND_SETTLE and amount_points > 0:
            expense_events.append(
                _RewardEvent(
                    key=f"points-billing-settle-{log_id}",
                    source_key=source_key,
                    title=title,
                    summary=summary,
                    amount=-amount_points,
                    occurred_at=occurred_at,
                    action_path=action_path,
                    action_label=action_label,
                )
            )

    return _PointsBillingEventBundle(
        expense_events=tuple(expense_events),
        frozen_entry_events=tuple(frozen_entry_events),
        active_frozen_events=tuple(active_frozen_events_by_key.values()),
        formal_billing_keys=tuple(sorted(formal_billing_keys)),
    )


def _build_points_event_snapshots(
    *,
    user_assets: list[object],
    audiobook_rows: list[object],
    dreamweaver_rows: list[object],
    manual_adjustment_logs: list[object] | None,
    billing_event_logs: list[object] | None,
    config: UserCenterPointsRuleConfig,
) -> tuple[list[_RewardEvent], list[_FrozenEvent], list[_FrozenEvent], set[str]]:
    billing_bundle = _build_points_billing_bundle(billing_event_logs=billing_event_logs)
    formal_billing_keys = set(billing_bundle.formal_billing_keys)
    reward_events = _build_user_asset_reward_events(user_assets=user_assets, config=config)
    audiobook_rewards, audiobook_frozen = _build_audiobook_events(
        audiobook_rows=audiobook_rows,
        config=config,
        skip_frozen_billing_keys=formal_billing_keys,
    )
    dreamweaver_rewards, dreamweaver_frozen = _build_dreamweaver_events(
        dreamweaver_rows=dreamweaver_rows,
        config=config,
        skip_frozen_billing_keys=formal_billing_keys,
    )
    manual_adjustment_events = _build_manual_adjustment_events(
        manual_adjustment_logs=list(manual_adjustment_logs or []),
    )

    reward_events.extend(audiobook_rewards)
    reward_events.extend(dreamweaver_rewards)
    reward_events.extend(manual_adjustment_events)
    reward_events.extend(billing_bundle.expense_events)

    frozen_events = [*billing_bundle.frozen_entry_events, *audiobook_frozen, *dreamweaver_frozen]
    active_frozen_events = [*billing_bundle.active_frozen_events, *audiobook_frozen, *dreamweaver_frozen]
    connected_sources = {
        event.source_key
        for event in [*reward_events, *frozen_events]
        if str(event.source_key or "").strip()
    }
    return reward_events, frozen_events, active_frozen_events, connected_sources


def _resolve_reward_event_expires_at(
    event: _RewardEvent,
    *,
    expires_delta: timedelta,
) -> datetime | None:
    if event.expires_at is not None:
        return event.expires_at
    if event.amount > 0 and event.occurred_at is not None:
        return event.occurred_at + expires_delta
    return None


def _points_entry_sort_key(entry: UserCenterPointsEntrySnapshot) -> tuple[float, str]:
    occurred_at = ensure_utc_datetime(entry.occurred_at)
    return (
        occurred_at.timestamp() if occurred_at else 0.0,
        entry.key,
    )


def build_user_center_points_bundle(
    *,
    user_assets: list[object],
    audiobook_rows: list[object],
    dreamweaver_rows: list[object],
    manual_adjustment_logs: list[object] | None = None,
    billing_event_logs: list[object] | None = None,
    config: UserCenterPointsRuleConfig | None = None,
) -> UserCenterPointsBundleSnapshot:
    points_config = config or UserCenterPointsRuleConfig()
    now = utc_now()
    expiring_cutoff = now + timedelta(days=max(points_config.expiring_notice_days, 0))
    expires_delta = timedelta(days=max(points_config.reward_ttl_days, 1))

    reward_events, frozen_events, active_frozen_events, connected_sources = _build_points_event_snapshots(
        user_assets=user_assets,
        audiobook_rows=audiobook_rows,
        dreamweaver_rows=dreamweaver_rows,
        manual_adjustment_logs=manual_adjustment_logs,
        billing_event_logs=billing_event_logs,
        config=points_config,
    )

    entries: list[UserCenterPointsEntrySnapshot] = []
    balance = 0.0
    frozen_total = 0.0
    expiring_soon = 0.0

    for event in reward_events:
        expires_at = _resolve_reward_event_expires_at(event, expires_delta=expires_delta)
        is_expired = bool(expires_at and event.amount > 0 and expires_at <= now)
        direction = "income" if event.amount > 0 else "expense"
        status = "expired" if is_expired else "active"

        entries.append(
            UserCenterPointsEntrySnapshot(
                key=event.key,
                source_key=event.source_key,
                title=event.title,
                summary=event.summary,
                amount=round(event.amount, 2),
                direction=direction,
                status=status,
                occurred_at=event.occurred_at,
                expires_at=expires_at,
                action_path=event.action_path,
                action_label=event.action_label,
            )
        )

        if is_expired:
            continue

        balance += event.amount
        if event.amount > 0 and expires_at and expires_at <= expiring_cutoff:
            expiring_soon += event.amount

    for event in frozen_events:
        entries.append(
            UserCenterPointsEntrySnapshot(
                key=event.key,
                source_key=event.source_key,
                title=event.title,
                summary=event.summary,
                amount=round(event.amount, 2),
                direction="hold",
                status="frozen",
                occurred_at=event.occurred_at,
                expires_at=None,
                action_path=event.action_path,
                action_label=event.action_label,
            )
        )

    for event in active_frozen_events:
        frozen_total += event.amount

    entries.sort(key=_points_entry_sort_key, reverse=True)

    return UserCenterPointsBundleSnapshot(
        account=UserCenterPointsAccountSnapshot(
            balance=round(balance, 2),
            frozen=round(frozen_total, 2),
            expiring_soon=round(expiring_soon, 2),
            connected_source_count=len(connected_sources),
            connected_source_keys=tuple(sorted(connected_sources)),
        ),
        entries=tuple(entries),
    )


def build_user_center_points_account(
    *,
    user_assets: list[object],
    audiobook_rows: list[object],
    dreamweaver_rows: list[object],
    manual_adjustment_logs: list[object] | None = None,
    billing_event_logs: list[object] | None = None,
    config: UserCenterPointsRuleConfig | None = None,
) -> UserCenterPointsAccountSnapshot:
    return build_user_center_points_bundle(
        user_assets=user_assets,
        audiobook_rows=audiobook_rows,
        dreamweaver_rows=dreamweaver_rows,
        manual_adjustment_logs=manual_adjustment_logs,
        billing_event_logs=billing_event_logs,
        config=config,
    ).account
