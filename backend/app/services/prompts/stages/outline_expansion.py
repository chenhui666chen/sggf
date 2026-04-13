"""
大纲扩展阶段提示词模块

从 outline_expander.py 提取的大纲扩展相关提示词模板
"""

from typing import Dict, Optional
from dataclasses import dataclass

from app.services.prompts.genre_registry import (
    get_genre_outline_guide as _get_genre_outline_guide,
    resolve_genre,
)


@dataclass
class OutlineExpansionPrompts:
    """大纲扩展提示词集合"""
    
    # 版本信息
    version: str = "1.0.0"
    
    @staticmethod
    def get_analysis_prompt(
        current_outline: str,
        world_setting: str,
        characters: str,
        target_chapters: int
    ) -> str:
        """获取大纲扩展潜力分析提示词"""
        return f"""你是一位资深小说策划师。请分析以下简短大纲的扩展潜力。

【当前大纲】
{current_outline}

【世界观】
{world_setting}

【人物设定】
{characters}

请分析：
1. **主线情节可扩展点**：识别可以深入展开的情节环节
2. **支线剧情机会**：可以添加哪些有价值的支线故事
3. **情节转折点**：需要增加哪些铺垫和转折
4. **节奏分布建议**：如何分配高潮、低潮、过渡章节
5. **伏笔埋设点**：可以在哪些地方设置伏笔

请给出具体分析，为扩展到{target_chapters}章提供依据。"""

    @staticmethod
    def get_plot_arcs_prompt(
        expansion_analysis: str,
        current_outline: str,
        target_chapters: int
    ) -> str:
        """获取情节线索设计提示词"""
        return f"""基于以下分析，设计长篇小说的情节线索体系。

【扩展分析】
{expansion_analysis}

【原始大纲】
{current_outline}

请设计：
1. **主线情节**：整本书的核心故事线（占比40%）
2. **A支线**：与主线紧密相关的次要故事线（占比25%）
3. **B支线**：人物成长或感情线（占比20%）
4. **C支线**：世界观探索或社会背景线（占比15%）

每条线索需要包括：
- 起始章节范围
- 核心冲突
- 关键转折点
- 与其他线索的交织点
- 高潮和解决方案

目标章节数：{target_chapters}章"""

    @staticmethod
    def get_chapter_breakdown_prompt(
        plot_arcs: str,
        world_setting: str,
        characters: str,
        target_chapters: int
    ) -> str:
        """获取章节分解提示词"""
        return f"""基于以下情节线索，生成详细的章节分解（{target_chapters}章）。

【情节线索】
{plot_arcs}

【原始设定】
- 世界观: {world_setting}
- 人物: {characters}

请为每一章生成结构清晰的简要说明，统一使用当前细纲字段，格式如下：

第1章：[标题]
- 场景目标：...
- 冲突设计：...
- 关键事件：...
- 涉及人物：[列出主要出场角色]
- 人物推进：[本章人物的重要变化或关系进展]
- 情节作用：[本章在整段剧情中的职责，例如承接/升级/爆点前置/伏笔回收]
- 结尾钩子：...
- 爽点类型：[如本章存在明确爽点再写]
- 伏笔事项：[如无则写“无”]

...（直到第{target_chapters}章）

要求：
1. 确保情节发展节奏合理（避免前松后紧）
2. 适当分布高潮章节（每10-15章一个小高潮）
3. 支线穿插自然，不影响主线推进
4. 伏笔和回收配对明确
5. 确保所有主要角色在不同阶段都有出场与推进，避免长时间"消失"。"""

    @staticmethod
    def get_expanded_outline_prompt(
        chapter_breakdown: str,
        plot_arcs: str,
        target_chapters: int
    ) -> str:
        """获取完整扩展大纲提示词"""
        return f"""基于以下信息，撰写完整的长篇小说情节大纲。

【章节分解】
{chapter_breakdown}

【情节线索】
{plot_arcs}

请撰写一份完整的情节大纲，包括：
1. **故事概述**（500字）
2. **情节发展**（按起承转合分四部分）
3. **重要转折点**（列出5-8个关键转折）
4. **高潮设计**（中期高潮 + 最终高潮）
5. **结局规划**（开放式/封闭式，是否留续集空间）

这份大纲将指导{target_chapters}章的创作。"""


# 人物扩展提示词
@dataclass
class CharacterExpansionPrompts:
    """人物扩展提示词集合"""
    
    version: str = "1.0.0"
    
    @staticmethod
    def get_analysis_prompt(
        main_characters: str,
        world_setting: str,
        plot_outline: str,
        target_count: int
    ) -> str:
        """获取人物扩展需求分析提示词"""
        return f"""你是一位资深人物设计师。请分析以下人物体系的扩展需求。

【当前主要人物】
{main_characters}

【世界观】
{world_setting}

【情节大纲】
{plot_outline}

请分析：
1. **现有人物数量**：当前有几个主要人物
2. **角色类型缺口**：缺少哪些类型的角色（对手、导师、辅助者、中立者等）
3. **情节需求分析**：根据情节发展，需要增加哪些角色
4. **人物关系机会**：可以设计哪些有趣的人物关系
5. **多样性建议**：如何增加人物的多样性和丰富性

目标人物总数：{target_count}个（包括主角、配角、次要角色）"""

    @staticmethod
    def get_incremental_expansion_prompt(
        current_characters: str,
        world_setting: str,
        plot_outline: str,
        current_count: int,
        target_count: int,
        genre_hint: str = ""
    ) -> str:
        """获取渐进式人物扩展提示词"""
        return f"""基于当前人物，扩展到{target_count}个角色。

【当前人物（{current_count}个）】
{current_characters}

【世界观】
{world_setting}

【情节大纲】
{plot_outline}

请补充{target_count - current_count}个新角色，要求：
1. 新角色类型多样（对手/导师/辅助/中立）
2. 与现有人物形成关系网
3. 符合世界观设定
4. 服务于情节发展
5. 每个角色包含：姓名、年龄、身份、外貌、性格、背景、动机、与主角关系
6. 确保所有{target_count}个角色都包含在内{genre_hint}"""


def get_genre_outline_guide(genre: str) -> str:
    """获取题材专属大纲节奏指导（委托给 genre_registry）"""
    return _get_genre_outline_guide(genre)
