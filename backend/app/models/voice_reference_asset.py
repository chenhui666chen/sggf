"""角色参考音色资产模型。

为有声书 Seed Audio 场景引擎提供稳定的声音身份资产层。共享
``AudioLibraryAsset`` 只支持 sfx/music，无法承载角色声音身份与授权信息；
本表以稳定 ``asset_id`` 引用参考音色，并记录来源、存储 URI、SHA-256 和授权
范围，避免把 Base64 长期写入 ``Project.audio_config``。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class VoiceReferenceAsset(Base):
    """角色参考音色资产索引。

    - ``system_voice``/``voice_clone``：直接使用 ``references[].speaker``，不落音频。
    - ``user_recording``/``provider_preview``：物化试听/授权录音为稳定音频，
      记录 ``storage_uri`` 与 ``sha256``，运行时按 ``asset_id`` 复用。
    """

    __tablename__ = "voice_reference_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)

    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    reference_kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reference_field: Mapped[str] = mapped_column(String(20), nullable=False, default="speaker")

    provider: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    source_voice_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    speaker: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_preview_cache_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    storage_uri: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    authorization_scope: Mapped[str] = mapped_column(
        String(40), nullable=False, default="account", index=True
    )
    authorization_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    authorization_basis: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    authorized_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    authorized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revoked_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoke_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    cleanup_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_requested", index=True
    )
    cleanup_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    cleanup_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("asset_id", name="uq_voice_reference_assets_asset_id"),
        Index("ix_voice_reference_assets_source_voice", "source_model", "source_voice_id"),
        Index(
            "ix_voice_reference_assets_owner_active",
            "owner_user_id",
            "revoked_at",
            "deleted_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<VoiceReferenceAsset id={self.id} asset_id={self.asset_id!r} "
            f"kind={self.reference_kind}>"
        )


__all__ = ["VoiceReferenceAsset"]
