from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.services.story_text_utils import (
    normalize_story_text,
    parse_chapter_number_token,
    split_story_event_items,
)

logger = logging.getLogger(__name__)

CHINESE_CHAPTER_NUMBER_PATTERN = r"[0-9一二三四五六七八九十百千万零两〇]+"
CHAPTER_HEADING_PATTERN = re.compile(
    rf"(?m)^(?P<prefix>#{{1,6}}\s*)?(?:\*\*)?\s*(?:新增\s*)?(?:[一二三四五六七八九十百千万零两〇]+[、.．]\s*)?"
    rf"第\s*(?P<number>{CHINESE_CHAPTER_NUMBER_PATTERN})\s*章(?:\s*[：:、\-]\s*|\s+)?"
    rf"(?P<title>[^\n]*?)\s*(?:\*\*)?\s*$"
)
CHARACTER_NAME_PATTERN = re.compile(
    r"(?m)^(?:###\s*)?(?:\*\*)?【姓名】(?:：|:)\s*(?P<name>.+?)\s*(?:\*\*)?\s*$"
)
LEGACY_ALIGNMENT_PLACEHOLDER_PATTERN = re.compile(
    r"^(?P<prefix>\s*-\s*)?(?P<label>人物承接|协同角色承接)[：:]\s*(?P<name>.+?)\s+在本章正式出场，并与当前主线形成明确关联。?\s*$"
)
OUTLINE_ROUND_SECTION_HEADING_PATTERN = re.compile(r"^\s*##\s*协同新增章节规划（第\d+轮）\s*$")
OUTLINE_FIELD_ALIASES: Dict[str, str] = {
    "场景目标": "scene_goal",
    "冲突设计": "conflict_design",
    "爽点类型": "highlight_type",
    "涉及人物": "involved_characters",
    "结尾钩子": "ending_hook",
    "伏笔事项": "foreshadowing_item",
    "关键事件": "key_events",
    "人物推进": "character_progress",
    "情节作用": "plot_function",
}
OUTLINE_FIELD_LINE_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(?P<label>"
    + "|".join(re.escape(label) for label in OUTLINE_FIELD_ALIASES)
    + r")(?:\*\*)?\s*[：:]\s*(?P<value>.*)$"
)
OUTLINE_LOOSE_FIELD_LINE_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(?P<label>"
    + "|".join(re.escape(label) for label in OUTLINE_FIELD_ALIASES)
    + r")(?:\*\*)?\s*[：:】]\s*(?P<value>.*)$"
)
OUTLINE_UNKNOWN_FIELD_LINE_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?[^：:\n]{1,16}(?:\*\*)?\s*[：:]\s*.*$"
)
OUTLINE_TAIL_SECTION_HEADING_PATTERN = re.compile(
    r"(?m)^\s*##\s*(?:\*\*)?\s*(?:[一二三四五六七八九十0-9]+[、.．]\s*)?"
    r"(?P<title>伏笔埋设检查|卷尾衔接检查|协同角色承接待补|人物承接待补)\s*(?:\*\*)?\s*$"
)
ALIGNMENT_PLACEHOLDER_FRAGMENT_PATTERN = re.compile(
    r"(?:^|\s)[\-*]?\s*(?:人物承接待补|协同角色承接待补)[：:]\s*"
    r"[^。\n]+?需在后续章节中正式出场，并与当前主线形成明确关联。?"
)
LEGACY_ALIGNMENT_PLACEHOLDER_FRAGMENT_PATTERN = re.compile(
    r"(?:^|\s)[\-*]?\s*(?:人物承接|协同角色承接)[：:]\s*"
    r"[^。\n]+?在本章正式出场，并与当前主线形成明确关联。?"
)
OUTLINE_TABLE_SEPARATOR_CELL_PATTERN = re.compile(r"^:?-{3,}:?$")


@dataclass
class OutlineBlock:
    original_number: int
    title: str
    body: str
    locked: bool = True
    source: str = "existing"
    anchor_after: Optional[int] = None


