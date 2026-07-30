"""固定音色生命周期账本模型。

MiniMax/StepAudio/豆包复刻的 ¥9.9、¥138 固定费用不能在每章重复收取，也不能
仅凭一个 ``voice_id`` 猜测是否已扣费。本表以**事件账本**方式登记音色生命周期
（创建/试听/正式复刻成功/首次正式使用），配合幂等键防止重复计费，并在真实扣费
后补录供应商凭证。在计费口径确定前只登记事件，不自动冻结或结算。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class VoiceAssetBillingLedger(Base):
    """音色生命周期计费事件账本。

    - ``event_type``：voice_created / preview / clone_succeeded / first_official_use。
    - ``idempotency_key``：同一账号范围下同一生命周期事件只登记一次。
    - ``charge_status``：pending / charged / waived / failed，扣费凭证补录后转 charged。
    """

    __tablename__ = "voice_asset_billing_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    owner_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    account_scope: Mapped[str] = mapped_column(String(40), nullable=False, default="user")

    provider: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    voice_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    voice_asset_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, index=True)

    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fixed_fee_yuan: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CNY")

    charge_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    provider_charge_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_charge_receipt: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    charged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    event_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_voice_asset_billing_ledger_idem"),
        Index(
            "ix_voice_asset_billing_ledger_voice",
            "provider",
            "model",
            "voice_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<VoiceAssetBillingLedger id={self.id} provider={self.provider!r} "
            f"voice_id={self.voice_id!r} event={self.event_type} "
            f"status={self.charge_status}>"
        )


__all__ = ["VoiceAssetBillingLedger"]
