"""
章节规划阶段提示词模块

从 workflow.py 提取的章节规划相关提示词
"""

from typing import Dict, Optional
from dataclasses import dataclass

from app.services.prompts.genre_registry import (
    get_genre_chapter_plan_guide as _get_genre_chapter_plan_guide,
    resolve_genre,
)


@dataclass
class ChapterPlanningPrompts:
    """章节规划提示词集合"""
    
    # 版本信息
    version: str = "1.0.0"
    
    @staticmethod
    def get_system_prompt(genre: str = "") -> str:
        """
        获取章节规划的 system prompt
        
        Args:
            genre: 题材名称
        """
        genre_hint = f"，专注于{genre}题材" if genre else ""
        
        return f"""你是一位资深的小说策划编辑{genre_hint}，擅长章节规划和节奏把控。
你的职责是根据整体大纲，为每一章制定详细的创作计划，确保：
- 情节推进合理有序
- 节奏张弛有度
- 伏笔和钩子安排得当
- 与前文保持连贯

请严格按照提供的结构输出章节规划。"""

    @staticmethod
    def get_user_prompt_template() -> str:
        """获取章节规划的 user prompt 模板"""
        return """请为第{chapter_number}章制定详细的创作计划。

【整体情节大纲】
{plot_outline}

【世界观设定摘要】
{world_setting_summary}

【人物设定摘要】
{characters_summary}

【前序章节分析】（最近3章）
{previous_analysis}

【前一章结尾】
{previous_ending}

请按以下结构输出本章规划：

- 场景目标：...
- 冲突设计：...
- 关键事件：
  1. ...
  2. ...
- 涉及人物：...
- 人物推进：...
- 情节作用：...
- 结尾钩子：...
- 爽点类型：...（如无明显爽点可写“无”）
- 伏笔事项：...（如无则写“无”）

---

要求：
- 确保与整本书的情节大纲保持一致
- 确保与前面章节的剧情连贯
- 推进故事发展，不能原地踏步
- 爽点和钩子必须具体、可执行
- 不要额外发明旧版冗余字段，统一使用当前章节规划字段"""

    @staticmethod
    def build_user_prompt(
        chapter_number: int,
        plot_outline: str,
        world_setting_summary: str,
        characters_summary: str,
        previous_analysis: str,
        previous_ending: str,
        genre_guide: str = ""
    ) -> str:
        """
        构建完整的 user prompt
        
        Args:
            chapter_number: 章节编号
            plot_outline: 情节大纲
            world_setting_summary: 世界观摘要
            characters_summary: 人物摘要
            previous_analysis: 前序章节分析
            previous_ending: 前一章结尾
            genre_guide: 题材专属指导
        
        Returns:
            完整的 user prompt
        """
        base_prompt = ChapterPlanningPrompts.get_user_prompt_template().format(
            chapter_number=chapter_number,
            plot_outline=plot_outline or "（暂无情节大纲）",
            world_setting_summary=world_setting_summary or "（暂无世界观摘要）",
            characters_summary=characters_summary or "（暂无人物摘要）",
            previous_analysis=previous_analysis or "（这是第一章）",
            previous_ending=previous_ending or "（这是第一章）"
        )
        
        # 添加题材专属指导
        if genre_guide and genre_guide.strip():
            base_prompt += f"""
【题材专属细化】（以下为通用规划要求的具体落地方式，请结合使用）
{genre_guide}"""
        
        return base_prompt


def get_genre_chapter_plan_guide(genre: str) -> str:
    """获取题材专属章节规划指导（委托给 genre_registry）"""
    return _get_genre_chapter_plan_guide(genre)


def get_climax_instruction(chapter_number: int) -> str:
    """
    获取高潮章节指示
    
    Args:
        chapter_number: 章节编号
    
    Returns:
        高潮章节指示字符串，如非高潮章返回空字符串
    """
    is_major_climax = chapter_number % 25 == 0   # 每25章一个大高潮
    is_climax_chapter = chapter_number % 5 == 0  # 每5章一个小高潮
    
    if is_major_climax:
        return f"""
⚠️ 【卷末大高潮章节】第{chapter_number}章是本卷结尾，需要：
- 设计一个让读者拍案叫绝的大爽点
- 本卷主要矛盾要有阶段性解决
- 为下一卷埋下新的悬念"""
    elif is_climax_chapter:
        return f"""
⚠️ 【小高潮章节】第{chapter_number}章需要设计一个明确的爽点：
- 可以是：打脸嘲讽者/突破升级/获得宝物/反转翻盘/装逼成功"""
    
    return ""