def normalize_character_name(name: str) -> str:
    if not name:
        return ""
    value = str(name).strip()
    value = re.sub(r"\*+", "", value)
    value = re.sub(r"^\d+[\.\、．\)\）]\s*", "", value)
    value = re.sub(r"^[一二三四五六七八九十百千万零两〇]+[、.．]\s*", "", value)
    value = re.sub(r"^[\"'“‘《「『][^\"'”’》」』]{1,12}[\"'”’》」』]\s*(?=.)", "", value)
    value = re.sub(r"[（(].*?[)）]$", "", value).strip()
    value = re.sub(r"\s+", "", value)
    value = value.replace("：", "").replace(":", "")
    value = value.strip("\"'“”‘’《》「」『』")
    return value


def parse_outline_blocks(text: str) -> Tuple[str, List[OutlineBlock]]:
    normalized_text = normalize_story_text(text)
    if not normalized_text or not normalized_text.strip():
        return "", []

    matches = list(CHAPTER_HEADING_PATTERN.finditer(normalized_text))
    if not matches:
        return normalized_text.strip(), []

    prefix = normalized_text[: matches[0].start()].rstrip()
    blocks: List[OutlineBlock] = []

    for index, match in enumerate(matches):
        chapter_number = parse_chapter_number_token(match.group("number"))
        if chapter_number is None:
            continue
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized_text)
        body = normalized_text[body_start:body_end].lstrip("\r\n").rstrip()
        title = (match.group("title") or "").strip()
        if title in {"", "大纲"}:
            title_match = re.search(
                r"(?m)^\s*\*\*章节标题建议\*\*\s*[：:]\s*[《<「『]?(?P<title>[^\n》>」』]+)",
                body,
            )
            title = (title_match.group("title") or "").strip() if title_match else ""
        blocks.append(
            OutlineBlock(
                original_number=int(chapter_number),
                title=title,
                body=body,
            )
        )

    return prefix, blocks


def render_outline(prefix: str, blocks: List[OutlineBlock]) -> str:
    parts: List[str] = []
    if prefix and prefix.strip():
        parts.append(prefix.strip())

    for index, block in enumerate(blocks, start=1):
        heading = f"第{index}章"
        normalized_title = normalize_outline_title(block.title)
        if normalized_title:
            heading = f"{heading}：{normalized_title}"
        parts.append(f"{heading}\n{block.body}".rstrip())

    return "\n\n".join(part for part in parts if part and part.strip())


def render_outline_with_original_numbers(prefix: str, blocks: List[OutlineBlock]) -> str:
    parts: List[str] = []
    if prefix and prefix.strip():
        parts.append(prefix.strip())

    for index, block in enumerate(blocks, start=1):
        chapter_number = int(block.original_number or index)
        heading = f"第{chapter_number}章"
        normalized_title = normalize_outline_title(block.title)
        if normalized_title:
            heading = f"{heading}：{normalized_title}"
        parts.append(f"{heading}\n{block.body}".rstrip())

    return "\n\n".join(part for part in parts if part and part.strip())


def extract_outline_tail_sections(text: str) -> List[str]:
    normalized_text = normalize_story_text(text)
    if not normalized_text or not normalized_text.strip():
        return []

    matches = list(OUTLINE_TAIL_SECTION_HEADING_PATTERN.finditer(normalized_text))
    if not matches:
        return []

    sections: List[str] = []
    for index, match in enumerate(matches):
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized_text)
        section_text = normalized_text[match.start():section_end].strip()
        if section_text:
            sections.append(section_text)
    return sections


def append_preserved_outline_tail_sections(text: str, tail_sections: List[str]) -> str:
    base_text = normalize_story_text(text).strip()
    if not tail_sections:
        return base_text

    existing_titles = {
        match.group("title")
        for match in OUTLINE_TAIL_SECTION_HEADING_PATTERN.finditer(base_text)
        if match.group("title")
    }
    parts: List[str] = [base_text] if base_text else []

    for section in tail_sections:
        normalized_section = normalize_story_text(section).strip()
        if not normalized_section:
            continue
        heading_match = OUTLINE_TAIL_SECTION_HEADING_PATTERN.search(normalized_section)
        title = heading_match.group("title") if heading_match else ""
        if title and title in existing_titles:
            continue
        parts.append(normalized_section)
        if title:
            existing_titles.add(title)

    return "\n\n".join(part for part in parts if part)


