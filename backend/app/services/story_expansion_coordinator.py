from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.langchain_bridge import create_task_llm
from app.services.character_parser import (
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
)
from app.services.story_text_utils import (
    normalize_story_text,
    parse_chapter_number_token,
)


CHINESE_CHAPTER_NUMBER_PATTERN = r"[0-9一二三四五六七八九十百千万零两〇]+"
CHAPTER_HEADING_PATTERN = re.compile(
    rf"(?m)^(?P<prefix>#{{1,6}}\s*)?(?:\*\*)?\s*(?:[一二三四五六七八九十百千万零两〇]+[、.．]\s*)?"
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
OUTLINE_UNKNOWN_FIELD_LINE_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?[^：:\n]{1,16}(?:\*\*)?\s*[：:]\s*.*$"
)


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


def _extract_outline_body_fields(body: str) -> Tuple[Dict[str, str], List[str]]:
    fields: Dict[str, List[str]] = {}
    extra_lines: List[str] = []
    current_key: Optional[str] = None

    for raw_line in normalize_story_text(body or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if OUTLINE_ROUND_SECTION_HEADING_PATTERN.match(stripped):
            current_key = None
            continue

        match = OUTLINE_FIELD_LINE_PATTERN.match(stripped)
        if match:
            current_key = OUTLINE_FIELD_ALIASES[match.group("label")]
            fields.setdefault(current_key, [])
            value = str(match.group("value") or "").strip()
            if value:
                fields[current_key].append(value)
            continue

        if OUTLINE_UNKNOWN_FIELD_LINE_PATTERN.match(stripped):
            current_key = None
            extra_lines.append(stripped)
            continue

        if current_key:
            fields.setdefault(current_key, []).append(stripped)
        else:
            extra_lines.append(stripped)

    return (
        {key: "\n".join(part for part in parts if str(part).strip()).strip() for key, parts in fields.items()},
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


def normalize_outline_text(text: str, characters_text: str = "") -> str:
    sanitized_text = sanitize_outline_alignment_placeholders(text or "")
    prefix, blocks = parse_outline_blocks(sanitized_text)
    if not blocks:
        return sanitized_text.strip()

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
    return render_outline_with_original_numbers(cleaned_prefix, normalized_blocks)


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


class StoryExpansionCoordinator:
    SHORT_CHAPTER_DELTA_LIMIT = 30
    SHORT_CHARACTER_DELTA_LIMIT = 10
    ITERATIVE_CHAPTER_STEP = 15
    ITERATIVE_CHARACTER_STEP = 15
    ITERATIVE_MAX_ROUNDS = 40
    CONVENTIONAL_COLLABORATION_MAX_CHAPTER_DELTA = ITERATIVE_CHAPTER_STEP * ITERATIVE_MAX_ROUNDS
    CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS = 300
    CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS = CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
    LARGE_PROJECT_CHAPTER_THRESHOLD = 100
    SUPER_LARGE_PROJECT_CHAPTER_THRESHOLD = 200
    FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD = CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS + 1
    EPIC_CHAPTER_THRESHOLD = 800
    EPIC_DEFAULT_CHAPTERS_PER_VOLUME = 40
    EPIC_MIN_VOLUMES = 10
    EPIC_MAX_VOLUMES = 50
    CHARACTER_TARGET_MIN_CHAPTERS_PER_ROLE = 8
    CHARACTER_TARGET_MAX_CHAPTERS_PER_ROLE = 5
    AUTO_CHARACTER_INCREMENT_SOFT_CAP = 8
    EPIC_FRAMEWORK_AUTO_CHARACTER_INCREMENT_SOFT_CAP = 24
    EPIC_FRAMEWORK_AUTO_CHARACTER_INCREMENT_FLOOR = 10

    def __init__(
        self,
        project_id: Optional[int] = None,
        genre: str = "",
        planned_chapters_max: int = 0,
    ) -> None:
        self.project_id = project_id
        self.genre = genre or ""
        try:
            self.planned_chapters_max = max(0, int(planned_chapters_max or 0))
        except Exception:
            self.planned_chapters_max = 0

        # 🔥 动态模型选择：根据计划章节数选择合适的模型
        if self.planned_chapters_max > self.SUPER_LARGE_PROJECT_CHAPTER_THRESHOLD:
            # 超大规模项目（>200章）：使用 qwen3.5-plus（65K输出能力）
            model_type = "outline_expand"  # qwen3.5-plus
            logger.debug(f"🔄 检测到超大规模项目（{self.planned_chapters_max}章），使用 qwen3.5-plus 模型")
        elif self.planned_chapters_max > self.LARGE_PROJECT_CHAPTER_THRESHOLD:
            # 大规模项目（100-200章）：使用 deepseek-reasoner（推理能力强）
            model_type = "volume_detail_expand"  # deepseek-reasoner
            logger.debug(f"✅ 检测到大规模项目（{self.planned_chapters_max}章），使用 deepseek-reasoner 模型")
        else:
            # 常规项目（≤100章）：使用 qwen3.5-plus（输出能力强）
            model_type = "outline_expand"  # qwen3.5-plus
            logger.debug(f"✅ 常规项目（{self.planned_chapters_max}章），使用 qwen3.5-plus 模型")

        self.planner_llm = create_task_llm(task_type=model_type, temperature=0.2)
        self.writer_llm = create_task_llm(task_type=model_type, temperature=0.45)
        self._outline_expander: Optional[Any] = None

    def _invoke_text(self, prompt: str, *, use_planner: bool = False) -> str:
        llm = self.planner_llm if use_planner else self.writer_llm
        response = llm.invoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    def _invoke_json(self, prompt: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        raw_text = self._invoke_text(prompt, use_planner=True)
        parsed = self._extract_json(raw_text)
        if isinstance(parsed, dict):
            return parsed
        return fallback

    @staticmethod
    def _extract_json(text: str) -> Optional[Any]:
        if not text:
            return None

        text = text.strip()
        for candidate in (text, *re.findall(r"\{[\s\S]*\}", text)):
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    @staticmethod
    def _summarize_outline_blocks(blocks: List[OutlineBlock], limit: int = 60) -> str:
        if not blocks:
            return "暂无已分章内容"
        lines = []
        for block in blocks[:limit]:
            title = block.title or "未命名章节"
            lines.append(f"- 第{block.original_number}章：{title}")
        if len(blocks) > limit:
            lines.append(f"- ……其余 {len(blocks) - limit} 章已省略")
        return "\n".join(lines)

    @staticmethod
    def _normalize_outline_ops(
        outline_ops: List[Dict[str, Any]],
        chapters_needed: int,
        current_chapter_count: int,
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        remaining = max(0, chapters_needed)

        for raw_op in outline_ops:
            if remaining <= 0:
                break

            action = str(raw_op.get("action") or "append").strip()
            if action not in {"append", "insert_after"}:
                action = "append"

            try:
                count = int(raw_op.get("count") or 0)
            except Exception:
                count = 0

            if count <= 0:
                continue

            count = min(count, remaining)
            after_chapter = raw_op.get("after_chapter")
            if action == "append":
                after_chapter = current_chapter_count if current_chapter_count > 0 else None
            else:
                try:
                    after_chapter = int(after_chapter)
                except Exception:
                    after_chapter = current_chapter_count if current_chapter_count > 0 else None
                if current_chapter_count <= 0:
                    action = "append"
                    after_chapter = None
                else:
                    after_chapter = max(1, min(current_chapter_count, after_chapter))

            normalized.append(
                {
                    "action": action,
                    "after_chapter": after_chapter,
                    "count": count,
                    "goal": str(raw_op.get("goal") or "补充关键剧情推进").strip(),
                    "focus_characters": list(raw_op.get("focus_characters") or []),
                    "notes": str(raw_op.get("notes") or "").strip(),
                }
            )
            remaining -= count

        if remaining > 0:
            normalized.append(
                {
                    "action": "append",
                    "after_chapter": current_chapter_count if current_chapter_count > 0 else None,
                    "count": remaining,
                    "goal": "补充新增章节并延续主线",
                    "focus_characters": [],
                    "notes": "自动补足缺失章节数",
                }
            )

        return normalized

    def _get_expander(self) -> Any:
        if self._outline_expander is None:
            from .agents.outline_expander import create_outline_expander

            self._outline_expander = create_outline_expander(
                genre=self.genre,
                planned_chapters_max=self.planned_chapters_max,
                project_id=self.project_id,
            )
        return self._outline_expander

    @staticmethod
    def _get_llm_model_name(llm: Any, fallback: str = "unknown") -> str:
        return (
            getattr(llm, "model_name", None)
            or getattr(llm, "model", None)
            or fallback
        )

    @staticmethod
    def _coerce_non_negative_int(value: Any, fallback: int = 0) -> int:
        try:
            return max(0, int(value))
        except Exception:
            return max(0, int(fallback or 0))

    @classmethod
    def _resolve_outline_count(
        cls,
        outline_text: str,
        reported_count: Any,
        fallback_count: int,
    ) -> int:
        _, blocks = parse_outline_blocks(outline_text or "")
        parsed_max_number = max((int(block.original_number or 0) for block in blocks), default=0)
        fallback_value = cls._coerce_non_negative_int(fallback_count)
        reported_value = cls._coerce_non_negative_int(reported_count)
        if parsed_max_number > 0:
            return max(fallback_value, parsed_max_number)
        return max(fallback_value, reported_value)

    @classmethod
    def _resolve_character_count(
        cls,
        characters_text: str,
        reported_count: Any,
        fallback_count: int,
    ) -> int:
        parsed_count = len(extract_character_names(characters_text or ""))
        fallback_value = cls._coerce_non_negative_int(fallback_count)
        reported_value = cls._coerce_non_negative_int(reported_count)
        if parsed_count > 0:
            return max(fallback_value, parsed_count)
        return max(fallback_value, reported_value)

    @staticmethod
    def _reason_claims_target_already_satisfied(reason: str) -> bool:
        text = str(reason or "").strip()
        if not text:
            return False
        keywords = (
            "已包含",
            "已达到",
            "远超",
            "数量充足",
            "无需继续",
            "角色数量充足",
            "人物数充足",
            "目标已达成",
        )
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _reason_claims_no_effective_character_growth(reason: str) -> bool:
        text = str(reason or "").strip()
        if not text:
            return False
        keywords = (
            "未新增有效角色",
            "未产生新增内容",
            "本轮未新增",
            "没有新增角色",
        )
        return any(keyword in text for keyword in keywords)

    @classmethod
    def _normalize_outline_stop_reason(
        cls,
        reason: str,
        *,
        before_chapter_count: int,
        after_chapter_count: int,
        outline_delta: str,
    ) -> str:
        text = str(reason or "").strip()
        if after_chapter_count <= before_chapter_count and not str(outline_delta or "").strip():
            return "大纲扩展未产生新增章节，为避免空转已提前停止。"
        if "未提供具体的上下文或主题" in text:
            return "大纲扩展未产生可用章节规划，建议补充更明确的章节目标或承接点后再继续。"
        return text or "大纲侧模型建议停止继续扩展。"

    @classmethod
    def _normalize_character_stop_reason(
        cls,
        reason: str,
        *,
        before_character_count: int,
        after_character_count: int,
        target_character_count: int,
    ) -> str:
        text = str(reason or "").strip()
        if after_character_count <= before_character_count:
            return "人物扩展未产生新增内容，为避免空转已提前停止。"
        if cls._reason_claims_no_effective_character_growth(text):
            added_count = max(0, after_character_count - before_character_count)
            remaining = max(0, target_character_count - after_character_count)
            return (
                f"人物扩展已暂时停止，本轮仅新增 {added_count} 人，"
                f"距离目标仍差 {remaining} 人，建议继续补充关键角色并同步章节承接。"
            )
        if after_character_count < target_character_count and cls._reason_claims_target_already_satisfied(text):
            return "人物扩展已暂停，但当前目标尚未达成，建议先复核现有人物职责与剧情承接。"
        return text or "人物侧模型建议停止继续扩展。"

    @staticmethod
    def _intent_to_strategy(intent: str) -> str:
        mapping = {
            "outline_led": "plot_first",
            "character_led": "character_first",
            "balanced": "balanced",
        }
        return mapping.get(str(intent or "").strip(), "balanced")

    @staticmethod
    def _estimate_stage_model(task_type: str, fallback: str = "unknown") -> str:
        try:
            from core.model_runtime import resolve_model_for_task

            return resolve_model_for_task(task_type, None) or fallback
        except Exception:
            return fallback

    @staticmethod
    def _estimate_context_model(scenario: str, current_count: int, fallback: str = "unknown") -> str:
        try:
            from .agents.layered_summarizer import LayeredSummarizer

            return LayeredSummarizer.estimate_selected_model(scenario, current_count)
        except Exception:
            return fallback

    @classmethod
    def _should_upgrade_total_to_epic(
        cls,
        target_total_reference: int,
        chapters_needed: int,
    ) -> bool:
        return (
            int(target_total_reference or 0) >= cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD
            and int(chapters_needed or 0) > 0
        )

    @staticmethod
    def _estimate_volume_detail_outline_model(
        chapters_count_range: Optional[Tuple[int, int]],
        fallback: str = "deepseek-reasoner",
    ) -> str:
        try:
            from .agents.outline_expander import OutlineExpander

            return OutlineExpander.estimate_volume_detail_model(chapters_count_range or (0, 0))
        except Exception:
            return fallback

    def _estimate_outline_model_for_plan(
        self,
        *,
        execution_mode: str,
        target_chapter_count: int,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        if execution_mode == "epic":
            return self._estimate_stage_model("concept", "qwen3.5-plus")
        if execution_mode == "volume_detail":
            chapter_range = None
            if isinstance(volume_detail_config, dict):
                chapter_range = volume_detail_config.get("chapters_count_range")
            return self._estimate_volume_detail_outline_model(chapter_range)
        return self._estimate_context_model("outline_expand", target_chapter_count, "qwen3.5-plus")

    def _estimate_character_model_for_plan(self, target_character_count: int) -> str:
        return self._estimate_context_model("character_expand", target_character_count, "deepseek-reasoner")

    def _estimate_character_density_multiplier(self) -> float:
        genre_text = normalize_story_text(self.genre or "").lower()
        if not genre_text:
            return 1.0

        high_density_keywords = (
            "玄幻",
            "奇幻",
            "仙侠",
            "武侠",
            "权谋",
            "宫斗",
            "群像",
            "史诗",
            "西幻",
            "科幻",
            "赛博",
            "无限",
            "冒险",
            "fantasy",
            "epic",
            "ensemble",
            "wuxia",
            "xianxia",
            "sci-fi",
            "scifi",
        )
        low_density_keywords = (
            "言情",
            "恋爱",
            "悬疑",
            "推理",
            "治愈",
            "校园",
            "青春",
            "成长",
            "日常",
            "romance",
            "mystery",
            "slice of life",
            "coming-of-age",
        )

        has_high_density_signal = any(keyword in genre_text for keyword in high_density_keywords)
        has_low_density_signal = any(keyword in genre_text for keyword in low_density_keywords)

        if has_high_density_signal and not has_low_density_signal:
            return 1.15
        if has_low_density_signal and not has_high_density_signal:
            return 0.9
        return 1.0

    def _estimate_character_target_range(self, chapter_count: int) -> Tuple[int, int]:
        effective_chapter_count = max(1, self._coerce_non_negative_int(chapter_count, 1))
        density_multiplier = self._estimate_character_density_multiplier()
        recommended_min = max(
            1,
            int(
                math.ceil(
                    (effective_chapter_count / self.CHARACTER_TARGET_MIN_CHAPTERS_PER_ROLE)
                    * density_multiplier
                )
            ),
        )
        recommended_max = max(
            recommended_min,
            int(
                math.ceil(
                    (effective_chapter_count / self.CHARACTER_TARGET_MAX_CHAPTERS_PER_ROLE)
                    * density_multiplier
                )
            ),
        )
        return recommended_min, recommended_max

    def _estimate_total_chapters_for_character_target(
        self,
        *,
        current_chapter_count: int,
        target_character_count: int,
        expansion_mode: str,
    ) -> Tuple[int, bool]:
        current_count = max(0, self._coerce_non_negative_int(current_chapter_count))
        target_count = max(0, self._coerce_non_negative_int(target_character_count))
        if target_count <= 0:
            return current_count, False

        estimated_target = max(
            current_count,
            target_count * self.CHARACTER_TARGET_MAX_CHAPTERS_PER_ROLE,
        )
        capped_by_conventional_limit = False
        if (
            expansion_mode in {"auto", "total"}
            and current_count <= self.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
            and estimated_target > self.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
        ):
            estimated_target = self.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS
            capped_by_conventional_limit = True

        return estimated_target, capped_by_conventional_limit

    @staticmethod
    def _format_character_target_range_text(recommended_min: int, recommended_max: int) -> str:
        if recommended_min >= recommended_max:
            return f"{recommended_min}"
        return f"{recommended_min}-{recommended_max}"

    def _estimate_character_increment_cap(
        self,
        chapter_delta: int,
        *,
        expansion_mode: str,
    ) -> int:
        effective_delta = max(0, self._coerce_non_negative_int(chapter_delta))
        if effective_delta <= 0:
            return 0
        if expansion_mode == "volume_detail":
            return max(2, min(6, int(math.ceil(effective_delta / 8))))
        if expansion_mode == "epic_framework":
            return max(
                self.EPIC_FRAMEWORK_AUTO_CHARACTER_INCREMENT_FLOOR,
                min(
                    self.EPIC_FRAMEWORK_AUTO_CHARACTER_INCREMENT_SOFT_CAP,
                    int(math.ceil(effective_delta / 24)),
                ),
            )
        return max(2, min(self.AUTO_CHARACTER_INCREMENT_SOFT_CAP, int(math.ceil(effective_delta / 6))))

    @staticmethod
    def _resolve_volume_detail_target_span(volume_detail_config: Optional[Dict[str, Any]]) -> int:
        normalized = StoryExpansionCoordinator._normalize_volume_detail_config(volume_detail_config)
        chapter_window = normalized.get("chapters_count_range")
        if isinstance(chapter_window, tuple) and len(chapter_window) == 2:
            try:
                lower = max(1, int(chapter_window[0]))
                upper = max(lower, int(chapter_window[1]))
                return upper
            except Exception:
                pass

        chapter_range = normalized.get("expected_chapter_range")
        if isinstance(chapter_range, tuple) and len(chapter_range) == 2:
            try:
                start = int(chapter_range[0])
                end = int(chapter_range[1])
                return max(1, end - start + 1)
            except Exception:
                pass

        expected_total = max(0, int(normalized.get("expected_total_chapter_count") or 0))
        current_total = max(0, int(normalized.get("current_total_chapter_count") or 0))
        if expected_total > current_total:
            return expected_total - current_total

        return 0

    def _build_volume_detail_reference_text(
        self,
        volume_detail_config: Optional[Dict[str, Any]],
    ) -> str:
        normalized = self._normalize_volume_detail_config(volume_detail_config)
        parts: List[str] = []

        existing_volume_detail = str(normalized.get("existing_volume_detail") or "").strip()
        if existing_volume_detail:
            parts.append(existing_volume_detail)

        target_volume_index = normalized.get("target_volume_index")
        volumes_data = normalized.get("volumes_data")
        if isinstance(volumes_data, dict) and target_volume_index:
            volume_data = ((volumes_data.get("volumes") or {}) or {}).get(str(target_volume_index)) or {}
            for key in ("title", "summary", "detail"):
                value = str(volume_data.get(key) or "").strip()
                if value:
                    parts.append(value)

        if not parts:
            framework_content = str(normalized.get("framework_content") or "").strip()
            if framework_content:
                parts.append(framework_content)

        deduped_parts: List[str] = []
        seen = set()
        for value in parts:
            normalized_value = normalize_story_text(value or "").strip()
            if not normalized_value or normalized_value in seen:
                continue
            seen.add(normalized_value)
            deduped_parts.append(normalized_value)

        return "\n\n".join(deduped_parts)

    def _estimate_volume_detail_auto_character_increment(
        self,
        *,
        current_character_count: int,
        characters_text: str,
        volume_detail_config: Optional[Dict[str, Any]],
    ) -> Dict[str, int]:
        volume_span = max(0, self._resolve_volume_detail_target_span(volume_detail_config))
        recommended_min, recommended_max = self._estimate_character_target_range(max(1, volume_span))
        if volume_span <= 0:
            return {
                "increment": 0,
                "recommended_min": recommended_min,
                "recommended_max": recommended_max,
                "volume_span": 0,
                "referenced_character_count": 0,
            }

        reference_text = self._build_volume_detail_reference_text(volume_detail_config)
        known_character_names = extract_character_names(characters_text or "")
        referenced_character_names = [
            name for name in known_character_names if name and name in reference_text
        ]
        referenced_character_count = len(referenced_character_names)
        increment_cap = self._estimate_character_increment_cap(
            volume_span,
            expansion_mode="volume_detail",
        )
        has_existing_detail = bool(
            str(self._normalize_volume_detail_config(volume_detail_config).get("existing_volume_detail") or "").strip()
        )

        if has_existing_detail:
            base_required = max(0, recommended_min - referenced_character_count)
        else:
            conservative_floor = max(2, int(math.ceil(recommended_min * 0.6)))
            base_required = max(0, conservative_floor - referenced_character_count)

        minimum_increment = 0
        if volume_span >= 24:
            minimum_increment = 2
        if volume_span >= 32:
            minimum_increment = 3
        if referenced_character_count >= max(2, recommended_min - 1):
            minimum_increment = 0

        if not reference_text.strip() and current_character_count <= 1:
            minimum_increment = max(minimum_increment, 3 if volume_span >= 30 else 2)

        suggested_increment = min(
            increment_cap,
            max(0, base_required, minimum_increment),
        )

        return {
            "increment": max(0, suggested_increment),
            "recommended_min": recommended_min,
            "recommended_max": recommended_max,
            "volume_span": volume_span,
            "referenced_character_count": referenced_character_count,
        }

    def _build_auto_character_growth_plan(
        self,
        *,
        current_character_count: int,
        suggested_increment: int,
        recommended_min: int,
        recommended_max: int,
        expansion_mode: str,
        chapter_delta: int,
    ) -> Dict[str, Any]:
        current_count = self._coerce_non_negative_int(current_character_count)
        increment = max(0, self._coerce_non_negative_int(suggested_increment))
        stage_target_characters = current_count + increment
        recommended_floor = max(
            stage_target_characters,
            self._coerce_non_negative_int(recommended_min, stage_target_characters),
        )
        recommended_ceiling = max(
            recommended_floor,
            self._coerce_non_negative_int(recommended_max, recommended_floor),
        )
        remaining_to_floor = max(0, self._coerce_non_negative_int(recommended_min) - stage_target_characters)
        task_target_characters = stage_target_characters
        if expansion_mode not in {"epic_framework", "volume_detail"} and chapter_delta > 0:
            progressive_increment = max(0, int(math.ceil(self._coerce_non_negative_int(chapter_delta) / 12)))
            task_target_characters = max(
                stage_target_characters,
                min(recommended_floor, stage_target_characters + progressive_increment),
            )

        if expansion_mode == "epic_framework":
            stage_label = "框架阶段"
            follow_up_phase = "后续卷级细化或后续协同"
        elif expansion_mode == "volume_detail":
            stage_label = "本卷"
            follow_up_phase = "后续单卷细化"
        else:
            stage_label = "首轮"
            follow_up_phase = "后续协同轮次"

        return {
            "recommended_min": recommended_floor,
            "recommended_max": recommended_ceiling,
            "recommended_range_text": self._format_character_target_range_text(
                recommended_floor,
                recommended_ceiling,
            ),
            "recommended_additional_min": max(0, recommended_floor - current_count),
            "recommended_additional_max": max(0, recommended_ceiling - current_count),
            "stage_label": stage_label,
            "suggested_increment": increment,
            "stage_target_characters": stage_target_characters,
            "task_target_characters": task_target_characters,
            "task_target_increment": max(0, task_target_characters - current_count),
            "remaining_to_recommended_min": remaining_to_floor,
            "follow_up_phase": follow_up_phase,
            "is_phased": remaining_to_floor > 0,
        }

    def _estimate_auto_character_increment(
        self,
        *,
        current_chapter_count: int,
        current_character_count: int,
        target_chapter_count: int,
        coverage_ratio: float,
        expansion_mode: str,
    ) -> Dict[str, int]:
        target_total_chapters = max(
            self._coerce_non_negative_int(current_chapter_count),
            self._coerce_non_negative_int(target_chapter_count),
        )
        recommended_min, recommended_max = self._estimate_character_target_range(target_total_chapters)
        chapter_delta = max(0, target_total_chapters - self._coerce_non_negative_int(current_chapter_count))

        if chapter_delta <= 0:
            return {
                "increment": 0,
                "recommended_min": recommended_min,
                "recommended_max": recommended_max,
            }

        if coverage_ratio < 0.45 and current_character_count >= recommended_min:
            return {
                "increment": 0,
                "recommended_min": recommended_min,
                "recommended_max": recommended_max,
            }

        gap_to_floor = max(0, recommended_min - self._coerce_non_negative_int(current_character_count))
        if gap_to_floor <= 0:
            return {
                "increment": 0,
                "recommended_min": recommended_min,
                "recommended_max": recommended_max,
            }

        increment_cap = self._estimate_character_increment_cap(
            chapter_delta,
            expansion_mode=expansion_mode,
        )
        suggested_increment = min(gap_to_floor, increment_cap)

        if current_character_count <= 0 and suggested_increment > 0:
            baseline_increment = 3 if self._estimate_character_density_multiplier() > 1.05 else 2
            suggested_increment = max(suggested_increment, baseline_increment)

        if coverage_ratio < 0.45 and current_character_count >= max(1, recommended_min - 1):
            suggested_increment = min(suggested_increment, 1)

        return {
            "increment": max(0, suggested_increment),
            "recommended_min": recommended_min,
            "recommended_max": recommended_max,
        }

    @classmethod
    def _build_total_mode_suitability(
        cls,
        *,
        current_chapter_count: int,
        target_chapter_count: int,
        chapters_needed: int,
        execution_mode: str,
    ) -> Dict[str, Any]:
        recommended_upper = cls.CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS
        effective_total = max(current_chapter_count, target_chapter_count)

        if effective_total > recommended_upper:
            request_band = "forbidden"
            request_band_label = "禁止常规协同"
            request_band_reason = (
                f"当前目标已超过常规协同上限 {recommended_upper} 章。"
                "超过 300 章后必须改用长篇框架协同。"
            )
        else:
            request_band = "recommended"
            request_band_label = "推荐区间"
            request_band_reason = "当前目标仍在常规协同的稳定工作带内，适合直接进行单轮或分轮扩展。"

        summary = (
            f"常规协同仅支持总规模不超过 {recommended_upper} 章的项目；"
            f"{cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD} 章及以上禁止继续使用常规协同，必须切换到长篇框架协同。"
        )

        return {
            "mode": "total",
            "request_band": request_band,
            "request_band_label": request_band_label,
            "request_band_reason": request_band_reason,
            "current_total_chapters": current_chapter_count,
            "target_total_chapters": target_chapter_count,
            "chapters_needed": chapters_needed,
            "execution_mode": execution_mode,
            "recommended_total_chapters_max": recommended_upper,
            "caution_total_chapters_min": None,
            "caution_total_chapters_max": None,
            "framework_preferred_total_from": cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD,
            "epic_auto_switch_total_from": cls.EPIC_CHAPTER_THRESHOLD,
            "preferred_iterative_step": cls.ITERATIVE_CHAPTER_STEP,
            "single_round_delta_limit": cls.SHORT_CHAPTER_DELTA_LIMIT,
            "summary": summary,
            "bands": [
                {
                    "key": "recommended",
                    "label": "推荐区间",
                    "range_text": f"总规模 1-{recommended_upper} 章",
                    "detail": f"单次新增建议按 {cls.ITERATIVE_CHAPTER_STEP} 章左右推进，质量和稳定性更均衡。",
                },
                {
                    "key": "forbidden",
                    "label": "禁止常规协同",
                    "range_text": f"总规模 >= {cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD} 章",
                    "detail": "超过 300 章后必须改用长篇框架协同，不能继续走常规协同。",
                },
            ],
        }

    @classmethod
    def _estimate_execution_rounds_from_mode_info(cls, mode_info: Dict[str, Any]) -> int:
        mode = str(mode_info.get("mode") or "delta").strip()
        chapters_needed = max(0, int(mode_info.get("chapters_needed") or 0))
        characters_needed = max(0, int(mode_info.get("characters_needed") or 0))

        if mode == "volume_detail":
            character_rounds = (characters_needed + cls.ITERATIVE_CHARACTER_STEP - 1) // cls.ITERATIVE_CHARACTER_STEP
            return max(1, 1 + character_rounds)
        if mode == "epic":
            # 长篇框架协同在一次任务内完成框架生成与必要的人物补足，
            # 不应按“分轮协同”展示为多轮任务。
            return 1
        if mode == "iterative":
            chapter_rounds = (chapters_needed + cls.ITERATIVE_CHAPTER_STEP - 1) // cls.ITERATIVE_CHAPTER_STEP
            character_rounds = (characters_needed + cls.ITERATIVE_CHARACTER_STEP - 1) // cls.ITERATIVE_CHARACTER_STEP
            return max(1, max(chapter_rounds, character_rounds))
        return 1

    @classmethod
    def _estimate_duration_minutes_range_from_mode_info(
        cls,
        mode_info: Dict[str, Any],
        estimated_rounds: int,
    ) -> Tuple[int, int]:
        mode = str(mode_info.get("mode") or "delta").strip()
        current_chapter_count = max(0, int(mode_info.get("current_chapter_count") or 0))
        target_chapter_count = max(
            current_chapter_count,
            int(mode_info.get("target_chapter_count") or current_chapter_count),
        )
        current_character_count = max(0, int(mode_info.get("current_character_count") or 0))
        target_character_count = max(
            current_character_count,
            int(mode_info.get("target_character_count") or current_character_count),
        )
        chapter_delta = max(0, target_chapter_count - current_chapter_count)
        character_delta = max(0, target_character_count - current_character_count)
        rounds = max(1, int(estimated_rounds or 1))

        if mode == "iterative":
            min_estimate = 4.0 + rounds * 2.2 + max(0, character_delta - 5) * 0.15
            max_estimate = 8.0 + rounds * 3.3 + max(0, character_delta - 5) * 0.25
        elif mode == "epic":
            epic_total_volumes = max(
                cls.EPIC_MIN_VOLUMES,
                int(
                    mode_info.get("epic_total_volumes")
                    or math.ceil(
                        max(target_chapter_count, cls.EPIC_CHAPTER_THRESHOLD)
                        / cls.EPIC_DEFAULT_CHAPTERS_PER_VOLUME
                    )
                ),
            )
            min_estimate = (
                3.0
                + epic_total_volumes * 0.25
                + max(0, target_chapter_count - cls.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS) * 0.002
                + max(0, character_delta - 8) * 0.08
            )
            max_estimate = (
                6.0
                + epic_total_volumes * 0.4
                + max(0, target_chapter_count - cls.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS) * 0.004
                + max(0, character_delta - 8) * 0.15
            )
        elif mode == "volume_detail":
            volume_range = mode_info.get("volume_chapter_range")
            if isinstance(volume_range, (list, tuple)) and len(volume_range) == 2:
                try:
                    volume_span = max(1, int(volume_range[1]) - int(volume_range[0]) + 1)
                except Exception:
                    volume_span = max(1, chapter_delta or cls.ITERATIVE_CHAPTER_STEP)
            else:
                volume_span = max(1, chapter_delta or cls.ITERATIVE_CHAPTER_STEP)

            min_estimate = 7.0 + volume_span * 0.2 + character_delta * 0.4
            max_estimate = 12.0 + volume_span * 0.35 + character_delta * 0.6
        else:
            min_estimate = 4.0 + chapter_delta * 0.18 + character_delta * 0.25
            max_estimate = 7.0 + chapter_delta * 0.28 + character_delta * 0.4

        min_minutes = max(5, int(math.ceil(min_estimate)))
        max_minutes = max(min_minutes + 3, int(math.ceil(max_estimate)))
        return min_minutes, max_minutes

    @staticmethod
    def _normalize_expansion_mode(expansion_mode: str) -> str:
        normalized = str(expansion_mode or "auto").strip()
        if normalized in {"auto", "total", "epic_framework", "volume_detail"}:
            return normalized
        return "auto"

    @staticmethod
    def _normalize_epic_config(epic_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {
            "total_volumes": None,
            "chapter_range": None,
        }
        if not isinstance(epic_config, dict):
            return normalized

        total_volumes = epic_config.get("total_volumes")
        if total_volumes is not None:
            try:
                normalized["total_volumes"] = max(1, int(total_volumes))
            except Exception:
                normalized["total_volumes"] = None

        chapter_range = epic_config.get("chapter_range")
        if isinstance(chapter_range, (list, tuple)) and len(chapter_range) == 2:
            try:
                lower = max(1, int(chapter_range[0]))
                upper = max(lower, int(chapter_range[1]))
                normalized["chapter_range"] = (lower, upper)
            except Exception:
                normalized["chapter_range"] = None

        return normalized

    @staticmethod
    def _normalize_volume_detail_config(
        volume_detail_config: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {
            "framework_content": "",
            "target_volume_index": None,
            "chapters_count_range": None,
            "start_chapter_num": None,
            "framework_header": "",
            "framework_footer": "",
            "volumes_data": None,
            "previous_volume_detail": "",
            "existing_volume_detail": "",
            "expected_chapter_range": None,
            "expected_total_chapter_count": None,
            "current_total_chapter_count": None,
            "total_volumes": None,
        }
        if not isinstance(volume_detail_config, dict):
            return normalized

        normalized["framework_content"] = str(volume_detail_config.get("framework_content") or "")
        normalized["framework_header"] = str(volume_detail_config.get("framework_header") or "")
        normalized["framework_footer"] = str(volume_detail_config.get("framework_footer") or "")
        normalized["previous_volume_detail"] = str(volume_detail_config.get("previous_volume_detail") or "")
        normalized["existing_volume_detail"] = str(volume_detail_config.get("existing_volume_detail") or "")
        normalized["volumes_data"] = volume_detail_config.get("volumes_data")

        for int_key in [
            "target_volume_index",
            "start_chapter_num",
            "expected_total_chapter_count",
            "current_total_chapter_count",
            "total_volumes",
        ]:
            value = volume_detail_config.get(int_key)
            if value is None:
                continue
            try:
                normalized[int_key] = int(value)
            except Exception:
                normalized[int_key] = None

        for tuple_key in ["chapters_count_range", "expected_chapter_range"]:
            value = volume_detail_config.get(tuple_key)
            if isinstance(value, (list, tuple)) and len(value) == 2:
                try:
                    lower = int(value[0])
                    upper = int(value[1])
                    normalized[tuple_key] = (lower, upper)
                except Exception:
                    normalized[tuple_key] = None

        return normalized

    @staticmethod
    def _recommend_intent(
        validation: Dict[str, Any],
        chapters_needed: int,
        characters_needed: int,
    ) -> Tuple[str, str]:
        chapter_count = int(validation.get("chapter_count") or 0)
        character_count = int(validation.get("character_count") or 0)
        coverage_ratio = _safe_float(validation.get("coverage_ratio") or 0.0)
        unreferenced_characters = list(validation.get("unreferenced_characters") or [])

        if chapters_needed > 0 and characters_needed <= 0:
            if character_count <= 0:
                return "outline_led", "当前以补章节为主，同时人物底盘偏薄，建议以大纲侧为主导推进。"
            return "outline_led", "本次主要目标是补章节，优先走大纲主导更符合当前诉求。"

        if characters_needed > 0 and chapters_needed <= 0:
            if chapter_count <= 0:
                return "character_led", "本次主要目标是补人物，先建立人物体系更贴近当前目标。"
            if coverage_ratio < 0.35:
                return "outline_led", "现有人物在大纲中的承接偏弱，建议先补情节锚点再扩人物。"
            return "character_led", "本次主要目标是补人物，优先走人物主导更符合当前诉求。"

        if chapter_count <= 0 and chapters_needed > 0:
            return "outline_led", "当前缺少可定位章节结构，建议先由大纲侧建立承接框架。"
        if character_count <= 0 and characters_needed > 0:
            return "character_led", "当前人物体系偏空，建议先补关键角色再做协同扩展。"
        if coverage_ratio < 0.55 or unreferenced_characters:
            return "outline_led", "当前人物与章节覆盖率偏低，建议先由大纲侧补承接与登场位。"
        return "balanced", "章节与人物都存在增量空间，适合做平衡协同扩展。"

    def _build_cross_support_plan(
        self,
        *,
        current_chapter_count: int,
        current_character_count: int,
        characters_text: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        validation: Dict[str, Any],
        expansion_mode: str = "auto",
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        plan = {
            "suggested_target_chapters": target_total_chapters,
            "suggested_target_characters": target_total_characters,
            "chapter_delta": 0,
            "character_delta": 0,
            "character_plan": None,
            "reasons": [],
        }

        coverage_ratio = _safe_float(validation.get("coverage_ratio") or 0.0)
        chapter_count = int(validation.get("chapter_count") or current_chapter_count or 0)
        character_count = int(validation.get("character_count") or current_character_count or 0)

        if expansion_mode == "volume_detail" and target_total_chapters is not None and target_total_characters is None:
            character_plan = self._estimate_volume_detail_auto_character_increment(
                current_character_count=character_count,
                characters_text=characters_text,
                volume_detail_config=volume_detail_config,
            )
            suggested_characters = int(character_plan["increment"] or 0)
            volume_span = max(
                0,
                int(character_plan.get("volume_span") or 0),
            )
            growth_plan = self._build_auto_character_growth_plan(
                current_character_count=character_count,
                suggested_increment=suggested_characters,
                recommended_min=int(character_plan["recommended_min"] or 0),
                recommended_max=int(character_plan["recommended_max"] or 0),
                expansion_mode=expansion_mode,
                chapter_delta=volume_span,
            )
            plan["character_plan"] = growth_plan
            if suggested_characters > 0:
                plan["character_delta"] = suggested_characters
                plan["suggested_target_characters"] = growth_plan["stage_target_characters"]
                plan["reasons"].append(
                    f"按本卷新增章节规模与题材倾向，全书结构化人物建议规模约为 {growth_plan['recommended_range_text']} 人。"
                    f"{growth_plan['stage_label']}先补到 {growth_plan['stage_target_characters']} 人"
                    f"（本次新增 {suggested_characters} 人），优先承接当前卷剧情；"
                    f"剩余角色将在{growth_plan['follow_up_phase']}继续补齐。"
                )

        if (
            expansion_mode != "volume_detail"
            and target_total_chapters is not None
            and target_total_characters is None
        ):
            character_plan = self._estimate_auto_character_increment(
                current_chapter_count=current_chapter_count,
                current_character_count=character_count,
                target_chapter_count=int(target_total_chapters),
                coverage_ratio=coverage_ratio,
                expansion_mode=expansion_mode,
            )
            suggested_characters = int(character_plan["increment"] or 0)
            growth_plan = self._build_auto_character_growth_plan(
                current_character_count=character_count,
                suggested_increment=suggested_characters,
                recommended_min=int(character_plan["recommended_min"] or 0),
                recommended_max=int(character_plan["recommended_max"] or 0),
                expansion_mode=expansion_mode,
                chapter_delta=max(0, int(target_total_chapters) - current_chapter_count),
            )
            plan["character_plan"] = growth_plan
            if suggested_characters > 0:
                plan["character_delta"] = suggested_characters
                plan["suggested_target_characters"] = growth_plan["stage_target_characters"]
                if expansion_mode == "epic_framework":
                    plan["reasons"].append(
                        f"按目标章节规模与题材倾向，全书结构化人物建议规模约为 {growth_plan['recommended_range_text']} 人。"
                        f"当前为长篇框架协同，{growth_plan['stage_label']}先补到 {growth_plan['stage_target_characters']} 人"
                        f"（本次新增 {suggested_characters} 人），优先搭起主线、阵营与关键承接角色；"
                        f"剩余角色将在{growth_plan['follow_up_phase']}继续补齐。"
                    )
                else:
                    plan["reasons"].append(
                        f"按目标章节规模与题材倾向，全书结构化人物建议规模约为 {growth_plan['recommended_range_text']} 人。"
                        f"点击一次开始协同后，系统会在同一次任务里自动分轮推进；首轮先补到 {growth_plan['stage_target_characters']} 人"
                        f"（首轮新增 {suggested_characters} 人），剩余角色会在{growth_plan['follow_up_phase']}继续补齐。"
                    )
                if growth_plan["task_target_characters"] > growth_plan["stage_target_characters"]:
                    plan["reasons"].append(
                        f"点击开始协同后，系统会在同一次任务里自动连续执行多轮；首轮先补到 {growth_plan['stage_target_characters']} 人，"
                        f"若推进顺利，本次任务预计补到 {growth_plan['task_target_characters']} 人。"
                    )
            elif coverage_ratio < 0.45 and character_count > 0:
                plan["reasons"].append(
                    "当前人物覆盖率偏低，系统本轮不继续自动加人，建议优先补足现有人物在新增章节中的职责与出场。"
                )

        if target_total_characters is not None and target_total_chapters is None:
            characters_needed = max(0, int(target_total_characters) - current_character_count)
            if characters_needed > 0:
                estimated_target_chapters, capped_by_conventional_limit = (
                    self._estimate_total_chapters_for_character_target(
                        current_chapter_count=current_chapter_count,
                        target_character_count=int(target_total_characters),
                        expansion_mode=expansion_mode,
                    )
                )
                suggested_chapters = max(0, estimated_target_chapters - current_chapter_count)
                plan["chapter_delta"] = suggested_chapters
                plan["suggested_target_chapters"] = estimated_target_chapters
                plan["reasons"].append(
                    f"本次以扩人物为主，系统已按目标人物规模同步推算章节承接量，建议先补到 {estimated_target_chapters} 章再扩展角色体系。"
                )
                if capped_by_conventional_limit:
                    plan["reasons"].append(
                        f"当前为常规协同，按目标人物规模推算的章节总量已触达常规协同上限 {self.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS} 章；如需更高承载角色规模，建议切换到长篇框架协同。"
                    )

        if (
            expansion_mode in {"auto", "total"}
            and target_total_chapters is None
            and target_total_characters is None
        ):
            if chapter_count <= 0:
                suggested_chapters = 8
            elif chapter_count < 20:
                suggested_chapters = 8
            elif chapter_count < 80:
                suggested_chapters = 6
            else:
                suggested_chapters = max(4, min(12, chapter_count // 8))

            target_chapter_count = current_chapter_count + suggested_chapters
            character_plan = self._estimate_auto_character_increment(
                current_chapter_count=current_chapter_count,
                current_character_count=character_count,
                target_chapter_count=target_chapter_count,
                coverage_ratio=coverage_ratio,
                expansion_mode="total",
            )
            suggested_characters = int(character_plan["increment"] or 0)
            growth_plan = self._build_auto_character_growth_plan(
                current_character_count=character_count,
                suggested_increment=suggested_characters,
                recommended_min=int(character_plan["recommended_min"] or 0),
                recommended_max=int(character_plan["recommended_max"] or 0),
                expansion_mode="total",
                chapter_delta=suggested_chapters,
            )

            plan["chapter_delta"] = suggested_chapters
            plan["suggested_target_chapters"] = current_chapter_count + suggested_chapters
            if suggested_characters > 0:
                plan["character_delta"] = suggested_characters
                plan["suggested_target_characters"] = growth_plan["stage_target_characters"]
                plan["character_plan"] = growth_plan
            plan["reasons"].append(
                "本次未显式填写目标，系统已按当前章节密度与人物覆盖状况自动估算建议目标。"
            )

        return plan

    def analyze_expansion_request(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str = "auto",
        intent: str = "auto",
        enable_auto_supplement: bool = False,
        expansion_mode: str = "auto",
        volume_character_increment: Optional[int] = None,
        epic_config: Optional[Dict[str, Any]] = None,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        current_outline = sanitize_outline_alignment_placeholders(current_outline or "")
        validation = evaluate_story_coordination(current_outline or "", characters or "")
        normalized_expansion_mode = self._normalize_expansion_mode(expansion_mode)
        normalized_epic_config = self._normalize_epic_config(epic_config)
        normalized_volume_detail_config = self._normalize_volume_detail_config(volume_detail_config)
        requested_mode_info = self.determine_execution_mode(
            current_outline=current_outline,
            characters=characters,
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            expansion_mode=normalized_expansion_mode,
            epic_config=normalized_epic_config,
            volume_detail_config=normalized_volume_detail_config,
        )

        recommended_intent, intent_reason = self._recommend_intent(
            validation=validation,
            chapters_needed=int(requested_mode_info.get("chapters_needed") or 0),
            characters_needed=int(requested_mode_info.get("characters_needed") or 0),
        )
        effective_intent = intent if intent in {"outline_led", "character_led", "balanced"} else recommended_intent

        support_plan = self._build_cross_support_plan(
            current_chapter_count=int(requested_mode_info.get("current_chapter_count") or 0),
            current_character_count=int(requested_mode_info.get("current_character_count") or 0),
            characters_text=characters or "",
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            validation=validation,
            expansion_mode=normalized_expansion_mode,
            volume_detail_config=normalized_volume_detail_config,
        )

        effective_target_chapters = target_total_chapters
        effective_target_characters = target_total_characters
        auto_supplement_applied = False

        if enable_auto_supplement:
            if effective_target_chapters is None and support_plan.get("suggested_target_chapters") is not None:
                effective_target_chapters = int(support_plan["suggested_target_chapters"])
                auto_supplement_applied = auto_supplement_applied or int(support_plan.get("chapter_delta") or 0) > 0
            if effective_target_characters is None and support_plan.get("suggested_target_characters") is not None:
                effective_target_characters = int(support_plan["suggested_target_characters"])
                auto_supplement_applied = auto_supplement_applied or int(support_plan.get("character_delta") or 0) > 0

        effective_mode_info = self.determine_execution_mode(
            current_outline=current_outline,
            characters=characters,
            target_total_chapters=effective_target_chapters,
            target_total_characters=effective_target_characters,
            expansion_mode=normalized_expansion_mode,
            epic_config=normalized_epic_config,
            volume_detail_config=normalized_volume_detail_config,
        )

        recommended_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation,
            chapters_needed=int(effective_mode_info.get("chapters_needed") or 0),
            characters_needed=int(effective_mode_info.get("characters_needed") or 0),
        )
        effective_strategy = (
            strategy
            if strategy in {"balanced", "plot_first", "character_first"}
            else self._intent_to_strategy(effective_intent)
        )
        if strategy == "auto" and effective_intent == "balanced":
            effective_strategy = recommended_strategy

        target_chapter_count = int(
            effective_mode_info.get("target_chapter_count")
            or effective_mode_info.get("current_chapter_count")
            or 0
        )
        target_character_count = int(
            effective_mode_info.get("target_character_count")
            or effective_mode_info.get("current_character_count")
            or 0
        )
        current_character_count = int(effective_mode_info.get("current_character_count") or 0)
        execution_mode = str(effective_mode_info.get("mode") or "delta").strip()
        estimated_rounds = self._estimate_execution_rounds_from_mode_info(effective_mode_info)
        estimated_duration_minutes_min, estimated_duration_minutes_max = (
            self._estimate_duration_minutes_range_from_mode_info(
                effective_mode_info,
                estimated_rounds,
            )
        )
        effective_expansion_mode = (
            "epic_framework"
            if execution_mode == "epic"
            else (
                "volume_detail"
                if execution_mode == "volume_detail"
                else (
                    normalized_expansion_mode
                    if normalized_expansion_mode in {"total", "epic_framework", "volume_detail"}
                    else "total"
                )
            )
        )

        outline_plan_model = self._estimate_outline_model_for_plan(
            execution_mode=execution_mode,
            target_chapter_count=target_chapter_count,
            volume_detail_config=normalized_volume_detail_config,
        )
        character_plan_model = self._estimate_character_model_for_plan(target_character_count)

        model_plan = {
            "coordinator_planner_model": self._get_llm_model_name(getattr(self, "planner_llm", None), "unknown"),
            "coordinator_writer_model": self._get_llm_model_name(getattr(self, "writer_llm", None), "unknown"),
            "outline_expansion_model": outline_plan_model,
            "character_expansion_model": character_plan_model,
            "estimated_rounds": estimated_rounds,
            "notes": [],
        }

        if not (current_outline or "").strip():
            model_plan["notes"].append("当前缺少结构化大纲，协同会优先从人物侧补强，并仅补充最小必要的承接情节。")
        if not (characters or "").strip():
            model_plan["notes"].append("当前缺少结构化人物体系，协同会先从大纲中识别角色需求，再补齐人物卡与关系。")

        warnings: List[str] = []
        if auto_supplement_applied and support_plan.get("reasons"):
            warnings.extend(list(dict.fromkeys(support_plan["reasons"])))
        if intent in {"outline_led", "character_led", "balanced"} and intent != recommended_intent:
            warnings.append("当前执行方向与系统建议不同，可能影响协同效率与结果稳定性。")
        if execution_mode == "iterative":
            warnings.append("当前会走分轮扩展；点击一次开始后，系统会在同一次任务里自动连续执行多轮，逐步逼近目标，而不是只执行首轮。")
        if execution_mode == "epic":
            warnings.append("当前会先生成长篇框架，再逐步细化，不会一次性产出完整卷级细纲。")
            model_plan["outline_expansion_model"] = self._estimate_stage_model("concept", outline_plan_model)
            model_plan["notes"].append(
                f"长篇框架阶段预计使用 {model_plan['outline_expansion_model']} 生成总卷框架，后续卷级细化会按单卷规模在 deepseek-reasoner / qwen3.5-plus 之间切换。"
            )
            if (
                normalized_expansion_mode == "auto"
                and target_chapter_count >= self.EPIC_CHAPTER_THRESHOLD
            ):
                warnings.append("目标章节规模已进入超长篇区间，系统在自动判断模式下切换为长篇框架协同。")
        if normalized_expansion_mode == "epic_framework" and execution_mode == "epic":
            warnings.append("当前为显式长篇框架协同，会优先保证总卷框架与角色体系匹配，再进入卷级细化。")
        if execution_mode == "volume_detail":
            warnings.append("当前会聚焦单卷细化，并同步检查该卷所需角色是否齐备。")
            volume_range = effective_mode_info.get("volume_chapter_range")
            if volume_range:
                model_plan["notes"].append(
                    f"当前聚焦第{effective_mode_info.get('target_volume_index')}卷，预计细化第{int(volume_range[0])}-{int(volume_range[1])}章。"
                )
            model_plan["outline_expansion_model"] = self._estimate_volume_detail_outline_model(
                normalized_volume_detail_config.get("chapters_count_range")
            )
            if normalized_volume_detail_config.get("existing_volume_detail"):
                warnings.append("目标卷已有细纲，本次协同会覆盖该卷现有细纲。")
        if target_chapter_count >= self.EPIC_CHAPTER_THRESHOLD:
            if execution_mode == "epic":
                model_plan["notes"].append(
                    f"目标章节规模较大，当前框架生成阶段会先用 {model_plan['outline_expansion_model']} 收敛总卷结构，再进入后续卷级细化。"
                )
            else:
                model_plan["notes"].append(
                    f"目标章节规模较大，大纲扩展预计使用 {model_plan['outline_expansion_model']}，协同会分阶段收敛而非一次性铺满全部细纲。"
                )
        if target_character_count >= 60:
            model_plan["character_expansion_model"] = self._estimate_character_model_for_plan(target_character_count)
            model_plan["notes"].append(
                f"目标人物规模较大，人物扩展预计使用 {model_plan['character_expansion_model']}，并建议分轮补齐关系与剧情职责。"
            )

        model_plan["notes"] = list(dict.fromkeys(item for item in model_plan["notes"] if item))
        mode_suitability = (
            self._build_total_mode_suitability(
                current_chapter_count=int(effective_mode_info.get("current_chapter_count") or 0),
                target_chapter_count=target_chapter_count,
                chapters_needed=int(effective_mode_info.get("chapters_needed") or 0),
                execution_mode=execution_mode,
            )
            if normalized_expansion_mode in {"auto", "total"}
            else None
        )

        intent_labels = {
            "outline_led": "大纲主导",
            "character_led": "人物主导",
            "balanced": "平衡协同",
            "auto": "自动判断",
        }
        mode_labels = {
            "delta": "单轮增量",
            "iterative": "分轮协同",
            "epic": "长篇框架",
            "volume_detail": "单卷细化",
        }
        summary_parts = [
            f"推荐采用{intent_labels.get(effective_intent, effective_intent)}",
            f"执行模式为{mode_labels.get(execution_mode, execution_mode)}",
            f"预计 {estimated_rounds} 轮",
        ]
        if auto_supplement_applied:
            if int(support_plan.get("chapter_delta") or 0) > 0:
                summary_parts.append(f"自动补足 {int(support_plan['chapter_delta'])} 章承接剧情")
            if int(support_plan.get("character_delta") or 0) > 0:
                character_plan = support_plan.get("character_plan") or {}
                task_target_characters = self._coerce_non_negative_int(
                    character_plan.get("task_target_characters"),
                )
                stage_target_characters = self._coerce_non_negative_int(
                    character_plan.get("stage_target_characters"),
                )
                if task_target_characters > stage_target_characters > 0:
                    summary_parts.append(
                        f"自动分轮补人：点击一次开始后系统会自动连续推进，首轮补足 {int(support_plan['character_delta'])} 个配套人物，本次任务预计补到 {task_target_characters} 人"
                    )
                else:
                    summary_parts.append(f"自动补足 {int(support_plan['character_delta'])} 个配套人物")
        if execution_mode == "epic":
            epic_range = effective_mode_info.get("epic_chapter_range")
            epic_volumes = effective_mode_info.get("epic_total_volumes")
            if epic_volumes and epic_range:
                summary_parts.append(
                    f"框架规模 {int(epic_volumes)} 卷 / {int(epic_range[0])}-{int(epic_range[1])} 章"
                )
        if execution_mode == "volume_detail":
            volume_range = effective_mode_info.get("volume_chapter_range")
            if volume_range:
                summary_parts.append(
                    f"聚焦第{int(effective_mode_info.get('target_volume_index') or 0)}卷 / 第{int(volume_range[0])}-{int(volume_range[1])}章"
                )

        return {
            "validation": validation,
            "execution_mode": execution_mode,
            "execution_mode_reason": effective_mode_info.get("reason", ""),
            "requested_target_chapter_count": target_total_chapters,
            "requested_target_character_count": target_total_characters,
            "effective_target_chapter_count": effective_target_chapters,
            "effective_target_character_count": effective_target_characters,
            "requested_volume_character_increment": volume_character_increment,
            "effective_volume_character_increment": (
                max(0, target_character_count - current_character_count)
                if execution_mode == "volume_detail"
                else None
            ),
            "recommended_strategy": recommended_strategy,
            "effective_strategy": effective_strategy,
            "recommended_intent": recommended_intent,
            "effective_intent": effective_intent,
            "requested_expansion_mode": normalized_expansion_mode,
            "effective_expansion_mode": effective_expansion_mode,
            "intent_reason": intent_reason,
            "auto_supplement_applied": auto_supplement_applied,
            "auto_supplement": support_plan,
            "estimated_rounds": estimated_rounds,
            "estimated_duration_minutes_min": estimated_duration_minutes_min,
            "estimated_duration_minutes_max": estimated_duration_minutes_max,
            "mode_suitability": mode_suitability,
            "model_plan": model_plan,
            "warnings": warnings,
            "epic_config": {
                "total_volumes": effective_mode_info.get("epic_total_volumes"),
                "chapter_range": list(effective_mode_info["epic_chapter_range"])
                if effective_mode_info.get("epic_chapter_range")
                else None,
            },
            "volume_detail": {
                "target_volume_index": effective_mode_info.get("target_volume_index"),
                "chapter_range": list(effective_mode_info["volume_chapter_range"])
                if effective_mode_info.get("volume_chapter_range")
                else None,
                "character_increment": (
                    max(0, target_character_count - current_character_count)
                    if execution_mode == "volume_detail"
                    else None
                ),
                "target_character_count": target_character_count if execution_mode == "volume_detail" else None,
                "existing_detail": bool(normalized_volume_detail_config.get("existing_volume_detail")),
            },
            "analysis_summary": "；".join(summary_parts),
        }

    def determine_execution_mode(
        self,
        current_outline: str,
        characters: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        expansion_mode: str = "auto",
        epic_config: Optional[Dict[str, Any]] = None,
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        _, outline_blocks = parse_outline_blocks(current_outline or "")
        current_chapter_count = len(outline_blocks)
        current_character_count = len(extract_character_names(characters or ""))
        normalized_expansion_mode = self._normalize_expansion_mode(expansion_mode)
        normalized_epic_config = self._normalize_epic_config(epic_config)
        normalized_volume_detail_config = self._normalize_volume_detail_config(volume_detail_config)

        target_chapter_count = (
            max(current_chapter_count, int(target_total_chapters))
            if target_total_chapters is not None
            else current_chapter_count
        )
        target_character_count = (
            max(current_character_count, int(target_total_characters))
            if target_total_characters is not None
            else current_character_count
        )

        chapters_needed = max(0, target_chapter_count - current_chapter_count)
        characters_needed = max(0, target_character_count - current_character_count)
        explicit_epic_range = normalized_epic_config.get("chapter_range")
        explicit_epic_volumes = normalized_epic_config.get("total_volumes")
        framework_reference = max(target_chapter_count, self.planned_chapters_max or 0)

        if normalized_expansion_mode == "volume_detail":
            volume_range = normalized_volume_detail_config.get("expected_chapter_range")
            current_total_count = int(normalized_volume_detail_config.get("current_total_chapter_count") or current_chapter_count)
            expected_total_count = int(normalized_volume_detail_config.get("expected_total_chapter_count") or target_chapter_count or current_total_count)
            target_chapter_count = max(target_chapter_count, expected_total_count)
            current_chapter_count = max(current_chapter_count, current_total_count)
            chapters_needed = max(0, target_chapter_count - current_chapter_count)
            characters_needed = max(0, target_character_count - current_character_count)
            return {
                "mode": "volume_detail",
                "reason": "已显式选择单卷细化协同，优先细化目标卷并同步补齐相关角色。",
                "current_chapter_count": current_chapter_count,
                "current_character_count": current_character_count,
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
                "chapters_needed": chapters_needed,
                "characters_needed": characters_needed,
                "requested_expansion_mode": normalized_expansion_mode,
                "target_volume_index": normalized_volume_detail_config.get("target_volume_index"),
                "volume_chapter_range": volume_range,
                "current_total_chapter_count": current_total_count,
            }

        if normalized_expansion_mode == "epic_framework":
            if explicit_epic_range:
                target_chapter_count = max(target_chapter_count, int(explicit_epic_range[1]))
            else:
                target_chapter_count = max(
                    target_chapter_count,
                    self.planned_chapters_max or 0,
                    self.EPIC_CHAPTER_THRESHOLD,
                )
            chapters_needed = max(0, target_chapter_count - current_chapter_count)
            characters_needed = max(0, target_character_count - current_character_count)
            return {
                "mode": "epic",
                "reason": "已显式选择长篇框架协同，优先生成可扩展的总卷框架。",
                "current_chapter_count": current_chapter_count,
                "current_character_count": current_character_count,
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
                "chapters_needed": chapters_needed,
                "characters_needed": characters_needed,
                "requested_expansion_mode": normalized_expansion_mode,
                "epic_total_volumes": explicit_epic_volumes,
                "epic_chapter_range": explicit_epic_range,
            }

        epic_reference = framework_reference
        if normalized_expansion_mode == "auto" and target_total_chapters is not None and epic_reference >= self.EPIC_CHAPTER_THRESHOLD:
            return {
                "mode": "epic",
                "reason": f"目标规模约 {epic_reference} 章，已进入超长篇范围，自动判断模式切换为长篇框架协同。",
                "current_chapter_count": current_chapter_count,
                "current_character_count": current_character_count,
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
                "chapters_needed": chapters_needed,
                "characters_needed": characters_needed,
                "requested_expansion_mode": normalized_expansion_mode,
                "epic_total_volumes": explicit_epic_volumes,
                "epic_chapter_range": explicit_epic_range,
            }

        if (
            chapters_needed > self.SHORT_CHAPTER_DELTA_LIMIT
            or characters_needed > self.SHORT_CHARACTER_DELTA_LIMIT
        ):
            return {
                "mode": "iterative",
                "reason": (
                    f"本次需新增 {chapters_needed} 章、{characters_needed} 人，"
                    "超出单轮 delta 适用范围，切换为分轮协同。"
                ),
                "current_chapter_count": current_chapter_count,
                "current_character_count": current_character_count,
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
                "chapters_needed": chapters_needed,
                "characters_needed": characters_needed,
                "requested_expansion_mode": normalized_expansion_mode,
            }

        return {
            "mode": "delta",
            "reason": (
                f"本次需新增 {chapters_needed} 章、{characters_needed} 人，"
                "适合直接做单轮 delta 协同。"
            ),
            "current_chapter_count": current_chapter_count,
            "current_character_count": current_character_count,
            "target_chapter_count": target_chapter_count,
            "target_character_count": target_character_count,
            "chapters_needed": chapters_needed,
            "characters_needed": characters_needed,
            "requested_expansion_mode": normalized_expansion_mode,
        }

    @staticmethod
    def _resolve_strategy(
        strategy: str,
        validation: Dict[str, Any],
        chapters_needed: int,
        characters_needed: int,
    ) -> str:
        normalized = str(strategy or "auto").strip()
        if normalized in {"balanced", "plot_first", "character_first"}:
            return normalized

        if chapters_needed > 0 and characters_needed <= 0:
            return "plot_first"
        if characters_needed > 0 and chapters_needed <= 0:
            return "character_first"
        if validation.get("character_count", 0) <= 0 and characters_needed > 0:
            return "character_first"
        if validation.get("chapter_count", 0) <= 0 and chapters_needed > 0:
            return "plot_first"
        if validation.get("coverage_ratio", 1.0) < 0.55:
            return "plot_first"
        if validation.get("unreferenced_characters"):
            return "plot_first"
        return "balanced"

    @staticmethod
    def _collect_new_character_names(existing_characters: str, merged_characters: str) -> List[str]:
        before = {normalize_character_name(name) for name in extract_character_names(existing_characters or "")}
        after_names = extract_character_names(merged_characters or "")
        return [name for name in after_names if normalize_character_name(name) not in before]

    @staticmethod
    def _extract_character_delta_text(existing_characters: str, merged_characters: str) -> str:
        before = {normalize_character_name(name) for name in extract_character_names(existing_characters or "")}
        new_blocks = [
            block_text
            for block_name, block_text in extract_character_blocks(merged_characters or "")
            if normalize_character_name(block_name) not in before
        ]
        return "\n\n".join(block for block in new_blocks if block and block.strip())

    @staticmethod
    def _extract_outline_delta_text(
        previous_outline: str,
        current_outline: str,
        previous_chapter_count: int = 0,
    ) -> str:
        previous_text = str(previous_outline or "").strip()
        current_text = str(current_outline or "").strip()
        if not current_text or current_text == previous_text:
            return ""

        _, previous_blocks = parse_outline_blocks(previous_text)
        _, current_blocks = parse_outline_blocks(current_text)
        if current_blocks:
            previous_map = {
                int(block.original_number or 0): block
                for block in previous_blocks
                if int(block.original_number or 0) > 0
            }
            chapter_threshold = max(0, int(previous_chapter_count or 0))
            if chapter_threshold <= 0 and previous_map:
                chapter_threshold = max(previous_map)

            delta_blocks = [
                block
                for block in current_blocks
                if int(block.original_number or 0) > chapter_threshold
            ]

            if not delta_blocks and previous_map:
                for block in current_blocks:
                    chapter_number = int(block.original_number or 0)
                    previous_block = previous_map.get(chapter_number)
                    if previous_block is None:
                        delta_blocks.append(block)
                        continue
                    if (
                        (previous_block.title or "").strip() != (block.title or "").strip()
                        or (previous_block.body or "").strip() != (block.body or "").strip()
                    ):
                        delta_blocks.append(block)

            if delta_blocks:
                return render_outline_with_original_numbers("", delta_blocks)

        if previous_text and current_text.startswith(previous_text):
            return current_text[len(previous_text):].strip()
        return current_text

    @staticmethod
    def _stringify_structured_value(value: Any, item_separator: str = "；") -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (list, tuple, set)):
            parts = [
                str(item).strip()
                for item in value
                if str(item).strip()
            ]
            return item_separator.join(parts)
        if isinstance(value, dict):
            parts = []
            for key, item in value.items():
                key_text = str(key).strip()
                item_text = str(item).strip()
                if not key_text and not item_text:
                    continue
                parts.append(f"{key_text}：{item_text}" if key_text else item_text)
            return item_separator.join(parts)
        return str(value).strip()

    @classmethod
    def _pick_structured_value(
        cls,
        item: Dict[str, Any],
        keys: Tuple[str, ...],
        item_separator: str = "；",
    ) -> str:
        for key in keys:
            if key in item:
                text = cls._stringify_structured_value(item.get(key), item_separator=item_separator)
                if text:
                    return text
        return ""

    @classmethod
    def _render_structured_character_cards(
        cls,
        items: Any,
        *,
        existing_names: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> str:
        if not isinstance(items, list):
            return ""

        existing = {normalize_character_name(name) for name in list(existing_names or [])}
        seen: set[str] = set()
        cards: List[str] = []

        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            name = normalize_character_name(raw_item.get("name") or raw_item.get("character_name") or "")
            if not name or name in existing or name in seen:
                continue
            seen.add(name)

            personality_anchor = cls._pick_structured_value(raw_item, ("personality_anchor",))
            if not personality_anchor:
                personality_anchor = _build_personality_anchor_text(
                    cls._pick_structured_value(raw_item, ("personality", "personality_traits")),
                    cls._pick_structured_value(raw_item, ("worldview_stance", "stance", "values")),
                )

            ability_and_limit = _build_ability_and_limit_text(
                cls._pick_structured_value(raw_item, ("ability_outline", "abilities", "skills", "specialty")),
                cls._pick_structured_value(raw_item, ("limitation", "flaw")),
            )

            mainline_binding = _build_mainline_binding_text(
                cls._pick_structured_value(raw_item, ("mainline_role", "story_function", "purpose")),
                cls._pick_structured_value(raw_item, ("mainline_clues", "story_threads")),
            )

            lines = [f"### 【姓名】：{name}"]
            field_pairs: List[Tuple[str, Optional[str]]] = [
                ("年龄/性别", cls._pick_structured_value(raw_item, ("age_gender", "demographics"))),
                ("故事立场", cls._pick_structured_value(raw_item, ("story_stance", "stance_alignment", "camp"))),
                ("角色定位", cls._pick_structured_value(raw_item, ("role_position", "role"))),
                ("所属势力", cls._pick_structured_value(raw_item, ("affiliation", "organization", "faction"))),
                ("外貌锚点", cls._pick_structured_value(raw_item, ("appearance_anchor", "appearance", "appearance_traits"))),
                ("性格锚点", personality_anchor),
                ("背景/当前处境", cls._pick_structured_value(raw_item, ("background_status", "background", "backstory"))),
                ("核心动机", cls._pick_structured_value(raw_item, ("motivation", "core_motivation"))),
                ("能力与限制", ability_and_limit),
                ("关键关系", cls._pick_structured_value(raw_item, ("key_relationships", "relationships_summary"))),
                ("主线绑定", mainline_binding),
                ("成长方向", cls._pick_structured_value(raw_item, ("growth_direction", "character_arc"))),
            ]
            for label, text in field_pairs:
                if text:
                    lines.append(f"【{label}】：{text}")

            cards.append("\n".join(lines))
            if limit is not None and len(cards) >= limit:
                break

        return "\n\n---\n\n".join(card for card in cards if card.strip())

    @classmethod
    def _render_structured_relationship_patch(cls, items: Any) -> str:
        if isinstance(items, str):
            return items.strip()
        if not isinstance(items, list):
            return ""

        lines: List[str] = []
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            source = cls._pick_structured_value(raw_item, ("source", "from"))
            target = cls._pick_structured_value(raw_item, ("target", "to"))
            relation_type = cls._pick_structured_value(raw_item, ("type", "relationship", "relation_type"))
            description = cls._pick_structured_value(raw_item, ("description", "summary", "detail"))
            if not source or not target:
                continue
            suffix = f"（{description}）" if description else ""
            lines.append(f"- {source} ↔ {target}：{relation_type or '关系'}{suffix}")

        return "\n".join(lines)

    @classmethod
    def _render_structured_chapter_blocks(cls, items: Any, *, detailed: bool) -> str:
        if not isinstance(items, list):
            return ""

        sections: List[str] = []
        for index, raw_item in enumerate(items, start=1):
            if not isinstance(raw_item, dict):
                continue

            title = cls._pick_structured_value(raw_item, ("title", "chapter_title"))
            if not title:
                title = f"新增章节{index}"

            involved_characters = cls._pick_structured_value(
                raw_item,
                ("involved_characters", "characters", "focus_characters"),
                item_separator="、",
            )
            scene_goal = cls._pick_structured_value(
                raw_item,
                ("scene_goal", "goal", "scene_objective"),
            )
            key_events = cls._pick_structured_value(raw_item, ("key_events", "events", "major_beats"))
            character_progress = cls._pick_structured_value(
                raw_item,
                ("character_progress", "character_arc", "relationship_shift"),
            )
            plot_function = cls._pick_structured_value(
                raw_item,
                ("plot_function", "story_function", "purpose"),
            )
            lines = [
                f"第{index}章：{title}",
                f"- 场景目标：{scene_goal or '待补充'}",
                f"- 冲突设计：{cls._pick_structured_value(raw_item, ('conflict_design', 'conflict', 'conflict_flow')) or '待补充'}",
                f"- 涉及人物：{involved_characters or '待定'}",
                f"- 关键事件：{key_events or '待补充'}",
                f"- 人物推进：{character_progress or '待补充'}",
                f"- 情节作用：{plot_function or '待补充'}",
                f"- 结尾钩子：{cls._pick_structured_value(raw_item, ('ending_hook', 'cliffhanger')) or '待补充'}",
            ]
            highlight_type = cls._pick_structured_value(raw_item, ('highlight_type', 'highlight', 'cool_point'))
            if highlight_type:
                lines.append(f"- 爽点类型：{highlight_type}")
            foreshadowing_item = cls._pick_structured_value(raw_item, ('foreshadowing_item', 'foreshadowing'))
            if foreshadowing_item:
                lines.append(f"- 伏笔事项：{foreshadowing_item}")
            sections.append("\n".join(lines))

        return "\n\n".join(section for section in sections if section.strip())

    @staticmethod
    def _append_unique_text(parts: List[str], text: str) -> None:
        value = str(text or "").strip()
        if not value or value in parts:
            return
        parts.append(value)

    @staticmethod
    def _build_alignment_warnings(
        new_character_names: List[str],
        validation: Optional[Dict[str, Any]],
    ) -> List[str]:
        if not new_character_names or not isinstance(validation, dict):
            return []

        unreferenced_names = {
            normalize_character_name(name): str(name).strip()
            for name in list(validation.get("unreferenced_characters") or [])
            if str(name).strip()
        }
        if not unreferenced_names:
            return []

        missing_new_names: List[str] = []
        for name in new_character_names:
            if normalize_character_name(name) in unreferenced_names:
                missing_new_names.append(name)

        if not missing_new_names:
            return []

        display_names = "、".join(missing_new_names[:5])
        if len(missing_new_names) > 5:
            display_names = f"{display_names} 等"
        return [
            (
                f"新增角色 {display_names} 尚未在更新后大纲中明确出场，"
                "建议下一轮优先补承接章节，或切换为人物优先策略。"
            )
        ]

    @staticmethod
    def _build_alignment_repair_note(repaired_names: List[str]) -> str:
        if not repaired_names:
            return ""

        display_names = "、".join(repaired_names[:5])
        if len(repaired_names) > 5:
            display_names = f"{display_names} 等"
        return f"已记录新增角色 {display_names} 的承接待补提示。"

    @staticmethod
    def _auto_repair_character_alignment(
        outline_text: str,
        new_character_names: List[str],
    ) -> Tuple[str, List[str]]:
        if not outline_text or not new_character_names:
            return outline_text or "", []

        deduped_names: List[str] = []
        seen = set()
        for name in new_character_names:
            normalized = normalize_character_name(name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped_names.append(str(name).strip())

        missing_names = [name for name in deduped_names if name and name not in outline_text]
        if not missing_names:
            return outline_text, []

        prefix, blocks = parse_outline_blocks(outline_text or "")
        if blocks:
            candidate_count = min(len(blocks), max(1, len(missing_names)))
            candidate_indexes = list(range(len(blocks) - candidate_count, len(blocks)))
            repaired_names: List[str] = []

            for index, name in enumerate(missing_names):
                target_block = blocks[candidate_indexes[index % len(candidate_indexes)]]
                if name in target_block.title or name in target_block.body:
                    continue
                note_line = f"- 人物承接待补：{name} 需在后续章节中正式出场，并与当前主线形成明确关联。"
                if target_block.body and target_block.body.strip():
                    target_block.body = f"{target_block.body.rstrip()}\n{note_line}".rstrip()
                else:
                    target_block.body = note_line
                repaired_names.append(name)

            return render_outline(prefix, blocks), repaired_names

        reminder_lines = ["## 协同角色承接待补"]
        for name in missing_names:
            reminder_lines.append(f"- {name}：需在后续章节或卷级细纲中正式出场，并承担明确剧情职责。")

        repaired_text = "\n".join(reminder_lines)
        if outline_text.strip():
            return f"{outline_text.rstrip()}\n\n{repaired_text}", missing_names
        return repaired_text, missing_names

    @staticmethod
    def _select_balanced_round_order(
        remaining_chapters: int,
        target_chapter_count: int,
        remaining_characters: int,
        target_character_count: int,
    ) -> str:
        if remaining_chapters > 0 and remaining_characters <= 0:
            return "plot_first"
        if remaining_characters > 0 and remaining_chapters <= 0:
            return "character_first"

        chapter_ratio = remaining_chapters / max(target_chapter_count, 1)
        character_ratio = remaining_characters / max(target_character_count, 1)
        return "plot_first" if chapter_ratio >= character_ratio else "character_first"

    def _build_epic_validation(
        self,
        framework_text: str,
        characters_text: str,
        estimated_chapters: int,
    ) -> Dict[str, Any]:
        character_names = extract_character_names(characters_text or "")
        referenced_characters = [name for name in character_names if name and name in (framework_text or "")]
        character_count = len(character_names)
        coverage_ratio = (len(referenced_characters) / character_count) if character_count else 0.0

        score = 45
        score += int(min(35, coverage_ratio * 35))
        score += int(min(20, estimated_chapters / 50))
        score = max(0, min(100, score))

        suggestions: List[str] = []
        if character_count and coverage_ratio < 0.6:
            suggestions.append("长篇框架中提及的人物覆盖率偏低，建议在卷级细纲阶段显式绑定关键人物。")
        suggestions.append("当前结果为长篇框架级协同，后续展开单卷细纲时需要继续做章节级验证。")

        return {
            "score": score,
            "chapter_count": estimated_chapters,
            "character_count": character_count,
            "coverage_ratio": round(coverage_ratio, 3),
            "referenced_characters": referenced_characters,
            "unreferenced_characters": [name for name in character_names if name not in referenced_characters],
            "suggestions": suggestions,
            "validation_stage": "epic_framework",
        }

    @staticmethod
    def _estimate_total_chapters_from_volumes_data(volumes_data: Optional[Dict[str, Any]]) -> int:
        if not isinstance(volumes_data, dict):
            return 0
        try:
            from app.services.outline_merger import normalize_volume_detail_layout

            volumes_data = normalize_volume_detail_layout(volumes_data)
        except Exception:
            pass
        total = 0
        for vol_data in (volumes_data.get("volumes") or {}).values():
            if vol_data.get("type") != "detail":
                continue
            chapter_range = vol_data.get("chapters_range") or [0, 0]
            try:
                total = max(total, int(chapter_range[1] or 0))
            except Exception:
                continue
        return total

    @classmethod
    def _estimate_epic_volume_count(cls, target_total_chapters: int) -> int:
        estimated = round(max(target_total_chapters, cls.EPIC_CHAPTER_THRESHOLD) / cls.EPIC_DEFAULT_CHAPTERS_PER_VOLUME)
        return max(cls.EPIC_MIN_VOLUMES, min(cls.EPIC_MAX_VOLUMES, estimated))

    @classmethod
    def _estimate_epic_chapter_range(cls, target_total_chapters: int) -> Tuple[int, int]:
        lower = max(cls.FRAMEWORK_PREFERRED_CHAPTER_THRESHOLD, int(target_total_chapters * 0.9))
        upper = max(lower + 60, int(target_total_chapters * 1.1))
        return lower, upper

    def build_story_expansion_plan(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str = "auto",
    ) -> Dict[str, Any]:
        _, outline_blocks = parse_outline_blocks(current_outline or "")
        character_names = extract_character_names(characters or "")

        current_chapter_count = len(outline_blocks)
        current_character_count = len(character_names)
        chapters_needed = max(0, (target_total_chapters or current_chapter_count) - current_chapter_count)
        characters_needed = max(0, (target_total_characters or current_character_count) - current_character_count)

        fallback_plan = {
            "strategy": strategy if strategy != "auto" else "balanced",
            "summary": "使用默认增量计划补足目标章节和角色。",
            "outline_ops": [],
            "character_ops": [],
            "relationship_ops": [],
        }

        if chapters_needed <= 0 and characters_needed <= 0:
            fallback_plan["summary"] = "目标章节数和目标人物数均不高于当前内容，无需新增。"
            return {
                **fallback_plan,
                "current_chapter_count": current_chapter_count,
                "current_character_count": current_character_count,
                "chapters_needed": chapters_needed,
                "characters_needed": characters_needed,
            }

        prompt = f"""
你是小说协同拓展架构师。请只做“delta 计划”，禁止重写旧大纲与旧人物。

【协同原则】
1. 已有章节全部视为锁定内容，只能新增章节。
2. 新章节允许插在中段，操作类型仅限 append 或 insert_after。
3. 已有人物全部视为锁定档案，只能新增角色、补关系、补章节职责。
4. 计划必须围绕“大纲拓展 + 人物拓展协同”输出。

【当前章节索引】
{self._summarize_outline_blocks(outline_blocks)}

【当前人物名单】
{("、".join(character_names) if character_names else "暂无")}

【世界观摘要】
{(world_setting or "暂无")[:3000]}

【当前大纲原文】
{(current_outline or "暂无")[:8000]}

【当前人物原文】
{(characters or "暂无")[:6000]}

【目标】
- 当前章节数：{current_chapter_count}
- 目标章节数：{target_total_chapters if target_total_chapters is not None else current_chapter_count}
- 需新增章节：{chapters_needed}
- 当前人物数：{current_character_count}
- 目标人物数：{target_total_characters if target_total_characters is not None else current_character_count}
- 需新增人物：{characters_needed}
- 偏好策略：{strategy}

请只返回 JSON，对象结构如下：
{{
  "strategy": "balanced",
  "summary": "一句话说明本轮协同拓展目的",
  "outline_ops": [
    {{
      "action": "append 或 insert_after",
      "after_chapter": 12,
      "count": 4,
      "goal": "这几章解决什么剧情缺口",
      "focus_characters": ["角色A", "角色B"],
      "notes": "为什么要插在这里"
    }}
  ],
  "character_ops": [
    {{
      "role_position": "导师/对手/盟友/信息角色/世界观角色",
      "purpose": "该角色补什么缺口",
      "related_existing": ["角色A"],
      "serve_chapter_hint": "第13-16章"
    }}
  ],
  "relationship_ops": [
    {{
      "source": "角色A",
      "target": "角色B",
      "type": "盟友/怀疑/利用/师徒/对手",
      "description": "15字以内"
    }}
  ]
}}
"""

        plan = self._invoke_json(prompt, fallback_plan)
        normalized_strategy = str(plan.get("strategy") or fallback_plan["strategy"]).strip()
        if strategy != "auto":
            normalized_strategy = strategy

        normalized_plan = {
            "strategy": normalized_strategy or "balanced",
            "summary": str(plan.get("summary") or fallback_plan["summary"]).strip(),
            "outline_ops": self._normalize_outline_ops(
                list(plan.get("outline_ops") or []),
                chapters_needed,
                current_chapter_count,
            ),
            "character_ops": list(plan.get("character_ops") or []),
            "relationship_ops": list(plan.get("relationship_ops") or []),
            "current_chapter_count": current_chapter_count,
            "current_character_count": current_character_count,
            "chapters_needed": chapters_needed,
            "characters_needed": characters_needed,
        }

        return normalized_plan

    def generate_character_delta(
        self,
        existing_characters: str,
        current_outline: str,
        world_setting: str,
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        characters_needed = int(plan.get("characters_needed") or 0)
        if characters_needed <= 0:
            return {
                "character_delta": "",
                "character_relationships": "",
                "new_characters": [],
            }

        existing_names = extract_character_names(existing_characters)
        op_summary_lines = []
        for index, op in enumerate(plan.get("character_ops") or [], start=1):
            role_type = op.get("role_position") or op.get("role_type") or "功能角色"
            purpose = op.get("purpose") or "补足人物职责"
            related = "、".join(op.get("related_existing") or []) or "暂无"
            chapter_hint = op.get("serve_chapter_hint") or "由你判断"
            op_summary_lines.append(
                f"{index}. 类型：{role_type}；目的：{purpose}；关联旧角色：{related}；服务章节：{chapter_hint}"
            )

        relationship_hints = []
        for item in plan.get("relationship_ops") or []:
            relationship_hints.append(
                f"- {item.get('source', '角色A')} ↔ {item.get('target', '角色B')}："
                f"{item.get('type', '关系')}（{item.get('description', '')}）"
            )

        json_prompt = f"""
你是小说人物协同设计师。请只新增 {characters_needed} 个角色，禁止重写旧角色。

【旧角色名单】
{("、".join(existing_names) if existing_names else "暂无")}

【人物缺口计划】
{chr(10).join(op_summary_lines) if op_summary_lines else "请根据大纲缺口自行补足角色功能"}

【关系补丁提示】
{chr(10).join(relationship_hints) if relationship_hints else "请自行补充与旧角色或新角色之间的关键关系"}

【世界观】
{(world_setting or "暂无")[:2500]}

【大纲摘要】
{(current_outline or "暂无")[:5000]}

请只返回 JSON，对象结构如下：
{{
  "characters": [
    {{
      "name": "角色名",
      "age_gender": "年龄/性别",
      "story_stance": "主角方/反派方/中立方/亦正亦邪",
      "role_position": "角色定位",
      "affiliation": "所属势力",
      "appearance_anchor": "外貌锚点",
      "personality_anchor": "性格锚点",
      "background_status": "背景/当前处境",
      "motivation": "核心动机",
      "ability_outline": "角色能力/特长",
      "limitation": "能力代价/短板",
      "key_relationships": "关键关系",
      "mainline_role": "主线剧情职责",
      "mainline_clues": "关联线索",
      "growth_direction": "成长方向"
    }}
  ],
  "relationship_patch": [
    {{
      "source": "角色A",
      "target": "角色B",
      "type": "关系类型",
      "description": "关系简述"
    }}
  ]
}}
"""

        structured_payload = self._invoke_json(
            json_prompt,
            fallback={"characters": [], "relationship_patch": []},
        )
        cards_text = self._render_structured_character_cards(
            structured_payload.get("characters"),
            existing_names=existing_names,
            limit=characters_needed,
        )
        relationships_text = self._render_structured_relationship_patch(
            structured_payload.get("relationship_patch")
        )

        if not cards_text:
            text_prompt = f"""
你是小说人物协同设计师。请只新增 {characters_needed} 个角色，禁止重写旧角色。

【旧角色名单】
{("、".join(existing_names) if existing_names else "暂无")}

【人物缺口计划】
{chr(10).join(op_summary_lines) if op_summary_lines else "请根据大纲缺口自行补足角色功能"}

【关系补丁提示】
{chr(10).join(relationship_hints) if relationship_hints else "请自行补充与旧角色或新角色之间的关键关系"}

【世界观】
{(world_setting or "暂无")[:2500]}

【大纲摘要】
{(current_outline or "暂无")[:5000]}

输出要求：
1. 只输出新增角色，不要复述旧角色。
2. 严格输出 {characters_needed} 个角色卡。
3. 角色卡使用统一格式，便于后续同步：

### 【姓名】：角色名
【年龄/性别】：...
【故事立场】：...
【角色定位】：...
【所属势力】：...
【外貌锚点】：...
【性格锚点】：性格：...
价值倾向：...
【背景/当前处境】：...
【核心动机】：...
【能力与限制】：能力：...
限制：...
【关键关系】：...
【主线绑定】：剧情职责：...
关联线索：...
【成长方向】：...
---

最后另起一节，输出：
## 关系补丁
- 角色A ↔ 角色B：关系类型（简述）
"""

            raw_text = self._invoke_text(text_prompt)
            split_pattern = re.split(r"(?m)^##\s*关系补丁\s*$", raw_text, maxsplit=1)
            if len(split_pattern) == 2:
                cards_text, relationships_text = split_pattern[0].strip(), split_pattern[1].strip()
            else:
                cards_text, relationships_text = raw_text.strip(), ""

        new_character_names = extract_character_names(cards_text)
        return {
            "character_delta": cards_text,
            "character_relationships": relationships_text,
            "new_characters": new_character_names,
        }

    @staticmethod
    def _find_insert_index(blocks: List[OutlineBlock], after_chapter: int) -> int:
        fallback = len(blocks)
        last_anchor_index: Optional[int] = None

        for index, block in enumerate(blocks):
            if block.source == "generated" and block.anchor_after == after_chapter:
                last_anchor_index = index
                fallback = index + 1
                continue
            if block.original_number == after_chapter:
                last_anchor_index = index
                fallback = index + 1
                continue
            if block.source == "existing" and block.original_number > after_chapter:
                return (last_anchor_index + 1) if last_anchor_index is not None else index

        return fallback

    def _generate_new_chapters_for_op(
        self,
        op: Dict[str, Any],
        blocks: List[OutlineBlock],
        world_setting: str,
        characters_text: str,
        new_character_cards: str,
    ) -> Tuple[List[OutlineBlock], str]:
        count = int(op.get("count") or 0)
        if count <= 0:
            return [], ""

        after_chapter = op.get("after_chapter")
        action = op.get("action") or "append"

        anchor_block = None
        next_block = None
        if after_chapter:
            for block in blocks:
                if block.source == "existing" and block.original_number == after_chapter:
                    anchor_block = block
                if (
                    block.source == "existing"
                    and block.original_number > after_chapter
                    and next_block is None
                ):
                    next_block = block
                    break

        placement = "接在当前大纲末尾"
        if action == "insert_after" and after_chapter:
            placement = f"插入到第{after_chapter}章之后"

        anchor_summary = (
            f"第{after_chapter}章：{anchor_block.title}\n{anchor_block.body[:800]}"
            if anchor_block
            else "无明确锚点"
        )
        next_summary = (
            f"第{next_block.original_number}章：{next_block.title}\n{next_block.body[:800]}"
            if next_block
            else "无，表示可在结尾延展"
        )

        json_prompt = f"""
你是小说章节拓展策划师。请只生成 {count} 个新增章节，不允许改写旧章节。

【插入位置】
{placement}

【当前锚点章节】
{anchor_summary}

【后继锁定章节】
{next_summary}

【本次剧情目标】
{op.get("goal") or "补强剧情推进"}

【本次重点人物】
{("、".join(op.get("focus_characters") or []) if op.get("focus_characters") else "请按剧情自行分配")}

【新增角色卡】
{(new_character_cards or "本轮未新增角色")[:3500]}

【完整人物上下文】
{(characters_text or "暂无")[:4000]}

【世界观】
{(world_setting or "暂无")[:2500]}

请只返回 JSON，对象结构如下：
{{
      "chapters": [
        {{
          "title": "章节标题",
          "scene_goal": "场景目标",
          "conflict_design": "冲突设计",
          "key_events": "关键事件",
          "involved_characters": ["角色A", "角色B"],
          "character_progress": "人物推进",
          "plot_function": "情节作用",
          "ending_hook": "结尾钩子",
          "highlight_type": "爽点类型",
          "foreshadowing_item": "伏笔事项"
        }}
      ]
}}
"""

        structured_payload = self._invoke_json(
            json_prompt,
            fallback={"chapters": []},
        )
        raw_text = self._render_structured_chapter_blocks(
            structured_payload.get("chapters"),
            detailed=True,
        )

        if not raw_text:
            prompt = f"""
你是小说章节拓展策划师。请只生成 {count} 个新增章节，不允许改写旧章节。

【插入位置】
{placement}

【当前锚点章节】
{anchor_summary}

【后继锁定章节】
{next_summary}

【本次剧情目标】
{op.get("goal") or "补强剧情推进"}

【本次重点人物】
{("、".join(op.get("focus_characters") or []) if op.get("focus_characters") else "请按剧情自行分配")}

【新增角色卡】
{(new_character_cards or "本轮未新增角色")[:3500]}

【完整人物上下文】
{(characters_text or "暂无")[:4000]}

【世界观】
{(world_setting or "暂无")[:2500]}

输出要求：
1. 只输出新增章节。
2. 严格输出 {count} 个章节。
3. 每章使用以下格式：

第1章：章节标题
- 场景目标：[地点] + [在场人物] + [要达成什么]（30-40字）
- 冲突设计：① 初始障碍 → ② 升级转折 → ③ 爽点爆发（60-80字）
- 关键事件：按 2-4 个关键节点概括本章必发生的事
- 涉及人物：角色A、角色B
- 人物推进：主角或关键配角发生了什么变化，关系如何推进
- 情节作用：本章在整段剧情中的职责（承接/升级/埋伏笔/爆点前置等）
- 结尾钩子：[悬念/危机/反转]（20-30字）
- 爽点类型：[如本章存在明确爽点再写]
- 伏笔事项：[本章埋设或回收的伏笔，如无则写"无"]

4. 若是插入式拓展，新增章节必须自然衔接锚点章节与后继章节。
"""

            raw_text = self._invoke_text(prompt)
        _, generated_blocks = parse_outline_blocks(raw_text)

        for block in generated_blocks:
            block.locked = False
            block.source = "generated"
            block.anchor_after = after_chapter if isinstance(after_chapter, int) else None
            block.original_number = after_chapter if isinstance(after_chapter, int) else 0

        return generated_blocks, raw_text.strip()

    def generate_outline_delta(
        self,
        current_outline: str,
        characters_text: str,
        world_setting: str,
        plan: Dict[str, Any],
        new_character_cards: str,
    ) -> Dict[str, Any]:
        prefix, blocks = parse_outline_blocks(current_outline or "")
        chapters_needed = int(plan.get("chapters_needed") or 0)

        if chapters_needed <= 0:
            return {
                "plot_outline": current_outline or "",
                "outline_delta": "",
                "outline_ops": [],
                "current_chapter_count": len(blocks),
            }

        if not blocks:
            structured_payload = self._invoke_json(
                f"""
你是小说章节拓展策划师。当前原版大纲没有显式章节，视为锁定总纲。
请基于它新增 {chapters_needed} 个章节卡，不要重写原文。

【锁定原版大纲】
{(current_outline or "暂无")[:6000]}

【人物上下文】
{(characters_text or "暂无")[:4000]}

【新增角色卡】
{(new_character_cards or "本轮未新增角色")[:3000]}

【世界观】
{(world_setting or "暂无")[:2500]}

请只返回 JSON，对象结构如下：
{{
  "chapters": [
    {{
      "title": "章节标题",
      "scene_goal": "场景目标",
      "conflict_design": "冲突设计",
      "key_events": "关键事件",
      "involved_characters": ["角色A", "角色B"],
      "character_progress": "人物推进",
      "plot_function": "情节作用",
      "ending_hook": "结尾钩子",
      "highlight_type": "爽点类型",
      "foreshadowing_item": "伏笔事项"
    }}
  ]
}}
""",
                fallback={"chapters": []},
            )
            raw_text = self._render_structured_chapter_blocks(
                structured_payload.get("chapters"),
                detailed=True,
            )
            if not raw_text:
                raw_text = self._invoke_text(
                    f"""
你是小说章节拓展策划师。当前原版大纲没有显式章节，视为锁定总纲。
请基于它新增 {chapters_needed} 个章节卡，不要重写原文。

【锁定原版大纲】
{(current_outline or "暂无")[:6000]}

【人物上下文】
{(characters_text or "暂无")[:4000]}

【新增角色卡】
{(new_character_cards or "本轮未新增角色")[:3000]}

【世界观】
{(world_setting or "暂无")[:2500]}

请严格输出 {chapters_needed} 个章节，格式如下：
第1章：章节标题
- 场景目标：...
- 冲突设计：...
- 关键事件：...
- 涉及人物：...
- 人物推进：...
- 情节作用：...
- 结尾钩子：...
- 爽点类型：...
- 伏笔事项：...
"""
                )
            _, generated_blocks = parse_outline_blocks(raw_text)
            merged_outline = build_outline_delta_section(current_outline or "", raw_text)
            chapter_count = len(generated_blocks)
            outline_ops_executed = [
                {
                    "action": "append",
                    "after_chapter": None,
                    "requested_count": chapters_needed,
                    "generated_count": chapter_count,
                    "generated_titles": [block.title for block in generated_blocks],
                }
            ]
            return {
                "plot_outline": merged_outline,
                "outline_delta": raw_text.strip(),
                "outline_ops": outline_ops_executed,
                "current_chapter_count": chapter_count,
            }

        outline_delta_parts: List[str] = []
        outline_ops_executed: List[Dict[str, Any]] = []
        mutable_blocks = list(blocks)

        for op in plan.get("outline_ops") or []:
            generated_blocks, raw_text = self._generate_new_chapters_for_op(
                op=op,
                blocks=mutable_blocks,
                world_setting=world_setting,
                characters_text=characters_text,
                new_character_cards=new_character_cards,
            )
            if raw_text:
                outline_delta_parts.append(raw_text)

            after_chapter = op.get("after_chapter")
            if generated_blocks:
                if isinstance(after_chapter, int):
                    insert_index = self._find_insert_index(mutable_blocks, after_chapter)
                else:
                    insert_index = len(mutable_blocks)
                mutable_blocks[insert_index:insert_index] = generated_blocks

            outline_ops_executed.append(
                {
                    "action": op.get("action") or "append",
                    "after_chapter": after_chapter,
                    "requested_count": int(op.get("count") or 0),
                    "generated_count": len(generated_blocks),
                    "generated_titles": [block.title for block in generated_blocks],
                    "goal": op.get("goal") or "",
                }
            )

        plot_outline = render_outline(prefix, mutable_blocks)
        return {
            "plot_outline": plot_outline,
            "outline_delta": "\n\n".join(part for part in outline_delta_parts if part.strip()),
            "outline_ops": outline_ops_executed,
            "current_chapter_count": len(mutable_blocks),
        }

    def _run_outline_round(
        self,
        current_outline: str,
        world_setting: str,
        characters: str,
        current_chapter_count: int,
        increment: int,
        target_total_chapters: int,
        overall_target_chapters: Optional[int] = None,
    ) -> Dict[str, Any]:
        expander = self._get_expander()
        return expander.expand_plot_outline_incremental(
            current_outline=current_outline,
            world_setting=world_setting,
            characters=characters,
            current_chapter_count=current_chapter_count,
            increment=increment,
            target_total_chapters=target_total_chapters,
            overall_target_chapters=overall_target_chapters,
        )

    @classmethod
    def _resolve_iterative_outline_round_text(
        cls,
        previous_outline: str,
        result: Dict[str, Any],
        previous_chapter_count: int,
    ) -> Tuple[str, str]:
        previous_text = str(previous_outline or "")
        next_outline_text = str(result.get("expanded_outline") or previous_text)
        round_outline_delta = str(result.get("outline_delta") or "").strip()

        if not round_outline_delta:
            chapter_breakdown = str(result.get("chapter_breakdown") or "").strip()
            if chapter_breakdown:
                chapter_breakdown_delta = cls._extract_outline_delta_text(
                    previous_text,
                    chapter_breakdown,
                    previous_chapter_count,
                )
                if chapter_breakdown_delta:
                    round_outline_delta = chapter_breakdown_delta
                    next_outline_text = build_outline_delta_section(previous_text, chapter_breakdown_delta)

        if not round_outline_delta:
            round_outline_delta = cls._extract_outline_delta_text(
                previous_text,
                next_outline_text,
                previous_chapter_count,
            )

        return next_outline_text, round_outline_delta

    def _run_character_round(
        self,
        current_characters: str,
        world_setting: str,
        plot_outline: str,
        current_character_count: int,
        increment: int,
        target_total_characters: int,
    ) -> Dict[str, Any]:
        expander = self._get_expander()
        return expander.expand_characters_incremental(
            main_characters=current_characters,
            world_setting=world_setting,
            plot_outline=plot_outline,
            current_character_count=current_character_count,
            increment=increment,
            target_total_characters=target_total_characters,
        )

    def _expand_characters_to_target(
        self,
        current_characters: str,
        world_setting: str,
        plot_outline: str,
        current_character_count: int,
        target_total_characters: int,
    ) -> Dict[str, Any]:
        rounds: List[Dict[str, Any]] = []
        stop_reasons: List[str] = []
        relationship_parts: List[str] = []
        character_delta_parts: List[str] = []
        characters_text = current_characters or ""
        current_count = current_character_count

        if target_total_characters <= current_count:
            return {
                "characters_text": characters_text,
                "current_character_count": current_count,
                "character_delta": "",
                "character_relationships": "",
                "rounds": rounds,
                "stop_reasons": stop_reasons,
            }

        for iteration in range(1, self.ITERATIVE_MAX_ROUNDS + 1):
            if current_count >= target_total_characters:
                break

            increment = min(self.ITERATIVE_CHARACTER_STEP, target_total_characters - current_count)
            round_result = self._run_character_round(
                current_characters=characters_text,
                world_setting=world_setting,
                plot_outline=plot_outline,
                current_character_count=current_count,
                increment=increment,
                target_total_characters=target_total_characters,
            )
            next_characters = round_result.get("all_characters") or characters_text
            next_count = self._resolve_character_count(
                next_characters,
                round_result.get("current_character_count"),
                current_count,
            )
            round_character_delta = self._extract_character_delta_text(characters_text, next_characters)
            self._append_unique_text(character_delta_parts, round_character_delta)
            self._append_unique_text(relationship_parts, round_result.get("character_relationships") or "")

            rounds.append(
                {
                    "round": iteration,
                    "before_character_count": current_count,
                    "after_character_count": next_count,
                    "increment_requested": increment,
                    "post_validation_score": round_result.get("post_validation_score", 0),
                    "cards_response_mode": round_result.get("cards_response_mode"),
                    "cards_retry_used": bool(round_result.get("cards_retry_used", False)),
                    "recognized_new_character_count": int(round_result.get("recognized_new_character_count") or 0),
                    "recognized_new_character_names": list(round_result.get("recognized_new_character_names") or []),
                }
            )

            characters_text = next_characters

            if next_count <= current_count:
                stop_reasons.append("人物扩展未产生新增内容，为避免空转已提前停止。")
                break

            current_count = next_count

            if round_result.get("should_optimize_first"):
                stop_reasons.append("人物-情节匹配度偏低，已停止继续新增人物。")
                break

            validation_score = int(round_result.get("post_validation_score") or 0)
            if 0 < validation_score < 60:
                stop_reasons.append(f"人物-情节匹配度降至 {validation_score}/100，已停止继续新增人物。")
                break

            if not round_result.get("should_continue", True) and current_count < target_total_characters:
                reason = str(round_result.get("continue_reason") or "").strip()
                stop_reasons.append(reason or "人物侧模型建议停止继续扩展。")
                break

        return {
            "characters_text": characters_text,
            "current_character_count": current_count,
            "character_delta": "\n\n".join(character_delta_parts),
            "character_relationships": "\n\n".join(relationship_parts),
            "rounds": rounds,
            "stop_reasons": stop_reasons,
        }

    def _execute_delta_mode(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str = "auto",
        mode_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        validation_before = evaluate_story_coordination(current_outline or "", characters or "")
        plan = self.build_story_expansion_plan(
            current_outline=current_outline,
            characters=characters,
            world_setting=world_setting,
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            strategy=strategy,
        )

        chapters_needed = int(plan.get("chapters_needed") or 0)
        characters_needed = int(plan.get("characters_needed") or 0)
        resolved_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation_before,
            chapters_needed=chapters_needed,
            characters_needed=characters_needed,
        )
        plan["strategy"] = resolved_strategy

        if chapters_needed > self.SHORT_CHAPTER_DELTA_LIMIT:
            raise ValueError("协同拓展一次最多新增 30 章，请切换为分轮模式执行。")
        if characters_needed > self.SHORT_CHARACTER_DELTA_LIMIT:
            raise ValueError("协同拓展一次最多新增 10 个角色，请切换为分轮模式执行。")
        if chapters_needed <= 0 and characters_needed <= 0:
            raise ValueError("目标章节数和目标人物数均不高于当前内容，无需协同拓展。")

        if resolved_strategy == "plot_first":
            outline_delta = self.generate_outline_delta(
                current_outline=current_outline,
                characters_text=characters or "",
                world_setting=world_setting,
                plan=plan,
                new_character_cards="",
            )
            character_delta = self.generate_character_delta(
                existing_characters=characters,
                current_outline=outline_delta["plot_outline"],
                world_setting=world_setting,
                plan=plan,
            )
            merged_characters = merge_character_delta(
                existing_characters=characters or "",
                new_character_cards=character_delta["character_delta"],
                relationship_patch=character_delta["character_relationships"],
            )
        else:
            character_delta = self.generate_character_delta(
                existing_characters=characters,
                current_outline=current_outline,
                world_setting=world_setting,
                plan=plan,
            )

            merged_characters = merge_character_delta(
                existing_characters=characters or "",
                new_character_cards=character_delta["character_delta"],
                relationship_patch=character_delta["character_relationships"],
            )

            outline_delta = self.generate_outline_delta(
                current_outline=current_outline,
                characters_text=merged_characters,
                world_setting=world_setting,
                plan=plan,
                new_character_cards=character_delta["character_delta"],
            )

        current_character_count = len(extract_character_names(merged_characters))
        new_characters = self._collect_new_character_names(characters or "", merged_characters)
        repaired_plot_outline, alignment_repairs = self._auto_repair_character_alignment(
            outline_delta["plot_outline"],
            new_characters,
        )
        outline_delta["plot_outline"] = repaired_plot_outline
        if outline_delta["outline_delta"] and outline_delta["outline_delta"].strip():
            repaired_outline_delta, delta_alignment_repairs = self._auto_repair_character_alignment(
                outline_delta["outline_delta"],
                new_characters,
            )
            outline_delta["outline_delta"] = repaired_outline_delta
            alignment_repairs = list(dict.fromkeys([*alignment_repairs, *delta_alignment_repairs]))
        outline_delta["plot_outline"] = normalize_outline_text(
            outline_delta["plot_outline"],
            merged_characters,
        )
        if outline_delta["outline_delta"] and outline_delta["outline_delta"].strip():
            outline_delta["outline_delta"] = normalize_outline_text(
                outline_delta["outline_delta"],
                merged_characters,
            )
        validation_after = evaluate_story_coordination(
            outline_delta["plot_outline"],
            merged_characters,
        )
        alignment_warnings = self._build_alignment_warnings(new_characters, validation_after)
        coordination_summary = plan["summary"]
        repair_note = self._build_alignment_repair_note(alignment_repairs)
        if repair_note:
            coordination_summary = f"{coordination_summary} {repair_note}"
        if alignment_warnings:
            coordination_summary = f"{coordination_summary} {' '.join(alignment_warnings)}"

        return {
            "execution_mode": "delta",
            "execution_mode_reason": (mode_info or {}).get("reason", ""),
            "strategy": resolved_strategy,
            "coordination_summary": coordination_summary,
            "plan": plan,
            "plot_outline": outline_delta["plot_outline"],
            "characters": merged_characters,
            "outline_delta": outline_delta["outline_delta"],
            "character_delta": character_delta["character_delta"],
            "character_relationships": character_delta["character_relationships"],
            "outline_ops": outline_delta["outline_ops"],
            "execution_rounds": [
                {
                    "round": 1,
                    "mode": "delta",
                    "strategy": resolved_strategy,
                    "chapters_generated": sum(
                        int(item.get("generated_count") or 0)
                        for item in outline_delta["outline_ops"]
                    ),
                    "characters_generated": len(new_characters),
                }
            ],
            "new_characters": new_characters,
            "alignment_repairs": alignment_repairs,
            "current_chapter_count": outline_delta["current_chapter_count"],
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
            "alignment_warnings": alignment_warnings,
        }

    def _execute_iterative_mode(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str,
        mode_info: Dict[str, Any],
        auto_supplement_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        validation_before = evaluate_story_coordination(current_outline or "", characters or "")
        resolved_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation_before,
            chapters_needed=int(mode_info.get("chapters_needed") or 0),
            characters_needed=int(mode_info.get("characters_needed") or 0),
        )

        current_outline_text = current_outline or ""
        current_characters = characters or ""
        current_chapter_count = int(mode_info.get("current_chapter_count") or 0)
        current_character_count = int(mode_info.get("current_character_count") or 0)
        initial_chapter_count = current_chapter_count
        target_chapter_count = int(mode_info.get("target_chapter_count") or current_chapter_count)
        target_character_count = int(mode_info.get("target_character_count") or current_character_count)
        stage_target_character_count = target_character_count

        rounds: List[Dict[str, Any]] = []
        stop_reasons: List[str] = []
        outline_delta_parts: List[str] = []
        relationship_parts: List[str] = []
        character_delta_parts: List[str] = []
        outline_active = target_chapter_count > current_chapter_count
        character_active = target_character_count > current_character_count
        dynamic_character_task_target = self._coerce_non_negative_int(
            ((auto_supplement_plan or {}).get("character_plan") or {}).get("task_target_characters"),
        )

        def refresh_target_character_count() -> int:
            nonlocal target_character_count, character_active
            if dynamic_character_task_target <= target_character_count:
                return target_character_count
            total_chapter_delta = max(0, target_chapter_count - initial_chapter_count)
            if total_chapter_delta <= 0:
                return target_character_count
            completed_chapter_delta = min(
                total_chapter_delta,
                max(0, current_chapter_count - initial_chapter_count),
            )
            progress = completed_chapter_delta / total_chapter_delta
            dynamic_target = stage_target_character_count + int(
                math.ceil((dynamic_character_task_target - stage_target_character_count) * progress)
            )
            if dynamic_target > target_character_count:
                target_character_count = min(dynamic_character_task_target, dynamic_target)
            if target_character_count > current_character_count:
                character_active = True
            return target_character_count

        for iteration in range(1, self.ITERATIVE_MAX_ROUNDS + 1):
            refresh_target_character_count()
            remaining_chapters = max(0, target_chapter_count - current_chapter_count)
            remaining_characters = max(0, target_character_count - current_character_count)
            if remaining_chapters <= 0 and remaining_characters <= 0:
                break

            round_strategy = resolved_strategy
            if round_strategy == "balanced":
                round_strategy = self._select_balanced_round_order(
                    remaining_chapters=remaining_chapters,
                    target_chapter_count=target_chapter_count,
                    remaining_characters=remaining_characters,
                    target_character_count=target_character_count,
                )

            before_chapter_count = current_chapter_count
            before_character_count = current_character_count
            round_record: Dict[str, Any] = {
                "round": iteration,
                "mode": "iterative",
                "strategy": round_strategy,
                "before_chapter_count": before_chapter_count,
                "before_character_count": before_character_count,
            }

            def run_plot_side() -> Optional[Dict[str, Any]]:
                nonlocal current_outline_text, current_chapter_count, outline_active
                if not outline_active:
                    return None
                before_round_chapter_count = current_chapter_count
                pending = max(0, target_chapter_count - current_chapter_count)
                if pending <= 0:
                    outline_active = False
                    return None
                increment = min(self.ITERATIVE_CHAPTER_STEP, pending)
                result = self._run_outline_round(
                    current_outline=current_outline_text,
                    world_setting=world_setting,
                    characters=current_characters,
                    current_chapter_count=current_chapter_count,
                    increment=increment,
                    target_total_chapters=current_chapter_count + increment,
                    overall_target_chapters=target_chapter_count,
                )
                next_outline_text, round_outline_delta = self._resolve_iterative_outline_round_text(
                    current_outline_text,
                    result,
                    current_chapter_count,
                )
                self._append_unique_text(outline_delta_parts, round_outline_delta)
                current_outline_text = next_outline_text
                current_chapter_count = self._resolve_outline_count(
                    next_outline_text,
                    result.get("current_chapter_count"),
                    current_chapter_count,
                )
                if current_chapter_count <= before_round_chapter_count and not round_outline_delta:
                    outline_active = False
                    stop_reasons.append(
                        self._normalize_outline_stop_reason(
                            str(result.get("continue_reason") or ""),
                            before_chapter_count=before_round_chapter_count,
                            after_chapter_count=current_chapter_count,
                            outline_delta=round_outline_delta,
                        )
                    )
                elif (
                    not result.get("should_continue", True)
                    and current_chapter_count < target_chapter_count
                    and current_chapter_count <= before_round_chapter_count
                ):
                    outline_active = False
                    stop_reasons.append(
                        self._normalize_outline_stop_reason(
                            str(result.get("continue_reason") or ""),
                            before_chapter_count=before_round_chapter_count,
                            after_chapter_count=current_chapter_count,
                            outline_delta=round_outline_delta,
                        )
                    )
                return {
                    "increment_requested": increment,
                    "after_chapter_count": current_chapter_count,
                    "outline_delta": round_outline_delta,
                    "continue_reason": result.get("continue_reason", ""),
                }

            def run_character_side() -> Optional[Dict[str, Any]]:
                nonlocal current_characters, current_character_count, character_active, target_character_count
                if not character_active:
                    return None
                before_round_character_count = current_character_count
                refresh_target_character_count()
                pending = max(0, target_character_count - current_character_count)
                if pending <= 0:
                    character_active = False
                    return None
                increment = min(self.ITERATIVE_CHARACTER_STEP, pending)
                result = self._run_character_round(
                    current_characters=current_characters,
                    world_setting=world_setting,
                    plot_outline=current_outline_text,
                    current_character_count=current_character_count,
                    increment=increment,
                    target_total_characters=target_character_count,
                )
                next_characters = result.get("all_characters") or current_characters
                next_count = self._resolve_character_count(
                    next_characters,
                    result.get("current_character_count"),
                    current_character_count,
                )
                round_character_delta = self._extract_character_delta_text(current_characters, next_characters)
                self._append_unique_text(character_delta_parts, round_character_delta)
                self._append_unique_text(relationship_parts, result.get("character_relationships") or "")

                current_characters = next_characters

                if next_count <= before_round_character_count:
                    character_active = False
                    stop_reasons.append(
                        self._normalize_character_stop_reason(
                            str(result.get("continue_reason") or ""),
                            before_character_count=before_round_character_count,
                            after_character_count=before_round_character_count,
                            target_character_count=target_character_count,
                        )
                    )
                else:
                    current_character_count = next_count

                if next_count > before_round_character_count and result.get("should_optimize_first"):
                    character_active = False
                    stop_reasons.append("人物-情节匹配度偏低，已停止继续新增人物。")

                validation_score = int(result.get("post_validation_score") or 0)
                if (
                    next_count > before_round_character_count
                    and 0 < validation_score < 60
                    and current_character_count < target_character_count
                ):
                    character_active = False
                    stop_reasons.append(f"人物-情节匹配度降至 {validation_score}/100，已停止继续新增人物。")

                if (
                    next_count > before_round_character_count
                    and not result.get("should_continue", True)
                    and current_character_count < target_character_count
                ):
                    character_active = False
                    stop_reasons.append(
                        self._normalize_character_stop_reason(
                            str(result.get("continue_reason") or ""),
                            before_character_count=before_round_character_count,
                            after_character_count=current_character_count,
                            target_character_count=target_character_count,
                        )
                    )

                return {
                    "increment_requested": increment,
                    "target_character_count": target_character_count,
                    "after_character_count": current_character_count,
                    "post_validation_score": result.get("post_validation_score", 0),
                    "continue_reason": result.get("continue_reason", ""),
                    "cards_response_mode": result.get("cards_response_mode"),
                    "cards_retry_used": bool(result.get("cards_retry_used", False)),
                    "recognized_new_character_count": int(result.get("recognized_new_character_count") or 0),
                    "recognized_new_character_names": list(result.get("recognized_new_character_names") or []),
                }

            if round_strategy == "plot_first":
                round_record["plot"] = run_plot_side()
                round_record["character"] = run_character_side()
            else:
                round_record["character"] = run_character_side()
                round_record["plot"] = run_plot_side()

            round_record["after_chapter_count"] = current_chapter_count
            round_record["after_character_count"] = current_character_count

            if (
                current_chapter_count == before_chapter_count
                and current_character_count == before_character_count
            ):
                if not outline_active and not character_active:
                    break
                round_record["validation"] = evaluate_story_coordination(current_outline_text, current_characters)
                rounds.append(round_record)
                stop_reasons.append("本轮协同未产生任何新增内容，已提前停止。")
                break

            round_record["validation"] = evaluate_story_coordination(current_outline_text, current_characters)
            rounds.append(round_record)

            if not outline_active and not character_active:
                break

        new_character_names = self._collect_new_character_names(characters or "", current_characters)
        current_outline_text, alignment_repairs = self._auto_repair_character_alignment(
            current_outline_text,
            new_character_names,
        )
        current_outline_text = normalize_outline_text(current_outline_text, current_characters)
        normalized_outline_delta = "\n\n".join(outline_delta_parts)
        if normalized_outline_delta.strip():
            normalized_outline_delta = normalize_outline_text(normalized_outline_delta, current_characters)
        validation_after = evaluate_story_coordination(current_outline_text, current_characters)
        current_chapter_count = self._resolve_outline_count(
            current_outline_text,
            validation_after.get("chapter_count"),
            current_chapter_count,
        )
        current_character_count = self._resolve_character_count(
            current_characters,
            validation_after.get("character_count"),
            current_character_count,
        )
        alignment_warnings = self._build_alignment_warnings(new_character_names, validation_after)
        reached_target = (
            current_chapter_count >= target_chapter_count
            and current_character_count >= target_character_count
        )

        if reached_target:
            summary = "已通过分轮协同达到目标章节数和人物数。"
        else:
            pending_parts = []
            if current_chapter_count < target_chapter_count:
                pending_parts.append(f"章节尚差 {target_chapter_count - current_chapter_count} 章")
            if current_character_count < target_character_count:
                pending_parts.append(f"人物尚差 {target_character_count - current_character_count} 人")
            reason_text = "；".join(dict.fromkeys([reason for reason in stop_reasons if reason]))
            summary = "分轮协同已执行完当前可安全推进的部分"
            if pending_parts:
                summary += f"，{', '.join(pending_parts)}"
            if reason_text:
                summary += f"。停止原因：{reason_text}"
        repair_note = self._build_alignment_repair_note(alignment_repairs)
        if repair_note:
            summary += f" {repair_note}"
        if alignment_warnings:
            summary += f" {' '.join(alignment_warnings)}"

        return {
            "execution_mode": "iterative",
            "execution_mode_reason": mode_info.get("reason", ""),
            "strategy": resolved_strategy,
            "coordination_summary": summary,
            "plan": {
                "strategy": resolved_strategy,
                "mode": "iterative",
                "target_chapter_count": target_chapter_count,
                "target_character_count": target_character_count,
            },
            "plot_outline": current_outline_text,
            "characters": current_characters,
            "outline_delta": normalized_outline_delta,
            "character_delta": "\n\n".join(character_delta_parts),
            "character_relationships": "\n\n".join(relationship_parts),
            "outline_ops": rounds,
            "execution_rounds": rounds,
            "new_characters": new_character_names,
            "alignment_repairs": alignment_repairs,
            "current_chapter_count": current_chapter_count,
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
            "alignment_warnings": alignment_warnings,
            "stop_reasons": stop_reasons,
        }

    def _execute_epic_mode(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str,
        mode_info: Dict[str, Any],
        epic_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.outline_merger import build_epic_volumes_json, parse_framework_to_volumes

        validation_before = evaluate_story_coordination(current_outline or "", characters or "")
        resolved_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation_before,
            chapters_needed=int(mode_info.get("chapters_needed") or 0),
            characters_needed=int(mode_info.get("characters_needed") or 0),
        )

        normalized_epic_config = self._normalize_epic_config(epic_config)
        target_chapter_count = max(
            int(target_total_chapters or 0),
            self.planned_chapters_max or 0,
            self.EPIC_CHAPTER_THRESHOLD,
        )
        target_character_count = int(
            mode_info.get("target_character_count")
            or target_total_characters
            or mode_info.get("current_character_count")
            or 0
        )

        current_characters = characters or ""
        current_character_count = int(mode_info.get("current_character_count") or 0)
        character_relationships = ""
        character_delta = ""
        execution_rounds: List[Dict[str, Any]] = []
        stop_reasons: List[str] = []

        if resolved_strategy == "character_first" and target_character_count > current_character_count:
            character_program = self._expand_characters_to_target(
                current_characters=current_characters,
                world_setting=world_setting,
                plot_outline=current_outline or "",
                current_character_count=current_character_count,
                target_total_characters=target_character_count,
            )
            current_characters = character_program["characters_text"]
            current_character_count = character_program["current_character_count"]
            character_relationships = character_program["character_relationships"]
            character_delta = character_program["character_delta"]
            stop_reasons.extend(character_program["stop_reasons"])
            for item in character_program["rounds"]:
                execution_rounds.append({"stage": "character_expand", **item})

        framework_world_setting = world_setting or ""
        if current_outline and current_outline.strip():
            outline_context = current_outline[:6000]
            framework_world_setting = (
                f"{framework_world_setting}\n\n【现有主线与基础大纲】\n{outline_context}"
                if framework_world_setting
                else f"【现有主线与基础大纲】\n{outline_context}"
            )

        explicit_range = normalized_epic_config.get("chapter_range")
        chapter_range = (
            explicit_range
            if explicit_range
            else self._estimate_epic_chapter_range(target_chapter_count)
        )
        total_volumes = int(
            normalized_epic_config.get("total_volumes")
            or self._estimate_epic_volume_count(target_chapter_count)
        )
        framework_result = self._get_expander().generate_epic_framework(
            world_setting=framework_world_setting,
            characters=current_characters,
            total_volumes=total_volumes,
            total_chapters_range=chapter_range,
        )

        plot_outline = framework_result.get("expanded_outline") or current_outline or ""
        estimated_chapters = int(framework_result.get("estimated_chapters") or target_chapter_count)
        try:
            volumes_data = parse_framework_to_volumes(plot_outline, total_volumes)
            epic_volumes_detail = build_epic_volumes_json(volumes_data)
        except Exception:
            volumes_data = {
                "total_volumes": total_volumes,
                "framework_header": plot_outline,
                "framework_footer": "",
                "volumes": {},
            }
            epic_volumes_detail = build_epic_volumes_json(volumes_data)
        execution_rounds.append(
            {
                "stage": "epic_framework",
                "volumes": total_volumes,
                "target_chapter_range": list(chapter_range),
                "estimated_chapters": estimated_chapters,
            }
        )

        if resolved_strategy != "character_first" and target_character_count > current_character_count:
            character_program = self._expand_characters_to_target(
                current_characters=current_characters,
                world_setting=world_setting,
                plot_outline=plot_outline,
                current_character_count=current_character_count,
                target_total_characters=target_character_count,
            )
            current_characters = character_program["characters_text"]
            current_character_count = character_program["current_character_count"]
            character_relationships = character_program["character_relationships"] or character_relationships
            character_delta = character_program["character_delta"] or character_delta
            stop_reasons.extend(character_program["stop_reasons"])
            for item in character_program["rounds"]:
                execution_rounds.append({"stage": "character_expand", **item})

        new_character_names = self._collect_new_character_names(characters or "", current_characters)
        plot_outline, alignment_repairs = self._auto_repair_character_alignment(
            plot_outline,
            new_character_names,
        )
        validation_after = self._build_epic_validation(
            framework_text=plot_outline,
            characters_text=current_characters,
            estimated_chapters=estimated_chapters,
        )
        alignment_warnings = self._build_alignment_warnings(new_character_names, validation_after)

        summary = (
            f"已切换为长篇框架优先协同，规划约 {estimated_chapters} 章、{total_volumes} 卷，"
            "后续建议按卷继续展开细纲。"
        )
        if stop_reasons:
            summary += f" 当前已记录阶段性停止原因：{'；'.join(dict.fromkeys(stop_reasons))}"
        repair_note = self._build_alignment_repair_note(alignment_repairs)
        if repair_note:
            summary += f" {repair_note}"
        if alignment_warnings:
            summary += f" {' '.join(alignment_warnings)}"

        return {
            "execution_mode": "epic",
            "execution_mode_reason": mode_info.get("reason", ""),
            "strategy": resolved_strategy,
            "coordination_summary": summary,
            "plan": {
                "strategy": resolved_strategy,
                "mode": "epic",
                "total_volumes": total_volumes,
                "target_chapter_range": list(chapter_range),
            },
            "plot_outline": plot_outline,
            "characters": current_characters,
            "outline_delta": plot_outline,
            "character_delta": character_delta,
            "character_relationships": character_relationships,
            "outline_ops": execution_rounds,
            "execution_rounds": execution_rounds,
            "new_characters": new_character_names,
            "alignment_repairs": alignment_repairs,
            "current_chapter_count": estimated_chapters,
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
            "alignment_warnings": alignment_warnings,
            "epic_framework": plot_outline,
            "epic_volumes_detail": epic_volumes_detail,
            "epic_total_volumes": total_volumes,
            "epic_chapter_range": list(chapter_range),
            "stop_reasons": stop_reasons,
        }

    def _execute_volume_detail_mode(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str,
        mode_info: Dict[str, Any],
        volume_detail_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.outline_merger import (
            build_epic_volumes_json,
            merge_volumes_to_outline,
            update_volume_detail,
        )
        from app.services.volume_connector import VolumeConnector

        normalized_volume_detail_config = self._normalize_volume_detail_config(volume_detail_config)
        if not normalized_volume_detail_config.get("framework_content"):
            raise ValueError("单卷细化协同缺少长篇框架上下文。")
        if not normalized_volume_detail_config.get("target_volume_index"):
            raise ValueError("单卷细化协同缺少目标卷编号。")
        if not normalized_volume_detail_config.get("chapters_count_range"):
            raise ValueError("单卷细化协同缺少本卷章节范围。")
        if not normalized_volume_detail_config.get("start_chapter_num"):
            raise ValueError("单卷细化协同缺少起始章节号。")

        validation_before = evaluate_story_coordination(current_outline or "", characters or "")
        resolved_strategy = self._resolve_strategy(
            strategy=strategy,
            validation=validation_before,
            chapters_needed=int(mode_info.get("chapters_needed") or 0),
            characters_needed=int(mode_info.get("characters_needed") or 0),
        )

        current_characters = characters or ""
        current_character_count = len(extract_character_names(current_characters))
        target_character_count = int(
            mode_info.get("target_character_count")
            or target_total_characters
            or current_character_count
        )
        target_volume_index = int(normalized_volume_detail_config["target_volume_index"])
        chapters_count_range = normalized_volume_detail_config["chapters_count_range"]
        start_chapter_num = int(normalized_volume_detail_config["start_chapter_num"])
        stop_reasons: List[str] = []
        execution_rounds: List[Dict[str, Any]] = []
        character_relationships = ""
        character_delta = ""

        if resolved_strategy == "character_first" and target_character_count > current_character_count:
            character_program = self._expand_characters_to_target(
                current_characters=current_characters,
                world_setting=world_setting,
                plot_outline=current_outline or normalized_volume_detail_config["framework_content"],
                current_character_count=current_character_count,
                target_total_characters=target_character_count,
            )
            current_characters = character_program["characters_text"]
            current_character_count = character_program["current_character_count"]
            character_relationships = character_program["character_relationships"]
            character_delta = character_program["character_delta"]
            stop_reasons.extend(character_program["stop_reasons"])
            for item in character_program["rounds"]:
                execution_rounds.append({"stage": "character_expand", **item})

        prev_volume_summary = None
        previous_volume_detail = normalized_volume_detail_config.get("previous_volume_detail")
        if previous_volume_detail and target_volume_index > 1:
            try:
                connector = VolumeConnector(llm=self._get_expander().llm)
                prev_volume_summary = connector.extract_volume_summary(
                    previous_volume_detail,
                    target_volume_index - 1,
                )
            except Exception:
                prev_volume_summary = None

        volume_result = self._get_expander().expand_volume_detail(
            framework_content=normalized_volume_detail_config["framework_content"],
            target_volume_index=target_volume_index,
            world_setting=world_setting,
            characters=current_characters,
            start_chapter_num=start_chapter_num,
            chapters_count_range=chapters_count_range,
            prev_volume_summary=prev_volume_summary,
            framework_header=normalized_volume_detail_config.get("framework_header") or None,
            framework_footer=normalized_volume_detail_config.get("framework_footer") or None,
        )

        chapters_start = int(volume_result.get("chapters_start") or start_chapter_num)
        chapters_end = int(
            volume_result.get("chapters_end")
            or (chapters_start + int(chapters_count_range[1]) - 1)
        )
        execution_rounds.append(
            {
                "stage": "volume_detail",
                "volume_index": target_volume_index,
                "chapter_range": [chapters_start, chapters_end],
            }
        )

        volumes_data = normalized_volume_detail_config.get("volumes_data") or {}
        volumes_data = json.loads(json.dumps(volumes_data, ensure_ascii=False))
        volumes_data = update_volume_detail(
            volumes_data,
            target_volume_index,
            volume_result["expanded_outline"],
            [chapters_start, chapters_end],
        )
        plot_outline = merge_volumes_to_outline(volumes_data)

        if resolved_strategy != "character_first" and target_character_count > current_character_count:
            character_focus_outline = str(volume_result.get("expanded_outline") or "").strip() or plot_outline
            character_program = self._expand_characters_to_target(
                current_characters=current_characters,
                world_setting=world_setting,
                plot_outline=character_focus_outline,
                current_character_count=current_character_count,
                target_total_characters=target_character_count,
            )
            current_characters = character_program["characters_text"]
            current_character_count = character_program["current_character_count"]
            character_relationships = character_program["character_relationships"] or character_relationships
            character_delta = character_program["character_delta"] or character_delta
            stop_reasons.extend(character_program["stop_reasons"])
            for item in character_program["rounds"]:
                execution_rounds.append({"stage": "character_expand", **item})

        new_character_names = self._collect_new_character_names(characters or "", current_characters)
        repaired_volume_detail, alignment_repairs = self._auto_repair_character_alignment(
            volume_result["expanded_outline"],
            new_character_names,
        )
        if repaired_volume_detail != volume_result["expanded_outline"]:
            volume_result["expanded_outline"] = repaired_volume_detail
            volumes_data = update_volume_detail(
                volumes_data,
                target_volume_index,
                volume_result["expanded_outline"],
                [chapters_start, chapters_end],
            )
            plot_outline = merge_volumes_to_outline(volumes_data)
        validation_after = evaluate_story_coordination(plot_outline, current_characters)
        alignment_warnings = self._build_alignment_warnings(new_character_names, validation_after)
        total_chapter_count = max(
            chapters_end,
            self._estimate_total_chapters_from_volumes_data(volumes_data),
        )

        summary = (
            f"已细化第{target_volume_index}卷，生成第{chapters_start}-{chapters_end}章的卷级细纲，"
            "并同步校准相关人物承接。"
        )
        if normalized_volume_detail_config.get("existing_volume_detail"):
            summary += " 本次覆盖了该卷原有细纲。"
        if stop_reasons:
            summary += f" 当前已记录阶段性停止原因：{'；'.join(dict.fromkeys(stop_reasons))}"
        repair_note = self._build_alignment_repair_note(alignment_repairs)
        if repair_note:
            summary += f" {repair_note}"
        if alignment_warnings:
            summary += f" {' '.join(alignment_warnings)}"

        return {
            "execution_mode": "volume_detail",
            "execution_mode_reason": mode_info.get("reason", ""),
            "strategy": resolved_strategy,
            "coordination_summary": summary,
            "plan": {
                "strategy": resolved_strategy,
                "mode": "volume_detail",
                "target_volume_index": target_volume_index,
                "chapter_range": [chapters_start, chapters_end],
            },
            "plot_outline": plot_outline,
            "characters": current_characters,
            "outline_delta": volume_result["expanded_outline"],
            "character_delta": character_delta,
            "character_relationships": character_relationships,
            "outline_ops": execution_rounds,
            "execution_rounds": execution_rounds,
            "new_characters": new_character_names,
            "alignment_repairs": alignment_repairs,
            "current_chapter_count": total_chapter_count,
            "current_character_count": current_character_count,
            "validation_before": validation_before,
            "validation_after": validation_after,
            "alignment_warnings": alignment_warnings,
            "epic_framework": normalized_volume_detail_config["framework_content"],
            "epic_volumes_detail": build_epic_volumes_json(volumes_data),
            "epic_total_volumes": normalized_volume_detail_config.get("total_volumes"),
            "volume_index": target_volume_index,
            "volume_chapter_range": [chapters_start, chapters_end],
            "stop_reasons": stop_reasons,
        }

    def execute(
        self,
        current_outline: str,
        characters: str,
        world_setting: str,
        target_total_chapters: Optional[int],
        target_total_characters: Optional[int],
        strategy: str = "auto",
        expansion_mode: str = "auto",
        epic_config: Optional[Dict[str, Any]] = None,
        volume_detail_config: Optional[Dict[str, Any]] = None,
        auto_supplement_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        current_outline = sanitize_outline_alignment_placeholders(current_outline or "")
        mode_info = self.determine_execution_mode(
            current_outline=current_outline,
            characters=characters,
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            expansion_mode=expansion_mode,
            epic_config=epic_config,
            volume_detail_config=volume_detail_config,
        )

        chapters_needed = int(mode_info.get("chapters_needed") or 0)
        characters_needed = int(mode_info.get("characters_needed") or 0)
        normalized_volume_detail_config = self._normalize_volume_detail_config(volume_detail_config)
        allow_volume_regeneration = (
            mode_info.get("mode") == "volume_detail"
            and bool(normalized_volume_detail_config.get("existing_volume_detail"))
        )
        if chapters_needed <= 0 and characters_needed <= 0 and not allow_volume_regeneration:
            raise ValueError("目标章节数和目标人物数均不高于当前内容，无需协同拓展。")

        mode = mode_info["mode"]
        if mode == "volume_detail":
            return self._execute_volume_detail_mode(
                current_outline=current_outline,
                characters=characters,
                world_setting=world_setting,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                mode_info=mode_info,
                volume_detail_config=volume_detail_config,
            )
        if mode == "epic":
            return self._execute_epic_mode(
                current_outline=current_outline,
                characters=characters,
                world_setting=world_setting,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                mode_info=mode_info,
                epic_config=epic_config,
            )
        if mode == "iterative":
            return self._execute_iterative_mode(
                current_outline=current_outline,
                characters=characters,
                world_setting=world_setting,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                mode_info=mode_info,
                auto_supplement_plan=auto_supplement_plan,
            )
        return self._execute_delta_mode(
            current_outline=current_outline,
            characters=characters,
            world_setting=world_setting,
            target_total_chapters=target_total_chapters,
            target_total_characters=target_total_characters,
            strategy=strategy,
            mode_info=mode_info,
        )
