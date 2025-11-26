
"""
类型化设定相关模型
"""
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型检查
    from app.models.project import Project


class SettingCollection(Base):
    """设定集合表"""

    __tablename__ = "setting_collections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship("Project", lazy="select")
    items: Mapped[List["SettingItem"]] = relationship(
        "SettingItem",
        lazy="select",
        cascade="all, delete-orphan",
        back_populates="collection",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<SettingCollection id={self.id} name={self.name!r}>"


class SettingItem(Base):
    """设定项表"""

    __tablename__ = "setting_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("setting_collections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    relations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now()
    )

    collection: Mapped["SettingCollection"] = relationship(
        "SettingCollection", back_populates="items", lazy="select"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<SettingItem id={self.id} name={self.name!r}>"

