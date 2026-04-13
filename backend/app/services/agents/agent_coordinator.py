
from typing import Optional, Dict, Any
import logging
import json
import re
import random

from .knowledge_base import NovelKnowledgeBase
from .memory_manager import NovelMemoryManager
from .agents import CreativeDirectorAgent, WorldArchitectAgent, CharacterDesignerAgent, ContentCreatorAgent, QualityReviewerAgent, OutlinePlanParserAgent
from core.langchain_bridge import create_task_llm, create_model_llm
from .intelligent_truncator import smart_truncate_for_context

# 导入模块化提示词
from app.services.prompts.stages.world_building import (
    WorldBuildingPrompts,
    CharacterDesignPrompts,
    get_genre_world_extension,
    get_genre_character_fields
)
from app.services.prompts.base.format import get_output_format
from app.services.prompts.stages.structure_design import (
    StructureDesignPrompts,
    get_genre_rhythm_guide
)
from app.services.prompts.stages.content_creation import FirstChapterPrompts
from app.services.character_parser import (
    CharacterTextParser,
    convert_legacy_grouped_characters_to_cards,
    has_parseable_character_cards,
    normalize_story_stance_label,
)
from app.services.prompts.genre_registry import (
    get_genre_module as _get_genre_module,
    get_genre_terminology as _get_genre_terminology,
    GENRE_PROMPT_MODULES as _GENRE_PROMPT_MODULES,
    GENRE_TERMINOLOGY as _GENRE_TERMINOLOGY,
    DEFAULT_GENRE_MODULE as _DEFAULT_GENRE_MODULE,
)

logger = logging.getLogger(__name__)


_SINGLE_ROLE_POSITION_RULES = (
    ("主角", ("主角",)),
    ("高位反派", ("高位反派", "终极反派", "最终对手")),
    ("初期对手", ("初期对手",)),
    ("危险盟友", ("危险盟友", "危险同盟")),
    ("导师", ("导师", "引路人", "老师", "前辈", "先生")),
    ("守护者", ("守护者", "护道者", "护卫", "保护者")),
    ("情报角色", ("情报角色", "情报员", "线人", "联络人", "信息接口", "系统", "辅助", "ai", "AI")),
    ("首领", ("首领", "领袖", "掌权者", "宗主", "司主", "家主", "阁主", "会长")),
    ("盟友", ("盟友", "伙伴", "同伴", "队友", "战友", "友方", "合作者", "协作者")),
    ("对手", ("对手", "敌手", "宿敌", "追猎者", "猎手", "反派")),
    ("中立角色", ("中立角色", "中立", "旁观者", "观察者")),
)


def _normalize_role_position_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    compact = text.splitlines()[0].strip().strip("“”\"'‘’")
    for canonical, keywords in _SINGLE_ROLE_POSITION_RULES:
        if any(keyword in compact for keyword in keywords):
            return canonical

    first_segment = re.split(r"[／/｜|；;,，]", compact, maxsplit=1)[0].strip()
    return first_segment[:12]


def _infer_story_stance_from_role_position_label(role_position: str) -> Optional[str]:
    mapping = {
        "主角": "主角方",
        "盟友": "主角方",
        "导师": "主角方",
        "守护者": "主角方",
        "情报角色": "主角方",
        "对手": "反派方",
        "初期对手": "反派方",
        "高位反派": "反派方",
        "中立角色": "中立方",
        "危险盟友": "亦正亦邪",
    }
    return mapping.get(str(role_position or "").strip())


def _replace_single_line_card_field(block: str, label: str, value: str) -> tuple[str, bool]:
    if not value:
        return block, False

    field_pattern = re.compile(
        rf"(?m)^(?P<prefix>\s*(?:###\s*)?(?:\*\*)?【{re.escape(label)}】(?:\*\*)?[：:]\s*).*$"
    )
    if field_pattern.search(block):
        updated = field_pattern.sub(lambda match: f"{match.group('prefix')}{value}", block, count=1)
        return updated, updated != block
    return block, False


def _insert_single_line_card_field(
    block: str,
    label: str,
    value: str,
    *,
    after_labels: tuple[str, ...],
) -> tuple[str, bool]:
    if not value:
        return block, False

    lines = block.splitlines()
    insert_at = 1 if lines else 0

    for index, line in enumerate(lines):
        if any(f"【{after_label}】" in line for after_label in after_labels):
            insert_at = index + 1

    lines.insert(insert_at, f"【{label}】：{value}")
    return "\n".join(lines), True


LEGACY_CHARACTER_SECTION_PATTERNS = (
    re.compile(
        r"(?im)^\s*(?:#+\s*)?[一二三四五六七八九十]+[、.．:：]\s*(?:主角|核心盟友|关键配角|核心反派|人物关系网(?:与动态)?|人物关系网络与动态)"
    ),
    re.compile(
        r"(?im)^\s*(?:#+\s*)?(?:核心主角|核心盟友|关键配角|核心反派|人物关系网|动态演变|关系动态要点)\s*$"
    ),
)


def _build_project_creative_variation_profile(
    project_id: Optional[int],
    *,
    title: Optional[str],
    genre: Optional[str],
    requirement: str,
) -> str:
    """基于项目信息生成差异化创意锚点，降低不同项目收敛到同一套路的概率。"""
    seed_material = f"{project_id or 0}|{title or ''}|{genre or ''}|{requirement or ''}"
    rng = random.Random(seed_material)

    protagonist_options = [
        "主角更像秩序中的修补者、记录者或维护者，而不是一上来就挑战世界的天选之子。",
        "主角开局拥有一定社会位置或既得身份，但这个位置正在迅速失效或被剥夺。",
        "主角的优势来自识别规则漏洞、信息差或灰色地带，而不只是天赋数值更高。",
        "主角背负一段必须长期隐瞒的职业、血缘或使命秘密，这个秘密会持续制造压力。",
        "主角不是最强执行者，而是更擅长组织资源、撮合利益或借势破局的人。",
    ]
    conflict_options = [
        "核心冲突来自秩序维护与个人求生之间的不可调和，而不只是强弱对撞。",
        "主要对手掌握解释权、舆论权、记忆权或规则定义权，不必是纯武力最强者。",
        "主角必须在两套互相冲突的价值体系之间反复站队，每次选择都有代价。",
        "表层目标是生存或上升，深层目标是阻止一种缓慢失控的系统性危机。",
        "每次阶段性胜利都要伴随更大范围的代价外溢，不能只有单向爽感。",
    ]
    world_options = [
        "世界的关键资源并不稀有，但被分配机制严密垄断，稀缺感来自规则而非数量。",
        "力量体系依赖代价交换，所有成长都伴随可见损耗、债务或身份变化。",
        "社会表面稳定，底层运转却依赖一套即将失效的旧规则。",
        "核心奇观来自行业、制度或仪式化日常，而不是单纯的远古遗迹或大场面。",
        "世界最大的秘密不是失落传承，而是所有人默认不说破的一条潜规则。",
    ]
    mood_options = [
        "外在节奏保持强推进，内里持续保留不安感和被追赶感。",
        "整体基调可以明亮克制，但关键转折必须带冷意和代价。",
        "爽感更多建立在精确反制、局面翻盘和秩序改写，而不是纯数值碾压。",
        "情绪氛围偏悬压、逼仄、慢燃反击，避免一路顺风的平推感。",
        "在高压主线中保留少量荒诞感或黑色幽默，让气质更有辨识度。",
    ]
    payoff_options = [
        "爽点优先来自改写规则、重排利益、挪动阵营，而不是单次打脸。",
        "用连续的小型兑现替代单一模板爆点，让主角推进更像滚雪球。",
        "每次升级都最好同步带来关系结构、身份位置或话语权变化。",
        "高潮优先体现借势、联手、反向利用和布局回收，而不是独狼开挂。",
        "关键高潮既要体现聪明，也要保留真实代价，避免过度无损胜利。",
    ]
    trope_avoidance_options = [
        "废柴逆袭",
        "系统绑定后无脑开挂",
        "宗门试炼或学院大比直接充当第一主冲突",
        "捡到上古传承后一路平推",
        "退婚羞辱驱动全部人物关系",
        "天赋检测后立刻震惊全场",
        "反派只会降智打脸",
    ]
    avoidance_count = min(3, len(trope_avoidance_options))
    avoid_tropes = rng.sample(trope_avoidance_options, k=avoidance_count)

    return (
        "【项目级差异化锚点】\n"
        f"- 主角切入：{rng.choice(protagonist_options)}\n"
        f"- 核心冲突：{rng.choice(conflict_options)}\n"
        f"- 世界底色：{rng.choice(world_options)}\n"
        f"- 情绪基调：{rng.choice(mood_options)}\n"
        f"- 爽点兑现：{rng.choice(payoff_options)}\n"
        f"- 默认套路规避：优先避开{'、'.join(avoid_tropes)}。"
    )

