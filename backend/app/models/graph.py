from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, Integer, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class KnowledgeGraphEdge(Base):
    """知识图谱关系边表"""

    __tablename__ = "knowledge_graph_edges"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_item_id: Mapped[int] = mapped_column(ForeignKey("setting_items.id", ondelete="CASCADE"), index=True)
    target_item_id: Mapped[int] = mapped_column(ForeignKey("setting_items.id", ondelete="CASCADE"), index=True)

    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    auto_extracted: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # 关系（可选，延迟加载，避免循环导入）
    # 提示：仅在查询中需要时使用 join

