"""
情节大纲和人物扩展器 - 自动扩展简短大纲和增加人物数量
"""
import json
import logging
import os
import re
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

VOLUME_DETAIL_CHAPTER_HEADING_PATTERN = re.compile(
    r"(?m)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*第\s*(\d+)\s*章(?:\*\*)?(?:[：:《\s]|$)"
)
VOLUME_DETAIL_RANGE_SHORTCUT_PATTERN = re.compile(
    r"(?:第\s*)?(?P<start>\d+)\s*(?:章)?\s*(?:-|~|～|—|－|至|到)\s*(?:第\s*)?(?P<end>\d+)\s*章"
)
VOLUME_DETAIL_GROUP_RANGE_PATTERN = re.compile(
    r"(?:章节|章节范围)\s*[：:]\s*(?P<start>\d+)\s*(?:-|~|～|—|－|至|到)\s*(?P<end>\d+)(?:\s*章)?"
)
VOLUME_DETAIL_MODEL_SWITCH_THRESHOLD = 80
VOLUME_DETAIL_MAX_CHAPTERS = 100
CHARACTER_CONTEXT_SUMMARY_LIMIT = 1800
CHARACTER_EXPANSION_OUTLINE_CONTEXT_LIMIT = 6000
CHARACTER_EXPANSION_CARD_CONTEXT_LIMIT = 6000
CHARACTER_EXPANSION_NEW_CARD_CONTEXT_LIMIT = 4200
CHARACTER_EXPANSION_MERGED_CONTEXT_LIMIT = 7200
EPIC_FRAMEWORK_CHARACTER_CONTEXT_LIMIT = 4200
VOLUME_DETAIL_CHARACTER_CONTEXT_LIMIT = 4200


CANONICAL_OUTLINE_CHAPTER_TEMPLATE = """- **场景目标**：（本章核心任务，30-40字）
  格式：[地点/局面] + [主要人物] + [要达成什么]

- **冲突设计**：（写清主要阻碍、升级过程与破局方向，40-80字）

- **关键事件**：
  1. ...
  2. ...

- **涉及人物**：...

- **人物推进**：（人物关系、立场、心理或能力的关键变化）

- **情节作用**：（承接/升级/转折/爆点前置/伏笔回收等）

- **结尾钩子**：（20-30字，说明下一章驱动力）

- **爽点类型**：（可选；如无明显爽点可写“无”）

- **伏笔事项**：（可选；如无则写“无”）"""


CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT = """- **场景目标**：...
- **冲突设计**：...
- **关键事件**：
  1. ...
  2. ...
- **涉及人物**：...
- **人物推进**：...
- **情节作用**：...
- **结尾钩子**：...
- **爽点类型**：...
- **伏笔事项**：..."""
from .agents import CreativeDirectorAgent, PlotArchitectAgent, CharacterDesignerAgent
from core.langchain_bridge import create_task_llm, create_model_llm
from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager
# 🎯 任务6：导入题材自适应模板系统
from .agent_coordinator import GENRE_PROMPT_MODULES, DEFAULT_GENRE_MODULE, REALM_SPAN_WARNING_THRESHOLD, REALM_SPAN_RECOMMEND_SUBDIVISION
# 🎆 引入分层摘要器
from .layered_summarizer import LayeredSummarizer
# 🆕 三层体系模块
from ..volume_connector import VolumeConnector
from ..foreshadowing_tracker import ForeshadowingTracker
from ..consistency_validator import ConsistencyValidator, get_consistency_validator, get_chapter_renumberer
# 🔥 新增：智能人物识别器和协同验证器
from .character_recognizer import CharacterRecognizer
from .character_plot_validator import CharacterPlotValidator
from ..character_parser import (
    CharacterTextParser,
    ParsedCharacter,
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
    _merge_parsed_character,
    normalize_character_name,
)
from ..character_runtime_context import build_character_prompt_context_from_text


class OutlineExpander:
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

        # 🔔 为扩展大纲固定使用 qwen3.5-plus
        self.llm = create_task_llm(task_type="outline_expand")

        # 🎆 为单卷详细扩展使用 DeepSeek-R1（深度推理能力 + 64K超长输出）
        # 官方最新能力：max_output_tokens=64K，足够生成70章大纲（约31,000字）
        r1_llm = create_task_llm(
            task_type="volume_detail_expand",
            max_tokens=64000  # 🔥 明确设置64K输出限制
        )
        self.plot_architect_r1 = PlotArchitectAgent(self.knowledge_base, self.memory_manager, llm=r1_llm)

        # 81-100章优先切到 qwen3.5-plus，避免大卷被较紧的输出窗口截断。
        plus_llm = create_task_llm(
            model="qwen3.5-plus",
            max_tokens=32768,
        )
        self.plot_architect_plus = PlotArchitectAgent(self.knowledge_base, self.memory_manager, llm=plus_llm)

        # 大卷场景也固定使用 qwen3.5-plus，严禁回退到 qwen-long
        large_volume_llm = create_task_llm(
            model="qwen3.5-plus",
            max_tokens=32768,
        )
        self.plot_architect_large = PlotArchitectAgent(self.knowledge_base, self.memory_manager, llm=large_volume_llm)

        logger.debug("🎆 单卷扩展使用 DeepSeek-R1 模型（64K超长输出能力）")
        logger.debug("🎆 单卷扩展在章节上限超过80章时固定切换到 qwen3.5-plus")
        
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

    def _legacy_expand_plot_outline(self, current_outline: str, world_setting: str,
                          characters: str, target_chapters: int = 50) -> Dict[str, Any]:
        """扩展情节大纲

        将简短大纲扩展为适合长篇小说的详细章节规划

        Args:
            current_outline: 当前的情节大纲
            world_setting: 世界观设定
            characters: 人物设定
            target_chapters: 目标章节数（默认50章，约150万字）

        Returns:
            扩展后的大纲字典，包含:
            - expanded_outline: 扩展后的完整大纲
            - chapter_breakdown: 章节分解（每章简要说明）
            - plot_arcs: 情节线索分析
            - expansion_suggestions: 扩展建议
        """
        logger.debug(f"\n{'='*70}")
        logger.debug(f"【情节大纲扩展器】启动大纲扩展，目标章节数: {target_chapters}")
        logger.debug(f"{'='*70}\n")

        # 第一步：分析当前大纲的可扩展点
        analysis_prompt = f"""你是一位资深小说策划师。请分析以下简短大纲的扩展潜力。

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

Please给出具体分析，为扩展到{target_chapters}章提供依据。"""

        logger.debug("【第一步】分析大纲扩展潜力...")
        expansion_analysis = self.creative_director.process(analysis_prompt, {})
        logger.debug("✅ 扩展潜力分析完成\n")

        # 第二步：生成情节线索
        plot_arcs_prompt = f"""基于以下分析，设计长篇小说的情节线索体系。

【扩展分析】
{expansion_analysis}

【原始大纲】
{current_outline}

Please design：
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

        logger.debug("【第二步】设计多线索情节体系...")
        plot_arcs = self.plot_architect.process(plot_arcs_prompt, {})
        logger.debug("✅ 情节线索设计完成\n")

        # 第三步：生成章节分解
        chapter_breakdown_prompt = f"""基于以下情节线索，生成详细的章节分解（{target_chapters}章）。

【情节线索】
{plot_arcs}

【原始设定】
- 世界观: {world_setting}
- 人物: {characters}

请为每一章生成结构清晰的简要说明，统一使用当前细纲字段，格式如下：

第1章：[标题]
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

第2章：[标题]
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

...（直到第{target_chapters}章）

要求：
1. 确保情节发展节奏合理（避免前松后紧）
2. 适当分布高潮章节（每10-15章一个小高潮）
3. 支线穿插自然，不影响主线推进
4. 伏笔和回收配对明确
5. 确保所有主要角色在不同阶段都有出场与推进，避免长时间“消失”。
"""

        logger.debug(f"【第三步】生成{target_chapters}章详细分解...")
        chapter_breakdown = self.plot_architect.process(chapter_breakdown_prompt, {})
        logger.debug("✅ 章节分解完成\n")

        # 第四步：生成完整扩展大纲
        expanded_outline_prompt = f"""基于以下信息，撰写完整的长篇小说情节大纲。

【章节分解】
{chapter_breakdown}

【情节线索】
{plot_arcs}

Please撰写一份完整的情节大纲，包括：
1. **故事概述**（500字）
2. **情节发展**（按起承转合分四部分）
3. **重要转折点**（列出5-8个关键转折）
4. **高潮设计**（中期高潮 + 最终高潮）
5. **结局规划**（开放式/封闭式，是否留续集空间）

这份大纲将指导{target_chapters}章的创作。"""

        logger.debug("【第四步】生成完整扩展大纲...")
        expanded_outline = self.creative_director.process(expanded_outline_prompt, {})
        logger.debug("✅ 完整大纲生成完成\n")

        logger.debug(f"{'='*70}")
        logger.debug(f"【情节大纲扩展器】扩展完成！")
        logger.debug(f"{'='*70}\n")

        return {
            "expanded_outline": expanded_outline,
            "chapter_breakdown": chapter_breakdown,
            "plot_arcs": plot_arcs,
            "expansion_analysis": expansion_analysis,
            "target_chapters": target_chapters
        }

    def _legacy_expand_characters(self, main_characters: str, world_setting: str,
                        plot_outline: str, target_count: int = 15) -> Dict[str, Any]:
        """扩展人物体系

        基于主要人物自动生成配角、对手、辅助角色等

        Args:
            main_characters: 当前主要人物设定
            world_setting: 世界观设定
            plot_outline: 情节大纲
            target_count: 目标人物总数（默认15个）

        Returns:
            扩展后的人物体系字典，包含:
            - all_characters: 完整人物列表
            - character_relationships: 人物关系网络
            - character_arcs: 人物成长线
            - role_distribution: 角色定位分布
        """
        logger.debug(f"\n{'='*70}")
        logger.debug(f"【人物体系扩展器】启动人物扩展，目标人物数: {target_count}")
        logger.debug(f"{'='*70}\n")

        # 第一步：分析现有人物和需求
        analysis_prompt = f"""你是一位资深人物设计师。请分析以下人物体系的扩展需求。

【当前主要人物】
{main_characters}

【世界观】
{world_setting}

【情节大纲】
{plot_outline}

Please分析：
1. **现有人物数量**：当前有几个主要人物
2. **角色类型缺口**：缺少哪些类型的角色（对手、导师、辅助者、中立者等）
3. **情节需求分析**：根据情节发展，需要增加哪些角色
4. **人物关系机会**：可以设计哪些有趣的人物关系
5. **多样性建议**：如何增加人物的多样性和丰富性

目标人物总数：{target_count}个（包括主角、配角、次要角色）"""

        logger.debug("【第一步】分析人物扩展需求...")
        character_analysis = self.character_designer.process(analysis_prompt, {})
        logger.debug("✅ 人物需求分析完成\n")

        # 第二步：设计角色定位分布
        primary_character = main_characters.splitlines()[0] if main_characters else "待定"
        role_distribution_prompt = f"""基于以下分析，设计人物角色定位体系。

【人物需求分析】
{character_analysis}

【现有主角】
{main_characters}

Please design{target_count}个人物的角色定位， including：

1. **主角阵营**（3-5人）
   - 主角：{primary_character}
   - 核心盟友：...
   - 导师/引路人：...

2. **对手阵营**（2-4人）
   - 主要反派：...
   - 次要对手：...
   - 中期敌人（后期可能转化）：...

3. **中立/辅助角色**（5-8人）
   - 信息提供者：...
   - 技能支持者：...
   - 情感陪伴者：...
   - 社会背景人物：...

每个角色需要注明：
- 姓名和基本设定（1句话）
- 在故事中的作用
- 与主角的关系
"""

        logger.debug("【第二步】设计角色定位体系...")
        role_distribution = self.character_designer.process(role_distribution_prompt, {})
        logger.debug("✅ 角色定位设计完成\n")

        # 第三步：生成完整人物档案
        character_profiles_prompt = f"""基于以下角色定位，为每个人物生成完整档案。

【角色定位】
{role_distribution}

【世界观】
{world_setting}

Please为{target_count}个人物生成详细档案，每个人物包括：

**格式模板**：
---
【姓名】：...
【年龄/性别】：...
【故事立场】：（主角方/反派方/中立方/亦正亦邪）
【角色定位】：（主角/盟友/对手/支持角色/中立角色等）
【所属势力】：（具体组织或无）
【外貌锚点】：（2-3句）
【性格锚点】：（可写成“性格：... / 价值倾向：...”）
【背景/当前处境】：（3-5句，简要说明过去经历与当前局面）
【核心动机】：（为什么参与故事，想要什么）
【能力与限制】：（可写成“能力：... / 限制：...”）
【关键关系】：（仅保留当前阶段最关键的3-5条关系）
【主线绑定】：（只写当前仍驱动剧情的“剧情职责：... / 关联线索：...”）
【成长方向】：（在故事中的变化，尽量用“从……到……”描述）
---

要求：
1. 人物要立体，有优点也有缺点
2. 避免脸谱化和刻板印象
3. 确保人物之间有化学反应
4. 每个人物都要有存在的价值
5. 【关键关系】不要累加已解决、已击杀、已退场或纯背景关系
6. 【主线绑定】不要写成跨阶段总账，只保留当前可直接调度的职责与线索
"""

        logger.debug(f"【第三步】生成{target_count}个人物完整档案...")
        all_characters = self.character_designer.process(character_profiles_prompt, {})
        logger.debug("✅ 人物档案生成完成\n")

        # 第四步：生成人物关系网络
        relationships_prompt = f"""基于以下人物档案，设计人物关系网络图。

【所有人物】
{all_characters}

Please design人物关系网络， including：

1. **核心关系链**
   - 主角 ↔ 盟友
   - 主角 ↔ 对手
   - 主角 ↔ 导师

2. **三角关系**
   - 人物A ↔ 人物B ↔ 人物C
   - 可以是友情、爱情、竞争等

3. **隐藏关系**
   - 在故事中后期揭示的关系
   - 意想不到的联系

4. **关系演变线**
   - 敌人→盟友
   - 陌生→亲密
   - 信任→背叛

格式示例：
- 主角 ⇄ 盟友A：战友关系，相互信任（第1章建立）
- 主角 → 导师B：单向崇拜，导师引导（第5章出现）
- 主角 ⇄ 反派C：宿敌关系，理念冲突（第10章首次交锋）
"""

        logger.debug("【第四步】生成人物关系网络...")
        character_relationships = self.character_designer.process(relationships_prompt, {})
        logger.debug("✅ 人物关系网络完成\n")

        logger.debug(f"{'='*70}")
        logger.debug(f"【人物体系扩展器】扩展完成！")
        logger.debug(f"{'='*70}\n")

        return {
            "all_characters": all_characters,
            "character_relationships": character_relationships,
            "role_distribution": role_distribution,
            "character_analysis": character_analysis,
            "target_count": target_count
        }

    def _legacy_generate_expansion_summary(self, outline_expansion: Dict[str, Any],
                                  character_expansion: Dict[str, Any]) -> str:
        """生成扩展总结报告

        Args:
            outline_expansion: 情节扩展结果
            character_expansion: 人物扩展结果

        Returns:
            格式化的扩展总结报告
        """
        summary = f"""
{'='*70}
【长篇小说扩展总结报告】
{'='*70}

## 一、情节大纲扩展

### 目标章节数
{outline_expansion.get('target_chapters', 'N/A')} 章

### 扩展策略
{outline_expansion.get('expansion_analysis', 'N/A')[:300]}...

### 情节线索
{outline_expansion.get('plot_arcs', 'N/A')[:300]}...

### 章节分解（示例前5章）
{outline_expansion.get('chapter_breakdown', 'N/A')[:500]}...

---

## 二、人物体系扩展

### 目标人物数
{character_expansion.get('target_count', 'N/A')} 个

### 角色定位
{character_expansion.get('role_distribution', 'N/A')[:300]}...

### 人物关系网络
{character_expansion.get('character_relationships', 'N/A')[:300]}...

---

## 三、实施建议

### 创作顺序
1. 使用扩展后的大纲更新 project_settings.plot_outline
2. 将扩展后的人物档案更新到 project_settings.characters
3. 保存章节分解到知识库，作为后续创作参考
4. 保存人物关系网络到知识库
5. 开始按章节顺序创作

### 注意事项
⚠️ 扩展后的内容较长，建议分阶段实施
⚠️ 在创作过程中可以根据实际情况调整细节
⚠️ 定期检查情节和人物的一致性

{'='*70}
"""
        return summary

    def _legacy_expand_plot_outline_incremental(self, current_outline: str, world_setting: str,
                                       characters: str, current_chapter_count: int,
                                       increment: int = 15,
                                       target_total_chapters: Optional[int] = None) -> Dict[str, Any]:
        """渐进式扩展情节大纲

        每次增加约15章，直到AI判断不再需要扩展

        Args:
            current_outline: 当前的情节大纲
            world_setting: 世界观设定
            characters: 人物设定
            current_chapter_count: 当前已有的章节数（如为0则自动识别）
            increment: 本次扩展的章节数（默认15章）
            target_total_chapters: 长篇小说目标总章节数（如未提供则按100章进行规划判断）

        Returns:
            扩展后的大纲字典，包含:
            - expanded_outline: 扩展后的完整大纲
            - chapter_breakdown: 章节分解
            - plot_arcs: 情节线索分析
            - current_chapter_count: 当前总章节数
            - should_continue: AI判断是否还需要继续扩展
            - continue_reason: 继续扩展的原因（如果需要）
        """
        # 🆕 智能识别当前章节数
        if current_chapter_count == 0:
            logger.debug("🔍 检测到 current_chapter_count=0，开始自动识别当前大纲的章节数...")
            detected_count = self.count_chapters_in_outline(current_outline)
            if detected_count > 0:
                current_chapter_count = detected_count
                logger.debug(f"🎯 识别成功！当前大纲已有 {current_chapter_count} 章\n")
            else:
                logger.debug("🆕 未识别到章节，从 0 章开始扩展\n")

        logger.debug(f"\n{'='*70}")
        logger.debug(f"【渐进式大纲扩展】从 {current_chapter_count} 章扩展到 {current_chapter_count + increment} 章")
        logger.debug(f"{'='*70}\n")

        target_chapters = current_chapter_count + increment

        # 🎯 任务6.1：修仙题材境界跨度检查
        realm_suggestion = self.check_realm_span_and_suggest()

        # 🎆 启用分层摘要策略 - 智能准备上下文
        logger.debug(f"\n{'='*70}")
        logger.debug(f"【分层摘要器】准备上下文")
        logger.debug(f"{'='*70}\n")
        
        context_result = self.layered_summarizer.prepare_context_for_expansion(
            outline=current_outline,
            characters=characters,
            worldview=world_setting,
            scenario="outline_expand",
            current_count=target_chapters,  # 使用目标章节数选择模型
            focus_range=None,  # 大纲扩展不需要聚焦特定范围
            project_id=self.project_id,
        )
        
        # 🔥 使用智能选择的模型
        selected_model = context_result["selected_model"]
        optimized_context = context_result["context"]
        memory_text = context_result.get("memory_text", "")
        structured_memory = context_result.get("structured_memory", {})
        stats = context_result["stats"]
        
        logger.debug(f"\n📊 上下文优化结果:")
        logger.debug(f"   - 选择模型: {selected_model}")
        logger.debug(f"   - 原始总长: {len(current_outline) + len(characters) + len(world_setting):,}字符")
        logger.debug(f"   - 优化后: {len(optimized_context):,}字符 (压缩{(1-stats['compression_ratio'])*100:.1f}%)")
        logger.debug(f"   - 结构化记忆: {len(memory_text):,}字符 / {len(structured_memory)}类")
        logger.debug(f"   - Token使用: {stats['total_tokens']:,} / {stats['target_tokens']:,} ({stats['total_tokens']/stats['target_tokens']*100:.1f}%)\n")
        
        # 🎆 更新LLM：使用智能选择的模型
        if selected_model != "qwen-long":  # 如果不是qwen-long，需要创建新的LLM
            dynamic_llm = create_model_llm(model=selected_model, temperature=0.7)
            logger.debug(f"🔄 动态创建 LLM: {selected_model}\n")
        else:
            dynamic_llm = self.llm  # 使用默认的qwen-long
            logger.debug(f"✅ 使用默认 LLM: qwen-long\n")

        # 🔥 修改：先执行扩展，再判断是否继续
        # 🆕 计算卷数和每卷章节数（网文通常每卷20-30章）
        chapters_per_volume = 25  # 每卷约25章
        volume_count = max(2, (target_chapters + chapters_per_volume - 1) // chapters_per_volume)

        # 第一步：执行扩展（网文卷结构）
        # 🎆 使用优化后的上下文替换原始内容
        expansion_prompt = f"""基于以下优化后的上下文，进行整体性扩展到{target_chapters}章。

{optimized_context}

【结构化记忆约束】
{memory_text or '（无可用结构化记忆）'}

请优先遵循上述结构化记忆中的主线弧线、人物状态、关系边、待回收伏笔和世界规则硬约束。

【网文结构设计原则】
⚠️ 网络小说不同于传统文学，需要特别注意：
1. **卷结构**：按"卷"划分，每卷有独立的小高潮和阶段性目标
2. **爽点密度**：每3-5章必须有一个爽点（打脸/升级/获得/反转）
3. **钩子设计**：每章结尾必须有悬念，让读者想点下一章
4. **节奏控制**：紧张-舒缓交替，避免长时间铺垫
5. **金手指展示**：定期展示主角的优势，给读者爽感
{self.genre_module.get('outline_rhythm_guide', '')}
{realm_suggestion}

【扩展要求】
🔥 重要：这不是简单增加章节，而是整体重新规划为网文卷结构

1. **整体视角**：从第1章到第{target_chapters}章的完整规划
2. **卷结构划分**：
   - 本书规划为**约{target_chapters}章**，分为**{volume_count}卷**
   - 每卷约{chapters_per_volume}章，有独立的阶段性高潮
   - 各卷章节数可灵活调整，但总数应接近{target_chapters}章

3. **人物全覆盖**：
   - 确保参考所有已生成的人物（主角、对手、支持、中立阵营）
   - 每个重要角色都有充分的出场和发展
   - 避免角色在后续章节中消失

4. **爽点节奏规划**：
   - 每5章一个小爽点（打脸/升级/获得宝物）
   - 每25章（卷末）一个大爽点（击败Boss/重大突破）
   - 爽点类型：打脸/升级/获得宝物/装逼成功/反转翻盘/美人倾心/万众瞩目

