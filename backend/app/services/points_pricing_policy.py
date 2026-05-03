from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from sqlalchemy.orm import Session

from app.models.admin_log import AdminOperationLog
from app.utils.datetime_utils import ensure_utc_datetime


POINTS_PRICING_POLICY_OPERATION_TYPE = "POINTS_PRICING_POLICY_UPDATE"
POINTS_PRICING_POLICY_RESOURCE_TYPE = "SYSTEM_POINTS_PRICING_POLICY"
POINTS_PRICING_POLICY_RESOURCE_ID = 0
POINTS_PRICING_POLICY_PREVIEW_BASIS_YUAN = 1.0

POINTS_PRICING_POLICY_OPERATING_MODULES: tuple[tuple[str, str], ...] = (
    ("audiobook", "有声书"),
    ("dreamweaver", "短剧"),
    ("novel", "小说协同"),
    ("book_parser", "拆书分析"),
    ("asset_studio", "资产生成"),
)

POINTS_PRICING_BASIS_OPTIONS = {"public_list_price", "standard_price_table"}


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


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _to_non_negative_float(value: object | None, fallback: float) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(amount, 0.0)


def _to_float_in_range(value: object | None, fallback: float, *, minimum: float, maximum: float) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(amount, minimum), maximum)


def _to_int_with_minimum(value: object | None, fallback: int, *, minimum: int) -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(amount, minimum)


