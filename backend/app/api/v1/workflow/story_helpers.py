"""Workflow API module."""
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, Tuple, List
from pydantic import BaseModel, ConfigDict
from datetime import datetime
import json
import re
import uuid
from sqlalchemy import inspect, text

from app.db.base import get_db, SessionLocal
from app.services.agent_coordinator import coordinator, StageType, AgentStatus
from app.core.security import get_current_user
from app.models.project import Project, Chapter
from app.models.setting import SettingCollection
from app.websocket.manager import ws_manager
from app.services.character_runtime_context import build_character_prompt_context_from_text
from app.services.workflow_context_builder import WorkflowContextBuilder
from app.utils.datetime_utils import parse_datetime_utc, utc_now
from core.model_resolution import normalize_model_id
from core.model_runtime import ensure_model_hub_initialized, resolve_model_for_task
from app.services.prompts.stages.world_building import CharacterDesignPrompts, get_genre_character_fields
from app.services.auto_system_detector import auto_create_system_collections

logger = logging.getLogger(__name__)

from app.api.v1.workflow.schemas import ExpandStoryRequest

def _get_conventional_collaboration_max_target_chapters(current_chapter_count: int) -> int:
    from app.services.story_expansion_coordinator import StoryExpansionCoordinator

    return StoryExpansionCoordinator.CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS


def _get_project_expansion_profile(project_id: int, db: Session) -> Dict[str, Any]:
    """统一获取扩展阶段所需的项目画像，避免不同入口的参数传递漂移。"""
    project_profile = WorkflowContextBuilder(db).get_project_profile(project_id)
    return {
        "genre": project_profile.genre,
        "planned_chapters_max": project_profile.planned_chapters_max,
    }


def _create_project_outline_expander(project_id: int, db: Session) -> Dict[str, Any]:
    from app.services.agents.outline_expander import create_outline_expander

    project_profile = _get_project_expansion_profile(project_id, db)
    project_genre = project_profile["genre"] or ""
    project_planned_chapters = project_profile["planned_chapters_max"] or 0

    return {
        "expander": create_outline_expander(
            genre=project_genre,
            planned_chapters_max=project_planned_chapters,
            project_id=project_id,
        ),
        "genre": project_genre,
        "planned_chapters_max": project_planned_chapters,
    }


def _build_project_world_setting_context(project_id: int, world_setting: str, db: Session) -> str:
    context_builder = WorkflowContextBuilder(db)
    return context_builder.build_world_setting_context(
        project_id,
        world_setting,
    ).combined_world_setting


def _sync_real_coordinator_project_context(
    project_id: int,
    context_builder: WorkflowContextBuilder,
    project_profile: Any = None,
) -> tuple[Any, Any]:
    project_profile = project_profile or context_builder.get_project_profile(project_id)
    real_coord = coordinator.get_real_coordinator(project_id)
    if real_coord and hasattr(real_coord, "project_context"):
        real_coord.project_context.update(project_profile.to_project_context_payload())
        logger.info(
            "   ✅ 已注入项目基本信息：title=%s, genre=%s",
            project_profile.title or "未命名项目",
            project_profile.genre or "通用",
        )
    return project_profile, real_coord


def _ensure_project_owned(project_id: int, user_id: int, db: Session) -> Project:
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == user_id)
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


def _build_task_start_response(
    *,
    task_id: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "success": True,
        "task_id": task_id,
        "message": message,
    }


CONCEPT_SIMILARITY_PATTERN_GROUPS: Dict[str, list[str]] = {
    "高频主角名": ["林尘", "苏辰", "叶凡", "萧凡", "秦风", "楚天", "陈长生"],
    "高频开局身份": ["宗门杂役", "杂役弟子", "废灵根", "无灵根", "外门弟子", "底层弟子", "濒死觉醒"],
    "高频金手指": ["系统流", "逆修系统", "反向修炼系统", "吞噬灵根", "悖论灵根", "掠夺他人修为", "越被看不起修为越暴涨", "扮猪吃虎"],
    "高频世界命名": ["九寰界", "九寰界域", "九大仙域", "九大仙宗", "七大仙宗", "上三界", "中三界", "下三界"],
    "高频终局真相": ["高维存在", "天外之眼", "监察者", "飞升骗局", "养蛊游戏", "轮回骗局", "历史被循环重置"],
}

RECENT_AVOIDANCE_GROUP_PRIORITY: Dict[str, int] = {
    "已用世界名": 100,
    "高频主角名": 90,
    "高频终局真相": 80,
    "高频金手指": 70,
    "高频世界命名": 60,
    "高频开局身份": 50,
}