5. **钩子设计**：
   - 每章结尾必须有悬念或钩子
   - 钩子类型：悬念式/危机式/反转式/升级式/对决式

Please生成完整的{target_chapters}章规划（🔥重点：每章必须有完整的详细规划）：

## 一、故事概述
[基于扩展后的完整故事，概述核心概念、主线冲突、主角成长轨迹，300-500字]

---

## 二、卷结构与章节详情（共{volume_count}卷，约{target_chapters}章）

### 【第一卷】「卷名」

**卷概述**：
- **章节范围**：第1-{chapters_per_volume}章
- **阶段目标**：（本卷主角的核心目标）
- **核心冲突**：（本卷的主要矛盾）
- **卷末高潮**：（本卷结尾的高潮事件）
- **关键人物**：（本卷重点登场人物）

**章节详情**：

#### 第1章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE}

#### 第2章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

#### 第3章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}
（以下第4章、第5章直到本卷最后一章，全部完整输出，禁止使用"...略"、"继续输出"、"其余省略"等占位符）

⚠️ 【极重要】必须逐章完整输出，每章包含所有字段，不可跳过任何章节！

---

### 【第二卷】「卷名」

**卷概述**：
- **章节范围**：...
- **阶段目标**：...

**章节详情**：

#### 第N章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE}
（后续章节全部完整输出，禁止省略）

---

（后续各卷，直到第{volume_count}卷的最后一章，每卷每章都必须完整输出）

---

## 三、爽点节奏总览

| 卷 | 章节 | 爽点类型 | 爽点描述 | 强度 |
|----|------|----------|----------|------|
| 一 | 第3章 | 首秀 | 首次展示金手指 | ⭐⭐ |
| 一 | 第{chapters_per_volume}章 | 卷末大爽 | 击败本卷Boss | ⭐⭐⭐⭐⭐ |
| ... | ... | ... | ... | ... |

---

## 四、情节线索总览

| 线索名称 | 类型 | 起始章 | 关键节点 | 收束章 |
|----------|------|--------|----------|--------|
| 主线 | 核心 | 第1章 | 第X章转折 | 第{target_chapters}章 |
| 支线A | 感情 | 第X章 | 第Y章 | 第Z章 |

---

## 五、人物出场统计

| 角色 | 阵营 | 首次登场 | 关键章节 | 角色弧光 |
|------|------|----------|----------|----------|
| 主角 | 主角 | 第1章 | 1,X,Y,Z | 成长轨迹 |
| ... | ... | ... | ... | ... |"""

        logger.debug(f"【第一步】整体性扩展章节（重新规划第1-{target_chapters}章）...")
        logger.debug(f"   📌 参考优化后的上下文（{len(optimized_context):,}字符）")
        logger.debug(f"   🔄 从{current_chapter_count}章整体扩展到{target_chapters}章")
        logger.debug(f"   🤖 调用模型: {selected_model}")
        
        # 🔥 使用动态选择的LLM
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="你是一位杰出的情节架构师，精通网络小说结构设计与爽点节奏规划。"),
            HumanMessage(content=expansion_prompt)
        ]
        response = dynamic_llm.invoke(messages)
        expansion_content = response.content
        logger.debug("✅ 章节扩展完成\n")

        # 第二步：整合更新大纲（不是简单追加，而是整体重构）
        integration_prompt = f"""基于当前大纲和新扩展的章节规划，生成一份完整的、结构清晰的大纲。

【原有大纲】
{current_outline}

【新扩展的章节规划】
{expansion_content}

【整合要求】
🔥 重要：这是整体重构，不是简单拼接

1. **不要简单堆码**：
   - 不要直接把新内容追加在后面
   - 不要保留重复的章节
   - 不要有“原有章节”和“新增章节”的分隔

2. **网文卷结构**：
   - 按"卷"划分，每卷{chapters_per_volume}章左右
   - 共{volume_count}卷，总计{target_chapters}章
   - 每卷有独立的阶段性高潮和爽点设计

3. **章节信息完整**：
   - 🔥 每章必须包含统一核心字段，并可按需要补充【爽点类型】【伏笔事项】等增强字段
   - 确保第1章到第{target_chapters}章都有详细规划
   - 所有人物都有合理出场和发展

4. **爽点和钩子集成**：
   - 爽点和钩子信息直接写在每章内，不要分离成单独表格
   - 同时在末尾提供爽点总览表便于快速查看

Please输出完整的、重新整合后的网文大纲（🔥重点：每章必须有完整的详细规划）：

## 一、故事概述
[整合后的完整故事概述，300-500字]

---

## 二、卷结构与章节详情（共{volume_count}卷，约{target_chapters}章）

### 【第一卷】「卷名」

**卷概述**：
- **章节范围**：第1-{chapters_per_volume}章
- **阶段目标**：（本卷主角的核心目标）
- **核心冲突**：（本卷的主要矛盾）
- **卷末高潮**：（本卷结尾的高潮事件）
- **关键人物**：（本卷重点登场人物）

**章节详情**：

#### 第1章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE}

#### 第2章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

#### 第3章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}
（以下第4章、第5章直到本卷最后一章，全部完整输出，禁止使用"...略"、"继续输出"、"其余省略"等占位符）

⚠️ 【极重要】必须逐章完整输出，每章包含所有字段，不可跳过任何章节！

---

### 【第二卷】「卷名」

**卷概述**：
- **章节范围**：...
- **阶段目标**：...

**章节详情**：

#### 第N章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE}
（后续章节全部完整输出，禁止省略）

---

## 三、爽点节奏总览

| 卷 | 章节 | 爽点类型 | 爽点描述 | 强度 |
|----|------|----------|----------|------|
| 一 | 第3章 | 首秀 | ... | ⭐⭐ |
| ... | ... | ... | ... | ... |

---

## 四、情节线索总览

| 线索名称 | 类型 | 起始章 | 关键节点 | 收束章 |
|----------|------|--------|----------|--------|
| 主线 | 核心 | 第1章 | 第X章 | 第{target_chapters}章 |

---

## 五、人物出场统计

| 角色 | 阵营 | 首次登场 | 关键章节 | 角色弧光 |
|------|------|----------|----------|----------|
| 主角 | 主角 | 第1章 | ... | ... |"""

        logger.debug(f"【第二步】整体重构大纲（最佳格式：章节详情+总览表）...")
        logger.debug(f"   🔄 重新组织所有{target_chapters}章的内容")
        logger.debug(f"   🤖 调用模型: {selected_model}")
        
        # 🔥 使用动态选择的LLM
        messages = [
            SystemMessage(content="你是一位杰出的情节架构师，精通网络小说结构设计与卷结构整合。"),
            HumanMessage(content=integration_prompt)
        ]
        response = dynamic_llm.invoke(messages)
        integrated_outline = response.content
        logger.debug("✅ 大纲整体重构完成\n")
        # 🆕 长篇小说目标章节数（用于判断是否继续扩展）
        long_novel_target = target_total_chapters or 100
        lower_threshold = int(long_novel_target * 0.5)
        upper_threshold = int(long_novel_target * 0.9)


        # 🔥 第三步：AI判断是否需要继续扩展（简化提示词，只传递统计信息）
        analysis_prompt = f"""你是一位资深小说策划师。Please analyze以下大纲是否 needs继续扩展。

【当前状态】
- 当前已有章节数：{target_chapters}
- 刚完成扩展：从{current_chapter_count}章扩展到{target_chapters}章
- 长篇目标总章节数：{long_novel_target}章

Please analyze：
1. **当前大纲的完整性**：是否已经覆盖了完整的故事线（开端、发展、高潮、结局）
2. **情节密度**：每章的情节容量是否合适，是否需要更多的过渡或详细描写
3. **支线发展**：是否有未展开的支线故事或人物关系
4. **伏笔和回收**：是否需要更多的伏笔铺垫

最后，以JSON格式回答：
{{
  "should_continue": true/false,
  "reason": "原因说明（100字以内）"
}}

判断标准（面向长篇小说）：
- 如果当前章节数 < {lower_threshold}，通常建议继续扩展（重点补充主线和支线）
- 如枟 {lower_threshold}-{upper_threshold} 章，根据故事完整性和情节复杂度判断
- 如果 > {upper_threshold} 章，需要非常充分的理由才继续扩展（例如仍有重要支线或伏笔尚未完成）
- 如果已有完整的故事结构，应该停止扩展"""

        logger.debug("【第三步】AI判断是否需要继续扩展...")
        logger.debug(f"   🤖 调用模型: {selected_model}")
        
        # 🔥 使用动态选择的LLM
        messages = [
            SystemMessage(content="你是一位资深小说策划师，擅长分析大纲完整性与判断是否需要继续扩展。"),
            HumanMessage(content=analysis_prompt)
        ]
        response = dynamic_llm.invoke(messages)
        analysis_result = response.content

        # 解析JSON结果
        import json
        import re

        # 提取JSON内容
        json_match = re.search(r'\{[\s\S]*?"should_continue"[\s\S]*?\}', analysis_result)
        should_continue = True
        continue_reason = ""

        if json_match:
            try:
                decision = json.loads(json_match.group())
                should_continue = decision.get('should_continue', True)
                continue_reason = decision.get('reason', '')
                logger.debug(f"✅ AI决策：{'继续扩展' if should_continue else '停止扩展'}")
                logger.debug(f"   原因：{continue_reason}")
            except Exception:
                logger.debug("⚠️  无法解析AI结果，默认继续扩展")
        else:
            logger.debug("⚠️  无法解析AI结果，默认继续扩展")

        logger.debug(f"{'='*70}")
        logger.debug(f"【渐进式大纲扩展】本轮完成！")
        logger.debug(f"{'='*70}\n")

        return {
            "expanded_outline": integrated_outline,  # 🔥 返回整合后的大纲
            "chapter_breakdown": expansion_content,
            "plot_arcs": {},  # 🔥 前端会智能提取摘要
            "current_chapter_count": target_chapters,
            "should_continue": should_continue,
            "continue_reason": continue_reason
        }

    def _expand_characters_incremental_with_layered_context(self, main_characters: str, world_setting: str,
                                                            plot_outline: str, current_character_count: int,
                                                            increment: int = 5,
                                                            target_total_characters: Optional[int] = None) -> Dict[str, Any]:
        """渐进式扩展人物体系

        每次增加3-6个角色，直到AI判断不再需要扩展

        Args:
            main_characters: 当前主要人物设定
            world_setting: 世界观设定
            plot_outline: 情节大纲
            current_character_count: 当前已有的人物数（如为0则自动识别）
            increment: 本次扩展的人物数（默认5个）
            target_total_characters: 长篇小说目标人物总数（如未提供则按25人进行规划判断）

        Returns:
            扩展后的人物体系字典，包含:
            - all_characters: 完整人物列表
            - character_relationships: 人物关系网络
            - role_distribution: 角色定位分布
            - current_character_count: 当前总人物数
            - should_continue: AI判断是否还需要继续扩展
            - continue_reason: 继续扩展的原因（如果需要）
        """
        # 🆕 智能识别当前人物数
        if current_character_count == 0:
            logger.debug("🔍 检测到 current_character_count=0，开始自动识别当前人物数...")
            detected_count = self.count_characters_in_text(main_characters)
            if detected_count > 0:
                current_character_count = detected_count
                logger.debug(f"🎯 识别成功！当前已有 {current_character_count} 个人物\n")
            else:
                logger.debug("🆕 未识别到人物，从 0 个开始扩展\n")

        # 🔥 新增：验证人物-情节匹配度
        if current_character_count > 0 and main_characters and plot_outline:
            logger.debug("🔍 开始验证人物-情节匹配度...")
            validation = self.character_plot_validator.validate_character_plot_alignment(
                characters=main_characters,
                plot_outline=plot_outline,
                world_setting=world_setting
            )

            logger.debug(f"📊 人物-情节匹配度: {validation['score']}/100")

            # 如果匹配度过低，建议先优化
            if validation['score'] < 60:
                logger.debug("⚠️ 匹配度较低，建议先优化现有人物与情节的关联")
                logger.debug(f"   冗余人物: {len(validation['redundant_characters'])}个")
                logger.debug(f"   缺失人物: {len(validation['missing_characters'])}个")
                logger.debug(f"   关系问题: {len(validation['relationship_issues'])}个")

                # 返回优化建议
                return {
                    "should_optimize_first": True,
                    "validation_score": validation['score'],
                    "validation_details": validation,
                    "current_character_count": current_character_count,
                    "optimization_suggestions": validation['suggestions'],
                    "message": "建议先优化现有人物与情节的关联，再进行扩展"
                }
            else:
                logger.debug(f"✅ 匹配度良好，可以继续扩展")
                if validation['missing_characters']:
                    logger.debug(f"💡 建议优先补充: {', '.join(validation['missing_characters'][:3])}")

        logger.debug(f"\n{'='*70}")
        logger.debug(f"【渐进式人物扩展】从 {current_character_count} 个扩展到 {current_character_count + increment} 个")
        logger.debug(f"{'='*70}\n")

        target_count = current_character_count + increment

        # 🎆 启用分层摘要策略 - 智能准备上下文
        context_result = self.layered_summarizer.prepare_context_for_expansion(
            outline=plot_outline,
            characters=main_characters,
            worldview=world_setting,
            scenario="character_expand",
            current_count=target_count,  # 使用目标人物数选择模型
            focus_range=None,  # 人物扩展不需要聚焦特定范围
            project_id=self.project_id,
        )
        
        # 🔥 使用智能选择的模型
        selected_model = context_result["selected_model"]
        optimized_context = context_result["context"]
        memory_text = context_result.get("memory_text", "")
        structured_memory = context_result.get("structured_memory", {})
        stats = context_result["stats"]
        
        # 打印优化结果日志
        logger.debug(f"\n📊 上下文优化结果:")
        logger.debug(f"   - 选择模型: {selected_model}")
        logger.debug(f"   - 原始总长: {len(plot_outline) + len(main_characters) + len(world_setting):,}字符")
        logger.debug(f"   - 优化后: {len(optimized_context):,}字符 (压缩{(1-stats['compression_ratio'])*100:.1f}%)")
        logger.debug(f"   - 结构化记忆: {len(memory_text):,}字符 / {len(structured_memory)}类")
        logger.debug(f"   - Token使用: {stats['total_tokens']:,} / {stats['target_tokens']:,}\n")

        # 🎆 更新LLM：使用智能选择的模型
        if selected_model != "qwen-long":
            dynamic_llm = create_model_llm(model=selected_model, temperature=0.8, max_tokens=4000)
        else:
            dynamic_llm = self.character_designer.llm
        
        # 临时替换LLM
        original_llm = self.character_designer.llm
        self.character_designer.llm = dynamic_llm
        
        try:
            # 🆕 获取题材专属人物字段
            character_extra_fields = self.genre_module.get('character_extra_fields', '')
            genre_specific_hint = f"\n\n🎯 【题材专属细化】（以下为人物设定的补充字段，请结合使用）\n{character_extra_fields}" if character_extra_fields else ""

            # 🔥 修改：先执行扩展，再判断是否继续
            # 第一步：执行扩展（使用优化后的上下文）
            expansion_prompt = f"""基于以下优化后的上下文，扩展到{target_count}个角色。

{optimized_context}

【结构化记忆约束】
{memory_text or '（无可用结构化记忆）'}

请优先保持现有人物状态、关系边和待回收伏笔的一致性，新角色必须围绕这些约束补位，而不是破坏它们。

【扩展要求】
- 新增 {increment} 个角色（从第{current_character_count + 1}个开始）
- 每个新角色需要完整的人物卡信息，至少覆盖：
  * 姓名、年龄/性别
  * 故事立场：主角方/反派方/中立方/亦正亦邪
  * 角色定位、所属势力
  * 外貌锚点、性格锚点
  * 背景/当前处境、核心动机
  * 能力与限制（必须同时写优势和短板）
  * 关键关系、主线绑定
  * 成长方向（能明确再写）

🔥 重要输出格式要求：
Please直接按阵营分类输出，格式如下（每个人物必须包含完整人物卡字段，**每个字段后必须换行**）：

⚠️ 【重要：姓名创作要求】
- **必须创作独特姓名**：不要使用常见、普通的名字
- **符合题材风格**：修仙题材用古风名字，科幻题材用现代或未来感名字，西幻题材用西式名字
- **避免重复**：每个人物的名字必须不同，不要使用如“林墨”、“苏娜”、“陈朔”、“老周”、“张伟”等示例名
- **富有意境**：名字应该有寃意或符号意义，与角色性格或命运相关

## 主角阵营

### 【姓名】：（请生成独特姓名）

【年龄/性别】：...

【故事立场】：主角方

【角色定位】：...

【所属势力】：...

【外貌锚点】：...

【性格锚点】：性格：...
价值倾向：...

【背景/当前处境】：...

【核心动机】：...

【能力与限制】：能力：...
限制：...

【关键关系】：...

【主线绑定】：剧情职责：...
关联线索：...

【成长方向】：...

---

### 【姓名】：（请生成独特姓名）

【年龄/性别】：...

...

---

## 对手阵营

### 【姓名】：（请生成独特姓名）
...

## 支持角色

### 【姓名】：（请生成独特姓名）
...

## 中立角色

### 【姓名】：（请生成独特姓名）
...

注意：
1. **关键：每个字段后必须有两个换行符**，保证排版清晰
2. 不要单独列出“新增角色列表”，直接合并到各阵营中
3. 使用【姓名】格式，方便识别和统计
4. 每个阵营的角色按重要性排序
5. 人物之间使用 --- 分隔线
6. 确保所有{target_count}个角色都包含在内{genre_specific_hint}"""

            logger.debug(f"【第一步】扩展角色（{current_character_count + 1}-{target_count}个）...")
            try:
                expansion_content = self.character_designer.process(expansion_prompt, {})
                logger.debug("✅ 角色扩展完成\n")
            except Exception as e:
                logger.debug(f"❌ 角色扩展失败: {e}")
                import traceback
                traceback.print_exc()
                raise

            # 第二步：整合更新人物体系（🔥 优化：仅传递现有角色摘要，避免上下文溢出）
            # 🔥 从 main_characters 中提取现有角色名单（避免传递完整上下文）
            existing_characters_summary = self._extract_character_names_summary(main_characters)

            integration_prompt = f"""Please将新扩展的角色整合到现有人物体系中，生成一份完整的、结构清晰的人物档案。

【现有角色名单】（共{current_character_count}个）
{existing_characters_summary}

【结构化记忆约束】
{memory_text or '（无可用结构化记忆）'}

【新增角色】
{expansion_content}

【整合要求】
1. **不要简单堆码**：不要直接把新内容追加在后面
2. **按阵营重新组织**：所有角色按阵营分类（主角、对手、支持、中立）
3. **信息完整但避免胖字段**：保留角色的可用信息密度，但把冗余字段折叠进“性格锚点 / 能力与限制 / 主线绑定”等核心字段
4. **统一档案格式**：所有角色使用相同的精简档案格式，直接服务后续大纲扩展和章节生成
5. **去重去重复**：如果有重复的角色，只保留一份最完整的
6. **规模控制**：在保证角色完整性的前提下，尽量让总人数接近{target_count}个（允许±2人的浮动）

Please输出完整的、重新整合后的人物档案，**每个字段后必须有两个换行符**，格式如下：

## 主角阵营

### 【姓名】：[姓名]

【年龄/性别】：...

【故事立场】：...

【角色定位】：主角/核心配角 等

【所属势力】：...

【外貌锚点】：...

【性格锚点】：性格：...
价值倾向：...

【背景/当前处境】：...

【核心动机】：...

【能力与限制】：能力：...
限制：...

【关键关系】：（仅保留当前阶段最关键的3-5条关系）

【主线绑定】：剧情职责：...
关联线索：...

【成长方向】：...

---

...（所有主角阵营角色）

## 对手阵营

### 【姓名】：[姓名]
...

## 支持角色

### 【姓名】：[姓名]
...

## 中立角色

### 【姓名】：[姓名]
...

确保所有{target_count}个角色都包含在内，按重要性排序。人物之间使用 --- 分隔。"""

            logger.debug(f"【第二步】整合更新人物体系（不进行简单堆码）...")
            try:
                integrated_characters = self.character_designer.process(integration_prompt, {})
                logger.debug("✅ 人物体系整合完成\n")
            except Exception as e:
                logger.debug(f"❌ 人物体系整合失败: {e}")
                import traceback
                traceback.print_exc()
                raise

            # 第三步：生成人物关系网络
            relationship_prompt = f"""基于以下完整的人物体系，生成完整的人物关系网络。

【所有人物】
{integrated_characters}

Please以下列格式生成人物关系网络：

### 人物关系网络

**主角阵营内部**：
- [角色A] ↔ [角色B]：[关系类型]（[关系描述]）

**对手阵营内部**：
- [角色C] ↔ [角色D]：[关系类型]（[关系描述]）

**跨阵营关系**：
- [主角] ↔ [对手]：[关系类型]（[关系描述]）

**支持角色关系**：
- [支持角色] ↔ [主要角色]：[关系类型]（[关系描述]）

Please确保：
1. 包含所有{target_count}个角色
2. 关系类型包括：师徒、盟友、对手、亲人、同事、竞争等
3. 每个关系都有简短描述（20字以内）"""

            logger.debug(f"【第三步】生成人物关系网络...")
            relationships = self.character_designer.process(relationship_prompt, {})
            logger.debug("✅ 关系网络生成完成\n")

            # 第四步：统计角色分布
            distribution_input = integrated_characters
            max_chars_raw = os.getenv("CHARACTER_DISTRIBUTION_MAX_CHARS", "60000")
            try:
                max_chars = max(10000, int(max_chars_raw))
            except Exception:
                max_chars = 60000
            if len(distribution_input) > max_chars:
                distribution_input = distribution_input[:max_chars].rstrip() + "\n\n[已截断：内容过长]"
                logger.debug(f"⚠️  角色体系统计超长，已截断到 {max_chars} 字符用于分布统计")

            distribution_prompt = f"""基于以下完整的人物体系，统计角色分布。

【所有人物】
{distribution_input}

Please以以下格式输出JSON：
{{
  "主角": 数量,
  "配角": 数量,
  "对手": 数量,
  "支持角色": 数量,
  "中立角色": 数量
}}

