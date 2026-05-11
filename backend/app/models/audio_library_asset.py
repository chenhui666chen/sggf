"""共享音频素材库资产模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AudioLibraryAsset(Base):
    """全局共享音乐/音效素材索引。

    音频文件本体仍存对象存储或本地缓存；本表只保存检索、授权、质量和
    存储 URI 元数据。
    """

    __tablename__ = "audio_library_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    library_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    asset_scope: Mapped[str] = mapped_column(String(30), nullable=False, default="shared_library", index=True)
    asset_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    style: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    mood: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    tempo: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    bucket: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    variant: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    storage_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="local_cache", index=True)
    storage_driver: Mapped[str] = mapped_column(String(60), nullable=False, default="local_fs", index=True)
    cloud_uri: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    public_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    object_key: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    local_cache_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    source: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    source_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    author_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    license: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    license_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    license_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    license_commercial: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    attribution_required: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    attribution_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_grade: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    quality_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, index=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scenes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    retrieved_at: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    license_checked_at: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("library_type", "asset_key", name="uq_audio_library_assets_type_key"),
        Index("ix_audio_library_assets_source", "source"),
    )


__all__ = ["AudioLibraryAsset"]
