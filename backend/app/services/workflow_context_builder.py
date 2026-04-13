from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

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
    character_hits: int = 0
    world_hits: int = 0
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
                       planned_chapters_min, planned_chapters_max, user_outline_plan
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
                       chapter_draft, review_report, final_version
                FROM project_settings
                WHERE project_id = :project_id
                """
            ),
            {"project_id": project_id},
        ).fetchone()

        if not row:
            return WorkflowStageTextContext(project_id=project_id)

        return WorkflowStageTextContext(
            project_id=project_id,
            concept=_decode_prompt_text(row[0]),
            world_setting=_decode_prompt_text(row[1]),
            characters=_decode_character_prompt_text(row[2]),
            plot_outline=_decode_prompt_text(row[3]),
            chapter_draft=_decode_prompt_text(row[4]),
            review_report=_decode_prompt_text(row[5]),
            final_version=_decode_prompt_text(row[6]),
        )

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

        return WorkflowEpicFrameworkState(
            project_id=project_id,
            epic_framework=_decode_storage_text(row[0]),
            framework_generated_at=row[1],
            plot_outline=_decode_storage_text(row[2]),
            epic_volumes_detail=_decode_storage_text(row[3]),
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
        for index, field_name in enumerate(field_names):
            if pretty_json:
                snapshot[field_name] = _decode_storage_text(row[index], pretty_json=True)
            elif field_name == "characters":
                snapshot[field_name] = _decode_character_prompt_text(row[index])
            else:
                snapshot[field_name] = _decode_prompt_text(row[index])
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

        params = {
            "project_id": project_id,
            "updated_at": utc_now().isoformat(),
            **fields,
        }
        assignments = ", ".join(
            [f"{field_name} = :{field_name}" for field_name in fields] + ["updated_at = :updated_at"]
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

    def build_typed_rag_context(
        self,
        project_id: int,
        query_text: Any,
        *,
        character_k: Optional[int] = None,
        world_k: Optional[int] = None,
        fallback_max_content_length: int = 200,
    ) -> WorkflowRagContext:
        normalized_query = _decode_prompt_text(query_text)
        relevant_categories = extract_relevant_categories_from_text(normalized_query)

        rag_character_context = ""
        rag_world_context = ""
        character_hits = 0
        world_hits = 0
        used_vector_search = False
        used_summary_fallback = False

        try:
            from app.core.config import settings
            from app.services.agents.intelligent_truncator import smart_truncate_for_context
            from app.services.setting_categories import SYSTEM_CATEGORIES
            from app.services.vector_sync import get_vector_kb

            kb = get_vector_kb()
            if kb and getattr(settings, "ENABLE_TYPED_RAG", True) and normalized_query.strip():
                used_vector_search = True
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

                character_hits = len(char_docs)
                world_hits = len(world_docs)

                if char_docs:
                    rag_character_context = "\n".join(
                        [
                            (
                                f"- {doc.metadata.get('name', '未知角色')}: "
                                f"{smart_truncate_for_context(doc.page_content, max_tokens=200, content_type='rag_doc', preserve_ratio=0.9)}"
                            )
                            for doc in char_docs
                        ]
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

        return WorkflowRagContext(
            project_id=project_id,
            query_text=normalized_query,
            relevant_categories=relevant_categories,
            rag_character_context=rag_character_context,
            rag_world_context=rag_world_context,
            character_hits=character_hits,
            world_hits=world_hits,
            used_vector_search=used_vector_search,
            used_summary_fallback=used_summary_fallback,
        )
