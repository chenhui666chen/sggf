"""角色与角色功法相关模型
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import String, Text, ForeignKey, DateTime, Integer, UniqueConstraint
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
    role: Mapped[Optional[str]] = mapped_column(  # 故事立场：主角方 / 反派方 / 中立方 / 亦正亦邪
        String(50), nullable=True
    )
    role_position: Mapped[Optional[str]] = mapped_column(  # 角色定位：主角 / 盟友 / 导师 / 对手 / 情报角色 等
        String(100), nullable=True
    )
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 所属势力
    faction: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # 人物重要程度（戏份权重）：主角 / 重要角色 / 次要角色 / 群众角色
    importance_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 出场状态：未出场 / 已出场 / 已退场
    appearance_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 生死状态：存活 / 死亡 / 失踪 / 未知
    life_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # 当前境界：指向境界体系中的某个 SettingItem
    current_realm_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("setting_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    
    # 🆕 新增：其他体系关联字段
    faction_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("setting_items.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属势力(外键→force_system)"
    )
    profession_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("setting_items.id", ondelete="SET NULL"), nullable=True, index=True, comment="职业(外键→profession_class_system)"
    )
    race_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("setting_items.id", ondelete="SET NULL"), nullable=True, index=True, comment="种族(外键→race_bloodline_system)"
    )
    
    # 🆕 JSON字段：掉握的功法/法宝/关联地点
    techniques_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="掉握的功法ID列表(JSON)")
    artifacts_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="拥有的法宝ID列表(JSON)")
    related_locations_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="关联地点ID列表(JSON)")
    
    # 🆕 自动维护字段：出场记录
    first_mention_chapter_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True, comment="首次提及章节"
    )
    last_appearance_chapter_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True, comment="最后出场章节"
    )
    appearance_chapters: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="所有出场章节ID列表(JSON)")
    relationship_network: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="人物关系网络(JSON)")

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

    # 稳定人物基线（P2：与章节级动态状态快照分离，禁止被动态值覆盖）
    personality: Mapped[Optional[str]] = mapped_column(  # 性格锚点
        Text, nullable=True, comment="稳定基线：性格锚点"
    )
    worldview: Mapped[Optional[str]] = mapped_column(  # 价值倾向
        Text, nullable=True, comment="稳定基线：世界观/价值倾向"
    )
    motivation: Mapped[Optional[str]] = mapped_column(  # 原始核心动机
        Text, nullable=True, comment="稳定基线：原始核心动机"
    )
    limitation: Mapped[Optional[str]] = mapped_column(  # 能力限制
        Text, nullable=True, comment="稳定基线：能力/弱点限制"
    )
    growth_direction: Mapped[Optional[str]] = mapped_column(  # 成长方向
        Text, nullable=True, comment="稳定基线：成长方向"
    )
    speech_style: Mapped[Optional[str]] = mapped_column(  # 说话风格短摘要
        Text, nullable=True, comment="稳定基线：说话风格（语气/称谓/回避表达等短摘要）"
    )

    # 结构化扩展字段（JSON 字符串形式存储）
    tags: Mapped[Optional[str]] = mapped_column(  # 人物标签：宗门弟子/家族少主/魔修 等
        Text, nullable=True
    )
    relations: Mapped[Optional[str]] = mapped_column(  # 与其他角色/势力的关系，可后续统一 UI
        Text, nullable=True
    )

    # 题材专属字段（通用 JSON 存储，适配所有题材的动态字段）
    # 修仙: {"修炼资质": "...", "当前修为": "...", "主修功法": "...", "法宝/灵器": "...", "势力地位": "..."}
    # 玄幻: {"血脉类型": "...", "当前等级": "...", "核心武技": "...", "核心武器": "...", "所属世界/区域": "..."}
    # 都市: {"社会地位": "...", "财富等级": "...", "核心资源": "...", "职业背景": "...", "都市技能": "..."}
    # 悬疑: {"信息掌控层级": "...", "调查权限": "...", "隐藏身份": "...", "关键秘密": "..."}
    # 言情: {"情感状态": "...", "魅力标签": "...", "社交圈层": "...", "情感创伤": "..."}
    # 耽美: {"情感状态": "...", "攻受属性": "...", "内心防线": "...", "关系认知": "..."}
    # 科幻: {"科技等级": "...", "基因改造": "...", "机械强化": "...", "AI融合度": "..."}
    # 纯文学: {"精神状态": "...", "价值观锚点": "...", "人生阶段": "...", "内心矛盾": "..."}
    genre_fields_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="题材专属字段(JSON)，键名由 genre_registry 定义"
    )

    # 卡片来源：expansion=协同扩展管线创建/更新；NULL=历史数据或手动创建（永不自动归档）
    source: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, comment="卡片来源：expansion=协同扩展管线"
    )

    # 归档时间：epic 框架重建后，新框架不再引用的扩展管线卡片被软归档
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="归档时间；非空=已随框架重建归档"
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
    project: Mapped["Project"] = relationship("Project", back_populates="characters", lazy="select")
    
    # 明确指定 foreign_keys 以解决歧义
    current_realm: Mapped[Optional["SettingItem"]] = relationship(
        "SettingItem", 
        foreign_keys=[current_realm_item_id],
        lazy="select"
    )
    faction_item: Mapped[Optional["SettingItem"]] = relationship(
        "SettingItem",
        foreign_keys=[faction_item_id],
        lazy="select"
    )
    profession_item: Mapped[Optional["SettingItem"]] = relationship(
        "SettingItem",
        foreign_keys=[profession_item_id],
        lazy="select"
    )
    race_item: Mapped[Optional["SettingItem"]] = relationship(
        "SettingItem",
        foreign_keys=[race_item_id],
        lazy="select"
    )
    
    # 角色-功法关联（CharacterTechnique 中间表）
    character_techniques: Mapped[List["CharacterTechnique"]] = relationship(
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
        "Character", back_populates="character_techniques", lazy="select"
    )
    technique_item: Mapped["SettingItem"] = relationship("SettingItem", lazy="select")

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return (
            f"<CharacterTechnique id={self.id} "
            f"character_id={self.character_id} technique_item_id={self.technique_item_id}>"
        )


class CharacterStateSnapshot(Base):
    """章节级人物动态状态快照表（P2）

    保存剧情驱动的人物动态状态（当前目标/信念/情绪/关系/已知信息），
    与 Character 基线列分离：动态状态绝不写回基线。
    同一角色同一章节唯一，重复保存幂等（覆盖更新）。
    """

    __tablename__ = "character_state_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "character_id",
            "chapter_id",
            name="uq_character_state_snapshot_project_character_chapter",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    character_id: Mapped[int] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 章节号冗余存储：支持按章节号排序与"恢复第 N 章前状态"查询
    chapter_number: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True, comment="章节号（用于按章节排序/恢复）"
    )

    # 动态状态
    current_motivation: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="当前目标/动机"
    )
    current_belief: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="当前信念"
    )
    emotional_state: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="情绪状态"
    )
    relationship_state_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="关系状态(JSON)"
    )
    known_information: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="已知信息"
    )
    state_changes_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="状态变更记录(JSON)"
    )
    evidence_text: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="状态证据文本片段"
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
    character: Mapped["Character"] = relationship(
        "Character", lazy="select", foreign_keys=[character_id]
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return (
            f"<CharacterStateSnapshot id={self.id} "
            f"character_id={self.character_id} chapter_id={self.chapter_id}>"
        )

