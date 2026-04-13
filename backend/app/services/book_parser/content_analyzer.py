"""
书籍内容分析器

使用AI提取书籍中的核心要素：
- 人物体系
- 世界观设定
- 情节脉络
- 写作风格
"""
import os
import json
import asyncio
import logging
import re
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum

from core.unified_llm_client import get_llm_client, UnifiedLLMClient
from core.model_resolution import TaskType
from .chapter_splitter import ChapterInfo, ChapterType

logger = logging.getLogger(__name__)

# 🛡️ 全局禁用代理配置 - 确保直连API
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if proxy_var in os.environ:
        del os.environ[proxy_var]


class AnalysisType(str, Enum):
    """分析类型"""
    CHARACTERS = "characters"
    WORLDVIEW = "worldview"
    PLOT = "plot"
    STYLE = "style"
    CONCEPTS = "concepts"
    THEMES = "themes"
    CHAPTER_SUMMARY = "chapter_summary"  # 🆕 章节摘要


@dataclass
class ChapterSummary:
    """章节摘要（与创作流程对齐）"""
    chapter_number: int
    title: str
    summary: str                    # 章节摘要（200-300字）
    characters_appeared: List[str]  # 出场人物
    key_events: List[str]           # 关键事件（每个30字，最多5个）
    setting: str                    # 场景/地点
    conflict: str                   # 冲突/悬念（50字）
    emotion_tone: str               # 情感基调


@dataclass
class AnalysisResult:
    """分析结果"""
    analysis_type: AnalysisType
    content: Dict[str, Any]
    confidence: float
    chapter_range: tuple  # (start, end)
    model_used: str
    token_used: int = 0
    extra_data: Optional[Dict[str, Any]] = None


# 进度回调类型
ProgressCallback = Callable[[str, int, str], Awaitable[None]]  # (stage, progress, message)


