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
from app.services.prompts.workflow_runtime import (
    build_iteration_loop_review_user_prompt,
    build_iteration_revision_user_prompt,
)
from app.services.auto_system_detector import auto_create_system_collections

logger = logging.getLogger(__name__)
def _estimate_tokens_by_chars(text: str) -> int:
    """估算文本 token 数，中文场景按 1.3 倍字符数近似。"""
    return int(len(text or "") * 1.3)


def _get_safe_input_token_budget(
    model_name: str,
    *,
    usage_ratio: float = 0.72,
    prompt_overhead_tokens: int = 500,
) -> int:
    """从统一模型配置读取上下文限制，计算较保守的输入预算。"""
    normalized_model = normalize_model_id(model_name) or model_name
    context_limit = 32000
    output_limit = 8192

    try:
        ensure_model_hub_initialized()
        from core.model_hub import model_hub

        spec = model_hub.registry.get_spec(normalized_model)
        if spec and spec.constraints:
            context_limit = int(spec.constraints.max_context_tokens or context_limit)
            output_limit = int(spec.constraints.max_output_tokens or output_limit)
    except Exception as exc:
        logger.warning("读取模型 %s 配置失败，回退默认预算: %s", normalized_model, exc)

    reserve_output_tokens = max(1200, min(output_limit, max(1200, int(context_limit * 0.25))))
    return max(1500, int(context_limit * usage_ratio) - reserve_output_tokens - prompt_overhead_tokens)


def _select_text_model_by_input_tokens(
    total_tokens: int,
    *,
    primary_model: str = "qwen3.7-plus",
    fallback_model: str = "qwen3.7-plus",
) -> tuple[str, int]:
    """按统一模型配置选择主模型或长上下文回退模型。"""
    safe_budget = _get_safe_input_token_budget(primary_model)
    selected = primary_model if total_tokens < safe_budget else fallback_model
    return selected, safe_budget


def _build_recent_full_chapter_excerpt(content: str, *, max_chars: int = 1200) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    head_chars = max(80, int(max_chars * 0.35))
    tail_chars = max_chars - head_chars - 5
    if tail_chars < 80:
        tail_chars = 80
        head_chars = max(60, max_chars - tail_chars - 5)
    return f"{text[:head_chars].rstrip()}\n...\n{text[-tail_chars:].lstrip()}"


def _select_previous_chapter_context_strategy(
    chapters: List[tuple[Any, ...]] | List[Dict[str, Any]],
    *,
    next_chapter_number: int,
    preferred_model: Optional[str] = None,
) -> Dict[str, Any]:
    """根据预计模型预算与章节长度，动态决定最近全文/详细摘要/连续性资产窗口。"""
    total = len(chapters or [])
    if total <= 0:
        return {
            "selected_model": preferred_model or "unknown",
            "safe_input_budget": 0,
            "history_budget_tokens": 0,
            "recent_full_count": 0,
            "detailed_summary_count": 0,
            "recent_asset_count": 0,
            "recent_full_excerpt_chars": 800,
        }

    selected_model = preferred_model
    if not selected_model:
        try:
            from app.services.agents.layered_summarizer import LayeredSummarizer

            selected_model = LayeredSummarizer.estimate_selected_model("chapter_generation", next_chapter_number)
        except Exception:
            selected_model = "qwen3.7-plus"

    safe_input_budget = _get_safe_input_token_budget(
        selected_model,
        usage_ratio=0.68,
        prompt_overhead_tokens=1200,
    )
    history_budget_tokens = max(2800, min(18000, int(safe_input_budget * 0.12)))
    recent_full_budget = max(1200, int(history_budget_tokens * 0.55))

    def _extract_content(row: tuple[Any, ...] | Dict[str, Any]) -> str:
        if isinstance(row, dict):
            return str(row.get("content", "") or "")
        if len(row) >= 4:
            return str(row[3] or "")
        return ""

    recent_full_count = 0
    used_recent_full_budget = 0
    for row in reversed(list(chapters)[-6:]):
        content = _extract_content(row)
        estimated_tokens = max(220, _estimate_tokens_by_chars(content))
        if recent_full_count < 6 and used_recent_full_budget + estimated_tokens <= recent_full_budget:
            recent_full_count += 1
            used_recent_full_budget += estimated_tokens
        else:
            break

    recent_full_count = min(total, max(1, recent_full_count))
    remaining_chapters = max(0, total - recent_full_count)
    summary_budget = max(1000, history_budget_tokens - min(used_recent_full_budget, recent_full_budget))
    detailed_summary_count = min(
        remaining_chapters,
        max(0, min(24, max(4 if remaining_chapters else 0, int(summary_budget / 260)))),
    )
    recent_asset_count = min(total, max(4, min(8, recent_full_count + 2)))
    recent_full_excerpt_chars = max(
        700,
        min(2600, int((recent_full_budget / max(recent_full_count, 1)) * 1.2)),
    )

    return {
        "selected_model": selected_model,
        "safe_input_budget": safe_input_budget,
        "history_budget_tokens": history_budget_tokens,
        "recent_full_count": recent_full_count,
        "detailed_summary_count": detailed_summary_count,
        "recent_asset_count": recent_asset_count,
        "recent_full_excerpt_chars": recent_full_excerpt_chars,
    }


