"""固定音色生命周期账本仓储。

以事件账本方式登记音色生命周期（创建/试听/正式复刻成功/首次正式使用），用幂等键
防止重复计费，并在真实扣费后补录供应商凭证。在计费口径确定前只登记事件，不自动
冻结或结算——``record_voice_billing_event`` 仅写入账本，实际扣费由上层在凭证齐备后
调用 ``mark_charge_settled`` 落地。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.voice_asset_billing_ledger import VoiceAssetBillingLedger


# 音色生命周期事件：创建、试听、正式复刻成功、首次正式使用。
_VALID_EVENT_TYPES = frozenset(
    {
        "voice_created",
        "preview",
        "clone_succeeded",
        "first_official_use",
    }
)

# 扣费状态：待处理、已扣费、豁免、失败。
_VALID_CHARGE_STATUS = frozenset({"pending", "charged", "waived", "failed"})


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _optional_text(value: Any) -> str | None:
    normalized = _text(value)
    return normalized or None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def normalize_billing_event_type(value: str) -> str:
    normalized = _text(value).lower()
    if normalized not in _VALID_EVENT_TYPES:
        raise ValueError(
            "event_type must be one of "
            "voice_created/preview/clone_succeeded/first_official_use"
        )
    return normalized


def normalize_charge_status(value: str) -> str:
    normalized = _text(value).lower()
    if normalized not in _VALID_CHARGE_STATUS:
        raise ValueError("charge_status must be one of pending/charged/waived/failed")
    return normalized


def build_billing_idempotency_key(
    *,
    provider: str,
    event_type: str,
    model: str | None = None,
    voice_id: str | None = None,
    owner_user_id: int | None = None,
    account_scope: str = "user",
) -> str:
    """按账号范围 + 供应商 + 模型 + 音色 + 事件类型构造幂等键。

    同一账号下同一生命周期事件（如“首次正式使用”）只登记一次，避免每章重复计费。
    """
    event = normalize_billing_event_type(event_type)
    parts = [
        _text(account_scope) or "user",
        _text(owner_user_id),
        _text(provider),
        _text(model),
        _text(voice_id),
        event,
    ]
    signature = "|".join(parts)
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:48]
    return f"vbl_{digest}"


def record_voice_billing_event(
    db: Session,
    *,
    provider: str,
    event_type: str,
    model: str | None = None,
    voice_id: str | None = None,
    owner_user_id: int | None = None,
    account_scope: str = "user",
    voice_asset_id: str | None = None,
    billable: bool = False,
    fixed_fee_yuan: float | None = None,
    currency: str = "CNY",
    occurred_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    event_payload: dict[str, Any] | None = None,
) -> VoiceAssetBillingLedger:
    """幂等登记一条音色生命周期事件，不触发任何扣费。"""
    event = normalize_billing_event_type(event_type)
    provider_value = _text(provider)
    if not provider_value:
        raise ValueError("provider is required for a billing event")

    scope = _text(account_scope) or "user"
    idempotency_key = build_billing_idempotency_key(
        provider=provider_value,
        event_type=event,
        model=model,
        voice_id=voice_id,
        owner_user_id=owner_user_id,
        account_scope=scope,
    )

    entry = (
        db.query(VoiceAssetBillingLedger)
        .filter(VoiceAssetBillingLedger.idempotency_key == idempotency_key)
        .first()
    )
    if entry is None:
        entry = VoiceAssetBillingLedger(idempotency_key=idempotency_key)
        db.add(entry)

    entry.owner_user_id = owner_user_id
    entry.account_scope = scope
    entry.provider = provider_value
    entry.model = _optional_text(model)
    entry.voice_id = _optional_text(voice_id)
    entry.voice_asset_id = _optional_text(voice_asset_id)
    entry.event_type = event
    entry.billable = bool(billable)
    entry.fixed_fee_yuan = _optional_float(fixed_fee_yuan)
    entry.currency = _text(currency) or "CNY"
    if entry.charge_status is None:
        entry.charge_status = "pending"
    if occurred_at is not None:
        entry.occurred_at = occurred_at
    entry.metadata_json = _dict_value(metadata)
    entry.event_payload_json = _dict_value(event_payload)
    return entry


def mark_charge_settled(
    db: Session,
    *,
    idempotency_key: str,
    provider_charge_id: str | None = None,
    provider_charge_receipt: str | None = None,
    charged_at: datetime | None = None,
    charge_status: str = "charged",
) -> VoiceAssetBillingLedger | None:
    """在供应商真实扣费凭证齐备后补录，并把事件置为最终扣费状态。"""
    entry = get_ledger_entry(db, idempotency_key)
    if entry is None:
        return None
    entry.charge_status = normalize_charge_status(charge_status)
    entry.provider_charge_id = _optional_text(provider_charge_id)
    entry.provider_charge_receipt = _optional_text(provider_charge_receipt)
    entry.charged_at = charged_at or datetime.utcnow()
    return entry


def get_ledger_entry(db: Session, idempotency_key: str) -> VoiceAssetBillingLedger | None:
    normalized = _text(idempotency_key)
    if not normalized:
        return None
    return (
        db.query(VoiceAssetBillingLedger)
        .filter(VoiceAssetBillingLedger.idempotency_key == normalized)
        .first()
    )


def list_voice_billing_events(
    db: Session,
    *,
    provider: str | None = None,
    voice_id: str | None = None,
    owner_user_id: int | None = None,
) -> list[VoiceAssetBillingLedger]:
    query = db.query(VoiceAssetBillingLedger)
    if provider:
        query = query.filter(VoiceAssetBillingLedger.provider == _text(provider))
    if voice_id:
        query = query.filter(VoiceAssetBillingLedger.voice_id == _text(voice_id))
    if owner_user_id is not None:
        query = query.filter(VoiceAssetBillingLedger.owner_user_id == owner_user_id)
    return query.order_by(VoiceAssetBillingLedger.id.asc()).all()


__all__ = [
    "build_billing_idempotency_key",
    "get_ledger_entry",
    "list_voice_billing_events",
    "mark_charge_settled",
    "normalize_billing_event_type",
    "normalize_charge_status",
    "record_voice_billing_event",
]