def _to_bool(value: object | None, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return fallback


def _normalize_pricing_basis(value: object | None, fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in POINTS_PRICING_BASIS_OPTIONS:
        return normalized
    return fallback


def _normalize_env_token(value: object | None) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    normalized_chars = [char if char.isalnum() else "_" for char in raw]
    normalized = "".join(normalized_chars).strip("_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized


@dataclass(frozen=True)
class PointsPricingPolicyConfig:
    points_per_yuan: int = _env_int("POINTS_POLICY_POINTS_PER_YUAN", 100)
    user_price_basis: str = str(os.getenv("POINTS_POLICY_USER_PRICE_BASIS", "public_list_price") or "public_list_price")
    user_price_rate: float = _env_float("POINTS_POLICY_USER_PRICE_RATE", 1.0)
    provider_discount_capture_rate: float = _env_float("POINTS_POLICY_PROVIDER_DISCOUNT_CAPTURE_RATE", 1.0)
    freeze_buffer_rate: float = _env_float("POINTS_POLICY_FREEZE_BUFFER_RATE", 0.05)
    margin_warning_rate: float = _env_float("POINTS_POLICY_MARGIN_WARNING_RATE", 0.15)
    negative_margin_block_enabled: bool = _env_bool("POINTS_POLICY_NEGATIVE_MARGIN_BLOCK_ENABLED", True)

    def to_payload(self) -> dict[str, int | float | bool | str]:
        return {
            "points_per_yuan": max(int(self.points_per_yuan), 1),
            "user_price_basis": _normalize_pricing_basis(self.user_price_basis, "public_list_price"),
            "user_price_rate": round(max(float(self.user_price_rate), 0.0), 4),
            "provider_discount_capture_rate": round(
                min(max(float(self.provider_discount_capture_rate), 0.0), 1.0),
                4,
            ),
            "freeze_buffer_rate": round(min(max(float(self.freeze_buffer_rate), 0.0), 1.0), 4),
            "margin_warning_rate": round(min(max(float(self.margin_warning_rate), 0.0), 1.0), 4),
            "negative_margin_block_enabled": bool(self.negative_margin_block_enabled),
        }


@dataclass(frozen=True)
class PointsPricingPolicySnapshot:
    config: PointsPricingPolicyConfig
    source: str
    updated_at: datetime | None = None
    updated_by_user_id: int | None = None
    updated_by_username: str | None = None
    operation_log_id: int | None = None


@dataclass(frozen=True)
class PointsBusinessSettlementSnapshot:
    module_key: str
    provider_key: str | None
    user_basis_yuan: float
    user_billed_yuan: float
    supplier_list_price_yuan: float
    supplier_discount_rate: float
    supplier_discount_rate_source: str
    supplier_discounted_cost_yuan: float
    supplier_discount_yuan: float
    captured_discount_yuan: float
    shared_discount_yuan: float
    policy_target_user_billed_yuan: float
    policy_alignment_gap_yuan: float
    platform_gross_profit_yuan: float
    platform_margin_rate: float | None
    margin_status: str
    negative_margin_blocked: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "module_key": self.module_key,
            "provider_key": self.provider_key,
            "user_basis_yuan": round(float(self.user_basis_yuan), 2),
            "user_billed_yuan": round(float(self.user_billed_yuan), 2),
            "supplier_list_price_yuan": round(float(self.supplier_list_price_yuan), 2),
            "supplier_discount_rate": round(float(self.supplier_discount_rate), 4),
            "supplier_discount_rate_source": self.supplier_discount_rate_source,
            "supplier_discounted_cost_yuan": round(float(self.supplier_discounted_cost_yuan), 2),
            "supplier_discount_yuan": round(float(self.supplier_discount_yuan), 2),
            "captured_discount_yuan": round(float(self.captured_discount_yuan), 2),
            "shared_discount_yuan": round(float(self.shared_discount_yuan), 2),
            "policy_target_user_billed_yuan": round(float(self.policy_target_user_billed_yuan), 2),
            "policy_alignment_gap_yuan": round(float(self.policy_alignment_gap_yuan), 2),
            "platform_gross_profit_yuan": round(float(self.platform_gross_profit_yuan), 2),
            "platform_margin_rate": None
            if self.platform_margin_rate is None
            else round(float(self.platform_margin_rate), 4),
            "margin_status": self.margin_status,
            "negative_margin_blocked": bool(self.negative_margin_blocked),
        }


def normalize_points_pricing_policy_payload(
    payload: Mapping[str, object] | None,
    *,
    base_config: PointsPricingPolicyConfig | None = None,
) -> dict[str, int | float | bool | str]:
    config = base_config or PointsPricingPolicyConfig()
    normalized = config.to_payload()

    if not isinstance(payload, Mapping):
        return normalized

    if "points_per_yuan" in payload:
        normalized["points_per_yuan"] = _to_int_with_minimum(
            payload.get("points_per_yuan"),
            int(normalized["points_per_yuan"]),
            minimum=1,
        )
    if "user_price_basis" in payload:
        normalized["user_price_basis"] = _normalize_pricing_basis(
            payload.get("user_price_basis"),
            str(normalized["user_price_basis"]),
        )
    if "user_price_rate" in payload:
        normalized["user_price_rate"] = round(
            _to_non_negative_float(payload.get("user_price_rate"), float(normalized["user_price_rate"])),
            4,
        )
    if "provider_discount_capture_rate" in payload:
        normalized["provider_discount_capture_rate"] = round(
            _to_float_in_range(
                payload.get("provider_discount_capture_rate"),
                float(normalized["provider_discount_capture_rate"]),
                minimum=0.0,
                maximum=1.0,
            ),
            4,
        )
    if "freeze_buffer_rate" in payload:
        normalized["freeze_buffer_rate"] = round(
            _to_float_in_range(
                payload.get("freeze_buffer_rate"),
                float(normalized["freeze_buffer_rate"]),
                minimum=0.0,
                maximum=1.0,
            ),
            4,
        )
    if "margin_warning_rate" in payload:
        normalized["margin_warning_rate"] = round(
            _to_float_in_range(
                payload.get("margin_warning_rate"),
                float(normalized["margin_warning_rate"]),
                minimum=0.0,
                maximum=1.0,
            ),
            4,
        )
    if "negative_margin_block_enabled" in payload:
        normalized["negative_margin_block_enabled"] = _to_bool(
            payload.get("negative_margin_block_enabled"),
            bool(normalized["negative_margin_block_enabled"]),
        )

    return normalized


def resolve_points_pricing_policy_config(
    payload: Mapping[str, object] | None,
    *,
    base_config: PointsPricingPolicyConfig | None = None,
) -> PointsPricingPolicyConfig:
    normalized = normalize_points_pricing_policy_payload(payload, base_config=base_config)
    return PointsPricingPolicyConfig(**normalized)


def resolve_provider_discount_rate(
    *,
    module_key: str,
    provider_key: str | None = None,
) -> tuple[float, str]:
    normalized_module = _normalize_env_token(module_key)
    normalized_provider = _normalize_env_token(provider_key)

    candidate_names: list[str] = []
    if normalized_module and normalized_provider:
        candidate_names.append(f"POINTS_POLICY_{normalized_module}_PROVIDER_DISCOUNT_RATE_{normalized_provider}")
    if normalized_module:
        candidate_names.append(f"POINTS_POLICY_{normalized_module}_PROVIDER_DISCOUNT_RATE_DEFAULT")
    if normalized_provider:
        candidate_names.append(f"POINTS_POLICY_PROVIDER_DISCOUNT_RATE_{normalized_provider}")
    candidate_names.append("POINTS_POLICY_PROVIDER_DISCOUNT_RATE_DEFAULT")

    for env_name in candidate_names:
        raw = str(os.getenv(env_name, "") or "").strip()
        if not raw:
            continue
        try:
            discount_rate = float(raw)
        except (TypeError, ValueError):
            continue
        return min(max(discount_rate, 0.0), 1.0), f"env:{env_name}"

    return 0.0, "default"


def build_points_business_settlement_snapshot(
    *,
    pricing_config: PointsPricingPolicyConfig,
    module_key: str,
    basis_yuan: float,
    provider_key: str | None = None,
) -> PointsBusinessSettlementSnapshot:
    supplier_list_price_yuan = max(float(basis_yuan), 0.0)
    user_billed_yuan = supplier_list_price_yuan * max(float(pricing_config.user_price_rate), 0.0)

    supplier_discount_rate, supplier_discount_rate_source = resolve_provider_discount_rate(
        module_key=module_key,
        provider_key=provider_key,
    )
    supplier_discount_yuan = supplier_list_price_yuan * supplier_discount_rate
    supplier_discounted_cost_yuan = supplier_list_price_yuan - supplier_discount_yuan

    capture_rate = min(max(float(pricing_config.provider_discount_capture_rate), 0.0), 1.0)
    captured_discount_yuan = supplier_discount_yuan * capture_rate
    shared_discount_yuan = supplier_discount_yuan - captured_discount_yuan
    policy_target_user_billed_yuan = supplier_list_price_yuan - shared_discount_yuan
    policy_alignment_gap_yuan = user_billed_yuan - policy_target_user_billed_yuan

    platform_gross_profit_yuan = user_billed_yuan - supplier_discounted_cost_yuan
    platform_margin_rate = None
    if user_billed_yuan > 0:
        platform_margin_rate = platform_gross_profit_yuan / user_billed_yuan

    if platform_gross_profit_yuan < 0:
        margin_status = "negative"
    elif platform_margin_rate is not None and platform_margin_rate < max(float(pricing_config.margin_warning_rate), 0.0):
        margin_status = "warning"
    else:
        margin_status = "healthy"

    return PointsBusinessSettlementSnapshot(
        module_key=str(module_key or "").strip() or "unknown",
        provider_key=str(provider_key or "").strip() or None,
        user_basis_yuan=round(supplier_list_price_yuan, 2),
        user_billed_yuan=round(user_billed_yuan, 2),
        supplier_list_price_yuan=round(supplier_list_price_yuan, 2),
        supplier_discount_rate=round(supplier_discount_rate, 4),
        supplier_discount_rate_source=supplier_discount_rate_source,
        supplier_discounted_cost_yuan=round(supplier_discounted_cost_yuan, 2),
        supplier_discount_yuan=round(supplier_discount_yuan, 2),
        captured_discount_yuan=round(captured_discount_yuan, 2),
        shared_discount_yuan=round(shared_discount_yuan, 2),
        policy_target_user_billed_yuan=round(policy_target_user_billed_yuan, 2),
        policy_alignment_gap_yuan=round(policy_alignment_gap_yuan, 2),
        platform_gross_profit_yuan=round(platform_gross_profit_yuan, 2),
        platform_margin_rate=None if platform_margin_rate is None else round(platform_margin_rate, 4),
        margin_status=margin_status,
        negative_margin_blocked=bool(pricing_config.negative_margin_block_enabled and platform_gross_profit_yuan < 0),
    )


def build_points_pricing_policy_operating_snapshots(
    *,
    pricing_config: PointsPricingPolicyConfig,
    preview_basis_yuan: float = POINTS_PRICING_POLICY_PREVIEW_BASIS_YUAN,
) -> list[dict[str, object]]:
    normalized_basis_yuan = max(float(preview_basis_yuan), 0.0)
    if normalized_basis_yuan <= 0:
        normalized_basis_yuan = POINTS_PRICING_POLICY_PREVIEW_BASIS_YUAN

    snapshots: list[dict[str, object]] = []
    for module_key, module_label in POINTS_PRICING_POLICY_OPERATING_MODULES:
        snapshot = build_points_business_settlement_snapshot(
            pricing_config=pricing_config,
            module_key=module_key,
            basis_yuan=normalized_basis_yuan,
        )
        payload = snapshot.to_payload()
        payload["module_label"] = module_label
        snapshots.append(payload)

    return snapshots


def _points_pricing_log_rank(log: object) -> tuple[float, int]:
    created_at = ensure_utc_datetime(getattr(log, "created_at", None))
    return (
        created_at.timestamp() if created_at else 0.0,
        int(getattr(log, "id", 0) or 0),
    )


def _resolve_latest_points_pricing_policy_log(
    *,
    db: Session | None = None,
    logs: list[object] | None = None,
) -> object | None:
    if logs:
        return max(logs, key=_points_pricing_log_rank)

    if db is None:
        return None

    return (
        db.query(AdminOperationLog)
        .filter(
            AdminOperationLog.operation_type == POINTS_PRICING_POLICY_OPERATION_TYPE,
            AdminOperationLog.resource_type == POINTS_PRICING_POLICY_RESOURCE_TYPE,
            AdminOperationLog.resource_id == POINTS_PRICING_POLICY_RESOURCE_ID,
            AdminOperationLog.response_status < 400,
        )
        .order_by(AdminOperationLog.created_at.desc(), AdminOperationLog.id.desc())
        .first()
    )


def get_points_pricing_policy_snapshot(
    *,
    db: Session | None = None,
    logs: list[object] | None = None,
) -> PointsPricingPolicySnapshot:
    default_config = PointsPricingPolicyConfig()
    latest_log = _resolve_latest_points_pricing_policy_log(db=db, logs=logs)

    if latest_log is None:
        return PointsPricingPolicySnapshot(
            config=resolve_points_pricing_policy_config(default_config.to_payload()),
            source="default",
        )

    config = resolve_points_pricing_policy_config(
        getattr(latest_log, "request_params", None) or {},
        base_config=default_config,
    )
    return PointsPricingPolicySnapshot(
        config=config,
        source="admin_log",
        updated_at=ensure_utc_datetime(getattr(latest_log, "created_at", None)),
        updated_by_user_id=getattr(latest_log, "user_id", None),
        updated_by_username=str(getattr(latest_log, "username", "") or "").strip() or None,
        operation_log_id=getattr(latest_log, "id", None),
    )