def _shrink_prompt_text(value: Any, max_length: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)] + "..."


def _join_prompt_items(value: Any, *, max_items: int = 4, max_length: int = 60) -> str:
    if not isinstance(value, list):
        return ""

    items = []
    for item in value[:max_items]:
        if isinstance(item, dict):
            text = ""
            for key in ("content", "description", "summary", "name", "term", "title", "result"):
                candidate = _shrink_prompt_text(item.get(key, ""), max_length=max_length)
                if candidate:
                    text = candidate
                    break
        else:
            text = _shrink_prompt_text(item, max_length=max_length)

        if text:
            items.append(text)

    return "；".join(items)


_PROJECT_TITLE_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\d+\.\s*)?(?:\*\*\s*)?(?:\d+\.\s*)?"
    r"(?:日志标题(?:（[^）]+）)?|项目标题|项目题目|书名)"
    r"\s*(?:\*\*)?\s*(?:[：:]\s*(?P<inline>.*))?\s*$"
)


def _looks_like_field_label(line: str) -> bool:
    return bool(
        re.match(
            r"^\s*(?:[-*]\s*)?(?:\d+\.\s*)?(?:\*\*\s*)?(?:\d+\.\s*)?[^《》\n]{1,30}(?:\s*\*\*)?\s*[：:]\s*$",
            line,
        )
    )


def _normalize_project_title_candidate(raw_value: str) -> Optional[str]:
    candidate = (raw_value or "").strip()
    if not candidate:
        return None

    candidate = re.sub(r"^\s*(?:[-*]\s+|\d+\.\s+)", "", candidate).strip()

    quoted_match = re.search(r"《([^》\n]+)》", candidate)
    if quoted_match:
        candidate = quoted_match.group(1).strip()
    else:
        wrapped_quote_match = re.search(r"[“\"]([^”\"\n]+)[”\"]", candidate)
        if wrapped_quote_match:
            candidate = wrapped_quote_match.group(1).strip()
        else:
            candidate = re.sub(r"^\*\*(.*?)\*\*$", r"\1", candidate).strip()
            candidate = candidate.strip("《》“”\"'` ")

    candidate = re.sub(r"\s+", " ", candidate).strip().rstrip("。；;")
    if len(candidate) < 2:
        return None
    if _PROJECT_TITLE_LABEL_RE.match(candidate):
        return None

    return candidate