Please确保所有数量加起来等于{target_count}。
只返回JSON，不要其他文字。"""

            logger.debug(f"【第四步】统计角色分布...")
            distribution_result = self.character_designer.process(distribution_prompt, {})
            logger.debug("✅ 角色分布统计完成\n")

            # 解析角色分布JSON
            import json
            import re

            distribution_dict = {}
            json_match = re.search(r'\{[\s\S]*?\}', distribution_result)
            if json_match:
                try:
                    distribution_dict = json.loads(json_match.group())
                    logger.debug(f"✅ 角色分布：{distribution_dict}")
                except Exception:
                    logger.debug("⚠️  无法解析角色分布JSON")


            # 🆕 长篇小说目标人物数量（用于判断是否继续扩展）
            character_target = target_total_characters or 25
            lower_threshold = max(15, character_target - 10)
            upper_threshold = character_target + 5

            # 🔥 第五步：AI判断是否需要继续扩展（在扩展完成后判断）
            # 🔥 优化：只传递统计信息，不传递完整文本，避免超过token限制
            analysis_prompt = f"""你是一位资深人物设计师。Please analyze以下人物体系是否 needs继续扩展。

【当前状态】
- 当前已有人物数：{target_count}
- 刚完成扩展：从{current_character_count}个扩展到{target_count}个
- 长篇目标人物数：{character_target}个
- 角色分布：{distribution_dict}

Please analyze：
1. **主要角色覆盖**：主角、配角、对手、师友等关键角色是否齐全
2. **角色均衡**：正面、负面、中立角色的比例是否合适

最后，以JSON格式回答：
{{
  "should_continue": true/false,
  "reason": "原因说明（100字以内）"
}}

判断标准（面向长篇小说人物体系）：
- 如果当前人物数 < {lower_threshold}，通常建议继续扩展，补足主要角色和关键配角
- 如果 {lower_threshold}-{character_target} 个，根据角色分布情况判断
- 如果 {character_target}-{upper_threshold} 个，偏向于收束人物，只在确有需要时少量补充
- 如果 > {upper_threshold} 个，需要非常充分的理由才继续扩展，避免角色过多导致人物形象被稀释"""

            logger.debug("【第五步】AI判断是否需要继续扩展...")
            analysis_result = self.character_designer.process(analysis_prompt, {})

            # 解析JSON结果
            import json
            import re

            json_match = re.search(r'\{[\s\S]*?"should_continue"[\s\S]*?\}', analysis_result)
            should_continue = True
            continue_reason = ""

            if json_match:
                try:
                    decision = json.loads(json_match.group())
                    should_continue = decision.get('should_continue', True)
                    continue_reason = decision.get('reason', '')
                    logger.debug(f"✅ AI决策：{'继续扩展' if should_continue else '停止扩展'}")
                    logger.debug(f"   原因：{continue_reason}")
                except Exception:
                    logger.debug("⚠️  无法解析AI结果，默认继续扩展")
            else:
                logger.debug("⚠️  无法解析AI结果，默认继续扩展")

            # 🔥 新增：扩展后二次验证
            post_validation_score = 0
            post_validation_details = {}

            if plot_outline:
                logger.debug("🔍 开始扩展后验证...")
                post_validation = self.character_plot_validator.validate_character_plot_alignment(
                    characters=integrated_characters,
                    plot_outline=plot_outline,
                    world_setting=world_setting
                )
                post_validation_score = post_validation['score']
                post_validation_details = post_validation

                logger.debug(f"📊 扩展后匹配度: {post_validation_score}/100")

                if post_validation_score >= 70:
                    logger.debug("✅ 人物与情节匹配良好")
                elif post_validation_score >= 60:
                    logger.debug("⚠️ 匹配度一般，建议关注以下问题：")
                    if post_validation['redundant_characters']:
                        logger.debug(f"   - 冗余人物: {', '.join(post_validation['redundant_characters'][:3])}")
                    if post_validation['missing_characters']:
                        logger.debug(f"   - 缺失人物: {', '.join(post_validation['missing_characters'][:3])}")
                else:
                    logger.debug("❌ 匹配度较低，强烈建议优化")

            logger.debug(f"{'='*70}")
            logger.debug(f"【渐进式人物扩展】本轮完成！")
            logger.debug(f"{'='*70}\n")

            return {
                "all_characters": integrated_characters,  # 🔥 返回整合后的人物体系
                "character_relationships": relationships,  # 🔥 现在生成完整的关系网络
                "role_distribution": distribution_dict,  # 🔥 现在生成角色分布
                "current_character_count": target_count,
                "should_continue": should_continue,
                "continue_reason": continue_reason,
                "post_validation_score": post_validation_score,  # 🔥 新增：扩展后匹配度
                "post_validation_details": post_validation_details  # 🔥 新增：详细验证结果
            }
        finally:
            # 🔄 恢复原始 LLM
            self.character_designer.llm = original_llm

    def _legacy_generate_epic_framework(self, world_setting: str, characters: str,
                               total_volumes: int, total_chapters_range: tuple[int, int]) -> Dict[str, Any]:
        """生成史诗框架（超长网文总体规划）
        
        为1000+章的超长网文生成宏观框架，每卷仅200-300字概要
        
        Args:
            world_setting: 世界观设定
            characters: 人物设定
            total_volumes: 总卷数(10-50卷)
            total_chapters_range: 总章节范围(min, max)
            
        Returns:
            史诗框架字典，包含:
            - expanded_outline: 史诗框架内容
            - total_volumes: 总卷数
            - estimated_chapters: 预估总章节数
        """
        logger.debug(f"\n{'='*70}")
        logger.debug(f"🌟 【史诗框架生成器】{total_volumes}卷，预计{total_chapters_range[0]}-{total_chapters_range[1]}章")
        logger.debug(f"{'='*70}\n")
        
        framework_prompt = f"""你是顶级网文架构师，擅长规划超长篇网文（1000章以上）。

【任务】
规划一部{total_volumes}卷的超长网文，预计{total_chapters_range[0]}-{total_chapters_range[1]}章

【当前设定】
世界观：
{world_setting}

主要人物：
{characters[:1000] if characters else '待完善'}

【输出要求】
⚠️ 这是史诗框架，不是详细大纲！每卷仅需200-300字概要

## 一、整体叙事节奏
分为前中后三期，每期占多少卷，预计章节数：
- 前期（第1-X卷）：主题/场景 → Y章
- 中期（第X-Y卷）：主题/场景 → Z章
- 后期（第Y-{total_volumes}卷）：主题/场景 → W章

## 二、境界/实力体系进阶
🔥 根据题材和总章数智能规划：

【境界密度规则】
- 若总章数 < 500：大境界3-5个，每大境界80-150章
- 若500-1500章：大境界5-8个，每大境界100-200章
- 若 > 1500章：大境界8-12个，每大境界120-250章

【题材适配】
- 修仙类：炼气→1-9层→筑基→金丹→元婴→化神→合体→渡劫（可下分初/中/后期）
- 玄幻类：战士→战师1-9星→大斗师→斗灵→斗圣→斗帝
- 武侠类：三流→二流→一流→宗师→大宗师→武圣
- 都市类：以财富/权势/影响力为阶段，如：起步→初有成就→行业精英→领域霸主

【具体要求】
1. 首先分析世界观是什么题材（修仙/玄幻/武侠/都市/其他）
2. 根据总章数{total_chapters_range[0]}-{total_chapters_range[1]}决定大境界数量
3. 每个大境界应分配60-200章，避免500+章才进阶一次
4. 修仙类需考虑小境界（如炼气1-9层），提供更频繁的成就感
5. 列出具体的境界进阶路径，格式如：
   - 第1-3卷：炼气1层→9层（约120-180章）
   - 第4-6卷：筑基初期→后期（约150-200章）
   - 第7-10卷：金丹初期→后期（约200-280章）
   - ...

⚠️ 关键：不要固定“有5卷一个大境界”，而是根据题材和总章数灵活调整！

## 三、{total_volumes}卷概要
❗️❗️ 每卷最多{VOLUME_DETAIL_MAX_CHAPTERS}章！如果内容多就增加卷数，不要让单卷超过{VOLUME_DETAIL_MAX_CHAPTERS}章 ❗️❗️

每卷格式：
【第X卷】卷名（预计30-{VOLUME_DETAIL_MAX_CHAPTERS}章，不得超过{VOLUME_DETAIL_MAX_CHAPTERS}章）
- 核心：本卷主题/目标
- 境界：主角境界范围（如：炼气3层→7层）
- 主要敌人：本卷Boss
- 卷末高潮：关键事件

## 四、关键伏笔布局
| 伏笔 | 埋设位置 | 铺垫卷 | 揭秘卷 |
|------|---------|--------|--------|
| 主角真实身份 | 第X卷 | 第Y,Z卷 | 第W卷 |
| 天道黑幕 | 第A卷 | 第B,C卷 | 第D卷 |
(至少10条跨卷伏笔)

## 五、核心人物生命周期
| 角色 | 登场 | 活跃期 | 退场/转型 |
|------|------|--------|-------------|
| 女主 | 第1卷 | 1-{total_volumes}卷 | 始终在线 |
| 师父 | 第1卷 | 1-8卷 | 第9卷羽化 |
(主要角色的登场退场规划)

记住：这是框架，不是详细大纲，保持高层视角！"""

        logger.debug("【第一步】生成史诗框架...")
        
        # 🛡️ 重试机制：处理网络波动
        import time
        max_retries = 3
        retry_delays = [2, 4, 8]  # 指数退避
        
        for attempt in range(max_retries):
            try:
                framework_content = self.creative_director.process(framework_prompt, {})
                logger.debug("✅ 史诗框架生成完成\n")
                break  # 成功则跳出重试循环
            except Exception as e:
                error_str = str(e).lower()
                # 检查是否是网络连接错误
                is_connection_error = any(keyword in error_str for keyword in [
                    'connection', 'ssl', 'timeout', 'eof', 'network', 'reset'
                ])
                
                if is_connection_error and attempt < max_retries - 1:
                    delay = retry_delays[attempt]
                    logger.debug(f"⚠️ 网络连接失败，{delay}秒后重试（第{attempt + 1}/{max_retries}次）...")
                    time.sleep(delay)
                    continue
                else:
                    # 非网络错误或最后一次重试失败
                    logger.debug(f"❌ 史诗框架生成失败: {e}")
                    raise
        
        logger.debug(f"{'='*70}")
        logger.debug(f"【史诗框架生成】完成！")
        logger.debug(f"{'='*70}\n")
        
        return {
            "expanded_outline": framework_content,
            "total_volumes": total_volumes,
            "estimated_chapters": (total_chapters_range[0] + total_chapters_range[1]) // 2,
            "framework_type": "epic"
        }
    
    def _legacy_expand_volume_detail(self, framework_content: str, target_volume_index: int,
                            world_setting: str, characters: str,
                            start_chapter_num: int,
                            chapters_count_range: tuple[int, int],
                            prev_volume_summary: Optional[Dict[str, Any]] = None,
                            pending_foreshadowings: Optional[List[Dict[str, Any]]] = None,
                            core_storyline: Optional[str] = None,
                            framework_header: Optional[str] = None,
                            framework_footer: Optional[str] = None) -> Dict[str, Any]:
        """基于史诗框架详细扩展单卷（三层体系增强版）
        
        根据已有的史诗框架，将指定的卷扩展为详细的章节大纲。
        采用「顶层框架锚定+卷级接口约束+章节锚点承接」三层体系。
        
        Args:
            framework_content: 史诗框架内容
            target_volume_index: 扩展第几卷
            world_setting: 世界观设定
            characters: 人物设定
            start_chapter_num: 起始章节号
            chapters_count_range: 本卷章节数量范围(min, max)，AI在此范围内自由发挥
            prev_volume_summary: 上一卷摘要信息（可选），包含：
                - core_plot_completed: 本卷完成的核心剧情
                - character_status_update: 人物状态更新
                - new_foreshadowings: 新埋下的伏笔
                - ending_hook: 卷尾钩子
                - next_volume_target: 下卷开局目标
            pending_foreshadowings: 待处理伏笔清单（可选），每项包含：
                - content: 伏笔内容
                - planted_volume: 埋设卷
                - action: 本卷动作（plant/pave/reveal）
            core_storyline: 全书核心主线（可选）
            framework_header: 🌟 框架头部（整体叙事节奏、境界体系等全局约束）
            framework_footer: 🌟 框架尾部（伏笔布局、人物生命周期等全局约束）
            
        Returns:
            单卷详细字典，包含:
            - expanded_outline: 详细大纲
            - volume_index: 卷索引
            - chapter_count: 实际章节数
        """
        logger.debug(f"\n{'='*70}")
        logger.debug(f"📖 【单卷详细扩展】第{target_volume_index}卷，从第{start_chapter_num}章开始，生成{chapters_count_range[0]}-{chapters_count_range[1]}章")
        logger.debug(f"{'='*70}\n")

        # 🔥 智能模型选择：根据章节数量自动选择最合适的模型
        avg_chapters = (chapters_count_range[0] + chapters_count_range[1]) // 2
        estimated_words = avg_chapters * 450  # 每章约450字

        if avg_chapters > 80:
            # 超大卷（>80章）：固定使用 qwen3.5-plus
            selected_architect = self.plot_architect_large
            model_name = "qwen3.5-plus"
            logger.debug(f"🔄 检测到超大卷（{avg_chapters}章，约{estimated_words}字），固定使用 qwen3.5-plus 模型")
            logger.debug("   💡 已禁用 qwen-long 回退，大卷仍只允许 qwen3.5-plus / DeepSeek")
        else:
            # 常规卷（≤80章）：使用 DeepSeek-R1（64K输出，质量更高）
            selected_architect = self.plot_architect_r1
            model_name = "deepseek-r1"
            logger.debug(f"✅ 使用 DeepSeek-R1 模型（{avg_chapters}章，约{estimated_words}字，64K输出能力）")

        # 🛡️ 临时修复：清空历史记忆，避免旧消息导致API错误
        logger.debug("🧹 清空历史记忆，避免旧消息影响...")
        self.plot_architect.memory_manager.clear_history()
        self.creative_director.memory_manager.clear_history()
        
        # 🆕 获取题材专属的章节细纲模板和补充说明
        chapter_template = self.genre_module.get('chapter_detail_template', '')
        outline_tips = self.genre_module.get('outline_detail_tips', '')  # 🆕 新增：题材补充说明
        template_example = chapter_template.format(
            chapter_num=1,
            chapter_title="章节标题"
        ) if chapter_template else ""
        
        # ==================== 🆕 三层体系增强 ====================
        
        # 1️⃣ 构建「顶层框架锚点」- 全书核心主线
        core_storyline_section = ""
        if core_storyline:
            core_storyline_section = f"""\n【🎯 全书核心主线（不可偏离）】\n{core_storyline}\n"""
        else:
            # 尝试从史诗框架中提取核心主线
            core_storyline_section = self._extract_core_storyline_from_framework(framework_content)
        
        # 2️⃣ 构建「卷级接口约束」- 上一卷衔接信息
        prev_volume_section = ""
        if prev_volume_summary and target_volume_index > 1:
            new_foreshadowings_text = self._format_foreshadowings_list(
                prev_volume_summary.get('new_foreshadowings', [])
            )
            prev_volume_section = f"""\n【📚 前置锚点（必须严格遵循）】

1. **上一卷结尾内容**：
   - 核心剧情完成：{prev_volume_summary.get('core_plot_completed', '待填充')}
   - 卷尾钩子：{prev_volume_summary.get('ending_hook', '待填充')}
   - 下卷开局目标：{prev_volume_summary.get('next_volume_target', '待填充')}

2. **人物状态更新**：
   {prev_volume_summary.get('character_status_update', '待填充')}

3. **已埋下的伏笔**（需在本卷或后续卷回收）：
   {new_foreshadowings_text}

⚠️ **本卷第{start_chapter_num}章必须从上述「下卷开局目标」开始**，确保卷间无缝衔接！\n"""
        
        # 3️⃣ 构建「待处理伏笔约束」
        foreshadowing_section = ""
        if pending_foreshadowings:
            plant_items = [f for f in pending_foreshadowings if f.get('action') == 'plant']
            pave_items = [f for f in pending_foreshadowings if f.get('action') == 'pave']
            reveal_items = [f for f in pending_foreshadowings if f.get('action') == 'reveal']
            
            foreshadowing_section = "\n【🎭 本卷伏笔任务】\n"
            if plant_items:
                foreshadowing_section += "\n**本卷需埋设的伏笔**：\n"
                for item in plant_items:
                    foreshadowing_section += f"- {item.get('content', '未知')}（揭秘于第{item.get('reveal_volume', '?')}卷）\n"
            if pave_items:
                foreshadowing_section += "\n**本卷需铺垫的伏笔**（已埋设，需强化暗示）：\n"
                for item in pave_items:
                    foreshadowing_section += f"- {item.get('content', '未知')}（埋设于第{item.get('planted_volume', '?')}卷）\n"
            if reveal_items:
                foreshadowing_section += "\n**本卷需揭秘的伏笔**（完成回收）：\n"
                for item in reveal_items:
                    foreshadowing_section += f"- {item.get('content', '未知')}（埋设于第{item.get('planted_volume', '?')}卷）\n"
        
        # 4️⃣ 构建「卷尾过渡段约束」- 明确最后3章任务
        end_chapter_num = start_chapter_num + chapters_count_range[1] - 1
        volume_transition_section = f"""\n【📍 卷尾过渡段设计（极重要）】

本卷最后3章（约第{end_chapter_num-2}~{end_chapter_num}章）必须完成以下任务：

1. **倒数第3章**（第{end_chapter_num-2}章左右）：完成本卷核心任务/Boss战/关键突破
2. **倒数第2章**（第{end_chapter_num-1}章左右）：抛出下一卷的核心悬念/新线索
3. **最后一章**（第{end_chapter_num}章左右）：明确下一卷的开局场景/目标，设置强力钩子\n"""
        
        # 5⃣️ 构建伏笔检查提示
        foreshadowing_checklist = self._generate_foreshadowing_checklist_hint(
            pending_foreshadowings, target_volume_index
        ) if pending_foreshadowings else "✅ 第X章：埋设主角身份伏笔（符合史诗框架）\n✅ 第Y章：提及相关线索（为后续卷铺垫）"
        
        # 6️⃣ 🌟 构建「全局约束模块」- 显式强调头部和尾部信息
        global_constraints_section = ""
        if framework_header or framework_footer:
            global_constraints_section = "\n【🌟 全局约束（必须严格遵循）】\n"
            
            if framework_header:
                # 提取头部关键信息（限制长度避免提示词过长）
                header_excerpt = framework_header[:2000] if len(framework_header) > 2000 else framework_header
                global_constraints_section += f"""\n**1⃣ 整体叙事节奏与境界体系**（本卷必须符合）：
{header_excerpt}
"""
            
            if framework_footer:
                # 提取尾部关键信息（限制长度避免提示词过长）
                footer_excerpt = framework_footer[:2000] if len(framework_footer) > 2000 else framework_footer
                global_constraints_section += f"""\n**2️⃣ 伏笔布局与人物周期**（本卷需配合）：
{footer_excerpt}

⚠️ 本卷的情节设计必须：
- 符合上述叙事节奏和境界进阶设定
- 配合全局伏笔布局（埋设/铺垫/揭秘）
- 保持人物生命周期的连续性
"""
        
        detail_prompt = f"""基于已有的史诗框架，详细扩展第{target_volume_index}卷。
{global_constraints_section}
{core_storyline_section}
{prev_volume_section}
{foreshadowing_section}
【史诗框架】
{framework_content}

【世界观设定】
{world_setting}

【人物设定】
{characters[:2000] if characters else '待完善'}

【扩展要求】
本卷章节编号从第{start_chapter_num}章开始，必须生成{chapters_count_range[0]}-{chapters_count_range[1]}章的详细大纲。

