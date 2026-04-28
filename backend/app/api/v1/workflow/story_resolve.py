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
from app.services.prompts.workflow_runtime import build_streaming_character_prompts
from app.services.auto_system_detector import auto_create_system_collections

logger = logging.getLogger(__name__)

from app.api.v1.workflow.schemas import (
    ExpandStoryRequest,
    VALID_PRESERVE_WRITTEN_MODES,
    VALID_STORY_EXPANSION_INTENTS,
    VALID_STORY_EXPANSION_MODES,
    VALID_STORY_EXPANSION_STRATEGIES,
)
from app.api.v1.workflow.story_helpers import (
    _build_project_world_setting_context,
    _create_project_outline_expander,
    _get_conventional_collaboration_max_target_chapters,
    _get_project_expansion_profile,
    _normalize_story_request_text_fields,
)

def _update_story_expansion_history_record(
    db: Session,
    *,
    task_id: str,
    status: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    update_query = text(
        """
        UPDATE generation_history
        SET status = :status,
            result = :result,
            error = :error,
            completed_at = :completed_at
        WHERE task_id = :task_id
        """
    )

    try:
        db.execute(
            update_query,
            {
                "task_id": task_id,
                "status": status,
                "result": json.dumps(result, ensure_ascii=False) if result is not None else None,
                "error": error,
                "completed_at": utc_now().isoformat(),
            },
        )
        db.commit()
    except Exception as history_error:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning("更新协同扩展任务记录失败: task_id=%s, error=%s", task_id, history_error)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_story_result_outline_ops(result: Dict[str, Any]) -> list[Dict[str, Any]]:
    normalized_ops: list[Dict[str, Any]] = []
    raw_ops = result.get("outline_ops")
    if not isinstance(raw_ops, list):
        return normalized_ops

    for item in raw_ops:
        if not isinstance(item, dict):
            continue

        action = str(item.get("action") or "").strip()
        if action in {"append", "insert_after"} or "generated_count" in item or "requested_count" in item:
            normalized_ops.append(
                {
                    "action": action or "append",
                    "after_chapter": item.get("after_chapter"),
                    "requested_count": item.get("requested_count"),
                    "generated_count": item.get("generated_count"),
                    "goal": item.get("goal"),
                    "generated_titles": list(item.get("generated_titles") or []),
                }
            )
            continue

        stage = str(item.get("stage") or item.get("mode") or "").strip()

        if stage in {"delta", "iterative"} or item.get("round") is not None:
            before_chapter_count = _safe_int(item.get("before_chapter_count"))
            after_chapter_count = _safe_int(item.get("after_chapter_count"))
            requested_count = _safe_int((item.get("plot") or {}).get("increment_requested"))
            generated_count = max(0, after_chapter_count - before_chapter_count)
            if requested_count <= 0:
                requested_count = _safe_int(item.get("chapters_generated"), generated_count)

            round_label = f"第{_safe_int(item.get('round'), 1)}轮协同"
            strategy = str(item.get("strategy") or "").strip()
            goal = f"{round_label}推进章节补强"
            if strategy:
                goal += f"（策略：{strategy}）"

            normalized_ops.append(
                {
                    "action": "insert_after" if before_chapter_count > 0 else "append",
                    "after_chapter": before_chapter_count if before_chapter_count > 0 else None,
                    "requested_count": requested_count if requested_count > 0 else None,
                    "generated_count": generated_count if generated_count > 0 else None,
                    "goal": goal,
                    "generated_titles": [],
                }
            )
            continue

        if stage == "epic_framework":
            target_chapter_range = item.get("target_chapter_range") or []
            estimated_chapters = _safe_int(item.get("estimated_chapters"))
            total_volumes = _safe_int(item.get("volumes"))
            if estimated_chapters <= 0 and isinstance(target_chapter_range, list) and len(target_chapter_range) >= 2:
                estimated_chapters = _safe_int(target_chapter_range[1])

            goal_parts = []
            if total_volumes > 0:
                goal_parts.append(f"生成 {total_volumes} 卷长篇框架")
            else:
                goal_parts.append("生成长篇框架")
            if isinstance(target_chapter_range, list) and len(target_chapter_range) >= 2:
                goal_parts.append(
                    f"规划 { _safe_int(target_chapter_range[0]) }-{ _safe_int(target_chapter_range[1]) } 章"
                )

            normalized_ops.append(
                {
                    "action": "append",
                    "after_chapter": None,
                    "requested_count": estimated_chapters if estimated_chapters > 0 else None,
                    "generated_count": estimated_chapters if estimated_chapters > 0 else None,
                    "goal": "，".join(part for part in goal_parts if part),
                    "generated_titles": [],
                }
            )
            continue

        if stage == "volume_detail":
            chapter_range = item.get("chapter_range") or []
            start_chapter = _safe_int(chapter_range[0]) if isinstance(chapter_range, list) and len(chapter_range) >= 1 else 0
            end_chapter = _safe_int(chapter_range[1]) if isinstance(chapter_range, list) and len(chapter_range) >= 2 else 0
            generated_count = max(0, end_chapter - start_chapter + 1) if start_chapter > 0 and end_chapter >= start_chapter else 0
            volume_index = _safe_int(item.get("volume_index"))
            goal = (
                f"细化第{volume_index}卷，第{start_chapter}-{end_chapter}章"
                if volume_index > 0 and generated_count > 0
                else "执行单卷细化协同"
            )

            normalized_ops.append(
                {
                    "action": "insert_after" if start_chapter > 1 else "append",
                    "after_chapter": start_chapter - 1 if start_chapter > 1 else None,
                    "requested_count": generated_count if generated_count > 0 else None,
                    "generated_count": generated_count if generated_count > 0 else None,
                    "goal": goal,
                    "generated_titles": [],
                }
            )

    return normalized_ops


def _normalize_story_character_sync_result(sync_result: Any) -> tuple[Optional[Dict[str, Any]], list[str]]:
    if not isinstance(sync_result, dict):
        return None, []

    warnings: list[str] = []
    raw_errors = sync_result.get("errors")
    if isinstance(raw_errors, list):
        warnings.extend(str(item).strip() for item in raw_errors if str(item).strip())
    elif raw_errors:
        warning_text = str(raw_errors).strip()
        if warning_text:
            warnings.append(warning_text)

    parsed_value = sync_result.get("parsed")
    if parsed_value is None and sync_result.get("total") is not None:
        parsed_value = sync_result.get("total")

    normalized: Dict[str, Any] = {
        "parsed": _safe_int(parsed_value, 0),
        "created": _safe_int(sync_result.get("created"), 0),
        "updated": _safe_int(sync_result.get("updated"), 0),
        "skipped": _safe_int(sync_result.get("skipped"), 0),
    }

    relationships = sync_result.get("relationships")
    if isinstance(relationships, dict):
        normalized["relationships"] = {
            "parsed": _safe_int(relationships.get("parsed"), 0),
            "saved": _safe_int(relationships.get("saved"), 0),
            "characters_updated": _safe_int(relationships.get("characters_updated"), 0),
        }

    return normalized, list(dict.fromkeys(item for item in warnings if item))


def _has_structured_character_cards(characters_text: Any) -> bool:
    if not isinstance(characters_text, str):
        return False

    if not characters_text.strip():
        return False

    try:
        from app.services.character_parser import has_parseable_character_cards

        return has_parseable_character_cards(characters_text)
    except Exception:
        return bool(
            re.search(
                r"(?:^|\n)\s*(?:###\s*)?(?:\*\*)?【姓名】(?:\*\*)?[：:]\s*\S+",
                characters_text,
            )
        )


def _normalize_concept_stage_characters_for_storage(
    project_id: int,
    characters_text: Any,
    *,
    concept_text: str = "",
    world_setting_text: str = "",
) -> str:
    if not isinstance(characters_text, str):
        return ""

    normalized = characters_text.strip()
    if not normalized:
        return ""

    workflow_state: Dict[str, Any] = {}
    try:
        workflow_state = coordinator.get_workflow_state(project_id) or {}
    except Exception:
        logger.warning("⚠️ 读取工作流状态失败，人物存储预处理将使用默认上下文")

    requirement = str(workflow_state.get("requirement") or "")

    try:
        real_coordinator = coordinator.get_real_coordinator(project_id)
    except Exception:
        real_coordinator = None
        logger.warning("⚠️ 获取真实协调器失败，人物存储预处理将跳过重排")

    normalize_fn = getattr(real_coordinator, "_normalize_character_cards_if_needed", None)
    if callable(normalize_fn):
        try:
            normalized = normalize_fn(
                normalized,
                requirement=requirement,
                concept=str(concept_text or ""),
                world_setting=str(world_setting_text or ""),
            )
        except Exception as exc:
            logger.warning("⚠️ 概念阶段人物重排失败，准备执行落库拦截: %s", exc)

    if not _has_structured_character_cards(normalized):
        try:
            from app.services.character_parser import convert_legacy_grouped_characters_to_cards

            converted = convert_legacy_grouped_characters_to_cards(normalized)
            if _has_structured_character_cards(converted):
                normalized = converted
        except Exception as exc:
            logger.warning("⚠️ 概念阶段人物规则转换失败，准备执行落库拦截: %s", exc)

    if _has_structured_character_cards(normalized):
        return normalized

    logger.warning(
        "⚠️ 概念阶段人物文本未通过结构化校验，跳过写入 project_settings.characters: project_id=%s",
        project_id,
    )
    return ""


def _build_concept_stage_character_prompts(
    project_genre: str,
    requirement: str,
    concept_text: str,
    world_setting_text: str,
) -> tuple[str, str]:
    return build_streaming_character_prompts(
        project_genre=project_genre,
        requirement=requirement,
        concept_text=concept_text,
        world_setting_text=world_setting_text,
    )


def _select_story_character_sync_source(result: Any) -> tuple[str, str]:
    if not isinstance(result, dict):
        return "", ""

    for source_name in ("character_delta", "characters"):
        characters_text = result.get(source_name)
        if _has_structured_character_cards(characters_text):
            return str(characters_text), source_name

    return "", ""


def _estimate_character_count_from_text(characters_text: str) -> int:
    if not (characters_text or "").strip():
        return 0

    normalized_text = characters_text or ""
    try:
        from app.services.story_expansion_coordinator import extract_character_names
        from app.services.story_text_utils import normalize_story_text

        normalized_text = normalize_story_text(characters_text)
        detected_names = extract_character_names(normalized_text)
        if detected_names:
            return len(detected_names)
    except Exception:
        logger.warning("⚠️ 人物识别降级为正则统计")

    return len(re.findall(r"【姓名】：", normalized_text))


def _estimate_chapter_count_from_text(outline_text: str) -> int:
    if not (outline_text or "").strip():
        return 0

    normalized_text = outline_text or ""
    try:
        from app.services.story_expansion_coordinator import parse_outline_blocks
        from app.services.story_text_utils import normalize_story_text

        normalized_text = normalize_story_text(outline_text)
        _, blocks = parse_outline_blocks(normalized_text)
        if blocks:
            return len(blocks)
    except Exception:
        logger.warning("⚠️ 章节识别降级为正则统计")

    return len(
        re.findall(
            r"(?m)^(?:#{1,6}\s*)?(?:[一二三四五六七八九十百千万零两〇]+[、.．]\s*)?第\s*[0-9一二三四五六七八九十百千万零两〇]+\s*章(?:\s*$|[：:、\-\s])",
            normalized_text,
        )
    )


def _coerce_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _resolve_story_result_count(
    *,
    reported_count: Any,
    parsed_count: int,
    validation_count: Any,
    fallback_count: Any,
) -> int:
    return max(
        _coerce_non_negative_int(reported_count),
        _coerce_non_negative_int(parsed_count),
        _coerce_non_negative_int(validation_count),
        _coerce_non_negative_int(fallback_count),
    )


def _resolve_story_epic_config(request: ExpandStoryRequest) -> Optional[Dict[str, Any]]:
    if request.expansion_mode != "epic_framework":
        return None
    if (
        request.total_volumes is None
        or request.total_chapters_min is None
        or request.total_chapters_max is None
    ):
        return None
    return {
        "total_volumes": int(request.total_volumes),
        "chapter_range": (
            int(request.total_chapters_min),
            int(request.total_chapters_max),
        ),
    }


def _detect_total_volumes_from_framework(framework_text: str) -> int:
    if not framework_text:
        return 10

    yaml_match = re.search(r"总卷数:\s*(\d+)", framework_text)
    if yaml_match:
        try:
            return max(1, int(yaml_match.group(1)))
        except Exception:
            pass

    volume_matches = re.findall(r"第\s*(\d+)\s*卷", framework_text)
    if volume_matches:
        try:
            return max(int(item) for item in volume_matches)
        except Exception:
            pass

    return 10


def _extract_story_volume_chapter_bounds_from_text(content: str) -> Optional[Tuple[int, int]]:
    text_content = str(content or "")
    if not text_content.strip():
        return None

    try:
        from app.services.story_expansion_coordinator import parse_outline_blocks
        from app.services.story_text_utils import normalize_story_text

        normalized_text = normalize_story_text(text_content)
        _, blocks = parse_outline_blocks(normalized_text)
        chapter_numbers = [
            int(block.original_number)
            for block in blocks
            if int(getattr(block, "original_number", 0) or 0) > 0
        ]
        if chapter_numbers:
            return min(chapter_numbers), max(chapter_numbers)
    except Exception:
        pass

    chapter_number_matches = [
        int(match)
        for match in re.findall(r"(?m)^(?:#{1,6}\s*)?(?:\*\*)?\s*第\s*(\d+)\s*章", text_content)
        if str(match).isdigit()
    ]
    if chapter_number_matches:
        return min(chapter_number_matches), max(chapter_number_matches)

    return None


def _estimate_story_volume_chapter_count_from_text(content: str) -> int:
    text_content = str(content or "")
    if not text_content.strip():
        return 0

    coverage_match = re.search(r"覆盖章节[：:]\s*(\d+)\s*[-~—至到]+\s*(\d+)\s*章?", text_content)
    if coverage_match:
        try:
            start = int(coverage_match.group(1))
            end = int(coverage_match.group(2))
            if end >= start > 0:
                return end - start + 1
        except Exception:
            pass

    range_span_match = re.search(r"章节规模[：:]\s*(\d+)\s*[-~—至到]+\s*(\d+)\s*章?", text_content)
    if range_span_match:
        try:
            lower = int(range_span_match.group(1))
            upper = int(range_span_match.group(2))
            return max(lower, upper, 0)
        except Exception:
            pass

    exact_span_match = re.search(r"章节规模[：:]\s*(\d+)\s*章?", text_content)
    if exact_span_match:
        try:
            return max(0, int(exact_span_match.group(1)))
        except Exception:
            pass

    estimated_match = re.search(r"预计\s*(\d+)(?:\s*[-~—至到]+\s*(\d+))?\s*章", text_content)
    if estimated_match:
        try:
            lower = int(estimated_match.group(1))
            upper = int(estimated_match.group(2) or lower)
            return max(lower, upper, 0)
        except Exception:
            pass

    chapter_bounds = _extract_story_volume_chapter_bounds_from_text(text_content)
    if chapter_bounds:
        start, end = chapter_bounds
        if end >= start > 0:
            return end - start + 1

    return 0


def _estimate_story_volume_chapter_count(vol_data: Dict[str, Any]) -> int:
    if not isinstance(vol_data, dict):
        return 0

    chapter_count = int(vol_data.get("chapter_count") or 0)
    if chapter_count > 0:
        return chapter_count

    chapter_range = vol_data.get("chapters_range") or [0, 0]
    if isinstance(chapter_range, (list, tuple)) and len(chapter_range) >= 2:
        try:
            start = int(chapter_range[0] or 0)
            end = int(chapter_range[1] or 0)
            if start > 0 and end >= start:
                return end - start + 1
        except Exception:
            pass

    for field in ("summary", "detail"):
        estimated = _estimate_story_volume_chapter_count_from_text(str(vol_data.get(field) or ""))
        if estimated > 0:
            return estimated

    return 0


def _resolve_story_volume_detail_planned_chapter_count(chapters_min: int, chapters_max: int) -> int:
    lower = max(1, int(chapters_min or 1))
    upper = max(lower, int(chapters_max or lower))
    return max(lower, min(upper, lower + max(0, (upper - lower) // 2)))


def _resolve_story_volume_detail_config(
    request: ExpandStoryRequest,
    db: Session,
) -> Optional[Dict[str, Any]]:
    if request.expansion_mode != "volume_detail":
        return None

    from app.services.outline_merger import (
        normalize_volume_detail_layout,
        parse_epic_volumes_json,
        parse_framework_to_volumes,
    )

    epic_framework_state = WorkflowContextBuilder(db).load_epic_framework_state(request.project_id)

    if not epic_framework_state.epic_framework:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="单卷细化协同需要先生成长篇框架",
        )

    framework_content = epic_framework_state.epic_framework
    stored_volumes_json = epic_framework_state.epic_volumes_detail or "{}"
    volumes_data = parse_epic_volumes_json(stored_volumes_json)
    if not volumes_data.get("volumes"):
        detected_total_volumes = _detect_total_volumes_from_framework(framework_content)
        volumes_data = parse_framework_to_volumes(framework_content, detected_total_volumes)
    volumes_data = normalize_volume_detail_layout(volumes_data, rewrite_detail_content=True)

    volumes_dict = volumes_data.get("volumes", {})
    target_volume_index = int(request.target_volume_index or 0)
    chapters_min = int(request.volume_chapters_min or 0)
    chapters_max = int(request.volume_chapters_max or 0)
    total_volumes = int(volumes_data.get("total_volumes") or len(volumes_dict) or 0)

    if total_volumes > 0 and target_volume_index > total_volumes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"目标卷编号超出范围 (1-{total_volumes})",
        )

    accumulated_chapters = 0
    current_total_chapter_count = 0
    previous_volume_detail = None
    existing_volume_detail = None

    for vol_key, vol_data in volumes_dict.items():
        if vol_data.get("type") == "detail":
            chapter_range = vol_data.get("chapters_range") or [0, 0]
            detected_end = 0
            try:
                detected_end = int(chapter_range[1] or 0)
            except Exception:
                detected_end = 0
            if detected_end <= 0:
                chapter_bounds = _extract_story_volume_chapter_bounds_from_text(str(vol_data.get("detail") or ""))
                if chapter_bounds:
                    detected_end = int(chapter_bounds[1])
            current_total_chapter_count = max(current_total_chapter_count, detected_end)

    for vol_num in range(1, target_volume_index):
        vol_data = volumes_dict.get(str(vol_num)) or {}
        accumulated_chapters += _estimate_story_volume_chapter_count(vol_data)
        if vol_num == target_volume_index - 1 and vol_data.get("type") == "detail":
            previous_volume_detail = vol_data.get("detail")

    target_volume = volumes_dict.get(str(target_volume_index)) or {}
    if target_volume.get("type") == "detail":
        existing_volume_detail = target_volume.get("detail")

    start_chapter_num = accumulated_chapters + 1
    planned_chapter_count = _resolve_story_volume_detail_planned_chapter_count(chapters_min, chapters_max)
    planned_chapter_range = (
        start_chapter_num,
        start_chapter_num + planned_chapter_count - 1,
    )
    expected_chapter_range = (
        start_chapter_num,
        start_chapter_num + chapters_max - 1,
    )
    planned_total_chapter_count = max(current_total_chapter_count, planned_chapter_range[1])
    expected_total_chapter_count = max(current_total_chapter_count, expected_chapter_range[1])

    return {
        "framework_content": framework_content,
        "target_volume_index": target_volume_index,
        "chapters_count_range": (chapters_min, chapters_max),
        "planned_chapter_count": planned_chapter_count,
        "planned_chapter_range": planned_chapter_range,
        "planned_total_chapter_count": planned_total_chapter_count,
        "start_chapter_num": start_chapter_num,
        "framework_header": volumes_data.get("framework_header", ""),
        "framework_footer": volumes_data.get("framework_footer", ""),
        "volumes_data": volumes_data,
        "previous_volume_detail": previous_volume_detail,
        "existing_volume_detail": existing_volume_detail,
        "expected_chapter_range": expected_chapter_range,
        "expected_total_chapter_count": expected_total_chapter_count,
        "current_total_chapter_count": current_total_chapter_count,
        "total_volumes": total_volumes,
    }


def _validate_story_framework_mode_switch(
    request: ExpandStoryRequest,
    db: Session,
) -> None:
    normalized_mode = str(request.expansion_mode or "auto").strip()
    if normalized_mode in {"epic_framework", "volume_detail"}:
        return

    if _resolve_story_target_chapters(request) is None:
        return

    epic_framework_state = WorkflowContextBuilder(db).load_epic_framework_state(request.project_id)
    has_framework = bool((epic_framework_state.epic_framework or "").strip()) or bool(
        epic_framework_state.framework_generated_at
    )
    if not has_framework:
        return

    if request.reset_epic_framework:
        return

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "当前项目已存在长篇框架。若要继续长篇路线，请使用单卷细化协同；"
            "若要切回常规协同，请确认清空旧框架后再执行。"
        ),
    )


