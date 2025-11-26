"""角色与角色功法相关模型
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型检查
    from app.models.project import Project
    from app.models.setting import SettingItem


class Character(Base):
    """结构化人物档案表

    用于将原本存储在 project_settings.characters 文本中的人物信息
    拆解为可结构化管理的单人角色卡。
    """

    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 基本信息
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    role: Mapped[Optional[str]] = mapped_column(  # 主角 / 反派 / 配角
        String(50), nullable=True
    )
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 阵营 / 势力
    faction: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # 人物重要程度（主角 / 重要配角 / 次要配角 / 路人等，可由前端自行约定枚举值）
    importance_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 出场状态：未出场 / 已出场 / 已退场
    appearance_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 生死状态：存活 / 死亡 / 失踪 / 未知
    life_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 当前境界：指向境界体系中的某个 SettingItem
    current_realm_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("setting_items.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 首次出场章节（可选，仅存储章节号，后续如需可扩展为外键）
    first_appearance_chapter: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # 文本信息
    summary: Mapped[Optional[str]] = mapped_column(  # 简短人物介绍
        Text, nullable=True
    )
    profile: Mapped[Optional[str]] = mapped_column(  # 完整人物档案
        Text, nullable=True
    )

    # 结构化扩展字段（JSON 字符串形式存储）
    tags: Mapped[Optional[str]] = mapped_column(  # 人物标签：宗门弟子/家族少主/魔修 等
        Text, nullable=True
    )
    relations: Mapped[Optional[str]] = mapped_column(  # 与其他角色/势力的关系，可后续统一 UI
        Text, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 关系定义
    project: Mapped["Project"] = relationship("Project", lazy="select")
    current_realm: Mapped[Optional["SettingItem"]] = relationship(
        "SettingItem", lazy="select"
    )
    techniques: Mapped[List["CharacterTechnique"]] = relationship(
        "CharacterTechnique",
        back_populates="character",
        lazy="select",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<Character id={self.id} name={self.name!r}>"


class CharacterTechnique(Base):
    """角色-功法关联表

    用于描述某个角色已掌握哪些功法（SettingItem），以及熟练度等信息。
    """

    __tablename__ = "character_techniques"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )

    technique_item_id: Mapped[int] = mapped_column(
        ForeignKey("setting_items.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 熟练度：入门 / 熟练 / 精通 / 大成 等，具体枚举由前端控制
    proficiency: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 学会该功法的大致章节号（可选）
    learned_at_chapter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 备注：特殊限制、施展代价等
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 关系定义
    character: Mapped["Character"] = relationship(
        "Character", back_populates="techniques", lazy="select"
    )
    technique_item: Mapped["SettingItem"] = relationship("SettingItem", lazy="select")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return (
            f"<CharacterTechnique id={self.id} "
            f"character_id={self.character_id} technique_item_id={self.technique_item_id}>"
        )

