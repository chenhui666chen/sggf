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
from app.services.agent_coordinator import coordinator, StageType, AgentStatus, validate_stage_prerequisites
from app.services.agents.agents import agent_stream_observer
from app.services.agent_registry import get_stage_agents_map
from app.core.security import get_current_user
from app.models.project import Project, Chapter
from app.models.setting import SettingCollection
from app.websocket.manager import ws_manager
from app.services.character_runtime_context import (
    build_character_prompt_context_from_text,
    build_initial_character_contexts_from_text,
)
from app.services.workflow_context_builder import WorkflowContextBuilder
from app.utils.datetime_utils import parse_datetime_utc, utc_now
from core.model_resolution import normalize_model_id
from core.model_runtime import ensure_model_hub_initialized, resolve_model_for_task
from app.services.prompts.workflow_runtime import (
    build_streaming_concept_prompts,
    build_streaming_structure_prompts,
    build_streaming_world_prompts,
    get_default_first_chapter_opening_and_ending,
)
from app.services.auto_system_detector import auto_create_system_collections

logger = logging.getLogger(__name__)

from app.api.v1.workflow.lock_manager import _get_workflow_execution_lock
from app.api.v1.workflow.helpers import *
from app.api.v1.workflow.helpers import (
    _sync_project_title_from_concept,
    apply_iteration_result_to_latest_chapter,
    resolve_current_chapter_number,
)
from app.api.v1.workflow.story_helpers import *
from app.api.v1.workflow.story_helpers import (
    _build_project_world_setting_context,
    _inject_recent_project_novelty_context,
    _sync_real_coordinator_project_context,
)
from app.api.v1.workflow.story_resolve import *
from app.api.v1.workflow.story_resolve import (
    _build_concept_stage_character_prompts,
    _normalize_concept_stage_characters_for_storage,
)
from app.api.v1.workflow.requirement import _resolve_workflow_requirement
async def execute_stage_with_streaming(
    task_id: str,
    project_id: int,
    stage_enum: StageType,
    user_id: int,
    db: Session,
    workflow_generation_model: Optional[str] = None,
    manual_multi_model_review: bool = False,
    manual_multi_model_review_preset: Optional[str] = None,
):
    """
    🆕 使用流式输出执行阶段任务

    支持 content/review/iteration 阶段的实时内容推送
    """
    import logging
    from sqlalchemy import text
    from app.db.base import SessionLocal  # 🔧 导入 SessionLocal

    logger = logging.getLogger("uvicorn.error")

    # 🔧 关键修复：创建新的独立 db session（避免使用请求级别的 session）
    db = SessionLocal()
    workflow_context_builder = WorkflowContextBuilder(db)
    observer_token = None
    
    try:
        logger.info(f"🌊 开始流式执行后台任务: {task_id}")
        project_profile = workflow_context_builder.get_project_profile(project_id)
        real_coord = coordinator.get_real_coordinator(project_id)

        # 确保协调器已初始化
        if not coordinator._coordinator_initialized:
            logger.info("   🔍 检测到协调器未初始化，开始初始化...")
            await coordinator.initialize_agents()
            logger.info("   ✅ 协调器初始化完成")

        # 🔧 关键修复：设置当前项目上下文，避免项目间数据污染
        coordinator.set_project_context(project_id)
        logger.info(f"   ✅ 已设置项目上下文：project_id={project_id}")
        
        # 🔧 关键修复：立即从数据库加载当前项目的基本信息，注入到 project_context
        try:
            project_profile, real_coord = _sync_real_coordinator_project_context(
                project_id,
                workflow_context_builder,
                project_profile,
            )
            if real_coord is None:
                raise RuntimeError("真实协调器未初始化")
        except Exception as e:
            raise RuntimeError("项目上下文初始化失败") from e

        if not coordinator._coordinator_initialized:
            raise RuntimeError("真实协调器未初始化")
        stage_context = workflow_context_builder.load_stage_text_context(project_id)
        real_coord.project_context.update({
            "concept": stage_context.concept,
            "world_setting": stage_context.world_setting,
            "characters": stage_context.characters,
            "plot_outline": stage_context.plot_outline,
            "content": stage_context.chapter_draft,
            "chapter_draft": stage_context.chapter_draft,
            "review": stage_context.review_report,
            "review_report": stage_context.review_report,
            "chapter_number": resolve_current_chapter_number(db, project_id),
            "workflow_generation_model": workflow_generation_model,
            "manual_multi_model_review": manual_multi_model_review if stage_enum == StageType.REVIEW else False,
            "manual_multi_model_review_preset": manual_multi_model_review_preset if stage_enum == StageType.REVIEW else None,
            "regenerate": False,
            "regenerate_targets": [],
        })
        validate_stage_prerequisites(stage_enum, real_coord.project_context)

        if stage_enum == StageType.CONCEPT:
            try:
                _inject_recent_project_novelty_context(
                    db,
                    project_id=project_id,
                    user_id=user_id,
                    real_coord=real_coord,
                    genre=project_profile.genre or None,
                )
                logger.info("   ✅ 已注入近期项目避重约束（流式）")
            except Exception as e:
                logger.warning(f"⚠️ 近期项目避重约束注入失败（流式）：{e}")
        
        # 确保 project_settings 记录存在
        if workflow_context_builder.ensure_project_settings_record(project_id):
            logger.info(f"   📝 初始化 project_settings 记录")
            logger.info("   ✅ project_settings 记录已创建")

        requirement, requirement_source = _resolve_workflow_requirement(db, project_id)
        logger.info(f"   ✅ 用户需求来源: {requirement_source}")

        # 🆕 推送阶段开始状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='active',
            progress=0
        )

        # 🆕 广播本阶段选用的模型，便于前端调试
        try:
            from app.core.config import settings
            default_content_model = getattr(settings, "DEFAULT_CONTENT_MODEL", "qwen3.7-plus")
        except Exception:
            default_content_model = "qwen3.7-plus"
        creative_model = workflow_generation_model or default_content_model
        stage_task_type = None
        stage_model_override = None
        if stage_enum == StageType.CONCEPT:
            stage_task_type = "concept"
            stage_model_override = creative_model
        elif stage_enum == StageType.STRUCTURE:
            stage_task_type = "structure_plot"
            stage_model_override = creative_model
        elif stage_enum == StageType.CONTENT:
            stage_task_type = "chapter"
            stage_model_override = creative_model
        elif stage_enum == StageType.REVIEW:
            stage_task_type = "review"
        elif stage_enum == StageType.ITERATION:
            stage_task_type = "rewrite"
            stage_model_override = creative_model
        stage_model = resolve_model_for_task(stage_task_type, stage_model_override) if stage_task_type else None
        if stage_model:
            await ws_manager.send_model_used(
                project_id=project_id,
                stage=stage_enum.value,
                model=stage_model,
                extra={
                    "source": "execute_stage_with_streaming",
                    "task_type": stage_task_type,
                }
            )

        # 🌊 发送流式输出开始通知
        await ws_manager.send_stream_start(project_id, stage_enum.value)

        STAGE_AGENTS_STREAMING = get_stage_agents_map()

        # 🆕 推送 Agent 开始工作状态
        stage_agents = STAGE_AGENTS_STREAMING.get(stage_enum.value, [])
        for agent in stage_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=stage_enum.value,
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='idle',
                progress=0,
                message=f'{agent["name"]}等待前置步骤...' 
            )
        logger.info(f"   📡 已发送 {len(stage_agents)} 个 Agent 开始状态（流式模式）")

        active_agent_id = ""

        async def announce_agent(agent_id: str):
            nonlocal active_agent_id
            active_agent_id = agent_id
            agent = next((item for item in stage_agents if item["id"] == agent_id), None)
            if agent:
                await ws_manager.send_agent_status(project_id=project_id, stage=stage_enum.value,
                    agent_id=agent_id, agent_name=agent["name"], status="working", progress=0,
                    message=f'{agent["name"]}正在执行...')

        # 🌊 创建流式输出回调
        chunk_index = [0]  # 使用列表以便在闭包中修改
        total_chars = [0]  # 总字符数

        async def on_stream_chunk(chunk: str, idx: int):
            """流式输出回调：推送每个文本块到前端"""
            chunk_index[0] = idx
            total_chars[0] += len(chunk)
            await ws_manager.send_stream_chunk(
                project_id=project_id,
                stage=stage_enum.value,
                chunk=chunk,
                chunk_index=idx,
                is_complete=False
            )
            # 🆕 每 50 个 chunk 更新一次 Agent 进度（避免太频繁）
            if idx % 50 == 0:
                estimated_progress = min(90, idx // 5)  # 估算进度
                for agent in stage_agents:
                    if agent["id"] != active_agent_id:
                        continue
                    await ws_manager.send_agent_status(
                        project_id=project_id,
                        stage=stage_enum.value,
                        agent_id=agent['id'],
                        agent_name=agent['name'],
                        status='working',
                        progress=estimated_progress,
                        message=f'已生成 {total_chars[0]} 字...'
                    )

        loop = asyncio.get_running_loop()
        visible_agents = {"plot_architect", "content_creator", "style_optimizer", "content_reviser", "quality_reviewer"}
        concept_targets = {"creative_director": "concept", "world_architect": "world", "character_designer": "character"}

        async def forward_agent_chunk(agent_id: str, chunk: str):
            target = concept_targets.get(agent_id) if stage_enum == StageType.CONCEPT else None
            if not chunk:
                await announce_agent(agent_id)
                if agent_id in visible_agents or target:
                    chunk_index[0] = 0
                    total_chars[0] = 0
                    await ws_manager.send_stream_start(project_id, stage_enum.value)
            elif target:
                chunk_index[0] += 1
                await ws_manager.send_stream_chunk(
                    project_id=project_id, stage=stage_enum.value, chunk=chunk,
                    chunk_index=chunk_index[0], is_complete=False, extra={"target": target},
                )
            elif agent_id in visible_agents:
                await on_stream_chunk(chunk, chunk_index[0] + 1)

        def observe_agent(agent_id: str, chunk: str):
            # Agent 在工作线程中执行，WebSocket 推送仍回到所属事件循环。
            try:
                asyncio.run_coroutine_threadsafe(forward_agent_chunk(agent_id, chunk), loop).result(timeout=15)
            except Exception:
                logger.warning("Agent 流式预览推送失败，不影响生成结果", exc_info=True)

        observer_token = agent_stream_observer.set(observe_agent)
        result_str = ""
        use_streaming_llm = (
            STREAMING_AVAILABLE and get_streaming_service is not None
            and stage_enum not in {StageType.REVIEW, StageType.ITERATION}
        )

        if use_streaming_llm:
            try:
                # 🌊 使用流式服务进行真正的流式 LLM 调用
                streaming_service = get_streaming_service()

                # 构建流式调用的提示词
                if stage_enum == StageType.CONTENT:
                    await announce_agent("content_creator")
                    # 内容创作阶段
                    plot_outline = stage_context.plot_outline
                    world_setting = stage_context.world_setting
                    characters = stage_context.characters
                    world_context = workflow_context_builder.build_world_setting_context(
                        project_id,
                        world_setting,
                    )
                    world_setting = world_context.combined_world_setting
                    selected_opening, selected_ending = get_default_first_chapter_opening_and_ending()

                    from app.services.agents.chapter_prompt_builder import ChapterPromptBuilder
                    from app.services.agents.intelligent_truncator import smart_truncate_for_context

                    content_plan_parts = []
                    if stage_context.concept:
                        content_plan_parts.append(f"【故事概念】\n{stage_context.concept}")
                    if plot_outline:
                        content_plan_parts.append(f"【第一章结构大纲】\n{plot_outline}")
                    if requirement:
                        content_plan_parts.append(f"【补充要求】\n{requirement}")
                    content_plan = "\n\n".join(
                        part for part in content_plan_parts if part.strip()
                    ) or plot_outline

                    first_chapter_rag = workflow_context_builder.build_typed_rag_context(
                        project_id,
                        content_plan or requirement or world_setting,
                        fallback_max_content_length=180,
                    )
                    rag_character_context = first_chapter_rag.rag_character_context
                    rag_world_context = first_chapter_rag.rag_world_context
                    if not rag_character_context and characters:
                        rag_character_context = build_character_prompt_context_from_text(
                            characters,
                            detail_limit=560,
                            summary_limit=240,
                        )
                    if not rag_character_context and characters:
                        rag_character_context = smart_truncate_for_context(
                            characters,
                            max_tokens=220,
                            content_type="prompt_context",
                            preserve_ratio=0.9,
                        )
                    if not rag_world_context:
                        rag_world_context = smart_truncate_for_context(
                            world_setting,
                            max_tokens=260,
                            content_type="prompt_context",
                            preserve_ratio=0.9,
                        )

                    # P1 统一人物上下文：首章使用初始基线（身份、动机、性格锚点、价值倾向、关系底色）
                    initial_character_contexts = (
                        build_initial_character_contexts_from_text(characters)
                    )

                    real_coord = coordinator.get_real_coordinator(project_id)
                    project_context = getattr(real_coord, "project_context", {}) if real_coord else {}
                    project_genre = (
                        project_context.get("genre")
                        or project_context.get("project_genre")
                        or ""
                    )
                    prompt_builder = ChapterPromptBuilder(genre=project_genre)
                    system_prompt = prompt_builder.build_system_prompt()
                    user_prompt = prompt_builder.build_user_prompt(
                        next_chapter_number=1,
                        chapter_plan=content_plan,
                        previous_ending="",
                        recent_chapter_assets_summary="",
                        core_character_anchor_context=initial_character_contexts.core_character_anchor_context,
                        focus_character_relationship_context=initial_character_contexts.focus_character_relationship_context,
                        character_runtime_context=initial_character_contexts.character_runtime_context,
                        rag_character_context=rag_character_context,
                        rag_world_context=rag_world_context,
                        selected_opening=selected_opening,
                        selected_ending=selected_ending,
                    )

                elif stage_enum == StageType.CONCEPT:
                    # 概念开发阶段 - 分三个子阶段流式输出
                    logger.info(f"   🌊 概念开发阶段开始流式输出...")
                    
                    # 1. 故事概念生成
                    await announce_agent("creative_director")
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成故事概念...")

                    real_coord = coordinator.get_real_coordinator(project_id)
                    project_context = getattr(real_coord, "project_context", {}) if real_coord else {}
                    project_title = project_context.get("title") or project_context.get("project_title") or "未命名项目"
                    project_genre = project_context.get("genre") or project_context.get("project_genre") or "通用题材"
                    recent_project_signatures = project_context.get("recent_project_signatures") or ""
                    recent_project_avoidance = project_context.get("recent_project_avoidance") or ""
                    
                    concept_system_prompt, concept_user_prompt = build_streaming_concept_prompts(
                        project_title=project_title,
                        project_genre=project_genre,
                        requirement=requirement or "",
                        recent_project_avoidance=recent_project_avoidance,
                        recent_project_signatures=recent_project_signatures,
                    )
                    
                    # 执行故事概念生成的流式调用
                    concept_result = ""
                    async def on_concept_chunk(chunk: str, idx: int):
                        nonlocal concept_result
                        concept_result += chunk
                        # 发送到前端的conceptContent状态
                        await ws_manager.send_stream_chunk(
                            project_id=project_id,
                            stage=stage_enum.value,
                            chunk=chunk,
                            chunk_index=idx,
                            is_complete=False,
                            extra={'target': 'concept'}
                        )
                    
                    await streaming_service.generate_chapter_streaming(
                        prompt=concept_user_prompt,
                        system_prompt=concept_system_prompt,
                        on_chunk=on_concept_chunk,
                        temperature=0.9,
                        model=workflow_generation_model,
                        task_type="concept",
                    )
                    
                    # 2. 世界观设定生成
                    await announce_agent("world_architect")
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成世界观设定...")
                    
                    world_system_prompt, world_user_prompt = build_streaming_world_prompts(
                        concept_text=concept_result,
                    )
                    
                    # 执行世界观设定生成的流式调用
                    world_result = ""
                    async def on_world_chunk(chunk: str, idx: int):
                        nonlocal world_result
                        world_result += chunk
                        # 发送到前端的worldContent状态
                        await ws_manager.send_stream_chunk(
                            project_id=project_id,
                            stage=stage_enum.value,
                            chunk=chunk,
                            chunk_index=idx,
                            is_complete=False,
                            extra={'target': 'world'}
                        )
                    
                    await streaming_service.generate_chapter_streaming(
                        prompt=world_user_prompt,
                        system_prompt=world_system_prompt,
                        on_chunk=on_world_chunk,
                        temperature=0.7,
                        model=workflow_generation_model,
                        task_type="worldview",
                    )
                    
                    # 3. 人物设定生成
                    await announce_agent("character_designer")
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成人物设定...")
                    
                    character_system_prompt, character_user_prompt = _build_concept_stage_character_prompts(
                        project_genre=project_genre,
                        requirement=requirement or "",
                        concept_text=concept_result,
                        world_setting_text=world_result,
                    )
                    
                    # 执行人物设定生成的流式调用
                    character_result = ""
                    async def on_character_chunk(chunk: str, idx: int):
                        nonlocal character_result
                        character_result += chunk
                        # 发送到前端的characterContent状态
                        await ws_manager.send_stream_chunk(
                            project_id=project_id,
                            stage=stage_enum.value,
                            chunk=chunk,
                            chunk_index=idx,
                            is_complete=False,
                            extra={'target': 'character'}
                        )
                    
                    await streaming_service.generate_chapter_streaming(
                        prompt=character_user_prompt,
                        system_prompt=character_system_prompt,
                        on_chunk=on_character_chunk,
                        temperature=0.7,
                        model=workflow_generation_model,
                        task_type="character",
                    )
                    
                    # 组合结果
                    result_str = f"{concept_result}\n\n{world_result}\n\n{character_result}"
                    logger.info(f"   ✅ 概念开发阶段流式输出完成，总长度: {len(result_str)} 字符")
                    
                    # 🔧 将概念阶段的三个部分数据存储到output_data，用于后续保存
                    output_data = {
                        "concept": concept_result,
                        "world_setting": world_result,
                        "characters": character_result
                    }

                elif stage_enum == StageType.STRUCTURE:
                    await announce_agent("plot_architect")
                    # 结构设计阶段 - 流式输出大纲
                    logger.info(f"   🌊 结构设计阶段开始流式输出...")
                    
                    # 获取概念开发阶段的成果
                    concept_data = stage_context.concept
                    world_setting = stage_context.world_setting
                    characters = stage_context.characters
                    
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成情节大纲...")
                    
                    structure_system_prompt, structure_user_prompt = build_streaming_structure_prompts(
                        concept_text=concept_data,
                        world_setting=world_setting,
                        characters=characters,
                        requirement=requirement or "",
                    )
                    
                    # 执行结构设计的流式调用
                    world_setting = _build_project_world_setting_context(
                        project_id,
                        world_setting,
                        db,
                    )
                    structure_result = ""
                    async def on_structure_chunk(chunk: str, idx: int):
                        nonlocal structure_result
                        structure_result += chunk
                        # 发送到前端
                        await ws_manager.send_stream_chunk(
                            project_id=project_id,
                            stage=stage_enum.value,
                            chunk=chunk,
                            chunk_index=idx,
                            is_complete=False
                        )
                    
                    await streaming_service.generate_chapter_streaming(
                        prompt=structure_user_prompt,
                        system_prompt=structure_system_prompt,
                        on_chunk=on_structure_chunk,
                        temperature=0.7,
                        model=workflow_generation_model,
                        task_type="structure_plot",
                    )
                    
                    result_str = structure_result
                    logger.info(f"   ✅ 结构设计阶段流式输出完成，总长度: {len(result_str)} 字符")
                    
                    # 🔧 将结构设计结果存储到output_data，用于后续保存
                    output_data = {
                        "plot_outline": structure_result
                    }

                else:
                    # 其他阶段不使用流式输出，回退到原有逻辑
                    raise ValueError(f"阶段 {stage_enum.value} 不支持流式输出")

                # 🔥 执行流式 LLM 调用
                logger.info(f"   🌊 开始流式 LLM 调用...")
                # 🆕 按阶段选择模型，避免使用默认 deepseek-v4-flash
                stage_model = None
                stage_task_type = None
                stage_model_override = None
                try:
                    from app.core.config import settings
                    default_content_model = getattr(settings, "DEFAULT_CONTENT_MODEL", "qwen3.7-plus")
                except Exception:
                    default_content_model = "qwen3.7-plus"
                creative_model = workflow_generation_model or default_content_model
                
                if stage_enum == StageType.CONTENT:
                    stage_task_type = "chapter"
                    stage_model_override = creative_model
                elif stage_enum == StageType.REVIEW:
                    stage_task_type = "review"
                elif stage_enum == StageType.ITERATION:
                    stage_task_type = "rewrite"
                    stage_model_override = creative_model
                stage_model = (
                    resolve_model_for_task(stage_task_type, stage_model_override)
                    if stage_task_type
                    else None
                )
                
                # 对于非CONCEPT阶段，执行流式调用
                if stage_enum == StageType.CONTENT:
                    result_str = await streaming_service.generate_chapter_streaming(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        on_chunk=on_stream_chunk,
                        temperature=0.7,
                        model=stage_model_override,
                        task_type=stage_task_type,
                    )
                    logger.info(f"   ✅ 流式 LLM 调用完成，生成 {len(result_str)} 字符")

            except Exception as streaming_error:
                logger.warning(f"   ⚠️  流式 LLM 调用失败，回退到原有逻辑: {streaming_error}")
                use_streaming_llm = False

        # 质量步骤位于传输降级边界之外，验证失败不得重新生成整个阶段。
        if use_streaming_llm and result_str:
            if stage_enum == StageType.STRUCTURE:
                output_data = await asyncio.to_thread(real_coord.finalize_structure, result_str)
                result_str = output_data["plot_outline"]
            elif stage_enum == StageType.CONTENT:
                output_data = await asyncio.to_thread(real_coord.finalize_content, result_str, chapter_plan=content_plan)
                result_str = output_data["content"]
            elif stage_enum == StageType.CONCEPT:
                if not all(isinstance(output_data.get(key), str) and output_data[key].strip() for key in ("concept", "world_setting", "characters")):
                    raise RuntimeError("概念开发未返回完整的概念、世界观和人物设定")

        # 如果流式调用失败或不可用，回退到原有逻辑
        if not use_streaming_llm or not result_str:
            logger.info(f"   📝 使用原有逻辑执行阶段...")
            stage_output = await coordinator.execute_stage(
                stage_enum,
                {
                    "project_id": project_id,
                    "user_id": user_id,
                    "requirement": requirement,
                    "enable_streaming": False,
                    "defer_completion": True,
                    "workflow_generation_model": workflow_generation_model,
                    "manual_multi_model_review": manual_multi_model_review,
                    "manual_multi_model_review_preset": manual_multi_model_review_preset,
                },
            )

            # 提取结果内容
            output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
            if stage_enum == StageType.ITERATION:
                result_str = output_data.get("revised_content", "")
            elif stage_enum == StageType.CONTENT:
                result_str = output_data.get("content", "") or output_data.get("chapters", "")
            elif stage_enum == StageType.REVIEW:
                result_str = output_data.get("review", "")
            # 🔧 修复：CONCEPT 和 STRUCTURE 阶段需要提取正确的字段
            elif stage_enum == StageType.CONCEPT:
                result_str = output_data.get("concept", "") or str(output_data) if output_data else ""
                logger.info(f"   🔍 CONCEPT 阶段提取结果: {len(result_str)} 字符")
            elif stage_enum == StageType.STRUCTURE:
                result_str = output_data.get("plot_outline", "") or output_data.get("structure", "") or str(output_data) if output_data else ""
                logger.info(f"   🔍 STRUCTURE 阶段提取结果: {len(result_str)} 字符")
            else:
                result_str = str(stage_output.output) if stage_output.output else ""

        # 模型执行已结束，持久化及同步规范化不得继续等待当前事件循环的预览回调。
        agent_stream_observer.reset(observer_token)
        observer_token = None

        # 🌊 发送流式输出结束通知
        await ws_manager.send_stream_end(
            project_id=project_id,
            stage=stage_enum.value,
            total_chars=len(result_str) if result_str else 0
        )

        # 🔧 确保 output_data 存在（防止未定义错误）
        if 'output_data' not in locals():
            # 🆕 如果是流式模式，需要从 result_str 中提取结构化数据
            if stage_enum == StageType.CONCEPT and result_str:
                # 尝试从 result_str 中提取三个部分：故事概念、世界观、人物
                logger.info(f"   🔍 流式模式，开始解析 CONCEPT 结果...")
                import re
                
                # 提取世界观部分
                world_pattern = r'(?:###?\s*二、世界观设定|###?\s*2\.\s*世界观设定|###\s*世界观设定)(.*?)(?=###?\s*三、人物设定|###?\s*3\.\s*人物设定|$)'
                world_match = re.search(world_pattern, result_str, re.DOTALL | re.IGNORECASE)
                world_setting = world_match.group(1).strip() if world_match else ""
                
                # 提取人物部分
                char_pattern = r'(?:###?\s*三、人物设定|###?\s*3\.\s*人物设定|###\s*人物设定)(.*?)$'
                char_match = re.search(char_pattern, result_str, re.DOTALL | re.IGNORECASE)
                characters = char_match.group(1).strip() if char_match else ""
                
                # 故事概念是从开头到世界观之前的部分
                concept_pattern = r'^(.*?)(?=###?\s*二、世界观设定|###?\s*2\.\s*世界观设定|###\s*世界观设定)'
                concept_match = re.search(concept_pattern, result_str, re.DOTALL | re.IGNORECASE)
                concept = concept_match.group(1).strip() if concept_match else result_str
                
                logger.info(f"   🔍 提取结果: concept={len(concept)}字, world={len(world_setting)}字, characters={len(characters)}字")
                
                output_data = {
                    "concept": concept,
                    "worldview": world_setting,
                    "world_setting": world_setting,
                    "characters": characters
                }
            else:
                output_data = {}

        # 更新任务状态为完成
        update_query = text("""
            UPDATE generation_history
            SET status = :status, result = :result, completed_at = :completed_at
            WHERE task_id = :task_id
        """)

        if not isinstance(result_str, str) or not result_str.strip():
            raise RuntimeError("阶段未返回有效产物")

        # 保存阶段输出到 project_settings
        logger.debug(f"\n{'='*50}")
        logger.debug(f"🔍 准备保存到 project_settings: stage={stage_enum.value}, project_id={project_id}, result_len={len(result_str) if result_str else 0}")
        logger.debug(f"{'='*50}\n")
        logger.info(f"   🔍 准备保存到 project_settings: stage={stage_enum.value}, project_id={project_id}, result_len={len(result_str) if result_str else 0}")
        try:
            # 🔧 添加 CONCEPT 阶段的保存（同时保存 concept, world_setting, characters）
            if stage_enum == StageType.CONCEPT:
                logger.info(f"   🔍 匹配到 CONCEPT 阶段，开始保存...")
                # 🔧 直接使用已定义的 output_data 变量
                concept_data = output_data.get("concept", result_str) if isinstance(output_data, dict) and output_data else result_str
                worldview_data = output_data.get("worldview", "") or output_data.get("world_setting", "") if isinstance(output_data, dict) and output_data else ""
                characters_data = output_data.get("characters", "") if isinstance(output_data, dict) and output_data else ""
                characters_data = _normalize_concept_stage_characters_for_storage(
                    project_id,
                    characters_data,
                    concept_text=str(concept_data or ""),
                    world_setting_text=str(worldview_data or ""),
                )
                
                logger.info(f"   🔍 CONCEPT 数据: concept={len(str(concept_data))}字, worldview={len(str(worldview_data))}字, characters={len(str(characters_data))}字")

                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    concept=json.dumps(concept_data, ensure_ascii=False) if concept_data else None,
                    world_setting=json.dumps(worldview_data, ensure_ascii=False) if worldview_data else None,
                    characters=json.dumps(characters_data, ensure_ascii=False) if characters_data else None,
                    stage_one_status="completed",
                )
                logger.info("   🔍 UPDATE 执行完成，字段已通过统一 helper 写入")
                logger.info(f"   💾 已保存概念/世界观/人物到 project_settings（流式模式）")
                
                # 🆕 从故事概念中提取日志标题，自动更新项目title（流式模式）
                if concept_data and isinstance(concept_data, str):
                    try:
                        _sync_project_title_from_concept(
                            db,
                            project_id,
                            concept_data,
                            mode_label="流式模式",
                        )
                    except Exception as e:
                        logger.warning(f"   ⚠️  提取日志标题失败（流式模式）: {e}")
            # 🔧 添加 STRUCTURE 阶段的保存
            elif stage_enum == StageType.STRUCTURE:
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    plot_outline=json.dumps(result_str, ensure_ascii=False),
                    review_meta={"first_chapter_structure": {"event_validation": output_data.get("event_validation", "")}},
                    stage_two_status="completed",
                )
                logger.info(f"   💾 已保存结构大纲到 project_settings（流式模式）")
            elif stage_enum == StageType.CONTENT:
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    chapter_draft=json.dumps(result_str, ensure_ascii=False),
                    stage_three_status="completed",
                )
            elif stage_enum == StageType.REVIEW:
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    review_report=json.dumps(result_str, ensure_ascii=False),
                    review_meta=output_data.get("review_meta") or {},
                    stage_four_status="completed",
                )
            elif stage_enum == StageType.ITERATION:
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    final_version=json.dumps(result_str, ensure_ascii=False),
                    review_meta={"first_chapter_iteration": {
                        "iteration_plan": output_data.get("iteration_plan", ""),
                        "final_review": output_data.get("final_review", ""),
                        "degraded": output_data.get("iteration_degraded", False),
                        "best_score": output_data.get("best_score"),
                    }},
                    stage_five_status="completed",
                )
                # 迭代终稿必须覆盖当前最新一章，否则用户看到的仍是上一版旧稿
                apply_iteration_result_to_latest_chapter(
                    db,
                    project_id=project_id,
                    content=result_str,
                    revision_note="迭代终稿覆盖（阶段级迭代）",
                )
        except Exception as save_error:
            logger.error(f"   ⚠️  保存到 project_settings 失败: {save_error}")
            # 🆕 添加详细堆栈跟踪
            import traceback
            logger.error(f"   🔍 堆栈跟踪:\n{traceback.format_exc()}")
            # 🆕 打印关键变量
            logger.error(f"   🔍 stage_enum={stage_enum}, project_id={project_id}, result_str_len={len(result_str) if result_str else 0}")
            logger.error(f"   🔍 output_data={type(output_data)}, output_data_keys={output_data.keys() if isinstance(output_data, dict) else 'not dict'}")
            raise

        db.execute(update_query, {
            "status": "completed", "result": result_str,
            "completed_at": utc_now().isoformat(), "task_id": task_id,
        })
        db.commit()
        coordinator.record_stage_result(stage_enum, project_id, output_data, "completed")

        # 推送任务完成通知
        await ws_manager.send_task_complete(
            project_id=project_id,
            task_id=task_id,
            result={"output": result_str}
        )

        # 🆕 推送 Agent 完成状态（流式模式）
        for agent in stage_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=stage_enum.value,
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='idle' if agent['id'] in output_data.get('skipped_agents', []) else 'completed',
                progress=0 if agent['id'] in output_data.get('skipped_agents', []) else 100,
                message='本轮无需修订，已跳过' if agent['id'] in output_data.get('skipped_agents', []) else f'{agent["name"]}已完成'
            )
        logger.info(f"   📡 已发送 {len(stage_agents)} 个 Agent 完成状态（流式模式）")

        # 推送阶段完成状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='completed',
            output=result_str,
            progress=100
        )

        # 🆕 保存记忆到数据库（统一存储方案 - 流式模式）
        try:
            from app.models.memory import Memory

            # 🆕 消息数量上限
            MAX_MESSAGES = 50

            # 查找或创建记忆记录
            memory = db.query(Memory).filter(
                Memory.project_id == project_id
            ).order_by(Memory.updated_at.desc()).first()

            # 构建新的消息记录
            new_message = {
                "role": "assistant",
                "content": result_str[:2000] if result_str else "",  # 限制长度
                "stage": stage_enum.value,
                "timestamp": utc_now().isoformat()
            }

            if memory:
                # 更新现有记忆
                messages = memory.messages or []
                messages.append(new_message)

                # 🆕 限制消息数量（保留最近 MAX_MESSAGES 条）
                if len(messages) > MAX_MESSAGES:
                    messages = messages[-MAX_MESSAGES:]

                memory.messages = messages
                memory.current_scene = stage_enum.value
                db.add(memory)
            else:
                # 创建新记忆
                project = db.query(Project).filter(Project.id == project_id).first()
                if project:
                    memory = Memory(
                        project_id=project_id,
                        user_id=project.user_id,
                        messages=[new_message],
                        current_scene=stage_enum.value
                    )
                    db.add(memory)

            db.commit()
            logger.info(f"   💾 已保存阶段记忆到数据库（流式模式）: {stage_enum.value}")
        except Exception as mem_error:
            logger.error(f"   ⚠️  保存记忆失败（流式模式）: {mem_error}")
            # 不影响主流程

    except Exception as e:
        logger.error(f"❌ 流式后台任务失败: {task_id}, 错误: {str(e)}")
        try:
            db.rollback()
        except Exception as rollback_error:
            logger.warning(f"⚠️  流式后台任务失败后回滚事务失败: {rollback_error}")

        # 更新任务状态为失败
        update_query = text("""
            UPDATE generation_history
            SET status = :status, error = :error, completed_at = :completed_at
            WHERE task_id = :task_id
        """)

        try:
            db.execute(update_query, {
                "status": "failed",
                "error": str(e),
                "completed_at": utc_now().isoformat(),
                "task_id": task_id
            })
            db.commit()
        except Exception:
            logger.exception("任务失败状态无法写入数据库，仍继续通知客户端")

        coordinator.record_stage_result(stage_enum, project_id, {}, "error")
        for agent in get_stage_agents_map().get(stage_enum.value, []):
            await ws_manager.send_agent_status(project_id=project_id, stage=stage_enum.value,
                agent_id=agent["id"], agent_name=agent["name"], status="error", progress=0,
                message="阶段未完成，请查看任务错误")

        # 推送任务失败通知
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e)
        )

        # 推送错误状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='error',
            progress=0
        )
    finally:
        if observer_token is not None:
            agent_stream_observer.reset(observer_token)
        # 🔧 关键修复：关闭独立创建的 db session
        db.close()
        logger.info(f"   📝 db session 已关闭")

