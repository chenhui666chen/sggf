"""
人物卡解析工具函数
"""
import re
from typing import Any, Optional, List

from app.services.story_text_utils import extract_preferred_character_name

from ._constants import (
    CANONICAL_STORY_STANCES,
    _EXPLICIT_STORY_STANCE_PATTERNS,
    _PRO_STORY_STANCE_PHRASES,
    _ANTI_STORY_STANCE_PHRASES,
    _NEUTRAL_STORY_STANCE_PHRASES,
    _AMBIGUOUS_STORY_STANCE_PHRASES,
)


def normalize_character_name(name: str) -> str:
    if not name:
        return ""
    value = extract_preferred_character_name(str(name).strip()) or str(name).strip()
    value = re.sub(r'^["\u201c\u201d\'\u2018\u2019\u300c\u300d\u300e\u300f]+|["\u201c\u201d\'\u2018\u2019\u300c\u300d\u300e\u300f]+$', '', value).strip()
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
        "speech_style",
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
