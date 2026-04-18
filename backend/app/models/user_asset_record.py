"""
用户资产记录模型
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class UserAssetRecord(Base):
    """用户资产记录表"""

    __tablename__ = "user_asset_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    asset_kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    asset_class: Mapped[str] = mapped_column(String(30), nullable=False, default="reusable", index=True)
    asset_uuid: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    storage_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="temp_cloud", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_uri: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    preview_uri: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    download_uri: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    checksum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    generation_mode: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return (
            f"<UserAssetRecord id={self.id} user_id={self.user_id} "
            f"kind={self.asset_kind} asset_uuid={self.asset_uuid}>"
        )
