"""公共音色池用户评分模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class VoicePoolRating(Base):
    __tablename__ = "voice_pool_ratings"

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("voice_pool_publications.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "publication_id",
            "user_id",
            name="uq_voice_pool_ratings_publication_user",
        ),
        CheckConstraint("score >= 1 AND score <= 5", name="ck_voice_pool_ratings_score"),
        Index("ix_voice_pool_ratings_publication_id", "publication_id"),
        Index("ix_voice_pool_ratings_user_id", "user_id"),
    )


__all__ = ["VoicePoolRating"]
