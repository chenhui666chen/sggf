from __future__ import annotations

import json
import logging
import re
from typing import Dict, Any, List, Optional
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.models.book_parser import BookSource, BookChapter, BookAnalysis
from app.models.project import Project, Chapter
from app.models.setting import SettingCollection, SettingItem
from app.models.character import Character
from app.models.user import User
from app.services.chapter_adaptation_assets import attach_cross_media_adaptation_hints
from app.services.character_parser import (
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
    infer_story_stance_from_text_evidence,
)
from app.services.setting_templates import get_hierarchy_config_json
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

from app.services.book_parser.project_bridge_pkg._constants import (
    ANALYSIS_TO_COLLECTION,
    STRUCTURED_MEMORY_LIMITS,
    CANONICAL_STORY_STANCES,
    CANONICAL_ROLE_POSITIONS,
    GENERIC_ROLE_POSITIONS,
)

class BuildersMixin:
    @staticmethod
    def _stringify_style_value(value: Any) -> str:
        """将风格字段规范成适合展示的单行文本。"""
        if value is None:
            return ""
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
            return "、".join(items)
        return str(value).strip()

    def _format_style_sentence(self, value: Any) -> str:
        """兼容新旧风格 schema 的句式描述。"""
        if isinstance(value, dict):
            parts: List[str] = []
            avg_length = self._stringify_style_value(value.get("avg_length"))
            if avg_length:
                parts.append(f"平均句长约{avg_length}字")
            complexity = self._stringify_style_value(value.get("complexity"))
            if complexity:
                parts.append(f"复杂度{complexity}")
            dominant_style = self._stringify_style_value(
                value.get("dominant_style") or value.get("style")
            )
            if dominant_style:
                parts.append(dominant_style)
            return "，".join(parts)

        return self._stringify_style_value(value)

    def _format_style_description(self, value: Any) -> str:
        """兼容字符串与对象两种描写风格格式。"""
        if isinstance(value, dict):
            parts: List[str] = []
            field_pairs = [
                ("场景", value.get("scene_description")),
                ("人物", value.get("character_description")),
                ("动作", value.get("action_description")),
                ("心理", value.get("psychological_description")),
            ]
            for label, raw_value in field_pairs:
                text_value = self._stringify_style_value(raw_value)
                if text_value:
                    parts.append(f"{label}：{text_value}")
            return "；".join(parts)

        return self._stringify_style_value(value)

    def _format_dialogue_ratio(self, value: Any) -> str:
        """将对话占比格式化为易读文本。"""
        if value is None or value == "":
            return ""

        try:
            ratio = float(value)
        except (TypeError, ValueError):
            return self._stringify_style_value(value)

        if ratio <= 1:
            ratio *= 100
        return f"对话占比约{ratio:.0f}%"

    def _build_style_reference_entries(self, style_content: Dict[str, Any]) -> List[tuple[str, str]]:
        """将风格分析结果归一化为可复用的条目列表。"""
        if not style_content:
            return []

        language_features = style_content.get("language_features")
        if not isinstance(language_features, dict):
            language_features = {}

        vocabulary_level = self._stringify_style_value(
            language_features.get("vocabulary_level") or style_content.get("vocabulary_features")
        )
        sentence_style = self._format_style_sentence(
            language_features.get("sentence_style") or style_content.get("sentence_style")
        )
        rhetoric = self._stringify_style_value(language_features.get("rhetoric"))
        dialogue_style = self._stringify_style_value(language_features.get("dialogue_style"))
        dialogue_ratio = self._format_dialogue_ratio(style_content.get("dialogue_ratio"))

        language_parts: List[str] = []
        if vocabulary_level:
            language_parts.append(f"用词：{vocabulary_level}")
        if sentence_style:
            language_parts.append(f"句式：{sentence_style}")
        if rhetoric:
            language_parts.append(f"修辞：{rhetoric}")
        if dialogue_style:
            language_parts.append(f"对话：{dialogue_style}")
        if dialogue_ratio:
            language_parts.append(dialogue_ratio)

        entries = [
            ("叙事视角", self._stringify_style_value(style_content.get("narrative_perspective"))),
            ("叙事风格", self._stringify_style_value(style_content.get("narrative_style"))),
            ("整体基调", self._stringify_style_value(style_content.get("tone"))),
            ("节奏特点", self._stringify_style_value(style_content.get("pacing"))),
            ("语言特点", "；".join(language_parts)),
            ("描写侧重", self._format_style_description(style_content.get("description_style"))),
            ("风格优势", self._stringify_style_value(style_content.get("strengths"))),
            ("独特标识", self._stringify_style_value(style_content.get("unique_features"))),
            ("类型惯例", self._stringify_style_value(style_content.get("genre_conventions"))),
            ("参考作者", self._stringify_style_value(style_content.get("similar_authors"))),
        ]

        return [(name, value) for name, value in entries if value]
    
    def _build_concept_text(self, analysis_map: Dict[str, BookAnalysis], book: BookSource) -> str:
        """构建故事概念文本（六部分标准格式 - 与创作模式一致）"""
        parts = []
        
        # 从情节分析提取概念信息
        plot_content = self._load_plot_content_with_fallback(analysis_map, book.id)
        worldview_content = self._load_analysis_content(analysis_map, 'worldview')
        concept_data = plot_content.get('concept', {}) if isinstance(plot_content, dict) else {}
        
        # 1. 一句话卖点（Logline）
        parts.append("**一句话卖点（Logline）**")
        logline = concept_data.get('logline', '')
        if not logline:
            main_plot = plot_content.get('main_plot', '') if isinstance(plot_content, dict) else ''
            logline = main_plot[:60] + '...' if len(main_plot) > 60 else main_plot
        parts.append(logline or f"《{book.title}》的故事")
        parts.append("")
        
        # 2. 日志标题（短标题）
        parts.append("**日志标题（短标题）**")
        short_title = concept_data.get('short_title', '') or book.title[:10]
        parts.append(short_title)
        parts.append("")
        
        # 3. 概念摘要（80–150字）
        parts.append("**概念摘要**")
        summary = concept_data.get('summary', '')
        if not summary and isinstance(plot_content, dict):
            summary = plot_content.get('main_plot', '')[:150]
        parts.append(summary or f"基于《{book.title}》的创作项目")
        parts.append("")
        
        # 4. 题材与流派
        parts.append("**题材与流派**")
        genre = concept_data.get('genre', '') or book.genre or '通用题材'
        sub_genre = concept_data.get('sub_genre', '')
        genre_text = f"{genre} / {sub_genre}" if sub_genre else genre
        parts.append(genre_text)
        parts.append("")
        
        # 5. 核心标签
        parts.append("**核心标签**")
        core_tags = concept_data.get('core_tags', [])
        if core_tags:
            parts.append("、".join(core_tags))
        else:
            parts.append("待补充")
        parts.append("")
        
        # 6. 核心冲突与情感基调
        parts.append("**核心冲突与情感基调**")
        core_conflict = concept_data.get('core_conflict', '')
        emotional_tone = concept_data.get('emotional_tone', '')
        
        if core_conflict:
            parts.append(f"核心冲突：{core_conflict}")
        if emotional_tone:
            parts.append(f"情感基调：{emotional_tone}")
        if not core_conflict and not emotional_tone:
            # 回退：从冲突列表提取
            conflicts = plot_content.get('conflicts', []) if isinstance(plot_content, dict) else []
            if conflicts:
                parts.append(f"核心冲突：{conflicts[0].get('description', '待分析')}")
        parts.append("")
        
        # 7. 世界观高概摘要（可简略）
        if isinstance(worldview_content, dict) and worldview_content.get('world_description'):
            parts.append("**世界观高概摘要**")
            parts.append(worldview_content['world_description'][:200])
            parts.append("")

        style_entries = self._build_style_reference_entries(
            self._load_analysis_content(analysis_map, 'style')
        )
        if style_entries:
            parts.append("**写作风格参考**")
            for name, value in style_entries[:6]:
                parts.append(f"- {name}：{value}")
            parts.append("")
        
        return '\n'.join(parts) if parts else f"# {book.title}\n\n基于《{book.title}》的创作项目"
    
    def _build_world_setting_text(self, analysis_map: Dict[str, BookAnalysis]) -> str:
        """构建世界观设定文本"""
        content = self._load_analysis_content(analysis_map, 'worldview')
        if not isinstance(content, dict) or not content:
            return ""
        
        parts = ["# 世界观设定", ""]
        
        # 世界类型
        if content.get('world_type'):
            parts.append(f"## 世界类型")
            parts.append(content['world_type'])
            parts.append("")
        
        # 世界描述
        if content.get('world_description'):
            parts.append(f"## 世界概述")
            parts.append(content['world_description'])
            parts.append("")
        
        # 力量体系
        power_systems = content.get('power_systems', [])
        if power_systems:
            parts.append("## 力量体系")
            for sys in power_systems:
                parts.append(f"### {sys.get('name', '未命名体系')}")
                if sys.get('description'):
                    parts.append(sys['description'])
                if sys.get('levels'):
                    parts.append(f"等级：{' → '.join(sys['levels'])}")
                parts.append("")
        
        # 重要地点
        locations = content.get('locations', [])[:10]
        if locations:
            parts.append("## 重要地点")
            for loc in locations:
                parts.append(f"### {loc.get('name', '未命名')}")
                if loc.get('type'):
                    parts.append(f"类型：{loc['type']}")
                if loc.get('description'):
                    parts.append(loc['description'])
                parts.append("")
        
        # 势力
        factions = content.get('factions', [])[:10]
        if factions:
            parts.append("## 主要势力")
            for faction in factions:
                parts.append(f"### {faction.get('name', '未命名')}")
                if faction.get('type'):
                    parts.append(f"类型：{faction['type']}")
                if faction.get('description'):
                    parts.append(faction['description'])
                parts.append("")
        
        return '\n'.join(parts)
    
    def _build_characters_text(self, analysis_map: Dict[str, BookAnalysis]) -> str:
        """生成与人物扩展一致的人物档案文本。"""
        content = self._load_analysis_content(analysis_map, 'characters')
        if not isinstance(content, dict) or not content:
            return ""

        def raw_text(value: Any, separator: str = "、") -> str:
            if value is None:
                return ""
            if isinstance(value, list):
                items = [raw_text(v, separator=separator) for v in value]
                items = [item for item in items if item]
                return separator.join(items)
            if isinstance(value, dict):
                return ""
            return str(value).strip()

        def is_placeholder_text(value: Any, *, allow_not_mentioned: bool = False) -> bool:
            text = raw_text(value)
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

        def normalize_text(value: Any, *, allow_not_mentioned: bool = False, separator: str = "、") -> str:
            if isinstance(value, list):
                items = [
                    normalize_text(item, allow_not_mentioned=allow_not_mentioned, separator=separator)
                    for item in value
                ]
                items = [item for item in items if item]
                return separator.join(list(dict.fromkeys(items)))

            text = raw_text(value, separator=separator)
            if is_placeholder_text(text, allow_not_mentioned=allow_not_mentioned):
                return ""
            return text

        def pick_first(*values: Any, allow_not_mentioned: bool = False, separator: str = "、") -> str:
            for value in values:
                text_value = normalize_text(
                    value,
                    allow_not_mentioned=allow_not_mentioned,
                    separator=separator,
                )
                if text_value:
                    return text_value
            return ""

        def truncate_text(value: str, limit: int = 36) -> str:
            text = normalize_text(value)
            if not text:
                return ""
            if len(text) <= limit:
                return text
            return text[: limit - 3].rstrip("，。；; ") + "..."

        def extract_action_phrase(text: str) -> str:
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
                    return truncate_text(match.group(1), 28)
            return ""

        def resolve_character_display_fields(
            char_data: Dict[str, Any],
            *,
            default_story_stance: str,
            default_role_position: str,
        ) -> tuple[str, str]:
            relation_to_main = pick_first(char_data.get('relationship_to_main'))
            role_position = self._normalize_role_position_value(
                char_data.get('role_position'),
                relationship_to_main=relation_to_main,
                fallback=default_role_position,
            )
            story_stance = self._infer_story_stance(
                explicit_stance=char_data.get('story_stance'),
                role_position=role_position,
                relationship_to_main=relation_to_main,
                fallback=default_story_stance,
                additional_texts=[
                    char_data.get('description'),
                    char_data.get('background_status'),
                    char_data.get('mainline_role'),
                    char_data.get('growth_direction'),
                ],
            )
            return story_stance, role_position

        def infer_motivation(description: str, mainline_role: str, relation_to_main: str, role_text: str) -> str:
            action_phrase = extract_action_phrase("；".join(filter(None, [description, mainline_role, relation_to_main])))
            if action_phrase:
                return action_phrase
            if relation_to_main:
                return f"围绕{truncate_text(relation_to_main, 18)}作出关键行动选择"
            if mainline_role:
                return f"其个人目标与{truncate_text(mainline_role, 18)}直接相关"
            if role_text == "主角":
                return "主动追索主线真相并推动事件进展"
            if role_text == "对手":
                return "维护自身立场并阻断主角推进"
            return "围绕主线冲突作出选择并影响局势"

        def infer_abilities(description: str, relation_to_main: str, role_text: str) -> str:
            source = "；".join(filter(None, [description, relation_to_main]))
            ability_rules = [
                (("工程师", "技术", "程序", "黑客", "接口", "系统", "数据分析"), "技术分析、系统操作与信息处理"),
                (("研究员", "科学家", "实验"), "研究分析与实验推进"),
                (("医生", "医师", "诊所", "治疗"), "医疗救治与应急判断"),
                (("警察", "警员", "军", "特工", "队长", "执法", "安保"), "战术执行、追踪与正面压制"),
                (("记者", "调查员", "调查"), "调查取证与信息整合"),
                (("首领", "负责人", "指挥", "组织", "抵抗"), "组织协调、资源调度与行动策划"),
                (("觉醒", "异能", "能力"), "特殊能力运用与高风险行动"),
            ]
            for keywords, text in ability_rules:
                if any(keyword in source for keyword in keywords):
                    return text
            if role_text == "对手":
                return "资源调动与局势压制能力"
            return "与主线任务相关的执行与应变能力"

        def infer_limitation(description: str, relation_to_main: str, role_text: str) -> str:
            source = "；".join(filter(None, [description, relation_to_main]))
            if any(keyword in source for keyword in ("真相", "追查", "追寻", "调查", "复仇", "执念")):
                return "对目标投入过深，关键节点容易冒险"
            if any(keyword in source for keyword in ("威胁", "胁迫", "受制", "被迫")):
                return "受外部压力牵制，立场稳定性有限"
            if role_text == "对手":
                return "立场强硬，容易低估对手与变量"
            if role_text == "主角":
                return "情感与目标绑定过深，容易承担过高风险"
            return "受立场、资源或情绪牵制，行动存在代价"

        def infer_growth_direction(mainline_role: str, relation_to_main: str, role_text: str) -> str:
            if role_text == "主角":
                return "从被动卷入事件，到主动追查真相并承担核心抉择"
            if role_text == "对手":
                return "从单纯阻力角色，逐步成为主线价值冲突的关键对照"
            if relation_to_main:
                return f"从{truncate_text(relation_to_main, 16)}的位置出发，逐步影响主线走向"
            if mainline_role:
                return "随着主线推进，其立场与选择不断被重新定义"
            return "在主线冲突中完成立场与关系的调整"

        def infer_age_gender(description: str, background: str, relation_to_main: str) -> str:
            source = "；".join(filter(None, [description, background, relation_to_main]))
            age_value = ""
            gender_value = ""

            age_rules = [
                ("少女", "少女"),
                ("少年", "少年"),
                ("青年", "青年"),
                ("年轻", "青年"),
                ("中年", "中年"),
                ("老人", "老年"),
                ("奶奶", "老年"),
            ]
            gender_rules = [
                ("母亲", "女性"),
                ("姐姐", "女性"),
                ("妹妹", "女性"),
                ("女士", "女性"),
                ("奶奶", "女性"),
                ("父亲", "男性"),
                ("哥哥", "男性"),
                ("弟弟", "男性"),
                ("男孩", "男性"),
                ("女孩", "女性"),
            ]

            for keyword, value in age_rules:
                if keyword in source:
                    age_value = value
                    break
            for keyword, value in gender_rules:
                if keyword in source:
                    gender_value = value
                    break

            if age_value and gender_value:
                return f"{age_value}/{gender_value}"
            return age_value or gender_value

        def infer_appearance(description: str, background: str, personality: str) -> str:
            source = "；".join(filter(None, [description, background, personality]))
            rules = [
                (("工程师", "系统", "接口", "数据"), "气质冷静克制，带长期高压工作的疲惫感"),
                (("医生", "诊疗", "医疗"), "衣着整洁利落，举止带有职业性的克制感"),
                (("高层", "局长", "负责人", "首领"), "仪表严整，带有长期掌控局势的压迫感"),
                (("地下", "黑市", "抵抗"), "装束偏低调实用，神情警惕而锋利"),
                (("老人", "老周", "奶奶"), "带有岁月沉淀感，神情沉稳而略显疲惫"),
            ]
            for keywords, text in rules:
                if any(keyword in source for keyword in keywords):
                    return text
            return "外在特征以身份气质为主，缺少明确细节描写"

        def infer_worldview(description: str, background: str, motivation: str, story_stance: str, faction: str) -> str:
            source = "；".join(filter(None, [description, background, motivation, story_stance, faction]))
            if any(keyword in source for keyword in ("真相", "自由", "自主", "主权", "揭露", "反抗")):
                return "倾向真相优先与个体记忆自主"
            if any(keyword in source for keyword in ("稳定", "秩序", "系统", "控制")):
                return "倾向秩序优先，但在控制与伦理间摇摆"
            if any(keyword in source for keyword in ("救治", "保护", "守护", "修复")):
                return "重视生命伦理、修复与个体保护"
            if story_stance:
                return f"立场偏向{story_stance}"
            return "在生存、伦理与真相之间不断权衡"

        def build_mainline_clues(char_data: Dict[str, Any], description: str, relation_to_main: str) -> str:
            parts: List[str] = []
            first_appearance = char_data.get('first_appearance_chapter')
            appearance_count = char_data.get('appearance_count')
            if isinstance(first_appearance, int) and first_appearance > 0:
                parts.append(f"首次在第{first_appearance}章出场")
            if isinstance(appearance_count, int) and appearance_count > 0:
                parts.append(f"累计出场{appearance_count}章")
            if relation_to_main:
                parts.append(f"与主角关系：{truncate_text(relation_to_main, 18)}")
            if description:
                parts.append(f"关键事件指向：{truncate_text(description, 24)}")
            deduped = list(dict.fromkeys([part for part in parts if part]))
            return "；".join(deduped)

        relationship_map: Dict[str, List[str]] = {}
        for rel in (content.get('character_relationships', []) or []):
            char_a = normalize_text(rel.get('character1'))
            char_b = normalize_text(rel.get('character2'))
            if not char_a or not char_b:
                continue
            relation = normalize_text(rel.get('relationship'))
            description = normalize_text(rel.get('description'))
            detail_parts = []
            if relation:
                detail_parts.append(relation)
            if description and description != relation:
                detail_parts.append(description)
            detail = "，".join(detail_parts)
            line_a = f"{char_b}：{detail}" if detail else char_b
            line_b = f"{char_a}：{detail}" if detail else char_a
            relationship_map.setdefault(char_a, []).append(line_a)
            relationship_map.setdefault(char_b, []).append(line_b)

        def value_or_default(value: str) -> str:
            return normalize_text(value) or "待补充"

        def append_character_card(
            target: List[str],
            char_data: Dict[str, Any],
            story_stance_text: str,
            role_text: str,
        ) -> None:
            name = normalize_text(char_data.get('name')) or "待补充"
            age_gender = pick_first(char_data.get('age_gender'), char_data.get('age'), char_data.get('gender'))
            appearance = pick_first(char_data.get('appearance_anchor'))
            personality = pick_first(char_data.get('personality_anchor'))
            background = pick_first(char_data.get('background_status'))
            worldview = pick_first(char_data.get('worldview'))
            description = pick_first(char_data.get('description'))
            relation_to_main = pick_first(char_data.get('relationship_to_main'))
            mainline_role = pick_first(char_data.get('mainline_role'), description, relation_to_main)
            motivation = pick_first(char_data.get('motivation'))
            story_stance = story_stance_text or pick_first(char_data.get('story_stance'), allow_not_mentioned=True)
            faction = pick_first(char_data.get('faction'), allow_not_mentioned=True)
            abilities = pick_first(char_data.get('ability_outline'))
            limitation = pick_first(char_data.get('limitation'))
            growth_direction = pick_first(char_data.get('growth_direction'))
            mainline_clues = pick_first(char_data.get('mainline_clues'), separator="；")

            relationship_lines: List[str] = []
            if relation_to_main:
                relationship_lines.append(f"与主角：{relation_to_main}")
            relationship_lines.extend(relationship_map.get(name, []))
            relationship_text = "；".join(list(dict.fromkeys([line for line in relationship_lines if line]))) or "待补充"

            if not motivation:
                motivation = infer_motivation(description, mainline_role, relation_to_main, role_text)
            if not age_gender:
                age_gender = infer_age_gender(description, background, relation_to_main)
            if not appearance:
                appearance = infer_appearance(description, background, personality)
            if not worldview:
                worldview = infer_worldview(description, background, motivation, story_stance, faction)
            if not abilities:
                abilities = infer_abilities(description, relation_to_main, role_text)
            if not limitation:
                limitation = infer_limitation(description, relation_to_main, role_text)
            if not growth_direction:
                growth_direction = infer_growth_direction(mainline_role, relation_to_main, role_text)
            if not mainline_clues:
                mainline_clues = build_mainline_clues(char_data, description or mainline_role, relation_to_main)

            target.append(f"### 【姓名】：{name}")
            target.append("")
            target.append(f"【年龄/性别】：{value_or_default(age_gender)}")
            target.append("")
            target.append(f"【故事立场】：{value_or_default(story_stance)}")
            target.append("")
            target.append(f"【角色定位】：{value_or_default(role_text)}")
            target.append("")
            target.append(f"【所属势力】：{value_or_default(faction)}")
            target.append("")
            target.append(f"【外貌锚点】：{value_or_default(appearance)}")
            target.append("")
            target.append(
                f"【性格锚点】：{value_or_default(_build_personality_anchor_text(personality, worldview))}"
            )
            target.append("")
            target.append(f"【背景/当前处境】：{value_or_default(background)}")
            target.append("")
            target.append(f"【核心动机】：{value_or_default(motivation)}")
            target.append("")
            target.append(
                f"【能力与限制】：{value_or_default(_build_ability_and_limit_text(abilities, limitation))}"
            )
            target.append("")
            target.append(f"【关键关系】：{value_or_default(relationship_text)}")
            target.append("")
            target.append(
                f"【主线绑定】：{value_or_default(_build_mainline_binding_text(mainline_role, mainline_clues))}"
            )
            target.append("")
            target.append(f"【成长方向】：{value_or_default(growth_direction)}")
            target.append("")
            target.append("---")
            target.append("")

        parts: List[str] = []
        characters = self._get_character_entries(content)

        groups: Dict[str, List[Any]] = {
            "主角阵营": [],
            "对手阵营": [],
            "支持角色": [],
            "中立角色": [],
            "摇摆角色": [],
        }

        for char in characters:
            is_primary = self._is_primary_character_entry(char)
            story_stance, role_text = resolve_character_display_fields(
                char,
                default_story_stance='',
                default_role_position='主线角色' if is_primary else '功能角色',
            )
            if story_stance == "主角方":
                if role_text == "主角":
                    groups["主角阵营"].append((char, story_stance, role_text))
                else:
                    groups["支持角色"].append((char, story_stance, role_text or "盟友"))
            elif story_stance == "反派方":
                groups["对手阵营"].append((char, story_stance, role_text or "对手"))
            elif story_stance == "中立方":
                groups["中立角色"].append((char, story_stance, role_text or "中立角色"))
            elif story_stance == "亦正亦邪":
                groups["摇摆角色"].append((char, story_stance, role_text or "摇摆角色"))
            else:
                groups["支持角色"].append((char, story_stance, role_text or "盟友"))

        for group_name, entries in groups.items():
            if not entries:
                continue
            parts.append(f"## {group_name}")
            parts.append("")
            for char_data, story_stance_text, role_text in entries:
                append_character_card(parts, char_data, story_stance_text, role_text)

        return "\n".join(parts).strip()

    def _build_plot_outline_text_legacy(self, analysis_map: Dict[str, BookAnalysis], book_id: int) -> str:
        """旧版总览式情节大纲生成逻辑，保留仅供定位对比。"""
        content = self._load_plot_content_with_fallback(analysis_map, book_id)
        if not isinstance(content, dict) or not content:
            return ""

        def normalize_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, list):
                items = [str(v).strip() for v in value if str(v).strip()]
                return "、".join(items)
            return str(value).strip()

        def format_arc_brief(arc: Any) -> str:
            if not isinstance(arc, dict):
                return normalize_text(arc) or "待补充"
            name = normalize_text(arc.get('name')) or "待补充"
            desc = normalize_text(arc.get('description'))
            chapters = arc.get('chapters') or []
            meta_parts = []
            if isinstance(chapters, list) and len(chapters) >= 2:
                meta_parts.append(f"第{chapters[0]}-{chapters[1]}章")
            arc_type = normalize_text(arc.get('type'))
            if arc_type:
                meta_parts.append(arc_type)
            if meta_parts:
                name = f"{name}（{' / '.join(meta_parts)}）"
            if desc:
                return f"{name}：{desc}"
            return name

        parts: List[str] = []

        main_plot = normalize_text(content.get('main_plot'))
        if not main_plot:
            main_plot = normalize_text(content.get('concept', {}).get('summary')) or normalize_text(content.get('concept', {}).get('logline'))
        parts.append("1. 故事概述")
        parts.append(main_plot if main_plot else "待补充")
        parts.append("")

        plot_arcs = content.get('plot_arcs', []) or []
        parts.append("2. 情节发展")
        if plot_arcs:
            for arc in plot_arcs:
                parts.append(f"- {format_arc_brief(arc)}")
        else:
            parts.append("待补充")
        parts.append("")

        turning_points = content.get('turning_points', []) or []
        parts.append("3. 重要转折点")
        if turning_points:
            for tp in turning_points[:8]:
                chapter = normalize_text(tp.get('chapter')) if isinstance(tp, dict) else ""
                event = normalize_text(tp.get('event')) if isinstance(tp, dict) else ""
                significance = normalize_text(tp.get('significance')) if isinstance(tp, dict) else ""
                title = f"第{chapter}章" if chapter else "关键节点"
                detail_parts = [item for item in [event, significance] if item]
                detail = "，".join(detail_parts)
                parts.append(f"- {title}：{detail}" if detail else f"- {title}")
        else:
            parts.append("待补充")
        parts.append("")

        parts.append("4. 高潮设计")
        climax_lines = []
        for arc in plot_arcs:
            if not isinstance(arc, dict):
                continue
            arc_type = normalize_text(arc.get('type'))
            arc_name = normalize_text(arc.get('name'))
            if "高潮" in arc_type or "高潮" in arc_name or "决战" in arc_name:
                climax_lines.append(f"- {format_arc_brief(arc)}")
        if not climax_lines and turning_points:
            for tp in turning_points[-2:]:
                chapter = normalize_text(tp.get('chapter')) if isinstance(tp, dict) else ""
                event = normalize_text(tp.get('event')) if isinstance(tp, dict) else ""
                title = f"第{chapter}章" if chapter else "关键节点"
                detail = event or (normalize_text(tp.get('significance')) if isinstance(tp, dict) else "")
                climax_lines.append(f"- {title}：{detail}" if detail else f"- {title}")
        if climax_lines:
            parts.extend(climax_lines)
        else:
            parts.append("待补充")
        parts.append("")

        parts.append("5. 结局规划")
        ending_lines = []
        for arc in plot_arcs:
            if not isinstance(arc, dict):
                continue
            arc_type = normalize_text(arc.get('type'))
            arc_name = normalize_text(arc.get('name'))
            if any(keyword in arc_type for keyword in ["结局", "收尾", "终局", "尾声"]) or any(keyword in arc_name for keyword in ["结局", "收尾", "终局", "尾声"]):
                ending_lines.append(f"- {format_arc_brief(arc)}")
        if not ending_lines:
            chapter_summaries = content.get('chapter_summaries') or []
            if chapter_summaries:
                last_summary = normalize_text(chapter_summaries[-1])
                if last_summary:
                    ending_lines.append(f"- {last_summary}")
        if ending_lines:
            parts.extend(ending_lines)
        else:
            parts.append("待补充")

        return "\n".join(parts).strip()