def _resolve_story_target_chapters(request: ExpandStoryRequest) -> Optional[int]:
    if request.expansion_mode == "epic_framework":
        candidates = [
            int(value)
            for value in [request.target_total_chapters, request.total_chapters_max]
            if value is not None
        ]
        return max(candidates) if candidates else None
    return request.target_total_chapters


def _resolve_story_target_characters(request: ExpandStoryRequest) -> Optional[int]:
    if request.expansion_mode == "volume_detail" and request.volume_character_increment is not None:
        increment = max(0, int(request.volume_character_increment))
        current_count = max(0, int(request.current_character_count or 0))
        parsed_count = _estimate_character_count_from_text(request.characters or "")
        current_count = max(current_count, parsed_count)
        return current_count + increment
    return request.target_total_characters


def _merge_outline_with_written_context(
    base_outline: str,
    written_context: str,
    *,
    section_title: str,
) -> str:
    base_text = str(base_outline or "").strip()
    written_text = str(written_context or "").strip()

    if not written_text:
        return base_text
    if not base_text:
        return written_text

    return f"{base_text}\n\n【{section_title}】\n{written_text}"


def _neutralize_written_context_chapter_labels(written_context: str) -> str:
    text = str(written_context or "")
    if not text.strip():
        return ""

    return re.sub(
        r"(?m)^(\s*#{0,6}\s*)?第\s*(\d+)\s*章",
        lambda match: f"{match.group(1) or ''}已写章节 {match.group(2)}",
        text,
    )