def normalize_outline_title(title: str) -> str:
    value = normalize_story_text(title or "").strip()
    if not value:
        return ""
    value = re.sub(r"^[#*\s]+", "", value).strip()
    value = re.sub(
        rf"^第\s*{CHINESE_CHAPTER_NUMBER_PATTERN}\s*章(?:[：:、\-\s]+)?",
        "",
        value,
    ).strip()
    return value


def _same_outline_value(left: str, right: str) -> bool:
    normalized_left = re.sub(r"[\s：:，,。、“”‘’\"'《》「」『』\-_*（）()]+", "", str(left or ""))
    normalized_right = re.sub(r"[\s：:，,。、“”‘’\"'《》「」『』\-_*（）()]+", "", str(right or ""))
    return bool(normalized_left) and normalized_left == normalized_right


def _normalize_outline_field_label(label: str) -> str:
    value = normalize_story_text(label or "").strip().strip("|").strip()
    if not value:
        return ""
    value = re.sub(r"^\*+|\*+$", "", value).strip()
    value = re.sub(r"[：:】]+$", "", value).strip()
    value = re.sub(r"\s+", "", value)
    return value if value in OUTLINE_FIELD_ALIASES else ""


def _split_outline_table_cells(line: str) -> List[str]:
    stripped = normalize_story_text(line or "").strip()
    if not stripped.startswith("|"):
        return []
    inner = stripped[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [cell.strip() for cell in inner.split("|")]


def _is_outline_table_separator_row(cells: List[str]) -> bool:
    return bool(cells) and all(
        not cell or OUTLINE_TABLE_SEPARATOR_CELL_PATTERN.match(cell)
        for cell in cells
    )


def _parse_loose_outline_field_line(line: str) -> Optional[Tuple[str, str]]:
    match = OUTLINE_LOOSE_FIELD_LINE_PATTERN.match(normalize_story_text(line or "").strip())
    if not match:
        return None
    label = _normalize_outline_field_label(match.group("label"))
    if not label:
        return None
    return OUTLINE_FIELD_ALIASES[label], str(match.group("value") or "").strip()


def _parse_outline_table_field_line(line: str) -> Optional[Tuple[str, str]]:
    cells = _split_outline_table_cells(line)
    if not cells or _is_outline_table_separator_row(cells):
        return None

    label = _normalize_outline_field_label(cells[0])
    if label:
        value = " | ".join(cell for cell in cells[1:] if str(cell).strip()).strip()
        return OUTLINE_FIELD_ALIASES[label], value

    return _parse_loose_outline_field_line(cells[0])


def _strip_alignment_placeholder_fragments(value: str) -> str:
    text = normalize_story_text(value or "").strip()
    if not text:
        return ""
    text = ALIGNMENT_PLACEHOLDER_FRAGMENT_PATTERN.sub(" ", text)
    text = LEGACY_ALIGNMENT_PLACEHOLDER_FRAGMENT_PATTERN.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    repeated_match = re.match(r"^(.{8,}?)(?:\s+\1)+$", text)
    if repeated_match:
        return repeated_match.group(1).strip()
    return text


def _append_outline_field_part(fields: Dict[str, List[str]], key: str, value: str) -> None:
    cleaned = _strip_alignment_placeholder_fragments(value)
    if not cleaned:
        return
    fields.setdefault(key, []).append(cleaned)


def _dedupe_outline_field_parts(parts: List[str]) -> str:
    deduped: List[str] = []
    seen = set()
    for part in parts:
        cleaned = _strip_alignment_placeholder_fragments(part)
        if not cleaned:
            continue
        key = re.sub(r"\s+", "", cleaned)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return "\n".join(deduped).strip()


def _extract_outline_body_fields(body: str) -> Tuple[Dict[str, str], List[str]]:
    fields: Dict[str, List[str]] = {}
    extra_lines: List[str] = []
    current_key: Optional[str] = None

    for raw_line in normalize_story_text(body or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if is_character_alignment_placeholder_line(stripped):
            current_key = None
            continue
        if OUTLINE_ROUND_SECTION_HEADING_PATTERN.match(stripped):
            current_key = None
            continue

        table_cells = _split_outline_table_cells(stripped)
        if table_cells:
            normalized_cells = [normalize_story_text(cell).strip() for cell in table_cells]
            if _is_outline_table_separator_row(table_cells):
                current_key = None
                continue
            if len(normalized_cells) >= 2 and normalized_cells[0] == "字段" and normalized_cells[1] == "内容":
                current_key = None
                continue

            parsed_table_field = _parse_outline_table_field_line(stripped)
            if parsed_table_field:
                current_key, value = parsed_table_field
                fields.setdefault(current_key, [])
                _append_outline_field_part(fields, current_key, value)
                continue

            current_key = None
            cleaned = _strip_alignment_placeholder_fragments(stripped)
            if cleaned:
                extra_lines.append(cleaned)
            continue

        match = OUTLINE_FIELD_LINE_PATTERN.match(stripped)
        if match:
            current_key = OUTLINE_FIELD_ALIASES[match.group("label")]
            fields.setdefault(current_key, [])
            value = str(match.group("value") or "").strip()
            _append_outline_field_part(fields, current_key, value)
            continue

        parsed_loose_field = _parse_loose_outline_field_line(stripped)
        if parsed_loose_field:
            current_key, value = parsed_loose_field
            fields.setdefault(current_key, [])
            _append_outline_field_part(fields, current_key, value)
            continue

        if OUTLINE_UNKNOWN_FIELD_LINE_PATTERN.match(stripped):
            current_key = None
            cleaned = _strip_alignment_placeholder_fragments(stripped)
            if cleaned:
                extra_lines.append(cleaned)
            continue

        if current_key:
            _append_outline_field_part(fields, current_key, stripped)
        else:
            cleaned = _strip_alignment_placeholder_fragments(stripped)
            if cleaned:
                extra_lines.append(cleaned)

    return (
        {key: _dedupe_outline_field_parts(parts) for key, parts in fields.items()},
        extra_lines,
    )


def _normalize_outline_character_list(value: str) -> str:
    parts = re.split(r"[、,，/／；;\s]+", str(value or "").strip())
    deduped: List[str] = []
    seen = set()
    for part in parts:
        normalized = normalize_character_name(part)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return "、".join(deduped)


def _extract_outline_involved_characters(
    title: str,
    fields: Dict[str, str],
    known_character_names: List[str],
) -> str:
    existing = _normalize_outline_character_list(fields.get("involved_characters", ""))
    if existing:
        return existing

    search_parts = [title]
    search_parts.extend(str(value or "") for value in fields.values())
    search_text = "\n".join(search_parts)

    matches: List[str] = []
    seen = set()
    for name in known_character_names:
        normalized = normalize_character_name(name)
        if not normalized or normalized in seen:
            continue
        if normalized in search_text:
            matches.append(normalized)
            seen.add(normalized)

    if "主角" in search_text and known_character_names:
        protagonist = normalize_character_name(known_character_names[0])
        if protagonist and protagonist not in seen:
            matches.insert(0, protagonist)

    return "、".join(matches)

r'''Temporarily quarantined corrupted legacy key-event normalization block.
def _normalize_key_event_lines(value: str) -> List[str]:
    items: List[str] = []
    for raw_line in normalize_story_text(value or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^\d+[\.\、．]\s*", "", stripped)
        stripped = re.sub(r"^[-*]\s*", "", stripped)
        if stripped:
            items.append(stripped)
    return [f"{index}. {item}" for index, item in enumerate(items, start=1)]


def _summarize_key_events(value: str) -> str:
    items = [re.sub(r"^\d+[\.\、．]\s*", "", item).strip() for item in _normalize_key_event_lines(value)]
    items = [item for item in items if item]
    if not items:
        return ""
    summary = "；".join(items[:3])
    return summary[:120].rstrip("；")


def _normalize_key_event_lines(value: str) -> List[str]:
    items = split_story_event_items(value, limit=5)
    return [f"{index}. {item}" for index, item in enumerate(items, start=1)]


def _summarize_key_events(value: str) -> str:
    items = split_story_event_items(value, limit=3)
    if not items:
        return ""
    summary = "锛?.join(items[:3])
    return summary[:120].rstrip("锛?)


def normalize_outline_text(text: str, characters_text: str = "") -> str:
    sanitized_text = sanitize_outline_alignment_placeholders(text or "")
    tail_sections = extract_outline_tail_sections(sanitized_text)
    tail_match = OUTLINE_TAIL_SECTION_HEADING_PATTERN.search(sanitized_text)
    body_text = sanitized_text[:tail_match.start()].rstrip() if tail_match else sanitized_text

    prefix, blocks = parse_outline_blocks(body_text)
    if not blocks:
        return append_preserved_outline_tail_sections(body_text.strip(), tail_sections)

    known_character_names = extract_character_names(characters_text or "")
    normalized_blocks: List[OutlineBlock] = []

    for block in blocks:
        title = normalize_outline_title(block.title) or f"第{int(block.original_number or 0) or 1}章"
        fields, extra_lines = _extract_outline_body_fields(block.body)
        raw_summary = " ".join(extra_lines).strip()
        key_events_lines = _normalize_key_event_lines(fields.get("key_events", ""))
        key_events_summary = _summarize_key_events(fields.get("key_events", ""))

        scene_goal = str(fields.get("scene_goal") or raw_summary or "").strip()
        if not scene_goal:
            scene_goal = f"围绕“{title}”推进本章主线，并完成阶段性目标。"

        conflict_design = str(fields.get("conflict_design") or "").strip()
        if not conflict_design or _same_outline_value(conflict_design, scene_goal):
            conflict_design = key_events_summary or f"主角在推进“{title}”时遭遇新阻碍，并在冲突升级后完成阶段性突破。"

        highlight_type = str(fields.get("highlight_type") or "").strip()

        involved_characters = _extract_outline_involved_characters(title, fields, known_character_names) or "待补充"

        character_progress = str(fields.get("character_progress") or "").strip()
        if not character_progress:
            if involved_characters != "待补充":
                character_progress = f"{involved_characters}在本章中的立场、关系或状态出现推进。"
            else:
                character_progress = "主角与关键角色状态发生变化，为后续冲突积累势能。"

        plot_function = str(fields.get("plot_function") or "").strip()
        if not plot_function:
            plot_function = f"承接“{title}”并推动阶段矛盾继续升级。"

        ending_hook = str(fields.get("ending_hook") or "").strip()
        if not ending_hook or _same_outline_value(ending_hook, highlight_type):
            ending_hook = f"新的危机与线索同步出现，把主线推进到“{title}”之后的下一阶段。"

        foreshadowing_item = str(fields.get("foreshadowing_item") or "").strip()

        body_lines = [
            f"- 场景目标：{scene_goal}",
            f"- 冲突设计：{conflict_design}",
            f"- 涉及人物：{involved_characters}",
            f"- 人物推进：{character_progress}",
            f"- 情节作用：{plot_function}",
            f"- 结尾钩子：{ending_hook}",
        ]
        if key_events_lines:
            body_lines.append("- 关键事件：")
            body_lines.extend(key_events_lines)
        else:
            body_lines.append("- 关键事件：待补充")
        if highlight_type:
            body_lines.append(f"- 爽点类型：{highlight_type}")
        if foreshadowing_item:
            body_lines.append(f"- 伏笔事项：{foreshadowing_item}")

        key_events_text = _summarize_key_events(fields.get("key_events", "")) or "寰呰ˉ鍏?"
        base_body_lines = body_lines[:6]
        remaining_body_lines = body_lines[7 + len(key_events_lines):] if key_events_lines else body_lines[7:]
        body_lines = [
            base_body_lines[0],
            base_body_lines[1],
            f"- 鍏抽敭浜嬩欢锛歿key_events_text}",
            base_body_lines[2],
            base_body_lines[3],
            base_body_lines[4],
            base_body_lines[5],
            *remaining_body_lines,
        ]

        normalized_blocks.append(
            OutlineBlock(
                original_number=int(block.original_number or 0),
                title=title,
                body="\n".join(body_lines).strip(),
                locked=block.locked,
                source=block.source,
                anchor_after=block.anchor_after,
            )
        )

    cleaned_prefix = "\n".join(
        line
        for line in normalize_story_text(prefix or "").splitlines()
        if not OUTLINE_ROUND_SECTION_HEADING_PATTERN.match(line.strip())
    ).strip()
    normalized_text = render_outline_with_original_numbers(cleaned_prefix, normalized_blocks)
    return append_preserved_outline_tail_sections(normalized_text, tail_sections)

'''


def _normalize_key_event_lines(value: str) -> List[str]:
    items = split_story_event_items(value, limit=5)
    return [f"{index}. {item}" for index, item in enumerate(items, start=1)]


def _summarize_key_events(value: str, *, limit: int = 3, max_length: int = 120) -> str:
    items = split_story_event_items(value, limit=limit)
    if not items:
        return ""
    summary = "；".join(items[:limit]).strip()
    return summary[:max_length].rstrip("；")


def _resolve_key_events_summary(raw_value: str, extra_lines: List[str]) -> str:
    summary = _summarize_key_events(raw_value)
    if summary:
        return summary

    fallback_text = " ".join(line.strip() for line in extra_lines if str(line).strip()).strip()
    fallback_items = split_story_event_items(fallback_text, limit=3)
    if len(fallback_items) >= 2:
        return "；".join(fallback_items).rstrip("；")
    return ""


def normalize_outline_text(text: str, characters_text: str = "") -> str:
    sanitized_text = sanitize_outline_alignment_placeholders(text or "")
    tail_sections = extract_outline_tail_sections(sanitized_text)
    tail_match = OUTLINE_TAIL_SECTION_HEADING_PATTERN.search(sanitized_text)
    body_text = sanitized_text[:tail_match.start()].rstrip() if tail_match else sanitized_text

    prefix, blocks = parse_outline_blocks(body_text)
    if not blocks:
        return append_preserved_outline_tail_sections(body_text.strip(), tail_sections)

    known_character_names = extract_character_names(characters_text or "")
    normalized_blocks: List[OutlineBlock] = []

    for block in blocks:
        title = normalize_outline_title(block.title) or f"第{int(block.original_number or 0) or 1}章"
        fields, extra_lines = _extract_outline_body_fields(block.body)
        raw_summary = " ".join(extra_lines).strip()
        key_events_text = _resolve_key_events_summary(fields.get("key_events", ""), extra_lines)

        scene_goal = str(fields.get("scene_goal") or raw_summary or "").strip()
        if not scene_goal:
            scene_goal = f"围绕《{title}》推进本章主线，并完成阶段性目标。"

        conflict_design = str(fields.get("conflict_design") or "").strip()
        if not conflict_design or _same_outline_value(conflict_design, scene_goal):
            conflict_design = key_events_text or f"主角在推进《{title}》时遭遇新阻碍，并在冲突升级后完成阶段性突破。"

        highlight_type = str(fields.get("highlight_type") or "").strip()
        involved_characters = _extract_outline_involved_characters(title, fields, known_character_names) or "待补充"

        character_progress = str(fields.get("character_progress") or "").strip()
        if not character_progress:
            if involved_characters != "待补充":
                character_progress = f"{involved_characters}在本章中的立场、关系或状态出现推进。"
            else:
                character_progress = "主角与关键角色状态发生变化，为后续冲突积累势能。"

        plot_function = str(fields.get("plot_function") or "").strip()
        if not plot_function:
            plot_function = f"承接《{title}》并推动阶段矛盾继续升级。"

        ending_hook = str(fields.get("ending_hook") or "").strip()
        if not ending_hook or _same_outline_value(ending_hook, highlight_type):
            ending_hook = f"新的危机与线索同步出现，把主线推进到《{title}》之后的下一阶段。"

        foreshadowing_item = str(fields.get("foreshadowing_item") or "").strip()

        body_lines = [
            f"- 场景目标：{scene_goal}",
            f"- 冲突设计：{conflict_design}",
            f"- 关键事件：{key_events_text or '待补充'}",
            f"- 涉及人物：{involved_characters}",
            f"- 人物推进：{character_progress}",
            f"- 情节作用：{plot_function}",
            f"- 结尾钩子：{ending_hook}",
        ]
        if highlight_type:
            body_lines.append(f"- 爽点类型：{highlight_type}")
        if foreshadowing_item:
            body_lines.append(f"- 伏笔事项：{foreshadowing_item}")

        normalized_blocks.append(
            OutlineBlock(
                original_number=int(block.original_number or 0),
                title=title,
                body="\n".join(body_lines).strip(),
                locked=block.locked,
                source=block.source,
                anchor_after=block.anchor_after,
            )
        )

    cleaned_prefix = "\n".join(
        line
        for line in normalize_story_text(prefix or "").splitlines()
        if not OUTLINE_ROUND_SECTION_HEADING_PATTERN.match(line.strip())
    ).strip()
    normalized_text = render_outline_with_original_numbers(cleaned_prefix, normalized_blocks)
    return append_preserved_outline_tail_sections(normalized_text, tail_sections)


def extract_character_names(text: str) -> List[str]:
    normalized_text = normalize_story_text(text)
    if not normalized_text or not normalized_text.strip():
        return []

    names: List[str] = []
    seen = set()
    for match in CHARACTER_NAME_PATTERN.finditer(normalized_text):
        normalized = normalize_character_name(match.group("name"))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(normalized)

    if names:
        return names

    try:
        from app.services.character_parser import CharacterTextParser

        parsed_characters = CharacterTextParser().parse_all_characters(normalized_text)
        for character in parsed_characters:
            normalized = normalize_character_name(getattr(character, "name", ""))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            names.append(normalized)
    except Exception:
        pass

    return names


def extract_character_blocks(text: str) -> List[Tuple[str, str]]:
    normalized_text = normalize_story_text(text)
    if not normalized_text or not normalized_text.strip():
        return []

    matches = list(CHARACTER_NAME_PATTERN.finditer(normalized_text))
    blocks: List[Tuple[str, str]] = []
    seen = set()

    if matches:
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized_text)
            block_text = normalized_text[start:end].strip()
            block_text = re.sub(r"(?ms)\n?---\s*$", "", block_text).rstrip()
            normalized_name = normalize_character_name(match.group("name"))
            if normalized_name and block_text and normalized_name not in seen:
                seen.add(normalized_name)
                blocks.append((normalized_name, block_text))

    if blocks:
        return blocks

    try:
        from app.services.character_parser import CharacterTextParser

        parsed_characters = CharacterTextParser().parse_all_characters(normalized_text)
        for character in parsed_characters:
            normalized_name = normalize_character_name(getattr(character, "name", ""))
            block_text = str(getattr(character, "raw_text", "") or "").strip()
            if not normalized_name or not block_text or normalized_name in seen:
                continue
            seen.add(normalized_name)
            blocks.append((normalized_name, block_text))
    except Exception:
        pass

    return blocks


def build_delta_section_title(base_title: str, existing_text: str) -> str:
    existing_rounds = re.findall(rf"(?m)^##\s*{re.escape(base_title)}", existing_text or "")
    return f"{base_title}（第{len(existing_rounds) + 1}轮）"


def merge_character_delta(
    existing_characters: str,
    new_character_cards: str,
    relationship_patch: str,
) -> str:
    normalized_existing = normalize_story_text(existing_characters)
    parts: List[str] = []
    if normalized_existing and normalized_existing.strip():
        parts.append(normalized_existing.rstrip())

    if new_character_cards and new_character_cards.strip():
        role_title = build_delta_section_title("协同新增角色", normalized_existing)
        parts.append(f"## {role_title}\n\n{new_character_cards.strip()}")

    if relationship_patch and relationship_patch.strip():
        relation_title = build_delta_section_title("协同新增关系", normalized_existing)
        parts.append(f"## {relation_title}\n\n{relationship_patch.strip()}")

    return "\n\n".join(part for part in parts if part and part.strip())


def build_outline_delta_section(existing_outline: str, generated_chapters: str) -> str:
    if not generated_chapters or not generated_chapters.strip():
        return existing_outline.strip()

    prefix, existing_blocks = parse_outline_blocks(existing_outline or "")
    _, generated_blocks = parse_outline_blocks(generated_chapters or "")
    if existing_blocks and generated_blocks:
        return render_outline_with_original_numbers(prefix, [*existing_blocks, *generated_blocks])

    section_title = build_delta_section_title("协同新增章节规划", existing_outline)
    if existing_outline and existing_outline.strip():
        return f"{existing_outline.rstrip()}\n\n## {section_title}\n\n{generated_chapters.strip()}"
    return generated_chapters.strip()


def sanitize_outline_alignment_placeholders(text: str) -> str:
    normalized_text = normalize_story_text(text)
    if not normalized_text or not normalized_text.strip():
        return normalized_text

    sanitized_lines: List[str] = []
    for line in normalized_text.splitlines():
        normalized_line = line.strip()
        legacy_match = LEGACY_ALIGNMENT_PLACEHOLDER_PATTERN.match(normalized_line)
        if not legacy_match:
            sanitized_lines.append(line)
            continue

        name = normalize_character_name(legacy_match.group("name"))
        if not name:
            sanitized_lines.append(line)
            continue

        prefix = legacy_match.group("prefix") or "- "
        label = (
            "协同角色承接待补"
            if "协同角色" in str(legacy_match.group("label") or "")
            else "人物承接待补"
        )
        sanitized_lines.append(
            f"{prefix}{label}：{name} 需在后续章节中正式出场，并与当前主线形成明确关联。"
        )

    return "\n".join(sanitized_lines)


def is_character_alignment_placeholder_line(line: str) -> bool:
    normalized_line = normalize_story_text(line or "").strip()
    if not normalized_line:
        return False
    if "人物承接待补" in normalized_line or "协同角色承接待补" in normalized_line:
        return True
    return bool(LEGACY_ALIGNMENT_PLACEHOLDER_PATTERN.match(normalized_line))


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def evaluate_story_coordination(
    outline_text: str,
    characters_text: str,
) -> Dict[str, Any]:
    sanitized_outline_text = sanitize_outline_alignment_placeholders(outline_text or "")
    _, outline_blocks = parse_outline_blocks(sanitized_outline_text)
    character_names = extract_character_names(characters_text or "")

    outline_reference_text = "\n".join(
        line
        for line in sanitized_outline_text.splitlines()
        if not is_character_alignment_placeholder_line(line)
    )
    referenced_characters = [name for name in character_names if name and name in outline_reference_text]
    unreferenced_characters = [name for name in character_names if name not in referenced_characters]

    chapter_count = len(outline_blocks)
    character_count = len(character_names)
    coverage_ratio = (len(referenced_characters) / character_count) if character_count else 0.0
    chapters_per_character = (chapter_count / character_count) if character_count else 0.0

    score = 35
    score += int(min(35, coverage_ratio * 35))
    score += int(min(15, chapter_count))
    score += int(min(15, chapters_per_character * 3))
    score = max(0, min(100, score))

    suggestions: List[str] = []
    if chapter_count == 0:
        suggestions.append("当前大纲缺少可定位章节，建议先生成章节卡，再做中段插入式拓展。")
    if unreferenced_characters:
        suggestions.append("存在未被大纲引用的人物，优先为这些角色补充登场章节或职责。")
    if character_count and coverage_ratio < 0.6:
        suggestions.append("人物与章节覆盖率偏低，新增章节时需要明确写出涉及人物与关系推进。")
    if chapter_count and not character_count:
        suggestions.append("大纲已具备章节结构，但人物档案不足，建议先补足关键功能角色。")
    if not suggestions:
        suggestions.append("当前人物与大纲的基础协同正常，适合继续做增量扩展。")

    return {
        "score": score,
        "chapter_count": chapter_count,
        "character_count": character_count,
        "coverage_ratio": round(coverage_ratio, 3),
        "referenced_characters": referenced_characters,
        "unreferenced_characters": unreferenced_characters,
        "suggestions": suggestions,
        "validation_stage": "chapter_level",
    }