def _safe_prompt_context_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    if not isinstance(value, str):
        return str(value or "")

    stripped = value.strip()
    if not stripped:
        return ""

    should_try_json = stripped.startswith(("{", "[")) or (
        stripped.startswith('"') and stripped.endswith('"')
    )
    if not should_try_json:
        return value

    try:
        parsed = json.loads(stripped)
    except Exception:
        return value

    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, ensure_ascii=False)
    return str(parsed or "")


def _extract_recent_project_tags(text_value: str, limit: int = 4) -> list[str]:
    text = _safe_prompt_context_text(text_value)
    if not text:
        return []

    tags: list[str] = []
    for match in re.findall(r"#([^\s#，。；、,.;:：]{2,16})", text):
        normalized = match.strip()
        if normalized and normalized not in tags:
            tags.append(normalized)
        if len(tags) >= limit:
            break
    return tags


def _extract_recent_project_world_names(text_value: str, limit: int = 2) -> list[str]:
    text = _safe_prompt_context_text(text_value)
    if not text:
        return []

    world_names: list[str] = []
    for match in re.findall(r"(?:此界名为|世界名为)[“\"《]?([\u4e00-\u9fffA-Za-z0-9]{2,12})", text):
        normalized = match.strip()
        if normalized and normalized not in world_names:
            world_names.append(normalized)
        if len(world_names) >= limit:
            break
    return world_names


def _extract_recent_project_pattern_hits(text_value: str, limit: int = 3) -> list[str]:
    text = _safe_prompt_context_text(text_value)
    if not text:
        return []

    hits: list[str] = []
    for patterns in CONCEPT_SIMILARITY_PATTERN_GROUPS.values():
        for pattern in patterns:
            if pattern in text and pattern not in hits:
                hits.append(pattern)
            if len(hits) >= limit:
                return hits
    return hits


def _normalize_story_request_text_fields(request: ExpandStoryRequest) -> ExpandStoryRequest:
    from app.services.story_text_utils import normalize_story_text

    return request.model_copy(
        update={
            "current_outline": normalize_story_text(request.current_outline),
            "world_setting": normalize_story_text(request.world_setting),
            "characters": normalize_story_text(request.characters),
        }
    )


def _clip_prompt_context(text_value: str, limit: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", text_value or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _prioritize_recent_avoidance_groups(
    detected_groups: Dict[str, list[str]],
    *,
    max_groups: int = 3,
) -> list[tuple[str, list[str]]]:
    ranked_groups = sorted(
        (
            (group_name, items)
            for group_name, items in detected_groups.items()
            if items
        ),
        key=lambda item: (
            -RECENT_AVOIDANCE_GROUP_PRIORITY.get(item[0], 0),
            -len(item[1]),
            item[0],
        ),
    )
    return ranked_groups[:max_groups]