# 题材术语映射字典（委托给 genre_registry）
GENRE_TERMINOLOGY = _GENRE_TERMINOLOGY

# 修仙/玄幻题材境界跨度阈值(章节数)
REALM_SPAN_WARNING_THRESHOLD = 500
REALM_SPAN_RECOMMEND_SUBDIVISION = 300

# 题材专属Prompt模块配置（委托给 genre_registry）
GENRE_PROMPT_MODULES = _GENRE_PROMPT_MODULES

# 通用题材(兜底方案)（委托给 genre_registry）
DEFAULT_GENRE_MODULE = _DEFAULT_GENRE_MODULE


class CreativeDirectorCoordinator:
    """
    真实协调器（简版实现）：提供五阶段方法与必要的上下文接口，
    以满足系统的调用约定并避免导入失败。
    """

    def __init__(
        self,
        knowledge_base: Optional[NovelKnowledgeBase] = None,
        memory_manager: Optional[NovelMemoryManager] = None,
        enable_communication: bool = True,
        enable_conflict_detection: bool = True,
        enable_detailed_logging: bool = True,
    ) -> None:
        self.knowledge_base = knowledge_base or NovelKnowledgeBase()
        self.memory_manager = memory_manager or NovelMemoryManager()

        self.enable_communication = enable_communication
        self.enable_conflict_detection = enable_conflict_detection
        self.enable_detailed_logging = enable_detailed_logging
        
        # 初始化真实Agent
        self.creative_director = CreativeDirectorAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.world_architect = WorldArchitectAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.character_designer = CharacterDesignerAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.content_creator = ContentCreatorAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.quality_reviewer = QualityReviewerAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)
        self.outline_plan_parser = OutlinePlanParserAgent(knowledge_base=self.knowledge_base, memory_manager=self.memory_manager)

        # 项目上下文
        self.project_id: Optional[int] = None
        self.project_context: Dict[str, Any] = {
            "concept": "",
            "world_setting": "",
            "characters": "",
            "plot_outline": "",
            "content": "",
            "chapters": [],
            "review": "",
        }

        # 长篇创作配置
        self.target_chapter_count: Optional[int] = None

        # 进度回调（可选）
        self._progress_cb = None
        self._progress_task_id = None
        self._progress_project_id = None

    # ---- 基础接口 ----
    def set_project_context(self, project_id: int) -> None:
        """
        设置当前项目上下文
        
        🔧 关键修复：切换项目时完全清空旧的 project_context，避免项目间数据污染
        """
        # 如果项目 ID 发生变化，完全清空旧的上下文
        if self.project_id != project_id:
            logger.info(f"🔄 切换项目上下文：{self.project_id} -> {project_id}")
            # 完全清空所有项目相关数据，确保新项目从干净状态开始
            # 不保留任何旧项目的配置信息，让每个项目都重新从数据库加载
            self.project_context = {
                "concept": "",
                "world_setting": "",
                "characters": "",
                "plot_outline": "",
                "content": "",
                "chapters": [],
                "review": "",
                # 🔧 关键修复：不保留旧项目的配置，全部清空
                "genre": None,
                "sub_genre": None,
                "planned_length_type": None,
                "planned_chapters_min": None,
                "planned_chapters_max": None,
                "parsed_outline_plan": {},
                # 清空重生相关标记
                "regenerate": False,
                "regenerate_targets": [],
                "title": None,
                "project_title": None,
                "project_genre": None,
            }

            # 清空跨项目共享的短期记忆，避免上一项目的对话历史继续进入新项目 prompt。
            self.memory_manager.clear_history()
            self.memory_manager.clear_context()
            self.memory_manager.load_from_disk(project_id)
            self.memory_manager.update_context(project_id=project_id)
        
        self.project_id = project_id
        for agent in (
            self.creative_director,
            self.world_architect,
            self.character_designer,
            self.content_creator,
            self.quality_reviewer,
            self.outline_plan_parser,
        ):
            agent.set_project_context(project_id)
        logger.info(f"✅ 项目上下文已设置：project_id={project_id}")

    def set_longform_config(self, target_chapter_count: Optional[int] = None) -> None:
        self.target_chapter_count = target_chapter_count

    def set_progress_callback(self, cb, task_id: str, project_id: int) -> None:
        self._progress_cb = cb
        self._progress_task_id = task_id
        self._progress_project_id = project_id

    def _requires_character_card_normalization(self, characters_text: str) -> bool:
        analysis = self._inspect_character_card_structure(characters_text)
        return bool(analysis.get("needs_normalization"))

    def _inspect_character_card_structure(self, characters_text: str) -> Dict[str, Any]:
        if not isinstance(characters_text, str):
            return {
                "parseable": False,
                "contains_mermaid": False,
                "contains_legacy_sections": False,
                "needs_normalization": False,
                "reason": "not_string",
            }

        normalized = characters_text.strip()
        if not normalized:
            return {
                "parseable": False,
                "contains_mermaid": False,
                "contains_legacy_sections": False,
                "needs_normalization": False,
                "reason": "empty",
            }

        parseable = has_parseable_character_cards(normalized)
        contains_mermaid = "mermaid" in normalized.lower()
        contains_legacy_sections = any(pattern.search(normalized) for pattern in LEGACY_CHARACTER_SECTION_PATTERNS)

        if not parseable:
            reason = "no_parseable_cards"
        elif contains_mermaid:
            reason = "contains_mermaid"
        elif contains_legacy_sections:
            reason = "contains_legacy_sections"
        else:
            reason = "ok"

        return {
            "parseable": parseable,
            "contains_mermaid": contains_mermaid,
            "contains_legacy_sections": contains_legacy_sections,
            "needs_normalization": reason != "ok",
            "reason": reason,
        }

    def _normalize_character_cards_if_needed(
        self,
        characters_text: str,
        *,
        requirement: str,
        concept: str,
        world_setting: str,
    ) -> str:
        raw_text = characters_text if isinstance(characters_text, str) else ""
        structure_analysis = self._inspect_character_card_structure(raw_text)
        if not structure_analysis["needs_normalization"]:
            return self._polish_structured_character_card_values(raw_text)

        logger.warning(
            "人物设定需要结构化重排：reason=%s, parseable=%s, legacy_sections=%s, mermaid=%s",
            structure_analysis["reason"],
            structure_analysis["parseable"],
            structure_analysis["contains_legacy_sections"],
            structure_analysis["contains_mermaid"],
        )

        rewrite_prompt = f"""你收到的是一份已经生成但格式跑偏的人物设定文本。请不要重新发散创作，也不要改变故事基本设定，只把已有信息重排为系统可解析的标准人物卡。

【重排原则】
1. 只做结构化重排，不重写故事核心设定，不额外扩展新人物、新势力、新阴谋。
2. 只输出连续的人物卡正文，不要输出总标题、导语、总结、分组标题、关系网、动态演变、mermaid 图。
3. 每个角色必须以 `### 【姓名】：` 开头，严格按标准人物卡字段逐行填写。
4. 组织、势力、阵营不能作为人物条目；如果原文是“组织 + 代表人物”的写法，必须拆成独立人物卡，并把组织写入【所属势力】。
5. 【故事立场】只能从“主角方 / 反派方 / 中立方 / 亦正亦邪”四个值中选择，禁止写“系统方”“主角阵营”“转向主角方”等自由发挥值。
6. 【角色定位】必须是单一标签，只能写成“主角 / 盟友 / 导师 / 对手 / 情报角色 / 守护者 / 首领 / 中立角色 / 危险盟友 / 初期对手 / 高位反派”等可调度定位，禁止写“系统/辅助”“导师/情报角色”这类复合值。
7. 【关键关系】必须写成“角色名：关系性质/当前张力”的格式，不能只列人名。
8. 【主线绑定】必须写成“剧情职责：... / 关联线索：...”。
9. 主角、主要反派、核心盟友在【年龄/性别】【所属势力】【外貌锚点】【核心动机】【关键关系】【主线绑定】中不得写“待补充”；如果原文信息分散，优先从其他段落提炼，不要偷懒留占位符。
10. 禁止输出“一、主角：XX”“二、关键配角”“三、核心反派”“四、人物关系网与动态”这类旧式策划结构。

【标准人物卡格式】
{get_output_format("characters").strip()}

【待重排原文】
{raw_text}"""

        try:
            rewrite_result = self.character_designer.process(
                rewrite_prompt,
                context={
                    "concept": concept,
                    "world_setting": world_setting,
                    "requirement": requirement,
                    "original_characters": raw_text,
                },
                temperature=0.2,
            )
            normalized = rewrite_result if isinstance(rewrite_result, str) else rewrite_result.get("output", "")
        except Exception:
            logger.exception("人物设定自动重排失败，保留原始输出")
            return raw_text

        normalized_analysis = self._inspect_character_card_structure(normalized)
        if normalized and not normalized_analysis["needs_normalization"]:
            logger.info("人物设定已自动重排为标准人物卡")
            return self._polish_structured_character_card_values(normalized)

        for candidate_text in (normalized, raw_text):
            converted = convert_legacy_grouped_characters_to_cards(candidate_text)
            converted_analysis = self._inspect_character_card_structure(converted)
            if converted and not converted_analysis["needs_normalization"]:
                logger.info("人物设定已通过规则兜底转换为标准人物卡")
                return self._polish_structured_character_card_values(converted)

        final_analysis = self._inspect_character_card_structure(normalized)
        logger.warning(
            "人物设定自动重排后仍未通过校验，保留原始输出：reason=%s, parseable=%s, legacy_sections=%s, mermaid=%s",
            final_analysis["reason"],
            final_analysis["parseable"],
            final_analysis["contains_legacy_sections"],
            final_analysis["contains_mermaid"],
        )
        return raw_text

    def _polish_structured_character_card_values(self, characters_text: str) -> str:
        raw_text = characters_text if isinstance(characters_text, str) else ""
        if not has_parseable_character_cards(raw_text):
            return raw_text

        parser = CharacterTextParser()
        split_pattern = r'(?m)(?=^\s*(?:###\s*)?(?:\*\*)?【姓名】(?:\*\*)?[：:])'
        blocks = [block.strip() for block in re.split(split_pattern, raw_text.strip()) if block.strip()]
        if not blocks:
            return raw_text

        changed = False
        polished_blocks = []

        for block in blocks:
            parsed = parser._parse_single_character(block)
            if not parsed:
                polished_blocks.append(block)
                continue

            new_block = block

            if parsed.name:
                updated_block, did_change = _replace_single_line_card_field(new_block, "姓名", parsed.name)
                new_block = updated_block
                changed = changed or did_change

            normalized_role_position = _normalize_role_position_label(parsed.role_position or "")
            if normalized_role_position:
                updated_block, did_change = _replace_single_line_card_field(
                    new_block,
                    "角色定位",
                    normalized_role_position,
                )
                if not did_change and "【角色定位】" not in new_block:
                    updated_block, did_change = _insert_single_line_card_field(
                        new_block,
                        "角色定位",
                        normalized_role_position,
                        after_labels=("故事立场", "年龄/性别", "姓名"),
                    )
                new_block = updated_block
                changed = changed or did_change

            normalized_story_stance = normalize_story_stance_label(parsed.role or "")
            if not normalized_story_stance:
                normalized_story_stance = _infer_story_stance_from_role_position_label(normalized_role_position)
            if normalized_story_stance:
                updated_block, did_change = _replace_single_line_card_field(
                    new_block,
                    "故事立场",
                    normalized_story_stance,
                )
                if not did_change and "【故事立场】" not in new_block:
                    updated_block, did_change = _insert_single_line_card_field(
                        new_block,
                        "故事立场",
                        normalized_story_stance,
                        after_labels=("年龄/性别", "姓名"),
                    )
                new_block = updated_block
                changed = changed or did_change

            polished_blocks.append(new_block)

        if changed:
            logger.info("人物设定已完成字段值归一化")
            return "\n\n".join(polished_blocks)
        return raw_text

    def parse_outline_plan(self, user_outline_plan: str, genre: str = "", planned_length_type: str = "") -> Dict[str, Any]:
        """
        解析用户自定义大纲规划文本，生成结构化JSON
        
        Args:
            user_outline_plan: 用户输入的自然语言大纲规划
            genre: 项目题材
            planned_length_type: 篇幅类型 (short/mid/long/epic)
        
        Returns:
            结构化规划数据，包含：
            - volume_plan: 卷结构规划
            - realm_plan: 境界规划（修仙题材）
            - rhythm_plan: 节奏要求
        """
        logger.info(f"📝 开始解析用户大纲规划...")
        
        if not user_outline_plan or not user_outline_plan.strip():
            logger.info("⚠️ 用户未提供自定义规划，返回空结果")
            return {}
        
        # 构建解析prompt
        parse_prompt = f"""请解析以下用户输入的大纲规划文本，提取其中的结构化信息。

【项目信息】
- 题材：{genre or "未指定"}
- 篇幅：{planned_length_type or "未指定"}

【用户规划原文】
{user_outline_plan}

【解析任务】
请从上述文本中提取以下信息（如果存在）：

1. **卷结构规划** (volume_plan)
   - 卷数：共几卷
   - 卷信息列表：[{{
       "volume_number": 1,
       "volume_title": "卷标题",
       "chapter_range": "1-30章" 或 {"min": 1, "max": 30},
       "main_goal": "本卷主要目标",
       "key_events": ["关键事件1", "关键事件2"]
     }}]

2. **境界规划** (realm_plan) - 仅适用于修仙/玄幻题材
   - 境界列表：[{{
       "realm_name": "境界名称",
       "chapter_range": "1-100章" 或 {"min": 1, "max": 100},
       "sub_levels": ["初期", "中期", "后期", "大圆满"],
       "key_abilities": ["核心能力1", "核心能力2"]
     }}]

3. **节奏要求** (rhythm_plan)
   - 爽点分布：每几章一个小爽点，每几章一个大爽点
   - 情绪起伏：["小爽", "压抑", "大爽", "悬疑", "爆爽"]
   - 转折点：主要转折点位置

【输出JSON Schema】
请严格按照以下JSON格式输出，**只输出JSON，不要添加任何markdown代码块标记或解释性文字**：

{{
  "volume_plan": {{
    "total_volumes": 数字,
    "volumes": [
      {{
        "volume_number": 1,
        "volume_title": "卷标题",
        "chapter_range": {{
          "min": 起始章,
          "max": 结束章
        }},
        "main_goal": "本卷主要目标",
        "key_events": ["事件1", "事件2"]
      }}
    ]
  }},
  "realm_plan": {{
    "realms": [
      {{
        "realm_name": "境界名",
        "chapter_range": {{
          "min": 起始章,
          "max": 结束章
        }},
        "sub_levels": ["阶段1", "阶段2"],
        "key_abilities": ["能力1", "能力2"]
      }}
    ]
  }},
  "rhythm_plan": {{
    "small_climax_interval": 每几章,
    "big_climax_interval": 每几章,
    "emotion_flow": ["小爽", "压抑", "大爽"],
    "major_turning_points": [章节号列表]
  }}
}}

**重要提醒**：
1. 如果用户文本中没有提到某个部分，请直接忽略该字段（不要输出null或空对象）
2. 如果是非修仙题材，可以忽略realm_plan
3. 必须输出合法的JSON格式，不要使用任何注释
4. 章节范围必须使用{{"min": X, "max": Y}}格式

现在请开始解析，直接输出JSON："""
        
        try:
            # 调用解析Agent
            result = self.outline_plan_parser.process(parse_prompt)
            
            # 清理输出，移除markdown代码块标记
            result = result.strip()
            if result.startswith("```json"):
                result = result[7:]
            if result.startswith("```"):
                result = result[3:]
            if result.endswith("```"):
                result = result[:-3]
            result = result.strip()
            
            # 解析JSON
            parsed_plan = json.loads(result)
            logger.info(f"✅ 大纲规划解析成功: {list(parsed_plan.keys())}")
            
            # 存储到项目上下文
            self.project_context["parsed_outline_plan"] = parsed_plan
            
            return parsed_plan
            
        except json.JSONDecodeError as e:
            logger.error(f"⚠️ JSON解析失败: {e}")
            logger.error(f"原始输出: {result[:500]}")
            # 尝试使用正则表达式提取
            return self._fallback_parse(user_outline_plan)
        except Exception as e:
            logger.error(f"⚠️ 解析过程出错: {e}")
            return self._fallback_parse(user_outline_plan)
    
    def _fallback_parse(self, text: str) -> Dict[str, Any]:
        """降级方案：使用正则表达式提取基本信息"""
        logger.info("🔧 使用降级方案解析大纲规划...")
        plan = {}
        
        # 提取卷数
        volume_match = re.search(r'(\d+)\s*卷', text)
        if volume_match:
            plan["volume_plan"] = {
                "total_volumes": int(volume_match.group(1)),
                "volumes": []
            }
        
        # 提取境界
        realm_matches = re.findall(r'(炼气|筑基|金丹|元婴|化神|渡劫|大乘|仙人)', text)
        if realm_matches:
            plan["realm_plan"] = {
                "realms": [{"realm_name": r} for r in set(realm_matches)]
            }
        
        logger.info(f"✅ 降级解析完成: {list(plan.keys())}")
        return plan

    # ---- 阶段方法 ----
    def _stage_one_concept_development(self, requirement: str) -> Dict[str, Any]:
        """
        阶段1：概念开发 - 调用真实Agent生成
        返回 keys：concept, world_setting, characters
        """
        logger.info(f"🎯 开始真实Agent概念开发，需求: {requirement[:100]}...")
        
        # 🔧 获取重生信息（在创意总监执行前就读取）
        regenerate_targets = self.project_context.get("regenerate_targets", [])
        is_regenerate = self.project_context.get("regenerate", False)
        
        # 1. 创意总监生成故事概念（按 regenerate_targets 条件执行）
        should_generate_concept = not is_regenerate or "story" in regenerate_targets
        
        if should_generate_concept:
            logger.info("📝 创意总监正在生成故事概念...")
            # 🔧 重生时的特别提示
            regenerate_hint = ""
            if is_regenerate and "story" in regenerate_targets:
                regenerate_hint = "\n\n【重生成说明】\n这是一次重新生成，请基于用户反馈进行优化与调整，确保有明显改进。若用户未提供具体反馈，则从以下角度进行轻微优化：\n1. 增强核心标签的差异化锐度\n2. 优化Logline的吸引力\n3. 调整核心冲突的层次感"
            project_title = self.project_context.get("title") or self.project_context.get("project_title") or "未命名项目"
            project_genre = self.project_context.get("genre") or self.project_context.get("project_genre") or "通用题材"
            recent_project_signatures = self.project_context.get("recent_project_signatures") or ""
            recent_project_avoidance = self.project_context.get("recent_project_avoidance") or ""
            variation_profile = _build_project_creative_variation_profile(
                self.project_id,
                title=project_title,
                genre=project_genre,
                requirement=requirement,
            )
            concept_prompt = f"""你是一名擅长网文结构设计的"创意总监"，需要为一个新项目生成【故事概念】和初步【世界观设定】。{regenerate_hint}

【已知信息】
- 项目题目：{project_title}
- 题材类型：{project_genre}
- 用户提供的初始想法（如有）：{requirement or "暂无"}

{variation_profile}

【执行偏好】
- 在不违背用户需求的前提下，优先把上述“项目级差异化锚点”落实到主角驱动、世界机制、核心冲突中。
- 除非用户明确要求，否则避免直接复用“废柴逆袭、系统开挂、宗门试炼、学院大比、捡到上古传承、退婚打脸”这类高频默认模板作为主轴。

【强避重约束】
{recent_project_avoidance or "（暂无近期项目避重清单，但仍需主动回避高频修仙模板。）"}
- 除非用户明确要求，否则不要使用“林尘”作为主角名。
- 除非用户明确要求，不要以“宗门杂役 / 杂役弟子 / 废灵根 / 无灵根少年濒死觉醒”作为标准开局。
- 除非用户明确要求，不要使用“吞噬灵根 / 逆修系统 / 反向修炼系统 / 越被羞辱越变强”作为核心机制。
- 除非用户明确要求，不要把世界命名为“九寰界 / 九寰界域”，也不要直接使用“九大仙宗 / 九大仙域 / 上中下三界”作为世界骨架。
- 除非用户明确要求，不要直接复用“飞升骗局 / 高维收割 / 天外监察者 / 养蛊游戏”作为终局真相模板。
- 如果你的方案与近期项目在“主角名、起点身份、核心能力、世界名称、势力骨架、终局真相”中重合达到 3 项及以上，视为不合格，必须先推翻再重想。

{recent_project_signatures}

【总体要求】
1. 先完成“故事概念”六段标准输出，再给出一个与之匹配的高度概括版世界观（可简略）。
2. 保持网文向：强调爽点潜力、冲突强度和持续升级空间。
3. 若 context 中提供了已有大纲或人物设定（重生成场景），须确保新概念与它们在世界观与核心矛盾上相容。

——————————
一、请先生成【故事概念】，严格按以下六个部分输出（用 Markdown 粗体标记小标题）：

1. **一句话卖点（Logline）**：
- 用一句极具吸引力的网文式概括，包含主角类型、核心能力/优势、主要对手/系统，以及最具爽感的长期目标或爆点。
- 优先使用“主角行动 + 意外结果”句式，例如：“档案修补员篡改禁城时序，反成帝国唯一合法继承人”，而不是单纯罗列设定。
- 控制在 30–60 字之间。

2. **日志标题（短标题）**：
- 用 4–10 个字给出一个便于读者记忆的项目名，偏网文风格。

3. **概念摘要（80–150字）**：
- 简要交代主角身份、初始困境、长期目标、主要阻力，以及世界观的一个独特钩子。
- 语气偏“介绍本书卖点”，而不是平铺剧情。

4. **题材与流派（主题材/子流派）**：
- 主题材例如：玄幻修真 / 反乌托邦科幻 / 历史权谋 / 都市奇能 等；
- 子流派例如：系统流 / 科技修仙流 / 穿越流 / 言情权谋 / 无限流 等；
- 用“主题材 / 子流派1+子流派2”的形式表述，保持网文分类习惯。

5. **核心标签（3–6个）**：
- 提炼最能体现本书差异化的关键词，如“末法时代、格物修真、底层逆袭、技术流打脸”；
- 必须至少包含 1 个“反套路/细分创新”标签（例如：“修真+工业流水线”“系统是反派”“主角不想飞升只想活下去”），避免全是常规标签；
- 避免只出现“热血、成长”这类无区分度的词语。

6. **核心冲突与情感基调**：
- 用 2–3 句话说明：
  - 主线冲突是谁对谁，是什么利益/观念/系统矛盾；
  - 整体情绪是偏爽文逆袭、黑暗现实、甜宠成长还是悬疑惊悚等（可以混合）。

——————————
二、在完成六段“故事概念”之后，请追加一个小节：

7. **世界观高概摘要（可简略）**：
- 用 3–5 句简要说明故事发生的时代背景、主要势力格局和核心规则特点；
- 此处只做高度概括，详细世界观将在后续阶段展开。

请严格按照上述顺序与小标题输出，不要添加其他额外说明。"""
            # 🎲 提高temperature增加创造性，避免相同题材生成重复内容
            concept_result = self.creative_director.process(
                concept_prompt,
                temperature=0.9  # 使用高温度增加随机性和创造性
            )
            concept = concept_result if isinstance(concept_result, str) else concept_result.get("output", requirement)
            logger.info(f"✅ 故事概念生成完成，长度: {len(concept)}")
        else:
            # 重生时不重生story，沿用旧概念
            concept = self.project_context.get("concept") or ""
            logger.info("⏭ 跳过故事概念生成，沿用现有故事概念。")
        
        # 2. 世界观架构师生成世界观设定（按 regenerate_targets 条件执行）
        # 判断是否需要重生世界观
        should_generate_world = not is_regenerate or "world" in regenerate_targets
        
        if should_generate_world:
            logger.info("🌍 世界观架构师正在生成世界观...")
            
            # 🆕 构建题材篇幅信息
            genre_info = ""
            parsed_plan = self.project_context.get("parsed_outline_plan", {})
            
            if self.project_context.get("genre"):
                genre_info += f"\n- 题材：{self.project_context.get('genre')}"
            if self.project_context.get("planned_length_type"):
                length_labels = {"short": "短篇", "mid": "中篇", "long": "长篇", "epic": "超长篇"}
                planned_length = length_labels.get(self.project_context.get("planned_length_type"), self.project_context.get("planned_length_type"))
                genre_info += f"\n- 篇幅：{planned_length}"
                if self.project_context.get("planned_chapters_min") and self.project_context.get("planned_chapters_max"):
                    genre_info += f"（{self.project_context.get('planned_chapters_min')}-{self.project_context.get('planned_chapters_max')}章）"
            
            # 🆕 获取题材专属Prompt模块
            current_genre = self.project_context.get("genre", "")
            genre_module = GENRE_PROMPT_MODULES.get(current_genre, DEFAULT_GENRE_MODULE)
            genre_terms = GENRE_TERMINOLOGY.get(current_genre, {})
            
            # 🆕 构建规划约束
            plan_constraint = ""
            if parsed_plan:
                plan_constraint += "\n\n【用户自定义规划约束】"
                
                # 境界规划
                if "realm_plan" in parsed_plan and parsed_plan["realm_plan"].get("realms"):
                    plan_constraint += "\n**境界规划**：用户已指定以下境界体系，世界观必须兼容："
                    
                    # 🆕 修仙/玄幻题材境界节奏检查
                    current_genre = self.project_context.get("genre", "")
                    if current_genre in ["修仙", "玄幻"]:
                        for realm in parsed_plan["realm_plan"]["realms"][:5]:  # 最多显示5个
                            realm_name = realm.get('realm_name', '')
                            plan_constraint += f"\n- {realm_name}"
                            
                            if realm.get('sub_levels'):
                                plan_constraint += f" (包含: {', '.join(realm['sub_levels'][:3])})"
                            
                            # 检查境界跨度
                            chapter_range = realm.get('chapter_range', {})
                            if isinstance(chapter_range, dict):
                                span = chapter_range.get('max', 0) - chapter_range.get('min', 0)
                                
                                # 超过500章触发建议
                                if span > REALM_SPAN_WARNING_THRESHOLD:
                                    plan_constraint += f" ⚠️ 跨度{span}章，建议细分为【{realm_name}·初期/中期/后期/大圆满】等子阶段"
                                # 300-500章给出温和提示
                                elif span > REALM_SPAN_RECOMMEND_SUBDIVISION:
                                    plan_constraint += f" 💡 跨度{span}章，可考虑细分子阶段以优化节奏"
                    else:
                        # 非修仙题材，简单显示
                        for realm in parsed_plan["realm_plan"]["realms"][:5]:
                            plan_constraint += f"\n- {realm.get('realm_name', '')}"
                            if realm.get('sub_levels'):
                                plan_constraint += f" (包含: {', '.join(realm['sub_levels'][:3])})"
                
                # 卷结构
                if "volume_plan" in parsed_plan and parsed_plan["volume_plan"].get("total_volumes"):
                    total_vols = parsed_plan["volume_plan"]["total_volumes"]
                    plan_constraint += f"\n**卷结构**：用户规划了{total_vols}卷结构，世界观需为这个长度预留升级空间。"
            
            # 🆕 构建题材术语适配提示
            if genre_terms:
                plan_constraint += "\n\n【题材术语适配建议】"
                plan_constraint += f"\n- 核心体系：{genre_terms.get('power_system', '')}"
                plan_constraint += f"\n- 关键资源：{genre_terms.get('resources', '')}"
                plan_constraint += f"\n- 典型冲突：{genre_terms.get('conflicts', '')}"
                plan_constraint += f"\n- 社会结构：{genre_terms.get('social_structure', '')}"
                if current_genre not in ["都市", "纯文学", "悬疑", "言情", "耽美"]:
                    plan_constraint += f"\n- 关键术语：{genre_terms.get('key_terms', '')}"
            
            # 🆕 使用模块化提示词生成世界观 prompt（引用式）
            genre_extra = genre_module.get('world_extra_sections', '') or get_genre_world_extension(current_genre)
            world_prompt = WorldBuildingPrompts.get_world_prompt(
                genre=f"{self.project_context.get('genre') or self.project_context.get('project_genre') or '通用题材'}{genre_info}",
                requirement=requirement or "暂无特别要求",
                genre_constraint=plan_constraint,
                genre_extra_sections=genre_extra
            )
            # 🔥 完整concept传入context,由_format_context智能截断
            world_context = {
                "concept": concept,
                "requirement": requirement
            }
            world_result = self.world_architect.process(world_prompt, context=world_context)
            world = world_result if isinstance(world_result, str) else world_result.get("output", "世界观设定")
            logger.info(f"✅ 世界观生成完成，长度: {len(world)}")
        else:
            # 重生时不重生world，沿用旧世界观
            world = self.project_context.get("world_setting") or ""
            logger.info("⏭ 跳过世界观生成，沿用现有世界观设定。")
        
        # 3. 人物设计师生成人物设定（按 regenerate_targets 条件执行）
        # 判断是否需要重生人物（目前 UI 只有 story/world，没有人物，所以重生时不该跳过）
        should_generate_characters = not is_regenerate or "characters" in regenerate_targets
        
        if should_generate_characters:
            logger.info("👥 人物设计师正在生成人物...")
            
            # 🆕 使用模块化提示词生成人物设计 prompt（引用式）
            char_extra = genre_module.get('character_extra_fields', '') or get_genre_character_fields(current_genre)
            char_prompt = CharacterDesignPrompts.get_character_prompt(
                requirement=requirement or "暂无特别要求",
                genre_extra_fields=char_extra
            )
            # 🔥 完整concept+world_setting传入context,由_format_context智能截断
            char_context = {
                "concept": concept,
                "world_setting": world,
                "requirement": requirement
            }
            char_result = self.character_designer.process(char_prompt, context=char_context)
            chars = char_result if isinstance(char_result, str) else char_result.get("output", "人物设定")
            chars = self._normalize_character_cards_if_needed(
                chars,
                requirement=requirement,
                concept=concept,
                world_setting=world,
            )
            logger.info(f"✅ 人物生成完成，长度: {len(chars)}")
        else:
            # 重生时不重生人物，沿用旧人物设定
            chars = self.project_context.get("characters") or ""
            logger.info("⏭ 跳过人物生成，沿用现有人物设定。")
        
        # 更新上下文
        self.project_context.update({
            "concept": concept,
            "world_setting": world,
            "characters": chars,
        })
        
        logger.info("🎉 概念开发阶段完成！")
        return {"concept": concept, "world_setting": world, "characters": chars}

    def _stage_two_structure_design(self, concept_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段2：结构设计 - 调用真实Agent生成
        返回 keys：plot_outline
        """
        logger.info(f"🎯 开始真实Agent结构设计...")
        
        concept = concept_result.get("concept") or self.project_context.get("concept")
        world_setting = concept_result.get("world_setting") or self.project_context.get("world_setting")
        characters = concept_result.get("characters") or self.project_context.get("characters")
        
        # 获取题材专属Prompt模块
        current_genre = self.project_context.get("genre", "")
        genre_module = GENRE_PROMPT_MODULES.get(current_genre, DEFAULT_GENRE_MODULE)
        
        logger.info("📝 创意总监正在生成网文卷结构大纲...")
        
        # 🎆 使用分层摘要策略优化上下文
        from .layered_summarizer import LayeredSummarizer
        
        logger.info(f"\n{'='*70}")
        logger.info(f"【分层摘要器】为结构设计阶段准备上下文")
        logger.info(f"{'='*70}\n")
        
        layered_summarizer = LayeredSummarizer(
            self.knowledge_base,
            persist_directory=self.memory_manager.persist_directory,
        )
        context_result = layered_summarizer.prepare_context_for_expansion(
            outline=concept or "",  # 结构设计阶段使用concept作为大纲
            characters=characters or "",
            worldview=world_setting or "",
            scenario="structure_design",
            current_count=self.target_chapter_count or 50,
            project_id=self.project_id,
        )
        
        # 🔥 使用智能选择的模型和优化后的上下文
        selected_model = context_result["selected_model"]
        optimized_context = context_result["context"]
        memory_text = context_result.get("memory_text", "")
        structured_memory = context_result.get("structured_memory", {})
        stats = context_result["stats"]
        
        logger.info(f"📊 上下文优化（结构设计 - 分层摘要）:")
        logger.info(f"   - 选择模型: {selected_model}")
        logger.info(f"   - 原始总长: {len(concept or '') + len(characters or '') + len(world_setting or ''):,}字符")
        logger.info(f"   - 优化后: {len(optimized_context):,}字符 (压缩{(1-stats['compression_ratio'])*100:.1f}%)")
        logger.info(f"   - 结构化记忆: {len(memory_text):,}字符 / {len(structured_memory)}类")
        logger.info(f"   - 目标tokens: {stats['total_tokens']:,} / {stats['target_tokens']:,}\n")
        
        # 🆕 使用模块化提示词生成结构设计 prompt（方案A - 纯引用式）
        rhythm_guide = genre_module.get('outline_rhythm_guide', '') or get_genre_rhythm_guide(current_genre)
        structure_prompt = StructureDesignPrompts.get_structure_prompt(
            genre_rhythm_guide=rhythm_guide,
            genre=current_genre or "通用"
        )
        
        # 🔥 只传optimized_context,避免与分层摘要冲突
        structure_context = {
            "optimized_context": optimized_context,
            "structured_memory_text": memory_text,
            "structured_memory": structured_memory,
        }
        memory_prompt_block = f"""
【结构化记忆约束】
{memory_text}

请优先遵循以上结构化记忆中的人物状态、关系边、伏笔和世界规则，不得随意覆盖或忽略。
""" if memory_text else ""
        # 🔄 临时切换创意总监到分层摘要器选择的模型
        orig_llm = getattr(self.creative_director, "llm", None)
        try:
            # 直接按选中的模型实例化，避免“选了A模型，实际又按task_type路由到B模型”
            structure_llm = create_model_llm(model=selected_model, temperature=0.7)
            logger.info(f"⚙️ [生效日志] 结构阶段按模型直连: {selected_model}")
            
            self.creative_director.llm = structure_llm
            structure_result = self.creative_director.process(
                f"{structure_prompt}\n\n{memory_prompt_block}".strip(),
                context=structure_context
            )
        finally:
            if orig_llm is not None:
                self.creative_director.llm = orig_llm
                logger.info("🔄 [生效日志] 结构阶段结束，创意总监恢复原模型配置")
        
        outline = structure_result if isinstance(structure_result, str) else structure_result.get("output", "结构大纲")
        logger.info(f"✅ 结构大纲生成完成，长度: {len(outline)}")
        
        self.project_context.update({"plot_outline": outline})
        return {"plot_outline": outline}

    def _extract_first_chapter_plan(self, plot_outline: str) -> str:
        """从完整大纲中提取第1章的规划内容
        
        Args:
            plot_outline: 完整的情节大纲
            
        Returns:
            第1章的规划内容,如果提取失败返回简化版本
        """
        if not plot_outline:
            return "请根据故事概念和世界观设定,创作引人入胜的第一章内容。"
        
        # 尝试提取第1章内容（支持多种格式）
        import re
        
        # 模式1: 匹配 "第1章" 或 "第一章" 开头的段落
        patterns = [
            r'第1章[：:](.*?)(?=第2章|第二章|卷二|$)',
            r'第一章[：:](.*?)(?=第2章|第二章|卷二|$)',
            r'第1章\s+(.*?)(?=第2章|第二章|卷二|$)',
            r'第一章\s+(.*?)(?=第2章|第二章|卷二|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, plot_outline, re.DOTALL | re.IGNORECASE)
            if match:
                extracted = match.group(0).strip()
                # 限制长度在2000字以内（保持精简）
                if len(extracted) > 2000:
                    extracted = extracted[:2000] + "..."
                logger.info(f"✅ 成功提取第1章规划,长度: {len(extracted)}")
                return extracted
        
        # 如果没有明确的章节标记,尝试提取开头部分
        lines = plot_outline.split('\n')
        first_section = []
        for line in lines[:50]:  # 只看前50行
            if line.strip():
                first_section.append(line)
                if len('\n'.join(first_section)) > 1500:
                    break
        
        if first_section:
            extracted = '\n'.join(first_section)
            logger.info(f"✅ 提取大纲开头作为第1章规划,长度: {len(extracted)}")
            return extracted
        
        # 兜底:返回整个大纲的前1500字
        fallback = plot_outline[:1500]
        logger.warning(f"⚠️ 无法识别第1章规划结构,使用大纲前1500字")
        return fallback

    def _stage_three_content_creation(self, structure_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段3：内容创作 - 调用真实Agent生成
        返回 keys：content 或 chapters
        """
        logger.info(f"🎯 开始真实Agent内容创作...")
        
        plot_outline = structure_result.get("plot_outline") or self.project_context.get("plot_outline")
        concept = self.project_context.get("concept")
        world_setting = self.project_context.get("world_setting")
        characters = self.project_context.get("characters")
        target = self.target_chapter_count or 1
        current_genre = self.project_context.get('genre') or self.project_context.get('project_genre') or ''
        
        logger.info(f"✍️ 内容创作师正在生成第1章草稿（目标{target}章）...")
        
        # 🔥 从大纲中提取第1章规划
        chapter_plan = self._extract_first_chapter_plan(plot_outline or '')
        
        # 🆕 定义开头/结尾方式（与 workflow.py 保持同步）
        opening_styles = {
            "对话开头": ("对话开头", "直接进入冲突或紧张场景，用对话抽出矛盾", ""),
            "动作开头": ("动作开头", "从正在发生的动态事件开始，制造紧迫感", ""),
            "悬念开头": ("悬念开头", "抛出问题或异常现象，引发读者好奇，创造独特的开场", ""),
            "场景开头": ("场景开头", "通过环境氛围描写快速建立情境，融入题材特色", ""),
            "反转开头": ("反转开头", "与上章结尾形成对比或反差，制造意外效果", ""),
        }
        ending_styles = {
            "悬念式": ("悬念式", "关键信息揭露一半，留下悬念让读者想继续阅读", ""),
            "转折式": ("转折式", "意外事件发生，打破读者预期", ""),
            "动作中断式": ("动作中断式", "危机时刻戈然而止，制造紧张感", ""),
            "信息炸弹式": ("信息炸弹式", "揭露惊人真相或身份，制造震撼效果", ""),
            "选择困境式": ("选择困境式", "主角面临艰难拉择，强化情绪张力", ""),
        }
        
        # ✅ 第1章使用固定的开头/结尾方式（适合开篇）
        selected_opening = opening_styles["悬念开头"]  # 第1章用悬念开头吸引读者
        selected_ending = ending_styles["悬念式"]  # 第1章结尾留悬念
        
        # 🆕 使用ChapterPromptBuilder（与生成下一章保持一致）
        from .chapter_prompt_builder import ChapterPromptBuilder
        
        builder = ChapterPromptBuilder(genre=current_genre)
        content_system_prompt = builder.build_system_prompt()
        content_user_prompt = builder.build_user_prompt(
            next_chapter_number=1,
            chapter_plan=chapter_plan,  # ✅ 只传第1章规划(~1500字)
            previous_ending="",  # 第1章无前文
            recent_chapter_assets_summary="",  # 第1章无连续性资产
            rag_character_context="",  # 初始化时RAG还是空的
            rag_world_context="",  # 初始化时RAG还是空的
            selected_opening=selected_opening,
            selected_ending=selected_ending,
        )
        
        # ✅ 使用双prompt调用
        content_result = self.content_creator.process(
            prompt=content_user_prompt,
            context=None,  # 不需要context
            system_prompt=content_system_prompt  # 传入system_prompt
        )
        content = content_result if isinstance(content_result, str) else content_result.get("output", "章节内容")
        logger.info(f"✅ 第1章创作完成，长度: {len(content)}")
        
        self.project_context.update({"content": content, "chapters": [content]})
        return {"content": content}

    def _stage_four_quality_review(self, content_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段4：质量评审 - 调用真实Agent生成
        返回 keys：review, needs_revision
        """
        logger.info(f"🎯 开始真实Agent质量评审...")
        
        content = (
            content_result.get("content")
            or self.project_context.get("content")
            or self.project_context.get("plot_outline")
            or ""
        )
        
        if not content:
            logger.warning("⚠️ 无内容可评审，返回占位符")
            return {"review": "无可评审内容", "needs_revision": False}
        
        logger.info("🔍 质量评审官正在评审内容...")
        
        # 🆕 使用智能截断替代手动截断
        # qwen3-max 限制: 256K tokens ≈ 384000字符
        # 评审模板约1500字 + content，需确保总输入不超限
        truncated_content = smart_truncate_for_context(
            content=content,
            max_tokens=20000,  # 为评审模板预留10720 tokens空间
            content_type="chapter",
            preserve_ratio=0.8  # 章节内容优先保留完整情节
        )
        
        logger.info(f"📏 内容长度: {len(content)} → {len(truncated_content)}字符")
        
        review_prompt = f"""你是一位专业的网络小说质量评审官。请使用【网文6维度评审体系】对以下内容进行评审：

【待评审内容】
{truncated_content}

## 📊 网文6维度评审体系

### 1. 爽点效果（权重25%）
- 本章是否有明确的爽点或为后续爽点做了铺垫？
- 是否成功吸引读者？

### 2. 节奏把控（权重20%）
- 信息密度是否适中？
- 场景转换是否流畅？
- 对话与叙述比例是否合理（建议30-50%对话）？

### 3. 钩子效果（权重15%）
- 章节开头是否吸引人？
- 章节结尾是否有悬念/钩子？
- 读者是否有“想点下一章”的冲动？

### 4. 代入感（权重15%）
- 主角视角是否清晰？
- 是否有强烈的画面感与情感渲染？

### 5. 文笔流畅度（权重10%）
- 是否存在明显AI痕迹或机械感？
- 对话是否自然、符合人物性格？
- 描写是否生动有画面感？

### 6. 内容一致性（权重15%）
- 与人物设定、世界观规则是否一致？

【输出格式】
请使用以下格式输出评审报告：

## 📊 网文质量评审报告

**综合评分**：X/10分

### 1. 爽点效果 ⭐⭐⭐
- 评价：...
- 问题：...

### 2. 节奏把控 ⭐⭐⭐
- 评价：...
- 问题：...

### 3. 钩子效果 ⭐⭐⭐
- 开头评价：...
- 结尾评价：...
- 问题：...

### 4. 代入感 ⭐⭐⭐
- 评价：...
- 问题：...

### 5. 文笔流畅度 ⭐⭐⭐
- 评价：...
- 问题：...

### 6. 内容一致性 ⭐⭐⭐
- 评价：...
- 问题：...

### 🔧 具体修改建议（按优先级排序）
1. 【必改】...
2. 【建议】...
3. 【可选】..."""
        
        # 🔥 prompt中已包含content[:3000],context不再重复传递
        review_context = None
        review_result = self.quality_reviewer.process(review_prompt, context=review_context)
        review = review_result if isinstance(review_result, str) else review_result.get("output", "评审报告")
        logger.info(f"✅ 质量评审完成，长度: {len(review)}")
        
        # 简单判断是否需要修订（基于关键词）
        needs_revision = any(keyword in review for keyword in ["需要修订", "建议修改", "必须改进", "严重问题"])
        logger.info(f"📋 是否需要修订: {needs_revision}")
        
        self.project_context.update({"review": review})
        return {"review": review, "needs_revision": needs_revision}

    def _stage_five_iteration_optimization(self, review_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        阶段5：迭代优化 - 调用真实Agent生成
        返回 keys：revised_content, final_review
        """
        logger.info(f"🎯 开始真实Agent迭代优化...")
        
        original_content = self.project_context.get("content") or ""
        review = review_result.get("review") or self.project_context.get("review") or ""
        needs_revision = review_result.get("needs_revision", False)
        
        if not needs_revision:
            logger.info("✅ 内容无需修订，直接通过")
            return {"revised_content": original_content, "final_review": "内容质量达标，无需修订"}
        
        logger.info("✏️ 内容创作师正在根据评审意见优化内容...")
        
        # 🆕 使用智能截断替代手动截断
        truncated_original = smart_truncate_for_context(
            content=original_content,
            max_tokens=13000,  # 为评审意见和提示词预留空间
            content_type="chapter",
            preserve_ratio=0.8
        )
        
        truncated_review = smart_truncate_for_context(
            content=review,
            max_tokens=6000,  # 评审意见保留核心问题
            content_type="review",
            preserve_ratio=0.9  # 评审意见优先保留【必改】项
        )
        
        logger.info(f"📏 原始内容: {len(original_content)} → {len(truncated_original)}字符")
        logger.info(f"📏 评审意见: {len(review)} → {len(truncated_review)}字符")
        
        revision_prompt = f"""请根据以下评审意见优化内容：

【原始内容】
{truncated_original}

【评审意见】
{truncated_review}

优化要求：
1. 保持故事主线和人物设定不变
2. 针对评审中指出的具体问题进行修改
3. 优化语言表达和叙事节奏
4. 增强细节描写和情感渲染
5. 确保逻辑连贯性

请输出优化后的完整内容。"""
        
        # 🔥 prompt中已包含original_content[:2000]和review[:1000],context不重复
        revision_context = None
        revision_result = self.content_creator.process(revision_prompt, context=revision_context)
        revised_content = revision_result if isinstance(revision_result, str) else revision_result.get("output", original_content)
        logger.info(f"✅ 内容优化完成，长度: {len(revised_content)}")
        
        # 最终评审
        logger.info("🔍 质量评审官进行最终评审...")
        
        # 🆕 使用智能截断
        truncated_revised = smart_truncate_for_context(
            content=revised_content,
            max_tokens=13000,
            content_type="chapter",
            preserve_ratio=0.8
        )
        
        logger.info(f"📏 优化后内容: {len(revised_content)} → {len(truncated_revised)}字符")
        
        final_review_prompt = f"""请对优化后的内容进行最终评审：

【优化后内容】
{truncated_revised}

Please confirm：
1. 是否解决了之前指出的问题
2. 整体质量是否达标
3. 是否可以发布

给出简短的最终评审意见。"""
        
        # 🔥 prompt中已包含revised_content[:2000],context不重复
        final_review_result = self.quality_reviewer.process(final_review_prompt, context=None)
        final_review = final_review_result if isinstance(final_review_result, str) else final_review_result.get("output", "最终评审完成")
        logger.info(f"✅ 最终评审完成，长度: {len(final_review)}")
        
        self.project_context.update({"content": revised_content})
        return {"revised_content": revised_content, "final_review": final_review}