class ContentAnalyzer:
    """
    书籍内容分析器
    
    使用AI模型提取书籍中的核心要素
    """
    
    # Token估算：中文约 1.5字/token
    CHARS_PER_TOKEN = 1.5

    # 人物分析结果统一使用的新语义字段，仅保留这些字段进入最终 payload。
    CHARACTER_OUTPUT_KEYS = (
        "name",
        "aliases",
        "role_position",
        "description",
        "story_stance",
        "faction",
        "age_gender",
        "appearance_anchor",
        "personality_anchor",
        "background_status",
        "worldview",
        "motivation",
        "ability_outline",
        "limitation",
        "growth_direction",
        "mainline_role",
        "mainline_clues",
        "relationship_to_main",
        "first_appearance_chapter",
        "appearance_count",
        "importance_score",
        "importance_level",
    )
    
    # qwen-long的安全限制（留一些余量给响应）
    MAX_INPUT_TOKENS = 50000  # 实际支持更多，保守估算
    
    # 情节分析批次大小
    BATCH_SIZE = 10
    
    # 最大重试次数
    MAX_RETRIES = 3

    # 单次模型请求总超时，避免汇总阶段无限挂起
    LLM_REQUEST_TIMEOUT_SECONDS = 180
    QWEN_LONG_REQUEST_TIMEOUT_SECONDS = 300
    
    def __init__(self, llm_client: Optional[UnifiedLLMClient] = None):
        """
        初始化分析器
        
        Args:
            llm_client: LLM客户端实例，不传则使用全局单例
        """
        self.llm = llm_client or get_llm_client()

    def _build_analysis_result(
        self,
        *,
        analysis_type: AnalysisType,
        content: Dict[str, Any],
        confidence: float,
        chapter_range: tuple,
        model_used: str,
        token_used: int = 0,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> AnalysisResult:
        """统一构造分析结果，并对低质量结果做显式降级。"""
        normalized_content = content if isinstance(content, dict) else {}
        normalized_extra = dict(extra_data or {})

        if normalized_content.get("parse_error"):
            raw_response = str(normalized_content.get("raw_response") or "")
            normalized_extra["parse_error"] = True
            normalized_extra["quality_warning"] = "LLM 响应未能成功解析为 JSON，当前分析结果已降级，不建议直接导入创作链路。"
            normalized_extra["raw_response_preview"] = raw_response[:500]
            normalized_content = {
                "parse_error": True,
                "quality_warning": normalized_extra["quality_warning"],
            }
            confidence = min(confidence, 0.15)

        return AnalysisResult(
            analysis_type=analysis_type,
            content=normalized_content,
            confidence=confidence,
            chapter_range=chapter_range,
            model_used=model_used,
            token_used=token_used,
            extra_data=normalized_extra or None,
        )
    
    async def analyze_all(
        self,
        chapters: List[ChapterInfo],
        on_progress: Optional[ProgressCallback] = None,
        analysis_types: Optional[List[AnalysisType]] = None,
        use_two_stage: bool = True  # 🆕 是否使用两阶段分析
    ) -> tuple[List[AnalysisResult], List[Dict[str, Any]]]:
        """
        执行全面分析
        
        两阶段流程：
        1. 阶段1: 逐章提取摘要（每章独立分析，不超限）
        2. 阶段2: 基于摘要汇总分析大纲/世界观/人物体系
        
        Args:
            chapters: 章节列表
            on_progress: 进度回调
            analysis_types: 要执行的分析类型，默认全部
            use_two_stage: 是否使用两阶段分析（默认开启）
            
        Returns:
            (分析结果列表, 章节摘要列表) - 章节摘要包含完整细纲数据
        """
        if analysis_types is None:
            analysis_types = [
                AnalysisType.CHARACTERS,
                AnalysisType.WORLDVIEW,
                AnalysisType.PLOT,
                AnalysisType.STYLE,
                AnalysisType.CONCEPTS,
            ]
        
        results = []
        chapter_summaries = []  # 🆕 保存章节摘要用于返回
        
        if use_two_stage and len(chapters) > 5:
            # 🆕 两阶段分析流程
            results, chapter_summaries = await self._two_stage_analysis(
                chapters, analysis_types, on_progress
            )
        else:
            if chapters:
                if on_progress:
                    await on_progress("chapter_extraction", 0, "正在提取章节摘要...")

                chapter_summaries = await self._extract_all_chapter_summaries(
                    chapters, on_progress
                )
                logger.info(f"✅ 小体量作品章节摘要提取完成: {len(chapter_summaries)} 章")

            # 原有采样分析流程（适用于少量章节）
            results = await self._sampling_analysis(
                chapters,
                analysis_types,
                on_progress,
                progress_start=50 if chapter_summaries else 0,
                progress_end=100,
            )
        
        if on_progress:
            await on_progress("complete", 100, "分析完成")
        
        return results, chapter_summaries
    
    async def _two_stage_analysis(
        self,
        chapters: List[ChapterInfo],
        analysis_types: List[AnalysisType],
        on_progress: Optional[ProgressCallback] = None
    ) -> tuple[List[AnalysisResult], List[Dict[str, Any]]]:
        """
        两阶段分析流程
        
        阶段1: 逐章提取摘要
        阶段2: 基于摘要汇总分析
        
        Returns:
            (分析结果列表, 章节摘要列表)
        """
        results = []
        
        # ========== 阶段1: 逐章提取摘要 ==========
        if on_progress:
            await on_progress("chapter_extraction", 0, "正在逐章提取摘要...")
        
        chapter_summaries = await self._extract_all_chapter_summaries(
            chapters, on_progress
        )
        
        logger.info(f"✅ 阶段1完成: 提取了 {len(chapter_summaries)} 章摘要")
        
        # ========== 阶段2: 基于摘要汇总分析 ==========
        if on_progress:
            await on_progress("synthesis", 50, "正在汇总分析...")
        
        for i, analysis_type in enumerate(analysis_types):
            progress = 50 + int((i / len(analysis_types)) * 50)
            
            if on_progress:
                await on_progress(
                    analysis_type.value, 
                    progress, 
                    f"正在汇总分析{self._get_type_name(analysis_type)}..."
                )
            
            try:
                result = await self._synthesize_from_summaries(
                    chapters, chapter_summaries, analysis_type
                )
                results.append(result)
                logger.info(f"✅ {analysis_type.value} 汇总分析完成")
            except Exception as e:
                logger.error(f"❌ {analysis_type.value} 汇总分析失败: {e}")
        
        return results, chapter_summaries  # 🆕 同时返回章节摘要
    
    async def _sampling_analysis(
        self,
        chapters: List[ChapterInfo],
        analysis_types: List[AnalysisType],
        on_progress: Optional[ProgressCallback] = None,
        progress_start: int = 0,
        progress_end: int = 100,
    ) -> List[AnalysisResult]:
        """原有采样分析流程（适用于少量章节）"""
        results = []
        total_steps = len(analysis_types)
        
        for i, analysis_type in enumerate(analysis_types):
            progress = progress_start + int((i / total_steps) * (progress_end - progress_start))
            
            if on_progress:
                await on_progress(
                    analysis_type.value, 
                    progress, 
                    f"正在分析{self._get_type_name(analysis_type)}..."
                )
            
            try:
                result = await self._analyze_by_type(chapters, analysis_type)
                results.append(result)
                logger.info(f"✅ {analysis_type.value} 分析完成")
            except Exception as e:
                logger.error(f"❌ {analysis_type.value} 分析失败: {e}")
        
        return results
    
    async def _analyze_by_type(
        self,
        chapters: List[ChapterInfo],
        analysis_type: AnalysisType
    ) -> AnalysisResult:
        """
        执行特定类型的分析
        """
        if analysis_type == AnalysisType.CHARACTERS:
            return await self.analyze_characters(chapters)
        elif analysis_type == AnalysisType.WORLDVIEW:
            return await self.analyze_worldview(chapters)
        elif analysis_type == AnalysisType.PLOT:
            return await self.analyze_plot(chapters)
        elif analysis_type == AnalysisType.STYLE:
            return await self.analyze_style(chapters)
        elif analysis_type == AnalysisType.CONCEPTS:
            return await self.analyze_concepts(chapters)
        else:
            raise ValueError(f"不支持的分析类型: {analysis_type}")
    
    def _get_type_name(self, analysis_type: AnalysisType) -> str:
        """获取分析类型的中文名称"""
        names = {
            AnalysisType.CHARACTERS: "人物体系",
            AnalysisType.WORLDVIEW: "世界观设定",
            AnalysisType.PLOT: "情节脉络",
            AnalysisType.STYLE: "写作风格",
            AnalysisType.CONCEPTS: "关键概念",
            AnalysisType.THEMES: "主题思想",
        }
        return names.get(analysis_type, analysis_type.value)

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """按中文语义边界粗切句子，供无模型兜底使用。"""
        if not text:
            return []

        raw_parts = re.split(r'(?<=[。！？!?])\s*|\n+', text)
        sentences: List[str] = []
        for part in raw_parts:
            cleaned = str(part or "").strip()
            if not cleaned:
                continue
            if re.fullmatch(r'[-=*_#\s]{3,}', cleaned):
                continue
            cleaned = re.sub(r'\s+', ' ', cleaned)
            if len(cleaned) >= 6:
                sentences.append(cleaned)
        return sentences

    @staticmethod
    def _normalize_character_text(value: Any, separator: str = "、") -> str:
        """将人物字段统一整理为单行文本。"""
        if value is None:
            return ""
        if isinstance(value, list):
            items: List[str] = []
            for item in value:
                text = ContentAnalyzer._normalize_character_text(item, separator=separator)
                if text:
                    items.append(text)
            return separator.join(list(dict.fromkeys(items)))
        if isinstance(value, dict):
            return ""
        return str(value).strip()

    @classmethod
    def _is_placeholder_character_text(
        cls,
        value: Any,
        *,
        allow_not_mentioned: bool = False,
    ) -> bool:
        """判断人物字段是否仅为占位值。"""
        text = cls._normalize_character_text(value)
        if not text:
            return True

        compact = re.sub(r"\s+", "", text).lower()
        placeholders = {
            "待补充",
            "未知",
            "不详",
            "暂无",
            "暂无信息",
            "暂无描写",
            "未说明",
            "未交代",
            "未明确提及",
            "未明确说明",
            "none",
            "null",
            "n/a",
            "na",
        }
        if not allow_not_mentioned:
            placeholders.add("未提及")

        if compact in placeholders:
            return True

        return bool(re.fullmatch(r"[?？.。·•…]+", text))

    @classmethod
    def _first_meaningful_character_text(
        cls,
        *values: Any,
        allow_not_mentioned: bool = False,
        separator: str = "、",
    ) -> str:
        """返回第一个有实际信息量的人物字段文本。"""
        for value in values:
            text = cls._normalize_character_text(value, separator=separator)
            if text and not cls._is_placeholder_character_text(
                text,
                allow_not_mentioned=allow_not_mentioned,
            ):
                return text
        return ""

    @classmethod
    def _canonicalize_character_entry(cls, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        """仅保留新语义字段，直接丢弃所有旧字段。"""
        normalized = dict(raw_item or {})
        return {
            key: value
            for key, value in normalized.items()
            if key in cls.CHARACTER_OUTPUT_KEYS and value not in (None, "", [], {})
        }

    @staticmethod
    def _truncate_character_text(text: str, limit: int = 40) -> str:
        """裁剪人物字段文本，避免生成过长句。"""
        normalized = " ".join(str(text or "").split()).strip("，。；; ")
        if not normalized:
            return ""
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3].rstrip("，。；; ") + "..."

    @classmethod
    def _extract_motivation_phrase(cls, text: str) -> str:
        """从描述中提取动机性短语。"""
        patterns = [
            r"(追查[^，。；]{2,30})",
            r"(追寻[^，。；]{2,30})",
            r"(寻找[^，。；]{2,30})",
            r"(调查[^，。；]{2,30})",
            r"(揭开[^，。；]{2,30})",
            r"(查明[^，。；]{2,30})",
            r"(保护[^，。；]{2,30})",
            r"(守护[^，。；]{2,30})",
            r"(营救[^，。；]{2,30})",
            r"(反抗[^，。；]{2,30})",
            r"(阻止[^，。；]{2,30})",
            r"(夺回[^，。；]{2,30})",
            r"(掌控[^，。；]{2,30})",
            r"(复仇[^，。；]{2,30})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return cls._truncate_character_text(match.group(1), limit=28)
        return ""

    @classmethod
    def _build_character_clues(
        cls,
        *,
        evidence: Optional[List[str]] = None,
        first_appearance_chapter: Optional[int] = None,
        appearance_count: Optional[int] = None,
    ) -> str:
        """构建可直接写入人物卡的关联线索。"""
        evidence_items: List[str] = []
        for item in evidence or []:
            text = cls._first_meaningful_character_text(item, separator="；")
            if text:
                evidence_items.append(text)

        if evidence_items:
            return cls._truncate_character_text(
                "；".join(list(dict.fromkeys(evidence_items))),
                limit=120,
            )

        appearance_parts: List[str] = []
        if first_appearance_chapter:
            appearance_parts.append(f"首次在第{first_appearance_chapter}章出场")
        if appearance_count:
            appearance_parts.append(f"累计出场{appearance_count}章")
        return "，".join(appearance_parts)

    @classmethod
    def _infer_age_gender(cls, char: Dict[str, Any]) -> str:
        """基于身份描述推断保守的年龄/性别信息。"""
        existing = cls._first_meaningful_character_text(
            char.get("age_gender"),
            char.get("age"),
            char.get("gender"),
        )
        if existing:
            return existing

        description = cls._first_meaningful_character_text(
            char.get("description"),
            char.get("background_status"),
            char.get("relationship_to_main"),
        )
        if not description:
            return ""

        age_markers = [
            ("少女", "少女"),
            ("少年", "少年"),
            ("男孩", "少年男性"),
            ("女孩", "少女女性"),
            ("青年", "青年"),
            ("年轻", "青年"),
            ("中年", "中年"),
            ("老年", "老年"),
            ("老人", "老年"),
            ("奶奶", "老年女性"),
            ("大叔", "中年男性"),
        ]
        gender_markers = [
            ("母亲", "女性"),
            ("姐姐", "女性"),
            ("妹妹", "女性"),
            ("女士", "女性"),
            ("奶奶", "女性"),
            ("父亲", "男性"),
            ("哥哥", "男性"),
            ("弟弟", "男性"),
        ]

        age_value = ""
        for keyword, value in age_markers:
            if keyword in description:
                age_value = value
                break

        gender_value = ""
        for keyword, value in gender_markers:
            if keyword in description:
                gender_value = value
                break

        if age_value and gender_value:
            return f"{age_value}/{gender_value}"
        return age_value or gender_value

    @classmethod
    def _infer_appearance(cls, char: Dict[str, Any]) -> str:
        """基于身份与气质生成保守外貌描述。"""
        existing = cls._first_meaningful_character_text(
            char.get("appearance_anchor"),
        )
        if existing:
            return existing

        description = cls._first_meaningful_character_text(
            char.get("description"),
            char.get("background_status"),
            char.get("personality_anchor"),
        )
        if not description:
            return ""

        rules = [
            (("工程师", "系统", "数据", "接口"), "气质冷静克制，常带技术人员的专注与疲惫感"),
            (("医生", "诊疗", "医疗"), "衣着利落整洁，举止带有长期临床工作的克制感"),
            (("首领", "局长", "高层", "负责人"), "仪表克制严整，给人长期掌控局势的压迫感"),
            (("地下", "黑市", "抵抗"), "行动装束偏低调实用，气场警惕凌厉"),
            (("老人", "老周", "奶奶"), "带有岁月沉淀感，神情沉稳而疲惫"),
        ]
        for keywords, text in rules:
            if any(keyword in description for keyword in keywords):
                return text
        return "外在特征以功能性与身份气质为主，缺少明确细节描写"

    @classmethod
    def _infer_worldview(cls, char: Dict[str, Any]) -> str:
        """基于立场/动机推断价值观立场。"""
        existing = cls._first_meaningful_character_text(
            char.get("worldview"),
        )
        if existing:
            return existing

        story_stance = cls._first_meaningful_character_text(
            char.get("story_stance"),
            allow_not_mentioned=True,
        )
        faction = cls._first_meaningful_character_text(
            char.get("faction"),
            allow_not_mentioned=True,
        )
        motivation = cls._first_meaningful_character_text(char.get("motivation"))
        description = cls._first_meaningful_character_text(char.get("description"), char.get("mainline_role"))
        source = "；".join(filter(None, [story_stance, faction, motivation, description]))

        if any(keyword in source for keyword in ("真相", "自主", "自由", "主权", "反抗", "揭露")):
            return "倾向个体记忆自主与真相优先"
        if any(keyword in source for keyword in ("稳定", "秩序", "控制", "系统")):
            return "倾向秩序优先，但在控制与伦理之间摇摆"
        if any(keyword in source for keyword in ("救治", "保护", "守护", "修复")):
            return "重视生命伦理与个体保护"
        if story_stance and story_stance != "未提及":
            return f"立场偏向{story_stance}"
        return "在生存、伦理与真相之间不断权衡"

    @classmethod
    def _infer_role_position(cls, char: Dict[str, Any]) -> str:
        """基于关系、立场与职责描述推断角色定位。"""
        existing = cls._first_meaningful_character_text(
            char.get("role_position"),
            allow_not_mentioned=True,
        )
        if existing:
            return existing

        description = cls._first_meaningful_character_text(
            char.get("description"),
            char.get("mainline_role"),
            char.get("background_status"),
        )
        relationship_to_main = cls._first_meaningful_character_text(char.get("relationship_to_main"))
        story_stance = cls._first_meaningful_character_text(
            char.get("story_stance"),
            allow_not_mentioned=True,
        )
        importance = cls._first_meaningful_character_text(
            char.get("importance_level"),
            char.get("importance"),
            allow_not_mentioned=True,
        )
        source = "；".join(filter(None, [description, relationship_to_main]))

        keyword_rules = [
            (("导师", "师父", "老师"), "导师"),
            (("情报", "线人", "内应", "耳目"), "情报角色"),
            (("守护", "护卫", "保镖"), "守护者"),
            (("医师", "医生", "治疗"), "治疗者"),
            (("首领", "统领", "领袖"), "首领"),
            (("盟友", "伙伴", "搭档", "战友", "同伴", "队友", "协助"), "盟友"),
            (("对手", "宿敌", "追杀", "围杀", "阻挠", "敌对"), "对手"),
            (("中立", "旁观", "游离"), "中立角色"),
        ]
        for keywords, role_position in keyword_rules:
            if any(keyword in source for keyword in keywords):
                return role_position

        if "主角" in importance:
            return "主角"
        if story_stance == "反派方":
            return "对手"
        if story_stance == "中立方":
            return "中立角色"
        if story_stance == "亦正亦邪":
            return "摇摆角色"
        if story_stance == "主角方":
            return "盟友"
        return "功能角色"

    @classmethod
    def _infer_character_defaults(cls, char: Dict[str, Any]) -> None:
        """为缺失的人物字段补充保守可用的默认内容。"""
        description = cls._first_meaningful_character_text(
            char.get("description"),
            char.get("mainline_role"),
        )
        relationship_to_main = cls._first_meaningful_character_text(char.get("relationship_to_main"))
        story_stance = cls._first_meaningful_character_text(
            char.get("story_stance"),
            allow_not_mentioned=True,
        )
        role_position = cls._infer_role_position(char)
        faction = cls._first_meaningful_character_text(
            char.get("faction"),
            allow_not_mentioned=True,
        )
        importance = cls._first_meaningful_character_text(
            char.get("importance_level"),
            char.get("importance"),
            allow_not_mentioned=True,
        )
        first_appearance = char.get("first_appearance_chapter")
        appearance_count = char.get("appearance_count")
        clue_text = cls._first_meaningful_character_text(char.get("mainline_clues"), separator="；")
        is_primary = role_position == "主角" or ("主角" in importance and story_stance in {"", "未提及", "主角方"})
        is_antagonist = story_stance == "反派方" or role_position == "对手"

        if not story_stance:
            char["story_stance"] = "未提及"
        else:
            char["story_stance"] = story_stance

        char["role_position"] = role_position

        if not faction:
            char["faction"] = "未提及"
        else:
            char["faction"] = faction

        if not cls._first_meaningful_character_text(char.get("mainline_role")):
            char["mainline_role"] = description or relationship_to_main or "推动主线事件的关键人物"

        if not cls._first_meaningful_character_text(char.get("motivation")):
            motivation = cls._extract_motivation_phrase("；".join([description, relationship_to_main]))
            if not motivation and relationship_to_main:
                motivation = f"围绕{cls._truncate_character_text(relationship_to_main, 18)}作出关键选择"
            if not motivation and description:
                motivation = f"其行动目标与“{cls._truncate_character_text(description, 22)}”直接相关"
            if not motivation:
                if is_primary:
                    motivation = "主动追索主线真相并推动事件进展"
                elif is_antagonist:
                    motivation = "维护自身立场并阻断主角推进"
                else:
                    motivation = "围绕主线冲突作出选择并影响局势"
            char["motivation"] = motivation

        if not cls._first_meaningful_character_text(
            char.get("ability_outline"),
        ):
            ability_source = "；".join(filter(None, [description, relationship_to_main, faction]))
            ability_rules = [
                (("工程师", "技术", "程序", "黑客", "接口", "系统", "数据分析"), "技术分析、系统操作与信息处理"),
                (("研究员", "科学家", "实验"), "研究分析与实验推进"),
                (("医生", "医师", "诊所", "治疗"), "医疗救治与应急判断"),
                (("警察", "警员", "军", "特工", "队长", "执法", "安保"), "战术执行、追踪与正面压制"),
                (("记者", "调查员", "调查"), "调查取证与信息整合"),
                (("首领", "负责人", "指挥", "组织", "抵抗"), "组织协调、资源调度与行动策划"),
                (("觉醒", "异能", "能力"), "特殊能力运用与高风险行动"),
            ]
            abilities = ""
            for keywords, text in ability_rules:
                if any(keyword in ability_source for keyword in keywords):
                    abilities = text
                    break
            if not abilities:
                if is_antagonist:
                    abilities = "资源调动与局势压制能力"
                else:
                    abilities = "与主线任务相关的执行与应变能力"
            char["ability_outline"] = abilities

        if not cls._first_meaningful_character_text(
            char.get("limitation"),
        ):
            limitation_source = "；".join(filter(None, [description, relationship_to_main]))
            if any(keyword in limitation_source for keyword in ("真相", "追查", "追寻", "调查", "复仇", "执念")):
                limitation_text = "对目标投入过深，关键节点容易冒险"
            elif any(keyword in limitation_source for keyword in ("威胁", "胁迫", "受制", "被迫")):
                limitation_text = "受外部压力牵制，立场稳定性有限"
            elif is_antagonist:
                limitation_text = "立场强硬，容易低估对手与变量"
            elif is_primary:
                limitation_text = "情感与目标绑定过深，容易承担过高风险"
            else:
                limitation_text = "受立场、资源或情绪牵制，行动存在代价"
            char["limitation"] = limitation_text

        if not cls._first_meaningful_character_text(
            char.get("growth_direction"),
        ):
            if is_primary:
                growth_direction_text = "从被动卷入事件，到主动追查真相并承担核心抉择"
            elif is_antagonist:
                growth_direction_text = "从单纯阻力角色，逐步成为主线价值冲突的关键对照"
            elif relationship_to_main:
                growth_direction_text = f"从{cls._truncate_character_text(relationship_to_main, 16)}的位置出发，逐步影响主线走向"
            else:
                growth_direction_text = "随着主线推进，其立场与选择不断被重新定义"
            char["growth_direction"] = growth_direction_text

        if not clue_text:
            char["mainline_clues"] = cls._build_character_clues(
                evidence=[],
                first_appearance_chapter=first_appearance,
                appearance_count=appearance_count,
            ) or "与主线事件存在直接关联"
        else:
            char["mainline_clues"] = clue_text

        if not cls._first_meaningful_character_text(char.get("age_gender"), char.get("age"), char.get("gender")):
            inferred_age_gender = cls._infer_age_gender(char)
            if inferred_age_gender:
                char["age_gender"] = inferred_age_gender

        if not cls._first_meaningful_character_text(
            char.get("appearance_anchor"),
        ):
            inferred_appearance = cls._infer_appearance(char)
            if inferred_appearance:
                char["appearance_anchor"] = inferred_appearance

        if not cls._first_meaningful_character_text(
            char.get("worldview"),
        ):
            inferred_worldview = cls._infer_worldview(char)
            if inferred_worldview:
                char["worldview"] = inferred_worldview

        char.pop("role", None)

    @classmethod
    def _merge_character_payload(cls, base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        """合并同名人物条目，优先保留信息量更高的字段。"""
        merged = dict(base)
        for key, incoming_value in incoming.items():
            if key == "name":
                continue
            if incoming_value in (None, "", [], {}):
                continue

            current_value = merged.get(key)
            if current_value in (None, "", [], {}) or cls._is_placeholder_character_text(current_value, allow_not_mentioned=True):
                merged[key] = incoming_value
                continue

            if isinstance(current_value, list) and isinstance(incoming_value, list):
                merged[key] = list(dict.fromkeys([*current_value, *incoming_value]))
                continue

            if isinstance(current_value, str) and isinstance(incoming_value, str) and len(incoming_value) > len(current_value):
                merged[key] = incoming_value

        return merged

    @classmethod
    def _normalize_character_entries(cls, parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
        """将人物分析结果统一整理为单一 characters 列表。"""
        if not isinstance(parsed, dict):
            return []

        raw_characters = parsed.get("characters")
        if not isinstance(raw_characters, list):
            raw_characters = []
            for bucket_name in ("main_characters", "supporting_characters"):
                bucket = parsed.get(bucket_name) or []
                if isinstance(bucket, list):
                    raw_characters.extend(bucket)

        deduped: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for raw_item in raw_characters:
            if not isinstance(raw_item, dict):
                continue
            normalized_item = cls._canonicalize_character_entry(raw_item)
            name = str(normalized_item.get("name") or "").strip()
            if not name:
                continue
            if name in deduped:
                deduped[name] = cls._merge_character_payload(deduped[name], normalized_item)
                continue
            deduped[name] = normalized_item
            order.append(name)

        return [deduped[name] for name in order]

    @classmethod
    def _replace_character_entries(cls, parsed: Dict[str, Any], characters: List[Dict[str, Any]]) -> Dict[str, Any]:
        """回写标准化后的单一人物列表，并移除旧桶字段。"""
        normalized = dict(parsed or {})
        normalized["characters"] = characters
        normalized.pop("main_characters", None)
        normalized.pop("supporting_characters", None)
        normalized.pop("minor_characters", None)
        return normalized

    @staticmethod
    def _is_likely_character_name(name: str) -> bool:
        """基于简单规则过滤明显不是人物的词。"""
        text = str(name or "").strip()
        if len(text) < 2 or len(text) > 4:
            return False
        if re.search(r'[^\u4e00-\u9fff]', text):
            return False

        stopwords = {
            "灰烬区", "水晶区", "记忆", "数据", "系统", "接口", "诊所", "技术员",
            "技术人", "人员", "局长", "母亲", "妹妹", "年轻人", "控制台", "界面",
            "传送带", "扫描仪", "日志", "样本", "设备", "空气", "晨光", "街区",
            "诊疗室", "忆晶", "信号", "代码", "光芒", "波动", "照片", "中心",
        }
        if text in stopwords:
            return False

        common_surnames = set(
            "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华"
            "金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方"
            "俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝安常乐于时傅皮"
            "卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计"
            "伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江"
            "童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫经"
            "房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉龚程邢裴陆荣翁"
            "荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车"
            "侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶"
            "司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴鬱胥能苍"
            "双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍璩桑桂濮牛寿通边扈燕冀郏"
            "浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居"
            "衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖"
            "融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯"
            "盖益桓公"
        )
        prefix_titles = {"小", "老", "阿"}
        invalid_name_chars = set("说道问答喊看想知在的了着呢吗吧呀么得将于与及并向从给被把让喃")

        if text[0] in prefix_titles:
            if len(text) < 2 or text[1] not in common_surnames:
                return False
        elif text[0] not in common_surnames:
            return False

        if any(ch in invalid_name_chars for ch in text[1:]):
            return False

        invalid_suffixes = (
            "区", "街", "城", "市", "镇", "村", "国", "州", "界", "门", "派", "宗",
            "会", "院", "局", "室", "楼", "站", "厂", "组", "队", "节", "器", "码",
        )
        if text.endswith(invalid_suffixes):
            return False

        return True

    def _extract_character_names_from_text(self, text: str, limit: int = 8) -> List[str]:
        """在无模型时，从正文里粗提人物名。"""
        if not text:
            return []

        patterns = [
            r'(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{2,4})(?=的(?:指尖|声音|目光|手指|眼神|袖口|肩膀|档案|神经接口|照片))',
            r'(?<![\u4e00-\u9fff])([\u4e00-\u9fff]{2,4})(?=(?:说|道|问|答|喊|念着|喃喃|低声|提醒|皱眉|起身|走近|转身|离开|看向|看着|想起|调取|穿过|见到|监测到|重新校准))',
            r'档案显示[:：]\s*([\u4e00-\u9fff]{2,4})',
            r'编号[\dA-Za-z]+批次[^。！？\n]{0,40}?([\u4e00-\u9fff]{2,4})',
        ]

        counters: Dict[str, int] = {}
        for pattern in patterns:
            for raw_name in re.findall(pattern, text):
                name = str(raw_name or "").strip()
                if not self._is_likely_character_name(name):
                    continue
                counters[name] = counters.get(name, 0) + 1

        ordered = sorted(counters.items(), key=lambda item: (-item[1], len(item[0]), item[0]))
        return [name for name, _ in ordered[:limit]]

    def _extract_setting_hint(self, text: str) -> str:
        """从章节开头粗提场景地点。"""
        if not text:
            return ""

        patterns = [
            r'([^\n，。]{2,20}(?:中心|诊所|街区|城区|实验室|办公室|控制室|大厦|酒吧|基地))',
            r'(?:在|来到|走进|进入|穿过)([^\n，。]{2,18})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text[:600])
            if match:
                return match.group(1).strip()[:20]
        return ""

    def _build_fallback_chapter_summary(
        self,
        chapter: ChapterInfo,
        *,
        reason: str = "",
    ) -> Dict[str, Any]:
        """当模型不可用或解析失败时，生成最低可用章节资产。"""
        text = chapter.content or ""
        sentences = self._split_sentences(text)
        key_events: List[str] = []
        for sentence in sentences:
            cleaned = sentence.strip("“”\"'")
            if not cleaned:
                continue
            event = cleaned[:30] + ("..." if len(cleaned) > 30 else "")
            if event not in key_events:
                key_events.append(event)
            if len(key_events) >= 5:
                break

        summary_candidates = sentences[:3]
        if len(sentences) > 4:
            summary_candidates.append(sentences[-1])
        summary = " ".join(summary_candidates).strip()
        if not summary:
            summary = (text[:240] + "...") if len(text) > 240 else text

        characters = self._extract_character_names_from_text(text)
        setting = self._extract_setting_hint(text)

        logger.warning(
            "章节摘要提取回退到规则模式: 第%s章《%s》%s",
            chapter.number,
            chapter.title,
            f"| 原因: {reason}" if reason else "",
        )

        return {
            "chapter_number": chapter.number,
            "title": chapter.title,
            "summary": summary[:400],
            "characters_appeared": characters,
            "key_events": key_events,
            "setting": setting,
            "character_clues": [],
            "scene_goal": f"{setting or '本章场景'}中推进核心事件"[:40],
            "conflict_arc": {
                "trigger": key_events[0] if key_events else "",
                "escalation": key_events[1] if len(key_events) > 1 else "",
                "resolution": key_events[-1] if key_events else "",
            },
            "emotion_curve": "平静→紧张→悬念" if key_events else "",
            "highlight": {"type": "无", "description": "规则兜底摘要，待模型补全", "intensity": "1"},
            "ending_hook": {
                "type": "悬念" if len(key_events) >= 2 else "无",
                "content": key_events[-1] if key_events else "本章需后续补全钩子",
            },
            "gains": {
                "character_gains": "",
                "plot_progress": key_events[0] if key_events else "",
            },
            "foreshadowing": [],
            "conflict": key_events[1] if len(key_events) > 1 else "",
            "emotion_tone": "紧张" if key_events else "",
        }

    def _build_fallback_character_analysis(
        self,
        character_appearances: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """当人物汇总模型不可用时，按章节出场频次生成最小人物体系。"""
        ranked_characters = sorted(
            [
                (name, info)
                for name, info in character_appearances.items()
                if self._is_likely_character_name(name) and (info.get("count") or 0) > 0
            ],
            key=lambda item: (
                -(item[1].get("count") or 0),
                item[1].get("first_chapter") or 10**9,
                item[0],
            ),
        )

        characters: List[Dict[str, Any]] = []
        relationship_pairs: List[Dict[str, str]] = []

        for idx, (name, info) in enumerate(ranked_characters[:12]):
            payload = {
                "name": name,
            "description": f"基于章节出场频次识别的人物，累计出现 {info.get('count', 0)} 章",
            "story_stance": "未提及",
            "role_position": "功能角色",
            "faction": "未提及",
            "first_appearance_chapter": info.get("first_chapter"),
            "appearance_count": info.get("count", 0),
                "importance_score": 1.0 if idx == 0 else round(max(0.3, 1 - idx * 0.08), 2),
            }

            if idx == 0:
                payload["story_stance"] = "主角方"
                payload["role_position"] = "主角"
                payload["importance_level"] = "主角"
                characters.append(payload)
            elif idx <= 2:
                payload["role_position"] = "盟友"
                payload["importance_level"] = "重要角色"
                characters.append(payload)
            else:
                payload["relationship_to_main"] = "与核心剧情相关"
                payload["importance_level"] = "次要角色"
                characters.append(payload)

        if len(characters) >= 2:
            anchor = characters[0]["name"]
            for char in characters[1:3]:
                relationship_pairs.append({
                    "character1": anchor,
                    "character2": char["name"],
                    "relationship": "核心关联人物",
                    "description": "基于章节共同高频出现的启发式关系",
                })

        logger.warning(
            "人物体系分析回退到规则模式: 生成 %s 个候选人物",
            len(characters),
        )

        for char in characters:
            self._infer_character_defaults(char)

        return {
            "characters": characters,
            "character_relationships": relationship_pairs,
            "character_statistics": character_appearances,
        }
    
    # ==================== 阶段1: 逐章提取摘要 ====================
    
    async def _extract_all_chapter_summaries(
        self,
        chapters: List[ChapterInfo],
        on_progress: Optional[ProgressCallback] = None
    ) -> List[Dict[str, Any]]:
        """
        逐章提取摘要（每章独立分析，不超限）
        
        提取内容与创作流程对齐：
        - 章节摘要
        - 出场人物
        - 关键事件
        - 场景/地点
        - 冲突/悬念
        - 情感基调
        """
        summaries = []
        total = len(chapters)
        
        # 并发控制：每批最多5章
        batch_size = 5
        
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch_chapters = chapters[batch_start:batch_end]
            
            # 并发提取这一批
            tasks = [
                self._extract_single_chapter_summary(ch)
                for ch in batch_chapters
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    logger.warning(f"第{batch_start + i + 1}章提取失败: {result}")
                    # 创建空摘要
                    summaries.append({
                        "chapter_number": batch_chapters[i].number,
                        "title": batch_chapters[i].title,
                        "summary": "提取失败",
                        "characters_appeared": [],
                        "key_events": [],
                        "setting": "",
                        "character_clues": [],
                        "conflict": "",
                        "emotion_tone": ""
                    })
                else:
                    summaries.append(result)
            
            # 更新进度
            if on_progress:
                progress = int((batch_end / total) * 45)  # 阶段1占总进度的45%
                await on_progress(
                    "chapter_extraction", 
                    progress, 
                    f"已提取 {batch_end}/{total} 章..."
                )
            
            # 防止API限流
            if batch_end < total:
                await asyncio.sleep(0.5)
        
        return summaries
    
    async def _extract_single_chapter_summary(
        self,
        chapter: ChapterInfo
    ) -> Dict[str, Any]:
        """
        提取单章摘要（增强版 - 支持细纲生成）
        
        输入：单章内容（最多3000字，确保信息完整）
        输出：结构化摘要 + 细纲关键要素
        """
        # 截取章节内容（增加到3000字以获取更完整信息）
        content = self._smart_truncate(chapter.content or "", 3000)
        
        prompt = f"""请深度分析以下章节内容，提取完整的情节要素（用于续写参考）。

【第{chapter.number}章 {chapter.title}】
{content}

请以JSON格式输出（每个字段都很重要，请认真填写）：
{{
    "summary": "章节摘要（300-400字，详细概括本章完整情节发展，包括起因、经过、结果、人物状态变化）",
    "characters_appeared": ["本章出场的人物姓名"],
    "key_events": [
        "关键事件1（30字以内，包含谁做了什么、结果如何）",
        "关键事件2",
        "关键事件3",
        "关键事件4",
        "关键事件5"
    ],
    "setting": "主要场景/地点（20字以内）",
    
    "character_clues": [
        {{
            "name": "人物姓名",
            "story_stance": "故事立场（主角方/反派方/中立方/亦正亦邪/未提及）",
            "faction": "所属势力/组织/门派（未提及则写未提及）",
            "evidence": "原文证据片段（20-40字，包含明确指向的词句）"
        }}
    ],
    
    "scene_goal": "场景目标（40字以内，格式：[地点] + [人物] + [要达成什么]）",
    
    "conflict_arc": {{
        "trigger": "冲突起因（30字以内）",
        "escalation": "冲突升级（30字以内，主角陷入困境或发现转机）",
        "resolution": "冲突结果（30字以内，本章如何收尾）"
    }},
    
    "emotion_curve": "情绪曲线（格式：起点情绪→转折情绪→终点情绪，如：平静→紧张→释然）",
    
    "highlight": {{
        "type": "本章爽点/高潮类型（打脸/升级/获得/反转/危机/无）",
        "description": "爽点具体内容（30字以内）",
        "intensity": "强度（1-5星）"
    }},
    
    "ending_hook": {{
        "type": "结尾钩子类型（悬念/危机/反转/机遇/无）",
        "content": "钩子具体内容（30字以内）"
    }},
    
    "gains": {{
        "character_gains": "主角收获（能力/物品/关系/信息，30字以内）",
        "plot_progress": "主线推进（埋设/揭示了什么伏笔或线索，30字以内）"
    }},
    
    "foreshadowing": ["本章埋设或回收的伏笔（可选，最多3个）"]
}}

注意：
1. 摘要要完整详细，包含故事的来龙去脉和人物状态变化
2. 人物只列出明确出场的，不要猜测
3. 关键事件最多5个，按重要性排序
4. 若本章无明显爽点/钩子，type填"无"，其他字段填"本章为过渡/铺垫章节"
5. 冲突发展要体现起承转合
6. 情绪曲线要准确反映读者阅读时的情感变化
7. 故事立场/所属势力必须有明确文本证据，否则写“未提及”"""

        try:
            result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
            parsed = self._parse_json_response(result)

            if parsed.get("parse_error"):
                raise ValueError("章节摘要 JSON 解析失败")

            # 确保必要字段存在（兼容旧格式 + 新增细纲字段）
            return {
                "chapter_number": chapter.number,
                "title": chapter.title,
                "summary": parsed.get("summary", ""),
                "characters_appeared": parsed.get("characters_appeared", []),
                "key_events": parsed.get("key_events", []),
                "setting": parsed.get("setting", ""),
                "character_clues": parsed.get("character_clues", []),
                # 🆕 细纲关键字段
                "scene_goal": parsed.get("scene_goal", ""),
                "conflict_arc": parsed.get("conflict_arc", {"trigger": "", "escalation": "", "resolution": ""}),
                "emotion_curve": parsed.get("emotion_curve", ""),
                "highlight": parsed.get("highlight", {"type": "无", "description": "", "intensity": "1"}),
                "ending_hook": parsed.get("ending_hook", {"type": "无", "content": ""}),
                "gains": parsed.get("gains", {"character_gains": "", "plot_progress": ""}),
                "foreshadowing": parsed.get("foreshadowing", []),
                # 兼容旧字段
                "conflict": parsed.get("conflict", ""),
                "emotion_tone": parsed.get("emotion_tone", "")
            }
        except Exception as exc:
            return self._build_fallback_chapter_summary(chapter, reason=str(exc))
    
    # ==================== 阶段2: 基于摘要汇总分析 ====================
    
    async def _synthesize_from_summaries(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]],
        analysis_type: AnalysisType
    ) -> AnalysisResult:
        """
        基于章节摘要汇总分析
        
        输入：所有章节的摘要信息
        输出：对应类型的分析结果
        """
        if analysis_type == AnalysisType.CHARACTERS:
            return await self._synthesize_characters(chapters, summaries)
        elif analysis_type == AnalysisType.WORLDVIEW:
            return await self._synthesize_worldview(chapters, summaries)
        elif analysis_type == AnalysisType.PLOT:
            return await self._synthesize_plot(chapters, summaries)
        elif analysis_type == AnalysisType.STYLE:
            return await self._synthesize_style(chapters, summaries)
        elif analysis_type == AnalysisType.CONCEPTS:
            return await self._synthesize_concepts(chapters, summaries)
        else:
            raise ValueError(f"不支持的汇总分析类型: {analysis_type}")
    
    async def _synthesize_characters(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]]
    ) -> AnalysisResult:
        """基于摘要汇总分析人物体系"""
        # 统计人物出场频次
        character_appearances = {}
        for s in summaries:
            for char in s.get("characters_appeared", []):
                if char not in character_appearances:
                    character_appearances[char] = {
                        "count": 0,
                        "first_chapter": s["chapter_number"],
                        "chapters": []
                    }
                character_appearances[char]["count"] += 1
                character_appearances[char]["chapters"].append(s["chapter_number"])

        # 汇总人物线索（故事立场/所属势力）
        character_clues: Dict[str, Dict[str, List[str]]] = {}
        for s in summaries:
            for clue in s.get("character_clues", []) or []:
                name = str(clue.get("name") or "").strip()
                if not name:
                    continue
                story_stance = str(clue.get("story_stance") or "").strip()
                faction = str(clue.get("faction") or "").strip()
                evidence = str(clue.get("evidence") or "").strip()
                entry = character_clues.setdefault(name, {"story_stance": [], "faction": [], "evidence": []})
                if story_stance and story_stance != "未提及":
                    entry["story_stance"].append(story_stance)
                if faction and faction != "未提及":
                    entry["faction"].append(faction)
                if evidence:
                    entry["evidence"].append(evidence)

        character_clues_summary = {
            name: {
                "story_stance": list(dict.fromkeys(values["story_stance"]))[:3],
                "faction": list(dict.fromkeys(values["faction"]))[:3],
                "evidence": list(dict.fromkeys(values["evidence"]))[:3],
            }
            for name, values in character_clues.items()
        }
        
        # 构建汇总提示词
        char_stats = json.dumps(
            {k: v["count"] for k, v in sorted(
                character_appearances.items(), 
                key=lambda x: x[1]["count"], 
                reverse=True
            )[:20]},
            ensure_ascii=False
        )
        
        # 提取关键事件中的人物关系线索
        key_events_text = "\n".join([
            f"第{s['chapter_number']}章: " + ", ".join(s.get("key_events", [])[:2])
            for s in summaries[:50]  # 取前50章的事件
        ])
        
        prompt = f"""基于以下全书统计信息，分析人物体系。

【人物出场统计（姓名: 出场次数）】
{char_stats}

【人物线索（故事立场/所属势力/证据）】
{json.dumps(character_clues_summary, ensure_ascii=False)}

【关键事件线索】
{key_events_text}

【全书信息】
总章数: {len(chapters)}章

请分析并输出JSON:
{{
    "characters": [
        {{
            "name": "人物姓名",
            "role_position": "角色定位（如主角/盟友/导师/对手/情报角色）",
            "description": "人物简介（50字）",
            "story_stance": "故事立场（主角方/反派方/中立方/亦正亦邪/未提及）",
            "faction": "所属势力/组织/门派（未提及则写未提及）",
            "age_gender": "年龄/性别（如青年男性/中年女性，无法判断写未提及）",
            "appearance_anchor": "外貌锚点（20字内，无法判断写未提及）",
            "personality_anchor": "性格锚点（20字内，概括最稳定的处事特征）",
            "background_status": "背景/当前处境（25字内，无法判断写未提及）",
            "worldview": "价值倾向/处事原则（20字内，用于补足性格锚点）",
            "motivation": "核心动机（20字内，无法判断写未提及）",
            "ability_outline": "能力与限制中的优势部分（20字内，无法判断写未提及）",
            "limitation": "能力与限制中的代价/短板（20字内，无法判断写未提及）",
            "growth_direction": "成长方向（25字内，无法判断写未提及）",
            "mainline_role": "主线绑定中的剧情职责（25字内）",
            "mainline_clues": "主线绑定中的关联线索/证据（30字内，无法判断写未提及）",
            "first_appearance_chapter": 1,
            "appearance_count": 出场次数,
            "importance_score": 0.9,
            "importance_level": "主角/核心角色/重要角色/次要角色/边缘角色/群众角色"
        }}
    ],
    "character_relationships": [
        {{
            "character1": "人物1",
            "character2": "人物2",
            "relationship": "关系类型",
            "description": "关系描述"
        }}
    ]
}}

注意：
1. 出场次数最多的通常是主角
2. 主角importance_score为0.9-1.0
3. 故事立场/所属势力必须有明确文本证据，否则写“未提及”
4. 关系基于事件线索推断
5. 人物字段必须尽量补全，禁止输出 ???、TBD 等占位值
6. 对主要人物优先补全年龄/性别、外貌锚点、性格锚点、主线绑定
7. 优先输出 limitation / growth_direction / mainline_role / mainline_clues 这些新语义键
8. 统一输出 role_position，禁止输出旧字段 role"""

        # 🆕 使用qwen-long进行汇总分析
        try:
            result = await self._call_qwen_long(prompt)
            parsed = self._parse_json_response(result)
            if parsed.get("parse_error"):
                raise ValueError("人物汇总 JSON 解析失败")
        except Exception as exc:
            logger.warning(f"人物汇总分析失败，回退到规则模式: {exc}")
            parsed = self._build_fallback_character_analysis(character_appearances)
        
        counts_sorted = sorted(
            [value["count"] for value in character_appearances.values() if value.get("count", 0) > 0],
            reverse=True
        )
        max_count = counts_sorted[0] if counts_sorted else 0

        def importance_level_for(name: str) -> str:
            count = character_appearances.get(name, {}).get("count", 0)
            if not counts_sorted or count <= 0:
                return "边缘角色"
            try:
                rank_index = counts_sorted.index(count)
            except ValueError:
                rank_index = len(counts_sorted) - 1
            ratio = rank_index / max(len(counts_sorted), 1)
            if ratio < 0.1:
                return "核心角色"
            if ratio < 0.3:
                return "重要角色"
            if ratio < 0.6:
                return "次要角色"
            return "边缘角色"

        def fill_character_fields(char: Dict[str, Any]) -> None:
            name = str(char.get("name") or "").strip()
            if not name:
                return
            if name in character_appearances:
                char.setdefault("appearance_count", character_appearances[name].get("count", 0))
                char.setdefault("first_appearance_chapter", character_appearances[name].get("first_chapter"))
                if max_count > 0 and not char.get("importance_score"):
                    char["importance_score"] = round(character_appearances[name].get("count", 0) / max_count, 2)
            char["importance_level"] = importance_level_for(name)
            if self._is_placeholder_character_text(char.get("story_stance"), allow_not_mentioned=True):
                char["story_stance"] = "未提及"
            if self._is_placeholder_character_text(char.get("faction"), allow_not_mentioned=True):
                char["faction"] = "未提及"
            clues = character_clues_summary.get(name, {})
            if clues:
                if self._is_placeholder_character_text(char.get("story_stance"), allow_not_mentioned=True) and clues.get("story_stance"):
                    char["story_stance"] = clues["story_stance"][0]
                if self._is_placeholder_character_text(char.get("faction"), allow_not_mentioned=True) and clues.get("faction"):
                    char["faction"] = clues["faction"][0]
                evidence_text = self._build_character_clues(
                    evidence=clues.get("evidence") or [],
                    first_appearance_chapter=char.get("first_appearance_chapter"),
                    appearance_count=char.get("appearance_count"),
                )
                if evidence_text and self._is_placeholder_character_text(char.get("mainline_clues")):
                    char["mainline_clues"] = evidence_text

            self._infer_character_defaults(char)
            if char.get("role_position") == "主角":
                char["importance_level"] = "主角"
        if isinstance(parsed, dict):
            characters = self._normalize_character_entries(parsed)
            for char in characters:
                fill_character_fields(char)
            parsed = self._replace_character_entries(parsed, characters)

        # 补充统计信息
        parsed["character_statistics"] = character_appearances
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.CHARACTERS,
            content=parsed,
            confidence=0.90,  # 基于全书统计，可信度更高
            chapter_range=(1, len(chapters)),
            model_used="qwen-long",  # 🆕 更新模型标识
        )
    
    async def _synthesize_worldview(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]]
    ) -> AnalysisResult:
        """基于摘要汇总分析世界观"""
        # 统计场景出现频次
        settings = {}
        for s in summaries:
            setting = s.get("setting", "")
            if setting and setting != "":
                settings[setting] = settings.get(setting, 0) + 1
        
        # 按出现频次排序
        top_settings = sorted(settings.items(), key=lambda x: x[1], reverse=True)[:15]
        
        # 提取前20章的详细信息（开篇世界观建立）
        opening_summaries = "\n".join([
            f"第{s['chapter_number']}章 {s['title']}: {s['summary']} [场景: {s.get('setting', '')}]"
            for s in summaries[:20]
        ])
        
        prompt = f"""基于以下全书统计信息，分析世界观设定。

【场景统计（场景: 出现次数）】
{json.dumps(dict(top_settings), ensure_ascii=False)}

【开篇世界观建立（前20章）】
{opening_summaries}

请分析并输出JSON:
{{
    "world_type": "世界类型（玄幻/仙侠/都市/科幻等）",
    "time_period": "时代背景",
    "world_description": "世界整体描述（100字）",
    "locations": [
        {{
            "name": "地点名称",
            "type": "地点类型",
            "description": "地点描述",
            "appearance_count": 出现次数,
            "importance": "high/medium/low"
        }}
    ],
    "power_systems": [
        {{
            "name": "体系名称",
            "description": "体系描述",
            "levels": ["等级1", "等级2"]
        }}
    ]
}}

注意：
1. 出现次数最多的场景通常是核心地点
2. 从开篇提取世界观基础设定"""

        # 🆕 使用qwen-long进行汇总分析
        result = await self._call_qwen_long(prompt)
        parsed = self._parse_json_response(result)
        
        # 补充统计信息
        parsed["setting_statistics"] = dict(top_settings)
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.WORLDVIEW,
            content=parsed,
            confidence=0.85,
            chapter_range=(1, len(chapters)),
            model_used="qwen-long",  # 🆕 更新模型标识
        )
    
    async def _synthesize_plot(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]]
    ) -> AnalysisResult:
        """基于摘要汇总分析情节脉络"""
        # 构建全书情节线
        plot_timeline = []
        for s in summaries:
            plot_timeline.append({
                "chapter": s["chapter_number"],
                "title": s["title"],
                "summary": s["summary"],
                "events": s.get("key_events", []),
                "conflict": s.get("conflict", ""),
                "tone": s.get("emotion_tone", "")
            })
        
        # 分段发送（防止超限）
        total = len(plot_timeline)
        chunk_size = 50
        
        if total <= chunk_size:
            timeline_text = json.dumps(plot_timeline, ensure_ascii=False, indent=1)
        else:
            # 采样关键节点
            sampled = (
                plot_timeline[:20] +  # 开篇
                plot_timeline[total//3:total//3+10] +  # 中间
                plot_timeline[-15:]  # 结尾
            )
            timeline_text = json.dumps(sampled, ensure_ascii=False, indent=1)
        
        prompt = f"""基于以下全书情节线，分析整体情节架构并提取故事概念。

【情节时间线（共{total}章）】
{timeline_text}

请分析并输出JSON（包含故事概念六部分 + 情节架构）:
{{
    "concept": {{
        "logline": "一句话卖点（30-60字，概括主角类型+核心能力+主要对手+最具爽感的目标）",
        "short_title": "日志标题（4-10字的简短名称）",
        "summary": "概念摘要（80-150字，介绍主角身份、困境、目标、阻力、世界观钩子）",
        "genre": "主题材（如：玄幻修真/都市奇能/科幻末世）",
        "sub_genre": "子流派（如：系统流/穿越流/无限流）",
        "core_tags": ["标签1", "标签2", "标签3"],
        "core_conflict": "核心冲突描述（谁对谁，什么利益/观念矛盾）",
        "emotional_tone": "情感基调（爽文逆袭/黑暗现实/甜宠成长/悬疑惊悚）"
    }},
    "main_plot": "主线剧情概述（200字）",
    "plot_arcs": [
        {{
            "name": "剧情弧名称",
            "description": "剧情弧描述",
            "chapters": [起始章, 结束章],
            "type": "开篇/发展/高潮/收尾"
        }}
    ],
    "turning_points": [
        {{
            "chapter": 章节号,
            "event": "转折事件",
            "significance": "重要性说明"
        }}
    ],
    "conflicts": [
        {{
            "type": "冲突类型",
            "description": "冲突描述",
            "status": "进行中/已解决"
        }}
    ]
}}

注意：
1. 故事概念部分要突出卖点和吸引力
2. 核心标签至少包含1个反套路/细分创新标签
3. 根据情感基调变化识别剧情节奏
4. 转折点通常伴随冲突升级"""

        # 🆕 使用qwen-long进行汇总分析
        result = await self._call_qwen_long(prompt)
        parsed = self._parse_json_response(result)
        
        # 补充统计信息
        parsed["total_chapters"] = total
        parsed["chapter_summaries"] = [s["summary"] for s in summaries]
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.PLOT,
            content=parsed,
            confidence=0.88,
            chapter_range=(1, len(chapters)),
            model_used="qwen-long",  # 🆕 更新模型标识
        )
    
    async def _synthesize_style(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]]
    ) -> AnalysisResult:
        """基于摘要汇总分析写作风格"""
        # 统计情感基调分布
        emotion_dist = {}
        for s in summaries:
            tone = s.get("emotion_tone", "未知")
            emotion_dist[tone] = emotion_dist.get(tone, 0) + 1
        
        # 采样原文片段用于风格分析
        sample_chapters = self._select_sample_chapters(chapters, 10)
        style_samples = []
        for ch in sample_chapters:
            if ch.content:
                # 取每章前500字
                style_samples.append(f"【第{ch.number}章】{ch.content[:500]}")
        
        prompt = f"""基于以下信息，分析写作风格。

【情感基调分布（全书{len(summaries)}章）】
{json.dumps(emotion_dist, ensure_ascii=False)}

【文风样本】
{chr(10).join(style_samples[:5])}

请分析并输出JSON:
{{
    "writing_style": "整体文风描述（50字）",
    "narrative_voice": "叙事视角（第一/第三人称）",
    "tone_distribution": {{"情感1": "比例%", "情感2": "比例%"}},
    "pacing": "叙事节奏（快/中/慢）",
    "dialogue_style": "对话风格描述",
    "description_style": "描写风格描述",
    "strengths": ["写作优点1", "写作优点2"],
    "genre_conventions": "是否遵循类型惯例"
}}"""

        # 🆕 使用qwen-long进行汇总分析
        result = await self._call_qwen_long(prompt)
        parsed = self._parse_json_response(result)
        
        # 补充统计信息
        parsed["emotion_statistics"] = emotion_dist
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.STYLE,
            content=parsed,
            confidence=0.82,
            chapter_range=(1, len(chapters)),
            model_used="qwen-long",  # 🆕 更新模型标识
        )

    async def _synthesize_concepts(
        self,
        chapters: List[ChapterInfo],
        summaries: List[Dict[str, Any]]
    ) -> AnalysisResult:
        """基于章节摘要汇总关键概念/术语。"""
        summary_payload = [
            {
                "chapter_number": summary.get("chapter_number"),
                "title": summary.get("title"),
                "summary": summary.get("summary"),
                "key_events": summary.get("key_events", []),
                "setting": summary.get("setting", ""),
                "scene_goal": summary.get("scene_goal", ""),
                "foreshadowing": summary.get("foreshadowing", []),
            }
            for summary in summaries
        ]

        prompt = f"""基于以下章节摘要，提取适合小说续写复用的关键概念、专有名词、重要物品与术语。

【章节摘要】
{json.dumps(summary_payload[:80], ensure_ascii=False, indent=2)}

请输出JSON：
{{
    "terms": [
        {{
            "term": "术语/概念名",
            "definition": "简明定义（40字以内）",
            "category": "术语/组织/物品/能力/地点/规则",
            "first_mention_chapter": 1
        }}
    ],
    "special_items": [
        {{
            "name": "重要物品名",
            "description": "物品作用（30字以内）"
        }}
    ],
    "techniques": [
        {{
            "name": "能力/技巧名",
            "description": "能力说明（30字以内）"
        }}
    ]
}}

要求：
1. 只保留对续写稳定有用的专有内容，不要提取普通常用词
2. 优先提取反复出现或推动剧情的概念
3. 若无法确认定义，请基于摘要做保守描述，不要过度脑补"""

        result = await self._call_qwen_long(prompt)
        parsed = self._parse_json_response(result)

        if "terms" not in parsed:
            parsed["terms"] = []
        if "special_items" not in parsed:
            parsed["special_items"] = []
        if "techniques" not in parsed:
            parsed["techniques"] = []

        return self._build_analysis_result(
            analysis_type=AnalysisType.CONCEPTS,
            content=parsed,
            confidence=0.78,
            chapter_range=(1, len(chapters)),
            model_used="qwen-long",
        )

    # ==================== 人物分析 ====================
    
    async def analyze_characters(
        self,
        chapters: List[ChapterInfo],
    ) -> AnalysisResult:
        """
        分析人物体系
        
        提取主要人物、配角、人物关系等
        """
        # 智能采样配置
        config = self._get_smart_sample_config(chapters)
        
        # 选择样本章节（开头、中间、结尾）
        samples = self._select_sample_chapters(chapters, config['sample_chapters'])
        
        # 构建分析内容
        content_for_analysis = self._build_chapter_summary(samples, config['words_per_chapter'])
        
        prompt = f"""请分析以下小说内容，提取完整的人物体系。

【小说片段】
{content_for_analysis}

请以JSON格式输出分析结果，严格遵循以下结构：
{{
    "characters": [
        {{
            "name": "人物姓名",
            "aliases": ["别名1", "别名2"],
            "role_position": "角色定位（如主角/盟友/导师/对手/情报角色）",
            "description": "人物简介（50字以内）",
            "story_stance": "故事立场（主角方/反派方/中立方/亦正亦邪/未提及）",
            "faction": "所属势力/组织/门派（未提及则写未提及）",
            "age_gender": "年龄/性别（如青年男性/中年女性，无法判断写未提及）",
            "appearance_anchor": "外貌锚点（20字内，无法判断写未提及）",
            "personality_anchor": ["性格锚点1", "性格锚点2"],
            "background_status": "背景/当前处境（25字内，无法判断写未提及）",
            "worldview": "价值倾向/处事原则（20字内，用于补足性格锚点）",
            "ability_outline": ["能力与限制中的优势部分"],
            "motivation": "核心动机（20字内，无法判断写未提及）",
            "limitation": "能力与限制中的代价/短板（20字内，无法判断写未提及）",
            "growth_direction": "成长方向（30字以内）",
            "mainline_role": "主线绑定中的剧情职责（25字内）",
            "mainline_clues": "主线绑定中的关联线索/证据（30字内，无法判断写未提及）",
            "first_appearance_chapter": 1,
            "importance_score": 0.9,
            "importance_level": "主角/核心角色/重要角色/次要角色/边缘角色/群众角色"
        }}
    ],
    "character_relationships": [
        {{
            "character1": "人物1",
            "character2": "人物2", 
            "relationship": "关系类型",
            "description": "关系描述"
        }}
    ],
    "factions": [
        {{
            "name": "势力/组织名",
            "members": ["成员1", "成员2"],
            "description": "势力描述"
        }}
    ]
}}

注意：
1. 主角importance_score应为0.9-1.0
2. 只提取明确出现的人物，不要猜测
3. 人物关系要基于文本证据
4. 故事立场/所属势力必须有明确文本证据，否则写“未提及”
5. 禁止输出 ???、TBD 等占位值
6. 对主要人物优先补全年龄/性别、外貌锚点、性格锚点、主线绑定
7. 优先输出 limitation / growth_direction / mainline_role / mainline_clues 这些新语义键
8. 统一输出 role_position，禁止输出旧字段 role"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)

        if not isinstance(parsed, dict):
            parsed = {}

        characters = self._normalize_character_entries(parsed)
        counts_sorted = sorted(
            [char.get("appearance_count", 0) for char in characters if char.get("appearance_count", 0) > 0],
            reverse=True
        )
        max_count = counts_sorted[0] if counts_sorted else 0

        def importance_level_for_count(count: int) -> str:
            if not counts_sorted or count <= 0:
                return "边缘角色"
            try:
                rank_index = counts_sorted.index(count)
            except ValueError:
                rank_index = len(counts_sorted) - 1
            ratio = rank_index / max(len(counts_sorted), 1)
            if ratio < 0.1:
                return "核心角色"
            if ratio < 0.3:
                return "重要角色"
            if ratio < 0.6:
                return "次要角色"
            return "边缘角色"

        for char in characters:
            if not isinstance(char, dict):
                continue
            if self._is_placeholder_character_text(char.get("story_stance"), allow_not_mentioned=True):
                char["story_stance"] = "未提及"
            if self._is_placeholder_character_text(char.get("faction"), allow_not_mentioned=True):
                char["faction"] = "未提及"
            if self._is_placeholder_character_text(char.get("importance_level"), allow_not_mentioned=True):
                char["importance_level"] = importance_level_for_count(char.get("appearance_count", 0))
            if max_count > 0 and not char.get("importance_score"):
                char["importance_score"] = round(char.get("appearance_count", 0) / max_count, 2)
            self._infer_character_defaults(char)
            if char.get("role_position") == "主角":
                char["importance_level"] = "主角"

        parsed = self._replace_character_entries(parsed, characters)

        return self._build_analysis_result(
            analysis_type=AnalysisType.CHARACTERS,
            content=parsed,
            confidence=0.85,
            chapter_range=(1, len(chapters)),
            model_used="qwen3-max",
        )
    
    # ==================== 世界观分析 ====================
    
    async def analyze_worldview(
        self,
        chapters: List[ChapterInfo],
        sample_chapters: int = 15
    ) -> AnalysisResult:
        """
        分析世界观设定
        
        提取世界类型、地点、势力、规则体系等
        """
        samples = self._select_sample_chapters(chapters, sample_chapters)
        content_for_analysis = self._build_chapter_summary(samples)
        
        prompt = f"""请分析以下小说内容，提取世界观设定。

