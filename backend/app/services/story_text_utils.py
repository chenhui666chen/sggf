from __future__ import annotations

import json
import re
from typing import Any, List, Optional


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
}
_UNKNOWN_NAME_MARKERS = {
    "未知",
    "不详",
    "匿名",
    "保密",
    "神秘人",
    "？？？",
    "???",
}


def decode_story_text_payload(value: Any) -> str:
    """Unwrap workflow text fields that may have been stored as JSON strings."""
    parsed = value

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        if stripped.startswith(("{", "[", '"')):
            try:
                parsed = json.loads(stripped)
            except Exception:
                parsed = value

    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, list):
        items: List[str] = []
        for item in parsed:
            if isinstance(item, str):
                item_text = decode_story_text_payload(item)
            else:
                item_text = json.dumps(item, ensure_ascii=False)
            if item_text and item_text.strip():
                items.append(item_text.strip())
        return "\n\n".join(items)
    if isinstance(parsed, dict):
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    return str(parsed or "")


def repair_story_text_payload(value: Any) -> str:
    """Repair mixed escaped/plain workflow text payloads into readable multiline text."""
    text = decode_story_text_payload(value)
    if not isinstance(text, str):
        return str(text or "")

    stripped = text.strip()
    if not stripped:
        return ""

    escaped_newlines = stripped.count("\\r\\n") + stripped.count("\\n")
    has_escaped_quotes = '\\"' in stripped
    looks_like_escaped_payload = stripped.startswith('"') or escaped_newlines >= 2 or has_escaped_quotes
    if not looks_like_escaped_payload:
        return text

    repaired = stripped
    if repaired.startswith('"'):
        repaired = repaired[1:]
    if repaired.endswith('"') and not repaired.endswith('\\"'):
        repaired = repaired[:-1]

    repaired = (
        repaired.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
    )

    if repaired.count("\n") > text.count("\n") or "【姓名】" in repaired or "【第1卷】" in repaired:
        return repaired
    return text


def normalize_story_text(value: Any) -> str:
    return repair_story_text_payload(value).replace("\r\n", "\n").replace("\r", "\n")


_INLINE_EVENT_MARKER_PATTERN = re.compile(
    r"(^|[\s；;。！？!?：:])(?P<marker>[①②③④⑤⑥⑦⑧⑨⑩⑪⑫]|\d{1,2}[\.、]|[一二三四五六七八九十]{1,3}[、.])\s*"
)
_STRONG_EVENT_SEPARATOR_PATTERN = re.compile(r"\s*(?:；|;|[—–-]{2,})\s*")


def _clean_story_event_item(value: str) -> str:
    text = normalize_story_text(value or "").strip()
    if not text:
        return ""

    text = re.sub(r"^[\-\*\u2022•]+\s*", "", text)
    text = re.sub(r"^(?:[①②③④⑤⑥⑦⑧⑨⑩⑪⑫]|\d{1,2}[\.、]|[一二三四五六七八九十]{1,3}[、.])\s*", "", text)
    text = text.strip("；;—–- ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_story_event_text_by_markers(text: str) -> List[str]:
    matches = list(_INLINE_EVENT_MARKER_PATTERN.finditer(text))
    if len(matches) < 2:
        return []

    items: List[str] = []
    for index, match in enumerate(matches):
        start = match.start("marker")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        item = _clean_story_event_item(text[start:end])
        if item:
            items.append(item)
    return items


def split_story_event_items(value: Any, *, limit: Optional[int] = None) -> List[str]:
    """Split dense story-event text into stable event items."""
    if value is None:
        return []

    if isinstance(value, list):
        items: List[str] = []
        for item in value:
            items.extend(split_story_event_items(item))
            if limit is not None and len(items) >= limit:
                return items[:limit]
        return items[:limit] if limit is not None else items

    if isinstance(value, dict):
        for key in ("content", "description", "summary", "event", "name"):
            text = split_story_event_items(value.get(key), limit=limit)
            if text:
                return text
        return []

    text = normalize_story_text(value).strip()
    if not text:
        return []

    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if parsed is not None:
            return split_story_event_items(parsed, limit=limit)

    raw_items: List[str] = []
    marker_items = _split_story_event_text_by_markers(text)
    if marker_items:
        raw_items.extend(marker_items)
    else:
        lines = [_clean_story_event_item(line) for line in text.splitlines()]
        raw_items.extend(line for line in lines if line)

        if len(raw_items) <= 1:
            separator_items = [
                _clean_story_event_item(part)
                for part in _STRONG_EVENT_SEPARATOR_PATTERN.split(text)
            ]
            separator_items = [part for part in separator_items if part]
            if 2 <= len(separator_items) <= 8:
                raw_items = separator_items

    deduped: List[str] = []
    seen = set()
    for item in raw_items:
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
        if limit is not None and len(deduped) >= limit:
            break

    return deduped[:limit] if limit is not None else deduped


def parse_chapter_number_token(token: str) -> Optional[int]:
    if token is None:
        return None

    value = str(token).strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)

    total = 0
    section = 0
    number = 0

    for char in value:
        if char in _CHINESE_DIGITS:
            number = _CHINESE_DIGITS[char]
            continue

        unit = _CHINESE_UNITS.get(char)
        if unit is None:
            return None

        if unit == 10000:
            section = (section + (number or 0)) * unit
            total += section
            section = 0
            number = 0
            continue

        section += (number or 1) * unit
        number = 0

    result = total + section + number
    return result if result > 0 or value in {"零", "〇"} else None


def extract_preferred_character_name(raw_name: str) -> str:
    text = str(raw_name or "").strip()
    if not text:
        return ""

    text = re.sub(r"^\*+|\*+$", "", text).strip()
    text = re.sub(r"\s*[（(][^()（）]{1,40}[)）]\s*$", "", text).strip()
    parts = [segment.strip() for segment in re.split(r"\s*/\s*|[|｜]", text) if segment.strip()]
    if not parts:
        parts = [text]

    cleaned_parts: List[str] = []
    for part in parts:
        candidate = part.strip()
        candidate = re.sub(r"^#+\s*", "", candidate)
        candidate = candidate.strip("“”\"'‘’")
        candidate = re.sub(r"编号\s*\d+", "", candidate).strip()
        candidate = re.sub(r"[【】\[\]<>《》]", "", candidate)
        candidate = re.sub(r"\s+", "", candidate)
        if candidate:
            cleaned_parts.append(candidate)

    if not cleaned_parts:
        return ""

    for candidate in reversed(cleaned_parts):
        if candidate not in _UNKNOWN_NAME_MARKERS:
            return candidate
    return cleaned_parts[0]
