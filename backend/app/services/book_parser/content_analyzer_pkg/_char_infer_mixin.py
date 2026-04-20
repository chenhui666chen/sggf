from __future__ import annotations

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
from ..chapter_splitter import ChapterInfo, ChapterType

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
    CHAPTER_SUMMARY = "chapter_summary"


@dataclass
class ChapterSummary:
    chapter_index: int
    title: str
    summary: str
    characters: List[str]
    key_events: List[str]


@dataclass
class AnalysisResult:
    analysis_type: AnalysisType
    content: Dict[str, Any]
    confidence: float
    chapter_summaries: Optional[List[ChapterSummary]] = None

class CharInferMixin:
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