⚠️ 【章节数量要求】：
- 最少章节数：{chapters_count_range[0]}章（不得少于此数量）
- 最多章节数：{chapters_count_range[1]}章（不得超过此数量）
- 建议章节数：{(chapters_count_range[0] + chapters_count_range[1]) // 2}章左右
- 如果剧情需要，可以在上述范围内自由调整，但必须完整输出每一章

{volume_transition_section}

🔥 【章节细纲模板】每章必须严格按以下格式：
## 二、第{target_volume_index}卷详细规划（第{start_chapter_num}-第{start_chapter_num + chapters_count_range[0] - 1}章至第{start_chapter_num + chapters_count_range[1] - 1}章）
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE}
'''

{outline_tips if outline_tips else ''}

Please输出完整的、重新整合后的网文大纲：

## 一、故事概述
[整合后的完整故事概述，300-500字]

## 二、第{target_volume_index}卷详细规划（预计{chapters_count_range[0]}-{chapters_count_range[1]}章，从第{start_chapter_num}章开始）

⚠️ 【极重要】必须逐章完整输出，不得省略任何章节！
- 本卷必须包含{chapters_count_range[0]}-{chapters_count_range[1]}章，不得少于{chapters_count_range[0]}章
- 禁止使用"中间章节略"、"......略"、"精选第X章"等占位符
- 每一章都必须按照上述模板格式完整展开，包含所有必填字段
- 从第{start_chapter_num}章开始，一直写到本卷最后一章（至少第{start_chapter_num + chapters_count_range[0] - 1}章），中间不能断开
- 如果剧情需要更多章节，可以扩展到第{start_chapter_num + chapters_count_range[1] - 1}章

### 第{start_chapter_num}章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

### 第{start_chapter_num + 1}章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

### 第{start_chapter_num + 2}章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}

### 第{start_chapter_num + 3}章：《章节标题》
{CANONICAL_OUTLINE_CHAPTER_TEMPLATE_SHORT}
（以下第{start_chapter_num + 4}章、第{start_chapter_num + 5}章直到本卷最后一章，全部完整输出，禁止使用"...略"、"继续输出"、"其余省略"等占位符）

⚠️ 【极重要】必须逐章完整输出，每章包含所有字段，不可跳过任何章节！

## 三、伏笔埋设检查
{foreshadowing_checklist}

## 四、卷尾衔接检查
✅ 本卷核心任务完成情况：（简述）
✅ 下卷开局场景：（明确描述）
✅ 卷尾钩子：（强力悬念）"""

        logger.debug(f"【第一步】详细扩展第{target_volume_index}卷（使用{model_name}模型）...")

        # 🛡️ 内容安全重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 第一次尝试：正常prompt
                # 后续尝试：添加内容安全约束
                if attempt > 0:
                    logger.debug(f"⚠️ 检测到内容安全问题，第{attempt + 1}次重试（共{max_retries}次）...")
                    # 在prompt末尾添加内容安全约束
                    safety_constraint = """

⚠️ 内容安全要求：
1. 避免包含暴力、血腥、恐怖等过度描写
2. 人物关系和情节发展应符合主流价值观
3. 使用委婉、克制的表达方式
4. 重点突出正面价值观和人物成长"""
                    detail_prompt_safe = detail_prompt + safety_constraint
                    volume_content = selected_architect.process(detail_prompt_safe, {})  # ✅ 使用选中的模型
                else:
                    volume_content = selected_architect.process(detail_prompt, {})  # ✅ 使用选中的模型
                
                logger.debug("✅ 单卷详细扩展完成\n")
                break  # 成功则跳出重试循环
                
            except Exception as e:
                error_str = str(e)
                # 检查是否是内容安全问题
                if 'data_inspection_failed' in error_str or 'inappropriate content' in error_str:
                    if attempt < max_retries - 1:
                        logger.debug(f"⚠️ 内容安全审查失败: {error_str[:100]}...")
                        continue  # 继续重试
                    else:
                        # 最后一次重试也失败，返回占位内容
                        logger.debug(f"❌ 第{target_volume_index}卷内容安全审查多次失败，使用占位内容")
                        volume_content = f"""## 第{target_volume_index}卷：内容生成失败

⚠️ 由于内容安全审查限制，本卷详细大纲暂时无法生成。
建议：
1. 调整世界观设定或人物关系，避免敏感内容
2. 手动编写本卷大纲
3. 稍后重试单卷扩展

章节范围：从第{start_chapter_num}章开始（预计{chapters_count_range[0]}-{chapters_count_range[1]}章）"""
                        break
                else:
                    # 非内容安全问题，直接抛出
                    raise
        
        logger.debug(f"{'='*70}")
        logger.debug(f"【单卷详细扩展】完成！")
        logger.debug(f"{'='*70}\n")
        
        # ✅ 三层体系整合：章节编号自动修正
        logger.debug(f"\n🔧 【章节编号修正器】检测第{target_volume_index}卷章节编号...")
        renumberer = get_chapter_renumberer()
        renumber_result = renumberer.detect_and_fix(
            content=volume_content,
            expected_start=start_chapter_num,
            expected_count_range=chapters_count_range
        )
        
        # 使用修正后的内容
        volume_content = renumber_result["fixed_content"]
        if renumber_result["was_fixed"]:
            logger.debug(f"✅ {renumber_result['details']}")
        else:
            logger.debug(f"✅ {renumber_result['details']}")
        
        # 估算实际章节数(取范围中值)
        estimated_chapters = (chapters_count_range[0] + chapters_count_range[1]) // 2
        
        # 如果有修正结果，使用实际章节数
        if renumber_result["fixed_range"][1] > 0:
            actual_start = renumber_result["fixed_range"][0]
            actual_end = renumber_result["fixed_range"][1]
            estimated_chapters = actual_end - actual_start + 1
        
        # ✅ 三层体系整合：一致性校验（严格模式）
        logger.debug(f"\n🔍 【一致性校验器】开始校验第{target_volume_index}卷...")
        validator = get_consistency_validator(strict_mode=True)
        validation_result = validator.validate(
            volume_content=volume_content,
            volume_index=target_volume_index,
            core_storyline=core_storyline or "",
            prev_volume_summary=prev_volume_summary,
            pending_foreshadowings=pending_foreshadowings,
            framework_content=framework_content
        )
        
        # 输出校验结果
        logger.debug(validation_result.get_summary())
        
        # 校验结果加入返回值
        validation_dict = validation_result.to_dict()
        
        return {
            "expanded_outline": volume_content,
            "volume_index": target_volume_index,
            "chapter_count": estimated_chapters,
            "current_chapter_count": estimated_chapters,
            # ✅ 新增：实际章节范围（修正后）
            "chapters_start": renumber_result["fixed_range"][0] if renumber_result["fixed_range"][0] > 0 else start_chapter_num,
            "chapters_end": renumber_result["fixed_range"][1] if renumber_result["fixed_range"][1] > 0 else start_chapter_num + estimated_chapters - 1,
            "renumber_result": renumber_result,
            # ✅ 新增：校验结果
            "validation": validation_dict,
            "validation_passed": validation_result.passed,
            "validation_issues": validation_dict.get('issues', []),
            "validation_suggestions": validation_dict.get('suggestions', [])
        }
    
    # ==================== 三层体系辅助方法 ====================
    
    def _extract_core_storyline_from_framework(self, framework_content: str) -> str:
        """从史诗框架中提取核心主线
        
        Args:
            framework_content: 史诗框架内容
            
        Returns:
            核心主线部分的提示词
        """
        import re
        
        if not framework_content:
            return ""
        
        # 尝试匹配整体叙事节奏部分
        patterns = [
            r'##\s*[一1][、.]?\s*故事总纲(?:与终局)?[\s\S]*?(?=##\s*[二2]|$)',
            r'##\s*一[、.]?\s*整体叙事节奏[\s\S]*?(?=##\s*[二2]|$)',
            r'【核心主线】[\s\S]*?(?=【|##|$)',
            r'核心主线[:：][\s\S]*?(?=\n\n|##|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, framework_content)
            if match:
                storyline = match.group(0).strip()
                # 限制长度
                if len(storyline) > 500:
                    storyline = storyline[:500] + "..."
                return f"\n【🎯 全书核心主线（从史诗框架提取）】\n{storyline}\n"
        
        # 如果找不到特定部分，提取框架开头部分作为概览
        overview = framework_content[:800] if len(framework_content) > 800 else framework_content
        return f"\n【🎯 全书框架概览】\n{overview}\n"
    
    def _format_foreshadowings_list(self, foreshadowings: List[Any]) -> str:
        """格式化伏笔列表为文本
        
        Args:
            foreshadowings: 伏笔列表，支持字典列表或字符串列表
            
        Returns:
            格式化后的文本
        """
        if not foreshadowings:
            return "无"
        
        result = []
        for item in foreshadowings:
            # 🌟 支持两种格式：字典和字符串
            if isinstance(item, dict):
                # 字典格式：{"content": "...", "planted_volume": X, "reveal_volume": Y}
                content = item.get('content', '未知伏笔')
                planted_vol = item.get('planted_volume', '?')
                reveal_vol = item.get('reveal_volume', '?')
                result.append(f"- {content}（埋设于第{planted_vol}卷，揭秘于第{reveal_vol}卷）")
            elif isinstance(item, str):
                # 字符串格式：直接是伏笔内容
                result.append(f"- {item}")
            else:
                result.append(f"- {str(item)}")
        
        return "\n   ".join(result) if result else "无"
    
    def _generate_foreshadowing_checklist_hint(self, 
                                               pending_foreshadowings: Optional[List[Dict[str, Any]]], 
                                               target_volume_index: int) -> str:
        """生成伏笔检查清单提示
        
        Args:
            pending_foreshadowings: 待处理伏笔列表
            target_volume_index: 当前卷索引
            
        Returns:
            伏笔检查清单文本
        """
        if not pending_foreshadowings:
            return "✅ 第X章：埋设主角身份伏笔（符合史诗框架）\n✅ 第Y章：提及相关线索（为后续卷铺垫）"
        
        checklist_lines = []
        for item in pending_foreshadowings:
            action = item.get('action', 'plant')
            content = item.get('content', '未知伏笔')
            
            if action == 'plant':
                reveal_vol = item.get('reveal_volume', '?')
                checklist_lines.append(f"✅ 第??章：埋设『{content[:20]}...』伏笔（将于第{reveal_vol}卷揭秘）")
            elif action == 'pave':
                planted_vol = item.get('planted_volume', '?')
                checklist_lines.append(f"✅ 第??章：铺垫『{content[:20]}...』（第{planted_vol}卷埋设，本卷强化暗示）")
            elif action == 'reveal':
                planted_vol = item.get('planted_volume', '?')
                checklist_lines.append(f"✅ 第??章：揭秘『{content[:20]}...』（第{planted_vol}卷埋设，本卷完成回收）")
        
        return "\n".join(checklist_lines) if checklist_lines else "✅ 无特定伏笔任务"

    @staticmethod
    def estimate_volume_detail_model(chapters_count_range: Tuple[int, int]) -> str:
        """根据单卷章节规模估算更合适的细化模型。"""
        lower = 0
        upper = 0
        if isinstance(chapters_count_range, (list, tuple)) and len(chapters_count_range) >= 2:
            try:
                lower = max(0, int(chapters_count_range[0] or 0))
            except Exception:
                lower = 0
            try:
                upper = max(lower, int(chapters_count_range[1] or 0))
            except Exception:
                upper = lower
        return "qwen3.5-plus" if upper > VOLUME_DETAIL_MODEL_SWITCH_THRESHOLD else "deepseek-reasoner"

    @staticmethod
    def _story_trim_volume_detail_preamble(volume_content: str) -> str:
        content = str(volume_content or "").strip()
        if not content:
            return ""

        for pattern in (
            r"(?m)^##\s*(?:(?:一|1)[、.．]?\s*)?(?:故事概述|本卷概述)\s*$",
            r"(?m)^##\s*(?:二|2)[、.．].*$",
        ):
            match = re.search(pattern, content)
            if match:
                return content[match.start():].lstrip()

        return content

    @staticmethod
    def _story_extract_json(text: str) -> Optional[Any]:
        if not text:
            return None
        content = str(text).strip()
        try:
            return json.loads(content)
        except Exception:
            pass

        for opener, closer in (("{", "}"), ("[", "]")):
            start = content.find(opener)
            end = content.rfind(closer)
            if start < 0 or end < start:
                continue
            candidate = content[start : end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    @staticmethod
    def _story_stringify(value: Any, limit: int = 300) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, str):
            text = value.strip()
        else:
            text = json.dumps(value, ensure_ascii=False)
        return text if len(text) <= limit else text[:limit] + "..."

    @staticmethod
    def _story_parse_outline_sections(outline: str) -> Dict[int, str]:
        sections: Dict[int, str] = {}
        if not outline or not outline.strip():
            return sections

        pattern = re.compile(r"(?m)^第\s*(\d+)\s*章[：:]\s*(.*)$")
        matches = list(pattern.finditer(outline))
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(outline)
            sections[int(match.group(1))] = outline[start:end].strip()
        return sections

    def _story_invoke_llm_json(
        self,
        llm: Any,
        system_prompt: str,
        user_prompt: str,
        fallback: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            response = llm.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
        except Exception:
            response = llm.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
        parsed = self._story_extract_json(getattr(response, "content", response))
        return parsed if isinstance(parsed, dict) else fallback

    def _story_invoke_agent_json(self, agent: Any, prompt: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        parsed = self._story_extract_json(agent.process(prompt, {}))
        return parsed if isinstance(parsed, dict) else fallback

    @staticmethod
    def _format_names(value: Any) -> str:
        if isinstance(value, list):
            return "、".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    @staticmethod
    def _story_extract_character_names(text: str) -> List[str]:
        names: List[str] = []
        seen = set()
        for match in re.finditer(r"(?m)^(?:###\s*)?【姓名】[：:]\s*(.+?)\s*$", text or ""):
            name = match.group(1).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    @staticmethod
    def _story_normalize_name(name: str) -> str:
        return re.sub(r"\s+", "", str(name or "").strip())

    @staticmethod
    def _story_truncate_text(text: Any, limit: int = 2000) -> str:
        content = str(text or "").strip()
        if not content:
            return ""
        return content if len(content) <= limit else content[:limit].rstrip() + "\n...(已截断)"

    @staticmethod
    def _story_extract_volume_block(framework_content: str, target_volume_index: int) -> str:
        if not framework_content or target_volume_index <= 0:
            return ""

        pattern = re.compile(
            rf"(?ms)^【第\s*{target_volume_index}\s*卷】.*?(?=^【第\s*\d+\s*卷】|^##\s*(?:[六七八九十0-9]+[、.]|关键伏笔|核心人物)|\Z)"
        )
        match = pattern.search(framework_content)
        return match.group(0).strip() if match else ""

    @staticmethod
    def _story_has_parseable_volume_sections(framework_content: str) -> bool:
        if not framework_content or not framework_content.strip():
            return False
        if "待补充分卷规划" in framework_content:
            return False
        return bool(re.search(r"(?m)^【第\s*\d+\s*卷】", framework_content))

    @staticmethod
    def _story_list_parseable_volume_indexes(framework_content: str) -> List[int]:
        indexes: List[int] = []
        seen: set[int] = set()
        for match in re.finditer(r"(?m)^【第\s*(\d+)\s*卷】", framework_content or ""):
            try:
                volume_index = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if volume_index in seen:
                continue
            seen.add(volume_index)
            indexes.append(volume_index)
        return indexes

    @classmethod
    def _story_has_expected_volume_sections(cls, framework_content: str, total_volumes: int) -> bool:
        expected_total = max(1, int(total_volumes or 0))
        if expected_total <= 0:
            return cls._story_has_parseable_volume_sections(framework_content)
        found_indexes = cls._story_list_parseable_volume_indexes(framework_content)
        expected_indexes = list(range(1, expected_total + 1))
        return found_indexes == expected_indexes

    @staticmethod
    def _story_count_rendered_volume_detail_chapters(volume_content: str) -> int:
        if not volume_content or not volume_content.strip():
            return 0
        return len(OutlineExpander._story_extract_rendered_volume_detail_chapter_numbers(volume_content))

    @staticmethod
    def _story_extract_volume_detail_main_section(volume_content: str) -> str:
        content = str(volume_content or "").strip()
        if not content:
            return ""

        code_fence_match = re.match(
            r"^\s*```(?:markdown|md|text)?\s*([\s\S]*?)\s*```\s*$",
            content,
            re.IGNORECASE,
        )
        if code_fence_match:
            content = code_fence_match.group(1).strip()

        detail_section_match = re.search(r"(?m)^##\s*(?:二|2)[、.．].*$", content)
        if detail_section_match:
            content = content[detail_section_match.start():]

        return re.split(r"(?m)^##\s*(?:三|3)[、.．].*$", content, maxsplit=1)[0].rstrip()

    @classmethod
    def _story_extract_rendered_volume_detail_chapter_numbers(cls, volume_content: str) -> List[int]:
        content = cls._story_extract_volume_detail_main_section(volume_content) or str(volume_content or "").strip()
        if not content:
            return []

        seen: set[int] = set()
        chapter_numbers: List[int] = []
        for match in VOLUME_DETAIL_CHAPTER_HEADING_PATTERN.finditer(content):
            try:
                chapter_number = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if chapter_number in seen:
                continue
            seen.add(chapter_number)
            chapter_numbers.append(chapter_number)
        return chapter_numbers

    @classmethod
    def _story_extract_rendered_volume_detail_chapter_range(
        cls,
        volume_content: str,
    ) -> Tuple[int, int]:
        chapter_numbers = cls._story_extract_rendered_volume_detail_chapter_numbers(volume_content)
        if not chapter_numbers:
            return (0, 0)
        return (chapter_numbers[0], chapter_numbers[-1])

    @staticmethod
    def _story_expected_volume_detail_chapter_end(
        *,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
    ) -> int:
        try:
            expected_start = max(1, int(start_chapter_num or 1))
        except Exception:
            expected_start = 1
        try:
            expected_lower_count = max(1, int(chapters_count_range[0] or 1))
        except Exception:
            expected_lower_count = 1
        try:
            expected_upper_count = max(expected_lower_count, int(chapters_count_range[1] or expected_lower_count))
        except Exception:
            expected_upper_count = expected_lower_count
        return expected_start + max(0, expected_upper_count - 1)

    @classmethod
    def _story_find_volume_detail_range_shortcuts(
        cls,
        volume_content: str,
        *,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
    ) -> List[Tuple[int, int]]:
        content = cls._story_extract_volume_detail_main_section(volume_content)
        if not content:
            return []

        try:
            expected_start = max(1, int(start_chapter_num or 1))
        except Exception:
            expected_start = 1
        expected_end = cls._story_expected_volume_detail_chapter_end(
            start_chapter_num=expected_start,
            chapters_count_range=chapters_count_range,
        )
        rendered_chapter_numbers = cls._story_extract_rendered_volume_detail_chapter_numbers(content)
        rendered_chapters = set(rendered_chapter_numbers)
        actual_chapter_count = len(rendered_chapter_numbers)
        try:
            required_min_count = max(1, int(chapters_count_range[0] or 1))
        except Exception:
            required_min_count = 1
        last_rendered_chapter = rendered_chapter_numbers[-1] if rendered_chapter_numbers else expected_start - 1
        shortcuts: List[Tuple[int, int]] = []

        for pattern in (VOLUME_DETAIL_RANGE_SHORTCUT_PATTERN, VOLUME_DETAIL_GROUP_RANGE_PATTERN):
            for match in pattern.finditer(content):
                try:
                    range_start = int(match.group("start"))
                    range_end = int(match.group("end"))
                except (TypeError, ValueError):
                    continue
                if range_end < range_start:
                    range_start, range_end = range_end, range_start

                overlap_start = max(range_start, expected_start)
                overlap_end = min(range_end, expected_end)
                if overlap_start > overlap_end:
                    continue

                missing_numbers = [
                    chapter_number
                    for chapter_number in range(overlap_start, overlap_end + 1)
                    if chapter_number not in rendered_chapters
                ]
                if not missing_numbers:
                    continue
                if (
                    actual_chapter_count >= required_min_count
                    and all(chapter_number > last_rendered_chapter for chapter_number in missing_numbers)
                ):
                    continue

                shortcut = (range_start, range_end)
                if shortcut not in shortcuts:
                    shortcuts.append(shortcut)

        return shortcuts

    @classmethod
    def _story_extract_volume_detail_chapter_block_map(
        cls,
        volume_content: str,
        *,
        min_chapter_number: int = 1,
        max_chapter_number: Optional[int] = None,
    ) -> Dict[int, str]:
        content = cls._story_extract_volume_detail_main_section(volume_content) or str(volume_content or "").strip()
        if not content:
            return {}

        matches = list(VOLUME_DETAIL_CHAPTER_HEADING_PATTERN.finditer(content))
        blocks: Dict[int, str] = {}
        min_number = max(1, int(min_chapter_number or 1))
        max_number = int(max_chapter_number) if max_chapter_number is not None else None
        for index, match in enumerate(matches):
            try:
                chapter_number = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if chapter_number < min_number:
                continue
            if max_number is not None and chapter_number > max_number:
                continue
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            block = content[start:end].strip()
            if block:
                blocks[chapter_number] = block
        return blocks

    @classmethod
    def _story_extract_missing_volume_detail_chapter_ranges(
        cls,
        volume_content: str,
        *,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
    ) -> List[Tuple[int, int]]:
        try:
            expected_start = max(1, int(start_chapter_num or 1))
        except Exception:
            expected_start = 1
        expected_end = cls._story_expected_volume_detail_chapter_end(
            start_chapter_num=expected_start,
            chapters_count_range=chapters_count_range,
        )
        rendered_chapters = set(cls._story_extract_rendered_volume_detail_chapter_numbers(volume_content))
        missing_numbers = [
            chapter_number
            for chapter_number in range(expected_start, expected_end + 1)
            if chapter_number not in rendered_chapters
        ]
        if not missing_numbers:
            return []

        ranges: List[Tuple[int, int]] = []
        range_start = missing_numbers[0]
        range_end = missing_numbers[0]
        for chapter_number in missing_numbers[1:]:
            if chapter_number == range_end + 1:
                range_end = chapter_number
                continue
            ranges.append((range_start, range_end))
            range_start = chapter_number
            range_end = chapter_number
        ranges.append((range_start, range_end))
        return ranges

    @staticmethod
    def _story_chunk_volume_detail_chapter_ranges(
        missing_ranges: List[Tuple[int, int]],
        *,
        chunk_size: int = 15,
    ) -> List[Tuple[int, int]]:
        normalized_chunk_size = max(1, int(chunk_size or 1))
        chunked_ranges: List[Tuple[int, int]] = []
        for range_start, range_end in missing_ranges:
            current_start = int(range_start)
            current_end = int(range_end)
            while current_start <= current_end:
                chunk_end = min(current_end, current_start + normalized_chunk_size - 1)
                chunked_ranges.append((current_start, chunk_end))
                current_start = chunk_end + 1
        return chunked_ranges

    @classmethod
    def _story_split_volume_detail_content(
        cls,
        volume_content: str,
    ) -> Tuple[str, str]:
        content = str(volume_content or "").strip()
        if not content:
            return "", ""

        code_fence_match = re.match(
            r"^\s*```(?:markdown|md|text)?\s*([\s\S]*?)\s*```\s*$",
            content,
            re.IGNORECASE,
        )
        if code_fence_match:
            content = code_fence_match.group(1).strip()

        tail_match = re.search(r"(?m)^##\s*(?:三|3)[、.．].*$", content)
        if tail_match:
            main_content = content[: tail_match.start()].rstrip()
            tail_content = content[tail_match.start() :].lstrip()
        else:
            main_content = content.rstrip()
            tail_content = ""

        matches = list(VOLUME_DETAIL_CHAPTER_HEADING_PATTERN.finditer(main_content))
        if matches:
            head_content = main_content[: matches[0].start()].rstrip()
        else:
            head_content = main_content.rstrip()

        return head_content, tail_content

    @classmethod
    def _story_strip_volume_detail_range_shortcut_lines(cls, volume_content: str) -> str:
        content = str(volume_content or "").strip()
        if not content:
            return ""

        cleaned_lines: List[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line)
                continue
            if stripped.startswith("##") or VOLUME_DETAIL_CHAPTER_HEADING_PATTERN.search(stripped):
                cleaned_lines.append(line)
                continue
            if VOLUME_DETAIL_RANGE_SHORTCUT_PATTERN.search(stripped) or VOLUME_DETAIL_GROUP_RANGE_PATTERN.search(stripped):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    @staticmethod
    def _story_extract_volume_detail_chapter_blocks(
        volume_content: str,
        *,
        min_chapter_number: int = 1,
    ) -> str:
        block_map = OutlineExpander._story_extract_volume_detail_chapter_block_map(
            volume_content,
            min_chapter_number=min_chapter_number,
        )
        return "\n\n".join(block_map[number] for number in sorted(block_map))

    @classmethod
    def _story_merge_volume_detail_supplement(
        cls,
        base_content: str,
        supplement_content: str,
        *,
        next_chapter_number: int,
        max_chapter_number: Optional[int] = None,
    ) -> str:
        base_text = str(base_content or "").strip()
        if not base_text:
            return base_text

        supplement_text = str(supplement_content or "").strip()
        if not supplement_text:
            return base_text

        supplement_block_map = cls._story_extract_volume_detail_chapter_block_map(
            supplement_text,
            min_chapter_number=next_chapter_number,
            max_chapter_number=max_chapter_number,
        )
        if not supplement_block_map:
            try:
                expected_max_count = (
                    max(1, int(max_chapter_number or next_chapter_number) - int(next_chapter_number) + 1)
                    if max_chapter_number is not None
                    else 20
                )
            except Exception:
                expected_max_count = 20
            renumber_result = get_chapter_renumberer().detect_and_fix(
                content=supplement_text,
                expected_start=next_chapter_number,
                expected_count_range=(1, expected_max_count),
            )
            supplement_block_map = cls._story_extract_volume_detail_chapter_block_map(
                renumber_result.get("fixed_content") or supplement_text,
                min_chapter_number=next_chapter_number,
                max_chapter_number=max_chapter_number,
            )
        if not supplement_block_map:
            return base_text

        base_block_map = cls._story_extract_volume_detail_chapter_block_map(base_text)
        merged_block_map = dict(base_block_map)
        merged_block_map.update(supplement_block_map)

        head_content, tail_content = cls._story_split_volume_detail_content(base_text)
        head_content = cls._story_strip_volume_detail_range_shortcut_lines(head_content)
        chapter_blocks = "\n\n".join(
            merged_block_map[number]
            for number in sorted(merged_block_map)
        ).strip()

        parts: List[str] = []
        if head_content:
            parts.append(head_content.strip())
        if chapter_blocks:
            parts.append(chapter_blocks)
        if tail_content:
            parts.append(tail_content.strip())
        return "\n\n".join(part for part in parts if part).strip()

    @staticmethod
    def _story_is_valid_volume_detail_chapter_count(
        chapter_count: int,
        chapters_count_range: Tuple[int, int],
    ) -> bool:
        try:
            lower = max(1, int(chapters_count_range[0] or 1))
        except Exception:
            lower = 1
        try:
            upper = max(lower, int(chapters_count_range[1] or lower))
        except Exception:
            upper = lower
        return lower <= int(chapter_count or 0) <= upper

    @staticmethod
    def _story_format_prev_volume_summary(prev_volume_summary: Optional[Dict[str, Any]]) -> str:
        if not isinstance(prev_volume_summary, dict) or not prev_volume_summary:
            return "（暂无上一卷摘要，可直接从当前卷切入，但仍需遵守全书框架。）"

        parts: List[str] = []
        for key, label in (
            ("core_plot_completed", "上一卷已完成"),
            ("ending_hook", "上一卷卷尾钩子"),
            ("next_volume_target", "本卷开局目标"),
            ("character_status_update", "人物状态变化"),
        ):
            text = str(prev_volume_summary.get(key) or "").strip()
            if text:
                parts.append(f"- {label}：{text}")

        foreshadowings_text = ""
        foreshadowings = prev_volume_summary.get("new_foreshadowings")
        if isinstance(foreshadowings, list):
            lines: List[str] = []
            for item in foreshadowings:
                if isinstance(item, dict):
                    content = str(item.get("content") or "未知伏笔").strip()
                    planted_volume = str(item.get("planted_volume") or "").strip()
                    reveal_volume = str(item.get("reveal_volume") or "").strip()
                    extras = "；".join(
                        part
                        for part in (
                            planted_volume and f"埋设于第{planted_volume}卷",
                            reveal_volume and f"预计第{reveal_volume}卷回收",
                        )
                        if part
                    )
                    lines.append(f"{content}" + (f"（{extras}）" if extras else ""))
                else:
                    text = str(item or "").strip()
                    if text:
                        lines.append(text)
            foreshadowings_text = "；".join(lines)
        elif foreshadowings:
            foreshadowings_text = str(foreshadowings).strip()
        if foreshadowings_text:
            parts.append(f"- 上一卷遗留伏笔：{foreshadowings_text}")

        return "\n".join(parts) if parts else "（暂无可用的上一卷衔接信息。）"

    @staticmethod
    def _story_format_pending_foreshadowings(pending_foreshadowings: Optional[List[Dict[str, Any]]]) -> str:
        if not pending_foreshadowings:
            return "（当前没有强制回收项，但至少保留1条可延续线索，并避免与总纲冲突。）"

        lines: List[str] = []
        for item in pending_foreshadowings:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "处理").strip()
            content = str(item.get("content") or "").strip()
            planted_volume = str(item.get("planted_volume") or "").strip()
            reveal_volume = str(item.get("reveal_volume") or "").strip()
            extras = "；".join(
                part
                for part in (
                    planted_volume and f"埋设卷：第{planted_volume}卷",
                    reveal_volume and f"目标回收卷：第{reveal_volume}卷",
                )
                if part
            )
            if content:
                lines.append(f"- {action}：{content}" + (f"（{extras}）" if extras else ""))

        return "\n".join(lines) if lines else "（当前没有可识别的伏笔任务。）"

    @classmethod
    def _story_extract_chapters_payload(cls, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []

        direct_chapters = payload.get("chapters")
        if isinstance(direct_chapters, list):
            return [chapter for chapter in direct_chapters if isinstance(chapter, dict)]

        chapter_plans = payload.get("chapter_plans")
        if isinstance(chapter_plans, list):
            return [chapter for chapter in chapter_plans if isinstance(chapter, dict)]

        novel_plan = payload.get("novel_plan")
        if isinstance(novel_plan, dict):
            nested_chapters = novel_plan.get("chapters")
            if isinstance(nested_chapters, list):
                return [chapter for chapter in nested_chapters if isinstance(chapter, dict)]

        volume_plan = payload.get("volume_plan")
        if isinstance(volume_plan, dict):
            volume_chapters = volume_plan.get("chapters")
            if isinstance(volume_chapters, list):
                return [chapter for chapter in volume_chapters if isinstance(chapter, dict)]

        return []

    @classmethod
    def _story_contains_premature_finale_signal(
        cls,
        payload: Dict[str, Any],
        *,
        current_round_target: int,
        overall_target_chapters: Optional[int],
    ) -> bool:
        if not isinstance(payload, dict):
            return False
        if not overall_target_chapters or overall_target_chapters <= current_round_target:
            return False

        serialized = json.dumps(payload, ensure_ascii=False)
        finale_keywords = (
            "大结局",
            "最终章",
            "终章",
            "终局",
            "完结",
            "收官",
            "尾声",
            "最终决战",
            "终战",
            "全书完结",
        )
        return any(keyword in serialized for keyword in finale_keywords)

    def _story_rewrite_payload_without_premature_finale(
        self,
        *,
        payload: Dict[str, Any],
        current_outline: str,
        characters: str,
        world_setting: str,
        new_chapter_start: int,
        target_chapters: int,
        story_target_chapters: int,
        chapter_schema: str,
    ) -> Dict[str, Any]:
        remaining_chapters = max(0, int(story_target_chapters or 0) - int(target_chapters or 0))
        rewrite_prompt = f"""你是小说章节修正师，请修正下面这份“常规协同”的章节 JSON。

【修正目标】
1. 当前只是在推进第 {new_chapter_start}-{target_chapters} 章，距离全书目标仍至少还有 {remaining_chapters} 章。
2. 禁止出现“终章 / 大结局 / 完结 / 终局 / 尾声 / 最终决战”等提前收官信号。
3. 本轮只能写成“阶段性高潮 / 转折 / 危机升级 / 新阶段开口”，不能写成全书完结。
4. 保留章节编号范围不变，只修正阶段定位、标题、关键事件、情节作用和结尾钩子中的提前完结表达。
5. 继续保持纯章节式 JSON，禁止卷级结构。

【当前大纲】
{current_outline}

【人物体系】
{characters}

【世界观】
{world_setting}

【待修正 JSON】
{json.dumps(payload, ensure_ascii=False, indent=2)}

【输出 JSON Schema】
{chapter_schema}

只返回合法 JSON，不要解释。"""
        return self._story_invoke_llm_json(
            self.llm,
            "你是小说章节修正师，请移除提前完结信号并保留阶段推进。",
            rewrite_prompt,
            fallback=payload,
        )

    @staticmethod
    def _story_normalize_incremental_continue_reason(
        reason: str,
        *,
        current_total: int,
        target_chapters: int,
        story_target_chapters: int,
    ) -> str:
        normalized_reason = str(reason or "").strip()
        if story_target_chapters > target_chapters and current_total >= target_chapters:
            return (
                f"当前可确认章节数（{current_total}）已达本轮目标章节数（{target_chapters}），"
                f"本轮阶段性细纲已完成，后续仍需继续朝全书目标 {story_target_chapters} 章推进。"
            )
        return normalized_reason

    @staticmethod
    def _story_count_rendered_outline_chapters(outline_text: str) -> int:
        if not outline_text or not str(outline_text).strip():
            return 0

        matches = re.findall(r"(?m)^(?:#{1,6}\s*)?第\s*(\d+)\s*章(?:[：:《\s]|$)", str(outline_text))
        chapter_numbers: List[int] = []
        for value in matches:
            try:
                chapter_numbers.append(int(value))
            except Exception:
                continue
        return max(chapter_numbers, default=0)

    @classmethod
    def _story_extract_incremental_overview(cls, payload: Dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""

        for key in (
            "story_overview",
            "stage_summary",
            "current_arc_summary",
            "future_outline_reservation",
            "structure_overview",
            "arc_summary",
        ):
            text = str(payload.get(key) or "").strip()
            if text:
                return text

        planning_metadata = payload.get("planning_metadata") if isinstance(payload.get("planning_metadata"), dict) else {}
        if planning_metadata:
            for key in ("current_arc_name", "arc_goal", "summary"):
                text = str(planning_metadata.get(key) or "").strip()
                if text:
                    return text

        novel_plan = payload.get("novel_plan") if isinstance(payload.get("novel_plan"), dict) else {}
        if novel_plan:
            for key in ("story_overview", "core_theme", "summary", "title"):
                text = str(novel_plan.get(key) or "").strip()
                if text:
                    return text

        volume_plan = payload.get("volume_plan") if isinstance(payload.get("volume_plan"), dict) else {}
        if volume_plan:
            for key in ("plot_arc_summary", "core_theme", "volume_title"):
                text = str(volume_plan.get(key) or "").strip()
                if text:
                    return text

        return ""

    @classmethod
    def _story_render_incremental_outline(cls, payload: Dict[str, Any], chapter_breakdown: str) -> str:
        overview = cls._story_extract_incremental_overview(payload)
        parts: List[str] = []

        if overview:
            parts.append("## 本轮阶段摘要")
            parts.append(overview)

        if chapter_breakdown and chapter_breakdown.strip():
            parts.append("## 新增章节规划")
            parts.append(chapter_breakdown.strip())

        return "\n".join(parts).strip()

    @classmethod
    def _story_render_outline_overview(cls, payload: Dict[str, Any]) -> str:
        story_overview = str(
            payload.get("story_overview")
            or payload.get("structure_overview")
            or payload.get("future_outline_reservation")
            or payload.get("novel_title")
            or ""
        ).strip()
        volumes = payload.get("volumes") if isinstance(payload.get("volumes"), list) else []
        novel_plan = payload.get("novel_plan") if isinstance(payload.get("novel_plan"), dict) else {}
        volume_plan = payload.get("volume_plan") if isinstance(payload.get("volume_plan"), dict) else {}
        planning_metadata = payload.get("planning_metadata") if isinstance(payload.get("planning_metadata"), dict) else {}
        if planning_metadata and not story_overview:
            story_overview = str(
                planning_metadata.get("current_arc_name")
                or planning_metadata.get("arc_goal")
                or planning_metadata.get("summary")
                or ""
            ).strip()
        if volume_plan and not story_overview:
            story_overview = str(
                volume_plan.get("plot_arc_summary")
                or volume_plan.get("core_theme")
                or volume_plan.get("volume_title")
                or ""
            ).strip()
        if novel_plan:
            if not story_overview:
                story_overview = str(
                    novel_plan.get("story_overview")
                    or novel_plan.get("core_theme")
                    or novel_plan.get("summary")
                    or novel_plan.get("title")
                    or ""
                ).strip()
            if not volumes:
                nested_volumes = novel_plan.get("volumes")
                if isinstance(nested_volumes, list):
                    volumes = nested_volumes
        if volume_plan and not volumes:
            volumes = [volume_plan]

        chapters = cls._story_extract_chapters_payload(payload)
        if not story_overview and not volumes and not chapters:
            return ""

        parts: List[str] = ["## 故事概述"]
        if story_overview:
            parts.append(story_overview)

        for volume in volumes:
            if not isinstance(volume, dict):
                continue
            volume_index = volume.get("volume_index") or "?"
            title = str(volume.get("title") or f"第{volume_index}卷").strip()
            parts.append(f"### 【第{volume_index}卷】「{title}」")
            for key, label in (
                ("stage_goal", "卷目标"),
                ("core_conflict", "核心冲突"),
                ("ending_climax", "卷末爆点"),
                ("new_chapter_direction", "新增章节方向"),
            ):
                text = str(volume.get(key) or "").strip()
                if text:
                    parts.append(f"- {label}：{text}")
            key_characters = cls._format_names(volume.get("key_characters"))
            if key_characters:
                parts.append(f"- 关键人物：{key_characters}")

        if chapters:
            chapter_breakdown, _ = cls._story_render_chapter_breakdown("", {"chapters": chapters})
            if chapter_breakdown:
                parts.append("## 章节规划")
                parts.append(chapter_breakdown)
        return "\n".join(parts).strip()

    @classmethod
    def _story_render_chapter_breakdown(cls, current_outline: str, payload: Dict[str, Any]) -> Tuple[str, int]:
        sections = cls._story_parse_outline_sections(current_outline)
        chapters = cls._story_extract_chapters_payload(payload)
        blocks: List[str] = []
        max_chapter = 0

        for chapter in chapters:
            try:
                chapter_number = int(chapter.get("chapter_number") or 0)
            except Exception:
                chapter_number = 0
            if chapter_number <= 0:
                continue
            max_chapter = max(max_chapter, chapter_number)
            title = str(chapter.get("title") or f"第{chapter_number}章").strip()
            status = str(chapter.get("status") or "").strip().lower()
            suffix = " [已写]" if status == "written" else ""
            lines = [f"#### 第{chapter_number}章：《{title}》{suffix}"]

            existing_body = sections.get(chapter_number, "").strip()
            if status == "written" and existing_body:
                lines.append(existing_body)
                blocks.append("\n".join(lines))
                continue

            for key, label in (
                ("scene_goal", "场景目标"),
                ("conflict_design", "冲突设计"),
                ("key_events", "关键事件"),
                ("character_progress", "人物推进"),
                ("plot_function", "情节作用"),
                ("ending_hook", "结尾钩子"),
            ):
                text = str(chapter.get(key) or "").strip()
                if text:
                    lines.append(f"- **{label}**：{text}")
            involved_characters = cls._format_names(
                chapter.get("involved_characters") or chapter.get("characters_involved")
            )
            if involved_characters:
                lines.append(f"- **涉及人物**：{involved_characters}")
            highlight_type = str(chapter.get("highlight_type") or "").strip()
            if highlight_type:
                lines.append(f"- **爽点类型**：{highlight_type}")
            foreshadowing_item = str(chapter.get("foreshadowing_item") or "").strip()
            if foreshadowing_item:
                lines.append(f"- **伏笔事项**：{foreshadowing_item}")
            if len(lines) == 1 and existing_body:
                lines.append(existing_body)
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks).strip(), max_chapter

    @classmethod
    def _story_render_character_cards(cls, items: Any) -> Tuple[str, List[str]]:
        if not isinstance(items, list):
            return "", []

        blocks: List[str] = []
        names: List[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            names.append(name)
            personality_anchor = str(item.get("personality_anchor") or "").strip()
            if not personality_anchor:
                personality_anchor = _build_personality_anchor_text(
                    item.get("personality"),
                    item.get("worldview_stance"),
                )
            ability_and_limits = _build_ability_and_limit_text(
                item.get("ability_outline") or item.get("abilities"),
                item.get("limitation"),
            )
            mainline_binding = _build_mainline_binding_text(
                item.get("mainline_role"),
                item.get("mainline_clues"),
            )
            lines = [f"### 【姓名】：{name}"]
            for text, label in (
                (str(item.get("age_gender") or "").strip(), "年龄/性别"),
                (str(item.get("story_stance") or "").strip(), "故事立场"),
                (str(item.get("role_position") or "").strip(), "角色定位"),
                (str(item.get("affiliation") or "").strip(), "所属势力"),
                (str(item.get("appearance_anchor") or item.get("appearance") or "").strip(), "外貌锚点"),
                (personality_anchor, "性格锚点"),
                (str(item.get("background_status") or item.get("background") or "").strip(), "背景/当前处境"),
                (str(item.get("motivation") or "").strip(), "核心动机"),
                (ability_and_limits, "能力与限制"),
                (str(item.get("key_relationships") or "").strip(), "关键关系"),
                (mainline_binding, "主线绑定"),
                (str(item.get("growth_direction") or "").strip(), "成长方向"),
            ):
                if text:
                    lines.append(f"【{label}】：{text}")
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks).strip(), names

    @classmethod
    def _story_parse_character_cards_response(
        cls,
        response_text: Any,
        *,
        existing_names: Optional[List[str]] = None,
    ) -> Tuple[str, List[str], str]:
        content = str(response_text or "").strip()
        if not content:
            return "", [], "empty"

        payload = cls._story_extract_json(content)
        if isinstance(payload, dict):
            rendered_cards, names = cls._story_render_character_cards(payload.get("characters"))
            if rendered_cards.strip():
                return rendered_cards, names, "json"

        parser = CharacterTextParser()
        parsed_characters = parser.parse_all_characters(content)
        if not parsed_characters:
            return "", [], "empty"

        existing_name_keys = {
            normalize_character_name(name) or cls._story_normalize_name(name)
            for name in (existing_names or [])
            if str(name or "").strip()
        }
        rendered_blocks: List[str] = []
        names: List[str] = []
        seen_keys: set[str] = set()

        for character in parsed_characters:
            normalized_name = normalize_character_name(character.name) or cls._story_normalize_name(character.name)
            if not normalized_name or normalized_name in existing_name_keys or normalized_name in seen_keys:
                continue
            seen_keys.add(normalized_name)
            names.append(character.name)
            rendered_blocks.append(cls._story_render_parsed_character_card(character))

        if rendered_blocks:
            return "\n\n".join(rendered_blocks).strip(), names, "raw_cards"
        return "", [], "empty"

    @classmethod
    def _story_render_existing_character_patch(cls, payload: Dict[str, Any]) -> str:
        updates = payload.get("updates") if isinstance(payload.get("updates"), list) else []
        if not updates:
            return ""

        parts = ["## 已有角色关系更新"]
        for item in updates:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                parts.append(f"### {name}")
            relation_updates = item.get("relationship_updates") if isinstance(item.get("relationship_updates"), list) else []
            relation_texts = []
            for relation in relation_updates:
                if not isinstance(relation, dict):
                    continue
                target = str(relation.get("target") or "").strip()
                description = str(relation.get("description") or "").strip()
                if target and description:
                    relation_texts.append(f"{target}：{description}")
            if relation_texts:
                parts.append(f"【关键关系·补充】：{'；'.join(relation_texts)}")
            for key, label in (
                ("mainline_clues_patch", "关联线索·补充"),
                ("mainline_role_patch", "剧情职责·补充"),
                ("growth_direction_patch", "成长方向·补充"),
            ):
                text = str(item.get(key) or "").strip()
                if text:
                    parts.append(f"【{label}】：{text}")
        return "\n".join(parts).strip()

    @staticmethod
    def _story_extract_existing_character_patch_field(block: str, label: str) -> str:
        pattern = re.compile(
            rf"(?ms)^\s*【{re.escape(label)}】[：:]\s*(.+?)(?=^\s*【|^\s*###\s+|\Z)"
        )
        match = pattern.search(block or "")
        return str(match.group(1) or "").strip() if match else ""

    @staticmethod
    def _story_split_inline_segments(text: Any) -> List[str]:
        content = str(text or "").strip()
        if not content:
            return []
        return [
            segment.strip()
            for segment in re.split(r"[；;\n]+", content)
            if segment and segment.strip()
        ]

    @classmethod
    def _story_merge_inline_segments(cls, *values: Any, separator: str = "；") -> str:
        merged: List[str] = []
        seen: set[str] = set()
        for value in values:
            for segment in cls._story_split_inline_segments(value):
                key = re.sub(r"\s+", "", segment)
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(segment)
        return separator.join(merged).strip()

    @classmethod
    def _story_upsert_existing_character_patch(
        cls,
        patch_map: Dict[str, Dict[str, str]],
        *,
        name: str,
        relationships: str = "",
        mainline_clues: str = "",
        mainline_role: str = "",
        growth_direction: str = "",
    ) -> None:
        display_name = str(name or "").strip()
        normalized_name = normalize_character_name(display_name) or cls._story_normalize_name(display_name)
        if not display_name or not normalized_name:
            return

        entry = patch_map.setdefault(normalized_name, {"name": display_name})
        if not entry.get("name"):
            entry["name"] = display_name

        for key, value in (
            ("relationships", relationships),
            ("mainline_clues", mainline_clues),
            ("mainline_role", mainline_role),
            ("growth_direction", growth_direction),
        ):
            merged_value = cls._story_merge_inline_segments(entry.get(key, ""), value)
            if merged_value:
                entry[key] = merged_value

    @classmethod
    def _story_collect_existing_character_patch_map_from_payload(
        cls,
        payload: Dict[str, Any],
    ) -> Dict[str, Dict[str, str]]:
        patch_map: Dict[str, Dict[str, str]] = {}
        updates = payload.get("updates") if isinstance(payload.get("updates"), list) else []
        for item in updates:
            if not isinstance(item, dict):
                continue
            relationship_updates = (
                item.get("relationship_updates")
                if isinstance(item.get("relationship_updates"), list)
                else []
            )
            relation_texts: List[str] = []
            for relation in relationship_updates:
                if not isinstance(relation, dict):
                    continue
                target = str(relation.get("target") or "").strip()
                description = str(relation.get("description") or "").strip()
                if target and description:
                    relation_texts.append(f"{target}：{description}")

            cls._story_upsert_existing_character_patch(
                patch_map,
                name=str(item.get("name") or "").strip(),
                relationships="；".join(relation_texts),
                mainline_clues=str(item.get("mainline_clues_patch") or "").strip(),
                mainline_role=str(item.get("mainline_role_patch") or "").strip(),
                growth_direction=str(item.get("growth_direction_patch") or "").strip(),
            )
        return patch_map

    @classmethod
    def _story_collect_existing_character_patch_map_from_text(
        cls,
        text: str,
    ) -> Tuple[str, Dict[str, Dict[str, str]]]:
        content = str(text or "")
        if not content.strip():
            return "", {}

        patch_map: Dict[str, Dict[str, str]] = {}
        pattern = re.compile(r"(?ms)^##\s*已有角色关系更新\s*\n?(.*?)(?=^##\s|\Z)")
        cleaned_parts: List[str] = []
        cursor = 0

        for match in pattern.finditer(content):
            leading = content[cursor:match.start()].strip()
            if leading:
                cleaned_parts.append(leading)

            section_body = str(match.group(1) or "").strip()
            for block in re.split(r"(?m)(?=^###\s+)", section_body):
                block_text = str(block or "").strip()
                if not block_text:
                    continue
                name_match = re.search(r"(?m)^###\s*(.+?)\s*$", block_text)
                if not name_match:
                    continue
                cls._story_upsert_existing_character_patch(
                    patch_map,
                    name=name_match.group(1).strip(),
                    relationships=cls._story_extract_existing_character_patch_field(block_text, "关键关系·补充"),
                    mainline_clues=cls._story_extract_existing_character_patch_field(block_text, "关联线索·补充"),
                    mainline_role=cls._story_extract_existing_character_patch_field(block_text, "剧情职责·补充"),
                    growth_direction=cls._story_extract_existing_character_patch_field(block_text, "成长方向·补充"),
                )

            cursor = match.end()

        trailing = content[cursor:].strip()
        if trailing:
            cleaned_parts.append(trailing)

        cleaned_text = "\n\n".join(part for part in cleaned_parts if part).strip()
        return cleaned_text, patch_map

    @classmethod
    def _story_render_parsed_character_card(cls, character: ParsedCharacter) -> str:
        age_gender_parts: List[str] = []
        if character.age is not None:
            age_gender_parts.append(f"{character.age}岁")
        if character.gender:
            age_gender_parts.append(character.gender)
        personality_anchor = _build_personality_anchor_text(character.personality, character.worldview)
        ability_and_limits = _build_ability_and_limit_text(character.abilities, character.limitation)
        mainline_binding = _build_mainline_binding_text(character.mainline_role, character.mainline_clues)
        lines = [f"### 【姓名】：{character.name}"]
        for text, label in (
            ("/".join(age_gender_parts), "年龄/性别"),
            (character.role or "", "故事立场"),
            (character.role_position or "", "角色定位"),
            (character.faction or "", "所属势力"),
            (character.appearance or "", "外貌锚点"),
            (personality_anchor, "性格锚点"),
            (character.background or "", "背景/当前处境"),
            (character.motivation or "", "核心动机"),
            (ability_and_limits, "能力与限制"),
            (character.relationships or "", "关键关系"),
            (mainline_binding, "主线绑定"),
            (character.growth_direction or "", "成长方向"),
        ):
            if str(text or "").strip():
                lines.append(f"【{label}】：{str(text).strip()}")
        return "\n".join(lines)

    @classmethod
    def _story_apply_existing_character_patch(
        cls,
        character: ParsedCharacter,
        patch: Dict[str, str],
    ) -> ParsedCharacter:
        character.relationships = cls._story_merge_inline_segments(
            character.relationships,
            patch.get("relationships"),
        )
        character.mainline_clues = cls._story_merge_inline_segments(
            character.mainline_clues,
            patch.get("mainline_clues"),
        )
        character.mainline_role = cls._story_merge_inline_segments(
            character.mainline_role,
            patch.get("mainline_role"),
        )
        character.growth_direction = cls._story_merge_inline_segments(
            character.growth_direction,
            patch.get("growth_direction"),
        )
        return character

    @classmethod
    def _story_merge_character_cards_with_patches(
        cls,
        main_characters: str,
        new_cards: str,
        patch_payload: Dict[str, Any],
    ) -> str:
        cleaned_main_characters, historical_patch_map = cls._story_collect_existing_character_patch_map_from_text(
            main_characters
        )
        current_patch_map = cls._story_collect_existing_character_patch_map_from_payload(patch_payload)
        patch_map = dict(historical_patch_map)
        for patch in current_patch_map.values():
            cls._story_upsert_existing_character_patch(
                patch_map,
                name=patch.get("name", ""),
                relationships=patch.get("relationships", ""),
                mainline_clues=patch.get("mainline_clues", ""),
                mainline_role=patch.get("mainline_role", ""),
                growth_direction=patch.get("growth_direction", ""),
            )

        parser = CharacterTextParser()
        existing_parsed = parser.parse_all_characters(cleaned_main_characters)
        new_parsed = parser.parse_all_characters(new_cards)
        merged_characters: Dict[str, ParsedCharacter] = {}
        ordered_keys: List[str] = []

        for character in [*existing_parsed, *new_parsed]:
            normalized_name = normalize_character_name(character.name) or cls._story_normalize_name(character.name)
            if not normalized_name:
                continue
            if normalized_name in merged_characters:
                merged_characters[normalized_name] = _merge_parsed_character(
                    merged_characters[normalized_name],
                    character,
                )
                continue
            merged_characters[normalized_name] = character
            ordered_keys.append(normalized_name)

        for normalized_name, patch in patch_map.items():
            character = merged_characters.get(normalized_name)
            if not character:
                continue
            merged_characters[normalized_name] = cls._story_apply_existing_character_patch(character, patch)

        rendered_cards = "\n\n".join(
            cls._story_render_parsed_character_card(merged_characters[key])
            for key in ordered_keys
            if key in merged_characters
        ).strip()

        fallback_parts: List[str] = []
        if cleaned_main_characters.strip() and not existing_parsed:
            fallback_parts.append(cleaned_main_characters.strip())
        if rendered_cards:
            fallback_parts.append(rendered_cards)
        if new_cards.strip() and not new_parsed:
            fallback_parts.append(new_cards.strip())
        return "\n\n".join(part for part in fallback_parts if part).strip()

    @classmethod
    def _story_render_relationships(cls, payload: Dict[str, Any]) -> str:
        groups = payload.get("relationship_groups") if isinstance(payload.get("relationship_groups"), list) else []
        if not groups:
            return ""

        parts: List[str] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_name = str(group.get("group") or "关系网络").strip()
            parts.append(f"**{group_name}**：")
            relationships = group.get("relationships") if isinstance(group.get("relationships"), list) else []
            for relation in relationships:
                if not isinstance(relation, dict):
                    continue
                source = str(relation.get("source") or "").strip()
                target = str(relation.get("target") or "").strip()
                relation_type = str(relation.get("type") or "").strip()
                description = str(relation.get("description") or "").strip()
                if source and target and relation_type and description:
                    parts.append(f"- {source} ↔ {target}：{relation_type}（{description}）")
        return "\n".join(parts).strip()

    @classmethod
    def _story_render_epic_framework(cls, payload: Dict[str, Any], total_volumes: int) -> str:
        if not isinstance(payload, dict) or not payload:
            return ""

        story_positioning = payload.get("story_positioning") if isinstance(payload.get("story_positioning"), dict) else {}
        stage_roadmap = (
            payload.get("stage_roadmap")
            if isinstance(payload.get("stage_roadmap"), list)
            else payload.get("story_phases")
        )
        rolling_strategy = payload.get("rolling_strategy") if isinstance(payload.get("rolling_strategy"), dict) else {}
        volumes = payload.get("volumes") if isinstance(payload.get("volumes"), list) else []
        power_progression = payload.get("power_progression") if isinstance(payload.get("power_progression"), list) else []
        foreshadowings = payload.get("foreshadowings") if isinstance(payload.get("foreshadowings"), list) else []
        lifecycle = payload.get("character_lifecycle") if isinstance(payload.get("character_lifecycle"), list) else []

        parts: List[str] = ["## 一、故事总纲与终局"]
        story_positioning_lines = [
            ("genre_type", "题材类型"),
            ("global_theme", "全局主题"),
            ("story_premise", "故事总纲"),
            ("core_hook", "核心卖点"),
            ("core_contradiction", "核心矛盾"),
            ("endgame_direction", "终局方向"),
        ]
        added_positioning = False
        for key, label in story_positioning_lines:
            text = str(story_positioning.get(key) or payload.get(key) or "").strip()
            if text:
                parts.append(f"- {label}：{text}")
                added_positioning = True
        if not added_positioning:
            parts.append("- 以长篇总纲统一约束世界观、主线终局与人物成长。")

        parts.append("")
        parts.append("## 二、阶段路线图")
        added_stage = False
        for phase in stage_roadmap if isinstance(stage_roadmap, list) else []:
            if not isinstance(phase, dict):
                continue
            added_stage = True
            stage_name = str(phase.get("stage") or phase.get("phase") or "阶段").strip()
            parts.append(f"### {stage_name}")
            for key, label in (
                ("volume_span", "覆盖卷段"),
                ("chapter_span", "覆盖章节"),
                ("phase_goal", "阶段目标"),
                ("main_conflict", "阶段主冲突"),
                ("growth_focus", "成长重点"),
                ("focus", "阶段重点"),
                ("ending_signal", "阶段收束标记"),
            ):
                text = str(phase.get(key) or "").strip()
                if text:
                    suffix = "章" if key == "chapter_span" and not text.endswith("章") else ""
                    parts.append(f"- {label}：{text}{suffix}")
        if not added_stage:
            parts.append("- 暂未给出明确的阶段路线图。")

        parts.append("")
        parts.append("## 三、力量与冲突升级路线")
        added_progression = False
        for item in power_progression:
            if not isinstance(item, dict):
                continue
            added_progression = True
            title = str(item.get("volume_span") or item.get("stage") or "阶段").strip()
            realm_stage = str(item.get("realm_stage") or "").strip()
            chapter_span = str(item.get("chapter_span") or "").strip()
            line = f"- {title}"
            if realm_stage:
                line += f"：{realm_stage}"
            if chapter_span:
                line += f"（{chapter_span if chapter_span.endswith('章') else chapter_span + '章'}）"
            parts.append(line)
            for key, label in (
                ("conflict_upgrade", "冲突升级"),
                ("notes", "说明"),
            ):
                text = str(item.get(key) or "").strip()
                if text:
                    parts.append(f"  - {label}：{text}")
        if not added_progression:
            parts.append("- 本书以阶段冲突升级代替单点爆发，保证长线成长不断档。")

        parts.append("")
        parts.append("## 四、滚动细化策略")
        added_strategy = False
        for key, label in (
            ("planning_principle", "规划原则"),
            ("detail_window", "细化窗口"),
            ("continuity_focus", "连续性重点"),
        ):
            text = str(rolling_strategy.get(key) or "").strip()
            if text:
                parts.append(f"- {label}：{text}")
                added_strategy = True

        anti_drift_rules = rolling_strategy.get("anti_drift_rules") if isinstance(rolling_strategy.get("anti_drift_rules"), list) else []
        if anti_drift_rules:
            added_strategy = True
            parts.append("- 防漂移规则：")
            for rule in anti_drift_rules:
                text = str(rule or "").strip()
                if text:
                    parts.append(f"  - {text}")

        character_collaboration = (
            rolling_strategy.get("character_collaboration")
            if isinstance(rolling_strategy.get("character_collaboration"), list)
            else []
        )
        if character_collaboration:
            added_strategy = True
            parts.append("- 人物协同方式：")
            for item in character_collaboration:
                text = str(item or "").strip()
                if text:
                    parts.append(f"  - {text}")

        if not added_strategy:
            parts.append("- 先锁定总纲与阶段目标，再按卷滚动细化，后续只展开当前卷与下卷接口。")
            parts.append("- 每次细化都要回看上一卷收束、活跃人物状态和伏笔任务，降低长篇漂移。")

        parts.append("")
        parts.append(f"## 五、分卷规划（共{total_volumes}卷）")
        if not volumes:
            parts.append("- 待补充分卷规划。")
        for volume in volumes:
            if not isinstance(volume, dict):
                continue
            volume_index = volume.get("volume_index") or "?"
            title = str(volume.get("title") or f"第{volume_index}卷").strip()
            parts.append(f"【第{volume_index}卷】{title}")
            for key, label in (
                ("chapter_span", "章节规模"),
                ("stage_positioning", "卷定位"),
                ("core_goal", "核心目标"),
                ("main_conflict", "主冲突"),
                ("character_focus", "人物焦点"),
                ("foreshadowing_task", "伏笔任务"),
                ("realm_stage", "力量/阶段进展"),
                ("major_enemy", "主要对手"),
                ("ending_climax", "卷末爆点"),
                ("next_volume_hook", "下卷交接"),
            ):
                text = str(volume.get(key) or "").strip()
                if text:
                    suffix = "章" if key == "chapter_span" and not text.endswith("章") else ""
                    parts.append(f"- {label}：{text}{suffix}")

        parts.append("")
        parts.append("## 六、关键伏笔布局")
        added_foreshadowings = False
        for item in foreshadowings:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            plant_at = str(item.get("plant_at") or "").strip()
            pave_at = cls._format_names(item.get("pave_at"))
            reveal_at = str(item.get("reveal_at") or "").strip()
            purpose = str(item.get("purpose") or "").strip()
            if content:
                detail = "；".join(
                    part
                    for part in (
                        plant_at and f"埋设：{plant_at}",
                        pave_at and f"铺垫：{pave_at}",
                        reveal_at and f"揭示：{reveal_at}",
                        purpose and f"作用：{purpose}",
                    )
                    if part
                )
                parts.append(f"- {content}（{detail}）" if detail else f"- {content}")
                added_foreshadowings = True
        if not added_foreshadowings:
            parts.append("- 暂无明确伏笔。")

        parts.append("")
        parts.append("## 七、核心人物生命周期")
        added_lifecycle = False
        for item in lifecycle:
            if not isinstance(item, dict):
                continue
            character = str(item.get("character") or "").strip()
            detail = "；".join(
                part
                for part in (
                    item.get("debut") and f"初登场：{item['debut']}",
                    item.get("active_span") and f"活跃跨度：{item['active_span']}",
                    item.get("transition") and f"阶段变化：{item['transition']}",
                    item.get("volume_role") and f"卷级职责：{item['volume_role']}",
                )
                if part
            )
            if character and detail:
                parts.append(f"- {character}：{detail}")
                added_lifecycle = True
        if not added_lifecycle:
            parts.append("- 核心人物随卷推进持续补齐。")
        return "\n".join(parts).strip()

    @classmethod
    def _story_render_volume_detail(
        cls,
        payload: Dict[str, Any],
        target_volume_index: int,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
        pending_foreshadowings: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, int]:
        if not isinstance(payload, dict) or not payload:
            return "", 0

        volume_positioning = payload.get("volume_positioning") if isinstance(payload.get("volume_positioning"), dict) else {}
        chapter_groups = payload.get("chapter_groups") if isinstance(payload.get("chapter_groups"), list) else []

        parts: List[str] = ["## 一、故事概述"]
        parts.append(str(payload.get("story_overview") or "").strip() or "本卷承接上一卷线索，继续推进主线。")
        positioning_lines: List[str] = []
        for key, label in (
            ("volume_title", "本卷标题"),
            ("phase_role", "本卷定位"),
            ("stage_goal", "阶段目标"),
            ("inheritance_from_prev", "承接上一卷"),
            ("main_conflict", "本卷主冲突"),
            ("character_coordination", "角色协同"),
            ("ending_handoff", "卷末交接"),
        ):
            text = str(volume_positioning.get(key) or "").strip()
            if text:
                positioning_lines.append(f"- {label}：{text}")
        if positioning_lines:
            parts.append("")
            parts.extend(positioning_lines)

        parts.append("")
        parts.append(f"## 二、第{target_volume_index}卷详细规划（预计{chapters_count_range[0]}-{chapters_count_range[1]}章，从第{start_chapter_num}章开始）")
        if chapter_groups:
            parts.append("- 本卷剧情段落：")
            for group in chapter_groups:
                if not isinstance(group, dict):
                    continue
                arc = str(group.get("arc") or "剧情段").strip()
                details = "；".join(
                    part
                    for part in (
                        group.get("chapter_span") and f"章节：{group['chapter_span']}",
                        group.get("stage_task") and f"任务：{group['stage_task']}",
                        group.get("conflict_upgrade") and f"冲突升级：{group['conflict_upgrade']}",
                        group.get("character_focus") and f"人物焦点：{group['character_focus']}",
                        group.get("foreshadowing_task") and f"伏笔任务：{group['foreshadowing_task']}",
                    )
                    if part
                )
                parts.append(f"  - {arc}" + (f"（{details}）" if details else ""))

        count = 0
        chapters = payload.get("chapters") if isinstance(payload.get("chapters"), list) else []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            count += 1
            try:
                chapter_number = int(chapter.get("chapter_number") or (start_chapter_num + count - 1))
            except Exception:
                chapter_number = start_chapter_num + count - 1
            title = str(chapter.get("title") or f"第{chapter_number}章").strip()
            parts.append("")
            parts.append(f"### 第{chapter_number}章：《{title}》")
            for key, label in (
                ("scene_goal", "场景目标"),
                ("conflict_design", "冲突设计"),
                ("key_events", "关键事件"),
                ("character_progress", "人物推进"),
                ("plot_function", "情节作用"),
                ("ending_hook", "结尾钩子"),
            ):
                text = str(chapter.get(key) or "").strip()
                if text:
                    parts.append(f"- **{label}**：{text}")
            involved_characters = cls._format_names(chapter.get("involved_characters"))
            if involved_characters:
                parts.append(f"- **涉及人物**：{involved_characters}")
            highlight_type = str(chapter.get("highlight_type") or "").strip()
            if highlight_type:
                parts.append(f"- **爽点类型**：{highlight_type}")
            foreshadowing_item = str(chapter.get("foreshadowing_item") or "").strip()
            if foreshadowing_item:
                parts.append(f"- **伏笔事项**：{foreshadowing_item}")

        parts.append("")
        parts.append("## 三、伏笔埋设检查")
        checks = payload.get("foreshadowing_checks") if isinstance(payload.get("foreshadowing_checks"), list) else []
        if checks:
            for item in checks:
                if not isinstance(item, dict):
                    continue
                chapter = str(item.get("chapter") or "待定章节").strip()
                action = str(item.get("action") or "处理").strip()
                content = str(item.get("content") or "").strip()
                if content:
                    parts.append(f"- {chapter}：{action} {content}")
        elif pending_foreshadowings:
            for item in pending_foreshadowings:
                if not isinstance(item, dict):
                    continue
                action = str(item.get("action") or "处理").strip()
                content = str(item.get("content") or "").strip()
                if content:
                    parts.append(f"- 待定章节：{action} {content}")
        else:
            parts.append("- 当前卷暂无强制伏笔任务。")

        parts.append("")
        parts.append("## 四、卷尾衔接检查")
        connection = payload.get("volume_connection_check") if isinstance(payload.get("volume_connection_check"), dict) else {}
        for key, label in (
            ("core_task_completion", "本卷任务完成"),
            ("next_volume_opening", "下卷开局场景"),
            ("ending_hook", "卷尾钩子"),
        ):
            text = str(connection.get(key) or "").strip()
            if text:
                parts.append(f"✅ {label}：{text}")
        if parts[-1] == "## 四、卷尾衔接检查":
            parts.append("✅ 当前卷已形成基本承接结构。")

        return "\n".join(parts).strip(), count

    @classmethod
    def _story_normalize_volume_detail_response(
        cls,
        raw_response: Any,
        *,
        target_volume_index: int,
        start_chapter_num: int,
        chapters_count_range: Tuple[int, int],
        pending_foreshadowings: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        content = cls._story_trim_volume_detail_preamble(str(raw_response or ""))
        if not content:
            return ""

        payload = cls._story_extract_json(content)
        if isinstance(payload, dict) and payload:
            rendered_content, _ = cls._story_render_volume_detail(
                payload,
                target_volume_index=target_volume_index,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
                pending_foreshadowings=pending_foreshadowings,
            )
            return cls._story_trim_volume_detail_preamble(rendered_content or content)

        return content

    def expand_plot_outline(self, current_outline: str, world_setting: str,
                          characters: str, target_chapters: int = 50) -> Dict[str, Any]:
        current_count = self.count_chapters_in_outline(current_outline)
        if target_chapters <= current_count:
            return {
                "expanded_outline": current_outline,
                "chapter_breakdown": "",
                "plot_arcs": {},
                "current_chapter_count": current_count,
                "target_chapters": target_chapters,
                "should_continue": False,
                "continue_reason": "目标章节数未超过当前章节数，无需继续扩展。",
                "expansion_analysis": "目标章节数未超过当前章节数，无需继续扩展。",
            }

        result = self.expand_plot_outline_incremental(
            current_outline=current_outline,
            world_setting=world_setting,
            characters=characters,
            current_chapter_count=current_count,
            increment=target_chapters - current_count,
            target_total_chapters=target_chapters,
        )
        result["target_chapters"] = target_chapters
        result["expansion_analysis"] = result.get("continue_reason") or result.get("expansion_analysis", "")
        return result

    def expand_characters(self, main_characters: str, world_setting: str,
                        plot_outline: str, target_count: int = 15) -> Dict[str, Any]:
        current_count = self.count_characters_in_text(main_characters)
        if target_count <= current_count:
            return {
                "all_characters": main_characters,
                "character_relationships": "",
                "role_distribution": {},
                "current_character_count": current_count,
                "target_count": target_count,
                "should_continue": False,
                "continue_reason": "目标人物数未超过当前人物数，无需继续扩展。",
                "character_analysis": "目标人物数未超过当前人物数，无需继续扩展。",
            }

        result = self.expand_characters_incremental(
            main_characters=main_characters,
            world_setting=world_setting,
            plot_outline=plot_outline,
            current_character_count=current_count,
            increment=target_count - current_count,
            target_total_characters=target_count,
        )
        result["target_count"] = target_count
        result["character_analysis"] = result.get("continue_reason") or result.get("character_analysis", "")
        return result

    def generate_expansion_summary(self, outline_expansion: Dict[str, Any],
                                  character_expansion: Dict[str, Any]) -> str:
        return f"""
{'='*70}
【长篇小说扩展总结报告】
{'='*70}

## 一、情节大纲扩展

### 目标章节数
{outline_expansion.get('target_chapters', 'N/A')} 章

### 扩展策略
{self._story_stringify(outline_expansion.get('expansion_analysis'))}

### 情节线索
{self._story_stringify(outline_expansion.get('plot_arcs'))}

### 章节分解（示例前5章）
{self._story_stringify(outline_expansion.get('chapter_breakdown'), limit=500)}

---

## 二、人物体系扩展

### 目标人物数
{character_expansion.get('target_count', 'N/A')} 个

### 角色定位
{self._story_stringify(character_expansion.get('role_distribution'))}

### 人物关系网络
{self._story_stringify(character_expansion.get('character_relationships'))}

{'='*70}
""".strip()

    def expand_plot_outline_incremental(self, current_outline: str, world_setting: str,
                                       characters: str, current_chapter_count: int,
                                       increment: int = 15,
                                       target_total_chapters: Optional[int] = None,
                                       overall_target_chapters: Optional[int] = None) -> Dict[str, Any]:
        target_chapters = target_total_chapters or (current_chapter_count + increment)
        story_target_chapters = max(
            int(target_chapters or 0),
            int(overall_target_chapters or 0),
            int(getattr(self, "planned_chapters_max", 0) or 0),
            int(current_chapter_count or 0) + int(increment or 0),
        )
        new_chapter_start = max(int(current_chapter_count or 0), 0) + 1
        anti_finale_instruction = ""
        if story_target_chapters > target_chapters:
            anti_finale_instruction = (
                f"\n10. 当前距离全书目标仍至少还有 {story_target_chapters - target_chapters} 章，"
                "严禁出现“终章 / 大结局 / 完结 / 终局 / 尾声 / 最终决战”等提前收官字样；"
                "只能写阶段性高潮和下一阶段钩子。"
            )

        chapter_schema = json.dumps(
            {
                "story_overview": "本轮阶段摘要，可留空",
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "章节标题",
                        "scene_goal": "场景目标",
                        "conflict_design": "冲突设计",
                        "key_events": "关键事件",
                        "involved_characters": ["角色A", "角色B"],
                        "character_progress": "人物推进",
                        "plot_function": "情节作用",
                        "ending_hook": "结尾钩子",
                        "highlight_type": "爽点类型",
                        "foreshadowing_item": "伏笔事项",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        characters_excerpt = self._story_build_character_context(
            characters,
            detail_limit=CHARACTER_EXPANSION_CARD_CONTEXT_LIMIT,
        ) or "（暂无人物体系）"
        chapter_user_prompt = f"""请基于当前大纲执行“常规协同”的纯章节式扩展。

【协同模式约束】
1. 当前模式是常规协同，禁止使用卷级结构。
2. 不要输出 `volumes`、`novel_plan.volumes`、`volume_plan`、`stage_roadmap`、`total_volumes`、`chapter_span` 等分卷/卷级字段。
3. 如需概括本轮阶段目标，只能写在 `story_overview` 中，且控制在 120 字以内。

【全书目标】
- 全书目标规模：约 {story_target_chapters} 章

【本轮目标】
- 当前已有章节数：{current_chapter_count}
- 本轮只新增：第 {new_chapter_start} 章到第 {target_chapters} 章
- 本轮补齐后，总章节数达到：{target_chapters}

【当前大纲】
{current_outline}

【人物体系】
{characters_excerpt}

【世界观】
{world_setting}

【输出 JSON Schema】
{chapter_schema}

要求：
1. `chapters` 中的 chapter_number 必须从现有章节后连续延伸，只输出第 {new_chapter_start} 章到第 {target_chapters} 章。
2. 不要改写已存在的章节，不要重写第 1 章到第 {current_chapter_count} 章。
3. 虽然本轮只写到第 {target_chapters} 章，但全书目标约 {story_target_chapters} 章，不要提前收束终局或写成完结篇。
4. 每章必须包含：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项。
5. `关键事件` 请概括 2-4 个本章必须发生的节点，不要写成空泛总结。
6. `人物推进` 要明确主角或关键配角发生了什么变化，关系如何前进。
7. `情节作用` 要说明本章在整段剧情中的职责，例如承接、升级、爆点前置、伏笔回收。
8. 返回结构必须以 `chapters` 为核心，不要把结果包进卷级结构后再嵌套输出。
9. 只返回 JSON，不要解释，不要 Markdown 代码块。{anti_finale_instruction}"""
        chapter_payload = self._story_invoke_llm_json(
            self.llm,
            "你是小说章节规划师，请按常规协同输出纯章节式 JSON。",
            chapter_user_prompt,
            fallback={"story_overview": "", "chapters": []},
        )
        if not self._story_extract_chapters_payload(chapter_payload):
            retry_chapter_payload = self._story_invoke_llm_json(
                self.llm,
                "你是小说章节规划师，请按常规协同输出纯章节式 JSON。",
                chapter_user_prompt
                + f"\n\n补充要求：必须返回 `chapters` 数组，并直接给出第 {new_chapter_start} 章到第 {target_chapters} 章的可执行新增章节规划；不要只写概述，不要改用卷级结构。",
                fallback={"story_overview": "", "chapters": []},
            )
            if self._story_extract_chapters_payload(retry_chapter_payload):
                chapter_payload = retry_chapter_payload

        if self._story_contains_premature_finale_signal(
            chapter_payload,
            current_round_target=target_chapters,
            overall_target_chapters=story_target_chapters,
        ):
            repaired_payload = self._story_rewrite_payload_without_premature_finale(
                payload=chapter_payload,
                current_outline=current_outline,
                characters=characters,
                world_setting=world_setting,
                new_chapter_start=new_chapter_start,
                target_chapters=target_chapters,
                story_target_chapters=story_target_chapters,
                chapter_schema=chapter_schema,
            )
            if self._story_extract_chapters_payload(repaired_payload):
                chapter_payload = repaired_payload

        chapter_breakdown, max_chapter = self._story_render_chapter_breakdown(current_outline, chapter_payload)
        expanded_outline = self._story_render_incremental_outline(chapter_payload, chapter_breakdown) or current_outline
        current_total = max(
            int(current_chapter_count or 0),
            self._story_count_rendered_outline_chapters(current_outline),
            self._story_count_rendered_outline_chapters(chapter_breakdown),
            max_chapter,
        )

        decision_payload = self._story_invoke_llm_json(
            self.llm,
            "请输出是否继续扩展的 JSON。",
            f"""请基于以下真实上下文判断当前章节扩展是否还需要继续。

【当前状态】
- 扩展前章节数：{current_chapter_count}
- 目标章节数：{target_chapters}
- 当前可确认章节数：{current_total}

【当前大纲】
{current_outline}

【本轮阶段摘要】
{expanded_outline}

【章节细纲】
{chapter_breakdown}

请只返回 JSON：
{{
  "should_continue": true,
  "reason": "100字以内说明"
}}

判断原则：
1. 若当前可确认章节数仍小于目标章节数，且细纲没有补齐，优先返回 true。
2. 若本轮没有产生可用的新章节规划，返回 false，并明确说明需要补什么上下文。
3. 不要脱离上述上下文泛泛而谈。
4. 若全书目标仍高于本轮目标，只能说明“本轮阶段性规划已完成，可继续下一轮扩展”，不要使用全书完结、终章、终局、收官、大结局等措辞。""",
            fallback={"should_continue": False, "reason": ""},
        )
        continue_reason = self._story_normalize_incremental_continue_reason(
            str(decision_payload.get("reason") or "").strip(),
            current_total=current_total,
            target_chapters=target_chapters,
            story_target_chapters=story_target_chapters,
        )

        return {
            "expanded_outline": expanded_outline,
            "chapter_breakdown": chapter_breakdown,
            "plot_arcs": chapter_payload,
            "current_chapter_count": current_total,
            "target_chapters": target_chapters,
            "should_continue": bool(decision_payload.get("should_continue", False)),
            "continue_reason": continue_reason,
            "expansion_analysis": continue_reason,
        }

    def expand_characters_incremental(self, main_characters: str, world_setting: str,
                                     plot_outline: str, current_character_count: int,
                                     increment: int = 5,
                                     target_total_characters: Optional[int] = None) -> Dict[str, Any]:
        existing_names = self._story_extract_character_names(main_characters)
        current_character_count = max(int(current_character_count or 0), len(existing_names))
        target_count = target_total_characters or (current_character_count + increment)
        characters_needed = max(0, int(target_count) - int(current_character_count))
        existing_names_text = "、".join(existing_names) if existing_names else "暂无"
        world_excerpt = self._story_truncate_text(world_setting, limit=2800) or "（暂无世界观补充）"
        outline_excerpt = self._story_truncate_text(
            plot_outline,
            limit=CHARACTER_EXPANSION_OUTLINE_CONTEXT_LIMIT,
        ) or "（暂无当前大纲）"
        characters_excerpt = self._story_build_character_context(
            main_characters,
            detail_limit=CHARACTER_EXPANSION_CARD_CONTEXT_LIMIT,
        ) or "（暂无现有人物卡）"

        cards_prompt = f"""你是小说人物协同设计师，请为当前故事阶段补充“新增角色卡”。

【目标】
- 当前人物数：{current_character_count}
- 目标人物数：{target_count}
- 本轮需新增：{characters_needed} 个

【现有角色名单】
{existing_names_text}

【现有人物卡】
{characters_excerpt}

【当前大纲】
{outline_excerpt}

【世界观】
{world_excerpt}

请只返回 JSON，对象结构如下：
{{
  "characters": [
    {{
      "name": "角色名",
      "age_gender": "年龄/性别",
      "story_stance": "主角方/反派方/中立方/亦正亦邪",
      "role_position": "角色定位",
      "affiliation": "所属势力",
      "appearance_anchor": "外貌锚点",
      "personality_anchor": "性格锚点",
      "background_status": "背景/当前处境",
      "motivation": "核心动机",
      "ability_outline": "角色能力/特长",
      "limitation": "能力代价/短板",
      "key_relationships": "关键关系",
      "mainline_role": "主线剧情职责",
      "mainline_clues": "关联线索",
      "growth_direction": "成长方向"
    }}
  ]
}}

要求：
1. 严格新增 {characters_needed} 个角色，禁止复写现有角色卡。
2. 新角色姓名不得与现有角色重复，且必须符合当前题材。
3. 每个新角色都必须承担明确剧情职责，至少与一个现有角色或主线冲突形成关系。
4. `key_relationships` 只保留当前最关键的 3-5 条关系，不要写已解决或纯历史背景关系总账。
5. `mainline_role` / `mainline_clues` 只保留当前阶段仍驱动剧情的内容，不要把多个阶段职责堆在一起。
6. 不要输出 Markdown，不要解释，只返回合法 JSON。"""

        cards_retry_used = False
        cards_response = self.character_designer.process(cards_prompt, {})
        new_cards, new_names, cards_response_mode = self._story_parse_character_cards_response(
            cards_response,
            existing_names=existing_names,
        )
        if characters_needed > 0 and not new_names:
            cards_retry_used = True
            retry_cards_response = self.character_designer.process(
                cards_prompt
                + f"""

补充要求：
1. 上次结果未识别到有效新增角色，本次必须至少补出 {characters_needed} 个新角色。
2. 优先返回合法 JSON；如果仍无法稳定输出 JSON，允许直接输出标准人物卡正文，但每个新角色都必须以 `### 【姓名】：` 开头。
3. 禁止只返回分析、建议、阵营标题或人物名单，必须给出可直接并入人物体系的完整角色卡。""",
                {},
            )
            new_cards, new_names, cards_response_mode = self._story_parse_character_cards_response(
                retry_cards_response,
                existing_names=existing_names,
            )
        elif characters_needed > 0 and len(new_names) < characters_needed:
            cards_retry_used = True
            remaining_count = max(0, characters_needed - len(new_names))
            recognized_names_text = "、".join(new_names) if new_names else "无"
            retry_cards_response = self.character_designer.process(
                cards_prompt
                + f"""

补充要求：
1. 上次仅识别到 {len(new_names)} 个有效新增角色，仍缺 {remaining_count} 个。
2. 本次只补足剩余 {remaining_count} 个新角色，禁止重复输出已经给出的角色：{recognized_names_text}。
3. 优先返回合法 JSON；如果仍无法稳定输出 JSON，允许直接输出标准人物卡正文，但每个新角色都必须以 `### 【姓名】：` 开头。
4. 禁止只返回分析、建议、阵营标题或人物名单，必须补齐可直接并入人物体系的完整角色卡。""",
                {},
            )
            retry_cards, retry_names, retry_mode = self._story_parse_character_cards_response(
                retry_cards_response,
                existing_names=[*existing_names, *new_names],
            )
            if retry_cards.strip():
                new_cards = (
                    f"{new_cards.rstrip()}\n\n{retry_cards.strip()}"
                    if new_cards.strip()
                    else retry_cards.strip()
                )
            if retry_names:
                new_names = list(dict.fromkeys([*new_names, *retry_names]))
            if retry_mode and not cards_response_mode:
                cards_response_mode = retry_mode

        new_cards_excerpt = self._story_build_character_context(
            new_cards,
            detail_limit=CHARACTER_EXPANSION_NEW_CARD_CONTEXT_LIMIT,
        ) or "（本轮未新增结构化角色卡）"
        patch_prompt = f"""你是小说人物统筹编辑，请只补充“已有角色需要新增的关系/职责补丁”。

【现有角色名单】
{existing_names_text}

【现有人物卡】
{characters_excerpt}

【本轮新增角色卡】
{new_cards_excerpt}

【当前大纲】
{outline_excerpt}

请只返回 JSON：
{{
  "updates": [
    {{
      "name": "已有角色名",
      "relationship_updates": [
        {{
          "target": "目标角色名",
          "description": "新增关系变化"
        }}
      ],
      "mainline_clues_patch": "需补充的关联线索",
      "mainline_role_patch": "需补充的剧情职责",
      "growth_direction_patch": "需补充的成长方向"
    }}
  ]
}}

要求：
1. 只对确有必要的已有角色输出补丁，没有必要可返回空数组。
2. 不要重写完整人物卡，不要新增不存在的角色名。
3. 重点补“新增角色引入后，老角色需要怎样承接”。"""

        patch_payload = self._story_invoke_agent_json(
            self.character_designer,
            patch_prompt,
            fallback={"updates": []},
        )
        merged_characters = self._story_merge_character_cards_with_patches(
            main_characters,
            new_cards,
            patch_payload,
        )
        merged_excerpt = self._story_build_character_context(
            merged_characters,
            detail_limit=CHARACTER_EXPANSION_MERGED_CONTEXT_LIMIT,
        ) or "（暂无完整人物体系）"
        relationship_prompt = f"""你是小说人物关系规划师，请基于当前完整人物体系输出关系网络 JSON。

【人物体系】
{merged_excerpt}

【当前大纲】
{outline_excerpt}

请只返回 JSON：
{{
  "relationship_groups": [
    {{
      "group": "主角阵营内部/对手阵营内部/跨阵营关系/支持角色关系",
      "relationships": [
        {{
          "source": "角色A",
          "target": "角色B",
          "type": "盟友/对手/师徒/利用/怀疑/亲人等",
          "description": "20字以内关系说明"
        }}
      ]
    }}
  ]
}}

要求：
1. 重点输出与本轮新增角色有关的关键关系。
2. 不要编造人物体系中不存在的角色。
3. 关系分组可以为空，但 JSON 结构必须合法。"""

        relationship_payload = self._story_invoke_agent_json(
            self.character_designer,
            relationship_prompt,
            fallback={"relationship_groups": []},
        )
        character_relationships = self._story_render_relationships(relationship_payload)

        distribution_prompt = f"""请基于以下人物体系统计角色分布，只返回 JSON。

【人物体系】
{merged_excerpt}

返回格式：
{{
  "主角": 数量,
  "配角": 数量,
  "对手": 数量,
  "支持角色": 数量,
  "中立角色": 数量
}}"""

        role_distribution = self._story_invoke_agent_json(
            self.character_designer,
            distribution_prompt,
            fallback={},
        )

        unique_new_names: List[str] = []
        normalized_existing = {self._story_normalize_name(name) for name in existing_names}
        normalized_unique_new_names: set[str] = set()
        for name in new_names:
            normalized_name = self._story_normalize_name(name)
            if not normalized_name or normalized_name in normalized_existing:
                continue
            if normalized_name in normalized_unique_new_names:
                continue
            unique_new_names.append(name)
            normalized_unique_new_names.add(normalized_name)

        decision_prompt = f"""你是小说人物协同审校员，请判断当前人物扩展是否还需要继续。

【当前状态】
- 扩展前人物数：{current_character_count}
- 目标人物数：{target_count}
- 本轮实际新增：{len(unique_new_names)}
- 当前可确认人物数：{max(current_character_count + len(unique_new_names), len(set(existing_names) | set(unique_new_names)))}
- 新增角色：{'、'.join(unique_new_names) if unique_new_names else '无'}

【当前大纲】
{outline_excerpt}

【完整人物体系】
{merged_excerpt}

请只返回 JSON：
{{
  "should_continue": true,
  "reason": "100字以内说明"
}}

判断原则：
1. 若目标人数已达到，通常返回 false。
2. 若本轮未新增有效角色，返回 false，并说明缺口原因。
3. 若大纲仍存在明显角色槽位缺口且目标人数未达到，可返回 true。
4. “当前可确认人物数”只能按结构化人物卡数量计算，不要把关系网提及、补丁提及、阵营引用重复计入。"""

        current_confirmed_count = max(
            current_character_count + len(unique_new_names),
            len(set(existing_names) | set(unique_new_names)),
        )
        decision_payload = self._story_invoke_agent_json(
            self.character_designer,
            decision_prompt,
            fallback={
                "should_continue": bool(unique_new_names) and current_confirmed_count < target_count,
                "reason": "",
            },
        )

        return {
            "all_characters": merged_characters,
            "character_relationships": character_relationships,
            "role_distribution": role_distribution if isinstance(role_distribution, dict) else {},
            "current_character_count": current_confirmed_count,
            "target_count": target_count,
            "should_continue": bool(decision_payload.get("should_continue", False)),
            "continue_reason": str(decision_payload.get("reason") or "").strip(),
            "should_optimize_first": False,
            "optimization_suggestions": [],
            "cards_response_mode": cards_response_mode,
            "cards_retry_used": cards_retry_used,
            "recognized_new_character_count": len(unique_new_names),
            "recognized_new_character_names": unique_new_names,
        }

    def generate_epic_framework(self, world_setting: str, characters: str,
                               total_volumes: int, total_chapters_range: tuple[int, int]) -> Dict[str, Any]:
        chapter_lower = max(1, int(total_chapters_range[0] or 1))
        chapter_upper = max(chapter_lower, int(total_chapters_range[1] or chapter_lower))
        world_excerpt = self._story_truncate_text(world_setting, limit=4000) or "（暂无世界观补充）"
        characters_excerpt = self._story_build_character_context(
            characters,
            detail_limit=EPIC_FRAMEWORK_CHARACTER_CONTEXT_LIMIT,
        ) or "（暂无核心人物卡）"
        schema = json.dumps(
            {
                "story_positioning": {
                    "genre_type": "题材类型",
                    "global_theme": "全局主题",
                    "story_premise": "故事总纲",
                    "core_hook": "核心卖点",
                    "endgame_direction": "终局方向",
                    "core_contradiction": "核心矛盾",
                },
                "stage_roadmap": [
                    {
                        "stage": "阶段名称",
                        "volume_span": "第1-3卷",
                        "chapter_span": "1-180",
                        "phase_goal": "阶段目标",
                        "main_conflict": "阶段主冲突",
                        "growth_focus": "成长重点",
                        "ending_signal": "阶段收束标记",
                    }
                ],
                "power_progression": [
                    {
                        "volume_span": "第1-2卷",
                        "chapter_span": "1-120",
                        "realm_stage": "力量或地位成长",
                        "conflict_upgrade": "冲突升级方式",
                        "notes": "说明",
                    }
                ],
                "rolling_strategy": {
                    "planning_principle": "总纲到卷纲再到当前卷细化",
                    "detail_window": "后续只细化当前卷，并保留下一卷接口",
                    "continuity_focus": "如何保持连续性",
                    "anti_drift_rules": [
                        "每次细化前回看上一卷结尾和人物状态",
                        "严格对齐当前阶段目标与卷末交接"
                    ],
                    "character_collaboration": [
                        "主角线负责推动主冲突",
                        "盟友线负责情报/情感/支线承接"
                    ],
                },
                "volumes": [
                    {
                        "volume_index": 1,
                        "title": "卷名",
                        "chapter_span": "60-80",
                        "stage_positioning": "本卷在全书中的定位",
                        "core_goal": "本卷核心目标",
                        "main_conflict": "本卷主冲突",
                        "character_focus": "本卷重点人物协同",
                        "foreshadowing_task": "本卷伏笔任务",
                        "ending_climax": "卷末爆点",
                        "next_volume_hook": "下卷交接"
                    }
                ],
                "foreshadowings": [
                    {
                        "content": "伏笔内容",
                        "plant_at": "第1卷",
                        "pave_at": ["第2卷"],
                        "reveal_at": "第4卷",
                        "purpose": "这条伏笔承担的作用"
                    }
                ],
                "character_lifecycle": [
                    {
                        "character": "角色名",
                        "debut": "第1卷",
                        "active_span": "1-6卷",
                        "transition": "阶段变化",
                        "volume_role": "卷级职责"
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        framework_prompt = f"""你是长篇网文总策划，请先做“总纲 -> 阶段路线图 -> 分卷规划 -> 滚动细化策略”的分层规划。

【目标】
- 总卷数：{total_volumes}卷
- 总章节规模：{chapter_lower}-{chapter_upper}章
- 当前阶段只做长篇框架，不输出逐章细纲

【规划原则】
1. 必须先明确全书总纲、终局方向和核心矛盾，再拆阶段路线图。
2. 每个阶段都要说明覆盖卷段、章节规模、阶段目标、主冲突和收束标记。
3. 每卷必须是可独立成立的故事阶段，写清卷定位、核心目标、人物协同、伏笔任务、卷末爆点和下卷交接。
4. 必须给出“滚动细化策略”，说明后续如何只细化当前卷，并通过上一卷摘要、人物状态和伏笔清单控制漂移。
5. 这是长篇框架，不要输出逐章清单，不要泛泛而谈。
6. 只返回合法 JSON 对象，不要解释，不要 Markdown 代码块。
7. `volumes` 数组长度必须严格等于 {total_volumes}，且 `volume_index` 必须从 1 连续覆盖到 {total_volumes}，不得缺卷、跳卷或只给示例卷。
8. 如果篇幅紧张，请压缩每卷描述，但绝不能减少卷数。

【世界观】
{world_excerpt}

【人物体系】
{characters_excerpt}

【输出 JSON Schema】
{schema}
"""

        payload = self._story_invoke_agent_json(
            self.creative_director,
            framework_prompt,
            fallback={"volumes": []},
        )
        framework_text = self._story_render_epic_framework(payload, total_volumes)
        if not self._story_has_expected_volume_sections(framework_text, total_volumes):
            existing_indexes = self._story_list_parseable_volume_indexes(framework_text)
            existing_indexes_text = "、".join(str(index) for index in existing_indexes) if existing_indexes else "无"
            fallback_prompt = f"""你是长篇网文总策划，请按以下结构输出长篇框架：

## 一、故事总纲与终局
- 题材类型
- 全局主题
- 故事总纲
- 核心卖点
- 核心矛盾
- 终局方向

## 二、阶段路线图
- 按阶段拆分全书，每个阶段写清覆盖卷段、章节规模、阶段目标、主冲突、成长重点、收束标记

## 三、力量与冲突升级路线
- 写清各阶段的力量/地位/冲突升级路径

## 四、滚动细化策略
- 说明后续如何只细化当前卷
- 说明如何通过上一卷摘要、人物状态、伏笔任务控制漂移
- 说明主角线、盟友线、对手线如何协同

## 五、分卷规划（共{total_volumes}卷）
【第1卷】卷名
- 章节规模
- 卷定位
- 核心目标
- 主冲突
- 人物焦点
- 伏笔任务
- 卷末爆点
- 下卷交接

## 六、关键伏笔布局
- 至少列出核心跨卷伏笔

## 七、核心人物生命周期
- 说明主要人物的登场、活跃跨度、阶段变化和卷级职责

强约束：
1. 总章节规模约 {chapter_lower}-{chapter_upper} 章。
2. 卷标题必须使用“【第X卷】标题”格式。
3. 必须完整列出【第1卷】到【第{total_volumes}卷】，总数严格等于 {total_volumes} 卷，不能缺少任何一卷。
4. 如果已有草稿只覆盖了部分卷（当前仅检测到：{existing_indexes_text}），请直接补全并重写完整的 1-{total_volumes} 卷分卷规划，不要只保留前几卷。
5. 若输出长度受限，请压缩每卷描述，但不要减少卷数。"""
            framework_text = self.creative_director.process(fallback_prompt, {})
        return {
            "expanded_outline": framework_text,
            "framework_type": "epic",
            "total_volumes": total_volumes,
            "total_chapters_range": total_chapters_range,
            "estimated_chapters": (chapter_lower + chapter_upper) // 2,
        }

    def expand_volume_detail(self, framework_content: str, target_volume_index: int,
                            world_setting: str, characters: str,
                            start_chapter_num: int,
                            chapters_count_range: tuple[int, int],
                            prev_volume_summary: Optional[Dict[str, Any]] = None,
                            pending_foreshadowings: Optional[List[Dict[str, Any]]] = None,
                            core_storyline: Optional[str] = None,
                            framework_header: Optional[str] = None,
                            framework_footer: Optional[str] = None) -> Dict[str, Any]:
        selected_model = self.estimate_volume_detail_model(chapters_count_range)
        selected_architect = self.plot_architect_plus if selected_model == "qwen3.5-plus" else self.plot_architect_r1
        target_volume_block = self._story_extract_volume_block(framework_content, target_volume_index)
        header_excerpt = self._story_truncate_text(framework_header, limit=1800) if framework_header else ""
        footer_excerpt = self._story_truncate_text(framework_footer, limit=1800) if framework_footer else ""
        world_excerpt = self._story_truncate_text(world_setting, limit=2500) or "（暂无额外世界观补充）"
        characters_excerpt = self._story_build_character_context(
            characters,
            detail_limit=VOLUME_DETAIL_CHARACTER_CONTEXT_LIMIT,
        ) or "（暂无核心人物信息）"
        core_storyline_text = self._story_truncate_text(
            core_storyline or self._extract_core_storyline_from_framework(framework_content),
            limit=1200,
        ) or "（请从当前卷框架中自行提炼核心主线，不得偏离全书目标。）"
        prev_volume_text = self._story_format_prev_volume_summary(prev_volume_summary)
        pending_foreshadowings_text = self._story_format_pending_foreshadowings(pending_foreshadowings)
        volume_outline_excerpt = self._story_truncate_text(
            target_volume_block or framework_content,
            limit=2000,
        ) or "（未能抽取到目标卷摘要，请结合全书框架自行聚焦当前卷。）"
        schema = json.dumps(
            {
                "story_overview": "本卷的起承转合摘要",
                "volume_positioning": {
                    "volume_title": "卷名",
                    "phase_role": "本卷在全书中的定位",
                    "stage_goal": "本卷阶段目标",
                    "inheritance_from_prev": "如何承接上一卷",
                    "main_conflict": "本卷主冲突",
                    "character_coordination": "主角/盟友/对手如何协同",
                    "ending_handoff": "如何交给下一卷"
                },
                "chapter_groups": [
                    {
                        "arc": "剧情段名称",
                        "chapter_span": f"{start_chapter_num}-{start_chapter_num + 4}",
                        "stage_task": "这一段完成什么任务",
                        "conflict_upgrade": "冲突如何升级",
                        "character_focus": "本段人物焦点",
                        "foreshadowing_task": "本段伏笔任务"
                    }
                ],
                "chapters": [
                    {
                        "chapter_number": start_chapter_num,
                        "title": "章节标题",
                        "scene_goal": "本章核心目标",
                        "conflict_design": "本章冲突推进",
                        "key_events": "关键事件",
                        "highlight_type": "爽点类型",
                        "character_progress": "人物推进",
                        "plot_function": "情节作用",
                        "ending_hook": "结尾钩子",
                        "foreshadowing_item": "伏笔事项",
                        "involved_characters": ["角色A", "角色B"]
                    }
                ],
                "foreshadowing_checks": [
                    {
                        "chapter": f"第{start_chapter_num}章",
                        "action": "埋设/铺垫/回收",
                        "content": "对应伏笔内容"
                    }
                ],
                "volume_connection_check": {
                    "core_task_completion": "本卷完成了什么",
                    "next_volume_opening": "下卷开局场景",
                    "ending_hook": "卷尾钩子"
                }
            },
            ensure_ascii=False,
            indent=2,
        )
        detail_prompt = f"""你是长篇网文章节策划，请将第{target_volume_index}卷细化为可执行的卷级细纲。

【任务范围】
- 目标卷：第{target_volume_index}卷
- 章节编号：从第{start_chapter_num}章开始
- 章节数量：至少{chapters_count_range[0]}章，最多{chapters_count_range[1]}章
- 当前目标：讲清一个完整故事阶段，并和上一卷、下一卷无缝衔接

【硬性要求】
1. 只返回合法 JSON 对象，不要解释，不要 Markdown 代码块。
2. `chapters` 中的 chapter_number 必须连续，从第{start_chapter_num}章开始。
3. 本卷必须明确起点承接、中段升级、卷末爆点、下卷开口，不能只列散点事件。
4. `chapter_groups` 要覆盖本卷主要剧情段，通常拆成3-5段，每段都要标明任务、冲突升级、人物焦点和伏笔任务。
5. 人物协同必须具体：主角负责推进主冲突，盟友/配角承担信息、关系、资源或情绪维度，对手线要形成压迫或反制。
6. 每章必须写清：关键事件、人物推进、情节作用，避免只有情绪描述没有结构职责。
7. 若新增人物，必须让其承担清晰剧情职责，不能为“凑人物卡”而出现。
8. 必须严格服从全书主线、当前卷摘要、上一卷承接与伏笔任务，避免长篇漂移。

【全书核心主线】
{core_storyline_text}

【全局框架头部约束】
{header_excerpt or '（暂无额外头部约束）'}

【当前卷框架摘要】
{volume_outline_excerpt}

【全局伏笔与人物生命周期】
{footer_excerpt or '（暂无额外尾部约束）'}

【上一卷承接信息】
{prev_volume_text}

【本卷待处理伏笔】
{pending_foreshadowings_text}

【世界观补充】
{world_excerpt}

【当前人物体系】
{characters_excerpt}

【输出 JSON Schema】
{schema}
"""

        payload = self._story_invoke_agent_json(
            selected_architect,
            detail_prompt,
            fallback={},
        )
        volume_content, chapter_count = self._story_render_volume_detail(
            payload,
            target_volume_index=target_volume_index,
            start_chapter_num=start_chapter_num,
            chapters_count_range=chapters_count_range,
            pending_foreshadowings=pending_foreshadowings,
        )
        fallback_prompt = f"""请详细扩展第{target_volume_index}卷，并严格按以下结构输出 Markdown：

## 一、故事概述
- 写清本卷承接、阶段目标、主冲突、角色协同和卷末交接

## 二、第{target_volume_index}卷详细规划（预计{chapters_count_range[0]}-{chapters_count_range[1]}章，从第{start_chapter_num}章开始）
- 可先写本卷剧情段落设计
- 然后从第{start_chapter_num}章起逐章输出，直到本卷结尾
- 每章必须包含：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项

## 三、伏笔埋设检查
- 明确本卷埋设/铺垫/回收了哪些伏笔

## 四、卷尾衔接检查
- 明确本卷任务完成情况、下卷开局场景、卷尾钩子

必须严格服从以下约束：
【全书核心主线】
{core_storyline_text}

【当前卷框架摘要】
{volume_outline_excerpt}

【上一卷承接信息】
{prev_volume_text}

【本卷待处理伏笔】
{pending_foreshadowings_text}
"""
        if not volume_content or not self._story_is_valid_volume_detail_chapter_count(chapter_count, chapters_count_range):
            retry_reason = ""
            if chapter_count > 0:
                retry_reason = (
                    f"\n\n补充纠偏：你上一版只输出了 {chapter_count} 章，"
                    f"未满足至少 {chapters_count_range[0]} 章、至多 {chapters_count_range[1]} 章的要求。"
                    "请整卷重写，不要只补摘要。"
                )
            volume_content = self._story_normalize_volume_detail_response(
                selected_architect.process(fallback_prompt + retry_reason, {}),
                target_volume_index=target_volume_index,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
                pending_foreshadowings=pending_foreshadowings,
            )

        renumberer = get_chapter_renumberer()
        renumber_result = renumberer.detect_and_fix(
            content=volume_content,
            expected_start=start_chapter_num,
            expected_count_range=chapters_count_range,
        )
        volume_content = renumber_result["fixed_content"]

        actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
        range_shortcuts = self._story_find_volume_detail_range_shortcuts(
            volume_content,
            start_chapter_num=start_chapter_num,
            chapters_count_range=chapters_count_range,
        )
        supplement_architect = self.plot_architect_r1 if selected_model == "qwen3.5-plus" else selected_architect
        if (
            not self._story_is_valid_volume_detail_chapter_count(actual_chapter_count, chapters_count_range)
            or range_shortcuts
        ):
            repair_reasons: List[str] = []
            if not self._story_is_valid_volume_detail_chapter_count(actual_chapter_count, chapters_count_range):
                repair_reasons.append(
                    f"上一版仍只识别到 {actual_chapter_count} 章，目标范围是 {chapters_count_range[0]}-{chapters_count_range[1]} 章。"
                )
            if range_shortcuts:
                shortcut_text = "、".join(f"第{start}-{end}章" for start, end in range_shortcuts)
                repair_reasons.append(
                    f"检测到你使用 {shortcut_text} 这类范围摘要代替逐章细纲。"
                    "禁止使用“第A-B章 / A-B章 / 第A至B章”这种写法概括多章，"
                    "目标范围内的每一章都必须单独写出章节标题与全部字段。"
                )
            repair_prompt = (
                fallback_prompt
                + "\n\n强制纠偏："
                + "".join(repair_reasons)
                + "请完整重写，并逐章输出，不得省略，不得用范围摘要代替缺失章节。"
            )
            volume_content = self._story_normalize_volume_detail_response(
                selected_architect.process(repair_prompt, {}),
                target_volume_index=target_volume_index,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
                pending_foreshadowings=pending_foreshadowings,
            )
            renumber_result = renumberer.detect_and_fix(
                content=volume_content,
                expected_start=start_chapter_num,
                expected_count_range=chapters_count_range,
            )
            volume_content = renumber_result["fixed_content"]
            actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
            range_shortcuts = self._story_find_volume_detail_range_shortcuts(
                volume_content,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
            )

        if range_shortcuts:
            missing_ranges = self._story_extract_missing_volume_detail_chapter_ranges(
                volume_content,
                start_chapter_num=start_chapter_num,
                chapters_count_range=chapters_count_range,
            )
            chunked_missing_ranges = self._story_chunk_volume_detail_chapter_ranges(
                missing_ranges,
                chunk_size=15,
            )
            for missing_start, missing_end in chunked_missing_ranges:
                main_section_excerpt = self._story_truncate_text(
                    self._story_extract_volume_detail_main_section(volume_content),
                    limit=6000,
                ) or "（当前正文规划区提取失败，请严格按框架补齐缺失章节。）"
                missing_prompt = f"""你上一版第{target_volume_index}卷细纲在第{missing_start}-{missing_end}章仍未逐章展开，当前文本存在范围摘要或缺失章节。

请不要重写整卷，只补写这段缺失章节：
- 只输出第{missing_start}章到第{missing_end}章的章节区块
- 不要重复已经写出的章节
- 不要输出“故事概述 / 伏笔埋设检查 / 卷尾衔接检查 / 解释 / 代码块”
- 禁止使用“第A-B章 / A-B章 / 第A至B章 / 章节：A-B”这类范围摘要代替任何单章
- 每一章都必须单独写出：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项

【当前卷框架摘要】
{volume_outline_excerpt}

【上一卷承接信息】
{prev_volume_text}

【当前已生成正文规划区摘录】
{main_section_excerpt}
"""
                supplemented_content = self._story_merge_volume_detail_supplement(
                    volume_content,
                    supplement_architect.process(missing_prompt, {}),
                    next_chapter_number=missing_start,
                    max_chapter_number=missing_end,
                )
                if supplemented_content == volume_content:
                    continue
                volume_content = supplemented_content
                renumber_result = renumberer.detect_and_fix(
                    content=volume_content,
                    expected_start=start_chapter_num,
                    expected_count_range=chapters_count_range,
                )
                volume_content = renumber_result["fixed_content"]
                actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
                range_shortcuts = self._story_find_volume_detail_range_shortcuts(
                    volume_content,
                    start_chapter_num=start_chapter_num,
                    chapters_count_range=chapters_count_range,
                )
                if not range_shortcuts:
                    break

        if 0 < actual_chapter_count < chapters_count_range[0]:
            rendered_chapter_range = self._story_extract_rendered_volume_detail_chapter_range(volume_content)
            last_chapter_num = (
                rendered_chapter_range[1]
                if rendered_chapter_range[1] > 0
                else start_chapter_num + actual_chapter_count - 1
            )
            next_chapter_num = max(start_chapter_num, last_chapter_num + 1)
            required_last_chapter = start_chapter_num + chapters_count_range[0] - 1
            allowed_last_chapter = start_chapter_num + chapters_count_range[1] - 1
            chapter_body = re.split(r"(?m)^##\s*(?:三|3)[、.．].*$", volume_content, maxsplit=1)[0].rstrip()
            continuation_context = chapter_body[-6000:] if len(chapter_body) > 6000 else chapter_body
            supplement_prompt = f"""你上一版第{target_volume_index}卷细纲已经写出了前面的 {actual_chapter_count} 章，但还没有达到最低章节数要求。

请不要重写已有内容，只补写缺失的后续章节：
- 从第{next_chapter_num}章开始连续输出
- 至少补到第{required_last_chapter}章
- 最多补到第{allowed_last_chapter}章
- 只返回新增章节区块，不要重复已有章节
- 不要输出“故事概述 / 伏笔埋设检查 / 卷尾衔接检查 / 解释 / 代码块”
- 每章仍需包含：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项

【当前卷框架摘要】
{volume_outline_excerpt}

【上一卷承接信息】
{prev_volume_text}

【已生成内容末段】
{continuation_context}
"""
            supplemented_content = self._story_merge_volume_detail_supplement(
                volume_content,
                supplement_architect.process(supplement_prompt, {}),
                next_chapter_number=next_chapter_num,
            )
            if supplemented_content != volume_content:
                volume_content = supplemented_content
                renumber_result = renumberer.detect_and_fix(
                    content=volume_content,
                    expected_start=start_chapter_num,
                    expected_count_range=chapters_count_range,
                )
                volume_content = renumber_result["fixed_content"]
                actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
                range_shortcuts = self._story_find_volume_detail_range_shortcuts(
                    volume_content,
                    start_chapter_num=start_chapter_num,
                    chapters_count_range=chapters_count_range,
                )

        if 0 < actual_chapter_count < chapters_count_range[0]:
            minimum_missing_ranges = self._story_extract_missing_volume_detail_chapter_ranges(
                volume_content,
                start_chapter_num=start_chapter_num,
                chapters_count_range=(chapters_count_range[0], chapters_count_range[0]),
            )
            chunked_minimum_missing_ranges = self._story_chunk_volume_detail_chapter_ranges(
                minimum_missing_ranges,
                chunk_size=15,
            )
            for missing_start, missing_end in chunked_minimum_missing_ranges:
                if actual_chapter_count >= chapters_count_range[0]:
                    break
                rendered_chapters_now = set(self._story_extract_rendered_volume_detail_chapter_numbers(volume_content))
                if all(
                    chapter_number in rendered_chapters_now
                    for chapter_number in range(missing_start, missing_end + 1)
                ):
                    continue
                main_section_excerpt = self._story_truncate_text(
                    self._story_extract_volume_detail_main_section(volume_content),
                    limit=6000,
                ) or "（当前正文规划区提取失败，请严格按框架补齐最低章节数要求所需的缺失章节。）"
                minimum_prompt = f"""你上一版第{target_volume_index}卷细纲还没有达到最低章节数要求，第{missing_start}-{missing_end}章仍缺失。

请不要重写整卷，只补写这段缺失章节：
- 只输出第{missing_start}章到第{missing_end}章的章节区块
- 不要重复已经写出的章节
- 不要输出“故事概述 / 伏笔埋设检查 / 卷尾衔接检查 / 解释 / 代码块”
- 这是为了补齐本卷至少 {chapters_count_range[0]} 章的最低要求，章号必须和前文连续衔接
- 每一章都必须单独写出：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、结尾钩子；可选补充爽点类型、伏笔事项

【当前卷框架摘要】
{volume_outline_excerpt}

【上一卷承接信息】
{prev_volume_text}

【当前已生成正文规划区摘录】
{main_section_excerpt}
"""
                supplemented_content = self._story_merge_volume_detail_supplement(
                    volume_content,
                    supplement_architect.process(minimum_prompt, {}),
                    next_chapter_number=missing_start,
                    max_chapter_number=missing_end,
                )
                if supplemented_content == volume_content:
                    continue
                volume_content = supplemented_content
                renumber_result = renumberer.detect_and_fix(
                    content=volume_content,
                    expected_start=start_chapter_num,
                    expected_count_range=chapters_count_range,
                )
                volume_content = renumber_result["fixed_content"]
                actual_chapter_count = self._story_count_rendered_volume_detail_chapters(volume_content)
                range_shortcuts = self._story_find_volume_detail_range_shortcuts(
                    volume_content,
                    start_chapter_num=start_chapter_num,
                    chapters_count_range=chapters_count_range,
                )

        if range_shortcuts:
            shortcut_text = "、".join(f"第{start}-{end}章" for start, end in range_shortcuts)
            raise ValueError(
                f"单卷细化未逐章展开：第{target_volume_index}卷仍存在范围摘要 {shortcut_text}，"
                "目标章节必须逐章完整输出。"
            )

        if not self._story_is_valid_volume_detail_chapter_count(actual_chapter_count, chapters_count_range):
            raise ValueError(
                f"单卷细化生成章节数不足：第{target_volume_index}卷最终仅识别到 {actual_chapter_count} 章，"
                f"目标范围为 {chapters_count_range[0]}-{chapters_count_range[1]} 章。"
            )

        validator = get_consistency_validator(strict_mode=True)
        validation_result = validator.validate(
            volume_content=volume_content,
            volume_index=target_volume_index,
            core_storyline=core_storyline or "",
            prev_volume_summary=prev_volume_summary,
            pending_foreshadowings=pending_foreshadowings,
            framework_content=framework_content,
        )
        validation_dict = validation_result.to_dict()
        rendered_chapter_range = self._story_extract_rendered_volume_detail_chapter_range(volume_content)
        chapters_start = rendered_chapter_range[0] if rendered_chapter_range[0] > 0 else start_chapter_num
        chapters_end = (
            rendered_chapter_range[1]
            if rendered_chapter_range[1] > 0
            else start_chapter_num + max(actual_chapter_count, 1) - 1
        )
        actual_count = actual_chapter_count

        return {
            "expanded_outline": volume_content,
            "volume_index": target_volume_index,
            "chapter_count": actual_count,
            "current_chapter_count": actual_count,
            "chapters_start": chapters_start,
            "chapters_end": chapters_end,
            "renumber_result": renumber_result,
            "validation": validation_dict,
            "validation_passed": validation_result.passed,
            "validation_issues": validation_dict.get('issues', []),
            "validation_suggestions": validation_dict.get('suggestions', []),
        }


def create_outline_expander(knowledge_base: Optional[NovelKnowledgeBase] = None,
                           memory_manager: Optional[NovelMemoryManager] = None,
                           genre: str = "",  # 🎯 任务6：添加题材参数
                           planned_chapters_max: int = 0,
                           project_id: Optional[int] = None) -> OutlineExpander:  # 🎯 任务6.1
    """创建大纲扩展器的工厂函数

    Args:
        knowledge_base: 知识库实例
        memory_manager: 记忆管理器实例
        genre: 题材类型
        planned_chapters_max: 规划的最大章节数

    Returns:
        配置好的OutlineExpander实例
    """
    expander = OutlineExpander(knowledge_base, memory_manager, genre, planned_chapters_max)
    if project_id is not None:
        expander.set_project_context(project_id)
    return expander

