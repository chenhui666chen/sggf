"""Workflow API module."""
import logging
import asyncio
import os
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, Tuple, List, Callable
from pydantic import BaseModel, ConfigDict
from datetime import datetime
import json
import re
import uuid
from sqlalchemy import inspect, text

from app.db.base import get_db, SessionLocal
from app.services.agent_coordinator import coordinator, StageType, AgentStatus
from app.services.agent_registry import get_stage_agents_map
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
    build_iteration_coordination_user_prompt,
    get_iteration_coordination_system_prompt,
    get_iteration_loop_review_system_prompt,
    get_iteration_revision_system_prompt,
)
from app.services.prompts.narrative_quality import (
    build_repair_hints,
    calibrate_review_score_to_rubric,
    extract_failure_codes,
    extract_unresolved_issues,
    format_foreshadow_ledger,
    format_quality_memory,
    register_foreshadowing,
    resolve_revision_mode,
    review_has_unsourced_new_fact,
    update_quality_memory,
)
from app.services.prompts.stages.content_creation import (
    extract_chapter_position,
    extract_key_events,
    split_scene_segments,
)
from app.services.agents.chapter_prompt_builder import extract_segment_tail
from app.core.config import settings
from app.services.auto_system_detector import auto_create_system_collections
from app.services.agents import review_feature_gate
from app.services.agents.multi_model_review_service import MultiModelReviewService
from app.services.generation_lock import (
    LockHandle,
    LockServiceUnavailableError,
    get_generation_lock_service,
)
from app.services.free_quota import (
    QuotaServiceUnavailableError,
    get_free_quota_service,
)

logger = logging.getLogger(__name__)


async def _keep_generation_lock_alive(
    lock_handle: Optional[LockHandle],
    *,
    interval_seconds: int = 300,
) -> None:
    """Renew the project lock until cancelled by the owning generation task."""
    if lock_handle is None:
        return
    lock_service = get_generation_lock_service()
    while True:
        await asyncio.sleep(interval_seconds)
        if not await lock_service.renew(lock_handle):
            raise RuntimeError(f"项目 {lock_handle.project_id} 生成锁续租失败")

_active_generate_next_chapter_task_ids: set[str] = set()
_active_generate_next_chapter_tasks: dict[int, asyncio.Task] = {}


def mark_generate_next_chapter_task_active(
    task_id: str,
    project_id: int | None = None,
    *,
    aio_task: asyncio.Task | None = None,
) -> None:
    _active_generate_next_chapter_task_ids.add(str(task_id))
    if project_id is not None and aio_task is not None:
        _active_generate_next_chapter_tasks[int(project_id)] = aio_task


def mark_generate_next_chapter_task_inactive(task_id: str, project_id: int | None = None) -> None:
    _active_generate_next_chapter_task_ids.discard(str(task_id))
    if project_id is not None:
        current = _active_generate_next_chapter_tasks.get(int(project_id))
        if current is None or current.done():
            _active_generate_next_chapter_tasks.pop(int(project_id), None)


def is_generate_next_chapter_task_active(task_id: str) -> bool:
    return str(task_id) in _active_generate_next_chapter_task_ids


def has_active_generate_next_chapter_for_project(project_id: int) -> bool:
    aio_task = _active_generate_next_chapter_tasks.get(int(project_id))
    if aio_task is None:
        return False
    if aio_task.done():
        _active_generate_next_chapter_tasks.pop(int(project_id), None)
        return False
    return True


def _select_iteration_fallback_version(
    *,
    initial_version: str,
    latest_revised_version: str,
    best_version: str,
) -> str:
    return best_version or initial_version or latest_revised_version


def _iteration_review_has_unresolved_required_items(review_text: str) -> bool:
    """检测复评中是否仍有必改项未执行。

    核验表优先，部分执行与未执行同样阻断（与首章验收原则对齐）；
    若复评未输出表格，剩余关键问题里残留的【必改】/MUST 也视为未执行；
    fallback 扫描跳过表格行，避免把核验表中已处理的 MUST ID 误判为残留；
    HIGH 级无出处新增事实（编造圆场）同样不得判为已闭环。
    """
    text = str(review_text or "")
    if review_has_unsourced_new_fact(text):
        return True
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        source = cells[0].upper()
        status_text = cells[1]
        is_required_item = "MUST" in source or "必改" in cells[0]
        if is_required_item and (
            "未执行" in status_text or "部分执行" in status_text
        ):
            return True
    remaining = ""
    marker = "## 剩余关键问题"
    if marker in text:
        remaining = text.split(marker, 1)[1]
        for stop in ("\n## ", "\n结论", "\n结论："):
            if stop in remaining:
                remaining = remaining.split(stop, 1)[0]
                break
    else:
        remaining = text
    for raw_line in remaining.splitlines():
        line = raw_line.strip()
        if line.startswith("|"):
            continue
        if "【必改】" in line or "MUST" in line.upper():
            return True
    return False


def _describe_iteration_round_rejection(
    *,
    round_idx: int,
    score: float,
    previous_best_score: float,
    has_unresolved_required_items: bool,
) -> str:
    """生成本轮改稿未被采纳为下一轮基底的原因日志。

    区分两种情况：评分提升但被必改项阻断，与评分确实未提升；
    避免阻断时输出“8.5 < 8.0”式与数字矛盾的错误比较文案。
    """
    if has_unresolved_required_items and score >= previous_best_score:
        return (
            f"↩️ 第{round_idx}轮评分提升（{score:.1f}/10 ≥ {previous_best_score:.1f}/10），"
            "但仍有必改项未执行，本轮改稿不采用，下一轮继续基于当前最佳版本修订"
        )
    return (
        f"↩️ 第{round_idx}轮评分未提升（{score:.1f}/10 < {previous_best_score:.1f}/10），"
        "下一轮继续基于当前最佳版本修订"
    )


# 章节正文合法收尾字符（句末标点/引号/括号收口）；结尾不在此集合视为疑似截断
_CHAPTER_ENDING_CHARS = set('。！？…！?~"\'\'』」》）).')


def _is_likely_truncated_chapter(text: str) -> bool:
    """启发式检测章节正文是否被截断：以非句末标点收尾（如'离她二十'）视为疑似截断。

    仅用于生成后的完整性守卫：命中后静默重试一次，不作为硬失败。
    """
    if not text or len(text) < 200:
        return False  # 空稿/极短稿走既有失败路径
    stripped = text.rstrip()
    if not stripped:
        return False
    return stripped[-1] not in _CHAPTER_ENDING_CHARS


# 结构级失败码：命中即视为章内结构断裂（同场复述/整弧重启/原地踏步），改稿无法修复，需重生成
STRUCTURAL_FAILURE_CODES = {"STRUCT_BROKEN", "STALL_NO_PROGRESS"}


def _extract_structural_failure_codes(review_text: str) -> set:
    """提取评审文本中的结构失败码，用于结构门控（重生成判定）与验收硬停止标记。"""
    return {
        str(fc.get("code") or "")
        for fc in extract_failure_codes(str(review_text or ""))
        if str(fc.get("code") or "") in STRUCTURAL_FAILURE_CODES
    }


def _split_stream_text(text: str, *, chunk_size: int = 1200) -> list:
    if not text:
        return []
    safe_chunk_size = max(1, int(chunk_size or 1))
    return [text[index:index + safe_chunk_size] for index in range(0, len(text), safe_chunk_size)]


def _resolve_next_chapter_multi_model_review_preset(
    project_context: Dict[str, Any],
    chapter_number: int,
    chapter_plan: str = "",
) -> Optional[str]:
    cfg = review_feature_gate.get_multi_model_review_config(project_context)
    if not cfg:
        return None

    is_manual = bool(
        project_context.get("force_multi_model_review")
        or project_context.get("manual_multi_model_review")
    )
    if "auto_scenarios" not in cfg and "auto_strategy" not in cfg and not is_manual:
        return str(cfg.get("preset") or "balanced_3")

    should_trigger, preset = review_feature_gate.should_trigger_multi_model_review(
        project_context,
        chapter_number=chapter_number,
        is_manual=is_manual,
        chapter_plan=chapter_plan,
    )
    return preset if should_trigger else None


def _build_next_chapter_review_meta(multi_model_result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "multi_model": bool(multi_model_result.get("multi_model")),
        "preset": multi_model_result.get("preset"),
        "chief_model": multi_model_result.get("chief_model"),
        "chief_model_reused_as_reviewer": bool(multi_model_result.get("chief_model_reused_as_reviewer")),
        "chief_cost": float(multi_model_result.get("chief_cost") or 0.0),
        "chief_usage_metadata": multi_model_result.get("chief_usage_metadata") or {},
        "total_cost": float(multi_model_result.get("total_cost") or 0.0),
        "structured_summary": multi_model_result.get("structured_summary") or {},
        "reviewer_models": multi_model_result.get("reviewer_models") or [],
        "reviewer_profiles": multi_model_result.get("reviewer_profiles") or [],
        "per_model_reports": multi_model_result.get("per_model_reports") or [],
        "fallback_required": bool(multi_model_result.get("fallback_required")),
        "fallback_reason": multi_model_result.get("fallback_reason"),
    }


async def _run_single_next_chapter_streaming_review(
    *,
    chapter_draft: str,
    chapter_plan: str,
    plot_outline: str,
    genre: str,
    next_chapter_number: int,
    recent_chapter_assets_summary: str,
    streaming_service: Any,
    on_review_chunk: Callable[[str, int], Any],
    real_coordinator: Any,
    review_model: Optional[str] = None,
    max_llm_attempts: int = 3,
    require_exact_model: bool = False,
) -> str:
    from app.services.prompts.review_prompts import GenreAdaptiveReviewPrompts

    review_system_prompt = GenreAdaptiveReviewPrompts.get_review_system_prompt(
        genre=genre,
    )
    review_user_prompt = GenreAdaptiveReviewPrompts.get_review_user_prompt(
        chapter_number=next_chapter_number,
        chapter_plan=chapter_plan,
        chapter_content=chapter_draft,
        plot_outline=plot_outline,
        genre=genre,
        recent_chapter_assets_summary=recent_chapter_assets_summary,
    )

    try:
        review_report = await streaming_service.generate_chapter_streaming(
            prompt=review_user_prompt,
            system_prompt=review_system_prompt,
            on_chunk=on_review_chunk,
            # 评审是判别任务：低温保证同一文本多次评审结论稳定（高温曾导致
            # 初评/终评对同一特征给出相反判断、失败码漂移）
            temperature=0.2,
            model=review_model,
            task_type="review",
            max_retries=max_llm_attempts,
            require_exact_model=require_exact_model,
            disable_thinking=True,
        )
        logger.info(
            f"   ✓ 评审完成（真流式 + {'锁定模型 ' + review_model if review_model else 'review任务路由'}），"
            f"报告长度: {len(review_report)}"
        )
        # 🆕 评分锚点程序化校准：评审模型存在"零问题仍压 7 分"的先验惯性
        # （六维全"无"+零失败码却给 7 分），提示词纪律无法根除，此处兜底对齐锚点
        calibrated = calibrate_review_score_to_rubric(review_report)
        if calibrated != review_report:
            logger.info("   🎚️ 评审分已按锚点校准（零必改低分/带必改高分修正）")
        return calibrated
    except Exception as e:
        # 🆕 锁定模型档位下禁止回退到协调器（回退路径模型不受控），直接终止
        if require_exact_model:
            logger.error(f"   ❌ 锁定模型评审失败且禁止回退: {e}")
            raise
        logger.error(f"   ⚠️ 真流式调用失败，回退到同步调用: {e}")
        if real_coordinator is not None and hasattr(real_coordinator, "review_chapter"):
            return calibrate_review_score_to_rubric(await asyncio.to_thread(
                real_coordinator.review_chapter,
                chapter_draft=chapter_draft,
                chapter_plan=chapter_plan,
                plot_outline=plot_outline,
            ))
        return "质量评审：章节符合要求，可以继续优化。"