def _extract_project_title_from_concept(concept_text: str) -> Optional[str]:
    if not isinstance(concept_text, str):
        return None

    lines = concept_text.splitlines()
    for index, line in enumerate(lines):
        match = _PROJECT_TITLE_LABEL_RE.match(line)
        if not match:
            continue

        inline_title = _normalize_project_title_candidate(match.group("inline") or "")
        if inline_title:
            return inline_title

        for next_line in lines[index + 1 : index + 4]:
            stripped_line = next_line.strip()
            if not stripped_line:
                continue
            if _PROJECT_TITLE_LABEL_RE.match(stripped_line) or _looks_like_field_label(stripped_line):
                break

            multiline_title = _normalize_project_title_candidate(stripped_line)
            if multiline_title:
                return multiline_title
            break

    return None


def _sync_project_title_from_concept(
    db: Session,
    project_id: int,
    concept_text: Any,
    *,
    mode_label: str = "",
) -> Optional[str]:
    if not isinstance(concept_text, str):
        return None

    project_title = _extract_project_title_from_concept(concept_text)
    if not project_title:
        return None

    update_title_query = text("""
        UPDATE projects SET title = :title, updated_at = :updated_at
        WHERE id = :project_id
    """)
    db.execute(update_title_query, {
        "title": project_title,
        "updated_at": utc_now().isoformat(),
        "project_id": project_id,
    })
    db.commit()

    mode_suffix = f"（{mode_label}）" if mode_label else ""
    logger.info(f"   📝 已从故事概念更新项目title{mode_suffix}: {project_title}")
    return project_title


def _format_conflict_arc(conflict_arc: Any) -> str:
    if not isinstance(conflict_arc, dict):
        return ""

    parts = []
    mapping = (
        ("trigger", "触发"),
        ("escalation", "升级"),
        ("resolution", "结果"),
        ("result", "结果"),
        ("description", "描述"),
    )
    for key, label in mapping:
        text = _shrink_prompt_text(conflict_arc.get(key, ""), max_length=50)
        if text:
            parts.append(f"{label}:{text}")

    deduplicated = []
    seen = set()
    for item in parts:
        if item not in seen:
            deduplicated.append(item)
            seen.add(item)

    return "；".join(deduplicated[:3])


def _format_chapter_gains(gains: Any) -> str:
    if not isinstance(gains, dict):
        return ""

    parts = []
    for key, label in (
        ("character_gains", "人物收获"),
        ("plot_progress", "剧情推进"),
    ):
        text = _shrink_prompt_text(gains.get(key, ""), max_length=50)
        if text:
            parts.append(f"{label}:{text}")

    return "；".join(parts)


def _format_ending_hook(ending_hook: Any, hooks: Any = None) -> str:
    if isinstance(ending_hook, dict):
        for key in ("content", "hook", "summary", "description", "type"):
            text = _shrink_prompt_text(ending_hook.get(key, ""), max_length=60)
            if text:
                return text

    text = _shrink_prompt_text(ending_hook, max_length=60)
    if text:
        return text

    return _join_prompt_items(hooks, max_items=2, max_length=60)


def _has_structured_chapter_assets(summary_data: Any) -> bool:
    if not isinstance(summary_data, dict):
        return False

    interesting_keys = (
        "scene_goal",
        "key_events",
        "appearing_characters",
        "key_characters",
        "conflict_arc",
        "highlight",
        "gains",
        "ending_hook",
        "hooks",
        "foreshadowing",
    )
    return any(summary_data.get(key) for key in interesting_keys)


