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

from app.api.v1.workflow.lock_manager import _get_workflow_execution_lock
from app.api.v1.workflow.helpers import *
from app.api.v1.workflow.story_helpers import *
from app.api.v1.workflow.story_resolve import *
async def execute_stage_with_streaming(task_id: str, project_id: int, stage_enum: StageType, user_id: int, db: Session):
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
        except Exception as e:
            logger.warning(f"⚠️ 项目基本信息注入失败：{e}")

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
            default_content_model = getattr(settings, "DEFAULT_CONTENT_MODEL", "qwen3-max")
        except Exception:
            default_content_model = "qwen3-max"
        stage_task_type = None
        stage_model_override = None
        if stage_enum == StageType.CONTENT:
            stage_task_type = "chapter"
            stage_model_override = default_content_model
        elif stage_enum == StageType.REVIEW:
            stage_task_type = "review"
        elif stage_enum == StageType.ITERATION:
            stage_task_type = "review"
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

        STAGE_AGENTS_STREAMING = {
            'concept': [
                {'id': 'creative-director', 'name': '创意总监'},
                {'id': 'worldview-architect', 'name': '世界观架构师'},
                {'id': 'character-designer', 'name': '人物设计师'},
            ],
            'structure': [
                {'id': 'plot-architect', 'name': '情节架构师'},
                {'id': 'event-validator', 'name': '事件验证官'},
            ],
            'content': [
                {'id': 'content-creator', 'name': '内容创作师'},
                {'id': 'style-optimizer', 'name': '文风优化师'},
            ],
            'review': [
                {'id': 'quality-reviewer', 'name': '质量评审官'},
            ],
            'iteration': [
                {'id': 'iteration-coordinator', 'name': '迭代协调官'},
                {'id': 'content-reviser', 'name': '内容修订师'},
                {'id': 'final-reviewer', 'name': '最终审核官'},
            ],
        }

        # 🆕 推送 Agent 开始工作状态
        stage_agents = STAGE_AGENTS_STREAMING.get(stage_enum.value, [])
        for agent in stage_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=stage_enum.value,
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='working',
                progress=0,
                message=f'{agent["name"]}正在工作中...'
            )
        logger.info(f"   📡 已发送 {len(stage_agents)} 个 Agent 开始状态（流式模式）")

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
                    await ws_manager.send_agent_status(
                        project_id=project_id,
                        stage=stage_enum.value,
                        agent_id=agent['id'],
                        agent_name=agent['name'],
                        status='working',
                        progress=estimated_progress,
                        message=f'已生成 {total_chars[0]} 字...'
                    )

        # 🔥 尝试使用流式 LLM 调用
        result_str = ""
        use_streaming_llm = STREAMING_AVAILABLE and get_streaming_service is not None

        if use_streaming_llm:
            try:
                # 🌊 使用流式服务进行真正的流式 LLM 调用
                streaming_service = get_streaming_service()

                # 获取项目上下文（用于构建提示词）
                stage_context = workflow_context_builder.load_stage_text_context(project_id)

                # 构建流式调用的提示词
                if stage_enum == StageType.CONTENT:
                    # 内容创作阶段
                    plot_outline = stage_context.plot_outline
                    world_setting = stage_context.world_setting
                    characters = stage_context.characters
                    world_context = workflow_context_builder.build_world_setting_context(
                        project_id,
                        world_setting,
                    )
                    world_setting = world_context.combined_world_setting
                    # 🆕 开头/结尾方式定义（从头创作共享模块）
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

                    # 第一章使用固定的开头/结尾方式（适合开篇）
                    selected_opening = opening_styles["悬念开头"]
                    selected_ending = ending_styles["悬念式"]

                    system_prompt = """你是一位经验丰富的网络小说作家。请根据提供的情节大纲、世界观设定和人物设定，创作精彩的第一章内容。

创作要求：
1. 语言生动，描写细腻，符合网文风格
2. 对话自然，符合人物性格
3. 情节紧凑，引人入胜，注意爽点节奏
4. 场景描写要有画面感
5. 注意段落分隔，便于阅读
6. 第一章要快速建立世界观和主角形象
7. 使用场景描写、对话、心理描写等多种手法

【质量标准】
- ✅ 人物性格和行为符合设定
- ✅ 遵循已建立的世界观规则
- ✅ 注重细节的合理性和真实感
- ✅ 开头要有吸引力，结尾要有悬念

【输出格式要求】⚠️
请直接输出章节内容，格式必须如下：

第一章 章节标题

章节正文内容...

注意：
- 第一行必须是章节标题，格式为"第一章 标题名称"
- 章节标题要简洁有力，能概括本章核心内容或悬念
- 不要包含任何额外的说明文字、作者话语等"""

                    user_prompt = f"""请创作第一章内容：

【情节大纲】
{plot_outline}

【世界观设定】
{world_setting}

【人物设定】
{characters}

【用户需求】
{requirement}

【目标字数】约3000字

【本章开头方式 - 建议】
建议使用【{selected_opening[0]}】方式开头，快速抓住读者注意力
- 技巧说明：{selected_opening[1]}

❌ 禁止使用：用"XXX醒来/睁开眼睛/阳光照进房间"开头

【本章结尾方式 - 建议】
建议使用【{selected_ending[0]}】结尾，让读者想点下一章
- 技巧说明：{selected_ending[1]}

❌ 禁止使用：总结式内心独白 + 对未来的展望（如"她知道，从这一刻起...")）

请开始创作第一章内容："""

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
                        rag_character_context=rag_character_context,
                        rag_world_context=rag_world_context,
                        selected_opening=selected_opening,
                        selected_ending=selected_ending,
                    )

                elif stage_enum == StageType.CONCEPT:
                    # 概念开发阶段 - 分三个子阶段流式输出
                    logger.info(f"   🌊 概念开发阶段开始流式输出...")
                    
                    # 1. 故事概念生成
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成故事概念...")

                    real_coord = coordinator.get_real_coordinator(project_id)
                    project_context = getattr(real_coord, "project_context", {}) if real_coord else {}
                    project_title = project_context.get("title") or project_context.get("project_title") or "未命名项目"
                    project_genre = project_context.get("genre") or project_context.get("project_genre") or "通用题材"
                    recent_project_signatures = project_context.get("recent_project_signatures") or ""
                    recent_project_avoidance = project_context.get("recent_project_avoidance") or ""
                    
                    concept_system_prompt = f"""你是一名擅长网文结构设计的\"创意总监\"，需要为一个新项目生成【故事概念】和初步【世界观设定】。

【已知信息】
- 项目题目：{project_title}
- 题材类型：{project_genre}

【强避重约束】
{recent_project_avoidance or "（暂无近期项目避重清单，但仍需主动回避高频修仙模板。）"}
- 除非用户明确要求，否则不要使用“林尘”作为主角名。
- 除非用户明确要求，不要以“宗门杂役 / 杂役弟子 / 废灵根 / 无灵根少年濒死觉醒”作为标准开局。
- 除非用户明确要求，不要使用“吞噬灵根 / 逆修系统 / 反向修炼系统 / 越被羞辱越变强”作为核心机制。
- 除非用户明确要求，不要把世界命名为“九寰界 / 九寰界域”，也不要直接使用“九大仙宗 / 九大仙域 / 上中下三界”作为世界骨架。
- 除非用户明确要求，不要直接复用“飞升骗局 / 高维收割 / 天外监察者 / 养蛊游戏”作为终局真相模板。
- 如果你的方案与近期项目在“主角名、起点身份、核心能力、世界名称、势力骨架、终局真相”中重合达到 3 项及以上，视为不合格，必须先推翻再重想。

{recent_project_signatures}

【总体要求】
1. 先完成\"故事概念\"六段标准输出，再给出一个与之匹配的高度概括版世界观（可简略）。
2. 保持网文向：强调爽点潜力、冲突强度和持续升级空间。

——————————
一、请先生成【故事概念】，严格按以下六个部分输出（用 Markdown 粗体标记小标题）：

1. **一句话卖点（Logline）**：
- 用一句极具吸引力的网文式概括，包含主角类型、核心能力/优势、主要对手/系统，以及最具爽感的长期目标或爆点。
- 优先使用“主角行动 + 意外结果”句式，例如：“档案修补员篡改禁城时序，反成帝国唯一合法继承人”，而不是单纯罗列设定。

2. **日志标题（短标题）**：
- 用 4–10 个字给出一个便于读者记忆的项目名，偏网文风格。

3. **概念摘要（80–150字）**：
- 简要交代主角身份、初始困境、长期目标、主要阻力，以及世界观的一个独特钩子。

4. **题材与流派（主题材/子流派）**：
- 主题材例如：玄幻修真 / 反乌托邦科幻 / 历史权谋 / 都市奇能 等；

5. **核心标签（3–6个）**：
- 用 3–6 个标签概括作品的核心气质，例如：#系统流 #无敌流 #热血 #成长 #复仇 #智斗

6. **核心冲突与情感基调**：
- 用 100–200 字说明主角面临的长期核心冲突（如：弱小时被欺压 vs 强大后遭围剿），以及全文的整体情绪氛围（如：前期压抑但充满希望，后期高燃且快节奏）。

二、接着生成【世界观设定】（简略版）
- 用 100–200 字给出最核心的世界观设定，包括世界背景、基本规则、主要势力等。

请严格按照上述顺序与小标题输出，不要添加其他额外说明。"""
                    
                    concept_user_prompt = f"""请为以下项目生成故事概念：

【项目题目】：{project_title}
【题材类型】：{project_genre}
【用户初始想法】：{requirement or "暂无"}"""
                    
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
                        task_type="concept",
                    )
                    
                    # 2. 世界观设定生成
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成世界观设定...")
                    
                    world_system_prompt = """你是一名\"世界观架构师\"，需要基于已有的故事概念，生成详细的世界观设定。

【要求】
1. 基于故事概念中的设定线索进行扩展
2. 保持与故事概念的一致性
3. 输出详细的世界观设定，包括世界背景、基本规则、主要势力等"""
                    
                    world_user_prompt = f"""请基于以下故事概念生成世界观设定：

{concept_result}"""
                    
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
                        task_type="worldview",
                    )
                    
                    # 3. 人物设定生成
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
                    # 结构设计阶段 - 流式输出大纲
                    logger.info(f"   🌊 结构设计阶段开始流式输出...")
                    
                    # 获取概念开发阶段的成果
                    concept_data = stage_context.concept
                    world_setting = stage_context.world_setting
                    characters = stage_context.characters
                    
                    await ws_manager.send_stream_start(project_id, stage_enum.value, "正在生成情节大纲...")
                    
                    structure_system_prompt = """你是一名"情节架构师"，需要基于故事概念、世界观和人物设定，设计详细的情节大纲。

【要求】
1. 基于已有的概念、世界观和人物设定进行大纲设计
2. 保持与前期设定的一致性
3. 设计清晰的情节线索和冲突发展
4. 为第一章提供具体的情节指导
5. 输出详细的情节大纲，包括主线情节、支线情节、关键节点等

【输出格式】
请按以下结构输出情节大纲：

## 一、主线情节
- 描述主要情节线索和发展脉络

## 二、第一章大纲
- 章节标题建议
- 开场设定
- 主要情节
- 关键冲突
- 章节结尾

## 三、后续章节规划（可选）
- 概述后续几章的大致发展方向"""
                    
                    structure_user_prompt = f"""请基于以下设定生成情节大纲：

【故事概念】
{concept_data}

【世界观设定】
{world_setting}

【人物设定】
{characters}

【用户需求】
{requirement}"""
                    
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
                        task_type="structure_plot",
                    )
                    
                    result_str = structure_result
                    logger.info(f"   ✅ 结构设计阶段流式输出完成，总长度: {len(result_str)} 字符")
                    
                    # 🔧 将结构设计结果存储到output_data，用于后续保存
                    output_data = {
                        "plot_outline": structure_result
                    }

                elif stage_enum == StageType.REVIEW:
                    # 质量评审阶段
                    chapter_draft = stage_context.chapter_draft

                    # 🆕 网文6维度评审体系（从头创作版本）
                    system_prompt = """你是一位专业的网络小说质量评审官。请使用【网文6维度评审体系】对第一章内容进行评审。

## 📊 网文6维度评审体系

### 1. 爽点效果（权重25%）
- 本章是否有明确的爽点或为后续爽点做了铺垫？
- 第一章作为开篇，是否成功吸引读者？

### 2. 节奏把控（权重20%）
- 信息密度是否适中（不过载也不空洞）？
- 场景转换是否流畅？
- 对话与叙述比例是否合理（建议30-50%对话）？

### 3. 钩子效果（权重15%）
- 章节开头是否吸引人？（是否避免了\"醒来/阳光照进\"的套路开头）
- 章节结尾是否有悬念/钩子？
- 读者是否有\"想点下一章\"的冲动？

### 4. 代入感（权重15%）
- 主角视角是否清晰？
- 读者能否代入主角的处境和情感？
- 世界观建立是否自然、不突兀？

### 5. 文笔流畅度（权重10%）
- 是否有明显的AI痕迹或机械感？
- 对话是否自然、符合人物性格？
- 描写是否生动有画面感？

### 6. 内容一致性（权重15%）
- 人物设定是否与提供的设定一致？
- 世界观规则是否与提供的设定一致？"""

                    user_prompt = f"""请评审以下第一章内容：

【章节内容】
{chapter_draft}

---

【输出格式】
请使用以下格式输出评审报告：

## 📊 网文质量评审报告

**综合评分**：X/10分

### 1. 爽点效果 ⭐⭐⭐
- 评价：...
- 问题：...

### 2. 节奏把控 ⭐⭐⭐
- 评价：...
- 问题：...

### 3. 钩子效果 ⭐⭐⭐
- 开头评价：...
- 结尾评价：...
- 问题：...

### 4. 代入感 ⭐⭐⭐
- 评价：...
- 问题：...

### 5. 文笔流畅度 ⭐⭐⭐
- 评价：...
- 问题：...

### 6. 内容一致性 ⭐⭐⭐
- 评价：...
- 问题：...

### 🔧 具体修改建议（按优先级排序）
1. 【必改】...
2. 【建议】...
3. 【可选】...

### ✨ 亮点
- ..."""

                elif stage_enum == StageType.ITERATION:
                    # 迭代优化阶段
                    chapter_draft = stage_context.chapter_draft
                    review_report = stage_context.review_report

                    # 🆕 增强版迭代优化提示词
                    system_prompt = """你是一位资深的网络小说编辑。请根据评审意见对第一章内容进行优化修改。

优化要求：
1. 保持原有故事框架和情节发展
2. 改进语言表达，增强网文风格
3. 增强细节描写，让场景更有画面感
4. 优化对话内容，使其更自然、更符合人物性格
5. 提升整体可读性和代入感
6. 针对评审中标注【必改】的问题必须修改
7. 标注【建议】的问题尽量修改

【输出格式要求】⚠️
请直接输出优化后的章节内容，格式必须如下：

第一章 章节标题

章节正文内容...

注意：
- 第一行必须是章节标题，格式为"第一章 标题名称"
- 不要包含任何优化说明、修改说明等额外内容
- 只输出优化后的纯净章节内容"""

                    user_prompt = f"""请根据评审意见优化以下第一章：

【原始章节】
{chapter_draft}

【评审意见】
{review_report}

请直接输出优化后的完整章节内容（第一行为章节标题）："""
                else:
                    # 其他阶段不使用流式输出，回退到原有逻辑
                    raise ValueError(f"阶段 {stage_enum.value} 不支持流式输出")

                # 🔥 执行流式 LLM 调用
                logger.info(f"   🌊 开始流式 LLM 调用...")
                # 🆕 按阶段选择模型，避免使用默认deepseek-chat
                stage_model = None
                stage_task_type = None
                stage_model_override = None
                try:
                    from app.core.config import settings
                    default_content_model = getattr(settings, "DEFAULT_CONTENT_MODEL", "qwen3-max")
                except Exception:
                    default_content_model = "qwen3-max"
                
                if stage_enum == StageType.CONTENT:
                    stage_task_type = "chapter"
                    stage_model_override = default_content_model
                elif stage_enum == StageType.REVIEW:
                    stage_task_type = "review"
                elif stage_enum == StageType.ITERATION:
                    stage_task_type = "review"
                stage_model = (
                    resolve_model_for_task(stage_task_type, stage_model_override)
                    if stage_task_type
                    else None
                )
                
                # 对于非CONCEPT阶段，执行流式调用
                if stage_enum in {StageType.CONTENT, StageType.REVIEW, StageType.ITERATION}:
                    result_str = await streaming_service.generate_chapter_streaming(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        on_chunk=on_stream_chunk,
                        temperature=0.7,
                        model=stage_model_override,
                        task_type=stage_task_type,
                    )
                    logger.info(f"   ✅ 流式 LLM 调用完成，生成 {len(result_str)} 字符")

                # 🆕 迭代优化阶段：清理输出内容 + 摘要压缩保护
                if stage_enum == StageType.ITERATION and result_str:
                    # 清理输出内容，移除额外的评审话语
                    def clean_final_output(content: str) -> str:
                        if not content:
                            return content
                        lines = content.split('\n')
                        cleaned_lines = []
                        skip_section = False
                        for line in lines:
                            line_lower = line.lower().strip()
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

                    result_str = clean_final_output(result_str)

                    # 安全保护：如果优化后字数远小于原稿，回退为原始内容
                    original_len = len(chapter_draft or "")
                    optimized_len = len(result_str or "")
                    if original_len >= 500 and optimized_len > 0 and optimized_len < original_len * 0.6:
                        logger.warning(
                            f"   ⚠️ 优化后长度({optimized_len}) 远小于原稿({original_len})，保留原始内容"
                        )
                        result_str = chapter_draft

            except Exception as streaming_error:
                logger.warning(f"   ⚠️  流式 LLM 调用失败，回退到原有逻辑: {streaming_error}")
                use_streaming_llm = False

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
                },
            )

            # 提取结果内容
            output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
            if stage_enum == StageType.ITERATION:
                result_str = output_data.get("revised_content", "") or output_data.get("final_review", "")
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

        db.execute(update_query, {
            "status": "completed",
            "result": result_str,
            "completed_at": utc_now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        logger.info(f"   ✅ 流式任务完成: {task_id}")

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
                    stage_four_status="completed",
                )
            elif stage_enum == StageType.ITERATION:
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    final_version=json.dumps(result_str, ensure_ascii=False),
                    stage_five_status="completed",
                )
        except Exception as save_error:
            logger.error(f"   ⚠️  保存到 project_settings 失败: {save_error}")
            # 🆕 添加详细堆栈跟踪
            import traceback
            logger.error(f"   🔍 堆栈跟踪:\n{traceback.format_exc()}")
            # 🆕 打印关键变量
            logger.error(f"   🔍 stage_enum={stage_enum}, project_id={project_id}, result_str_len={len(result_str) if result_str else 0}")
            logger.error(f"   🔍 output_data={type(output_data)}, output_data_keys={output_data.keys() if isinstance(output_data, dict) else 'not dict'}")

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
                status='completed',
                progress=100,
                message=f'{agent["name"]}已完成'
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

        db.execute(update_query, {
            "status": "failed",
            "error": str(e),
            "completed_at": utc_now().isoformat(),
            "task_id": task_id
        })
        db.commit()

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
        # 🔧 关键修复：关闭独立创建的 db session
        db.close()
        logger.info(f"   📝 db session 已关闭")