def _build_story_written_chapter_preview(
    request: ExpandStoryRequest,
    db: Session,
) -> Dict[str, Any]:
    result = {
        "effective_outline": request.current_outline or "",
        "effective_current_chapter_count": int(request.current_chapter_count or 0),
        "written_chapter_count": 0,
        "written_outline_context": "",
        "warnings": [],
        "applied": False,
    }

    if request.expansion_mode == "volume_detail":
        return result
    if getattr(request, "preserve_written_mode", "extract_extend") == "regenerate_all":
        return result

    chapter_query = text(
        """
        SELECT chapter_number, title, content, summary, summary_data
        FROM chapters
        WHERE project_id = :project_id
          AND content IS NOT NULL
          AND content != ''
        ORDER BY chapter_number ASC
        """
    )
    chapter_rows_result = db.execute(chapter_query, {"project_id": request.project_id})
    chapter_rows = chapter_rows_result.fetchall() if hasattr(chapter_rows_result, "fetchall") else []
    written_count = len(chapter_rows)
    result["written_chapter_count"] = written_count

    if written_count <= 0:
        return result

    from app.services.agents.written_chapters_handler import build_written_chapter_summary_preview

    preview_sections = []
    for row in chapter_rows:
        chapter_number = row[0]
        chapter_title = row[1] or f"第{chapter_number}章"
        chapter_content = row[2] or ""
        chapter_summary = row[3] or ""
        chapter_summary_data = row[4]
        preview_text = build_written_chapter_summary_preview(
            chapter_number=chapter_number,
            title=chapter_title,
            content=chapter_content,
            summary=chapter_summary,
            summary_data=chapter_summary_data,
        )
        preview_sections.append(
            f"已写章节 {chapter_number}：{chapter_title}\n- 已写摘要：{preview_text}"
        )

    written_preview_outline = "\n\n".join(preview_sections)
    result["written_outline_context"] = written_preview_outline
    result["effective_outline"] = _merge_outline_with_written_context(
        request.current_outline,
        written_preview_outline,
        section_title="已写章节摘要预览（用于连续性约束）",
    )
    result["effective_current_chapter_count"] = max(
        int(request.current_chapter_count or 0),
        written_count,
    )
    result["applied"] = True

    if request.preserve_written_mode == "extract_extend":
        result["warnings"].append("检测到已写正文，预检阶段先按摘要预览，实际执行前会先提取已写章节细纲。")
    elif request.preserve_written_mode == "preserve_written":
        result["warnings"].append("检测到已写正文，预检阶段会按章节摘要保护已写内容。")

    return result


