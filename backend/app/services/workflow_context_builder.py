from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.character_runtime_context import (
    build_character_prompt_context_from_text,
    build_core_character_anchor_context_from_text,
    build_focus_character_relationship_context_from_text,
    extract_core_character_names_from_text,
)
from app.services.setting_templates import (
    build_project_settings_summary,
    extract_relevant_categories_from_text,
)
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


@dataclass
class WorkflowWorldContext:
    project_id: int
    base_world_setting: str
    settings_summary: str
    combined_world_setting: str
    summary_already_embedded: bool = False


@dataclass
class WorkflowRagContext:
    project_id: int
    query_text: str
    relevant_categories: List[str] = field(default_factory=list)
    rag_character_context: str = ""
    rag_world_context: str = ""
    rag_previous_context: str = ""
    character_hits: int = 0
    world_hits: int = 0
    previous_hits: int = 0
    used_vector_search: bool = False
    used_summary_fallback: bool = False


@dataclass
class WorkflowProjectProfile:
    project_id: int
    title: str = ""
    genre: str = ""
    sub_genre: str = ""
    planned_length_type: str = ""
    planned_chapters_min: int = 0
    planned_chapters_max: int = 0
    user_outline_plan: str = ""
    review_config: str = ""

    def to_project_context_payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "project_title": self.title,
            "genre": self.genre,
            "sub_genre": self.sub_genre,
            "planned_length_type": self.planned_length_type,
            "planned_chapters_min": self.planned_chapters_min,
            "planned_chapters_max": self.planned_chapters_max,
            "user_outline_plan": self.user_outline_plan,
            "review_config": self.review_config,
            "project_genre": self.genre,
        }


@dataclass
class WorkflowStageTextContext:
    project_id: int
    concept: str = ""
    world_setting: str = ""
    characters: str = ""
    plot_outline: str = ""
    chapter_draft: str = ""
    review_report: str = ""
    review_meta: dict[str, Any] = field(default_factory=dict)
    final_version: str = ""


@dataclass
class WorkflowConceptStorageState:
    project_id: int
    concept_value: Any = ""
    world_setting_value: Any = ""
    characters_value: Any = field(default_factory=list)


@dataclass
class WorkflowEpicFrameworkState:
    project_id: int
    epic_framework: str = ""
    framework_generated_at: Any = None
    plot_outline: str = ""
    epic_volumes_detail: str = ""


@dataclass
class WorkflowChapterGenerationContext:
    project_id: int
    chapter_number: int
    current_chapter_outline: str = ""
    current_volume_context: str = ""
    epic_framework_context: str = ""
    planning_character_prompt_context: str = ""
    character_prompt_context: str = ""
    core_character_anchor_context: str = ""
    focus_character_relationship_context: str = ""
    content_character_context: str = ""
    outline_source: str = ""
    rag_query_text: str = ""
    focus_character_names: List[str] = field(default_factory=list)
    core_character_names: List[str] = field(default_factory=list)


WORKFLOW_STAGE_FIELD_MAP: dict[str, str] = {
    "concept": "concept",
    "world_builder": "world_setting",
    "character_designer": "characters",
    "structure": "plot_outline",
    "content": "chapter_draft",
    "review": "review_report",
    "iteration": "final_version",
}


WORKFLOW_STAGE_STATUS_FIELD_MAP: dict[str, str] = {
    "concept": "stage_one_status",
    "structure": "stage_two_status",
    "content": "stage_three_status",
    "review": "stage_four_status",
    "iteration": "stage_five_status",
}


WORKFLOW_STAGE_STATUS_DEFAULTS: dict[str, str] = {
    "stage_one_status": "pending",
    "stage_two_status": "pending",
    "stage_three_status": "pending",
    "stage_four_status": "pending",
    "stage_five_status": "pending",
}


ALLOWED_PROJECT_SETTINGS_UPDATE_FIELDS = {
    "concept",
    "world_setting",
    "characters",
    "plot_outline",
    "chapter_draft",
    "review_report",
    "review_meta",
    "final_version",
    "stage_one_status",
    "stage_two_status",
    "stage_three_status",
    "stage_four_status",
    "stage_five_status",
    "epic_framework",
    "epic_volumes_detail",
    "epic_framework_generated_at",
}


def _decode_prompt_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    if not isinstance(value, str):
        return str(value)

    stripped = value.strip()
    if not stripped:
        return ""

    should_try_json = stripped.startswith(("{", "[")) or (
        stripped.startswith('"') and stripped.endswith('"')
    )
    if not should_try_json:
        try:
            from app.services.story_text_utils import repair_story_text_payload

            repaired = repair_story_text_payload(value)
            return repaired if repaired != value else value
        except Exception:
            return value

    try:
        parsed = json.loads(stripped)
    except (TypeError, json.JSONDecodeError):
        try:
            from app.services.story_text_utils import repair_story_text_payload

            repaired = repair_story_text_payload(value)
            return repaired if repaired != value else value
        except Exception:
            return value

    if isinstance(parsed, str):
        return parsed

    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, ensure_ascii=False)

    return str(parsed)


def _decode_character_prompt_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(
            text_block
            for item in value
            if (text_block := _decode_prompt_text(item)).strip()
        )

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except (TypeError, json.JSONDecodeError):
                return _decode_prompt_text(value)
            if isinstance(parsed, list):
                return _decode_character_prompt_text(parsed)

    return _decode_prompt_text(value)


