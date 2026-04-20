"""
Legacy格式人物卡处理

处理旧版分组格式的人物卡文本
"""
import re
import logging
from typing import Dict, List, Optional

from app.services.story_text_utils import normalize_story_text

from ._constants import CANONICAL_STORY_STANCES
from ._dataclasses import ParsedCharacter
from ._utils import (
    normalize_character_name,
    infer_story_stance_from_text_evidence,
    _build_personality_anchor_text,
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
)
from ._parser import CharacterTextParser, has_parseable_character_cards

logger = logging.getLogger("uvicorn.error")


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