def _format_recent_chapter_asset(chapter_payload: Dict[str, Any]) -> str:
    summary_data = chapter_payload.get("summary_data") or {}
    if not isinstance(summary_data, dict):
        return ""

    chapter_number = chapter_payload.get("chapter_number", "?")
    title = (chapter_payload.get("title") or "").strip()
    chapter_label = f"第{chapter_number}章《{title}》" if title else f"第{chapter_number}章"
    lines = [chapter_label]

    core_summary = _shrink_prompt_text(
        summary_data.get("core_summary") or chapter_payload.get("summary", ""),
        max_length=120,
    )
    if core_summary:
        lines.append(f"- 核心摘要: {core_summary}")

    scene_goal = _shrink_prompt_text(summary_data.get("scene_goal", ""), max_length=60)
    if scene_goal:
        lines.append(f"- 场景目标: {scene_goal}")

    key_events = _join_prompt_items(summary_data.get("key_events"), max_items=4, max_length=40)
    if key_events:
        lines.append(f"- 关键事件: {key_events}")

    characters = _join_prompt_items(
        summary_data.get("appearing_characters") or summary_data.get("key_characters"),
        max_items=5,
        max_length=20,
    )
    if characters:
        lines.append(f"- 相关人物: {characters}")

    conflict_arc = _format_conflict_arc(summary_data.get("conflict_arc"))
    if conflict_arc:
        lines.append(f"- 冲突推进: {conflict_arc}")

    highlight = summary_data.get("highlight")
    if isinstance(highlight, dict):
        highlight_type = _shrink_prompt_text(highlight.get("type", ""), max_length=20)
        highlight_desc = _shrink_prompt_text(highlight.get("description", ""), max_length=50)
        highlight_text = "：".join(part for part in (highlight_type, highlight_desc) if part)
        if highlight_text:
            lines.append(f"- 高光设计: {highlight_text}")

    gains = _format_chapter_gains(summary_data.get("gains"))
    if gains:
        lines.append(f"- 本章收获: {gains}")

    ending_hook = _format_ending_hook(
        summary_data.get("ending_hook"),
        summary_data.get("hooks"),
    )
    if ending_hook:
        lines.append(f"- 结尾钩子: {ending_hook}")

    foreshadowing = _join_prompt_items(summary_data.get("foreshadowing"), max_items=3, max_length=50)
    if foreshadowing:
        lines.append(f"- 伏笔事项: {foreshadowing}")

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_recent_chapter_assets_summary(
    previous_chapters_payload: list[Dict[str, Any]],
    *,
    limit: int = 4,
) -> str:
    structured_payloads = [
        payload
        for payload in previous_chapters_payload
        if _has_structured_chapter_assets(payload.get("summary_data"))
    ]

    if not structured_payloads:
        return ""

    formatted_parts = []
    for payload in structured_payloads[-limit:]:
        formatted = _format_recent_chapter_asset(payload)
        if formatted:
            formatted_parts.append(formatted)

    return "\n\n".join(formatted_parts)


def _build_iteration_revision_prompt(
    *,
    chapter_number: int,
    chapter_content: str,
    review_text: str,
    iteration_plan: str = "",
    recent_chapter_assets_summary: str = "",
    include_history_hint: bool = False,
    revision_mode_hint: str = "",
    repair_hints: str = "",
) -> str:
    return build_iteration_revision_user_prompt(
        chapter_number=chapter_number,
        chapter_content=chapter_content,
        review_text=review_text,
        iteration_plan=iteration_plan,
        recent_chapter_assets_summary=recent_chapter_assets_summary,
        include_history_hint=include_history_hint,
        revision_mode_hint=revision_mode_hint,
        repair_hints=repair_hints,
    )


def _build_iteration_review_prompt(
    *,
    chapter_number: int,
    chapter_content: str,
    chapter_plan: str,
    review_text: str = "",
    iteration_plan: str = "",
    recent_chapter_assets_summary: str = "",
) -> str:
    return build_iteration_loop_review_user_prompt(
        chapter_number=chapter_number,
        chapter_content=chapter_content,
        chapter_plan=chapter_plan,
        review_text=review_text,
        iteration_plan=iteration_plan,
        recent_chapter_assets_summary=recent_chapter_assets_summary,
    )


# 🆕 导入流式输出服务
try:
    from app.services.streaming_service import get_streaming_service
    STREAMING_AVAILABLE = True
except ImportError:
    STREAMING_AVAILABLE = False
    get_streaming_service = None  # type: ignore

