"""
阶段专属提示词模块

包含各创作阶段的专属提示词：
- chapter_planning.py: 章节规划
- content_creation.py: 内容创作
- outline_expansion.py: 大纲扩展
- world_building.py: 世界观设计
- character_design.py: 人物设计
"""

from .chapter_planning import ChapterPlanningPrompts, get_genre_chapter_plan_guide, get_climax_instruction
from .content_creation import ContentCreationPrompts
from .outline_expansion import OutlineExpansionPrompts, CharacterExpansionPrompts, get_genre_outline_guide
from .world_building import (
    WorldBuildingPrompts,
    CharacterDesignPrompts,
    get_genre_world_extension,
    get_genre_character_fields
)

__all__ = [
    # 章节规划
    'ChapterPlanningPrompts',
    'get_genre_chapter_plan_guide',
    'get_climax_instruction',
    # 内容创作
    'ContentCreationPrompts',
    # 大纲扩展
    'OutlineExpansionPrompts',
    'CharacterExpansionPrompts',
    'get_genre_outline_guide',
    # 世界观与人物设计
    'WorldBuildingPrompts',
    'CharacterDesignPrompts',
    'get_genre_world_extension',
    'get_genre_character_fields',
]
