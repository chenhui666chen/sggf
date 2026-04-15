"""
人物卡文本解析器

解析AI生成的文本格式人物卡，提取结构化字段，
并同步到数据库的characters表中。
"""
import json
import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from app.services.character_runtime_context import (
    build_character_relations_payload,
    extract_character_relation_items,
)
from app.services.story_text_utils import (
    extract_preferred_character_name,
    normalize_story_text,
)

logger = logging.getLogger("uvicorn.error")

CANONICAL_STORY_STANCES = ("主角方", "反派方", "中立方", "亦正亦邪")
_EXPLICIT_STORY_STANCE_PATTERNS = (
    re.compile(r"(?:\*\*)?【故事立场】(?:\*\*)?[：:]\s*(主角方|反派方|中立方|亦正亦邪)"),
    re.compile(r"故事立场[：:]\s*(主角方|反派方|中立方|亦正亦邪)"),
)
_PRO_STORY_STANCE_PHRASES = (
    "从敌对到生死相托的战友",
    "互不背叛",
    "投资者与引路人",
    "镜像与救赎",
    "功能性伙伴",
    "精神导师",
    "现实导师",
    "核心护卫",
    "信任圈内",
    "向导与组织接口",
    "技术协作者",
    "数据遗产继承者",
    "生死相托",
)
_ANTI_STORY_STANCE_PHRASES = (
    "主要追捕者",
    "武力对抗符号",
    "学术讨伐",
    "天道正义围剿",
    "秩序暴力",
    "污名为",
)
_NEUTRAL_STORY_STANCE_PHRASES = (
    "记忆崩解受害者",
    "旁观者",
    "游离于多方",
)
_AMBIGUOUS_STORY_STANCE_PHRASES = (
    "立场游移",
    "两面下注",
)


def normalize_character_name(name: str) -> str:
    if not name:
        return ""
    value = extract_preferred_character_name(str(name).strip()) or str(name).strip()
    value = re.sub(r'^[\"“”\'‘’「」『』]+|[\"“”\'‘’「」『』]+$', '', value).strip()
    value = re.sub(r'[（(].*?[）)]', '', value)
    value = value.replace('昵称', '')
    value = re.sub(r'[【】\[\]<>《》]', '', value)
    value = re.sub(r'\s+', '', value).strip()
    return value