def _decode_storage_text(value: Any, *, pretty_json: bool = False) -> str:
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return json.dumps(
            value,
            ensure_ascii=False,
            indent=2 if pretty_json else None,
        )

    if not isinstance(value, str):
        return str(value)

    stripped = value.strip()
    if not stripped:
        return ""

    should_try_json = stripped.startswith(("{", "[")) or (
        stripped.startswith('"') and stripped.endswith('"')
    )
    if not should_try_json:
        try:
            from app.services.story_text_utils import repair_story_text_payload

            repaired = repair_story_text_payload(value)
            return repaired if repaired != value else value
        except Exception:
            return value

    try:
        parsed = json.loads(stripped)
    except (TypeError, json.JSONDecodeError):
        try:
            from app.services.story_text_utils import repair_story_text_payload

            repaired = repair_story_text_payload(value)
            return repaired if repaired != value else value
        except Exception:
            return value

    if isinstance(parsed, str):
        return parsed

    if isinstance(parsed, (dict, list)):
        return json.dumps(
            parsed,
            ensure_ascii=False,
            indent=2 if pretty_json else None,
        )

    return str(parsed)


def _parse_storage_value(value: Any, default: Any) -> Any:
    if value is None:
        return default

    if isinstance(value, (dict, list)):
        return value

    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped:
        return default

    try:
        return json.loads(stripped)
    except (TypeError, json.JSONDecodeError):
        return value


def _merge_distinct_text_blocks(primary: str, secondary: str) -> tuple[str, bool]:
    primary_text = (primary or "").strip()
    secondary_text = (secondary or "").strip()

    if not secondary_text:
        return primary_text, False
    if not primary_text:
        return secondary_text, False
    if primary_text == secondary_text:
        return primary_text, True
    if secondary_text in primary_text:
        return primary_text, True
    if primary_text in secondary_text:
        return secondary_text, True
    return f"{primary_text}\n\n{secondary_text}", False


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truncate_context_block(value: Any, max_chars: int = 1600) -> str:
    text = _decode_prompt_text(value).strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 9].rstrip()}\n...(已截断)"


