"""共享音频素材的用户评分模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AudioLibraryAssetRating(Base):
    """记录一名用户对一个共享音频素材的最新评分。"""

    __tablename__ = "audio_library_asset_ratings"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("audio_library_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "user_id",
            name="uq_audio_library_asset_ratings_asset_user",
        ),
        CheckConstraint(
            "score >= 1 AND score <= 5",
            name="ck_audio_library_asset_ratings_score",
        ),
        Index("ix_audio_library_asset_ratings_asset_id", "asset_id"),
        Index("ix_audio_library_asset_ratings_user_id", "user_id"),
    )


__all__ = ["AudioLibraryAssetRating"]