async def _run_next_chapter_quality_review(
    *,
    project_context: Dict[str, Any],
    chapter_draft: str,
    chapter_plan: str,
    plot_outline: str,
    genre: str,
    next_chapter_number: int,
    recent_chapter_assets_summary: str,
    streaming_service: Any,
    on_review_chunk: Callable[[str, int], Any],
    real_coordinator: Any,
    enable_multi_model_review: bool = True,
    review_model: Optional[str] = None,
    max_llm_attempts: int = 3,
    require_exact_model: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    # 🆕 免费档短路：不进多模型评审 gate，直接单模型评审
    multi_model_preset = (
        _resolve_next_chapter_multi_model_review_preset(
            project_context,
            next_chapter_number,
            chapter_plan,
        )
        if enable_multi_model_review
        else None
    )
    review_meta: Dict[str, Any] = {}
    if multi_model_preset:
        try:
            cfg = review_feature_gate.get_multi_model_review_config(project_context) or {}
            service = MultiModelReviewService(
                preset=multi_model_preset,
                chief_model=cfg.get("chief_model"),
            )
            multi_model_result = await service.review(
                chapter_draft,
                genre=genre,
                chapter_plan=chapter_plan,
            )
            review_meta = _build_next_chapter_review_meta(multi_model_result)
            review_report = str(multi_model_result.get("review") or "")
            if multi_model_result.get("multi_model") and review_report:
                await on_review_chunk(review_report, 1)
                logger.info(f"   ✓ 多模型评审完成，报告长度: {len(review_report)}")
                return review_report, review_meta
            logger.warning("多模型评审未产出足够结果，回退单模型评审")
        except Exception as e:
            review_meta = {
                "multi_model": False,
                "fallback_required": True,
                "fallback_reason": str(e),
            }
            logger.exception("多模型评审失败，回退单模型评审")

    review_report = await _run_single_next_chapter_streaming_review(
        chapter_draft=chapter_draft,
        chapter_plan=chapter_plan,
        plot_outline=plot_outline,
        genre=genre,
        next_chapter_number=next_chapter_number,
        recent_chapter_assets_summary=recent_chapter_assets_summary,
        streaming_service=streaming_service,
        on_review_chunk=on_review_chunk,
        real_coordinator=real_coordinator,
        review_model=review_model,
        max_llm_attempts=max_llm_attempts,
        require_exact_model=require_exact_model,
    )
    if review_meta:
        review_meta["multi_model"] = False
    return review_report, review_meta


def _get_chapter_plan_prompt_token_budget(model_name: Optional[str]) -> int:
    normalized_model = normalize_model_id(model_name) or model_name or "qwen3.7-plus"
    if normalized_model == "doubao-seed-character":
        try:
            configured_budget = int(os.getenv("DOUBAO_CHAPTER_PLAN_PROMPT_BUDGET", "80000"))
        except (TypeError, ValueError):
            configured_budget = 80000
        # 128K 输入窗口不贴边使用，给系统提示词、输出和服务端 token 估算差异留余量。
        return max(12000, min(configured_budget, 96000))

    safe_budget = _get_safe_input_token_budget(
        normalized_model,
        usage_ratio=0.60,
        prompt_overhead_tokens=2200,
    )
    return safe_budget


def _truncate_prompt_text(text: str, max_chars: int) -> str:
    value = str(text or "").strip()
    if not value or max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 80:
        return value[:max_chars].rstrip()

    marker = "\n...\n"
    available = max_chars - len(marker)
    head_chars = max(40, int(available * 0.68))
    tail_chars = max(30, available - head_chars)
    return f"{value[:head_chars].rstrip()}{marker}{value[-tail_chars:].lstrip()}"


def _shrink_prompt_text_to_token_budget(text: str, token_budget: int) -> str:
    value = str(text or "").strip()
    if not value or token_budget <= 0:
        return ""
    if _estimate_tokens_by_chars(value) <= token_budget:
        return value

    max_chars = max(40, int(token_budget / 1.3) - 16)
    shrunk = _truncate_prompt_text(value, max_chars)
    while _estimate_tokens_by_chars(shrunk) > token_budget and max_chars > 40:
        max_chars = max(40, int(max_chars * 0.82))
        shrunk = _truncate_prompt_text(value, max_chars)
    return shrunk


def _guard_chapter_plan_prompt_sections(
    sections: Dict[str, str],
    *,
    static_prompt_tokens: int,
    max_prompt_tokens: int,
) -> Dict[str, str]:
    dynamic_budget = max(300, max_prompt_tokens - static_prompt_tokens - 80)
    weights = {
        "current_chapter_outline": 0.16,
        "current_volume_context": 0.07,
        "core_character_anchor_context": 0.07,
        "focus_character_relationship_context": 0.07,
        "planning_character_context": 0.10,
        "epic_framework_context": 0.06,
        "optimized_context_text": 0.22,
        "structured_memory_text": 0.08,
        "previous_chapters_summary": 0.06,
        "recent_chapter_assets_summary": 0.06,
        "previous_ending": 0.04,
        "climax_instruction": 0.02,
        "chapter_plan_guide": 0.06,
        "concept": 0.03,
        "foreshadow_ledger_text": 0.03,
        "project_quality_memory_text": 0.03,
        "narrative_state_text": 0.03,
        "settings_catalog": 0.05,
    }
    guarded: Dict[str, str] = {}
    for key, value in sections.items():
        section_budget = max(40, int(dynamic_budget * weights.get(key, 0.04)))
        guarded[key] = _shrink_prompt_text_to_token_budget(value, section_budget)
    return guarded


def _build_chapter_plan_user_prompt(
    *,
    next_chapter_number: int,
    concept: str,
    current_chapter_outline: str,
    current_volume_context: str,
    core_character_anchor_context: str,
    focus_character_relationship_context: str,
    planning_character_context: str,
    epic_framework_context: str,
    optimized_context_text: str,
    structured_memory_text: str,
    previous_chapters_summary: str,
    recent_chapter_assets_summary: str,
    previous_ending: str,
    climax_instruction: str = "",
    chapter_plan_guide: str = "",
    foreshadow_ledger_text: str = "",
    project_quality_memory_text: str = "",
    narrative_state_text: str = "",
    settings_catalog: str = "",
    model_name: Optional[str] = None,
    max_prompt_tokens: Optional[int] = None,
) -> str:
    fallback_sections = {
        "concept": "（暂无故事概念）",
        "current_chapter_outline": "（未提取到当前章节精确细纲，将回退到章节窗口推断）",
        "current_volume_context": "（无可用卷级上下文）",
        "core_character_anchor_context": "（无可用核心角色锚点）",
        "focus_character_relationship_context": "（无可用焦点人物关系摘要）",
        "planning_character_context": "（无可用人物规划候选摘要）",
        "epic_framework_context": "（无额外长篇框架约束）",
        "optimized_context_text": "（无可用优化上下文）",
        "structured_memory_text": "（无可用结构化记忆）",
        "previous_chapters_summary": "（这是第一章）",
        "recent_chapter_assets_summary": "（最近章节没有可用的结构化连续性资产）",
        "previous_ending": "（这是第一章，没有前一章）",
        "climax_instruction": "",
        "chapter_plan_guide": "",
        "foreshadow_ledger_text": "",
        "project_quality_memory_text": "",
        "narrative_state_text": "",
        "settings_catalog": "",
    }
    raw_sections = {
        "concept": concept,
        "current_chapter_outline": current_chapter_outline,
        "current_volume_context": current_volume_context,
        "core_character_anchor_context": core_character_anchor_context,
        "focus_character_relationship_context": focus_character_relationship_context,
        "planning_character_context": planning_character_context,
        "epic_framework_context": epic_framework_context,
        "optimized_context_text": optimized_context_text,
        "structured_memory_text": structured_memory_text,
        "previous_chapters_summary": previous_chapters_summary,
        "recent_chapter_assets_summary": recent_chapter_assets_summary,
        "previous_ending": previous_ending,
        "climax_instruction": climax_instruction,
        "chapter_plan_guide": chapter_plan_guide,
        "foreshadow_ledger_text": foreshadow_ledger_text,
        "project_quality_memory_text": project_quality_memory_text,
        "narrative_state_text": narrative_state_text,
        "settings_catalog": settings_catalog,
    }

    def normalize_sections(source: Dict[str, str]) -> Dict[str, str]:
        return {
            key: str(value or "").strip() or fallback_sections[key]
            for key, value in source.items()
        }

    def render(sections: Dict[str, str]) -> str:
        genre_specific = ""
        if sections["chapter_plan_guide"]:
            genre_specific = f"""
【题材专属细化】（以下为通用规划要求的具体落地方式）
{sections["chapter_plan_guide"]}"""

        ledger_block = ""
        if sections["foreshadow_ledger_text"]:
            ledger_block = f"""
【未回收伏笔账本】（前文已埋设且尚未回收的伏笔，规划时优先考虑回收时机，禁止遗忘）
{sections["foreshadow_ledger_text"]}
"""

        memory_block = ""
        if sections["project_quality_memory_text"]:
            memory_block = f"""
【项目级高频问题记忆】（本项目历次评审中的高频未解决问题，规划时必须主动规避，不要让同类问题再次发生）
{sections["project_quality_memory_text"]}
"""

        settings_catalog_block = ""
        if sections["settings_catalog"]:
            settings_catalog_block = f"""
【项目设定清单】（项目设定中心已有的设定名称，规划时优先从中选择复用；确需新设定时须与既有设定不冲突）
{sections["settings_catalog"]}"""

        narrative_state_block = ""
        if sections["narrative_state_text"]:
            narrative_state_block = f"""
【叙事状态增量】（写后消化沉淀的执行结果：未偿还债务必须优先承接，人物按最新状态安排，未闭合事件不可当作未发生）
{sections["narrative_state_text"]}
"""

        settings_output_section = ""
        if sections["settings_catalog"]:
            settings_output_section = """
## 8. 设定调用
- 本章涉及的已有设定（功法/武器/丹药/地点/势力等）：名称必须与【项目设定清单】中的名称完全一致，注明使用者与用途
- 本章引入的新设定（如无则写"无"）：新设定不得与既有设定冲突，命名避免与清单中名称近似
"""

        return f"""请为第{next_chapter_number}章制定创作计划。

【整本书信息 - 智能优化上下文】
- 故事概念：{sections["concept"]}

【当前章节精确细纲】（如存在，最高优先级承接）
{sections["current_chapter_outline"]}

【当前卷上下文】（用于保持卷目标、卷节奏与卷内推进方向）
{sections["current_volume_context"]}

【核心角色锚点】（始终保留主角/核心对手/关键驱动者的长期目标与叙事职责）
{sections["core_character_anchor_context"]}

【焦点人物关系】（优先承接本章相关人物之间正在变化的关系与博弈）
{sections["focus_character_relationship_context"]}

【人物规划候选摘要】（用于本章规划阶段决定出场与推进，不直接灌入全量人物）
{sections["planning_character_context"]}

【长篇框架约束】（用于保持跨卷一致性）
{sections["epic_framework_context"]}

【优化后的核心上下文】（已通过分层摘要策略压缩）
{sections["optimized_context_text"]}

【结构化记忆约束】（优先遵循）
{sections["structured_memory_text"]}

【已完成章节摘要】
{sections["previous_chapters_summary"]}

【最近章节连续性资产】（优先承接拆书细纲、未完成冲突、人物状态、伏笔与钩子）
{sections["recent_chapter_assets_summary"]}
{ledger_block}{memory_block}{narrative_state_block}{settings_catalog_block}
【前一章结尾】（⚠️ 本章规划必须显式回应其结尾钩子/悬念：推进、升级、部分揭示或在"伏笔事项"标注悬置原因；结尾点名的威胁人物/关键人物本章须有着落——出场、被感知、被提及或主角对其的心理评估，不得无声消失）
{sections["previous_ending"]}
{sections["climax_instruction"]}

【输出要求】
请为第{next_chapter_number}章制定创作计划，必须包含：
## 1. 本章定位
- 章节定位：从【普通推进/开篇定调/小高潮/大高潮/关键转折/伏笔回收/人物突破/世界观揭示/卷末收束/完结收束】中严格选择一个，不要自造标签
- 在整体情节中的位置（起承转合哪个阶段）
- 本章类型：【日常/过渡/冲突/高潮/转折】

## 2. 核心事件
- 推进主线情节的关键事件
- 事件的起因-经过-结果

## 3. 爽点设计 ⚡
- 本章爽点类型：【打脸/升级/获得/反转/装逼/无（铺垫章）】
- 爽点具体内容描述
- 铺垫方式（如何让爽点更有冲击力）

## 4. 人物推进
- 主角本章的成长或变化
- 重要配角的表现
- 人物关系推进

## 5. 结尾钩子设计 🎣
- 钩子类型：【悬念式/危机式/反转式/信息炸弹式/选择困境式】
- 钩子具体内容
- 确保读者有“想点下一章”的冲动

## 6. 场景安排
- 时间、地点、氛围
- 场景转换节点

## 7. 伏笔事项
- 伏笔事项：本章新埋设或回收的伏笔（如无则写"无"）；若回收，注明对应第几章埋设的伏笔
{settings_output_section}
【约束】
- 确保与整本书情节大纲、前文剧情和结构化记忆保持一致
- 如提供当前章节精确细纲，必须优先落实场景目标、关键事件、人物出场、冲突推进、结尾钩子和伏笔
- 不得把细纲短过场扩写成与前章同构的重头戏；若同一功能场景再现，情况变化必须写清（例如宽限已过、威胁升级、当众撕破脸），篇幅上仍应是过场而非重播
- 人物动机、关系和主线绑定优先以人物运行态摘要为准
- 如果最近章节连续性资产已有场景目标、人物状态、伏笔或钩子，必须优先承接
- 推进故事发展，不能原地踏步；爽点和钩子必须具体、可执行{genre_specific}"""

    normalized_sections = normalize_sections(raw_sections)
    prompt = render(normalized_sections)
    if max_prompt_tokens is None:
        max_prompt_tokens = _get_chapter_plan_prompt_token_budget(model_name)
    if max_prompt_tokens <= 0 or _estimate_tokens_by_chars(prompt) <= max_prompt_tokens:
        return prompt

    static_sections = normalize_sections({key: "" for key in raw_sections})
    static_prompt_tokens = _estimate_tokens_by_chars(render(static_sections))
    guarded_sections = _guard_chapter_plan_prompt_sections(
        normalized_sections,
        static_prompt_tokens=static_prompt_tokens,
        max_prompt_tokens=max_prompt_tokens,
    )
    prompt = render(guarded_sections)

    trim_order = [
        "chapter_plan_guide",
        "optimized_context_text",
        "previous_chapters_summary",
        "planning_character_context",
        "current_volume_context",
        "core_character_anchor_context",
        "focus_character_relationship_context",
        "epic_framework_context",
        "structured_memory_text",
        "recent_chapter_assets_summary",
        "current_chapter_outline",
        "previous_ending",
    ]
    cursor = 0
    while _estimate_tokens_by_chars(prompt) > max_prompt_tokens and cursor < len(trim_order) * 4:
        key = trim_order[cursor % len(trim_order)]
        current_tokens = _estimate_tokens_by_chars(guarded_sections.get(key, ""))
        next_budget = max(30, int(current_tokens * 0.72))
        guarded_sections[key] = _shrink_prompt_text_to_token_budget(guarded_sections.get(key, ""), next_budget)
        prompt = render(guarded_sections)
        cursor += 1

    return prompt


from app.api.v1.workflow import router
from app.api.v1.workflow.schemas import *
from app.api.v1.workflow.helpers import *
from app.api.v1.workflow.helpers import (
    _build_iteration_review_prompt,
    _build_iteration_revision_prompt,
    _build_recent_chapter_assets_summary,
    _build_recent_full_chapter_excerpt,
    _estimate_tokens_by_chars,
    _get_safe_input_token_budget,
    _select_previous_chapter_context_strategy,
    _select_text_model_by_input_tokens,
)
from app.api.v1.workflow.story_helpers import *
from app.api.v1.workflow.story_helpers import _sync_real_coordinator_project_context
from app.api.v1.workflow.generation_profile import resolve_generation_profile
from app.api.v1.workflow.routes_optimize import (
    _create_generated_chapter,
    _extract_iteration_review_score,
)

@router.post("/{project_id}/generate-next-chapter")
async def generate_next_chapter(
    project_id: int,
    request: Optional[GenerateNextChapterRequest] = Body(default=None),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    生成下一章（异步模式）

    立即返回 task_id，后台执行四个步骤：
    1. 章节规划（0-25%）- 不保存，仅内存传递
    2. 内容创作（25-50%）- 保存到 chapter_draft
    3. 质量评审（50-75%）- 保存到 review_report
    4. 迭代优化（75-100%）- 保存到 final_version + chapters 表

    响应:
    {
        "task_id": "uuid-string",
        "status": "running",
        "message": "已开始生成第X章",
        "next_chapter_number": X
    }
    """
    # 注意：asyncio/text 已在模块顶部导入；函数内禁止就地 import（会遮蔽整个函数作用域）
    logger = logging.getLogger("uvicorn.error")

    # 🆕 项目生成锁：跨进程/跨实例互斥，任务启动后转交后台任务释放
    lock_service = get_generation_lock_service()
    lock_handle: Optional[LockHandle] = None
    background_task_started = False
    # 🆕 任务ID提前生成：免费档配额 reservation 以 task_id 为键
    task_id = str(uuid.uuid4())
    quota_reserved = False
    quota_result = None

    try:
        logger.info(f"📍 开始生成下一章（异步模式），项目ID: {project_id}")
        try:
            generation_profile = resolve_generation_profile(
                current_user=current_user,
                requested_tier=request.generation_tier if request else None,
                requested_model=request.workflow_generation_model if request else None,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        workflow_generation_model = generation_profile.model
        logger.info(
            f"   ✓ 生成档位: {generation_profile.tier} | 模型: {workflow_generation_model} | "
            f"最大迭代轮次: {generation_profile.max_iteration_rounds}"
        )
        # 🆕 锁定模型档位预检（fail closed）：模型被 catalog guard 重路由时直接拒绝，不占资源不启动任务
        if not generation_profile.allow_model_fallback and generation_profile.model:
            preflight_resolved = resolve_model_for_task(None, generation_profile.model)
            if preflight_resolved != generation_profile.model:
                logger.warning(
                    f"   ❌ 免费档预检失败：{generation_profile.model} 被重路由为 {preflight_resolved}"
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="免费生成模型暂不可用，请稍后再试",
                )
        workflow_context_builder = WorkflowContextBuilder(db)
        
        # 1. 验证项目存在且属于用户
        project = db.query(Project).filter(
            (Project.id == project_id) & (Project.user_id == current_user.id)
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="项目不存在"
            )
        
        logger.info(f"   ✓ 项目验证通过: {project.title}")

        # 🆕 P4：熔断检查——暂停状态阻断自动推进，仅人工确认（resume_after_confirmation）后恢复
        try:
            from app.services.narrative_circuit_breaker import (
                build_pause_detail,
                confirm_and_resume,
                is_paused,
            )

            breaker_meta = workflow_context_builder.load_review_meta(project_id) or {}
            if is_paused(breaker_meta):
                if request and request.resume_after_confirmation:
                    confirm_and_resume(breaker_meta)
                    workflow_context_builder.update_project_settings_fields(
                        project_id,
                        review_meta=breaker_meta,
                    )
                    logger.info("   🔁 熔断已由人工确认解除，恢复自动推进")
                else:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=build_pause_detail(breaker_meta),
                    )
        except HTTPException:
            raise
        except Exception as breaker_error:
            logger.warning(f"   ⚠️ 熔断检查失败（不阻断生成）: {breaker_error}")

        # 🆕 1.5 获取项目生成锁（Redis SET NX + token + TTL，全档位生效）
        # Redis 故障时：标准档回退进程内互斥并告警；免费档 fail closed 直接拒绝
        try:
            lock_handle = await lock_service.acquire(
                project_id,
                allow_local_fallback=(generation_profile.tier != "free"),
            )
            if lock_handle is None:
                # 🆕 残留锁回收：后端重启/进程被杀会中断后台任务，但 Redis 锁最长残留 30 分钟，
                # 表现为"没有任何可见任务却持续 409"。存活任务心跳每 300s 续租回满 TTL，
                # 锁剩余 TTL 低于阈值即判定持有任务已死 → 原子回收后重试获取一次
                stale_released = await lock_service.force_release_stale(project_id)
                if stale_released:
                    logger.warning(
                        f"   🧹 项目 {project_id} 存在残留生成锁（持有任务已中断），已自动回收"
                    )
                    lock_handle = await lock_service.acquire(
                        project_id,
                        allow_local_fallback=(generation_profile.tier != "free"),
                    )
                elif not has_active_generate_next_chapter_for_project(project_id):
                    # 本进程已无真正在跑的生成任务，但锁仍被占用：
                    # 常见于前端断流/热重载后心跳协程还活着，TTL 一直被续满。
                    orphan_released = await lock_service.force_release(project_id)
                    if orphan_released:
                        logger.warning(
                            f"   🧹 项目 {project_id} 生成锁被孤儿任务占用（本进程无活跃生成），已强制回收"
                        )
                        lock_handle = await lock_service.acquire(
                            project_id,
                            allow_local_fallback=(generation_profile.tier != "free"),
                        )
        except LockServiceUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="生成服务暂不可用，请稍后再试",
            ) from exc
        if lock_handle is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该项目正在生成章节中，请稍后重试；可在对应项目的创作流程页查看进度",
            )
        logger.info(f"   🔒 已获取项目生成锁 (backend={lock_handle.backend})")

        # 🆕 1.6 免费档配额原子占用（Lua：用户日额度 + 全局发放量，超限不递增）
        if generation_profile.quota_enabled:
            quota_service = get_free_quota_service()
            try:
                quota_result = await quota_service.reserve(current_user.id, task_id)
            except QuotaServiceUnavailableError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="免费额度服务暂不可用，请稍后再试",
                ) from exc
            if not quota_result.allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "message": (
                            "今日免费生成额度已用完"
                            if quota_result.reason == "user_limit"
                            else "今日免费发放量已达上限，请明天再来"
                        ),
                        "remaining_quota": quota_result.remaining,
                        "reset_at": quota_result.reset_at,
                    },
                )
            quota_reserved = True
            logger.info(
                f"   🎫 免费额度占用成功 | 剩余: {quota_result.remaining} | 重置: {quota_result.reset_at}"
            )

        # 2. 获取项目设定
        settings_context = workflow_context_builder.load_stage_text_context(project_id)
        
        if not any(
            [
                settings_context.concept,
                settings_context.world_setting,
                settings_context.characters,
                settings_context.plot_outline,
            ]
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="项目设定不存在，请先完成工作流程初始化"
            )
        
        concept = settings_context.concept
        world_setting = settings_context.world_setting
        characters = settings_context.characters
        plot_outline = settings_context.plot_outline
        logger.info(f"   ✓ 项目设定已加载")
        
        # 3. 获取已生成章节
        # 🆕 过滤软删除行：否则已删除章节仍被计入 next_chapter_number 并进入连续性上下文
        query = text("""
            SELECT id, chapter_number, title, content, summary
            FROM chapters
            WHERE project_id = :project_id
              AND deleted_at IS NULL
            ORDER BY chapter_number ASC
        """)
        chapters_result = db.execute(query, {"project_id": project_id}).fetchall()
        existing_chapters = [(r[0], r[1], r[2], r[3], r[4]) for r in chapters_result]

        # 计算下一章编号
        next_chapter_number = len(existing_chapters) + 1
        logger.info(f"   ✓ 当前已有 {len(existing_chapters)} 章，即将生成第 {next_chapter_number} 章")

        # 🆕 当所有章节都被删除时（连第一章都不存在），重置工作流章节相关阶段状态与草稿
        # 保留 concept/structure 阶段（项目设定与总大纲），仅清空章节草稿与评审/迭代产物
        # 这样前端会从"章节规划"步骤开始重新生成第 1 章
        if not existing_chapters:
            logger.info(f"   🔄 检测到项目无任何章节，重置章节草稿与阶段状态...")
            WorkflowContextBuilder(db).update_project_settings_fields(
                project_id,
                chapter_draft=None,
                review_report=None,
                final_version=None,
                stage_three_status="pending",
                stage_four_status="pending",
                stage_five_status="pending",
            )
            db.commit()
            logger.info(f"   ✅ 已重置章节草稿与阶段状态，将从第1章章节规划开始重新生成")

        # 4. 提取前一章结尾（用于衔接）与完整正文（用于重复输出检测）
        previous_ending = ""
        previous_chapter_content = ""
        if existing_chapters:
            previous_chapter = existing_chapters[-1]
            if previous_chapter[3]:  # 有内容
                # 提取最后500个字符
                content = previous_chapter[3]
                previous_chapter_content = str(content)
                previous_ending = content[-500:] if len(content) > 500 else content
        
        # 5. 生成已完成章节摘要，并为内容创作准备结构化的上一章信息
        def summarize_chapters(chapters):
            """生成已完成章节的摘要，并构造供内容生成使用的高层摘要列表。

            策略：按预计模型预算与章节长度动态决定
            - 最近若干章：使用扩展正文摘录，保证连续性
            - 再往前若干章：使用结构化摘要，覆盖更长历史
            - 更早章节：使用简要摘要，控制成本
            """
            if not chapters:
                return "这是第一章，之前没有章节。", [], ""

            # 局部导入，避免潜在的循环依赖
            from app.services.agents.chapter_summarizer import create_chapter_summarizer

            summaries = []
            previous_chapters_payload = []

            summarizer = None
            try:
                summarizer = create_chapter_summarizer(db_session=db)
            except Exception as e:
                logger.error(f"   ⚠️ 创建章节摘要生成器失败，将回退到内容前200字: {e}")

            total = len(chapters)
            context_strategy = _select_previous_chapter_context_strategy(
                chapters,
                next_chapter_number=next_chapter_number,
                preferred_model=workflow_generation_model,
            )
            recent_full_count = int(context_strategy.get("recent_full_count") or 0)
            detailed_summary_count = int(context_strategy.get("detailed_summary_count") or 0)
            recent_asset_count = int(context_strategy.get("recent_asset_count") or 0)
            recent_full_excerpt_chars = int(context_strategy.get("recent_full_excerpt_chars") or 1200)

            for idx, chapter in enumerate(chapters):
                chapter_id, chapter_num, title, content, existing_summary = chapter
                content = content or ""
                title = title or ""
                summary_text = (existing_summary or "").strip()
                summary_data = {}

                # 计算当前章节距离最后一章的距离
                distance_from_end = total - idx

                # 动态判断该章节的上下文层级
                use_recent_full_context = distance_from_end <= recent_full_count
                needs_detailed_summary = (
                    distance_from_end > recent_full_count
                    and distance_from_end <= recent_full_count + detailed_summary_count
                )
                needs_recent_assets = distance_from_end <= recent_asset_count

                if summarizer and (needs_detailed_summary or needs_recent_assets):
                    try:
                        cached_summary = summarizer.load_summary_from_db(chapter_id)
                        if isinstance(cached_summary, dict):
                            summary_data = cached_summary
                            summary_text = summary_data.get("core_summary", "").strip() or summary_text
                    except Exception as e:
                        logger.warning(f"   ⚠️ 读取第{chapter_num}章缓存摘要失败，将继续使用已有内容: {e}")

                if summarizer and (needs_detailed_summary or needs_recent_assets) and not summary_data:
                    # 对详细摘要区和最近连续性资产区补齐结构化摘要
                    try:
                        summary_data = summarizer.get_or_generate_summary(
                            chapter_id=chapter_id,
                            chapter_number=chapter_num,
                            chapter_title=title or f"第{chapter_num}章",
                            chapter_content=content,
                            summary_length=220,
                        )
                        summary_text = summary_data.get("core_summary", "").strip() or summary_text
                        logger.info(f"   ✅ 第{chapter_num}章补齐结构化摘要资产（距离末尾{distance_from_end}章）")
                    except Exception as e:
                        logger.error(f"   ⚠️ 生成第{chapter_num}章摘要失败，将回退简要摘要: {e}")

                if use_recent_full_context:
                    # 最近章节优先保留更长的上下文摘录，而不是只保留摘要句。
                    summary_text = _build_recent_full_chapter_excerpt(
                        content,
                        max_chars=recent_full_excerpt_chars,
                    ) or summary_text
                    context_mode = "recent_full"
                elif needs_detailed_summary:
                    if not summary_text:
                        summary_text = content[:220] if content and len(content) > 220 else content
                    context_mode = "detailed_summary"
                else:
                    if not summary_text:
                        summary_text = content[:200] if content and len(content) > 200 else content
                    context_mode = "brief_summary"

                if context_mode == "recent_full":
                    summaries.append(f"第{chapter_num}章 《{title}》:\n{summary_text}")
                else:
                    summaries.append(f"第{chapter_num}章 《{title}》: {summary_text}...")
                previous_chapters_payload.append(
                    {
                        "chapter_number": chapter_num,
                        "title": title,
                        "content": content,
                        "summary": summary_text,
                        "summary_data": summary_data,
                        "summary_mode": context_mode,
                    }
                )

            # 输出策略统计
            if total > 0:
                recent_full_range = (
                    f"第{max(1, total - recent_full_count + 1)}-{total}章"
                    if total > recent_full_count else f"第1-{total}章"
                )
                summary_range_start = max(1, total - recent_full_count - detailed_summary_count + 1)
                summary_range_end = max(0, total - recent_full_count)
                
                logger.info(f"   📊 上下文策略：")
                logger.info(
                    f"      - 预计规划模型: {context_strategy.get('selected_model', 'unknown')} "
                    f"(历史预算约 {context_strategy.get('history_budget_tokens', 0)} tokens)"
                )
                logger.info(f"      - 最近{min(recent_full_count, total)}章扩展正文摘录: {recent_full_range}")
                if summary_range_end > 0:
                    logger.info(
                        f"      - 往前{min(detailed_summary_count, summary_range_end)}章结构化摘要: "
                        f"第{summary_range_start}-{summary_range_end}章"
                    )
                if total > recent_full_count + detailed_summary_count:
                    logger.info(
                        f"      - 更早{total - recent_full_count - detailed_summary_count}章简要摘要: "
                        f"第1-{total - recent_full_count - detailed_summary_count}章"
                    )
                logger.info(f"      - 最近连续性资产窗口: {min(recent_asset_count, total)}章")

            recent_chapter_assets_summary = _build_recent_chapter_assets_summary(previous_chapters_payload)
            return "\n\n".join(summaries), previous_chapters_payload, recent_chapter_assets_summary

        previous_chapters_summary, previous_chapters_payload, recent_chapter_assets_summary = summarize_chapters(existing_chapters)

        # 6. 使用提前生成的任务ID创建任务记录（task_id 已在配额 reservation 中使用）
        logger.info(f"   🎯 创建异步任务: {task_id}")

        # 创建任务记录
        insert_query = text("""
            INSERT INTO generation_history
            (project_id, task_type, task_id, status, created_at)
            VALUES (:project_id, :task_type, :task_id, :status, :created_at)
        """)

        db.execute(insert_query, {
            "project_id": project_id,
            "task_type": "generate_next_chapter",
            "task_id": task_id,
            "status": "running",
            "created_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"   ✅ 任务记录已创建")

        world_context = workflow_context_builder.build_world_setting_context(
            project_id,
            world_setting,
        )
        merged_world_setting = world_context.combined_world_setting
        if world_context.settings_summary:
            logger.info(
                "   ✓ 已统一装配工作流世界观上下文（设定摘要%s）",
                "去重复用" if world_context.summary_already_embedded else "实时注入",
            )

        # 7. 启动后台任务
        generation_task = asyncio.create_task(
            execute_generate_next_chapter_task(
                task_id=task_id,
                project_id=project_id,
                user_id=current_user.id,
                next_chapter_number=next_chapter_number,
                concept=concept or '',
                world_setting=merged_world_setting,
                characters=characters or '',
                plot_outline=plot_outline or '',
                previous_ending=previous_ending,
                previous_chapters_summary=previous_chapters_summary,
                previous_chapters_payload=previous_chapters_payload,
                recent_chapter_assets_summary=recent_chapter_assets_summary,
                workflow_generation_model=workflow_generation_model,
                generation_tier=generation_profile.tier,
                max_iteration_rounds=generation_profile.max_iteration_rounds,
                enable_multi_model_review=generation_profile.enable_multi_model_review,
                max_llm_attempts=generation_profile.max_llm_attempts,
                allow_model_fallback=generation_profile.allow_model_fallback,
                lock_handle=lock_handle,
                quota_enabled=generation_profile.quota_enabled,
            )
        )
        mark_generate_next_chapter_task_active(task_id, project_id, aio_task=generation_task)
        background_task_started = True
        logger.info(f"   🚀 后台任务已启动")

        # 8. 立即返回响应
        response = {
            "task_id": task_id,
            "status": "running",
            "message": f"已开始生成第{next_chapter_number}章",
            "next_chapter_number": next_chapter_number,
            "workflow_generation_model": workflow_generation_model,
            "generation_tier": generation_profile.tier,
        }
        if quota_result is not None:
            response["remaining_quota"] = quota_result.remaining
            response["quota_reset_at"] = quota_result.reset_at
        return response

    except HTTPException:
        # 锁已获取但任务未启动：退还额度并释放锁（避免 409 死锁到 TTL 过期）
        if not background_task_started:
            if quota_reserved:
                await get_free_quota_service().refund_if_pending(task_id)
            if lock_handle is not None:
                await lock_service.release(lock_handle)
        raise
    except Exception as e:
        if not background_task_started:
            if quota_reserved:
                await get_free_quota_service().refund_if_pending(task_id)
            if lock_handle is not None:
                await lock_service.release(lock_handle)
        logger.error(f"❌ 创建生成下一章任务失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/free-generation/quota")
async def get_free_generation_quota(current_user=Depends(get_current_user)):
    """Return the authenticated user's free chapter allowance."""
    try:
        quota = await get_free_quota_service().get_status(current_user.id)
    except QuotaServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="免费额度服务暂不可用，请稍后再试",
        ) from exc
    return {
        "enabled": bool(getattr(settings, "FREE_TIER_ENFORCEMENT_ENABLED", False)),
        "daily_limit": quota.daily_limit,
        "used": quota.used,
        "remaining": quota.remaining,
        "reset_at": quota.reset_at,
        "global_available": quota.global_available,
    }


async def execute_generate_next_chapter_task(
    task_id: str,
    project_id: int,
    user_id: int,
    next_chapter_number: int,
    concept: str,
    world_setting: str,
    characters: str,
    plot_outline: str,
    previous_ending: str,
    previous_chapters_summary: str,
    previous_chapters_payload: list,
    recent_chapter_assets_summary: str,
    workflow_generation_model: Optional[str] = None,
    generation_tier: str = "standard",
    max_iteration_rounds: Optional[int] = None,
    enable_multi_model_review: bool = True,
    max_llm_attempts: int = 3,
    allow_model_fallback: bool = True,
    lock_handle: Optional[LockHandle] = None,
    quota_enabled: bool = False,
):
    """
    后台执行生成下一章任务（真流式版本）

    执行四个步骤：
    1. 章节规划（0-25%）- 使用 asyncio.to_thread 避免阻塞
    2. 内容创作（25-50%）- 使用真流式 LLM 调用
    3. 质量评审（50-75%）- 使用真流式 LLM 调用
    4. 迭代优化（75-100%）- 使用真流式 LLM 调用
    """
    # 注意：text/SessionLocal 已在模块顶部导入；函数内禁止就地 import（会遮蔽整个函数作用域）
    logger = logging.getLogger("uvicorn.error")
    logger.info(
        f"🚀 开始执行后台任务: {task_id}, 生成第{next_chapter_number}章 | "
        f"档位: {generation_tier} | 模型: {workflow_generation_model or '自动'}"
    )
    # 🆕 锁定模型档位（免费档）：禁止回退时全链路严格校验模型，重路由即终止
    require_exact_model = not allow_model_fallback
    mark_generate_next_chapter_task_active(task_id, project_id)

    # 获取流式服务
    streaming_service = get_streaming_service()

    # 创建独立的数据库会话
    db = SessionLocal()
    lock_heartbeat_task = (
        asyncio.create_task(_keep_generation_lock_alive(lock_handle))
        if lock_handle is not None
        else None
    )

    # 🆕 定义四个步骤对应的 Agent 列表，统一来自后端 Agent 注册表
    STEP_AGENTS = get_stage_agents_map(include_stage=True)

    try:
        workflow_context_builder = WorkflowContextBuilder(db)
        project_profile = workflow_context_builder.get_project_profile(project_id)
        chapter_generation_context = workflow_context_builder.build_chapter_generation_context(
            project_id,
            next_chapter_number,
            plot_outline=plot_outline or "",
            characters=characters or "",
        )
        if chapter_generation_context.outline_source:
            logger.info(
                "   📌 当前章细纲命中：source=%s, chapter=%s, length=%s",
                chapter_generation_context.outline_source,
                next_chapter_number,
                len(chapter_generation_context.current_chapter_outline or ""),
            )
        else:
            logger.info("   📌 当前章细纲未命中结构化章节块，将依赖章节窗口上下文推断")
        if chapter_generation_context.focus_character_names:
            logger.info(
                "   👥 当前章优先人物：%s",
                "、".join(chapter_generation_context.focus_character_names),
            )
        # ==================== 步骤1：章节规划（真流式） ====================
        # 🆕 推送步骤1的 Agent 开始工作状态
        step1_agents = STEP_AGENTS['structure']
        for agent in step1_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='working',
                progress=0,
                message=f'{agent["name"]}正在规划章节结构...'
            )
        logger.info(f"   📡 已发送 {len(step1_agents)} 个 Agent 开始状态（步骤1）")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=5,
            message=f"步骤 1/4: 正在规划第{next_chapter_number}章结构..."
        )
        logger.info(f"   → 步骤1: 生成章节规划（真流式）...")

        # 确保协调器已初始化
        if not coordinator._coordinator_initialized:
            logger.info("   🔍 协调器未初始化，开始初始化...")
            await coordinator.initialize_agents()
            logger.info("   ✅ 协调器初始化完成")

        coordinator.set_project_context(project_id)
        project_profile, real_coordinator = _sync_real_coordinator_project_context(
            project_id,
            workflow_context_builder,
            project_profile,
        )
        if not real_coordinator:
            raise Exception("Agent协调器未初始化")

        # 🆕 发送流式开始通知
        await ws_manager.send_stream_start(project_id, 'structure', f"第{next_chapter_number}章规划开始...")
        # 🔔 推送阶段开始状态（生成下一章 - 步骤1）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='structure',
            status='active',
            progress=0
        )

        # 🆕 创建流式输出回调
        plan_chunk_index = [0]

        async def on_plan_chunk(chunk: str, idx: int):
            """章节规划流式回调"""
            plan_chunk_index[0] = idx
            await ws_manager.send_stream_chunk(
                project_id=project_id,
                stage='structure',
                chunk=chunk,
                chunk_index=idx,
                is_complete=False
            )

        # 🎆 第一步：为章节规划使用分层摘要策略
        from app.services.agents.layered_summarizer import LayeredSummarizer
        from app.services.agents.agent_coordinator import GENRE_PROMPT_MODULES, DEFAULT_GENRE_MODULE
        from app.services.prompts.stages.chapter_planning import (
            ChapterPlanningPrompts, 
            get_genre_chapter_plan_guide,
            get_climax_instruction
        )

        # 🆕 获取高潮章节指示（大纲节奏优先：以本章细纲标注为准，取模节奏仅兜底）
        climax_instruction = get_climax_instruction(
            next_chapter_number,
            chapter_outline=chapter_generation_context.current_chapter_outline or "",
        )
        
        # 🆕 获取项目题材
        plan_project_genre = project_profile.genre or ""
        logger.info(f"   🎯 项目题材: {plan_project_genre or '通用'}")
        
        # 🆕 获取题材专属章节规划指导
        plan_genre_module = GENRE_PROMPT_MODULES.get(plan_project_genre, DEFAULT_GENRE_MODULE)
        chapter_plan_guide = plan_genre_module.get('chapter_plan_guide', '')
        
        # 🎆 使用分层摘要策略优化上下文
        layered_summarizer = LayeredSummarizer()
        plan_character_context = (
            chapter_generation_context.planning_character_prompt_context
            or chapter_generation_context.content_character_context
            or ""
        )
        forced_plan_model = normalize_model_id(workflow_generation_model) if workflow_generation_model else None
        forced_plan_ratio = 0.45 if forced_plan_model else None
        plan_context_result = layered_summarizer.prepare_context_for_expansion(
            outline=plot_outline or "",
            characters=plan_character_context,
            worldview=world_setting or "",
            scenario="chapter_generation",
            current_count=next_chapter_number,  # 使用当前章节数选择模型
            focus_range=(max(1, next_chapter_number - 5), next_chapter_number + 5),  # 聚焦当前章节前后5章
            project_id=project_id,
            forced_model=forced_plan_model,
            forced_target_ratio=forced_plan_ratio,
        )
        
        # 🔥 使用智能选择的模型和优化后的上下文
        selected_plan_model = workflow_generation_model or plan_context_result["selected_model"]
        plan_optimized_context_text = plan_context_result["context"]
        plan_memory_text = plan_context_result.get("memory_text", "")
        plan_structured_memory = plan_context_result.get("structured_memory", {})
        plan_stats = plan_context_result["stats"]
        
        logger.info(f"   📊 上下文优化（章节规划 - 分层摘要）:")
        logger.info(f"      - 选择模型: {selected_plan_model}")
        logger.info(f"      - 原始总长: {len(plot_outline or '') + len(plan_character_context) + len(world_setting or ''):,}字符")
        logger.info(f"      - 优化后: {len(plan_optimized_context_text):,}字符 (压缩{(1-plan_stats['compression_ratio'])*100:.1f}%)")
        logger.info(f"      - 结构化记忆: {len(plan_memory_text):,}字符 / {len(plan_structured_memory)}类")
        logger.info(f"      - Token使用: {plan_stats['total_tokens']:,} / {plan_stats['target_tokens']:,}")
        logger.info(f"      - 聚焦范围: 第{max(1, next_chapter_number - 5)}-{next_chapter_number + 5}章")
        logger.info(f"      - 人物输入: {len(plan_character_context):,}字符（按当前章筛选后的候选摘要）")
        resolved_plan_model = resolve_model_for_task(None, selected_plan_model) or selected_plan_model
        
        # 构建包含各部分的上下文字典（用于后续提示词构建）
        plan_optimized_context = {
            'project_concept': concept or '',
            'plot_outline': plan_optimized_context_text,  # 使用优化后的完整上下文
            'structured_memory_text': plan_memory_text,
            'structured_memory': plan_structured_memory,
            'world_setting': '',  # 已包含在优化上下文中
            'characters': '',  # 已包含在优化上下文中
            'previous_chapters_analysis': previous_chapters_summary or '',
            'recent_chapter_assets_summary': recent_chapter_assets_summary or '',
            'previous_ending': previous_ending or ''
        }
        # 🆕 广播步骤1模型
        await ws_manager.send_model_used(
            project_id=project_id,
            stage='structure',
            model=resolved_plan_model,
            extra={
                "step": "chapter_plan",
                "chapter_number": next_chapter_number,
                "requested_model": selected_plan_model,
            }
        )

        # 🆕 构建章节规划提示词（使用模块化系统）
        plan_system_prompt = ChapterPlanningPrompts.get_system_prompt(plan_project_genre)
        plan_prompt_budget = _get_chapter_plan_prompt_token_budget(selected_plan_model)
        # 🆕 P1-2/P1-3：加载项目级质量记忆与伏笔账本（持久化于 project_settings.review_meta）
        try:
            project_review_meta = workflow_context_builder.load_review_meta(project_id) or {}
        except Exception as meta_error:
            logger.warning(f"   ⚠️ 加载 review_meta 失败，跳过记忆/账本注入: {meta_error}")
            project_review_meta = {}
        foreshadow_ledger_text = ""
        unified_foreshadow_tasks: list = []
        try:
            # P0：统一伏笔上下文适配器——将框架/章节两层伏笔投影为统一任务格式；
            # 解析失败时回退旧账本格式，不阻断章节生成
            from app.services.foreshadow_adapter import (
                build_unified_foreshadow_tasks,
                extract_volume_foreshadow_texts,
                format_unified_foreshadow_section,
            )

            epic_framework_state = workflow_context_builder.load_epic_framework_state(project_id)
            # 🆕 卷级 new_foreshadowings 接线：从卷明细/卷上下文规则提取伏笔摘要，
            # 与框架伏笔、章节账本合并为三层统一任务
            volume_foreshadow_texts = extract_volume_foreshadow_texts(
                getattr(epic_framework_state, "epic_volumes_detail", "") or "",
                chapter_generation_context.current_volume_context or "",
            )
            unified_foreshadow_tasks = build_unified_foreshadow_tasks(
                framework_text=getattr(epic_framework_state, "epic_framework", "") or "",
                review_meta=project_review_meta,
                volume_foreshadow_texts=volume_foreshadow_texts,
                current_chapter=next_chapter_number,
            )
            foreshadow_ledger_text = format_unified_foreshadow_section(
                unified_foreshadow_tasks,
                current_chapter=next_chapter_number,
            )
        except Exception as foreshadow_adapter_error:
            logger.warning(
                f"   ⚠️ 统一伏笔适配失败，回退旧账本格式: {foreshadow_adapter_error}"
            )
            unified_foreshadow_tasks = []
            # 🆕 P4：账本存在但适配解析失败，视为账本损坏 → 熔断信号（立即暂停）
            if (project_review_meta or {}).get("foreshadow_ledger"):
                try:
                    from app.services.narrative_circuit_breaker import record_generation_signal

                    record_generation_signal(
                        project_review_meta,
                        chapter_number=next_chapter_number,
                        event="ledger_corrupt",
                        detail=str(foreshadow_adapter_error)[:200],
                    )
                    workflow_context_builder.update_project_settings_fields(
                        project_id,
                        review_meta=project_review_meta,
                    )
                except Exception as breaker_signal_error:
                    logger.warning(f"   ⚠️ 熔断信号记录失败: {breaker_signal_error}")
        if not foreshadow_ledger_text:
            foreshadow_ledger_text = format_foreshadow_ledger(project_review_meta, next_chapter_number)
        project_quality_memory_text = format_quality_memory(project_review_meta)
        # 🆕 P2：叙事状态增量（写后消化沉淀，优先承接债务/人物变化/未闭合事件）
        narrative_state_text = ""
        try:
            from app.services.narrative_state_extractor import format_narrative_state_section

            narrative_state_text = format_narrative_state_section(
                project_review_meta, next_chapter_number
            )
        except Exception as narrative_state_error:
            logger.warning(f"   ⚠️ 叙事状态增量加载失败，跳过注入: {narrative_state_error}")
        # 🆕 P3：质量趋势与文风漂移告警作为证据注入（与失败码配合，不替代修订路由）
        try:
            from app.services.narrative_metrics import (
                format_quality_trend_advice,
                format_style_drift_advice,
            )

            for trend_advice in (
                format_quality_trend_advice(project_review_meta),
                format_style_drift_advice(project_review_meta, next_chapter_number),
            ):
                if trend_advice:
                    project_quality_memory_text = (
                        f"{project_quality_memory_text}\n\n{trend_advice}".strip()
                    )
        except Exception as trend_error:
            logger.warning(f"   ⚠️ 质量趋势告警加载失败，跳过注入: {trend_error}")
        if foreshadow_ledger_text:
            logger.info(f"   📌 伏笔账本注入：{foreshadow_ledger_text.count(chr(10)) + 1} 条未回收伏笔")
        if project_quality_memory_text:
            logger.info("   🧠 项目级高频问题记忆注入（前3条）")
        # 🆕 设定清单：项目设定中心全部设定名称，供规划选择复用并在"设定调用"字段点名
        try:
            from app.services.setting_templates import build_settings_catalog_text

            plan_settings_catalog = build_settings_catalog_text(project_id, db)
        except Exception as catalog_error:
            logger.warning(f"   ⚠️ 设定清单生成失败，跳过注入: {catalog_error}")
            plan_settings_catalog = ""
        if plan_settings_catalog:
            logger.info(
                f"   📖 设定清单注入：{len(plan_settings_catalog):,}字符"
            )
        plan_user_prompt = _build_chapter_plan_user_prompt(
            next_chapter_number=next_chapter_number,
            concept=plan_optimized_context.get('project_concept', concept),
            current_chapter_outline=chapter_generation_context.current_chapter_outline,
            current_volume_context=chapter_generation_context.current_volume_context,
            core_character_anchor_context=chapter_generation_context.core_character_anchor_context,
            focus_character_relationship_context=chapter_generation_context.focus_character_relationship_context,
            planning_character_context=(
                chapter_generation_context.planning_character_prompt_context
                or chapter_generation_context.character_prompt_context
            ),
            epic_framework_context=chapter_generation_context.epic_framework_context,
            optimized_context_text=plan_optimized_context.get('plot_outline', plot_outline),
            structured_memory_text=plan_optimized_context.get('structured_memory_text', ''),
            previous_chapters_summary=plan_optimized_context.get('previous_chapters_analysis', previous_chapters_summary),
            recent_chapter_assets_summary=plan_optimized_context.get('recent_chapter_assets_summary', recent_chapter_assets_summary),
            previous_ending=plan_optimized_context.get('previous_ending', previous_ending),
            climax_instruction=climax_instruction,
            chapter_plan_guide=chapter_plan_guide,
            foreshadow_ledger_text=foreshadow_ledger_text,
            project_quality_memory_text=project_quality_memory_text,
            narrative_state_text=narrative_state_text,
            settings_catalog=plan_settings_catalog,
            model_name=selected_plan_model,
            max_prompt_tokens=plan_prompt_budget,
        )
        plan_prompt_tokens = _estimate_tokens_by_chars(plan_user_prompt)
        logger.info(
            "      - 最终规划Prompt: %s tokens / 预算 %s tokens",
            plan_prompt_tokens,
            plan_prompt_budget,
        )

        # 🆕 使用真流式 LLM 调用（智能选择模型）
        try:
            chapter_plan = await streaming_service.generate_chapter_streaming(
                prompt=plan_user_prompt,
                system_prompt=plan_system_prompt,
                on_chunk=on_plan_chunk,
                temperature=0.7,
                model=selected_plan_model,  # 🔥 使用智能选择的模型
                max_retries=max_llm_attempts,
                require_exact_model=require_exact_model,
                disable_thinking=True,  # 🆕 规划默认关闭思考模式，避免 reasoning 占用上下文
            )
            logger.info(f"   ✓ 章节规划已完成（真流式 + {selected_plan_model}），长度: {len(chapter_plan)}")
        except Exception as e:
            # 🆕 锁定模型档位下禁止回退到协调器（回退路径模型不受控），直接终止
            if require_exact_model:
                logger.error(f"   ❌ 锁定模型章节规划失败且禁止回退: {e}")
                raise
            logger.error(f"   ⚠️ 真流式调用失败，回退到同步调用: {e}")
            # 回退到同步调用
            if hasattr(real_coordinator, 'generate_chapter_plan'):
                chapter_plan = await asyncio.to_thread(
                    real_coordinator.generate_chapter_plan,
                    chapter_number=next_chapter_number,
                    project_concept=concept,
                    plot_outline="\n\n".join(
                        part
                        for part in (
                            chapter_generation_context.current_chapter_outline,
                            chapter_generation_context.current_volume_context,
                            plot_outline,
                        )
                        if part and part.strip()
                    ),
                    world_setting=world_setting,
                    characters=chapter_generation_context.character_prompt_context or characters,
                    previous_chapters_summary=previous_chapters_summary,
                    previous_ending=previous_ending
                )
            else:
                chapter_plan = f"第{next_chapter_number}章创作规划\n\n根据情节大纲和前序章节，本章将继续推进故事发展..."

        # 🆕 P1：细纲驱动的写前连续性闸门（纯规则校验，验证规划能否在当前叙事状态下执行）
        gate_issues: list = []
        gate_warning_section = ""
        try:
            from app.services.pre_generation_gate import (
                build_gate_report,
                format_gate_feedback,
                format_gate_warning_section,
                has_blocking_issues,
                infer_current_volume,
                run_pre_generation_gate,
            )

            gate_character_rows = db.execute(
                text(
                    """
                    SELECT name, appearance_status, life_status
                    FROM characters
                    WHERE project_id = :project_id
                    """
                ),
                {"project_id": project_id},
            ).fetchall()
            gate_character_states = [
                {
                    "name": row[0],
                    "appearance_status": row[1],
                    "life_status": row[2],
                }
                for row in gate_character_rows
            ]
            gate_current_volume = infer_current_volume(
                chapter_generation_context.current_volume_context or "",
                chapter_generation_context.current_chapter_outline or "",
            )

            def _run_gate() -> list:
                return run_pre_generation_gate(
                    chapter_plan=chapter_plan,
                    chapter_outline=chapter_generation_context.current_chapter_outline or "",
                    unified_tasks=unified_foreshadow_tasks,
                    character_states=gate_character_states,
                    current_volume=gate_current_volume,
                    current_chapter=next_chapter_number,
                    settings_catalog=plan_settings_catalog,
                )

            gate_issues = _run_gate()
            if has_blocking_issues(gate_issues):
                # blocking → 附加闸门反馈重规划，最多2轮；仍失败则保留草稿与报告转人工确认
                max_gate_replans = 2
                for gate_round in range(1, max_gate_replans + 1):
                    blocking_count = sum(
                        1 for issue in gate_issues if issue.get("severity") == "blocking"
                    )
                    logger.warning(
                        f"   🚧 写前闸门 blocking×{blocking_count}，重规划第{gate_round}/{max_gate_replans}轮"
                    )
                    await ws_manager.send_task_progress(
                        project_id=project_id,
                        task_id=task_id,
                        progress=25,
                        message=f"写前闸门发现冲突，重规划中（{gate_round}/{max_gate_replans}）",
                    )
                    chapter_plan = await streaming_service.generate_chapter_streaming(
                        prompt=plan_user_prompt + "\n\n" + format_gate_feedback(gate_issues),
                        system_prompt=plan_system_prompt,
                        on_chunk=on_plan_chunk,
                        temperature=0.5,
                        model=selected_plan_model,
                        max_retries=max_llm_attempts,
                        require_exact_model=require_exact_model,
                        disable_thinking=True,  # 🆕 重规划同样关闭思考模式
                    )
                    gate_issues = _run_gate()
                    if not has_blocking_issues(gate_issues):
                        logger.info(f"   ✓ 写前闸门第{gate_round}轮重规划后通过")
                        break

                if has_blocking_issues(gate_issues):
                    # 不丢弃规划：保存草稿与闸门报告到 review_meta，任务失败转人工确认
                    gate_report = build_gate_report(
                        gate_issues,
                        chapter_number=next_chapter_number,
                        rounds=max_gate_replans,
                    )
                    try:
                        gate_review_meta = workflow_context_builder.load_review_meta(project_id) or {}
                        gate_review_meta["pre_generation_gate"] = {
                            "report": gate_report,
                            "plan_draft": chapter_plan[:8000],
                        }
                        # 🆕 P4：闸门连续 blocking 信号 → 熔断（连续两章未解决则暂停）
                        try:
                            from app.services.narrative_circuit_breaker import record_generation_signal

                            record_generation_signal(
                                gate_review_meta,
                                chapter_number=next_chapter_number,
                                event="gate_blocking",
                                detail=f"重规划后仍有 {gate_report['blocking_count']} 项 blocking 未解决",
                            )
                        except Exception as breaker_signal_error:
                            logger.warning(f"   ⚠️ 熔断信号记录失败: {breaker_signal_error}")
                        workflow_context_builder.update_project_settings_fields(
                            project_id,
                            review_meta=gate_review_meta,
                        )
                    except Exception as gate_save_error:
                        logger.warning(f"   ⚠️ 闸门报告保存失败: {gate_save_error}")
                    raise RuntimeError(
                        f"第{next_chapter_number}章写前闸门重规划{max_gate_replans}轮后仍存在"
                        f"{gate_report['blocking_count']}项 blocking 冲突，规划草稿与闸门报告已保存至"
                        " review_meta.pre_generation_gate，请人工确认或调整细纲后重试"
                    )
            gate_warning_section = format_gate_warning_section(gate_issues)
            if gate_issues:
                logger.info(
                    f"   🚧 写前闸门通过：blocking=0，warning={sum(1 for i in gate_issues if i.get('severity') == 'warning')}"
                )
        except RuntimeError:
            raise
        except Exception as gate_error:
            logger.warning(f"   ⚠️ 写前闸门接入异常，跳过闸门: {gate_error}")
            gate_issues = []
            gate_warning_section = ""

        try:
            plan_meta = workflow_context_builder.load_review_meta(project_id) or {}
            plan_meta["last_chapter_plan"] = {
                "chapter_number": next_chapter_number,
                "plan": chapter_plan[:12000],
                "outline": (chapter_generation_context.current_chapter_outline or "")[:4000],
            }
            workflow_context_builder.update_project_settings_fields(
                project_id,
                review_meta=plan_meta,
            )
        except Exception as plan_persist_error:
            logger.warning(f"   ⚠️ 章节规划落库失败（不阻断生成）: {plan_persist_error}")

        await ws_manager.send_stream_end(project_id, 'structure', len(chapter_plan), f"第{next_chapter_number}章规划完成")
        # 🔔 推送阶段完成状态（生成下一章 - 步骤1）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='structure',
            status='completed',
            output=chapter_plan,
            progress=25
        )

        # 🆕 推送步骤1的 Agent 完成状态
        for agent in step1_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(step1_agents)} 个 Agent 完成状态（步骤1）")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=25,
            message=f"步骤 1/4: 章节规划完成 ✓"
        )

        # ==================== 步骤2：内容创作（真流式） ====================
        logger.info(f"   🔴 开始步骤2：内容创作")
        
        # 🆕 推送步骤2的 Agent 开始工作状态
        step2_agents = STEP_AGENTS['content']
        logger.info(f"   📄 已获取步骤2 Agents: {[a['name'] for a in step2_agents]}")
        
        for agent in step2_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='working',
                progress=0,
                message=f'{agent["name"]}正在创作章节内容...'
            )
        logger.info(f"   📡 已发送 {len(step2_agents)} 个 Agent 开始状态（步骤2）")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=30,
            message=f"步骤 2/4: 正在创作第{next_chapter_number}章内容..."
        )
        logger.info(f"   → 步骤2: 生成章节内容（真流式）...")
        logger.info(f"   📊 章节规划长度: {len(chapter_plan)} 字")

        # 🆕 发送流式开始通知
        logger.info(f"   🌊 发送流式开始通知...")
        await ws_manager.send_stream_start(project_id, 'content', f"第{next_chapter_number}章内容创作开始...")
        # 🔔 推送阶段开始状态（生成下一章 - 步骤2）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='content',
            status='active',
            progress=25
        )

        # 🆕 创建流式输出回调
        content_chunk_index = [0]
        logger.info(f"   🔧 已创建流式回调函数")

        async def on_content_chunk(chunk: str, idx: int):
            """内容创作流式回调"""
            content_chunk_index[0] = idx
            await ws_manager.send_stream_chunk(
                project_id=project_id,
                stage='content',
                chunk=chunk,
                chunk_index=idx,
                is_complete=False
            )

        logger.info(f"   📐 匹配章节定位与场景类型...")

        # 🆕 开头/结尾方式与节奏指导：统一从 content_creation 单一来源导入（章节定位路由优先，禁止内嵌副本）
        from app.services.prompts.stages.content_creation import get_recommended_styles

        selected_opening, selected_ending, match_method, position_rhythm_hint = get_recommended_styles(
            chapter_plan, next_chapter_number
        )

        logger.info(f"   📝 第{next_chapter_number}章 - 开头: {selected_opening[0]}, 结尾: {selected_ending[0]} [{match_method}]")
        logger.info(f"   💬 构建内容创作提示词...")

        # 🆕 上下文优化：获取智能模型选择
        from app.services.agents.context_optimizer import get_context_optimizer
        context_optimizer = get_context_optimizer(
            current_chapter=next_chapter_number,
            stage='content_creation',
            model_name=workflow_generation_model,
        )
        
        # 🆕 获取优化器选择的模型（不再需要 optimize_for_chapter_generation，因为章节规划已消化上下文）
        selected_content_model = workflow_generation_model or context_optimizer.selected_model
        resolved_content_model = resolve_model_for_task(None, selected_content_model) or selected_content_model
        logger.info(f"   🤖 内容创作使用模型: {resolved_content_model} (requested={selected_content_model})")
        # 🆕 广播步骤2模型
        await ws_manager.send_model_used(
            project_id=project_id,
            stage='content',
            model=resolved_content_model,
            extra={
                "step": "chapter_content",
                "chapter_number": next_chapter_number,
                "requested_model": selected_content_model,
            }
        )

        # 🆕 Typed-RAG（按类型检索并注入提示）
        rag_character_context = ""
        rag_world_context = ""
        rag_query_text = "\n\n".join(
            part
            for part in (
                chapter_plan,
                chapter_generation_context.rag_query_text,
                (
                    f"相关人物：{'、'.join(chapter_generation_context.focus_character_names)}"
                    if chapter_generation_context.focus_character_names
                    else ""
                ),
            )
            if part and part.strip()
        )
        # 🆕 P2 检索质量：embedding query 用短句（出场人物+关键事件），避免整章规划长文本稀释语义
        compact_query_parts = list(chapter_generation_context.focus_character_names or [])
        compact_query_parts.extend(extract_key_events(chapter_plan)[:3])
        rag_search_query = "；".join(part for part in compact_query_parts if part) or (chapter_plan[:800])
        rag_bundle = workflow_context_builder.build_typed_rag_context(
            project_id,
            rag_search_query or chapter_plan,
            fallback_max_content_length=200,
            current_chapter_number=next_chapter_number,
            category_source_text=rag_query_text or chapter_plan,
            focus_character_names=(
                chapter_generation_context.focus_character_names
                or chapter_generation_context.core_character_names
            ),
            chapter_plan=chapter_plan,
        )
        rag_character_context = rag_bundle.rag_character_context
        rag_world_context = rag_bundle.rag_world_context
        rag_previous_context = rag_bundle.rag_previous_context
        if rag_bundle.relevant_categories:
            logger.info(f"   📆 章节规划涉及体系: {rag_bundle.relevant_categories}")
        if rag_bundle.used_vector_search:
            logger.info(
                "   📚 RAG注入：人物%s条，设定%s条，前文章节%s条",
                rag_bundle.character_hits,
                rag_bundle.world_hits,
                rag_bundle.previous_hits,
            )
        if rag_bundle.used_summary_fallback:
            logger.info(
                "   📚 RAG fallback: 从设定中心直接查询%s个相关体系",
                len(rag_bundle.relevant_categories),
            )

        # 🆕 构建内容创作提示词（精简版 - 章节规划已消化大部分上下文）
        from app.services.agents.chapter_prompt_builder import ChapterPromptBuilder
        from app.services.character_state_snapshot import merge_character_state_context

        # 获取项目题材
        project_genre = project_profile.genre or ""

        builder = ChapterPromptBuilder(genre=project_genre)
        content_system_prompt = builder.build_system_prompt()
        # 闭环读取端：人物当前状态（快照）在前，运行态摘要（基线）在后
        merged_character_runtime_context = merge_character_state_context(
            chapter_generation_context.character_state_context,
            chapter_generation_context.character_prompt_context,
        )
        content_user_prompt = builder.build_user_prompt(
            next_chapter_number=next_chapter_number,
            chapter_plan=chapter_plan,
            previous_ending=previous_ending or "",
            recent_chapter_assets_summary=recent_chapter_assets_summary or "",
            rag_character_context=rag_character_context,
            rag_world_context=rag_world_context,
            selected_opening=selected_opening,
            selected_ending=selected_ending,
            position_rhythm_hint=position_rhythm_hint,
            project_quality_memory_text=project_quality_memory_text,
            current_chapter_outline=chapter_generation_context.current_chapter_outline,
            current_volume_context=chapter_generation_context.current_volume_context,
            core_character_anchor_context=chapter_generation_context.core_character_anchor_context,
            focus_character_relationship_context=chapter_generation_context.focus_character_relationship_context,
            character_runtime_context=merged_character_runtime_context,
            epic_framework_context=chapter_generation_context.epic_framework_context,
            rag_previous_context=rag_previous_context,
        )
        # 🆕 P1：写前闸门 warning 注入正文 prompt（允许生成，但进入创作提醒）
        if gate_warning_section:
            content_user_prompt = f"{content_user_prompt}\n\n{gate_warning_section}"

        # 📊 输出精简版 prompt 统计
        logger.info(f"   📉 Prompt优化（精简版）：")
        logger.info(f"      - 章节规划: {len(chapter_plan)} 字")
        logger.info(f"      - 前一章结尾: {len(previous_ending or '')} 字")
        logger.info(f"      - 最近章节连续性资产: {len(recent_chapter_assets_summary or '')} 字")
        logger.info(f"      - RAG人物: {len(rag_character_context)} 字")
        logger.info(f"      - RAG设定: {len(rag_world_context)} 字")
        logger.info(f"      - 总共: {len(content_user_prompt)} 字（移除冗余情节大纲/世界观/人物/前序章节）")

        # 🆕 使用真流式 LLM 调用（智能选择模型）
        logger.info(f"   🚀 开始调用流式 LLM 服务生成章节内容...")

        # 🆕 P2-1 场景分段生成：默认关闭（SCENE_SEGMENTATION_ENABLED，见 config 注释）。
        # 事件条目切片保证不了"一段一景"，历史三次跨项目结构事故（同场复述/整弧重启）均源于分段互盲
        chapter_draft = ""
        segments = []
        if getattr(settings, "SCENE_SEGMENTATION_ENABLED", False):
            segments = split_scene_segments(chapter_plan)
        draft_is_segmented = bool(segments)
        if segments:
            logger.info(
                f"   ✂️ 场景分段生成：{len(segments)}段，各段事件数={[len(s['events']) for s in segments]}"
            )
            try:
                segment_parts = []
                previous_segment_tail = ""
                for seg_idx, seg in enumerate(segments):
                    seg_user_prompt = builder.build_segment_user_prompt(
                        next_chapter_number=next_chapter_number,
                        chapter_plan=chapter_plan,
                        segments=segments,
                        seg_index=seg_idx,
                        previous_segment_tail=previous_segment_tail,
                        previous_ending=previous_ending or "",
                        recent_chapter_assets_summary=recent_chapter_assets_summary or "",
                        rag_character_context=rag_character_context,
                        rag_world_context=rag_world_context,
                        selected_opening=selected_opening,
                        selected_ending=selected_ending,
                        position_rhythm_hint=position_rhythm_hint,
                        project_quality_memory_text=project_quality_memory_text,
                        current_chapter_outline=chapter_generation_context.current_chapter_outline,
                        current_volume_context=chapter_generation_context.current_volume_context,
                        core_character_anchor_context=chapter_generation_context.core_character_anchor_context,
                        focus_character_relationship_context=chapter_generation_context.focus_character_relationship_context,
                        character_runtime_context=merged_character_runtime_context,
                        epic_framework_context=chapter_generation_context.epic_framework_context,
                        rag_previous_context=rag_previous_context,
                    )
                    if gate_warning_section:
                        seg_user_prompt = f"{seg_user_prompt}\n\n{gate_warning_section}"
                    seg_content = await streaming_service.generate_chapter_streaming(
                        prompt=seg_user_prompt,
                        system_prompt=content_system_prompt,
                        on_chunk=on_content_chunk,
                        temperature=0.7,
                        model=selected_content_model,  # 🔥 使用智能选择的模型
                        max_retries=max_llm_attempts,
                        require_exact_model=require_exact_model,
                        disable_thinking=True,  # 🆕 正文生成关闭思考模式，避免思考文本混入产出
                    )
                    segment_parts.append(seg_content.strip())
                    previous_segment_tail = extract_segment_tail(seg_content)
                    logger.info(
                        f"   ✓ 第{seg['index']}/{len(segments)}段完成，字数: {len(seg_content)}"
                    )
                chapter_draft = "\n\n".join(segment_parts)
                logger.info(
                    f"   ✓ 章节初稿分段合成完成（真流式 + {selected_content_model}），字数: {len(chapter_draft)}"
                )
            except Exception as seg_error:
                # 🔒 锁定模型档位下失败不可回退（回退路径模型不受控），直接终止
                if require_exact_model:
                    logger.error(f"   ❌ 锁定模型分段生成失败且禁止回退: {seg_error}")
                    raise
                logger.warning(f"   ⚠️ 分段生成失败，回退单遍生成: {seg_error}")

        try:
            if not chapter_draft:  # 分段生成未产出时走单遍生成（含分段失败的回退）
                chapter_draft = await streaming_service.generate_chapter_streaming(
                    prompt=content_user_prompt,
                    system_prompt=content_system_prompt,
                    on_chunk=on_content_chunk,
                    temperature=0.7,
                    model=selected_content_model,  # 🔥 使用智能选择的模型
                    max_retries=max_llm_attempts,
                    require_exact_model=require_exact_model,
                    disable_thinking=True,  # 🆕 正文生成关闭思考模式，避免思考文本混入产出
                )
            logger.info(f"   ✓ 章节初稿已完成（真流式 + {selected_content_model}），字数: {len(chapter_draft)}")
        except Exception as e:
            # 🆕 锁定模型档位下禁止回退到协调器（回退路径模型不受控），直接终止
            if require_exact_model:
                logger.error(f"   ❌ 锁定模型内容创作失败且禁止回退: {e}")
                raise
            logger.error(f"   ⚠️ 真流式调用失败，回退到同步调用: {e}")
            import traceback
            traceback.print_exc()  # 🔧 打印完整的异常堆栈
            # 回退到同步调用
            if hasattr(real_coordinator, 'generate_chapter_content'):
                try:
                    chapter_draft = await asyncio.to_thread(
                        real_coordinator.generate_chapter_content,
                        chapter_number=next_chapter_number,
                        chapter_plan=chapter_plan,
                        world_setting=world_setting,
                        characters=chapter_generation_context.content_character_context
                        or chapter_generation_context.character_prompt_context
                        or characters,
                        previous_ending=previous_ending,
                        target_word_count=3000,
                        previous_chapters=previous_chapters_payload,
                    )
                    logger.info(f"   ✓ 使用同步方式生成章节成功，字数: {len(chapter_draft)}")
                except Exception as sync_error:
                    logger.error(f"   ❌ 同步调用也失败: {sync_error}")
                    traceback.print_exc()
                    chapter_draft = f"第{next_chapter_number}章内容\n\n{chapter_plan}\n\n（此处为生成的章节内容）"
            else:
                logger.warning("   ⚠️ 协调器没有 generate_chapter_content 方法，使用默认模板")
                chapter_draft = f"第{next_chapter_number}章内容\n\n{chapter_plan}\n\n（此处为生成的章节内容）"

        # 🆕 截断守卫：初稿以非句末标点收尾（如 max_tokens 耗尽/流中断，结尾停在"离她二十"）
        # → 静默重试一次（no-op 回调，避免前端流式文本重复）；仍截断则保留原稿进后续流程
        if _is_likely_truncated_chapter(chapter_draft):
            logger.warning(
                f"   ⚠️ 章节初稿疑似截断（结尾 20 字: …{chapter_draft[-20:]}），静默重试一次"
            )

            async def _silent_retry_chunk(chunk: str, idx: int):
                return

            try:
                retry_draft = await streaming_service.generate_chapter_streaming(
                    prompt=content_user_prompt,
                    system_prompt=content_system_prompt,
                    on_chunk=_silent_retry_chunk,
                    temperature=0.7,
                    model=selected_content_model,
                    max_retries=max_llm_attempts,
                    require_exact_model=require_exact_model,
                    disable_thinking=True,
                )
                if retry_draft and not _is_likely_truncated_chapter(retry_draft) and len(retry_draft) > 200:
                    chapter_draft = retry_draft
                    logger.info(f"   ✓ 截断重试成功，初稿字数: {len(chapter_draft)}")
                else:
                    logger.warning("   ⚠️ 截断重试仍不完整，保留原初稿进入后续流程")
            except Exception as retry_error:
                logger.warning(f"   ⚠️ 截断重试失败，保留原初稿进入后续流程: {retry_error}")

        # 🆕 P4：空/无效/高度重复输出检测 → empty_output 熔断信号（立即暂停）并终止任务；
        # 放在额度确认前，失败时免费档 reservation 仍为 pending 可退还
        # previous_chapter_content 只在 HTTP 入口准备；后台任务从 payload 还原上一章全文。
        previous_full_text = ""
        if previous_chapters_payload:
            last_payload = previous_chapters_payload[-1] if isinstance(previous_chapters_payload, list) else None
            if isinstance(last_payload, dict):
                previous_full_text = str(last_payload.get("content") or "")
        from app.services.narrative_circuit_breaker import detect_invalid_chapter_output
        _invalid_output_detail = detect_invalid_chapter_output(chapter_draft, previous_full_text)
        if _invalid_output_detail:
            try:
                from app.services.narrative_circuit_breaker import record_generation_signal

                empty_output_meta = workflow_context_builder.load_review_meta(project_id) or {}
                record_generation_signal(
                    empty_output_meta,
                    chapter_number=next_chapter_number,
                    event="empty_output",
                    detail=_invalid_output_detail,
                )
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    review_meta=empty_output_meta,
                )
            except Exception as breaker_signal_error:
                logger.warning(f"   ⚠️ 熔断信号记录失败: {breaker_signal_error}")
            raise RuntimeError(
                f"第{next_chapter_number}章{_invalid_output_detail}，已暂停自动推进，"
                "请在创作流程页确认暂停原因后继续生成"
            )

        # 🆕 免费档：首次正文产出成功，额度转为已消耗（此后失败不退额，防主动断连刷生成）
        chapter_content_produced = True
        if quota_enabled:
            if not await get_free_quota_service().mark_consumed(task_id):
                raise RuntimeError("正文已生成，但免费额度消费状态记录失败，请稍后联系管理员")

        logger.info(f"   🌊 发送流式结束通知...")
        await ws_manager.send_stream_end(project_id, 'content', len(chapter_draft), f"第{next_chapter_number}章内容创作完成")
        # 🔔 推送阶段完成状态（生成下一章 - 步骤2）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='content',
            status='completed',
            output=chapter_draft,
            progress=50
        )
        logger.info(f"   ✓ 流式结束通知已发送")

        # 🆕 推送步骤2的 Agent 完成状态
        for agent in step2_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(step2_agents)} 个 Agent 完成状态（步骤2）")

        # 保存章节初稿到 project_settings
        logger.info(f"   💾 开始保存章节初稿到数据库...")
        workflow_context_builder.update_project_settings_fields(
            project_id,
            chapter_draft=chapter_draft,
        )
        logger.info(f"   ✓ 章节初稿已同步到数据库")

        logger.info(f"   📡 发送步骤2完成进度通知...")
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=50,
            message=f"步骤 2/4: 章节内容创作完成 ✓"
        )
        logger.info(f"   ✅ 步骤2完全完成！")

        # ==================== 步骤3：质量评审（真流式） ====================
        # 🆕 推送步骤3的 Agent 开始工作状态
        step3_agents = STEP_AGENTS['review']
        for agent in step3_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='working',
                progress=0,
                message=f'{agent["name"]}正在评审章节质量...'
            )
        logger.info(f"   📡 已发送 {len(step3_agents)} 个 Agent 开始状态（步骤3）")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=55,
            message=f"步骤 3/4: 正在进行质量评审..."
        )
        logger.info(f"   → 步骤3: 质量评审（真流式）...")

        # 🆕 发送流式开始通知
        await ws_manager.send_stream_start(project_id, 'review', f"第{next_chapter_number}章质量评审开始...")
        # 🔔 推送阶段开始状态（生成下一章 - 步骤3）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='review',
            status='active',
            progress=50
        )

        # 🆕 创建流式输出回调
        review_chunk_index = [0]

        async def on_review_chunk(chunk: str, idx: int):
            """评审流式回调"""
            review_chunk_index[0] = idx
            await ws_manager.send_stream_chunk(
                project_id=project_id,
                stage='review',
                chunk=chunk,
                chunk_index=idx,
                is_complete=False
            )

         # 🆕 获取项目题材（用于题材自适应评审）
        review_project_genre = project_profile.genre or ""
        logger.info(f"   🎯 评审使用题材: {review_project_genre or '通用'}")

        review_project_context = project_profile.to_project_context_payload()
        review_project_context.update(
            {
                "chapter_number": next_chapter_number,
                "next_chapter_number": next_chapter_number,
            }
        )

        review_report, review_meta = await _run_next_chapter_quality_review(
            project_context=review_project_context,
            chapter_draft=chapter_draft,
            chapter_plan=chapter_plan,
            plot_outline=plot_outline,
            genre=review_project_genre,
            next_chapter_number=next_chapter_number,
            recent_chapter_assets_summary=recent_chapter_assets_summary,
            streaming_service=streaming_service,
            on_review_chunk=on_review_chunk,
            real_coordinator=real_coordinator,
            enable_multi_model_review=enable_multi_model_review,
            review_model=(workflow_generation_model if require_exact_model else None),
            max_llm_attempts=max_llm_attempts,
            require_exact_model=require_exact_model,
        )

        await ws_manager.send_stream_end(project_id, 'review', len(review_report), f"第{next_chapter_number}章质量评审完成")
        # 🔔 推送阶段完成状态（生成下一章 - 步骤3）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='review',
            status='completed',
            output=review_report,
            progress=75
        )

        # 🆕 推送步骤3的 Agent 完成状态
        for agent in step3_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(step3_agents)} 个 Agent 完成状态（步骤3）")

        # 保存评审报告到 project_settings
        # 🆕 同时留存初评全文到 review_meta.initial_review：终稿编辑评审会覆盖 review_report，
        # 初评是生成侧质量的真实基线（prompt 优化的观测对象），必须可追溯
        if isinstance(review_meta, dict) and review_report:
            review_meta["initial_review"] = review_report
        workflow_context_builder.update_project_settings_fields(
            project_id,
            review_report=review_report,
            review_meta=review_meta,
        )
        logger.info(f"   ✓ 评审报告已同步到数据库")

        # 🆕 结构失败码门控：分段初稿被评审判结构断裂（同场复述/整弧重启）时，
        # 改稿没有删除原语、修不干净（历史表现为"各留一点"），直接丢弃分段初稿、
        # 单遍重生成一次并静默复评；一次封顶，防循环。程序检测（n-gram/词表）对
        # "换细节的两次发明"不可行（已用真实初稿校准验证），评审即为检测器。
        if draft_is_segmented:
            structural_regen_codes = _extract_structural_failure_codes(review_report)
            if structural_regen_codes:
                logger.warning(
                    f"   🚧 分段初稿被评审判结构失败({', '.join(sorted(structural_regen_codes))})，"
                    f"跳过改稿直接单遍重生成"
                )
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=78,
                    message=f"步骤 3/4: 检测到结构复述（{', '.join(sorted(structural_regen_codes))}），单遍重生成中...",
                )
                try:
                    async def _silent_chunk(chunk: str, idx: int):
                        return

                    regenerated_draft = await streaming_service.generate_chapter_streaming(
                        prompt=content_user_prompt,
                        system_prompt=content_system_prompt,
                        on_chunk=_silent_chunk,
                        temperature=0.7,
                        model=selected_content_model,
                        max_retries=max_llm_attempts,
                        require_exact_model=require_exact_model,
                        disable_thinking=True,
                    )
                    if regenerated_draft and len(regenerated_draft) > 200:
                        chapter_draft = regenerated_draft
                        # 单模型静默复评，保证后续迭代基于新稿与新评审
                        review_report = await _run_single_next_chapter_streaming_review(
                            chapter_draft=chapter_draft,
                            chapter_plan=chapter_plan,
                            plot_outline=plot_outline,
                            genre=review_project_genre,
                            next_chapter_number=next_chapter_number,
                            recent_chapter_assets_summary=recent_chapter_assets_summary,
                            streaming_service=streaming_service,
                            on_review_chunk=_silent_chunk,
                            real_coordinator=real_coordinator,
                            review_model=(workflow_generation_model if require_exact_model else None),
                            max_llm_attempts=max_llm_attempts,
                            require_exact_model=require_exact_model,
                        )
                        workflow_context_builder.update_project_settings_fields(
                            project_id,
                            chapter_draft=chapter_draft,
                            review_report=review_report,
                        )
                        await ws_manager.send_stage_update(
                            project_id=project_id,
                            stage='content',
                            status='completed',
                            output=chapter_draft,
                            progress=50,
                        )
                        await ws_manager.send_stage_update(
                            project_id=project_id,
                            stage='review',
                            status='completed',
                            output=review_report,
                            progress=75,
                        )
                        logger.info(
                            f"   ✅ 结构门控单遍重生成完成（{len(chapter_draft)}字），复评报告已更新"
                        )
                    else:
                        logger.warning("   ⚠️ 单遍重生成产出为空/过短，保留分段初稿进入迭代")
                except Exception as regen_error:
                    if require_exact_model:
                        logger.error(f"   ❌ 锁定模型单遍重生成失败且禁止回退: {regen_error}")
                        raise
                    logger.warning(f"   ⚠️ 单遍重生成失败，保留分段初稿进入迭代: {regen_error}")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=75,
            message=f"步骤 3/4: 质量评审完成 ✓"
        )

        # ==================== 步骤4：迭代优化（真流式） ====================
        # 🆕 推送步骤4的 Agent 开始工作状态
        step4_agents = STEP_AGENTS['iteration']
        # 注意：settings 已在模块顶部导入；函数内禁止再就地 import（会遮蔽整个函数作用域）
        try:
            pass_score_threshold = float(getattr(settings, 'ITERATION_PASS_SCORE', 8.5))
            max_rounds = int(getattr(settings, 'ITERATION_MAX_ROUNDS', 2))
        except Exception:
            pass_score_threshold = 8.5
            max_rounds = 2
        # 🆕 生成档位解析后的明确轮次优先于全局配置（免费档为 1）
        if max_iteration_rounds is not None:
            max_rounds = int(max_iteration_rounds)

        initial_review_score = _extract_iteration_review_score(review_report)
        skip_iteration_optimization = initial_review_score >= pass_score_threshold
        logger.info(
            f"   🎯 迭代优化目标分值: {pass_score_threshold} | 最大轮次: {max_rounds} | "
            f"初始评审分值: {initial_review_score:.1f}/10"
        )
        for agent in step4_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed' if skip_iteration_optimization else 'working',
                progress=100 if skip_iteration_optimization else 0,
                message=(
                    f'{agent["name"]}检测到初始评审已达标，已跳过迭代优化'
                    if skip_iteration_optimization
                    else f'{agent["name"]}正在迭代章节内容...'
                )
            )
        logger.info(
            f"   📡 已发送 {len(step4_agents)} 个 Agent "
            f"{'完成状态（步骤4-跳过优化）' if skip_iteration_optimization else '开始状态（步骤4）'}"
        )

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=80,
            message=(
                f"步骤 4/4: 初始评审已达标（{initial_review_score:.1f}/10），跳过迭代优化"
                if skip_iteration_optimization
                else "步骤 4/4: 正在迭代中，请等待..."
            )
        )
        logger.info(
            f"   → 步骤4: {'初始评审已达标，跳过迭代优化' if skip_iteration_optimization else '迭代优化（真流式）...'}"
        )

        # 🆕 发送流式开始通知
        if not skip_iteration_optimization:
            await ws_manager.send_stream_start(project_id, 'iteration', f"第{next_chapter_number}章迭代优化开始...")
            # 🔔 推送阶段开始状态（生成下一章 - 步骤4）
            await ws_manager.send_stage_update(
                project_id=project_id,
                stage='iteration',
                status='active',
                progress=75
            )

        # 🆕 创建流式输出回调
        iteration_chunk_index = [0]

        async def on_iteration_chunk(chunk: str, idx: int):
            """迭代优化流式回调"""
            iteration_chunk_index[0] = idx
            await ws_manager.send_stream_chunk(
                project_id=project_id,
                stage='iteration',
                chunk=chunk,
                chunk_index=idx,
                is_complete=False
            )

        # 🆕 构建迭代优化提示词
        iteration_coordination_system_prompt = get_iteration_coordination_system_prompt()
        iteration_system_prompt = get_iteration_revision_system_prompt()

        # 🆕 标记迭代循环是否正常执行完毕（跳过迭代/异常回退时保持 False）：
        # 仅正常执行后补跑"终稿编辑评审"（那两条路径终稿=初稿，初评已配套且为全量格式）
        iteration_loop_ran = False
        # 🆕 迭代过程留痕：每轮修订稿与配套复评的汇总，章节保存后写入版本历史/评审表
        iteration_round_records: List[Dict[str, Any]] = []

        # 🆕 使用迭代优化（max改稿 + R1打分循环,达到阈值后再输出）
        try:
            # 🎯 根据实际输入长度动态选择改稿模型
            def estimate_tokens(text: str) -> int:
                """估算文本的 token 数（中文按1.3倍字符数估算）"""
                return _estimate_tokens_by_chars(text)
            
            def select_model_by_length(chapter_content: str, reviews: str) -> str:
                """根据输入长度智能选择模型
                
                Args:
                    chapter_content: 当前章节内容
                    reviews: 累积的评审意见
                
                Returns:
                    选择的模型名称
                """
                # 估算总输入长度（章节 + 评审 + 系统提示词 + 用户提示词模板）
                if workflow_generation_model:
                    return workflow_generation_model
                chapter_tokens = estimate_tokens(chapter_content)
                reviews_tokens = estimate_tokens(reviews)
                prompt_overhead = 500  # 系统提示词和用户提示词模板的开销
                
                total_tokens = chapter_tokens + reviews_tokens + prompt_overhead
                selected_model, _ = _select_text_model_by_input_tokens(total_tokens)
                return selected_model
            
            # 初始评审意见
            initial_reviews = review_report or ""
            
            # 选择初始模型
            selected_revision_model = select_model_by_length(chapter_draft, initial_reviews)
            resolved_revision_model = resolve_model_for_task(None, selected_revision_model) or selected_revision_model
            logger.info(f"   🤖 迭代优化改稿模型: {resolved_revision_model} (requested={selected_revision_model})")
            logger.info(f"      - 章节长度: {len(chapter_draft)} 字 ≈ {estimate_tokens(chapter_draft)} tokens")
            logger.info(f"      - 初始评审: {len(initial_reviews)} 字 ≈ {estimate_tokens(initial_reviews)} tokens")
            logger.info(f"      - 预估总计: ≈ {estimate_tokens(chapter_draft) + estimate_tokens(initial_reviews) + 500} tokens")
            logger.info(f"      - {selected_revision_model} 安全输入预算: ≈ {_get_safe_input_token_budget(selected_revision_model)} tokens")
            
            # 🆕 广播步骤4改稿模型（首轮改稿前广播一次）
            if not skip_iteration_optimization:
                await ws_manager.send_model_used(
                    project_id=project_id,
                    stage='iteration',
                    model=resolved_revision_model,
                    extra={
                        "step": "iteration_revision",
                        "chapter_number": next_chapter_number,
                        "requested_model": selected_revision_model,
                    }
                )

            effective_rounds = 0 if skip_iteration_optimization else max_rounds

            # 初始版本与评审
            current_version = chapter_draft
            current_review = review_report
            final_version = current_version
            # 🆕 终稿配套评审：始终与最终输出版本同源的评审报告（初始为初稿评审）
            final_review = review_report
            reached_pass = skip_iteration_optimization
            best_version = current_version
            best_review = current_review
            latest_revised_version = ""
            # 初始化最佳分数为已有评审的分数（若无法提取则为0）
            best_score = _extract_iteration_review_score(current_review)
            # 🆕 累积所有轮次的评审意见，作为改稿参考
            all_reviews = [f"【第0轮评审（初稿）】\n{current_review}"]

            # 🆕 P1-1 失败码修订路由：从初始评审解析失败码，判定轻/重修订模式
            initial_failure_codes = extract_failure_codes(current_review)
            revision_mode, revision_mode_hint = resolve_revision_mode(initial_failure_codes)
            # 🆕 P2-2 T1 修复相位：失败码直检命中案例库，注入机制修复指引
            repair_hints_text = build_repair_hints(initial_failure_codes)
            if revision_mode:
                logger.info(
                    f"   🧭 初始评审失败码路由: 模式={revision_mode}, 码数={len(initial_failure_codes)} "
                    f"({', '.join(fc['code'] for fc in initial_failure_codes[:5])})"
                )

            if skip_iteration_optimization:
                logger.info(
                    f"   🎉 初始评审已达标（{initial_review_score:.1f}/10 >= {pass_score_threshold:.1f}/10），"
                    f"跳过后续迭代优化"
                )

            # 不透出中间稿的流式回调（前端只看最终稿）
            async def noop_chunk(chunk: str, idx: int):
                return

            for round_idx in range(1, effective_rounds + 1):
                logger.info(f"   🔄 迭代优化第{round_idx}/{max_rounds}轮：开始改稿")
                # 🆕 推送迭代轮次信息到前端
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=min(95, 70 + round_idx * 5),
                    message=f"步骤 4/4: 第{round_idx}/{effective_rounds}轮，迭代协调官正在整理修改计划..."
                )
                # 第N轮：根据所有历史评审意见进行改稿
                # 🆕 将所有评审意见汇总，按轮次展示
                all_reviews_text = "\n\n".join(all_reviews)
                
                # 🎯 每轮动态选择模型（因为评审意见在累积）
                current_model = select_model_by_length(current_version, all_reviews_text)
                if current_model != selected_revision_model:
                    selected_revision_model = current_model
                    resolved_revision_model = (
                        resolve_model_for_task(None, selected_revision_model) or selected_revision_model
                    )
                    logger.info(
                        f"   🔄 第{round_idx}轮模型切换: {resolved_revision_model} "
                        f"(requested={selected_revision_model})"
                    )
                    logger.info(f"      - 当前章节: {len(current_version)} 字 ≈ {estimate_tokens(current_version)} tokens")
                    logger.info(f"      - 累积评审: {len(all_reviews_text)} 字 ≈ {estimate_tokens(all_reviews_text)} tokens")
                    logger.info(f"      - 预估总计: ≈ {estimate_tokens(current_version) + estimate_tokens(all_reviews_text) + 500} tokens")
                    # 广播模型切换
                    await ws_manager.send_model_used(
                        project_id=project_id,
                        stage='iteration',
                        model=resolved_revision_model,
                        extra={
                            "step": f"iteration_round_{round_idx}",
                            "reason": "context_length_increase",
                            "requested_model": selected_revision_model,
                        }
                    )
                iteration_plan_text = ""
                try:
                    coordination_user_prompt = build_iteration_coordination_user_prompt(
                        chapter_number=next_chapter_number,
                        chapter_content=current_version,
                        review_text=all_reviews_text,
                        recent_chapter_assets_summary=recent_chapter_assets_summary,
                        include_history_hint=True,
                    )
                    iteration_plan_text = await streaming_service.generate_chapter_streaming(
                        prompt=coordination_user_prompt,
                        system_prompt=iteration_coordination_system_prompt,
                        on_chunk=noop_chunk,
                        temperature=0.3,
                        model=selected_revision_model,
                        max_retries=max_llm_attempts,
                        require_exact_model=require_exact_model,
                        disable_thinking=True,
                    )
                    logger.info(f"   ✓ 第{round_idx}轮迭代计划生成完成，长度: {len(iteration_plan_text)}")
                except Exception as coordination_error:
                    # 🆕 锁定模型档位下模型被重路由等失败不可忽略，直接终止
                    if require_exact_model:
                        logger.error(f"   ❌ 锁定模型迭代计划失败且禁止回退: {coordination_error}")
                        raise
                    logger.warning(
                        f"   ⚠️ 第{round_idx}轮迭代计划生成失败，将直接依据评审意见改稿: {coordination_error}"
                    )

                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=min(95, 71 + round_idx * 5),
                    message=f"步骤 4/4: 第{round_idx}/{effective_rounds}轮，内容修订师正在执行修改..."
                )
                iteration_user_prompt_round = _build_iteration_revision_prompt(
                    chapter_number=next_chapter_number,
                    chapter_content=current_version,
                    review_text=all_reviews_text,
                    iteration_plan=iteration_plan_text,
                    recent_chapter_assets_summary=recent_chapter_assets_summary,
                    include_history_hint=True,
                    revision_mode_hint=revision_mode_hint,
                    repair_hints=repair_hints_text,
                    chapter_plan=chapter_plan,
                    current_chapter_outline=chapter_generation_context.current_chapter_outline,
                )

                # 仅在最后一轮向前端流式输出正文；前几轮不推送正文
                on_chunk_cb = noop_chunk
                revised_version = await streaming_service.generate_chapter_streaming(
                    prompt=iteration_user_prompt_round,
                    system_prompt=iteration_system_prompt,
                    on_chunk=on_chunk_cb,
                    temperature=0.7,
                    model=selected_revision_model,
                    max_retries=max_llm_attempts,
                    require_exact_model=require_exact_model,
                    disable_thinking=True,
                )
                latest_revised_version = revised_version
                logger.info(f"   ✓ 第{round_idx}轮改稿完成（{selected_revision_model}），字数: {len(revised_version)}")

                # 🆕 截断守卫：改稿以非句末标点收尾 → 静默重试一次；仍截断保留原改稿
                if _is_likely_truncated_chapter(revised_version):
                    logger.warning(
                        f"   ⚠️ 第{round_idx}轮改稿疑似截断（结尾 20 字: …{revised_version[-20:]}），静默重试一次"
                    )
                    try:
                        retry_revised = await streaming_service.generate_chapter_streaming(
                            prompt=iteration_user_prompt_round,
                            system_prompt=iteration_system_prompt,
                            on_chunk=noop_chunk,
                            temperature=0.7,
                            model=selected_revision_model,
                            max_retries=max_llm_attempts,
                            require_exact_model=require_exact_model,
                            disable_thinking=True,
                        )
                        if retry_revised and not _is_likely_truncated_chapter(retry_revised) and len(retry_revised) > 200:
                            revised_version = retry_revised
                            latest_revised_version = revised_version
                            logger.info(f"   ✓ 截断重试成功，第{round_idx}轮改稿字数: {len(revised_version)}")
                        else:
                            logger.warning(f"   ⚠️ 第{round_idx}轮改稿截断重试仍不完整，保留原改稿")
                    except Exception as retry_error:
                        logger.warning(f"   ⚠️ 第{round_idx}轮改稿截断重试失败，保留原改稿: {retry_error}")

                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=min(95, 72 + round_idx * 5),
                    message=f"步骤 4/4: 第{round_idx}轮改稿完成，正在复评..."
                )

                # 评审打分（R1）
                review_system_prompt_loop = get_iteration_loop_review_system_prompt()
                review_user_prompt_loop = _build_iteration_review_prompt(
                    chapter_number=next_chapter_number,
                    chapter_content=revised_version,
                    chapter_plan=chapter_plan,
                    review_text=all_reviews_text,
                    iteration_plan=iteration_plan_text,
                    recent_chapter_assets_summary=recent_chapter_assets_summary,
                    previous_version=current_version,
                )
                new_review_report = await streaming_service.generate_chapter_streaming(
                    prompt=review_user_prompt_loop,
                    system_prompt=review_system_prompt_loop,
                    on_chunk=noop_chunk,  # 评分不流式推送正文
                    temperature=0.3,
                    model=(workflow_generation_model if require_exact_model else None),
                    task_type="review",
                    max_retries=max_llm_attempts,
                    require_exact_model=require_exact_model,
                    disable_thinking=True,
                )
                score = _extract_iteration_review_score(new_review_report)
                has_unresolved_required_items = _iteration_review_has_unresolved_required_items(new_review_report)
                logger.info(f"   🧮 第{round_idx}轮评分：{score:.1f}/10")
                # 🆕 P1-1：复评后按最新失败码刷新修订模式（轻码→局部修订，重码→实质性重写）
                round_failure_codes = extract_failure_codes(new_review_report)
                revision_mode, revision_mode_hint = resolve_revision_mode(round_failure_codes)
                # 🆕 P2-2 T1：同步刷新机制修复指引，下一轮改稿使用最新失败码命中的修复机制
                repair_hints_text = build_repair_hints(round_failure_codes)
                if revision_mode:
                    logger.info(
                        f"   🧭 第{round_idx}轮失败码路由刷新: 模式={revision_mode}, "
                        f"码数={len(round_failure_codes)}"
                    )
                if review_has_unsourced_new_fact(new_review_report):
                    logger.warning(
                        f"   🕳️ 第{round_idx}轮修订靠无出处新事实应付必改（NEW_FACT_UNSOURCED|HIGH），判为未闭环"
                    )
                if has_unresolved_required_items:
                    logger.info("   🚧 第%s轮仍有必改项未执行，本轮不作为可采用版本", round_idx)
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=min(95, 80 + round_idx * 3),
                    message=f"步骤 4/4: 正在迭代中（第{round_idx}轮评分 {score:.1f}/10）..."
                )
                
                # 🆕 将本轮评审意见加入历史记录
                all_reviews.append(f"【第{round_idx}轮评审】\n{new_review_report}")

                # 🆕 记录最高评分版本
                previous_best_score = best_score
                score_improved = (not has_unresolved_required_items) and score >= previous_best_score
                if score_improved:
                    best_score = score
                    best_version = revised_version
                    best_review = new_review_report

                # 🆕 本轮修订稿与配套复评进版本历史（评分、剩余失败码、是否被采用写进备注）
                iteration_round_records.append({
                    "round": round_idx,
                    "content": revised_version,
                    "review": new_review_report,
                    "score": score,
                    "failure_codes": [code.get("code") for code in round_failure_codes],
                    "adopted": bool(score_improved),
                })

                # 判定是否达标（🆕 结构失败码残留为硬停止条件：改稿修不掉结构断裂，不允许判达标）
                round_structural_codes = _extract_structural_failure_codes(new_review_report)
                if round_structural_codes:
                    logger.warning(
                        f"   🚧 第{round_idx}轮复评仍有结构失败码 {sorted(round_structural_codes)}，本轮不判达标"
                    )
                if (
                    score >= pass_score_threshold
                    and not has_unresolved_required_items
                    and not round_structural_codes
                ):
                    final_version = revised_version
                    current_review = new_review_report
                    reached_pass = True
                    logger.info(f"   🎉 达到目标分值 {pass_score_threshold}，停止迭代")
                    break
                else:
                    # 只有评分不下降时才把本轮改稿作为下一轮基底，避免低分稿继续污染后续迭代。
                    if score_improved:
                        current_version = revised_version
                    else:
                        logger.info(
                            "   "
                            + _describe_iteration_round_rejection(
                                round_idx=round_idx,
                                score=score,
                                previous_best_score=previous_best_score,
                                has_unresolved_required_items=has_unresolved_required_items,
                            )
                        )
                        current_version = best_version
                    current_review = new_review_report
                    final_version = best_version

            if not reached_pass:
                logger.info(f"   ⚠️ 未达标，输出最高评分版本：{best_score:.1f}/10")
                final_version = _select_iteration_fallback_version(
                    initial_version=chapter_draft,
                    latest_revised_version=latest_revised_version,
                    best_version=best_version,
                )
                # 输出为最高分版本 → 配套评审取该版本当轮的评审
                final_review = best_review
            else:
                # 达标（或跳过迭代）：current_review 即与 final_version 配套的评审
                final_review = current_review
            iteration_loop_ran = True
            logger.info(f"   ✅ 迭代优化结束，输出最终版本，长度: {len(final_version)}")
        except Exception as e:
            # 🆕 锁定模型档位下禁止回退到协调器（回退路径模型不受控），直接终止
            if require_exact_model:
                logger.error(f"   ❌ 锁定模型迭代优化失败且禁止回退: {e}")
                raise
            logger.error(f"   ⚠️ 真流式迭代优化失败，回退到同步调用: {e}")
            # 回退路径输出初稿 → 配套评审回到初评
            final_review = review_report
            # 回退到同步调用
            if hasattr(real_coordinator, 'optimize_chapter'):
                final_version = await asyncio.to_thread(
                    real_coordinator.optimize_chapter,
                    chapter_draft=chapter_draft,
                    review_report=review_report
                )
            else:
                final_version = chapter_draft
        # 🆕 清理输出内容，移除额外的评审话语
        def clean_final_output(content: str) -> str:
            """清理最终输出，移除可能的额外评审话语"""
            if not content:
                return content
            lines = content.split('\n')
            cleaned_lines = []
            skip_section = False
            for line in lines:
                line_lower = line.lower().strip()
                # 跳过评审相关的段落
                if any(keyword in line_lower for keyword in [
                    '优化说明', '修改说明', '评审', '改进建议', '优化要点',
                    '以下是优化后', '根据评审意见', '主要修改', '优化内容'
                ]):
                    skip_section = True
                    continue
                if skip_section and line.strip() == '':
                    skip_section = False
                    continue
                if not skip_section:
                    cleaned_lines.append(line)
            return '\n'.join(cleaned_lines).strip()

        final_version = clean_final_output(final_version)

        # 🆕 安全保护：如果优化后字数远小于原稿，则认为可能被压缩成摘要，回退为原始章节内容
        original_len = len(chapter_draft or "")
        optimized_len = len(final_version or "")
        from app.services.chapter_structure_guard import should_revert_short_revision
        # 注意：extract_failure_codes 已在模块顶部导入；此处若再就地 import，
        # 会将整个函数作用域内的该名字绑定为局部变量，导致循环前的首次调用抛 UnboundLocalError
        structural_codes = {"STRUCT_BROKEN", "STALL_NO_PROGRESS"}
        has_structural_failure = any(
            str(fc.get("code") or "") in structural_codes
            for fc in extract_failure_codes(review_report or "")
        )
        if should_revert_short_revision(
            chapter_draft,
            final_version,
            has_structural_failure=has_structural_failure,
        ):
            logger.warning(
                f"   ?? ?????({optimized_len}) ?????({original_len})?????????????????????"
            )
            final_version = chapter_draft
            # 回滚为初稿 → 配套评审回到初评；初评已是对该文本的全量评审，无需再跑终稿编辑评审
            final_review = review_report
            iteration_loop_ran = False
        elif original_len >= 500 and optimized_len > 0 and optimized_len < original_len * 0.6:
            logger.info(
                f"   ? ?????????{optimized_len}/{original_len}???????"
            )


        if not skip_iteration_optimization:
            for chunk in _split_stream_text(final_version):
                next_chunk_index = iteration_chunk_index[0] + 1
                await on_iteration_chunk(chunk, next_chunk_index)
            await ws_manager.send_stream_end(project_id, 'iteration', len(final_version), f"第{next_chapter_number}章迭代优化完成")
        # 🔔 推送阶段完成状态（生成下一章 - 步骤4）
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage='iteration',
            status='completed',
            output=final_version,
            progress=100
        )

        # 🆕 推送步骤4的 Agent 完成状态
        for agent in step4_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(step4_agents)} 个 Agent 完成状态（步骤4）")

        # 🆕 终稿编辑评审：迭代循环正常执行后，以初评同款全量格式（六维分析+必改/建议/可选+亮点）
        # 对最终版本重新评审一次，作为用户人工精修的参考——循环复评的核验表服务于机器验收
        # （判通过/失败码/未执行检测），不适合编辑参考；且通过的章节此前没有任何"本章可精修项"指引。
        # 展示增强类调用：失败仅降级为保留循环复评，不得让已生成完毕的章节整体失败。
        if iteration_loop_ran and final_version and len(final_version) > 200:
            try:
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=93,
                    message="步骤 4/4: 正在生成终稿编辑评审（人工精修参考）...",
                )

                async def _editorial_review_chunk(chunk: str, idx: int):
                    return

                editorial_review = await _run_single_next_chapter_streaming_review(
                    chapter_draft=final_version,
                    chapter_plan=chapter_plan,
                    plot_outline=plot_outline,
                    genre=review_project_genre,
                    next_chapter_number=next_chapter_number,
                    recent_chapter_assets_summary=recent_chapter_assets_summary,
                    streaming_service=streaming_service,
                    on_review_chunk=_editorial_review_chunk,
                    real_coordinator=real_coordinator,
                    review_model=(workflow_generation_model if require_exact_model else None),
                    max_llm_attempts=max_llm_attempts,
                    require_exact_model=require_exact_model,
                )
                if editorial_review and len(editorial_review) > 100:
                    final_review = editorial_review
                    logger.info(
                        f"   ✅ 终稿编辑评审完成（人工精修参考），长度: {len(editorial_review)}"
                    )
                else:
                    logger.warning("   ⚠️ 终稿编辑评审产出为空/过短，保留循环复评作为终稿评审")
            except Exception as editorial_error:
                logger.warning(
                    f"   ⚠️ 终稿编辑评审失败，保留循环复评作为终稿评审: {editorial_error}"
                )

        # 保存最终版本到 project_settings
        # 🆕 同时以"终稿配套评审"覆盖 review_report：迭代正常执行后为终稿编辑评审（人工精修参考，
        # 全量六维格式）；循环复评（核验表）仅服务于机器验收。final_review 与 final_version 严格同版本配对
        workflow_context_builder.update_project_settings_fields(
            project_id,
            final_version=final_version,
            review_report=final_review,
        )
        logger.info(
            f"   ✓ 最终版本已同步到数据库（评审报告已更新为终稿配套评审，长度: {len(final_review or '')}）"
        )

        # 🆕 实时刷新前端评审面板：终稿评审替换初评显示（前端 stage_update 处理器会更新评审内容状态）
        if not skip_iteration_optimization and final_review and final_review != review_report:
            await ws_manager.send_stage_update(
                project_id=project_id,
                stage='review',
                status='completed',
                output=final_review,
                progress=75
            )
            logger.info(f"   📡 已推送终稿评审到前端评审面板")

        # 🆕 P1-2/P1-3：沉淀项目级质量记忆与伏笔账本（写入 review_meta，供后续章节注入）
        try:
            latest_review_meta = workflow_context_builder.load_review_meta(project_id) or {}
            # 🆕 验收硬停止标记：最终评审仍含结构失败码时，照常输出最高分版本
            # （章节不能空），但不允许静默当"完成"——标记 review_meta 并向用户透出警告
            final_structural_codes = _extract_structural_failure_codes(
                final_review or review_report or ""
            )
            if final_structural_codes:
                latest_review_meta["structural_failure_unresolved"] = True
                latest_review_meta["structural_failure_codes"] = sorted(final_structural_codes)
                logger.warning(
                    f"   🚧 验收硬停止：最终评审仍含结构失败码 {sorted(final_structural_codes)}，"
                    f"已标记 review_meta.structural_failure_unresolved，请人工复核本章"
                )
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=95,
                    message=f"⚠️ 本章最终稿仍存在结构问题（{', '.join(sorted(final_structural_codes))}），已标记待人工复核",
                )
            # 质量记忆：从最终评审提取未解决问题（达标章通常无剩余问题，未达标章自动沉淀）
            unresolved_issues = extract_unresolved_issues(final_review or review_report or "")
            if unresolved_issues:
                update_quality_memory(latest_review_meta, next_chapter_number, unresolved_issues)
            # 伏笔账本：登记本章伏笔埋设/回收
            register_foreshadowing(
                latest_review_meta,
                next_chapter_number,
                chapter_plan,
                chapter_position=extract_chapter_position(chapter_plan),
            )
            # 🆕 P4：本章正常完成，重置熔断的闸门连续计数
            try:
                from app.services.narrative_circuit_breaker import record_generation_signal

                record_generation_signal(
                    latest_review_meta,
                    chapter_number=next_chapter_number,
                    event="generation_success",
                )
            except Exception as breaker_signal_error:
                logger.warning(f"   ⚠️ 熔断信号记录失败: {breaker_signal_error}")
            workflow_context_builder.update_project_settings_fields(
                project_id,
                review_meta=latest_review_meta,
            )
            if unresolved_issues:
                logger.info(
                    f"   🧠 已沉淀 {len(unresolved_issues)} 条未解决问题到项目级质量记忆"
                )
        except Exception as memory_error:
            logger.warning(f"   ⚠️ 质量记忆/伏笔账本沉淀失败（不影响本章产出）: {memory_error}")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=90,
            message=f"步骤 4/4: 正在保存章节..."
        )

        # ==================== 保存章节 ====================
        # 生成章节标题
        def convert_number_to_chinese(num: int) -> str:
            chinese_nums = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
            if num <= 10:
                return chinese_nums[num]
            elif num < 20:
                return '十' + chinese_nums[num - 10]
            elif num < 100:
                tens = num // 10
                ones = num % 10
                return chinese_nums[tens] + '十' + (chinese_nums[ones] if ones > 0 else '')
            else:
                return str(num)

        try:
            lines = final_version.split('\n')
            potential_title = None
            for line in lines[:5]:
                line = line.strip()
                if line and ('第' in line or '章' in line) and len(line) < 30:
                    potential_title = line
                    break

            if potential_title:
                chapter_title = potential_title
            else:
                chinese_num = convert_number_to_chinese(next_chapter_number)
                chapter_title = f"第{chinese_num}章 未命名"
        except Exception:
            chinese_num = convert_number_to_chinese(next_chapter_number)
            chapter_title = f"第{chinese_num}章 未命名"

        logger.info(f"   ✓ 章节标题: {chapter_title}")

        new_chapter = _create_generated_chapter(
            db,
            project_id=project_id,
            chapter_number=next_chapter_number,
            title=chapter_title,
            content=final_version,
        )
        new_chapter_id = new_chapter.id

        logger.info(f"   ✅ 章节已保存: id={new_chapter_id}")

        # 🆕 迭代过程落库：初稿与每轮修订稿进版本历史，初评/每轮复评/终稿评审进评审表
        try:
            from app.services.workflow_revision_store import record_iteration_history

            record_iteration_history(
                db,
                chapter_id=new_chapter_id,
                initial_content=chapter_draft,
                initial_review=review_report,
                initial_score=initial_review_score,
                rounds=iteration_round_records,
                final_review=final_review,
                final_score=_extract_iteration_review_score(final_review),
            )
        except Exception as revision_store_error:
            logger.warning(
                f"   ⚠️ 迭代过程落库失败（不影响本章产出）: {revision_store_error}"
            )
        
        # 🆕 内容进化器：记录生成数据（5%采样 + 隐式反馈收集）
        try:
            from app.services.content_evolution import get_engine, GenerationStage
            
            evolution_engine = get_engine()
            await evolution_engine.on_generation_complete(
                project_id=project_id,
                chapter_id=new_chapter_id,
                genre=plan_project_genre or "通用",
                stage=GenerationStage.CONTENT,
                module_name="chapter_content",
                version_id="default",  # 暂用默认版本，后续可扩展为变体检测
                is_variant=False,
                content=final_version,
                ai_score=None,  # AI评分在评审阶段已完成
            )
            logger.info(f"   📊 内容进化器：已记录生成数据")
        except Exception as evo_err:
            logger.debug(f"   ⚠️ 内容进化器记录失败（不影响主流程）: {evo_err}")
        
        # 🚨 已移除正则快速提取，统一使用后台AI提取服务
        # 见: start_chapter_post_save_task -> chapter_post_save.py -> unified_extraction.py
        # 所有设定提取现在都经过AI处理，生成高质量描述

        # 🆕 设定回流（自动合并高置信候选 + 一致性检测）已移至后台任务内执行：
        # 原先此处同步执行 auto_merge 早于后台提取，本章新提取的候选要等下一章才被合并；
        # 现在由 process_chapter_post_save 在提取落库后立即回流（auto_merge_settings=True）。

        # ✅ 章节保存完成，立即更新任务状态并推送完成事件
        # 注意：摘要生成和统一提取将在后台异步执行，不阻塞主流程
        update_query = text("""
            UPDATE generation_history
            SET status = :status, completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        db.execute(update_query, {
            "status": "completed",
            "completed_at": utc_now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        # 发送完成事件（章节已保存）
        await ws_manager.send_task_complete(
            project_id=project_id,
            task_id=task_id,
            result={
                "chapter": {
                    "id": new_chapter_id,
                    "chapter_number": next_chapter_number,
                    "title": chapter_title,
                    "word_count": len(final_version),
                }
            }
        )

        logger.info(f"✅ 章节生成任务完成: {task_id}, 第{next_chapter_number}章已保存")
        
        # 🚀 启动后台任务（统一提取 + 摘要生成）- 异步执行，不等待结果
        try:
            from app.services.chapter_post_save import start_chapter_post_save_task
            
            logger.info(f"🚀 启动后台任务：统一提取 + 摘要生成（异步）...")
            
            # 启动后台异步任务（不等待完成）
            # 🆕 注意：generate_summary=True，仅工作流场景生成摘要
            start_chapter_post_save_task(
                chapter_id=new_chapter_id,
                chapter_title=chapter_title,
                chapter_content=final_version,
                chapter_number=next_chapter_number,
                project_id=project_id,
                generate_summary=True,  # 🆕 工作流场景需要生成摘要
                # 🆕 免费档后置提取/摘要同样锁定模型；标准档传 None 保持现有行为
                post_processing_model=(workflow_generation_model if require_exact_model else None),
                # 🆕 提取完成后执行设定回流：合并高置信候选 + 一致性检测（修复 P0-2 时序倒挂）
                chapter_plan=chapter_plan or "",
                auto_merge_settings=True,
            )
            
            logger.info(f"✅ 后台任务已启动，将在后台异步执行")
            
        except Exception as e:
            logger.warning(f"⚠️ 启动后台任务失败（不影响章节保存）: {e}")
            import traceback
            traceback.print_exc()

    except Exception as e:
        logger.error(f"❌ 后台任务失败: {task_id}, 错误: {e}")
        import traceback
        traceback.print_exc()

        # 🆕 免费档：正文产出前失败退还额度（reservation 仍为 pending 才退，幂等）
        if quota_enabled and not locals().get("chapter_content_produced", False):
            await get_free_quota_service().refund_if_pending(task_id)

        # 更新任务状态为失败
        try:
            update_query = text("""
                UPDATE generation_history
                SET status = :status, error = :error, completed_at = :completed_at
                WHERE task_id = :task_id
            """)
            db.execute(update_query, {
                "status": "failed",
                "error": str(e),
                "completed_at": utc_now().isoformat(),
                "task_id": task_id
            })
            db.commit()
        except Exception as update_error:
            logger.warning(f"⚠️ 更新任务失败状态失败: {update_error}")

        # 发送错误事件
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e)
        )
    finally:
        mark_generate_next_chapter_task_inactive(task_id, project_id)
        if lock_heartbeat_task is not None:
            lock_heartbeat_task.cancel()
            try:
                await lock_heartbeat_task
            except asyncio.CancelledError:
                pass
            except Exception as heartbeat_error:
                logger.error("项目 %s 生成锁心跳已失败: %s", project_id, heartbeat_error)
        # 🆕 任务结束（成功/失败）释放项目生成锁（release 内部按 token 校验，幂等且不抛异常）
        if lock_handle is not None:
            released = await get_generation_lock_service().release(lock_handle)
            logger.info(f"   🔓 项目 {project_id} 生成锁释放{'成功' if released else '失败（由 TTL 兜底）'}")
        db.close()