async def _prepare_story_execution_request(
    request: ExpandStoryRequest,
    db: Session,
) -> Dict[str, Any]:
    request = _normalize_story_request_text_fields(request)
    preview = _build_story_written_chapter_preview(request, db)
    if not preview.get("applied"):
        return {
            "request": request,
            "written_chapter_count": int(preview.get("written_chapter_count") or 0),
            "warnings": list(preview.get("warnings") or []),
            "applied": False,
        }

    combined_world_setting = _build_project_world_setting_context(
        request.project_id,
        request.world_setting,
        db,
    )

    from app.services.agents.written_chapters_handler import process_written_chapters

    expander_bundle = _create_project_outline_expander(request.project_id, db)
    expander = expander_bundle["expander"]
    project_genre = expander_bundle["genre"]

    written_count, extracted_outline_text = await process_written_chapters(
        project_id=request.project_id,
        preserve_written_mode=request.preserve_written_mode,
        project_genre=project_genre,
        combined_world_setting=combined_world_setting,
        db=db,
        extractor_llm=expander.llm,
    )

    written_outline_context = str(
        extracted_outline_text
        or preview.get("written_outline_context")
        or ""
    ).strip()
    if written_outline_context:
        written_outline_context = _neutralize_written_context_chapter_labels(written_outline_context)
        section_title = (
            "已写章节提炼细纲（执行前自动抽取）"
            if extracted_outline_text
            else "已写章节摘要预览（执行前回退）"
        )
        effective_outline = _merge_outline_with_written_context(
            request.current_outline,
            written_outline_context,
            section_title=section_title,
        )
    else:
        effective_outline = preview["effective_outline"] or request.current_outline

    effective_chapter_count = max(
        int(request.current_chapter_count or 0),
        int(preview["effective_current_chapter_count"] or 0),
        int(written_count or 0),
    )

    warnings = list(preview.get("warnings") or [])
    if written_count > 0 and request.preserve_written_mode == "extract_extend":
        warnings.append("执行前已根据已写正文提取章节细纲，并据此重新计算协同缺口。")
    elif written_count > 0 and request.preserve_written_mode == "preserve_written":
        warnings.append("执行前已按已写章节摘要保护正文内容，并据此重新计算协同缺口。")

    return {
        "request": request.model_copy(
            update={
                "current_outline": effective_outline,
                "current_chapter_count": effective_chapter_count,
            }
        ),
        "written_chapter_count": written_count,
        "warnings": warnings,
        "applied": True,
    }