def normalize_story_stance_label(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if text in CANONICAL_STORY_STANCES:
        return text
    if "亦正亦邪" in text or any(phrase in text for phrase in _AMBIGUOUS_STORY_STANCE_PHRASES):
        return "亦正亦邪"
    if any(keyword in text for keyword in ("中立", "旁观", "游离", "受害者")):
        return "中立方"
    if any(keyword in text for keyword in ("反派", "对手", "敌对", "宿敌", "追捕", "追杀", "围剿", "打压", "污名", "猎杀", "夺取")):
        return "反派方"
    if any(keyword in text for keyword in ("主角", "主角方", "主角阵营", "盟友", "战友", "同伴", "队友", "伙伴", "导师", "引路人", "护卫", "守护", "协作者", "向导", "助力")):
        return "主角方"
    return None


def extract_story_stance_from_text(text: Any) -> Optional[str]:
    normalized_text = str(text or "").strip()
    if not normalized_text:
        return None
    for pattern in _EXPLICIT_STORY_STANCE_PATTERNS:
        match = pattern.search(normalized_text)
        if match:
            return normalize_story_stance_label(match.group(1))
    return None


def infer_story_stance_from_text_evidence(*texts: Any) -> Optional[str]:
    cleaned_texts = [str(text or "").strip() for text in texts if str(text or "").strip()]
    if not cleaned_texts:
        return None

    for text in cleaned_texts:
        explicit = extract_story_stance_from_text(text)
        if explicit:
            return explicit

    merged = "\n".join(cleaned_texts)

    if any(phrase in merged for phrase in _AMBIGUOUS_STORY_STANCE_PHRASES):
        return "亦正亦邪"
    if any(phrase in merged for phrase in _PRO_STORY_STANCE_PHRASES):
        return "主角方"
    if any(phrase in merged for phrase in _ANTI_STORY_STANCE_PHRASES):
        return "反派方"
    if any(phrase in merged for phrase in _NEUTRAL_STORY_STANCE_PHRASES):
        return "中立方"

    for text in cleaned_texts:
        if len(text) <= 40:
            normalized = normalize_story_stance_label(text)
            if normalized:
                return normalized

    return None


def _merge_parsed_character(base: "ParsedCharacter", incoming: "ParsedCharacter") -> "ParsedCharacter":
    for field_name in (
        "age",
        "gender",
        "role",
        "role_position",
        "faction",
        "importance_level",
        "appearance",
        "personality",
        "background",
        "worldview",
        "motivation",
        "abilities",
        "limitation",
        "mainline_role",
        "growth_direction",
        "relationships",
        "mainline_clues",
    ):
        cur = getattr(base, field_name, None)
        nxt = getattr(incoming, field_name, None)
        if nxt is None or nxt == "":
            continue
        if cur is None or cur == "":
            setattr(base, field_name, nxt)
            continue
        if isinstance(cur, str) and isinstance(nxt, str) and len(nxt) > len(cur):
            setattr(base, field_name, nxt)

    base_norm = normalize_character_name(base.name)
    incoming_norm = normalize_character_name(incoming.name)
    if base_norm and incoming_norm and base_norm == incoming_norm:
        if len(incoming.name.strip()) < len(base.name.strip()):
            base.name = incoming.name.strip()
    return base


def _clean_character_card_value(value: Any) -> str:
    return str(value or "").strip()


def _build_compound_field_text(items: List[tuple[str, Any]], default: str = "") -> str:
    lines: List[str] = []
    seen = set()
    for prefix, value in items:
        cleaned = _clean_character_card_value(value)
        if not cleaned:
            continue
        rendered = cleaned
        if prefix and not (
            cleaned.startswith(f"{prefix}：")
            or cleaned.startswith(f"{prefix}:")
        ):
            rendered = f"{prefix}：{cleaned}"
        if rendered in seen:
            continue
        seen.add(rendered)
        lines.append(rendered)
    return "\n".join(lines) if lines else default


def _build_personality_anchor_text(personality: Any, worldview: Any, default: str = "") -> str:
    return _build_compound_field_text(
        [
            ("性格", personality),
            ("价值倾向", worldview),
        ],
        default=default,
    )


def _build_ability_and_limit_text(abilities: Any, limitation: Any, default: str = "") -> str:
    return _build_compound_field_text(
        [
            ("能力", abilities),
            ("限制", limitation),
        ],
        default=default,
    )


def _build_mainline_binding_text(mainline_role: Any, mainline_clues: Any, default: str = "") -> str:
    return _build_compound_field_text(
        [
            ("剧情职责", mainline_role),
            ("关联线索", mainline_clues),
        ],
        default=default,
    )


def _extract_prefixed_character_value(text: Any, prefixes: tuple[str, ...]) -> Optional[str]:
    content = _clean_character_card_value(text)
    if not content:
        return None
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        for prefix in prefixes:
            for marker in ("：", ":"):
                token = f"{prefix}{marker}"
                if stripped.startswith(token):
                    value = stripped[len(token):].strip()
                    if value:
                        return value
    return None


@dataclass
class ParsedCharacter:
    """解析后的人物卡结构"""
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    role: Optional[str] = None  # 故事立场：主角方/反派方/中立方/亦正亦邪
    role_position: Optional[str] = None  # 角色定位：主角/盟友/导师/对手/情报角色等
    faction: Optional[str] = None  # 所属势力
    importance_level: Optional[str] = None  # 重要性
    
    # 文本字段（将合并到profile中）
    appearance: Optional[str] = None  # 外貌特征
    personality: Optional[str] = None  # 性格特点
    background: Optional[str] = None  # 背景故事
    worldview: Optional[str] = None  # 世界观/价值观立场
    motivation: Optional[str] = None  # 核心动机
    abilities: Optional[str] = None  # 能力/特长
    limitation: Optional[str] = None  # 能力限制/代价
    mainline_role: Optional[str] = None  # 主线中的剧情职责
    growth_direction: Optional[str] = None  # 人物成长方向
    relationships: Optional[str] = None  # 关键关系
    mainline_clues: Optional[str] = None  # 关联线索
    
    # 原始文本块
    raw_text: str = ""
    
    def build_summary(self) -> str:
        """构建人物简介（1-3句话）"""
        parts = []
        identity_parts = []
        if self.role:
            identity_parts.append(self.role)
        if self.role_position and self.role_position not in identity_parts:
            identity_parts.append(self.role_position)
        if identity_parts:
            parts.append(" / ".join(identity_parts))
        if self.personality:
            # 取性格特点的第一句
            first_sentence = self.personality.split('。')[0] if self.personality else ""
            if first_sentence:
                parts.append(first_sentence)
        if self.motivation:
            parts.append(f"核心动机：{self.motivation.split('。')[0]}")
        return '。'.join(parts[:3]) + '。' if parts else ""
    
    def build_profile(self) -> str:
        """构建完整人物档案"""
        sections = []

        demographics = []
        if self.age is not None:
            demographics.append(f"{self.age}岁")
        if self.gender:
            demographics.append(self.gender)
        if demographics:
            sections.append(f"【年龄/性别】\n{'/'.join(demographics)}")
        if self.role:
            sections.append(f"【故事立场】\n{self.role}")
        if self.role_position:
            sections.append(f"【角色定位】\n{self.role_position}")
        if self.faction:
            sections.append(f"【所属势力】\n{self.faction}")
        if self.appearance:
            sections.append(f"【外貌锚点】\n{self.appearance}")
        personality_anchor = _build_personality_anchor_text(self.personality, self.worldview)
        if personality_anchor:
            sections.append(f"【性格锚点】\n{personality_anchor}")
        if self.background:
            sections.append(f"【背景/当前处境】\n{self.background}")
        if self.motivation:
            sections.append(f"【核心动机】\n{self.motivation}")
        ability_and_limit = _build_ability_and_limit_text(self.abilities, self.limitation)
        if ability_and_limit:
            sections.append(f"【能力与限制】\n{ability_and_limit}")
        if self.relationships:
            sections.append(f"【关键关系】\n{self.relationships}")
        mainline_binding = _build_mainline_binding_text(self.mainline_role, self.mainline_clues)
        if mainline_binding:
            sections.append(f"【主线绑定】\n{mainline_binding}")
        if self.growth_direction:
            sections.append(f"【成长方向】\n{self.growth_direction}")
        
        return "\n\n".join(sections) if sections else self.raw_text


class CharacterTextParser:
    """人物卡文本解析器"""

    FIELD_LABEL_ALIASES = {
        "性格特征": "性格特点",
        "背景经历": "背景故事",
        "价值立场": "世界观/价值观立场",
        "能力特长": "能力/特长",
        "弱点缺陷": "弱点/缺陷",
        "剧情作用": "在情节中的作用",
        "成长线": "人物成长线",
        "外貌锚点": "外貌锚点",
        "性格锚点": "性格锚点",
        "背景/当前处境": "背景/当前处境",
        "能力与限制": "能力与限制",
        "主线绑定": "主线绑定",
        "成长方向": "成长方向",
    }
    LOOSE_FIELD_LABEL_ALIASES = {
        "姓名": "姓名",
        "角色名": "姓名",
        "人物名": "姓名",
        "年龄/性别": "年龄/性别",
        "年龄性别": "年龄/性别",
        "故事立场": "故事立场",
        "角色定位": "角色定位",
        "所属势力": "所属势力",
        "重要性": "重要性",
        "外貌特征": "外貌特征",
        "外貌锚点": "外貌锚点",
        "性格特点": "性格特点",
        "性格特征": "性格特点",
        "性格锚点": "性格锚点",
        "背景故事": "背景故事",
        "背景经历": "背景故事",
        "背景/当前处境": "背景/当前处境",
        "世界观/价值观立场": "世界观/价值观立场",
        "价值立场": "世界观/价值观立场",
        "核心动机": "核心动机",
        "能力/特长": "能力/特长",
        "能力特长": "能力/特长",
        "能力与限制": "能力与限制",
        "弱点/缺陷": "弱点/缺陷",
        "弱点缺陷": "弱点/缺陷",
        "在情节中的作用": "在情节中的作用",
        "剧情作用": "在情节中的作用",
        "人物成长线": "人物成长线",
        "成长线": "人物成长线",
        "成长方向": "成长方向",
        "关键关系": "关键关系",
        "关联线索": "关联线索",
        "主线绑定": "主线绑定",
    }
    NON_CHARACTER_HEADING_KEYWORDS = (
        "关系补丁",
        "人物关系",
        "角色关系",
        "协同新增关系",
        "协同新增角色",
        "新增角色",
        "人物卡",
        "角色名单",
        "人物名单",
    )
    LOOSE_HEADING_NAME_PATTERN = re.compile(
        r'^\s*###\s*(?!【姓名】)(?:\*\*)?(?P<name>.+?)(?:\*\*)?\s*$'
    )
    MARKDOWN_SECTION_LINE_PATTERN = re.compile(
        r'^\s*[-*]\s+(?:\*\*)?[^*\n：:]{1,20}(?:\*\*)?\s*[：:]\s*\S+'
    )

    # 字段匹配模式（支持多种格式变体）
    # 支持：【姓名】：xxx 或 **【姓名】**：xxx 或 ### 【姓名】：xxx
    FIELD_PATTERNS = {
        # 姓名特殊处理：可能有 ### 或 ** 前缀
        'name': r'(?:###\s*)?(?:\*\*)?【姓名】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'age_gender': r'(?:\*\*)?【年龄/性别】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'story_stance': r'(?:\*\*)?【故事立场】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'role_position': r'(?:\*\*)?【角色定位】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'faction': r'(?:\*\*)?【所属势力】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'importance': r'(?:\*\*)?【重要性】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'appearance': r'(?:\*\*)?【(?:外貌特征|外貌锚点)】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'personality': r'(?:\*\*)?【(?:性格特点|性格锚点)】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'background': r'(?:\*\*)?【(?:背景故事|背景/当前处境)】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'worldview': r'(?:\*\*)?【世界观/价值观立场】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'motivation': r'(?:\*\*)?【核心动机】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'abilities': r'(?:\*\*)?【(?:能力/特长|能力与限制)】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'limitation': r'(?:\*\*)?【弱点/缺陷】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'mainline_role': r'(?:\*\*)?【在情节中的作用】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'growth_direction': r'(?:\*\*)?【(?:人物成长线|成长方向)】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'relationships': r'(?:\*\*)?【关键关系】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'mainline_clues': r'(?:\*\*)?【关联线索】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
    }
    
    # 阵营识别模式
    FACTION_PATTERNS = {
        '主角阵营': ['主角', '主角阵营', '正派'],
        '对手阵营': ['对手', '反派', '对手阵营', '敌对'],
        '支持角色': ['支持', '辅助', '支持角色'],
        '中立角色': ['中立', '中立角色'],
    }

    @classmethod
    def _normalize_character_card_labels(cls, text: str) -> str:
        normalized = text or ""
        for alias, canonical in cls.FIELD_LABEL_ALIASES.items():
            normalized = re.sub(
                rf"(?m)^(\s*(?:\*\*)?【){re.escape(alias)}(】(?:\*\*)?[：:])",
                rf"\1{canonical}\2",
                normalized,
            )
        return normalized

    @staticmethod
    def _clean_candidate_name(name: str) -> str:
        value = extract_preferred_character_name(str(name or "").strip()) or str(name or "").strip()
        value = re.sub(r'^(?:姓名|角色名|人物名)\s*[：:]\s*', '', value).strip()
        value = re.sub(r'^\*+|\*+$', '', value).strip()
        value = re.sub(r'^[\"“”\'‘’「」『』]+|[\"“”\'‘’「」『』]+$', '', value).strip()
        value = re.sub(r'[（(].*?[）)]', '', value)
        value = re.sub(r'[【】\[\]<>《》]', '', value)
        value = re.sub(r'\s{2,}', ' ', value).strip()
        return value

    @classmethod
    def _extract_heading_metadata(cls, heading_text: str) -> tuple[str, Optional[str], Optional[str]]:
        cleaned_heading = re.sub(r'^\s*###\s*', '', str(heading_text or "")).strip()
        cleaned_heading = re.sub(r'^\*+|\*+$', '', cleaned_heading).strip()
        meta_match = re.search(r'[（(](?P<meta>[^()（）]{1,40})[）)]\s*$', cleaned_heading)
        meta_text = meta_match.group("meta").strip() if meta_match else ""
        name_text = cleaned_heading[:meta_match.start()].strip() if meta_match else cleaned_heading
        normalized_name = cls._clean_candidate_name(name_text)

        role_hint = None
        if any(keyword in meta_text for keyword in ("主角", "反派", "对手", "中立", "亦正亦邪")):
            role_hint = meta_text

        importance_hint = None
        if meta_text:
            importance_hint = cls()._extract_importance(meta_text)

        return normalized_name, role_hint, importance_hint

    @classmethod
    def _match_loose_field_line(cls, line: str) -> Optional[tuple[str, str]]:
        if not line or not line.strip():
            return None

        labels = sorted(cls.LOOSE_FIELD_LABEL_ALIASES, key=len, reverse=True)
        pattern = "|".join(re.escape(label) for label in labels)
        match = re.match(
            rf'^\s*(?:[-*]\s*)?(?:\d+[.、]\s*)?(?:\*\*)?(?P<label>{pattern})(?:\*\*)?\s*[：:]\s*(?P<value>.+?)\s*$',
            line,
        )
        if not match:
            return None

        label = cls.LOOSE_FIELD_LABEL_ALIASES.get(match.group("label"))
        value = match.group("value").strip()
        if not label or not value:
            return None
        return label, value

    @classmethod
    def _block_has_card_fields(cls, lines: List[str], start_index: int) -> bool:
        for index in range(start_index, len(lines)):
            raw_line = lines[index]
            stripped = raw_line.strip()
            if not stripped:
                continue
            if re.match(r'^\s*##\s+', raw_line):
                return False
            if cls.LOOSE_HEADING_NAME_PATTERN.match(raw_line):
                return False
            if re.match(r'^\s*(?:###\s*)?(?:\*\*)?【姓名】(?:\*\*)?[：:]', raw_line):
                return False
            matched = cls._match_loose_field_line(raw_line)
            if matched and matched[0] != "姓名":
                return True
            if cls.MARKDOWN_SECTION_LINE_PATTERN.match(raw_line):
                return True
            if re.match(r'^\s*(?:[-*]\s*)?(?:\*\*)?【[^】]+】(?:\*\*)?[：:]\s*\S+', raw_line):
                return True
        return False

    @classmethod
    def _normalize_loose_character_card_lines(cls, text: str) -> str:
        lines = (text or "").splitlines()
        normalized_lines: List[str] = []

        for index, line in enumerate(lines):
            loose_field = cls._match_loose_field_line(line)
            if loose_field:
                label, value = loose_field
                if label == "姓名":
                    cleaned_name = cls._clean_candidate_name(value)
                    normalized_lines.append(f"### 【姓名】：{cleaned_name or value.strip()}")
                else:
                    normalized_lines.append(f"【{label}】：{value}")
                continue

            heading_match = cls.LOOSE_HEADING_NAME_PATTERN.match(line)
            if heading_match:
                cleaned_name, role_hint, importance_hint = cls._extract_heading_metadata(
                    heading_match.group("name")
                )
                if (
                    cleaned_name
                    and len(cleaned_name) <= 30
                    and not any(keyword in cleaned_name for keyword in cls.NON_CHARACTER_HEADING_KEYWORDS)
                    and cls._block_has_card_fields(lines, index + 1)
                ):
                    normalized_lines.append(f"### 【姓名】：{cleaned_name}")
                    if role_hint:
                        normalized_lines.append(f"【角色定位】：{role_hint}")
                    if importance_hint:
                        normalized_lines.append(f"【重要性】：{importance_hint}")
                    continue

            normalized_lines.append(line)

        return "\n".join(normalized_lines)

    @classmethod
    def _prepare_text_for_parsing(cls, text: str) -> str:
        normalized = cls._normalize_character_card_labels(normalize_story_text(text))
        return cls._normalize_loose_character_card_lines(normalized)

    @staticmethod
    def _split_character_blocks(text: str) -> List[str]:
        split_pattern = r'(?=(?:###\s*)?(?:\*\*)?【姓名】(?:\*\*)?[：:])'
        return [block.strip() for block in re.split(split_pattern, text or "") if block.strip()]
    
    def parse_all_characters(self, text: str) -> List[ParsedCharacter]:
        """解析文本中的所有人物卡

        支持多种格式：
        1. ### 【姓名】：李铁柱
        2. 【姓名】：李铁柱
        3. **【姓名】**：李铁柱
        """
        characters = []
        unique: Dict[str, ParsedCharacter] = {}
        current_faction = None

        normalized_text = self._prepare_text_for_parsing(text)

        logger.debug(f"📋 开始解析人物卡，文本长度: {len(normalized_text)} 字符")

        character_blocks = self._split_character_blocks(normalized_text)

        logger.debug(f"   分割出 {len(character_blocks)} 个文本块")

        for i, block in enumerate(character_blocks):
            # 检测阵营标题（## 主角阵营 等）
            faction_match = re.search(r'^##\s*([^#\n]+?)(?:\n|$)', block, re.MULTILINE)
            if faction_match:
                faction_title = faction_match.group(1).strip()
                for faction, keywords in self.FACTION_PATTERNS.items():
                    if any(kw in faction_title for kw in keywords):
                        current_faction = faction
                        logger.debug(f"   检测到阵营: {current_faction}")
                        break

            # 解析人物卡
            parsed = self._parse_single_character(block)
            if parsed and parsed.name:
                if current_faction and not parsed.faction:
                    parsed.faction = current_faction
                key = normalize_character_name(parsed.name) or parsed.name.strip()
                if key in unique:
                    unique[key] = _merge_parsed_character(unique[key], parsed)
                else:
                    unique[key] = parsed
                logger.debug(f"   ✓ 成功解析人物: {parsed.name}")
            elif '【姓名】' in block:
                logger.debug(f"   ✗ 块 {i} 包含【姓名】但解析失败，前100字符: {block[:100]}...")

        if unique:
            characters = list(unique.values())

        logger.info(f"📋 解析完成，共识别 {len(characters)} 个人物")
        return characters

    def _parse_single_character(self, block: str) -> Optional[ParsedCharacter]:
        """解析单个人物卡文本块"""
        block = self._normalize_character_card_labels(block)

        # 提取姓名
        name_match = re.search(self.FIELD_PATTERNS['name'], block, re.DOTALL)
        if not name_match:
            logger.debug(f"   未匹配到姓名字段")
            return None

        name = self._clean_candidate_name(name_match.group(1))
        # 清理名字中可能的markdown格式（如 **李铁柱** -> 李铁柱）
        name = re.sub(r'\*+', '', name).strip()

        if not name:
            logger.debug(f"   姓名为空")
            return None
        if len(name) > 30:  # 名字过长可能是解析错误（放宽限制）
            logger.debug(f"   姓名过长: {name[:30]}...")
            return None

        char = ParsedCharacter(name=name, raw_text=block)

        # 解析年龄和性别
        age_gender_match = re.search(self.FIELD_PATTERNS['age_gender'], block, re.DOTALL)
        if age_gender_match:
            age_gender = age_gender_match.group(1).strip()
            char.age, char.gender = self._parse_age_gender(age_gender)

        # 解析故事立场
        story_stance_match = re.search(self.FIELD_PATTERNS['story_stance'], block, re.DOTALL)
        if story_stance_match:
            role_text = story_stance_match.group(1).strip()
            char.role = self._normalize_role(role_text)

        # 解析角色定位
        role_position_match = re.search(self.FIELD_PATTERNS['role_position'], block, re.DOTALL)
        if role_position_match:
            char.role_position = role_position_match.group(1).strip()
            if not char.role:
                char.role = self._infer_story_stance_from_role_position(char.role_position)

        # 解析所属势力
        faction_match = re.search(self.FIELD_PATTERNS['faction'], block, re.DOTALL)
        if faction_match:
            char.faction = faction_match.group(1).strip()
        
        # 解析重要性
        importance_match = re.search(self.FIELD_PATTERNS['importance'], block, re.DOTALL)
        if importance_match:
            char.importance_level = importance_match.group(1).strip()
        elif char.role_position or char.role:
            char.importance_level = self._extract_importance(char.role_position or char.role or "")

        # 解析其他字段
        for field_name in ['appearance', 'personality', 'background', 'worldview',
                           'motivation', 'abilities', 'limitation', 'mainline_role',
                           'growth_direction', 'relationships', 'mainline_clues']:
            pattern = self.FIELD_PATTERNS.get(field_name)
            if pattern:
                matches = list(re.finditer(pattern, block, re.DOTALL))
                if matches:
                    match = matches[-1] if field_name == "mainline_clues" else matches[0]
                    value = match.group(1).strip()
                    # 清理多余空白
                    value = re.sub(r'\n{3,}', '\n\n', value)
                    setattr(char, field_name, value)

        combined_personality = _extract_prefixed_character_value(char.personality, ("性格",))
        combined_worldview = _extract_prefixed_character_value(char.personality, ("价值倾向",))
        if combined_personality:
            char.personality = combined_personality
        if combined_worldview and not char.worldview:
            char.worldview = combined_worldview

        combined_abilities = _extract_prefixed_character_value(char.abilities, ("能力",))
        combined_limitation = _extract_prefixed_character_value(char.abilities, ("限制", "弱点", "代价"))
        if combined_abilities:
            char.abilities = combined_abilities
        if combined_limitation and not char.limitation:
            char.limitation = combined_limitation

        binding_match = re.search(r'(?:\*\*)?【主线绑定】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)', block, re.DOTALL)
        binding_text = binding_match.group(1).strip() if binding_match else ""
        combined_mainline_role = _extract_prefixed_character_value(binding_text, ("剧情职责", "主线职责"))
        combined_mainline_clues = _extract_prefixed_character_value(binding_text, ("关联线索",))
        if combined_mainline_role and not char.mainline_role:
            char.mainline_role = combined_mainline_role
        if combined_mainline_clues and not char.mainline_clues:
            char.mainline_clues = combined_mainline_clues

        return char

    def _parse_age_gender(self, text: str) -> tuple:
        """解析年龄和性别字段"""
        age = None
        gender = None

        # 提取年龄数字
        age_match = re.search(r'(\d+)\s*岁?', text)
        if age_match:
            try:
                age = int(age_match.group(1))
            except ValueError:
                pass

        # 提取性别
        if '男' in text:
            gender = '男'
        elif '女' in text:
            gender = '女'

        return age, gender

    def _normalize_role(self, role_text: str) -> str:
        """标准化故事立场"""
        normalized = normalize_story_stance_label(role_text)
        if normalized:
            return normalized
        return role_text.split('/')[0].strip()[:10]

    def _infer_story_stance_from_role_position(self, role_text: str) -> Optional[str]:
        """从角色定位推断故事立场，兼容旧版仅输出角色定位的人物卡。"""
        return infer_story_stance_from_text_evidence(role_text)

    def _extract_importance(self, role_text: str) -> str:
        """提取重要性等级（戏份权重）"""
        if '主角' in role_text:
            return '主角'
        elif '核心' in role_text or '关键' in role_text or '重要' in role_text:
            return '重要角色'
        elif '次要' in role_text:
            return '次要角色'
        elif '龙套' in role_text or '路人' in role_text or '群众' in role_text:
            return '群众角色'
        # 默认为次要角色
        return '次要角色'


LEGACY_CHARACTER_SECTION_PATTERN = re.compile(
    r'(?m)^\s*(?:#{1,6}\s*)?(?P<index>[一二三四五六七八九十]+)[、.．:：]\s*(?P<title>[^\n]+?)\s*$'
)
LEGACY_CHARACTER_ITEM_PATTERN = re.compile(
    r'(?m)^\s*(?P<index>\d+)[.、]\s*(?P<title>[^\n]{1,80})\s*$'
)
LEGACY_SKIP_SECTION_KEYWORDS = (
    "人物关系",
    "关系网络",
    "关系网",
    "剧情功能",
    "设计总结",
    "一致性说明",
    "核心原则",
    "总结",
)
LEGACY_INLINE_FIELD_PATTERN = re.compile(
    r'^\s*(?:[-*]\s*)?(?P<label>[^：:\n]{1,20})\s*[：:]\s*(?P<value>.+?)\s*$'
)
LEGACY_ORG_PATTERN = re.compile(
    r'[“"「]?(?P<name>[A-Za-z0-9\u4e00-\u9fff]{2,20}(?:宗|门|司|会|殿|府|阁|墟|楼|谷|盟|宫|院|山|族|朝|城|庭|塔))[”"」]?'
)


def _clean_legacy_name_candidate(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r'^(?:姓名|名讳|角色名|人物名)\s*[：:]\s*', '', text).strip()
    text = re.split(r'[／/]', text, maxsplit=1)[0].strip()
    text = re.split(r'\s+真名\s*[：:]\s*', text, maxsplit=1)[0].strip()
    text = re.split(r'\s+身份\s*[：:]\s*', text, maxsplit=1)[0].strip()
    text = re.sub(r'^[“"「]|[”"」]$', '', text).strip()
    return normalize_character_name(text)


def _normalize_legacy_heading_label(line: str) -> str:
    label = str(line or "").strip()
    label = re.sub(r'^\s*(?:[-*]\s*)?(?:\d+[.、]\s*)?', '', label).strip()
    label = label.strip("：: ")
    return label


def _infer_legacy_bucket(label: str) -> Optional[str]:
    normalized = _normalize_legacy_heading_label(label)
    if not normalized:
        return None
    if any(keyword in normalized for keyword in ("姓名", "名讳")):
        return "name"
    if any(keyword in normalized for keyword in ("年龄/性别", "年龄", "外貌年龄", "性别")):
        return "age_gender"
    if any(keyword in normalized for keyword in ("身份", "出身", "背景", "经历")):
        return "background"
    if any(keyword in normalized for keyword in ("外貌", "形象", "气质", "着装", "日常状态", "称号")):
        return "appearance"
    if any(keyword in normalized for keyword in ("能力", "金手指", "战斗风格", "道名")):
        return "abilities"
    if any(keyword in normalized for keyword in ("性格", "心理", "认知", "情感", "内核")):
        return "personality"
    if any(keyword in normalized for keyword in ("理念", "信念", "世界观", "价值观")):
        return "worldview"
    if any(keyword in normalized for keyword in ("动机", "驱动", "目的", "抉择")):
        return "motivation"
    if any(keyword in normalized for keyword in ("弱点", "代价", "风险", "困境", "反噬", "撕裂")):
        return "limitation"
    if any(keyword in normalized for keyword in ("成长", "转折", "初始状态", "中期状态", "后期方向", "终极真相")):
        return "growth_direction"
    if "关系" in normalized or "锚点" in normalized:
        return "relationships"
    if any(keyword in normalized for keyword in ("作用", "剧情功能")):
        return "mainline_role"
    return None


def _append_legacy_field(target: Dict[str, List[str]], field_name: str, value: str) -> None:
    cleaned = re.sub(r'^\s*(?:[-*]\s*)?', '', str(value or "").strip()).strip()
    if not cleaned:
        return
    target.setdefault(field_name, [])
    if cleaned not in target[field_name]:
        target[field_name].append(cleaned)


def _join_legacy_field(values: List[str]) -> str:
    cleaned_values = [str(item).strip() for item in values if str(item).strip()]
    if not cleaned_values:
        return ""
    return "\n".join(cleaned_values)


def _extract_legacy_faction(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    match = LEGACY_ORG_PATTERN.search(normalized)
    if match:
        return match.group("name")
    if "无门无派" in normalized or "散修" in normalized:
        return "无"
    return ""


def _split_legacy_sections(text: str) -> List[tuple[str, str]]:
    matches = list(LEGACY_CHARACTER_SECTION_PATTERN.finditer(text or ""))
    if not matches:
        return []

    sections: List[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = match.group("title").strip()
        body = (text[start:end] or "").strip()
        if title:
            sections.append((title, body))
    return sections


def _split_legacy_section_title(title: str) -> tuple[str, str]:
    normalized = str(title or "").strip()
    parts = re.split(r'[：:]', normalized, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), _clean_legacy_name_candidate(parts[1])
    return normalized, ""


def _is_legacy_primary_section(title: str) -> bool:
    return "主角" in title and "配角" not in title and "反派" not in title and "对立" not in title


def _looks_like_character_item_heading(title: str) -> bool:
    candidate = _clean_legacy_name_candidate(title)
    if not candidate:
        return False
    if len(candidate) > 20:
        return False
    return not any(
        keyword in candidate
        for keyword in ("表象", "特质", "能力", "关系", "总结", "设计", "原则", "功能", "状态", "方向")
    )


def _split_legacy_character_entries(section_title: str, body: str, section_name_hint: str) -> List[tuple[str, str]]:
    if _is_legacy_primary_section(section_title):
        return [(section_name_hint, body)]

    matches = [
        match
        for match in LEGACY_CHARACTER_ITEM_PATTERN.finditer(body or "")
        if _looks_like_character_item_heading(match.group("title"))
    ]
    if not matches:
        if re.search(r'(?m)^\s*(?:[-*]\s*)?(?:姓名|名讳)\s*[：:]', body or ""):
            return [("", body)]
        return []

    entries: List[tuple[str, str]] = []
    leading = (body[: matches[0].start()] or "").strip()
    if re.search(r'(?m)^\s*(?:[-*]\s*)?(?:姓名|名讳)\s*[：:]', leading):
        entries.append(("", leading))

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        entry_title = match.group("title").strip()
        entry_body = (body[start:end] or "").strip()
        entries.append((entry_title, entry_body))

    return entries


def _infer_legacy_role_position(section_title: str, entry_text: str) -> str:
    combined = f"{section_title}\n{entry_text}"
    if "主角" in section_title and "配角" not in section_title:
        return "主角"
    if any(keyword in combined for keyword in ("导师", "师父", "如师如父", "引路人")):
        return "导师"
    if any(keyword in combined for keyword in ("情报", "暗线", "观察者")):
        return "情报角色"
    if any(keyword in combined for keyword in ("守护", "庇护", "保护")):
        return "守护者"
    if any(keyword in section_title for keyword in ("反派", "对立")):
        if any(keyword in combined for keyword in ("司主", "宗主", "府主", "长老", "天道")):
            return "高位反派"
        return "对手"
    if any(keyword in combined for keyword in ("背叛", "摇摆", "危险", "双面")):
        return "危险盟友"
    if any(keyword in section_title for keyword in ("配角", "盟友")):
        return "盟友"
    return "中立角色"


def _infer_legacy_defaults(section_title: str, entry_text: str) -> tuple[str, str, str]:
    parser = CharacterTextParser()
    role_position = _infer_legacy_role_position(section_title, entry_text)

    story_stance = infer_story_stance_from_text_evidence(section_title, entry_text, role_position)
    if not story_stance:
        if any(keyword in section_title for keyword in ("反派", "对立")):
            story_stance = "反派方"
        elif any(keyword in section_title for keyword in ("主角", "配角", "盟友")):
            story_stance = "主角方"
        else:
            story_stance = "中立方"

    importance = "主角" if role_position == "主角" else parser._extract_importance(section_title or role_position)
    if importance == "次要角色" and any(keyword in section_title for keyword in ("关键", "核心", "主要")):
        importance = "重要角色"
    return story_stance, role_position, importance


def _build_legacy_mainline_clues(fields: Dict[str, str]) -> str:
    candidates = [
        fields.get("mainline_role", ""),
        fields.get("relationships", ""),
        fields.get("background", ""),
        fields.get("growth_direction", ""),
    ]
    merged: List[str] = []
    for item in candidates:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        first_line = cleaned.splitlines()[0].strip()
        if first_line and first_line not in merged:
            merged.append(first_line)
    return "；".join(merged[:3])


def _render_full_character_card(name: str, fields: Dict[str, str]) -> str:
    ordered_fields = [
        ("年龄/性别", fields.get("age_gender") or "待补充"),
        ("故事立场", fields.get("story_stance") or "中立方"),
        ("角色定位", fields.get("role_position") or "中立角色"),
        ("所属势力", fields.get("faction") or "无"),
        ("外貌锚点", fields.get("appearance") or "待补充"),
        (
            "性格锚点",
            _build_personality_anchor_text(
                fields.get("personality"),
                fields.get("worldview"),
                default="待补充",
            ),
        ),
        ("背景/当前处境", fields.get("background") or "待补充"),
        ("核心动机", fields.get("motivation") or "待补充"),
        (
            "能力与限制",
            _build_ability_and_limit_text(
                fields.get("abilities"),
                fields.get("limitation"),
                default="待补充",
            ),
        ),
        ("关键关系", fields.get("relationships") or "待补充"),
        (
            "主线绑定",
            _build_mainline_binding_text(
                fields.get("mainline_role"),
                fields.get("mainline_clues"),
                default="待补充",
            ),
        ),
        ("成长方向", fields.get("growth_direction") or "待补充"),
    ]

    lines = [f"### 【姓名】：{name}"]
    for label, value in ordered_fields:
        lines.append(f"【{label}】：{str(value).strip() or '待补充'}")
    return "\n".join(lines)


def _convert_legacy_entry_to_card(
    section_title: str,
    entry_name_hint: str,
    entry_body: str,
) -> str:
    fields_raw: Dict[str, List[str]] = {}
    generic_lines: List[str] = []
    current_bucket: Optional[str] = None
    name = _clean_legacy_name_candidate(entry_name_hint)
    faction = ""

    for raw_line in (entry_body or "").splitlines():
        line = str(raw_line or "").strip()
        if not line or line.startswith("|"):
            continue
        if re.fullmatch(r'[*\-]{3,}', line):
            current_bucket = None
            continue

        inline_match = LEGACY_INLINE_FIELD_PATTERN.match(line)
        if inline_match:
            label = _normalize_legacy_heading_label(inline_match.group("label"))
            value = inline_match.group("value").strip()
            bucket = _infer_legacy_bucket(label)
            if bucket == "name":
                candidate_name = _clean_legacy_name_candidate(value)
                if candidate_name:
                    name = candidate_name
                else:
                    _append_legacy_field(fields_raw, "background", f"{label}：{value}")
                current_bucket = None
                continue
            if bucket == "age_gender":
                _append_legacy_field(fields_raw, "age_gender", value)
                current_bucket = None
                continue
            if bucket == "background":
                _append_legacy_field(fields_raw, "background", f"{label}：{value}")
                if not faction:
                    faction = _extract_legacy_faction(value)
                current_bucket = "background"
                continue
            if bucket:
                rendered_value = value if label in ("年龄/性别", "年龄", "外貌年龄", "性别") else f"{label}：{value}"
                _append_legacy_field(fields_raw, bucket, rendered_value)
                current_bucket = bucket
                continue

        subsection_bucket = _infer_legacy_bucket(line)
        if subsection_bucket and len(_normalize_legacy_heading_label(line)) <= 20:
            current_bucket = subsection_bucket
            continue

        if current_bucket:
            _append_legacy_field(fields_raw, current_bucket, line)
        else:
            generic_lines.append(re.sub(r'^\s*(?:[-*]\s*)?', '', line).strip())

    if not name:
        for fallback_line in generic_lines:
            inline_match = LEGACY_INLINE_FIELD_PATTERN.match(fallback_line)
            if inline_match and _infer_legacy_bucket(inline_match.group("label")) == "name":
                candidate_name = _clean_legacy_name_candidate(inline_match.group("value"))
                if candidate_name:
                    name = candidate_name
                    break

    if not name:
        return ""

    if generic_lines:
        _append_legacy_field(fields_raw, "background", "\n".join(generic_lines[:4]))

    fields = {
        field_name: _join_legacy_field(values)
        for field_name, values in fields_raw.items()
    }
    if not faction:
        faction = _extract_legacy_faction(
            "\n".join(
                item
                for item in (
                    fields.get("background", ""),
                    fields.get("relationships", ""),
                    entry_body,
                )
                if item
            )
        )

    story_stance, role_position, importance = _infer_legacy_defaults(section_title, entry_body)
    story_stance = infer_story_stance_from_text_evidence(
        fields.get("relationships", ""),
        fields.get("mainline_role", ""),
        fields.get("worldview", ""),
        role_position,
    ) or story_stance

    fields["story_stance"] = story_stance
    fields["role_position"] = fields.get("role_position") or role_position
    fields["importance_level"] = fields.get("importance_level") or importance
    fields["faction"] = faction or "无"
    fields["mainline_clues"] = fields.get("mainline_clues") or _build_legacy_mainline_clues(fields)

    return _render_full_character_card(name, fields)


def convert_legacy_grouped_characters_to_cards(characters_text: str) -> str:
    if not isinstance(characters_text, str) or not characters_text.strip():
        return ""

    if has_parseable_character_cards(characters_text):
        return characters_text

    normalized_text = normalize_story_text(characters_text)
    sections = _split_legacy_sections(normalized_text)
    if not sections:
        return ""

    cards: List[str] = []
    seen_names: set[str] = set()

    for raw_title, body in sections:
        section_title, section_name_hint = _split_legacy_section_title(raw_title)
        if any(keyword in section_title for keyword in LEGACY_SKIP_SECTION_KEYWORDS):
            continue

        entries = _split_legacy_character_entries(section_title, body, section_name_hint)
        for entry_name_hint, entry_body in entries:
            card = _convert_legacy_entry_to_card(section_title, entry_name_hint, entry_body)
            if not card:
                continue
            name_match = re.search(r'^###\s*【姓名】：(.+?)$', card, re.MULTILINE)
            if not name_match:
                continue
            normalized_name = normalize_character_name(name_match.group(1))
            if not normalized_name or normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)
            cards.append(card)

    result = "\n\n".join(cards).strip()
    return result if has_parseable_character_cards(result) else ""


def sync_parsed_characters_to_db(
    project_id: int,
    parsed_characters: List[ParsedCharacter],
    db_session: Any
) -> Dict[str, Any]:
    """
    将解析后的人物卡同步到数据库的characters表

    逻辑：
    1. 根据姓名查找已存在的角色
    2. 如果存在则更新，不存在则创建
    3. 返回同步统计信息

    Args:
        project_id: 项目ID
        parsed_characters: 解析后的人物卡列表
        db_session: SQLAlchemy数据库会话

    Returns:
        同步统计信息
    """
    from app.models.character import Character

    created_count = 0
    updated_count = 0
    skipped_count = 0
    errors = []

    existing_characters = db_session.query(Character).filter(
        Character.project_id == project_id
    ).all()
    existing_by_norm: Dict[str, Character] = {}
    for item in existing_characters:
        key = normalize_character_name(item.name) or (item.name or "").strip()
        if not key or key in existing_by_norm:
            continue
        existing_by_norm[key] = item

    for parsed in parsed_characters:
        try:
            # 查找已存在的角色（按项目ID和姓名）
            parsed_key = normalize_character_name(parsed.name) or parsed.name.strip()
            existing = existing_by_norm.get(parsed_key)
            if not existing:
                existing = db_session.query(Character).filter(
                    Character.project_id == project_id,
                    Character.name == parsed.name
                ).first()
                if existing and parsed_key:
                    existing_by_norm[parsed_key] = existing

            if existing:
                # 更新已存在的角色
                existing.gender = parsed.gender or existing.gender
                existing.age = parsed.age or existing.age
                existing.role = parsed.role or existing.role
                existing.role_position = parsed.role_position or existing.role_position
                existing.faction = parsed.faction or existing.faction
                existing.importance_level = parsed.importance_level or existing.importance_level
                existing.summary = parsed.build_summary() or existing.summary
                existing.profile = parsed.build_profile() or existing.profile

                # 更新关系字段（JSON格式）
                if parsed.relationships:
                    existing.relations = json.dumps(
                        build_character_relations_payload(parsed.relationships),
                        ensure_ascii=False,
                    )

                updated_count += 1
                logger.debug(f"   📝 更新角色: {parsed.name}")
            else:
                # 创建新角色
                new_char = Character(
                    project_id=project_id,
                    name=parsed.name,
                    gender=parsed.gender,
                    age=parsed.age,
                    role=parsed.role,
                    role_position=parsed.role_position,
                    faction=parsed.faction,
                    importance_level=parsed.importance_level,
                    summary=parsed.build_summary(),
                    profile=parsed.build_profile(),
                    relations=(
                        json.dumps(
                            build_character_relations_payload(parsed.relationships),
                            ensure_ascii=False,
                        )
                        if parsed.relationships
                        else None
                    ),
                    appearance_status="未出场",  # 默认未出场
                    life_status="存活",  # 默认存活
                )
                db_session.add(new_char)
                created_count += 1
                if parsed_key:
                    existing_by_norm[parsed_key] = new_char
                logger.debug(f"   ➕ 创建角色: {parsed.name}")

        except Exception as e:
            errors.append(f"{parsed.name}: {str(e)}")
            skipped_count += 1
            logger.warning(f"   ⚠️ 同步角色失败 {parsed.name}: {e}")

    # 提交事务
    try:
        db_session.commit()
        logger.info(f"✅ 角色同步完成: 创建 {created_count} 个, 更新 {updated_count} 个, 跳过 {skipped_count} 个")
    except Exception as e:
        db_session.rollback()
        logger.error(f"❌ 角色同步提交失败: {e}")
        raise

    return {
        "created": created_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "errors": errors,
        "total": len(parsed_characters)
    }


def parse_and_sync_characters(
    project_id: int,
    characters_text: str,
    db_session: Any
) -> Dict[str, Any]:
    """
    一键解析文本人物卡并同步到数据库

    这是提供给外部调用的主函数。

    Args:
        project_id: 项目ID
        characters_text: 包含人物卡的文本
        db_session: SQLAlchemy数据库会话

    Returns:
        解析和同步的统计信息
    """
    logger.info(f"🚀 开始解析并同步人物卡到数据库，项目ID: {project_id}")

    # 1. 解析文本
    parser = CharacterTextParser()
    parsed_characters = parser.parse_all_characters(characters_text)

    if not parsed_characters:
        logger.warning("⚠️ 未能解析出任何人物卡")
        return {
            "parsed": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": ["未能解析出任何人物卡"],
            "total": 0
        }

    # 2. 同步到数据库
    sync_result = sync_parsed_characters_to_db(project_id, parsed_characters, db_session)
    sync_result["parsed"] = len(parsed_characters)

    return sync_result


def has_parseable_character_cards(characters_text: str) -> bool:
    """用于在同步前做轻量检测，复用与真实解析一致的口径。"""
    if not isinstance(characters_text, str) or not characters_text.strip():
        return False

    parser = CharacterTextParser()
    normalized_text = parser._prepare_text_for_parsing(characters_text)
    for block in parser._split_character_blocks(normalized_text):
        if parser._parse_single_character(block):
            return True
    return False


def parse_and_sync_relationships(
    project_id: int,
    relationships_text: str,
    db_session: Any
) -> Dict[str, Any]:
    """
    🆕 解析人物关系文本并同步到Character.relations字段
    
    支持的格式：
    - [角色A] ↔ [角色B]：[关系类型]（[关系描述]）
    - 主角 ⇄ 盟友A：战友关系，相互信任（第1章建立）
    - 李铁柱 → 师傅：师徒关系
    
    Args:
        project_id: 项目ID
        relationships_text: 关系文本
        db_session: 数据库会话
    
    Returns:
        解析和同步的统计信息
    """
    from app.models.character import Character
    
    logger.info(f"🔗 开始解析人物关系文本，项目ID: {project_id}")
    
    if not relationships_text:
        logger.warning("⚠️ 关系文本为空")
        return {"parsed": 0, "saved": 0, "characters_updated": 0}
    
    # 获取项目下所有人物
    characters = db_session.query(Character).filter(
        Character.project_id == project_id
    ).all()
    
    if not characters:
        logger.warning(f"⚠️ 项目 {project_id} 没有人物卡")
        return {"parsed": 0, "saved": 0, "characters_updated": 0}
    
    # 构建名称到人物的映射
    name_to_char = {char.name: char for char in characters}
    
    # 解析关系文本
    # 匹配模式：- [xxx] ↔/⇄/→/← [xxx]：xxx（xxx）
    # 或者：- xxx ↔/⇄/→/← xxx：xxx
    relation_patterns = [
        # 模式1：- [角色A] ↔ [角色B]：关系类型（描述）
        r'-\s*\[?([^\[\]↔⇄→←：:]+?)\]?\s*[↔⇄→←]\s*\[?([^\[\]↔⇄→←：:]+?)\]?\s*[：:]\s*([^（）()]+?)(?:（([^）]+)）|\(([^)]+)\))?\s*$',
        # 模式2：角色A ↔ 角色B：关系类型
        r'([\u4e00-\u9fa5]{2,8})\s*[↔⇄→←]\s*([\u4e00-\u9fa5]{2,8})\s*[：:]\s*(.+?)\s*$',
    ]
    
    parsed_relations = []
    
    for line in relationships_text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('*'):
            continue
        
        for pattern in relation_patterns:
            match = re.search(pattern, line, re.MULTILINE)
            if match:
                groups = match.groups()
                source = groups[0].strip() if groups[0] else None
                target = groups[1].strip() if groups[1] else None
                rel_type = groups[2].strip() if groups[2] else "关联"
                description = (groups[3] or groups[4] if len(groups) > 3 else None) or ""
                
                # 清理关系类型（去除多余标符）
                rel_type = rel_type.split('，')[0].split(',')[0].strip()
                
                if source and target and source != target:
                    parsed_relations.append({
                        'source': source,
                        'target': target,
                        'type': rel_type,
                        'description': description.strip() if description else ""
                    })
                break
    
    logger.info(f"   解析出 {len(parsed_relations)} 条关系")
    
    # 将关系写入Character.relations字段
    saved_count = 0
    updated_chars = set()
    
    for rel in parsed_relations:
        source_name = rel['source']
        target_name = rel['target']
        rel_type = rel['type']
        
        # 查找源人物
        source_char = name_to_char.get(source_name)
        if not source_char:
            # 尝试模糊匹配
            for name, char in name_to_char.items():
                if source_name in name or name in source_name:
                    source_char = char
                    break
        
        if not source_char:
            logger.debug(f"   未找到源人物: {source_name}")
            continue
        
        # 解析现有关系
        try:
            existing_relations = json.loads(source_char.relations) if source_char.relations else None
        except Exception:
            existing_relations = source_char.relations or None

        existing_relation_items = extract_character_relation_items(existing_relations)
        
        # 检查是否已存在相同关系
        already_exists = any(
            r.get('target') == target_name and r.get('type') == rel_type
            for r in existing_relation_items if isinstance(r, dict)
        )
        
        if not already_exists:
            # 添加新关系
            new_relation = {
                "target": target_name,
                "type": rel_type
            }
            source_char.relations = json.dumps(
                build_character_relations_payload(
                    {
                        "text": (
                            existing_relations.get("text")
                            if isinstance(existing_relations, dict)
                            else (existing_relations if isinstance(existing_relations, str) else "")
                        ),
                        "items": [*existing_relation_items, new_relation],
                    }
                ),
                ensure_ascii=False,
            )
            updated_chars.add(source_char.id)
            saved_count += 1
            logger.debug(f"   → {source_name} --[{rel_type}]--> {target_name}")
    
    # 提交更改
    if updated_chars:
        db_session.commit()
        logger.info(f"   🔗 已更新 {len(updated_chars)} 个人物的关系数据，共 {saved_count} 条关系")
    
    return {
        "parsed": len(parsed_relations),
        "saved": saved_count,
        "characters_updated": len(updated_chars)
    }