def _build_recent_project_avoidance_context(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    genre: Optional[str],
    limit: int = 4,
) -> tuple[str, str]:
    recent_query = text(
        """
        SELECT p.id, p.title, p.genre, ps.concept, ps.world_setting, ps.characters
        FROM projects p
        LEFT JOIN project_settings ps ON ps.project_id = p.id
        WHERE p.user_id = :user_id
          AND p.id <> :project_id
          AND (
            COALESCE(ps.concept, '') <> ''
            OR COALESCE(ps.world_setting, '') <> ''
            OR COALESCE(ps.characters, '') <> ''
          )
        ORDER BY COALESCE(p.updated_at, p.created_at) DESC
        LIMIT 8
        """
    )
    rows = db.execute(
        recent_query,
        {"user_id": user_id, "project_id": project_id},
    ).fetchall()

    if not rows:
        return "", ""

    selected_rows = sorted(
        rows,
        key=lambda row: (
            0 if genre and row[2] and str(row[2]) == str(genre) else 1,
        ),
    )[:limit]

    signature_sections: list[str] = []
    combined_text_parts: list[str] = []

    for idx, row in enumerate(selected_rows[:3], start=1):
        recent_title = row[1] or f"项目{row[0]}"
        recent_genre = row[2] or "未标注"
        concept_txt = _safe_prompt_context_text(row[3])
        world_txt = _safe_prompt_context_text(row[4])
        characters_txt = _safe_prompt_context_text(row[5])
        combined_text_parts.extend([concept_txt, world_txt, characters_txt])

        tag_candidates = _extract_recent_project_tags(concept_txt)
        if not tag_candidates:
            tag_candidates = _extract_recent_project_tags(world_txt)

        world_names = _extract_recent_project_world_names(world_txt)
        if not world_names:
            world_names = _extract_recent_project_world_names(concept_txt)

        pattern_hits = _extract_recent_project_pattern_hits(
            "\n".join(part for part in (concept_txt, world_txt, characters_txt) if part)
        )

        section_lines = [
            f"{idx}. 《{recent_title}》",
            f"- 题材：{recent_genre}",
        ]
        if tag_candidates:
            section_lines.append(f"- 核心标签：{'、'.join(tag_candidates[:3])}")
        if world_names:
            section_lines.append(f"- 世界名：{'、'.join(world_names[:1])}")
        if pattern_hits:
            section_lines.append(f"- 已出现元素：{'、'.join(pattern_hits[:2])}")

        signature_sections.append("\n".join(section_lines))

    combined_text = "\n".join(part for part in combined_text_parts if part)
    detected_groups: Dict[str, list[str]] = {}
    for group_name, patterns in CONCEPT_SIMILARITY_PATTERN_GROUPS.items():
        hits: list[str] = []
        for pattern in patterns:
            if pattern in combined_text and pattern not in hits:
                hits.append(pattern)
        if hits:
            detected_groups[group_name] = hits[:4]

    extracted_world_names = []
    for match in re.findall(r"(?:此界名为|世界名为)[“\"《]?([\u4e00-\u9fffA-Za-z0-9]{2,12})", combined_text):
        if match not in extracted_world_names:
            extracted_world_names.append(match)
    if extracted_world_names:
        detected_groups["已用世界名"] = extracted_world_names[:4]

    recent_signatures = "【近期项目关键避重锚点（仅供避重，不可复写）】\n" + "\n".join(signature_sections)
    recent_avoidance = ""
    if detected_groups:
        prioritized_groups = _prioritize_recent_avoidance_groups(detected_groups, max_groups=3)
        avoidance_lines = [
            f"- {group_name}：{'、'.join(items)}"
            for group_name, items in prioritized_groups
            if items
        ]
        recent_avoidance = (
            "【近期项目避重清单】\n"
            "- 以下元素在你最近生成的项目中已经较高频出现，请优先回避直接复用；如确实需要使用，必须做出明显改写。\n"
            + "\n".join(avoidance_lines)
        )

    return recent_signatures, recent_avoidance


def _inject_recent_project_novelty_context(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    real_coord: Any,
    genre: Optional[str],
) -> None:
    if not real_coord or not hasattr(real_coord, "project_context"):
        return

    recent_signatures, recent_avoidance = _build_recent_project_avoidance_context(
        db,
        project_id=project_id,
        user_id=user_id,
        genre=genre,
    )
    real_coord.project_context.update(
        {
            "recent_project_signatures": recent_signatures,
            "recent_project_avoidance": recent_avoidance,
        }
    )


def _build_story_execution_task_kwargs(
    *,
    task_id: str,
    request: ExpandStoryRequest,
    user_id: int,
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "project_id": request.project_id,
        "user_id": user_id,
        "current_outline": request.current_outline,
        "world_setting": request.world_setting,
        "characters": request.characters,
        "current_chapter_count": request.current_chapter_count,
        "current_character_count": request.current_character_count,
        "target_total_chapters": request.target_total_chapters,
        "target_total_characters": request.target_total_characters,
        "strategy": request.strategy,
        "intent": request.intent,
        "enable_auto_supplement": request.enable_auto_supplement,
        "expansion_mode": request.expansion_mode,
        "total_volumes": request.total_volumes,
        "total_chapters_min": request.total_chapters_min,
        "total_chapters_max": request.total_chapters_max,
        "target_volume_index": request.target_volume_index,
        "volume_chapters_min": request.volume_chapters_min,
        "volume_chapters_max": request.volume_chapters_max,
        "volume_character_increment": request.volume_character_increment,
        "preserve_written_mode": request.preserve_written_mode,
        "reset_epic_framework": request.reset_epic_framework,
    }


def _enqueue_story_expansion_task(
    *,
    task_id: str,
    request: ExpandStoryRequest,
    user_id: int,
) -> None:
    asyncio.create_task(
        execute_expand_story_task(
            **_build_story_execution_task_kwargs(
                task_id=task_id,
                request=request,
                user_id=user_id,
            )
        )
    )


def _create_story_expansion_history_record(
    db: Session,
    *,
    project_id: int,
    task_id: str,
) -> None:
    insert_query = text(
        """
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :created_at)
        """
    )

    db.execute(
        insert_query,
        {
            "project_id": project_id,
            "task_type": "expand_story",
            "task_id": task_id,
            "status": "running",
            "created_at": utc_now().isoformat(),
        },
    )
    db.commit()

