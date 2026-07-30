"""公共音色池发布条目模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class VoicePoolPublication(Base):
    """私有参考音色面向全站用户的可撤回发布视图。"""

    __tablename__ = "voice_pool_publications"

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_asset_id: Mapped[int] = mapped_column(
        ForeignKey("voice_reference_assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voice_origin: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)

    gender_presentation: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    age_impression: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    primary_style: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    accent: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, index=True)
    timbre_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scenario_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    emotion_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    rights_basis: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    license_version: Mapped[str] = mapped_column(String(40), nullable=False)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    public_preview_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    public_reference_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending_review", index=True
    )
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("publication_id", name="uq_voice_pool_publications_publication_id"),
        UniqueConstraint("source_asset_id", name="uq_voice_pool_publications_source_asset"),
        Index(
            "ix_voice_pool_publications_discovery",
            "status",
            "gender_presentation",
            "age_impression",
            "primary_style",
        ),
    )


__all__ = ["VoicePoolPublication"]