【小说片段】
{content_for_analysis}

请以JSON格式输出分析结果：
{{
    "world_type": "世界类型（如：玄幻、仙侠、都市、科幻等）",
    "time_period": "时代背景",
    "world_description": "世界整体描述（100字以内）",
    "locations": [
        {{
            "name": "地点名称",
            "type": "地点类型（城市/门派/国家/位面等）",
            "description": "地点描述",
            "importance": "high/medium/low"
        }}
    ],
    "power_systems": [
        {{
            "name": "体系名称（如：修仙、斗气、魔法等）",
            "description": "体系描述",
            "levels": ["等级1", "等级2", "等级3"],
            "rules": ["规则1", "规则2"]
        }}
    ],
    "factions": [
        {{
            "name": "势力名称",
            "type": "势力类型",
            "description": "势力描述",
            "alignment": "正派/反派/中立"
        }}
    ],
    "special_items": [
        {{
            "name": "物品名称",
            "type": "物品类型",
            "description": "物品描述"
        }}
    ],
    "world_rules": [
        "世界运行的重要规则1",
        "世界运行的重要规则2"
    ]
}}

注意：
1. 只提取文本中明确提到的设定
2. 不要添加未出现的内容
3. 地点和势力按重要性排序"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.WORLDVIEW,
            content=parsed,
            confidence=0.80,
            chapter_range=(1, len(chapters)),
            model_used="qwen3-max",
        )
    
    # ==================== 情节分析 ====================
    
    async def analyze_plot(
        self,
        chapters: List[ChapterInfo]
    ) -> AnalysisResult:
        """
        分析情节脉络
        
        提取主线剧情、关键事件、冲突节点等
        """
        # 使用所有章节的摘要信息
        chapter_summaries = []
        for ch in chapters:
            summary = f"第{ch.number}章 {ch.title}"
            if ch.content:
                # 取每章开头和结尾的片段
                content = ch.content[:500] + "..." + ch.content[-300:] if len(ch.content) > 800 else ch.content
                summary += f"\n{content[:800]}"
            chapter_summaries.append(summary)
        
        # 分批处理
        batch_results = []
        for i in range(0, len(chapter_summaries), self.BATCH_SIZE):
            batch = chapter_summaries[i:i + self.BATCH_SIZE]
            batch_text = "\n\n---\n\n".join(batch)
            
            prompt = f"""请分析以下章节内容，提取情节要点。

【章节内容】
{batch_text}

请提取这些章节中的关键情节事件，以JSON格式输出：
{{
    "events": [
        {{
            "chapter": 章节号,
            "event": "事件描述（30字以内）",
            "type": "转折点/冲突/高潮/伏笔/日常",
            "characters_involved": ["涉及人物"],
            "impact": "事件影响（20字以内）"
        }}
    ]
}}"""

            result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
            parsed = self._parse_json_response(result)
            if "events" in parsed:
                batch_results.extend(parsed["events"])
        
        # 合并并识别主线
        main_plot_prompt = f"""基于以下事件列表，分析整体情节结构。

【事件列表】
{json.dumps(batch_results[:50], ensure_ascii=False, indent=2)}

请以JSON格式输出完整的情节分析：
{{
    "main_plot": "主线剧情概述（200字以内）",
    "plot_arcs": [
        {{
            "name": "剧情弧名称",
            "description": "剧情弧描述",
            "chapters": [起始章, 结束章],
            "type": "开篇/发展/高潮/收尾"
        }}
    ],
    "turning_points": [
        {{
            "chapter": 章节号,
            "event": "转折事件",
            "significance": "重要性说明"
        }}
    ],
    "conflicts": [
        {{
            "type": "冲突类型",
            "parties": ["冲突方1", "冲突方2"],
            "description": "冲突描述",
            "status": "进行中/已解决"
        }}
    ],
    "key_events": {json.dumps(batch_results[:20], ensure_ascii=False)}
}}"""

        result = await self._call_llm_with_retry(main_plot_prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)
        
        # 确保key_events存在
        if "key_events" not in parsed:
            parsed["key_events"] = batch_results[:30]
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.PLOT,
            content=parsed,
            confidence=0.75,
            chapter_range=(1, len(chapters)),
            model_used="qwen3-max",
        )
    
    # ==================== 写作风格分析 ====================
    
    async def analyze_style(
        self,
        chapters: List[ChapterInfo],
        sample_chapters: int = 10
    ) -> AnalysisResult:
        """
        分析写作风格
        
        提取叙事视角、语言特点、对话风格等
        """
        samples = self._select_sample_chapters(chapters, sample_chapters)
        
        # 提取纯文本片段用于风格分析
        text_samples = []
        for ch in samples:
            if ch.content:
                # 取随机片段
                content = ch.content
                if len(content) > 1000:
                    start = len(content) // 4
                    text_samples.append(content[start:start + 800])
                else:
                    text_samples.append(content)
        
        sample_text = "\n\n---\n\n".join(text_samples[:5])
        
        prompt = f"""请分析以下小说文本的写作风格。

【文本样本】
{sample_text}

请以JSON格式输出风格分析结果：
{{
    "narrative_perspective": "叙事视角（第一人称/第三人称限知/第三人称全知）",
    "narrative_style": "叙事风格描述",
    "tone": "整体基调（如：轻松幽默/严肃深沉/热血激昂等）",
    "pacing": "节奏特点（快节奏/慢热/张弛有度等）",
    "language_features": {{
        "vocabulary_level": "词汇水平（通俗/文雅/专业术语多等）",
        "sentence_style": "句式特点（长句为主/短句有力/混合等）",
        "rhetoric": ["常用修辞手法1", "常用修辞手法2"],
        "dialogue_style": "对话风格描述"
    }},
    "description_style": {{
        "scene_description": "场景描写特点",
        "character_description": "人物描写特点",
        "action_description": "动作描写特点",
        "psychological_description": "心理描写特点"
    }},
    "strengths": ["写作优点1", "写作优点2"],
    "unique_features": ["独特风格特征1", "独特风格特征2"],
    "similar_authors": ["风格相似的作者（如有）"],
    "genre_conventions": "是否遵循类型惯例及程度"
}}"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)
        
        return self._build_analysis_result(
            analysis_type=AnalysisType.STYLE,
            content=parsed,
            confidence=0.80,
            chapter_range=(1, len(chapters)),
            model_used="qwen3-max",
        )

    async def analyze_concepts(
        self,
        chapters: List[ChapterInfo],
        sample_chapters: int = 15
    ) -> AnalysisResult:
        """
        分析关键概念/术语

        提取续写阶段最需要复用的专有名词、规则、物品与能力。
        """
        samples = self._select_sample_chapters(chapters, sample_chapters)
        content_for_analysis = self._build_chapter_summary(samples, 1000)

        prompt = f"""请分析以下小说内容，提取适合后续续写使用的关键概念与专有名词。