def _validate_expand_story_request(
    request: ExpandStoryRequest,
    *,
    allow_empty_targets_for_analysis: bool = False,
) -> None:
    from app.services.story_expansion_coordinator import StoryExpansionCoordinator

    if request.target_total_chapters is None and request.target_total_characters is None:
        if request.expansion_mode not in {"epic_framework", "volume_detail"} and not allow_empty_targets_for_analysis:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="至少需要提供目标章节数或目标人物数之一",
            )

    if request.target_total_chapters is not None and request.target_total_chapters <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="目标章节数必须大于 0",
        )

    if request.target_total_characters is not None and request.target_total_characters <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="目标人物数必须大于 0",
        )

    if request.volume_character_increment is not None:
        if request.volume_character_increment < 0 or request.volume_character_increment > 30:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="单卷细化的人物新增上限必须在 0-30 之间",
            )

    if request.strategy not in VALID_STORY_EXPANSION_STRATEGIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的协同策略",
        )

    if request.intent not in VALID_STORY_EXPANSION_INTENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的协同意图",
        )

    if request.expansion_mode not in VALID_STORY_EXPANSION_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的协同扩展模式",
        )

    if request.preserve_written_mode not in VALID_PRESERVE_WRITTEN_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的已写章节处理模式",
        )

    if request.expansion_mode == "total":
        max_target_chapters = _get_conventional_collaboration_max_target_chapters(request.current_chapter_count)
        effective_total_chapters = max(
            int(request.current_chapter_count or 0),
            int(request.target_total_chapters or request.current_chapter_count or 0),
        )
        if effective_total_chapters > max_target_chapters:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=StoryExpansionCoordinator.build_conventional_collaboration_limit_message(),
            )

    if request.expansion_mode == "epic_framework":
        if (
            request.total_volumes is None
            or request.total_volumes < StoryExpansionCoordinator.EPIC_MIN_VOLUMES
            or request.total_volumes > StoryExpansionCoordinator.EPIC_MAX_VOLUMES
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "长篇框架协同需要有效的总卷数 "
                    f"({StoryExpansionCoordinator.EPIC_MIN_VOLUMES}-{StoryExpansionCoordinator.EPIC_MAX_VOLUMES})"
                ),
            )
        if (
            request.total_chapters_min is None
            or request.total_chapters_max is None
            or request.total_chapters_min < StoryExpansionCoordinator.EPIC_FRAMEWORK_MIN_TOTAL_CHAPTERS
            or request.total_chapters_max > StoryExpansionCoordinator.EPIC_FRAMEWORK_MAX_TOTAL_CHAPTERS
            or request.total_chapters_min > request.total_chapters_max
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "长篇框架协同需要有效的总章节范围 "
                    f"({StoryExpansionCoordinator.build_epic_framework_total_range_text()})"
                ),
            )

    if request.expansion_mode == "volume_detail":
        if request.target_volume_index is None or request.target_volume_index < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="单卷细化协同需要指定有效的卷编号",
            )
        if (
            request.volume_chapters_min is None
            or request.volume_chapters_max is None
            or request.volume_chapters_min < StoryExpansionCoordinator.VOLUME_DETAIL_MIN_CHAPTERS
            or request.volume_chapters_max > StoryExpansionCoordinator.VOLUME_DETAIL_MAX_CHAPTERS
            or request.volume_chapters_min > request.volume_chapters_max
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "单卷细化协同需要有效的本卷章节范围 "
                    f"({StoryExpansionCoordinator.build_volume_detail_chapter_range_text()})"
                ),
            )


