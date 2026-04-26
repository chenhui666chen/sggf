"""Outline expansion mixin."""
import json
import logging
import os
import re
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

from ..agents import CreativeDirectorAgent, PlotArchitectAgent, CharacterDesignerAgent
from core.langchain_bridge import create_task_llm, create_model_llm
from core.model_runtime import estimate_model_timeout_seconds
from ..knowledge_base import NovelKnowledgeBase
from ..memory_manager import NovelMemoryManager
from ..agent_coordinator import GENRE_PROMPT_MODULES, DEFAULT_GENRE_MODULE, REALM_SPAN_WARNING_THRESHOLD, REALM_SPAN_RECOMMEND_SUBDIVISION
from ..layered_summarizer import LayeredSummarizer
from ...volume_connector import VolumeConnector
from ...foreshadowing_tracker import ForeshadowingTracker
from ...consistency_validator import ConsistencyValidator, get_consistency_validator, get_chapter_renumberer
from ..character_recognizer import CharacterRecognizer
from ..character_plot_validator import CharacterPlotValidator
from ...character_parser import (
    CharacterTextParser,
    ParsedCharacter,
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
    _merge_parsed_character,
    normalize_character_name,
)
from ...character_runtime_context import build_character_prompt_context_from_text
from ._constants import *

class OutlineExpanderBase:
    """情节大纲和人物扩展器"""

    def __init__(self, knowledge_base: Optional[NovelKnowledgeBase] = None,
                 memory_manager: Optional[NovelMemoryManager] = None,
                 genre: str = "",  # 🎯 任务6：添加题材参数
                 planned_chapters_max: int = 0):  # 🎯 任务6.1：添加章节数参数用于境界检查
        """初始化扩展器

        Args:
            knowledge_base: 知识库实例
            memory_manager: 记忆管理器实例
            genre: 题材类型（修仙、都市、悬疑等）
            planned_chapters_max: 规划的最大章节数
        """
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()
        self.genre = genre  # 🎯 保存题材
        self.planned_chapters_max = planned_chapters_max
        self.project_id: Optional[int] = None

        # 初始化AI Agent
        self.creative_director = CreativeDirectorAgent(self.knowledge_base, self.memory_manager)
        self.plot_architect = PlotArchitectAgent(self.knowledge_base, self.memory_manager)
        self.character_designer = CharacterDesignerAgent(self.knowledge_base, self.memory_manager)

        # 🚀 协同扩展全链路统一使用 deepseek-v4-pro（384K 超长输出）
        # 旧的 qwen3.5-plus / DeepSeek-R1 / qwen-long 分级路由已废弃：
        # V4 Pro 一次可输出约 58–65 万汉字，单卷乃至整本细纲均可一次生成，
        # 无需再依章节数动态切换，也无需再对输出进行二次裁剪。
        outline_expand_max_tokens = 32768
        outline_expand_timeout = estimate_model_timeout_seconds(
            "qwen3.5-plus",
            outline_expand_max_tokens,
        )
        self.llm = create_task_llm(
            task_type="outline_expand",
            max_tokens=outline_expand_max_tokens,
            timeout=outline_expand_timeout,
        )

        # 以下三个属性保留字段名以兼容既有调用点（_volumedetail / _incrementalexpansion / 测试），
        # 但均指向同一份 deepseek-v4-pro 实例，不再做能力分级。
        volume_detail_max_tokens = 64000
        volume_detail_timeout = estimate_model_timeout_seconds(
            "deepseek-v4-pro",
            volume_detail_max_tokens,
        )
        r1_llm = create_task_llm(
            task_type="volume_detail_expand",
            max_tokens=volume_detail_max_tokens,
            timeout=volume_detail_timeout,
        )
        self.plot_architect_r1 = PlotArchitectAgent(self.knowledge_base, self.memory_manager, llm=r1_llm)

        plus_max_tokens = 32768
        plus_timeout = estimate_model_timeout_seconds(
            "qwen3.5-plus",
            plus_max_tokens,
        )
        plus_llm = create_task_llm(
            model="qwen3.5-plus",
            max_tokens=plus_max_tokens,
            timeout=plus_timeout,
        )
        self.plot_architect_plus = PlotArchitectAgent(self.knowledge_base, self.memory_manager, llm=plus_llm)

        large_volume_llm = create_task_llm(
            model="qwen3.5-plus",
            max_tokens=plus_max_tokens,
            timeout=plus_timeout,
        )
        self.plot_architect_large = PlotArchitectAgent(self.knowledge_base, self.memory_manager, llm=large_volume_llm)

        logger.debug("🚀 协同扩展统一使用 deepseek-v4-pro 模型（384K 超长输出）")
        
        # 🎆 初始化分层摘要器
        self.layered_summarizer = LayeredSummarizer(
            self.knowledge_base,
            persist_directory=self.memory_manager.persist_directory,
        )

        # 🔥 初始化智能人物识别器和协同验证器
        self.character_recognizer = CharacterRecognizer()
        self.character_plot_validator = CharacterPlotValidator()
        logger.debug("🔥 已加载智能人物识别器和协同验证器")

        # 🎯 任务6.3：获取题材专属Prompt模块
        self.genre_module = GENRE_PROMPT_MODULES.get(genre, DEFAULT_GENRE_MODULE)
        logger.debug(f"🎯 题材：{genre}，已加载专属Prompt模块")

    def set_project_context(self, project_id: int) -> None:
        """设置项目上下文，供分层摘要缓存跨轮复用"""
        self.project_id = project_id

    def count_chapters_in_outline(self, outline: str) -> int:
        """智能识别大纲中的章节数

        通过正则表达式和AI判断识别当前大纲有多少章

        Args:
            outline: 当前的情节大纲

        Returns:
            识别到的章节数
        """
        import re

        if not outline or outline.strip() == '':
            return 0

        # 方法1：正则表达式匹配
        # 匹配形如："第N章"、"Chapter N"、"第N回"等
        # 🔧 关键修复：只匹配后面带有标题符号的章节，排除范围描述
        patterns = [
            r'第(\d+)章[：:、]',  # 第X章： 或 第X章、
            r'第(\d+)回[：:、]',  # 第X回： 或 第X回、
            r'Chapter\s+(\d+)[：:]',  # Chapter X:
            r'####\s*第(\d+)章',  # Markdown标题 #### 第X章
        ]

        chapter_numbers = []
        for pattern in patterns:
            matches = re.findall(pattern, outline)
            chapter_numbers.extend(matches)

        if chapter_numbers:
            # 转换中文数字为阿拉伯数字
            chinese_nums = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

            max_chapter = 0
            for num_str in chapter_numbers:
                try:
                    if num_str.isdigit():
                        max_chapter = max(max_chapter, int(num_str))
                    elif num_str in chinese_nums:
                        max_chapter = max(max_chapter, chinese_nums[num_str])
                except Exception:
                    continue

            if max_chapter > 0:
                logger.debug(f"✅ 正则识别到章节数: {max_chapter}")
                return max_chapter

        # 方法2：如果正则没有匹配到，使用AI判断
        logger.debug("⚠️  正则无法识别章节数，使用AI判断...")

        ai_prompt = f"""请分析以下大纲有多少章。

【大纲】
{outline[:1000]}

请直接返回一个数字，代表识别到的章节数。
如果无法识别或大纲太简略无明确章节划分，返回0。

示例格式：
- 如果有第1章到第5章，返回：5
- 如果是简要描述无章节，返回：0

只返回数字，不要其他内容。"""

        try:
            ai_result = self.creative_director.process(ai_prompt, {})
            # 提取数字
            import re
            numbers = re.findall(r'\d+', ai_result)
            if numbers:
                chapter_count = int(numbers[0])
                logger.debug(f"✅ AI识别到章节数: {chapter_count}")
                return chapter_count
        except Exception as e:
            logger.debug(f"❌ AI识别失败: {e}")

        logger.debug("⚠️  无法识别章节数，默认返回0")
        return 0

    def check_realm_span_and_suggest(self) -> str:
        """🎯 任务6.1：修仙题材境界跨度检查和细分建议
        
        当修仙/玄幻题材的长篇小说超过500章时，建议将境界细分
        
        Returns:
            建议文本，如果不需要建议则返回空字符串
        """
        # 只对修仙/玄幻题材生效
        if self.genre not in ["修仙", "玄幻"]:
            return ""
        
        # 只对超过500章的长篇生效
        if self.planned_chapters_max < REALM_SPAN_WARNING_THRESHOLD:
            return ""
        
        # 生成建议文本
        suggestion = f"""

【🎯 修仙题材境界跨度优化建议】

⚠️ **检测到长篇小说**：本书规划约{self.planned_chapters_max}章，属于长篇作品

**境界细分建议**：
- 📉 **推荐境界跨度**：每个大境界约{REALM_SPAN_RECOMMEND_SUBDIVISION}章以内
- ❌ **避免单个境界超过{REALM_SPAN_WARNING_THRESHOLD}章**，否则会导致：
  1. 节奏拖沓，读者疑惑"为什么还不突破"
  2. 爽点单一，缺少境界跨越的震撑感
  3. 后期境界压缩，前后不均

**具体建议**：
1. **细分大境界**：将原本5个大境界细分为7-8个，例如：
   - 原：炼气 → 筑基 → 金丹 → 元婴 → 化神
   - 改：炼气 → 筑基 → 金丹 → 元婴 → 化神 → 炼虚 → 合体 → 渡劫

2. **增加小境界层次**：每个大境界内设置3-5个小境界（初期/中期/后期/大圆满）
   - 每10-30章一个小境界突破，增加爽点密度
   - 大境界突破作为卷末高潮

3. **增加特殊体质/功法升级线**：除境界外，增加其他提升线
   - 体质觉醒：普通 → 隐藏体质 → 神体觉醒
   - 功法进阶：黄阶 → 玄阶 → 地阶 → 天阶
   - 法宝成长：法器 → 灵器 → 宝器 → 仙器

请在生成大纲时，结合以上建议，确保境界提升节奏合理，爽点分布均匀。
"""
        
        logger.debug(f"🎯 境界跨度检查：长篇{self.planned_chapters_max}章，已添加细分建议")
        return suggestion

    def count_characters_in_text(self, characters_text: str) -> int:
        """智能识别人物文本中的人物数（使用新的智能识别器）

        通过智能识别器准确识别人物数量

        Args:
            characters_text: 当前的人物设定文本

        Returns:
            识别到的人物数
        """
        if not characters_text or characters_text.strip() == '':
            return 0

        # 🔥 使用智能识别器
        count, character_names = self.character_recognizer.count_characters(
            text=characters_text,
            use_ai_verification=True  # 启用AI验证
        )

        return count

    def _extract_character_names_summary(self, characters_text: str) -> str:
        """提取角色名单摘要（仅包含姓名和基本定位，避免上下文溢出）

        Args:
            characters_text: 完整的人物设定文本

        Returns:
            简化的角色名单摘要
        """
        if not characters_text or characters_text.strip() == '':
            return "（暂无现有角色）"

        # 使用智能识别器提取角色名
        _, character_names = self.character_recognizer.count_characters(
            text=characters_text,
            use_ai_verification=False  # 不需要AI验证，快速提取即可
        )

        if not character_names:
            return "（暂无现有角色）"

        # 构建简化摘要（仅姓名列表）
        summary_lines = []
        for idx, name in enumerate(character_names, 1):
            summary_lines.append(f"{idx}. {name}")

        return "\n".join(summary_lines)

    def _story_build_character_context(
        self,
        characters_text: Any,
        *,
        detail_limit: int,
        summary_limit: int = CHARACTER_CONTEXT_SUMMARY_LIMIT,
    ) -> str:
        content = str(characters_text or "").strip()
        if not content:
            return ""

        try:
            summarized_context = build_character_prompt_context_from_text(
                content,
                detail_limit=detail_limit,
                summary_limit=summary_limit,
            )
            if summarized_context:
                return summarized_context
        except Exception:
            logger.debug("人物运行时摘要构建失败，回退到原始截断", exc_info=True)

        detail_excerpt = self._story_truncate_text(content, limit=detail_limit)
        if len(content) <= detail_limit:
            return detail_excerpt

        roster_summary = self._story_truncate_text(
            self._extract_character_names_summary(content),
            limit=summary_limit,
        )
        if not roster_summary:
            return detail_excerpt

        return f"【角色名单摘要】\n{roster_summary}\n\n【人物卡节选】\n{detail_excerpt}"
