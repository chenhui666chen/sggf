"""
人物卡文本解析器主类
"""
import re
import logging
from typing import Dict, List, Optional

from app.services.story_text_utils import (
    extract_preferred_character_name,
    normalize_story_text,
)

from ._dataclasses import ParsedCharacter
from ._utils import (
    normalize_character_name,
    normalize_story_stance_label,
    infer_story_stance_from_text_evidence,
    _merge_parsed_character,
    _extract_prefixed_character_value,
)

logger = logging.getLogger("uvicorn.error")


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
        "说话风格": "说话风格",
        "语言风格": "说话风格",
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
        'speech_style': r'(?:\*\*)?【(?:说话风格|语言风格)】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
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
                           'growth_direction', 'relationships', 'mainline_clues',
                           'speech_style']:
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
