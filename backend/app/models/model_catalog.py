"""模型档案中心数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class ModelCatalogEntry(Base):
    """统一存储项目已接入模型的归档信息与联网校验结果。"""

    __tablename__ = "model_catalog_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    model_key: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), index=True, nullable=False, comment="一级分类")
    subcategory: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, comment="二级分类")
    model_family: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, comment="模型家族")
    config_source: Mapped[str] = mapped_column(String(50), nullable=False, comment="配置来源")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")

    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommended_scenarios: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    limitations: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    integration_notes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    documentation_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    source_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    modalities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    capabilities_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    constraints_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    performance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    routing_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    default_params_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    verification_status: Mapped[str] = mapped_column(
        String(20),
        index=True,
        nullable=False,
        default="pending",
        comment="pending/verified/partial/failed",
    )
    verification_scope: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    verification_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reachable_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sources: Mapped[list["ModelCatalogSource"]] = relationship(
        "ModelCatalogSource",
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="ModelCatalogSource.id",
        lazy="selectin",
    )


class ModelCatalogSource(Base):
    """模型档案的单条联网校验来源记录。"""

    __tablename__ = "model_catalog_sources"
    __table_args__ = (
        UniqueConstraint("entry_id", "url", name="uq_model_catalog_sources_entry_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("model_catalog_entries.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="documentation/reference/fallback")
    source_domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reachable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    page_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    page_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    verification_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    entry: Mapped["ModelCatalogEntry"] = relationship("ModelCatalogEntry", back_populates="sources")
