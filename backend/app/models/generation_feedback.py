# -*- coding: utf-8 -*-
"""
Generation Feedback Model - User ratings and QC results for model performance tracking.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class GenerationFeedback(Base):
    """生成结果反馈记录 — 用户评分 + QC质检结果回流。"""

    __tablename__ = "generation_feedbacks"
    # 注意：user_id/model_id/applied_to_profile 已由列级 index=True 生成同名索引
    # （ix_generation_feedbacks_{user_id|model_id|applied_to_profile}），
    # 此处不再显式注册，避免 create_all 重复建同名索引报错。
    __table_args__ = (
        Index("ix_generation_feedbacks_task_type", "task_type"),
        Index("ix_generation_feedbacks_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )

    model_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)

    user_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="用户评分 1-5")
    user_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="用户文字反馈")

    qc_passed: Mapped[Optional[bool]] = mapped_column(nullable=True, comment="AutoQC是否通过")
    qc_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="AutoQC综合得分 0-1")
    qc_details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, comment="AutoQC各维度详情")

    style_match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="风格匹配度 0-1")
    prompt_adherence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="提示词遵循度 0-1")
    visual_quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="视觉质量分 0-1")
    character_consistency_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="角色一致性 0-1")
    motion_stability_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="运动稳定性 0-1")

    generation_latency: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="生成耗时(秒)")
    generation_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="生成成本")

    prompt_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="原始提示词")
    output_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, comment="生成结果URL")

    source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="user",
        comment="反馈来源: user/auto_qc/system",
    )

    applied_to_profile: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        index=True,
        comment="是否已回流更新模型画像",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "model_id": self.model_id,
            "task_type": self.task_type,
            "user_rating": self.user_rating,
            "user_comment": self.user_comment,
            "qc_passed": self.qc_passed,
            "qc_score": self.qc_score,
            "qc_details": self.qc_details,
            "style_match_score": self.style_match_score,
            "prompt_adherence_score": self.prompt_adherence_score,
            "visual_quality_score": self.visual_quality_score,
            "character_consistency_score": self.character_consistency_score,
            "motion_stability_score": self.motion_stability_score,
            "generation_latency": self.generation_latency,
            "generation_cost": self.generation_cost,
            "source": self.source,
            "applied_to_profile": self.applied_to_profile,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