【小说片段】
{content_for_analysis}

请以JSON格式输出：
{{
    "terms": [
        {{
            "term": "术语/概念名",
            "definition": "简明定义（40字以内）",
            "category": "术语/组织/物品/能力/地点/规则",
            "first_mention_chapter": 1
        }}
    ],
    "special_items": [
        {{
            "name": "重要物品名",
            "description": "物品作用（30字以内）"
        }}
    ],
    "techniques": [
        {{
            "name": "能力/技巧名",
            "description": "能力说明（30字以内）"
        }}
    ]
}}

要求：
1. 仅提取明确出现且对世界观/剧情推进有价值的概念
2. 普通称呼、泛化名词不要纳入 terms
3. first_mention_chapter 尽量依据文本判断，无法确认时填首次明显出现的章节
4. definition 要面向续写使用，强调“是什么、有什么用”"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        parsed = self._parse_json_response(result)

        if "terms" not in parsed:
            parsed["terms"] = []
        if "special_items" not in parsed:
            parsed["special_items"] = []
        if "techniques" not in parsed:
            parsed["techniques"] = []

        return self._build_analysis_result(
            analysis_type=AnalysisType.CONCEPTS,
            content=parsed,
            confidence=0.78,
            chapter_range=(1, len(chapters)),
            model_used="qwen3-max",
        )

    # ==================== 辅助方法 ====================
    
    def _estimate_tokens(self, text: str) -> int:
        """估算文本的token数"""
        return int(len(text) / self.CHARS_PER_TOKEN)
    
    def _get_smart_sample_config(self, chapters: List[ChapterInfo]) -> dict:
        """
        智能计算采样配置
        
        根据书籍规模动态调整采样策略
        """
        total_chapters = len(chapters)
        total_words = sum(ch.word_count for ch in chapters)
        avg_chapter_words = total_words // max(total_chapters, 1)
        
        logger.info(f"📊 书籍统计: {total_chapters}章, {total_words}字, 平均{avg_chapter_words}字/章")
        
        # 目标：每个分析任务的输入控制在安全范围内
        target_chars = int(self.MAX_INPUT_TOKENS * self.CHARS_PER_TOKEN * 0.7)  # 70%安全边界
        
        if total_words <= 50000:  # 小书(≤ 5万字)
            # 可以分析大部分内容
            sample_chapters = min(total_chapters, 30)
            words_per_chapter = min(avg_chapter_words, 1500)
        elif total_words <= 200000:  # 中等(5-20万字)
            # 适度采样
            sample_chapters = min(total_chapters, 25)
            words_per_chapter = min(avg_chapter_words, 1000)
        elif total_words <= 500000:  # 较大(20-50万字)
            # 重点采样
            sample_chapters = min(total_chapters, 20)
            words_per_chapter = 800
        else:  # 超大(> 50万字)
            # 精简采样
            sample_chapters = min(total_chapters, 15)
            words_per_chapter = 600
        
        # 验证估算
        estimated_chars = sample_chapters * words_per_chapter
        estimated_tokens = self._estimate_tokens(str(estimated_chars))  # 粗略估算
        
        logger.info(f"🎯 采样配置: {sample_chapters}章 x {words_per_chapter}字 ≈ {estimated_chars}字")
        
        return {
            'sample_chapters': sample_chapters,
            'words_per_chapter': words_per_chapter,
            'total_words': total_words,
            'total_chapters': total_chapters,
            'avg_chapter_words': avg_chapter_words,
        }
    
    def _build_context_anchor(self, chapters: List[ChapterInfo], prior_analysis: Dict[str, Any] = None) -> str:
        """
        构建上下文锚点（保持分析连贯性）
        
        锚点包含：
        - 全书核心信息
        - 前序分析结果摘要
        - 本次分析定位
        """
        anchor_parts = []
        
        # 1. 全书核心锚点
        total_chapters = len(chapters)
        total_words = sum(ch.word_count for ch in chapters)
        first_chapter_title = chapters[0].title if chapters else "未知"
        
        anchor_parts.append(f"""【全书信息】
- 总章节: {total_chapters}章
- 总字数: {total_words}字
- 开篇标题: {first_chapter_title}""")
        
        # 2. 前序分析锚点（如果有）
        if prior_analysis:
            if 'genre' in prior_analysis:
                anchor_parts.append(f"- 已识别类型: {prior_analysis['genre']}")
            if 'characters' in prior_analysis:
                chars = prior_analysis['characters'][:3]  # 取前3个关键人物
                char_names = [c.get('name', '') for c in chars if isinstance(c, dict)]
                if char_names:
                    anchor_parts.append(f"- 已识别关键人物: {', '.join(char_names)}")
            if 'world_type' in prior_analysis:
                anchor_parts.append(f"- 世界观类型: {prior_analysis['world_type']}")
        
        return "\n".join(anchor_parts)
    
    def _select_sample_chapters(
        self,
        chapters: List[ChapterInfo],
        count: int
    ) -> List[ChapterInfo]:
        """
        选择样本章节（小说专用策略）
        
        策略：
        - 开篇精读（50%）：建立人物、世界观、故事起点
        - 中段抽样（25%）：情节发展、冲突升级
        - 结尾细读（25%）：高潮、结局走向
        """
        if len(chapters) <= count:
            return chapters
        
        total = len(chapters)
        
        # 小说专用分配比例：开篇50% + 中段25% + 结尾25%
        head_count = int(count * 0.5)  # 开篇重要，多采样
        middle_count = int(count * 0.25)
        tail_count = count - head_count - middle_count
        
        # 开篇：前 N 章（人物出场、世界观建立）
        head = chapters[:head_count]
        
        # 中段：均匀抽样（情节发展）
        middle_start = int(total * 0.3)
        middle_end = int(total * 0.7)
        if middle_count > 0 and middle_end > middle_start:
            middle_step = max(1, (middle_end - middle_start) // middle_count)
            middle = [chapters[i] for i in range(middle_start, middle_end, middle_step)][:middle_count]
        else:
            middle = []
        
        # 结尾：最后 N 章（高潮、结局）
        tail = chapters[-tail_count:] if tail_count > 0 else []
        
        selected = head + middle + tail
        
        logger.info(f"📚 小说采样: 开篇{len(head)}章 + 中段{len(middle)}章 + 结尾{len(tail)}章 = {len(selected)}章")
        
        return selected
    
    def _build_chapter_summary(
        self,
        chapters: List[ChapterInfo],
        max_words_per_chapter: int = 800
    ) -> str:
        """
        构建章节摘要文本（语义边界切分）
        
        策略：
        - 不在对话中间截断
        - 不在句子中间截断
        - 优先在段落结束处切分
        """
        summaries = []
        for ch in chapters:
            header = f"【第{ch.number}章 {ch.title}】"
            if ch.content:
                content = self._smart_truncate(ch.content, max_words_per_chapter)
                summaries.append(f"{header}\n{content}")
            else:
                summaries.append(header)
        
        return "\n\n".join(summaries)
    
    def _smart_truncate(self, text: str, max_length: int) -> str:
        """
        智能截断文本（语义边界优先）
        
        优先级：段落结束 > 句号结束 > 逗号 > 强制截断
        """
        if len(text) <= max_length:
            return text
        
        # 在max_length附近寻找最佳切分点
        search_start = int(max_length * 0.8)  # 从80%位置开始找
        search_text = text[search_start:max_length + 100]  # 允许少量超出
        
        # 优先级切分点
        cut_points = [
            ('\n\n', '段落'),      # 段落结束
            ('。', '句号'),       # 中文句号
            ('。"', '对话结束'),   # 对话结束
            ('”', '引号结束'),   # 引号结束
            ('！', '感叹号'),     # 感叹号
            ('？', '问号'),       # 问号
            ('，', '逗号'),       # 逗号（次优先）
        ]
        
        for marker, name in cut_points:
            pos = search_text.rfind(marker)
            if pos != -1:
                cut_pos = search_start + pos + len(marker)
                return text[:cut_pos].rstrip() + "..."
        
        # 实在找不到，强制截断
        return text[:max_length] + "..."
    
    async def _call_llm_with_retry(
        self,
        prompt: str,
        task_type: TaskType,
        max_retries: int = 3
    ) -> str:
        """
        带重试的LLM调用
        
        实现指数退避策略
        """
        messages = [
            {"role": "system", "content": "你是一个专业的小说分析助手，擅长从文本中提取结构化信息。请始终以有效的JSON格式输出结果。"},
            {"role": "user", "content": prompt}
        ]
        
        last_error = None
        for attempt in range(max_retries):
            try:
                result = await asyncio.wait_for(
                    self.llm.chat(
                        messages=messages,
                        task_type=task_type,
                        temperature=0.3,  # 低温度保证一致性
                        max_tokens=4000,
                        timeout=self.LLM_REQUEST_TIMEOUT_SECONDS,
                    ),
                    timeout=self.LLM_REQUEST_TIMEOUT_SECONDS + 5,
                )
                return result
            except Exception as e:
                last_error = e
                wait_time = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                logger.warning(f"LLM调用失败(尝试 {attempt + 1}/{max_retries}): {e}，{wait_time}秒后重试")
                await asyncio.sleep(wait_time)
        
        raise Exception(f"LLM调用失败，已重试{max_retries}次: {last_error}")
    
    async def _call_qwen_long(
        self,
        prompt: str,
        max_retries: int = 3
    ) -> str:
        """
        调用阿里云 qwen-long 模型（用于汇总分析）
        
        支持超长输入（1000万tokens）
        """
        messages = [
            {"role": "system", "content": "你是一个专业的小说分析助手，擅长从大量文本中提取结构化信息。请始终以有效的JSON格式输出结果。"},
            {"role": "user", "content": prompt}
        ]
        
        last_error = None
        for attempt in range(max_retries):
            try:
                logger.info(
                    "🚀 开始调用 qwen-long | 输入: %s字 | 尝试: %s/%s",
                    len(prompt),
                    attempt + 1,
                    max_retries,
                )
                content = await asyncio.wait_for(
                    self.llm.chat(
                        messages=messages,
                        model="qwen-long",
                        temperature=0.3,
                        max_tokens=8000,
                        timeout=self.QWEN_LONG_REQUEST_TIMEOUT_SECONDS,
                    ),
                    timeout=self.QWEN_LONG_REQUEST_TIMEOUT_SECONDS + 5,
                )

                logger.info(f"✅ qwen-long调用成功 | 输入: {len(prompt)}字 | 输出: {len(content)}字")
                return content
                
            except Exception as e:
                last_error = e
                wait_time = 2 ** attempt
                logger.warning(f"qwen-long调用失败(尝试 {attempt + 1}/{max_retries}): {e}，{wait_time}秒后重试")
                await asyncio.sleep(wait_time)
        
        raise Exception(f"qwen-long调用失败，已重试{max_retries}次: {last_error}")
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """
        解析LLM的JSON响应
        
        处理可能的格式问题
        """
        # 尝试直接解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        
        # 尝试提取JSON块
        import re
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # 尝试提取花括号内容
        brace_match = re.search(r'\{[\s\S]*\}', response)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass
        
        # 返回原始文本包装
        logger.warning("无法解析JSON响应，返回原始文本")
        return {"raw_response": response, "parse_error": True}
    
    # ==================== 快速分析方法 ====================
    
    async def quick_analyze(
        self,
        chapters: List[ChapterInfo]
    ) -> Dict[str, Any]:
        """
        快速分析（只提取关键信息）
        
        用于预览和快速判断
        """
        # 只取前5章分析
        samples = chapters[:5]
        content = self._build_chapter_summary(samples, 500)
        
        prompt = f"""请快速分析以下小说开头，提取关键信息。

【小说开头】
{content}

请以JSON格式简要输出：
{{
    "genre": "类型判断",
    "main_character": "主角姓名",
    "setting": "背景设定（20字）",
    "initial_conflict": "初始冲突（30字）",
    "writing_style": "风格描述（20字）",
    "quality_assessment": "质量评估（优秀/良好/一般/较差）"
}}"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        return self._parse_json_response(result)
    
    # ==================== 快速分析方法 ====================
    
    async def quick_analyze(
        self,
        chapters: List[ChapterInfo]
    ) -> Dict[str, Any]:
        """
        快速分析（只提取关键信息）
        
        用于预览和快速判断
        """
        # 只取前5章分析
        samples = chapters[:5]
        content = self._build_chapter_summary(samples, 500)
        
        prompt = f"""请快速分析以下小说开头，提取关键信息。

【小说开头】
{content}

请以JSON格式简要输出：
{{
    "genre": "类型判断",
    "main_character": "主角姓名",
    "setting": "背景设定（20字）",
    "initial_conflict": "初始冲突（30字）",
    "writing_style": "风格描述（20字）",
    "quality_assessment": "质量评估（优秀/良好/一般/较差）"
}}"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        return self._parse_json_response(result)
    
    # ==================== 快速分析方法 ====================
    
    async def quick_analyze(
        self,
        chapters: List[ChapterInfo]
    ) -> Dict[str, Any]:
        """
        快速分析（只提取关键信息）
        
        用于预览和快速判断
        """
        # 只取前5章分析
        samples = chapters[:5]
        content = self._build_chapter_summary(samples, 500)
        
        prompt = f"""请快速分析以下小说开头，提取关键信息。

【小说开头】
{content}

请以JSON格式简要输出：
{{
    "genre": "类型判断",
    "main_character": "主角姓名",
    "setting": "背景设定（20字）",
    "initial_conflict": "初始冲突（30字）",
    "writing_style": "风格描述（20字）",
    "quality_assessment": "质量评估（优秀/良好/一般/较差）"
}}"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        return self._parse_json_response(result)
    
    # ==================== 快速分析方法 ====================
    
    async def quick_analyze(
        self,
        chapters: List[ChapterInfo]
    ) -> Dict[str, Any]:
        """
        快速分析（只提取关键信息）
        
        用于预览和快速判断
        """
        # 只取前5章分析
        samples = chapters[:5]
        content = self._build_chapter_summary(samples, 500)
        
        prompt = f"""请快速分析以下小说开头，提取关键信息。

【小说开头】
{content}

请以JSON格式简要输出：
{{
    "genre": "类型判断",
    "main_character": "主角姓名",
    "setting": "背景设定（20字）",
    "initial_conflict": "初始冲突（30字）",
    "writing_style": "风格描述（20字）",
    "quality_assessment": "质量评估（优秀/良好/一般/较差）"
}}"""

        result = await self._call_llm_with_retry(prompt, TaskType.BOOK_ANALYSIS)
        return self._parse_json_response(result)


