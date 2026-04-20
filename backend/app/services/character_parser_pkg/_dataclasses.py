"""
人物卡数据类定义
"""
from dataclasses import dataclass, field
from typing import Optional

from ._utils import (
    _build_personality_anchor_text,
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
)


@dataclass
class ParsedCharacter:
    """解析后的人物卡结构"""
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    role: Optional[str] = None
    role_position: Optional[str] = None
    faction: Optional[str] = None
    importance_level: Optional[str] = None
    
    appearance: Optional[str] = None
    personality: Optional[str] = None
    background: Optional[str] = None
    worldview: Optional[str] = None
    motivation: Optional[str] = None
    abilities: Optional[str] = None
    limitation: Optional[str] = None
    mainline_role: Optional[str] = None
    growth_direction: Optional[str] = None
    relationships: Optional[str] = None
    mainline_clues: Optional[str] = None
    
    raw_text: str = ""
    
    def build_summary(self) -> str:
        """构建人物简介（1-3句话）"""
        parts = []
        identity_parts = []
        if self.role:
            identity_parts.append(self.role)
        if self.role_position and self.role_position not in identity_parts:
            identity_parts.append(self.role_position)
        if identity_parts:
            parts.append(" / ".join(identity_parts))
        if self.personality:
            first_sentence = self.personality.split('。')[0] if self.personality else ""
            if first_sentence:
                parts.append(first_sentence)
        if self.motivation:
            parts.append(f"核心动机：{self.motivation.split('。')[0]}")
        return '。'.join(parts[:3]) + '。' if parts else ""
    
    def build_profile(self) -> str:
        """构建完整人物档案"""
        sections = []

        demographics = []
        if self.age is not None:
            demographics.append(f"{self.age}岁")
        if self.gender:
            demographics.append(self.gender)
        if demographics:
            sections.append(f"【年龄/性别】\n{'/'.join(demographics)}")
        if self.role:
            sections.append(f"【故事立场】\n{self.role}")
        if self.role_position:
            sections.append(f"【角色定位】\n{self.role_position}")
        if self.faction:
            sections.append(f"【所属势力】\n{self.faction}")
        if self.appearance:
            sections.append(f"【外貌锚点】\n{self.appearance}")
        personality_anchor = _build_personality_anchor_text(self.personality, self.worldview)
        if personality_anchor:
            sections.append(f"【性格锚点】\n{personality_anchor}")
        if self.background:
            sections.append(f"【背景/当前处境】\n{self.background}")
        if self.motivation:
            sections.append(f"【核心动机】\n{self.motivation}")
        ability_and_limit = _build_ability_and_limit_text(self.abilities, self.limitation)
        if ability_and_limit:
            sections.append(f"【能力与限制】\n{ability_and_limit}")
        if self.relationships:
            sections.append(f"【关键关系】\n{self.relationships}")
        mainline_binding = _build_mainline_binding_text(self.mainline_role, self.mainline_clues)
        if mainline_binding:
            sections.append(f"【主线绑定】\n{mainline_binding}")
        if self.growth_direction:
            sections.append(f"【成长方向】\n{self.growth_direction}")
        
        return "\n\n".join(sections) if sections else self.raw_text