def _parse_chapter_number(raw: Any) -> Optional[int]:
    text_value = str(raw or "").strip()
    if not text_value:
        return None
    if text_value.isdigit():
        number = int(text_value)
        return number if number > 0 else None

    digit_map = {
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
    unit_map = {"十": 10, "百": 100, "千": 1000, "万": 10000}

    total = 0
    current = 0
    has_number_token = False
    for char in text_value:
        if char in digit_map:
            current = digit_map[char]
            has_number_token = True
        elif char in unit_map:
            unit = unit_map[char]
            has_number_token = True
            if current == 0:
                current = 1
            total += current * unit
            current = 0

    if not has_number_token:
        return None

    total += current
    return total if total > 0 else None


_CHAPTER_HEADING_PATTERNS = (
    re.compile(
        r"^\s*(?:#+\s*)?第\s*([0-9一二三四五六七八九十百千万零两〇]+)\s*"
        r"[章节回幕集部篇](?:\s*[:：\-—]?\s*.*)?$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*Chapter\s+(\d+)\b.*$", re.IGNORECASE),
)


def _match_chapter_heading(line: str) -> Optional[int]:
    for pattern in _CHAPTER_HEADING_PATTERNS:
        match = pattern.search(str(line or ""))
        if not match:
            continue
        number = _parse_chapter_number(match.group(1))
        if number is not None:
            return number
    return None


def _extract_chapter_blocks(text_value: Any) -> list[dict[str, Any]]:
    content = _decode_prompt_text(text_value).strip()
    if not content:
        return []

    blocks: list[dict[str, Any]] = []
    current_number: Optional[int] = None
    current_lines: list[str] = []

    for raw_line in content.splitlines():
        chapter_number = _match_chapter_heading(raw_line)
        if chapter_number is not None:
            if current_number is not None and current_lines:
                block_text = "\n".join(current_lines).strip()
                if block_text:
                    blocks.append({"number": current_number, "text": block_text})
            current_number = chapter_number
            current_lines = [raw_line]
            continue

        if current_number is not None:
            current_lines.append(raw_line)

    if current_number is not None and current_lines:
        block_text = "\n".join(current_lines).strip()
        if block_text:
            blocks.append({"number": current_number, "text": block_text})

    return blocks


def _extract_exact_chapter_outline(text_value: Any, chapter_number: int) -> str:
    for block in _extract_chapter_blocks(text_value):
        if block.get("number") == chapter_number:
            return str(block.get("text") or "").strip()
    return ""


MERGED_VOLUME_OUTLINE_HEADING_PATTERN = re.compile(
    r"(?m)^\s*#{1,6}\s*【第\s*\d+\s*卷】"
)
MERGED_VOLUME_OUTLINE_DETAIL_SUMMARY_PATTERN = re.compile(
    r"(?m)^\s*<summary>📖 第\d+卷详细章节"
)


def _looks_like_merged_volume_outline(text: str) -> bool:
    content = str(text or "").strip()
    if not content:
        return False

    if "## 📚 分卷概要" in content:
        return True

    heading_matches = list(MERGED_VOLUME_OUTLINE_HEADING_PATTERN.finditer(content))
    if len(heading_matches) >= 2:
        return True

    if heading_matches and (
        "<details" in content or MERGED_VOLUME_OUTLINE_DETAIL_SUMMARY_PATTERN.search(content)
    ):
        return True

    return False


def _normalize_plot_outline_text(text: str, *, characters_text: str = "") -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    if _looks_like_merged_volume_outline(content):
        return content
    if not _extract_chapter_blocks(content):
        return content

    try:
        from app.services.story_expansion_coord_pkg._standalone import normalize_outline_text

        normalized = normalize_outline_text(content, characters_text or "")
        return normalized.strip() or content
    except Exception:
        return content


def _decode_plot_outline_prompt_text(value: Any, *, characters_text: str = "") -> str:
    decoded = _decode_prompt_text(value)
    return _normalize_plot_outline_text(decoded, characters_text=characters_text)


def _decode_plot_outline_storage_text(
    value: Any,
    *,
    characters_text: str = "",
    pretty_json: bool = False,
) -> str:
    decoded = _decode_storage_text(value, pretty_json=pretty_json)
    if pretty_json:
        return decoded
    return _normalize_plot_outline_text(decoded, characters_text=characters_text)


def _rebuild_plot_outline_from_epic_volumes_detail(
    plot_outline: str,
    epic_volumes_detail: str,
) -> tuple[str, str]:
    normalized_plot_outline = str(plot_outline or "")
    normalized_epic_volumes_detail = str(epic_volumes_detail or "")
    if not normalized_epic_volumes_detail.strip():
        return normalized_plot_outline, normalized_epic_volumes_detail

    try:
        from app.services.outline_merger import (
            build_epic_volumes_json,
            merge_volumes_to_outline,
            normalize_volume_detail_layout,
            parse_epic_volumes_json,
        )

        volumes_data = parse_epic_volumes_json(normalized_epic_volumes_detail)
        if not volumes_data.get("volumes"):
            return normalized_plot_outline, normalized_epic_volumes_detail

        normalized_volumes = normalize_volume_detail_layout(
            volumes_data,
            rewrite_detail_content=True,
        )
        merged_plot_outline = merge_volumes_to_outline(normalized_volumes)
        if merged_plot_outline.strip():
            normalized_plot_outline = merged_plot_outline
        normalized_epic_volumes_detail = build_epic_volumes_json(normalized_volumes)
    except Exception as exc:
        logger.warning("根据 epic_volumes_detail 重建 plot_outline 失败: %s", exc)

    return normalized_plot_outline, normalized_epic_volumes_detail


def _find_volume_match(
    volumes_data: dict[str, Any],
    chapter_number: int,
) -> tuple[Optional[int], dict[str, Any]]:
    if not isinstance(volumes_data, dict):
        return None, {}

    volumes = volumes_data.get("volumes")
    if not isinstance(volumes, dict):
        return None, {}

    for raw_key, raw_value in volumes.items():
        if not isinstance(raw_value, dict):
            continue
        chapters_range = raw_value.get("chapters_range") or []
        start = _safe_int(chapters_range[0], 0) if len(chapters_range) >= 1 else 0
        end = _safe_int(chapters_range[1], 0) if len(chapters_range) >= 2 else 0
        if start > 0 and end >= start and start <= chapter_number <= end:
            return _safe_int(raw_key, 0) or None, raw_value

    for raw_key, raw_value in volumes.items():
        if not isinstance(raw_value, dict):
            continue
        detail_text = _decode_prompt_text(raw_value.get("detail")).strip()
        if detail_text and _extract_exact_chapter_outline(detail_text, chapter_number):
            return _safe_int(raw_key, 0) or None, raw_value

    return None, {}


def _build_volume_context_text(
    *,
    volume_number: Optional[int],
    volume_data: dict[str, Any],
    chapter_number: int,
) -> str:
    if not volume_data:
        return ""

    lines: list[str] = []
    title = _decode_prompt_text(volume_data.get("title")).strip()
    volume_label = f"第{volume_number}卷" if volume_number else "当前卷"
    if title:
        lines.append(f"{volume_label}《{title}》")
    else:
        lines.append(volume_label)

    chapters_range = volume_data.get("chapters_range") or []
    start = _safe_int(chapters_range[0], 0) if len(chapters_range) >= 1 else 0
    end = _safe_int(chapters_range[1], 0) if len(chapters_range) >= 2 else 0
    if start > 0 and end >= start:
        lines.append(f"- 覆盖章节：第{start}-{end}章（当前生成第{chapter_number}章）")

    chapter_count = _safe_int(volume_data.get("chapter_count"), 0)
    if chapter_count > 0:
        lines.append(f"- 卷内章节规模：约{chapter_count}章")

    summary_text = _truncate_context_block(volume_data.get("summary"), max_chars=700)
    if summary_text:
        if summary_text.startswith(("-", "1.", "2.", "3.", "4.", "5.")):
            lines.append(summary_text)
        else:
            lines.append(f"- 卷目标/卷摘要：{summary_text}")

    return "\n".join(line for line in lines if str(line).strip())


def _build_epic_framework_context_text(volumes_data: dict[str, Any]) -> str:
    if not isinstance(volumes_data, dict):
        return ""

    parts: list[str] = []
    framework_header = _truncate_context_block(volumes_data.get("framework_header"), max_chars=900)
    framework_footer = _truncate_context_block(volumes_data.get("framework_footer"), max_chars=900)

    if framework_header:
        parts.append(f"【长篇框架前置约束】\n{framework_header}")
    if framework_footer:
        parts.append(f"【长篇框架后置约束】\n{framework_footer}")

    return "\n\n".join(parts)


def _extract_focus_character_names(
    characters_text: str,
    reference_text: str,
    *,
    limit: int = 6,
) -> list[str]:
    content = str(characters_text or "").strip()
    reference = str(reference_text or "").strip()
    if not content or not reference:
        return []

    try:
        from app.services.character_parser import CharacterTextParser
    except Exception:
        return []

    parser = CharacterTextParser()
    parsed_characters = parser.parse_all_characters(content)
    if not parsed_characters:
        return []

    focus_names: list[str] = []
    for character in parsed_characters:
        normalized_name = _decode_prompt_text(getattr(character, "name", "")).strip()
        if not normalized_name or normalized_name not in reference:
            continue
        if normalized_name in focus_names:
            continue
        focus_names.append(normalized_name)
        if len(focus_names) >= limit:
            break

    return focus_names


def _dedupe_names(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        normalized = _decode_prompt_text(raw_value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _join_context_sections(*sections: str) -> str:
    return "\n\n".join(
        section.strip()
        for section in sections
        if section and section.strip()
    )


def _get_character_doc_identity(doc: Any) -> str:
    metadata = getattr(doc, "metadata", {}) or {}
    for key in ("character_id", "character_name", "name", "title"):
        text = _decode_prompt_text(metadata.get(key)).strip()
        if text:
            return text
    return _decode_prompt_text(getattr(doc, "page_content", "")).strip()[:80]


def _flatten_character_prompt_summary(value: Any) -> str:
    text = _decode_prompt_text(value).strip()
    if not text:
        return ""

    if text.startswith("【角色名单摘要】"):
        blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
        text = blocks[-1] if blocks else text

    if text.startswith("【人物运行摘要】"):
        parts = text.split("\n", 1)
        text = parts[1].strip() if len(parts) == 2 else text.replace("【人物运行摘要】", "").strip()

    if text.startswith("- "):
        text = text[2:].strip()

    return text


def _build_character_doc_context_line(doc: Any, *, smart_truncate_for_context: Any) -> str:
    metadata = getattr(doc, "metadata", {}) or {}
    name = _decode_prompt_text(
        metadata.get("character_name") or metadata.get("name") or "未知角色"
    ).strip() or "未知角色"

    runtime_summary = _flatten_character_prompt_summary(metadata.get("runtime_summary"))
    if runtime_summary:
        return f"- {name}: {runtime_summary}"

    current_relationships = _decode_prompt_text(metadata.get("current_relationships")).strip()
    current_mainline = _decode_prompt_text(metadata.get("current_mainline")).strip()
    metadata_parts = []
    if current_relationships:
        metadata_parts.append(f"当前关系：{current_relationships}")
    if current_mainline:
        metadata_parts.append(f"当前主线：{current_mainline}")
    if metadata_parts:
        return f"- {name}: {'；'.join(metadata_parts)}"

    fallback_summary = _flatten_character_prompt_summary(
        build_character_prompt_context_from_text(
            getattr(doc, "page_content", ""),
            detail_limit=220,
            summary_limit=120,
            max_characters=1,
        )
    )
    if not fallback_summary:
        fallback_summary = smart_truncate_for_context(
            _decode_prompt_text(getattr(doc, "page_content", "")),
            max_tokens=200,
            content_type="rag_doc",
            preserve_ratio=0.9,
        )

    return f"- {name}: {fallback_summary}" if fallback_summary else ""


class WorkflowContextBuilder:
    """统一负责工作流项目画像、阶段文本上下文与 RAG 注入。"""

    def __init__(self, db: Session):
        self.db = db

    def get_stage_field_name(self, stage: str) -> Optional[str]:
        return WORKFLOW_STAGE_FIELD_MAP.get(stage)

    def get_stage_status_field_name(self, stage: str) -> Optional[str]:
        return WORKFLOW_STAGE_STATUS_FIELD_MAP.get(stage)

    def get_project_profile(self, project_id: int) -> WorkflowProjectProfile:
        row = self.db.execute(
            text(
                """
                SELECT title, genre, sub_genre, planned_length_type,
                       planned_chapters_min, planned_chapters_max, user_outline_plan,
                       review_config
                FROM projects
                WHERE id = :project_id
                """
            ),
            {"project_id": project_id},
        ).fetchone()

        if not row:
            return WorkflowProjectProfile(project_id=project_id)

        return WorkflowProjectProfile(
            project_id=project_id,
            title=str(row[0] or ""),
            genre=str(row[1] or ""),
            sub_genre=str(row[2] or ""),
            planned_length_type=str(row[3] or ""),
            planned_chapters_min=int(row[4] or 0),
            planned_chapters_max=int(row[5] or 0),
            user_outline_plan=_decode_prompt_text(row[6]),
            review_config=str(row[7] or ""),
        )

    def ensure_project_settings_record(self, project_id: int) -> bool:
        existing = self.db.execute(
            text("SELECT id FROM project_settings WHERE project_id = :project_id"),
            {"project_id": project_id},
        ).fetchone()
        if existing:
            return False

        now = utc_now().isoformat()
        self.db.execute(
            text(
                """
                INSERT INTO project_settings
                (project_id, stage_one_status, stage_two_status, stage_three_status,
                 stage_four_status, stage_five_status, created_at, updated_at)
                VALUES
                (:project_id, 'pending', 'pending', 'pending', 'pending', 'pending',
                 :created_at, :updated_at)
                """
            ),
            {
                "project_id": project_id,
                "created_at": now,
                "updated_at": now,
            },
        )
        self.db.commit()
        return True

    def load_stage_text_context(self, project_id: int) -> WorkflowStageTextContext:
        row = self.db.execute(
            text(
                """
                SELECT concept, world_setting, characters, plot_outline,
                       epic_volumes_detail,
                       chapter_draft, review_report, review_meta, final_version
                FROM project_settings
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).fetchone()

        if not row:
            return WorkflowStageTextContext(project_id=project_id)

        characters_text = _decode_character_prompt_text(row[2])
        plot_outline = _decode_plot_outline_prompt_text(
            row[3],
            characters_text=characters_text,
        )
        plot_outline, _ = _rebuild_plot_outline_from_epic_volumes_detail(
            plot_outline,
            _decode_storage_text(row[4]),
        )

        return WorkflowStageTextContext(
            project_id=project_id,
            concept=_decode_prompt_text(row[0]),
            world_setting=_decode_prompt_text(row[1]),
            characters=characters_text,
            plot_outline=plot_outline,
            chapter_draft=_decode_prompt_text(row[5]),
            review_report=_decode_prompt_text(row[6]),
            review_meta=_parse_storage_value(row[7], {}),
            final_version=_decode_prompt_text(row[8]),
        )

    def load_review_meta(self, project_id: int) -> dict[str, Any]:
        row = self.db.execute(
            text(
                """
                SELECT review_meta
                FROM project_settings
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).fetchone()

        if not row:
            return {}
        parsed = _parse_storage_value(row[0], {})
        return parsed if isinstance(parsed, dict) else {}

    def load_concept_storage_state(self, project_id: int) -> WorkflowConceptStorageState:
        row = self.db.execute(
            text(
                """
                SELECT concept, world_setting, characters
                FROM project_settings
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).fetchone()

        if not row:
            return WorkflowConceptStorageState(project_id=project_id)

        return WorkflowConceptStorageState(
            project_id=project_id,
            concept_value=_parse_storage_value(row[0], ""),
            world_setting_value=_parse_storage_value(row[1], ""),
            characters_value=_parse_storage_value(row[2], []),
        )

    def load_epic_framework_state(self, project_id: int) -> WorkflowEpicFrameworkState:
        row = self.db.execute(
            text(
                """
                SELECT epic_framework, epic_framework_generated_at, plot_outline, epic_volumes_detail
                FROM project_settings
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).fetchone()

        if not row:
            return WorkflowEpicFrameworkState(project_id=project_id)

        epic_framework = _decode_storage_text(row[0])
        framework_generated_at = row[1]
        plot_outline = _decode_plot_outline_storage_text(row[2])
        epic_volumes_detail = _decode_storage_text(row[3])
        plot_outline, epic_volumes_detail = _rebuild_plot_outline_from_epic_volumes_detail(
            plot_outline,
            epic_volumes_detail,
        )

        return WorkflowEpicFrameworkState(
            project_id=project_id,
            epic_framework=epic_framework,
            framework_generated_at=framework_generated_at,
            plot_outline=plot_outline,
            epic_volumes_detail=epic_volumes_detail,
        )

    def read_stage_content(
        self,
        project_id: int,
        stage: str,
        *,
        pretty_json: bool = False,
    ) -> str:
        field_name = self.get_stage_field_name(stage)
        if not field_name:
            raise ValueError(f"Unsupported workflow stage: {stage}")

        if field_name == "plot_outline":
            row = self.db.execute(
                text(
                    """
                    SELECT plot_outline, epic_volumes_detail
                    FROM project_settings
                    WHERE project_id = :project_id
                    """
                ),
                {"project_id": project_id},
            ).fetchone()
        else:
            row = self.db.execute(
                text(
                    f"""
                    SELECT {field_name}
                    FROM project_settings
                    WHERE project_id = :project_id
                    """
                ),
                {"project_id": project_id},
            ).fetchone()

        if not row:
            return ""

        if field_name == "plot_outline":
            plot_outline = _decode_plot_outline_storage_text(row[0], pretty_json=pretty_json)
            plot_outline, _ = _rebuild_plot_outline_from_epic_volumes_detail(
                plot_outline,
                _decode_storage_text(row[1]),
            )
            return plot_outline

        value = row[0]
        if pretty_json:
            return _decode_storage_text(value, pretty_json=True)

        if field_name == "characters":
            return _decode_character_prompt_text(value)
        return _decode_prompt_text(value)

    def load_stage_contents_snapshot(
        self,
        project_id: int,
        *,
        pretty_json: bool = False,
    ) -> dict[str, str]:
        row = self.db.execute(
            text(
                """
                SELECT concept, world_setting, characters, plot_outline,
                       epic_volumes_detail,
                       chapter_draft, review_report, final_version
                FROM project_settings
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).fetchone()

        field_names = [
            "concept",
            "world_setting",
            "characters",
            "plot_outline",
            "chapter_draft",
            "review_report",
            "final_version",
        ]
        if not row:
            return {field_name: "" for field_name in field_names}

        snapshot: dict[str, str] = {}
        characters_text = _decode_character_prompt_text(row[2])
        plot_outline_value = _decode_plot_outline_storage_text(
            row[3],
            characters_text=characters_text,
            pretty_json=pretty_json,
        )
        plot_outline_value, _ = _rebuild_plot_outline_from_epic_volumes_detail(
            plot_outline_value,
            _decode_storage_text(row[4]),
        )
        for index, field_name in enumerate(field_names):
            if pretty_json:
                if field_name == "plot_outline":
                    snapshot[field_name] = plot_outline_value
                else:
                    source_index = index if index < 3 else index + 1
                    snapshot[field_name] = _decode_storage_text(row[source_index], pretty_json=True)
            elif field_name == "characters":
                snapshot[field_name] = characters_text
            elif field_name == "plot_outline":
                snapshot[field_name] = plot_outline_value
            else:
                source_index = index if index < 3 else index + 1
                snapshot[field_name] = _decode_prompt_text(row[source_index])
        return snapshot

    def load_stage_status_snapshot(self, project_id: int) -> dict[str, str]:
        row = self.db.execute(
            text(
                """
                SELECT stage_one_status, stage_two_status, stage_three_status,
                       stage_four_status, stage_five_status
                FROM project_settings
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).fetchone()

        status_names = list(WORKFLOW_STAGE_STATUS_DEFAULTS.keys())
        if not row:
            return dict(WORKFLOW_STAGE_STATUS_DEFAULTS)

        snapshot: dict[str, str] = {}
        for index, field_name in enumerate(status_names):
            snapshot[field_name] = str(row[index] or WORKFLOW_STAGE_STATUS_DEFAULTS[field_name])
        return snapshot

    def update_project_settings_fields(self, project_id: int, **fields: Any) -> None:
        if not fields:
            return

        unknown_fields = sorted(
            field_name for field_name in fields if field_name not in ALLOWED_PROJECT_SETTINGS_UPDATE_FIELDS
        )
        if unknown_fields:
            raise ValueError(f"Unsupported project_settings fields: {', '.join(unknown_fields)}")

        self.ensure_project_settings_record(project_id)

        normalized_fields = dict(fields)
        if "review_meta" in normalized_fields:
            normalized_fields["review_meta"] = json.dumps(
                normalized_fields["review_meta"] or {},
                ensure_ascii=False,
            )

        if "epic_volumes_detail" in normalized_fields and normalized_fields["epic_volumes_detail"] is not None:
            normalized_fields["epic_volumes_detail"] = _decode_storage_text(
                normalized_fields["epic_volumes_detail"]
            )

        if "plot_outline" in normalized_fields:
            characters_value = normalized_fields.get("characters")
            if characters_value is None:
                character_row = self.db.execute(
                    text(
                        """
                        SELECT characters
                        FROM project_settings
                        WHERE project_id = :project_id
                        """
                    ),
                    {"project_id": project_id},
                ).fetchone()
                characters_value = character_row[0] if character_row else ""

            normalized_fields["plot_outline"] = _decode_plot_outline_prompt_text(
                normalized_fields.get("plot_outline"),
                characters_text=_decode_character_prompt_text(characters_value),
            )

        epic_volumes_detail_value = normalized_fields.get("epic_volumes_detail")
        if isinstance(epic_volumes_detail_value, str) and epic_volumes_detail_value.strip():
            base_plot_outline = normalized_fields.get("plot_outline")
            if base_plot_outline is None:
                current_outline_row = self.db.execute(
                    text(
                        """
                        SELECT plot_outline
                        FROM project_settings
                        WHERE project_id = :project_id
                        """
                    ),
                    {"project_id": project_id},
                ).fetchone()
                base_plot_outline = _decode_plot_outline_storage_text(
                    current_outline_row[0] if current_outline_row else ""
                )

            rebuilt_plot_outline, rebuilt_epic_volumes_detail = _rebuild_plot_outline_from_epic_volumes_detail(
                _decode_prompt_text(base_plot_outline),
                epic_volumes_detail_value,
            )
            normalized_fields["plot_outline"] = rebuilt_plot_outline
            normalized_fields["epic_volumes_detail"] = rebuilt_epic_volumes_detail

        params = {
            "project_id": project_id,
            "updated_at": utc_now().isoformat(),
            **normalized_fields,
        }
        assignments = ", ".join(
            [f"{field_name} = :{field_name}" for field_name in normalized_fields] + ["updated_at = :updated_at"]
        )
        self.db.execute(
            text(
                f"""
                UPDATE project_settings
                SET {assignments}
                WHERE project_id = :project_id
                """
            ),
            params,
        )
        self.db.commit()

    def write_stage_content(self, project_id: int, stage: str, content: Any) -> None:
        field_name = self.get_stage_field_name(stage)
        if not field_name:
            raise ValueError(f"Unsupported workflow stage: {stage}")
        self.update_project_settings_fields(project_id, **{field_name: content})

    def build_world_setting_context(
        self,
        project_id: int,
        world_setting: Any = "",
        *,
        relevant_categories: Optional[List[str]] = None,
        max_summary_item_length: int = 300,
    ) -> WorkflowWorldContext:
        base_world_setting = _decode_prompt_text(world_setting)
        settings_summary = build_project_settings_summary(
            project_id,
            self.db,
            relevant_categories=relevant_categories,
            max_content_length=max_summary_item_length,
        )
        combined_world_setting, summary_already_embedded = _merge_distinct_text_blocks(
            base_world_setting,
            settings_summary,
        )
        return WorkflowWorldContext(
            project_id=project_id,
            base_world_setting=base_world_setting,
            settings_summary=settings_summary,
            combined_world_setting=combined_world_setting,
            summary_already_embedded=summary_already_embedded,
        )

    def build_chapter_generation_context(
        self,
        project_id: int,
        chapter_number: int,
        *,
        plot_outline: Any = "",
        characters: Any = "",
    ) -> WorkflowChapterGenerationContext:
        normalized_characters = _decode_character_prompt_text(characters)
        normalized_outline = _decode_plot_outline_prompt_text(
            plot_outline,
            characters_text=normalized_characters,
        )
        epic_framework_state = self.load_epic_framework_state(project_id)

        volumes_data: dict[str, Any] = {}
        try:
            from app.services.outline_merger import parse_epic_volumes_json

            volumes_data = parse_epic_volumes_json(epic_framework_state.epic_volumes_detail or "")
        except Exception as exc:
            logger.warning("章节生成上下文解析 epic_volumes_detail 失败: %s", exc)

        outline_source = ""
        current_chapter_outline = ""

        volume_number, volume_data = _find_volume_match(volumes_data, chapter_number)
        if volume_data:
            current_chapter_outline = _extract_exact_chapter_outline(
                volume_data.get("detail"),
                chapter_number,
            )
            if current_chapter_outline:
                outline_source = (
                    f"epic_volumes_detail.volume_{volume_number}"
                    if volume_number
                    else "epic_volumes_detail"
                )

        if not current_chapter_outline and normalized_outline:
            current_chapter_outline = _extract_exact_chapter_outline(normalized_outline, chapter_number)
            if current_chapter_outline:
                outline_source = "plot_outline"

        if (
            not current_chapter_outline
            and epic_framework_state.plot_outline
            and epic_framework_state.plot_outline != normalized_outline
        ):
            current_chapter_outline = _extract_exact_chapter_outline(
                epic_framework_state.plot_outline,
                chapter_number,
            )
            if current_chapter_outline:
                outline_source = "epic_framework.plot_outline"

        current_volume_context = _build_volume_context_text(
            volume_number=volume_number,
            volume_data=volume_data,
            chapter_number=chapter_number,
        )
        epic_framework_context = _build_epic_framework_context_text(volumes_data)

        focus_reference_text = "\n\n".join(
            part
            for part in (
                current_chapter_outline,
                current_volume_context,
                normalized_outline,
            )
            if part and part.strip()
        )
        focus_character_names = _extract_focus_character_names(
            normalized_characters,
            focus_reference_text,
        )
        core_character_names = extract_core_character_names_from_text(
            normalized_characters,
            preferred_names=focus_character_names,
            max_characters=4,
        )
        prioritized_character_names = _dedupe_names(
            focus_character_names + core_character_names
        )
        character_prompt_context = build_character_prompt_context_from_text(
            normalized_characters,
            detail_limit=1200,
            summary_limit=360,
            max_characters=12,
            preferred_names=prioritized_character_names,
        )
        planning_character_prompt_context = build_character_prompt_context_from_text(
            normalized_characters,
            detail_limit=1800,
            summary_limit=520,
            max_characters=15,
            preferred_names=prioritized_character_names,
        )
        core_character_anchor_context = build_core_character_anchor_context_from_text(
            normalized_characters,
            preferred_names=prioritized_character_names,
            max_characters=4,
            detail_limit=720,
        )
        focus_character_relationship_context = (
            build_focus_character_relationship_context_from_text(
                normalized_characters,
                focus_names=focus_character_names,
                fallback_names=core_character_names,
                max_characters=4,
                detail_limit=520,
            )
        )
        content_character_context = _join_context_sections(
            core_character_anchor_context,
            focus_character_relationship_context,
            character_prompt_context,
        )

        rag_query_parts = []
        if current_chapter_outline:
            rag_query_parts.append(current_chapter_outline)
        if current_volume_context:
            rag_query_parts.append(current_volume_context)
        if focus_character_names:
            rag_query_parts.append(f"相关人物：{'、'.join(focus_character_names)}")
        if not focus_character_names and core_character_names:
            rag_query_parts.append(f"相关人物：{'、'.join(core_character_names)}")
        rag_query_text = "\n\n".join(
            part for part in rag_query_parts if part and part.strip()
        ).strip()

        return WorkflowChapterGenerationContext(
            project_id=project_id,
            chapter_number=chapter_number,
            current_chapter_outline=current_chapter_outline,
            current_volume_context=current_volume_context,
            epic_framework_context=epic_framework_context,
            planning_character_prompt_context=planning_character_prompt_context,
            character_prompt_context=character_prompt_context,
            core_character_anchor_context=core_character_anchor_context,
            focus_character_relationship_context=focus_character_relationship_context,
            content_character_context=content_character_context,
            outline_source=outline_source,
            rag_query_text=rag_query_text,
            focus_character_names=focus_character_names,
            core_character_names=core_character_names,
        )

    def build_typed_rag_context(
        self,
        project_id: int,
        query_text: Any,
        *,
        character_k: Optional[int] = None,
        world_k: Optional[int] = None,
        fallback_max_content_length: int = 200,
        current_chapter_number: Optional[int] = None,
        previous_chapter_k: Optional[int] = None,
        recent_chapter_window: int = 3,
        category_source_text: Optional[str] = None,
        focus_character_names: Optional[List[str]] = None,
        chapter_plan: Optional[str] = None,
    ) -> WorkflowRagContext:
        normalized_query = _decode_prompt_text(query_text)
        # 类别提取用原文（子串匹配，文本越全越准）；embedding 检索用短 query（避免长文本稀释语义）
        relevant_categories = extract_relevant_categories_from_text(
            _decode_prompt_text(category_source_text) if category_source_text else normalized_query
        )

        # 🆕 场景驱动设定召回：按细纲场景（战斗/炼制等）与焦点人物，
        # 确定性召回人物当前可用的功法/武器/丹药/境界，先于 RAG 注入。
        scene_pack = None
        try:
            from app.services.scene_setting_retriever import build_scene_setting_pack

            scene_pack = build_scene_setting_pack(
                self.db,
                project_id,
                focus_character_names,
                current_chapter_number=current_chapter_number,
                source_text=_decode_prompt_text(category_source_text) if category_source_text else normalized_query,
            )
            if scene_pack:
                logger.info(
                    "   ⚔️ 场景设定包命中：场景=%s，设定项=%d",
                    scene_pack.scene_types,
                    len(scene_pack.setting_ids),
                )
        except Exception as exc:
            logger.warning("场景设定包构建失败（忽略，不影响RAG）: %s", exc)

        # 🆕 规划点名设定召回：章节规划中明确提到的设定名，
        # 确定性注入详情（与场景包互补，重复项去重）。
        planned_setting_items: List[Any] = []
        planned_setting_lines: List[str] = []
        try:
            from app.services.scene_setting_retriever import extract_planned_settings

            raw_plan = _decode_prompt_text(chapter_plan) if chapter_plan else ""
            planned_setting_items = extract_planned_settings(self.db, project_id, raw_plan)
            if planned_setting_items:
                logger.info("   📌 规划点名设定命中：%s", "、".join(it.name for it in planned_setting_items))
        except Exception as exc:
            logger.warning("规划点名设定提取失败（忽略，不影响RAG）: %s", exc)

        rag_character_context = ""
        rag_world_context = ""
        rag_previous_context = ""
        character_hits = 0
        world_hits = 0
        previous_hits = 0
        used_vector_search = False
        used_summary_fallback = False

        try:
            from app.core.config import settings
            from app.services.agents.intelligent_truncator import smart_truncate_for_context
            from app.services.setting_categories import SYSTEM_CATEGORIES
            from app.services.vector_sync import get_vector_kb

            kb = get_vector_kb()
            if kb and getattr(settings, "ENABLE_TYPED_RAG", True) and normalized_query.strip():
                char_docs = kb.search(
                    query=normalized_query,
                    k=character_k or getattr(settings, "TYPED_RAG_K_CHAR", 4),
                    filter_type="character",
                    project_id=project_id,
                )
                world_docs = kb.search(
                    query=normalized_query,
                    k=world_k or getattr(settings, "TYPED_RAG_K_WORLD", 5),
                    filter_type="world_setting",
                    project_id=project_id,
                )

                # 🆕 前文章节长程检索：召回本章之前、近期窗口之外的章节片段。
                # 近 recent_chapter_window 章已由结构化连续性资产覆盖，这里只取更早的长期细节。
                previous_lines: List[str] = []
                if current_chapter_number and current_chapter_number > 1:
                    prev_k = previous_chapter_k or getattr(settings, "TYPED_RAG_K_PREV", 2)
                    chapter_docs = kb.search(
                        query=normalized_query,
                        k=max(prev_k * 5, 10),
                        filter_type="chapter",
                        project_id=project_id,
                    )
                    earliest_allowed = current_chapter_number - recent_chapter_window
                    seen_chapters = set()
                    for doc in chapter_docs:
                        meta = doc.metadata or {}
                        raw_num = meta.get("chapter_num") or meta.get("chapter_number")
                        try:
                            doc_chapter = int(raw_num)
                        except (TypeError, ValueError):
                            continue
                        if doc_chapter >= earliest_allowed or doc_chapter in seen_chapters:
                            continue
                        seen_chapters.add(doc_chapter)
                        snippet = smart_truncate_for_context(
                            doc.page_content, max_tokens=150, content_type="rag_doc", preserve_ratio=0.9
                        )
                        title = meta.get("title") or f"第{doc_chapter}章"
                        previous_lines.append(f"- 第{doc_chapter}章《{title}》片段: {snippet}")
                        if len(previous_lines) >= prev_k:
                            break
                    if previous_lines:
                        rag_previous_context = "\n".join(previous_lines)
                        previous_hits = len(previous_lines)

                if relevant_categories and world_docs:
                    category_aliases = set(
                        SYSTEM_CATEGORIES.get(category, category)
                        for category in relevant_categories
                    )
                    prioritized_docs = []
                    fallback_docs = []
                    for doc in world_docs:
                        doc_category = doc.metadata.get("category", "")
                        if doc_category in relevant_categories or doc_category in category_aliases:
                            prioritized_docs.append(doc)
                        else:
                            fallback_docs.append(doc)
                    world_docs = prioritized_docs + fallback_docs

                # 🆕 场景设定包/规划点名去重：已确定性注入的设定项不再通过 RAG 重复注入
                planned_setting_ids = {item.id for item in planned_setting_items}
                if (scene_pack or planned_setting_ids) and world_docs:
                    injected_ids = set(scene_pack.setting_ids if scene_pack else set()) | planned_setting_ids
                    world_docs = [
                        doc
                        for doc in world_docs
                        if doc.metadata.get("setting_id") not in injected_ids
                    ]

                deduped_char_docs = []
                seen_character_keys = set()
                for doc in char_docs:
                    doc_key = _get_character_doc_identity(doc)
                    if doc_key in seen_character_keys:
                        continue
                    seen_character_keys.add(doc_key)
                    deduped_char_docs.append(doc)

                character_hits = len(deduped_char_docs)
                world_hits = len(world_docs)

                if deduped_char_docs:
                    rag_character_context = "\n".join(
                        line
                        for doc in deduped_char_docs
                        if (line := _build_character_doc_context_line(
                            doc,
                            smart_truncate_for_context=smart_truncate_for_context,
                        ))
                    )

                if world_docs:
                    rag_world_context = "\n".join(
                        [
                            (
                                f"- {doc.metadata.get('title', '设定')}: "
                                f"{smart_truncate_for_context(doc.page_content, max_tokens=250, content_type='rag_doc', preserve_ratio=0.9)}"
                            )
                            for doc in world_docs
                        ]
                    )

                # 🆕 标志语义修正：向量检索真正命中（任一类型有结果）才算生效
                used_vector_search = bool(deduped_char_docs or world_docs or previous_lines)
        except Exception as exc:
            logger.warning("统一 Typed-RAG 上下文构建失败: %s", exc)

        if not rag_world_context and relevant_categories:
            rag_world_context = build_project_settings_summary(
                project_id,
                self.db,
                relevant_categories=relevant_categories,
                max_content_length=fallback_max_content_length,
            )
            used_summary_fallback = bool(rag_world_context)

        # 🆕 场景设定包前置注入：人物当前可用设定优先级高于 RAG/摘要
        if scene_pack and scene_pack.text:
            rag_world_context = (
                f"{scene_pack.text}\n{rag_world_context}" if rag_world_context else scene_pack.text
            )
            world_hits += len(scene_pack.setting_ids)

        # 🆕 规划点名设定注入：章节规划明确点到的设定详情（与场景包去重）
        if planned_setting_items:
            try:
                from app.services.agents.intelligent_truncator import smart_truncate_for_context
            except Exception:
                smart_truncate_for_context = None  # type: ignore[assignment]

            scene_pack_ids = set(scene_pack.setting_ids) if scene_pack else set()
            fresh_items = [item for item in planned_setting_items if item.id not in scene_pack_ids]
            if fresh_items:
                def _render_setting_content(raw: str) -> str:
                    if not raw.strip():
                        return ""
                    if smart_truncate_for_context is None:
                        return raw[:400]
                    return smart_truncate_for_context(
                        raw, max_tokens=250, content_type="rag_doc", preserve_ratio=0.9
                    )

                planned_lines = [
                    f"- {item.name}: {_render_setting_content(item.content or '')}"
                    for item in fresh_items
                    if (item.content or "").strip()
                ]
                if planned_lines:
                    planned_block = (
                        "【规划指定设定】（章节规划明确调用的设定，正文写作必须严格遵守）\n"
                        + "\n".join(planned_lines)
                    )
                    rag_world_context = (
                        f"{planned_block}\n{rag_world_context}" if rag_world_context else planned_block
                    )
                    world_hits += len(planned_lines)

        return WorkflowRagContext(
            project_id=project_id,
            query_text=normalized_query,
            relevant_categories=relevant_categories,
            rag_character_context=rag_character_context,
            rag_world_context=rag_world_context,
            rag_previous_context=rag_previous_context,
            character_hits=character_hits,
            world_hits=world_hits,
            previous_hits=previous_hits,
            used_vector_search=used_vector_search,
            used_summary_fallback=used_summary_fallback,
        )