def _build_story_expansion_analysis(
    *,
    request: ExpandStoryRequest,
    db: Session,
) -> Dict[str, Any]:
    from app.services.story_expansion_coordinator import StoryExpansionCoordinator

    combined_world_setting = _build_project_world_setting_context(
        request.project_id,
        request.world_setting,
        db,
    )

    project_profile = _get_project_expansion_profile(request.project_id, db)
    project_genre = project_profile["genre"]
    project_planned_chapters = project_profile["planned_chapters_max"]

    coordinator = StoryExpansionCoordinator(
        project_id=request.project_id,
        genre=project_genre or "",
        planned_chapters_max=project_planned_chapters or 0,
    )
    target_total_chapters = _resolve_story_target_chapters(request)
    target_total_characters = _resolve_story_target_characters(request)
    epic_config = _resolve_story_epic_config(request)
    volume_detail_config = _resolve_story_volume_detail_config(request, db)
    if volume_detail_config is not None:
        planned_total = int(volume_detail_config.get("planned_total_chapter_count") or 0)
        if planned_total > 0:
            target_total_chapters = max(target_total_chapters or 0, planned_total)
    analysis = coordinator.analyze_expansion_request(
        current_outline=request.current_outline,
        characters=request.characters,
        world_setting=combined_world_setting,
        target_total_chapters=target_total_chapters,
        target_total_characters=target_total_characters,
        strategy=request.strategy,
        intent=request.intent,
        enable_auto_supplement=request.enable_auto_supplement,
        expansion_mode=request.expansion_mode,
        volume_character_increment=request.volume_character_increment,
        epic_config=epic_config,
        volume_detail_config=volume_detail_config,
    )
    return {
        "coordinator": coordinator,
        "combined_world_setting": combined_world_setting,
        "analysis": analysis,
        "volume_detail_config": volume_detail_config,
    }
