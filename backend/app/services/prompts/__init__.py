"""
提示词模块化系统

目录结构:
- base/: 基础通用模块（角色、质量标准、输出格式）
- stages/: 阶段专属模块（章节规划、内容创作、大纲扩展等）
- genres/: 题材专属模块（从 agent_coordinator.py 迁移）
- builder.py: 统一组装器

设计原则:
1. 每个模块独立可测试
2. 支持版本追踪（为提示词进化做准备）
3. 支持动态组装（基础 + 题材扩展）
4. 支持前端开关控制
"""

from .builder import (
    PromptBuilder,
    PromptModule,
    PromptConfig,
    create_prompt_builder,
    # 阶段专属快捷构建器
    build_chapter_planning_prompt,
    build_content_creation_prompt,
    build_world_building_prompt,
    build_character_design_prompt,
    # 进化追踪
    PromptUsageRecord,
    PromptEvolutionTracker,
)

__all__ = [
    # 核心类
    'PromptBuilder',
    'PromptModule',
    'PromptConfig',
    # 工厂函数
    'create_prompt_builder',
    # 阶段快捷构建器
    'build_chapter_planning_prompt',
    'build_content_creation_prompt',
    'build_world_building_prompt',
    'build_character_design_prompt',
    # 进化追踪
    'PromptUsageRecord',
    'PromptEvolutionTracker',
]
