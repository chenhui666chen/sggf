"""Workflow API module."""
import logging
import asyncio
import os
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
from app.services.auto_system_detector import auto_create_system_collections

logger = logging.getLogger(__name__)

_active_generate_next_chapter_task_ids: set[str] = set()


def mark_generate_next_chapter_task_active(task_id: str) -> None:
    _active_generate_next_chapter_task_ids.add(str(task_id))


def mark_generate_next_chapter_task_inactive(task_id: str) -> None:
    _active_generate_next_chapter_task_ids.discard(str(task_id))


def is_generate_next_chapter_task_active(task_id: str) -> bool:
    return str(task_id) in _active_generate_next_chapter_task_ids


def _select_iteration_fallback_version(
    *,
    initial_version: str,
    latest_revised_version: str,
    best_version: str,
) -> str:
    return best_version or initial_version or latest_revised_version


def _iteration_review_has_unresolved_required_items(review_text: str) -> bool:
    """检测复评核验表中是否仍有必改项未执行。"""
    for raw_line in str(review_text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        source = cells[0].upper()
        status_text = cells[1]
        is_required_item = "MUST" in source or "必改" in cells[0]
        if is_required_item and "未执行" in status_text:
            return True
    return False


def _split_stream_text(text: str, *, chunk_size: int = 1200) -> list[str]:
    if not text:
        return []
    safe_chunk_size = max(1, int(chunk_size or 1))
    return [text[index:index + safe_chunk_size] for index in range(0, len(text), safe_chunk_size)]


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

【前一章结尾】
{sections["previous_ending"]}
{sections["climax_instruction"]}

【输出要求】
请为第{next_chapter_number}章制定创作计划，必须包含：
## 1. 本章定位
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

【约束】
- 确保与整本书情节大纲、前文剧情和结构化记忆保持一致
- 如提供当前章节精确细纲，必须优先落实场景目标、关键事件、人物出场、冲突推进、结尾钩子和伏笔
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
from app.api.v1.workflow.model_selection import resolve_workflow_generation_model
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
    import asyncio
    from sqlalchemy import text

    logger = logging.getLogger("uvicorn.error")

    try:
        logger.info(f"📍 开始生成下一章（异步模式），项目ID: {project_id}")
        try:
            workflow_generation_model = resolve_workflow_generation_model(
                request.workflow_generation_model if request else None
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
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
        query = text("""
            SELECT id, chapter_number, title, content, summary
            FROM chapters
            WHERE project_id = :project_id
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

        # 4. 提取前一章结尾（用于衔接）
        previous_ending = ""
        if existing_chapters:
            previous_chapter = existing_chapters[-1]
            if previous_chapter[3]:  # 有内容
                # 提取最后500个字符
                content = previous_chapter[3]
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

        # 6. 生成任务ID并创建任务记录
        task_id = str(uuid.uuid4())
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
        mark_generate_next_chapter_task_active(task_id)
        asyncio.create_task(
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
            )
        )
        logger.info(f"   🚀 后台任务已启动")

        # 8. 立即返回响应
        return {
            "task_id": task_id,
            "status": "running",
            "message": f"已开始生成第{next_chapter_number}章",
            "next_chapter_number": next_chapter_number,
            "workflow_generation_model": workflow_generation_model,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 创建生成下一章任务失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


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
):
    """
    后台执行生成下一章任务（真流式版本）

    执行四个步骤：
    1. 章节规划（0-25%）- 使用 asyncio.to_thread 避免阻塞
    2. 内容创作（25-50%）- 使用真流式 LLM 调用
    3. 质量评审（50-75%）- 使用真流式 LLM 调用
    4. 迭代优化（75-100%）- 使用真流式 LLM 调用
    """
    from sqlalchemy import text
    from app.db.base import SessionLocal

    logger = logging.getLogger("uvicorn.error")
    logger.info(f"🚀 开始执行后台任务: {task_id}, 生成第{next_chapter_number}章")
    mark_generate_next_chapter_task_active(task_id)

    # 获取流式服务
    streaming_service = get_streaming_service()

    # 创建独立的数据库会话
    db = SessionLocal()

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

        # 🆕 获取高潮章节指示（使用模块化函数）
        climax_instruction = get_climax_instruction(next_chapter_number)
        
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
            )
            logger.info(f"   ✓ 章节规划已完成（真流式 + {selected_plan_model}），长度: {len(chapter_plan)}")
        except Exception as e:
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

        logger.info(f"   📐 开始匹配场景类型...")

        # 🆕 开头/结尾方式定义（与 agent_coordinator 保持同步）
        opening_styles = {
            "对话开头": ("对话开头", "直接进入冲突或紧张场景，用对话抽出矛盾", ""),
            "动作开头": ("动作开头", "从正在发生的动态事件开始，制造紧迫感", ""),
            "悬念开头": ("悬念开头", "抛出问题或异常现象，引发读者好奇，创造独特的开场", ""),
            "场景开头": ("场景开头", "通过环境氛围描写快速建立情境，融入题材特色", ""),
            "反转开头": ("反转开头", "与上章结尾形成对比或反差，制造意外效果", ""),
            "内心独白开头": ("内心独白开头", "从人物内心思绪入手，展现心理冲突或决策过程", ""),
            "回忆插入开头": ("回忆插入开头", "通过回忆或闪回提供关键背景，丰富当前情节", ""),
            "疯狂开头": ("疯狂开头", "从激烈冲突或混乱场面开始，立即抽住读者注意力", ""),
            "对比开头": ("对比开头", "通过前后对比或境遇差异，强化情绪冲击", ""),
            "时间跳跃开头": ("时间跳跃开头", "直接跳转到事件后的关键时刻，略过过程增加节奏", ""),
        }
        ending_styles = {
            "悬念式": ("悬念式", "关键信息揭露一半，留下悬念让读者想继续阅读", ""),
            "转折式": ("转折式", "意外事件发生，打破读者预期", ""),
            "动作中断式": ("动作中断式", "危机时刻戈然而止，制造紧张感", ""),
            "信息炸弹式": ("信息炸弹式", "揭露惊人真相或身份，制造震撑效果", ""),
            "选择困境式": ("选择困境式", "主角面临艰难拉择，强化情绪张力", ""),
            "情感升华式": ("情感升华式", "通过情感浓度提升结束，留下余韵", ""),
            "环境渲染式": ("环境渲染式", "以环境气氛变化暗示危机或转机", ""),
            "对话留白式": ("对话留白式", "关键对话说一半留一半，制造疑问", ""),
            "时间压力式": ("时间压力式", "引入倒计时或期限，增加紧迫感", ""),
            "身份揭露式": ("身份揭露式", "暗示或半揭露人物真实身份，激发好奇", ""),
        }

        # 🆕 情节类型 → 推荐的开头/结尾方式
        scene_style_rules = {
            "战斗": {"keywords": ["战斗", "打斗", "厮杀", "对决", "交手", "出招", "攻击", "防御", "刀剑", "拳脚"],
                    "opening": "动作开头", "ending": "动作中断式"},
            "悬疑": {"keywords": ["悬疑", "推理", "谜团", "线索", "真相", "秘密", "调查", "疑点", "隐情", "身世"],
                    "opening": "悬念开头", "ending": "悬念式"},
            "转折": {"keywords": ["转折", "揭秘", "真相大白", "身份", "背叛", "反转", "意外", "惊人", "原来", "竟然"],
                    "opening": "反转开头", "ending": "信息炸弹式"},
            "情感": {"keywords": ["告别", "离别", "重逢", "表白", "感情", "思念", "回忆", "温情", "感动", "眼泪"],
                    "opening": "场景开头", "ending": "选择困境式"},
            "危机": {"keywords": ["危机", "危险", "生死", "逃亡", "追杀", "困境", "绝境", "险境", "紧急", "千钧一发"],
                    "opening": "动作开头", "ending": "动作中断式"},
            "对话": {"keywords": ["谈判", "对话", "交涉", "质问", "争执", "辩论", "说服", "威胁", "警告", "摊牌"],
                    "opening": "对话开头", "ending": "转折式"},
            "日常": {"keywords": ["日常", "休息", "准备", "旅途", "修炼", "学习", "训练", "恢复", "整顿", "计划"],
                    "opening": "场景开头", "ending": "悬念式"},
            "升级": {"keywords": ["突破", "升级", "进阶", "觉醒", "获得", "传承", "机缘", "宝物", "功法", "神通"],
                    "opening": "悬念开头", "ending": "信息炸弹式"},
        }

        # 🆕 分析章节规划，匹配情节类型
        matched_scene_type = None
        max_keyword_count = 0
        for scene_type, rule in scene_style_rules.items():
            keyword_count = sum(1 for kw in rule["keywords"] if kw in chapter_plan)
            if keyword_count > max_keyword_count:
                max_keyword_count = keyword_count
                matched_scene_type = scene_type

        # 🆕 根据匹配结果选择开头/结尾方式
        if matched_scene_type and max_keyword_count >= 1:
            rule = scene_style_rules[matched_scene_type]
            selected_opening = opening_styles[rule["opening"]]
            selected_ending = ending_styles[rule["ending"]]
            match_method = f"关键词匹配({matched_scene_type}场景, 命中{max_keyword_count}个关键词)"
        else:
            # 回退到章节编号轮换
            opening_list = list(opening_styles.values())
            ending_list = list(ending_styles.values())
            opening_index = (next_chapter_number - 1) % len(opening_list)
            ending_index = (next_chapter_number + 2) % len(ending_list)
            selected_opening = opening_list[opening_index]
            selected_ending = ending_list[ending_index]
            match_method = "章节编号轮换(未匹配到关键词)"

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
        rag_bundle = workflow_context_builder.build_typed_rag_context(
            project_id,
            rag_query_text or chapter_plan,
            fallback_max_content_length=200,
        )
        rag_character_context = rag_bundle.rag_character_context
        rag_world_context = rag_bundle.rag_world_context
        if rag_bundle.relevant_categories:
            logger.info(f"   📆 章节规划涉及体系: {rag_bundle.relevant_categories}")
        if rag_bundle.used_vector_search:
            logger.info(
                "   📚 RAG注入：人物%s条，设定%s条",
                rag_bundle.character_hits,
                rag_bundle.world_hits,
            )
        if rag_bundle.used_summary_fallback:
            logger.info(
                "   📚 RAG fallback: 从设定中心直接查询%s个相关体系",
                len(rag_bundle.relevant_categories),
            )

        # 🆕 构建内容创作提示词（精简版 - 章节规划已消化大部分上下文）
        from app.services.agents.chapter_prompt_builder import ChapterPromptBuilder
        
        # 获取项目题材
        project_genre = project_profile.genre or ""
        
        builder = ChapterPromptBuilder(genre=project_genre)
        content_system_prompt = builder.build_system_prompt()
        content_user_prompt = builder.build_user_prompt(
            next_chapter_number=next_chapter_number,
            chapter_plan=chapter_plan,
            previous_ending=previous_ending or "",
            recent_chapter_assets_summary=recent_chapter_assets_summary or "",
            rag_character_context=rag_character_context,
            rag_world_context=rag_world_context,
            selected_opening=selected_opening,
            selected_ending=selected_ending,
            current_chapter_outline=chapter_generation_context.current_chapter_outline,
            current_volume_context=chapter_generation_context.current_volume_context,
            core_character_anchor_context=chapter_generation_context.core_character_anchor_context,
            focus_character_relationship_context=chapter_generation_context.focus_character_relationship_context,
            character_runtime_context=chapter_generation_context.character_prompt_context,
            epic_framework_context=chapter_generation_context.epic_framework_context,
        )
        
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
        try:
            chapter_draft = await streaming_service.generate_chapter_streaming(
                prompt=content_user_prompt,
                system_prompt=content_system_prompt,
                on_chunk=on_content_chunk,
                temperature=0.7,
                model=selected_content_model,  # 🔥 使用智能选择的模型
            )
            logger.info(f"   ✓ 章节初稿已完成（真流式 + {selected_content_model}），字数: {len(chapter_draft)}")
        except Exception as e:
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
        
        # 🆕 使用题材自适应评审提示词
        from app.services.prompts.review_prompts import GenreAdaptiveReviewPrompts
        
        review_system_prompt = GenreAdaptiveReviewPrompts.get_review_system_prompt(
            genre=review_project_genre
        )
        
        review_user_prompt = GenreAdaptiveReviewPrompts.get_review_user_prompt(
            chapter_number=next_chapter_number,
            chapter_plan=chapter_plan,
            chapter_content=chapter_draft,
            plot_outline=plot_outline,
            genre=review_project_genre,
            recent_chapter_assets_summary=recent_chapter_assets_summary,
        )

        # 🆕 使用真流式 LLM 调用（按 review 任务路由）
        try:
            review_report = await streaming_service.generate_chapter_streaming(
                prompt=review_user_prompt,
                system_prompt=review_system_prompt,
                on_chunk=on_review_chunk,
                temperature=0.7,
                task_type="review",
            )
            logger.info(f"   ✓ 评审完成（真流式 + review任务路由），报告长度: {len(review_report)}")
        except Exception as e:
            logger.error(f"   ⚠️ 真流式调用失败，回退到同步调用: {e}")
            # 回退到同步调用
            if hasattr(real_coordinator, 'review_chapter'):
                review_report = await asyncio.to_thread(
                    real_coordinator.review_chapter,
                    chapter_draft=chapter_draft,
                    chapter_plan=chapter_plan,
                    plot_outline=plot_outline
                )
            else:
                review_report = "质量评审：章节符合要求，可以继续优化。"

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
        workflow_context_builder.update_project_settings_fields(
            project_id,
            review_report=review_report,
        )
        logger.info(f"   ✓ 评审报告已同步到数据库")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=75,
            message=f"步骤 3/4: 质量评审完成 ✓"
        )

        # ==================== 步骤4：迭代优化（真流式） ====================
        # 🆕 推送步骤4的 Agent 开始工作状态
        step4_agents = STEP_AGENTS['iteration']
        try:
            from app.core.config import settings
            pass_score_threshold = float(getattr(settings, 'ITERATION_PASS_SCORE', 9.0))
            max_rounds = int(getattr(settings, 'ITERATION_MAX_ROUNDS', 2))
        except Exception:
            pass_score_threshold = 8.5
            max_rounds = 2

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
            reached_pass = skip_iteration_optimization
            best_version = current_version
            latest_revised_version = ""
            # 初始化最佳分数为已有评审的分数（若无法提取则为0）
            best_score = _extract_iteration_review_score(current_review)
            # 🆕 累积所有轮次的评审意见，作为改稿参考
            all_reviews = [f"【第0轮评审（初稿）】\n{current_review}"]

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
                    )
                    logger.info(f"   ✓ 第{round_idx}轮迭代计划生成完成，长度: {len(iteration_plan_text)}")
                except Exception as coordination_error:
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
                )

                # 仅在最后一轮向前端流式输出正文；前几轮不推送正文
                on_chunk_cb = noop_chunk
                revised_version = await streaming_service.generate_chapter_streaming(
                    prompt=iteration_user_prompt_round,
                    system_prompt=iteration_system_prompt,
                    on_chunk=on_chunk_cb,
                    temperature=0.7,
                    model=selected_revision_model,
                )
                latest_revised_version = revised_version
                logger.info(f"   ✓ 第{round_idx}轮改稿完成（{selected_revision_model}），字数: {len(revised_version)}")
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
                )
                new_review_report = await streaming_service.generate_chapter_streaming(
                    prompt=review_user_prompt_loop,
                    system_prompt=review_system_prompt_loop,
                    on_chunk=noop_chunk,  # 评分不流式推送正文
                    temperature=0.3,
                    task_type="review",
                )
                score = _extract_iteration_review_score(new_review_report)
                has_unresolved_required_items = _iteration_review_has_unresolved_required_items(new_review_report)
                logger.info(f"   🧮 第{round_idx}轮评分：{score:.1f}/10")
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

                # 判定是否达标
                if score >= pass_score_threshold and not has_unresolved_required_items:
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
                            f"   ↩️ 第{round_idx}轮评分未提升（{score:.1f}/10 < {previous_best_score:.1f}/10），"
                            "下一轮继续基于当前最佳版本修订"
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
            logger.info(f"   ✅ 迭代优化结束，输出最终版本，长度: {len(final_version)}")
        except Exception as e:
            logger.error(f"   ⚠️ 真流式迭代优化失败，回退到同步调用: {e}")
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
        if original_len >= 500 and optimized_len > 0 and optimized_len < original_len * 0.6:
            logger.warning(
                f"   ⚠️ 优化后长度({optimized_len}) 远小于原稿({original_len})，疑似被压缩为摘要，本次将保留原始章节内容"
            )
            final_version = chapter_draft

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

        # 保存最终版本到 project_settings
        workflow_context_builder.update_project_settings_fields(
            project_id,
            final_version=final_version,
        )
        logger.info(f"   ✓ 最终版本已同步到数据库")

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

        # 🆕 阶段3：自动合并高置信度设定项到正式集合
        try:
            from app.services.setting_auto_merge import SettingAutoMergeService
            
            # 获取候选集合
            candidate_collection = db.query(SettingCollection).filter(
                SettingCollection.project_id == project_id,
                SettingCollection.category == "candidate"
            ).first()
            
            if candidate_collection:
                merge_result = SettingAutoMergeService.auto_merge_high_confidence_items(
                    db=db,
                    project_id=project_id,
                    candidate_collection_id=candidate_collection.id,
                    chapter_plan=chapter_plan or "",
                    chapter_content=final_version or "",
                )
                
                if merge_result["merged_count"] > 0:
                    logger.info(
                        f"   ✓ 自动合并高置信度设定: "
                        f"成功 {merge_result['merged_count']} 项, "
                        f"跳过 {merge_result['skipped_count']} 项"
                    )
        except Exception as e:
            logger.warning(f"   ⚠️ 自动合并设定失败: {e}")

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
                generate_summary=True  # 🆕 工作流场景需要生成摘要
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
        mark_generate_next_chapter_task_inactive(task_id)
        db.close()


