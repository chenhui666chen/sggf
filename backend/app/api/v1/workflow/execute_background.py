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
from app.api.v1.workflow.helpers import _sync_project_title_from_concept
from app.api.v1.workflow.story_helpers import *
from app.api.v1.workflow.story_helpers import (
    _inject_recent_project_novelty_context,
    _sync_real_coordinator_project_context,
)
from app.api.v1.workflow.story_resolve import *
from app.api.v1.workflow.story_resolve import _normalize_concept_stage_characters_for_storage
from app.api.v1.workflow.requirement import _resolve_workflow_requirement
from app.api.v1.workflow.execute_streaming import execute_stage_with_streaming
async def _run_execute_stage_background_serialized(
    task_id: str,
    project_id: int,
    stage_enum: StageType,
    user_id: int,
    db: Session,
    regenerate: bool = False,
    targets: Optional[list[str]] = None,
    feedback: Optional[str] = None,
):
    async with _get_workflow_execution_lock(project_id):
        await execute_stage_background(
            task_id,
            project_id,
            stage_enum,
            user_id,
            db,
            regenerate,
            targets,
            feedback,
        )


async def _run_execute_stage_with_streaming_serialized(
    task_id: str,
    project_id: int,
    stage_enum: StageType,
    user_id: int,
    db: Session,
):
    async with _get_workflow_execution_lock(project_id):
        await execute_stage_with_streaming(task_id, project_id, stage_enum, user_id, db)


async def execute_stage_background(task_id: str, project_id: int, stage_enum: StageType, user_id: int, db: Session, regenerate: bool = False, targets: Optional[list[str]] = None, feedback: Optional[str] = None):
    """后台执行阶段任务"""
    import logging
    from sqlalchemy import text
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"🔥 开始执行后台任务: {task_id}")
        workflow_context_builder = WorkflowContextBuilder(db)
        project_profile = workflow_context_builder.get_project_profile(project_id)
        real_coord = coordinator.get_real_coordinator(project_id)
        
        # 🆕 关键修复：确保协调器已初始化
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
                logger.info("   ✅ 已注入近期项目避重约束")
            except Exception as e:
                logger.warning(f"⚠️ 近期项目避重约束注入失败：{e}")

        # 🆕 确保 project_settings 记录存在（关键修复！）
        if workflow_context_builder.ensure_project_settings_record(project_id):
            logger.info(f"   📝 初始化 project_settings 记录")
            logger.info(f"   ✅ project_settings 记录已创建")
        
        requirement, requirement_source = _resolve_workflow_requirement(db, project_id)
        logger.info(f"   ✅ 用户需求来源: {requirement_source}")
        logger.info(f"   ✅ 当前用户需求: {requirement[:50]}...")
        
        # 🆕 题材与篇幅规划注入（概念阶段首次启动时）
        if stage_enum == StageType.CONCEPT and not regenerate:
            try:
                genre = project_profile.genre
                sub_genre = project_profile.sub_genre
                planned_length_type = project_profile.planned_length_type
                planned_chapters_min = project_profile.planned_chapters_min
                planned_chapters_max = project_profile.planned_chapters_max
                user_outline_plan = project_profile.user_outline_plan

                # 🆕 如果有自定义大纲规划，先解析
                if user_outline_plan and user_outline_plan.strip():
                    logger.info("📝 检测到用户自定义大纲规划，开始解析...")

                    # 调用规划解析Agent
                    if real_coord and hasattr(real_coord, 'parse_outline_plan'):
                        parsed_plan = real_coord.parse_outline_plan(
                            user_outline_plan=user_outline_plan,
                            genre=genre or "",
                            planned_length_type=planned_length_type or ""
                        )

                        if parsed_plan:
                            logger.info(f"✅ 大纲规划解析完成: {list(parsed_plan.keys())}")

                            # 将解析结果注入到项目上下文
                            real_coord.project_context.update({
                                "genre": genre,
                                "sub_genre": sub_genre,
                                "planned_length_type": planned_length_type,
                                "planned_chapters_min": planned_chapters_min,
                                "planned_chapters_max": planned_chapters_max,
                                "parsed_outline_plan": parsed_plan
                            })
                        else:
                            logger.warning("⚠️ 大纲规划解析返回空结果")

                # 将题材篇幅信息添加到需求文本（供prompt使用）
                if genre or planned_length_type:
                    genre_info = f"\n\n【题材与篇幅信息】\n"
                    if genre:
                        genre_info += f"- 题材类型：{genre}"
                        if sub_genre:
                            genre_info += f" / {sub_genre}"
                        genre_info += "\n"
                    if planned_length_type:
                        length_labels = {"short": "短篇", "mid": "中篇", "long": "长篇", "epic": "超长篇"}
                        genre_info += f"- 篇幅规划：{length_labels.get(planned_length_type, planned_length_type)}"
                        if planned_chapters_min and planned_chapters_max:
                            genre_info += f"（{planned_chapters_min}-{planned_chapters_max}章）"
                        genre_info += "\n"
                    
                    requirement += genre_info
                    logger.info(f"✅ 已注入题材与篇幅信息到需求文本")
                        
            except Exception as e:
                logger.warning(f"⚠️ 题材与篇幅信息注入失败: {e}")
                import traceback
                traceback.print_exc()
        
        # 📝 概念阶段附加评审反馈到需求（仅影响生成，不会直接写库）
        if stage_enum == StageType.CONCEPT and feedback:
            requirement = f"{requirement}\n用户评审反馈：{feedback}"

        # 🆕 相互参考约束注入（仅重生时）
        if stage_enum == StageType.CONCEPT and regenerate:
            try:
                existing_context = workflow_context_builder.load_stage_text_context(project_id)
                concept_txt = existing_context.concept
                world_txt = existing_context.world_setting
                char_txt = existing_context.characters

                def clip(s, n=1200):
                    return s[:n] if isinstance(s, str) else ""

                targets_set = set(targets or ['story', 'world'])
                # 重生story：参考世界观+人物
                if 'story' in targets_set and 'world' not in targets_set:
                    requirement += f"\n\n【一致性约束】需与既有世界观与人物设定保持一致。\n【世界观摘要】\n{clip(world_txt)}\n【人物设定摘要】\n{clip(char_txt)}"
                # 重生world：参考故事概念+人物
                elif 'world' in targets_set and 'story' not in targets_set:
                    requirement += f"\n\n【一致性约束】需与既有故事概念与人物设定保持一致。\n【故事概念摘要】\n{clip(concept_txt)}\n【人物设定摘要】\n{clip(char_txt)}"
                # 重生story+world：参考人物
                else:
                    requirement += f"\n\n【一致性约束】需与既有人物设定保持一致。\n【人物设定摘要】\n{clip(char_txt)}"

                logger.info(f"✅ 已注入相互参考约束（targets={list(targets_set) if targets_set else []}，长度={len(requirement)}）")
            except Exception as e:
                logger.warning(f"⚠️ 相互参考约束注入失败: {e}")

        # 🔔 推送阶段开始状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='active',
            progress=0
        )

        # 🆕 推送任务开始进度
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=0,
            message=f"开始执行{stage_enum.value}阶段"
        )
        logger.info(f"   📡 已发送任务开始进度: {task_id}")

        # 🆕 定义每个阶段的 Agent 配置（使用 snake_case 命名规范）
        STAGE_AGENTS = {
            'concept': [
                {'id': 'creative_director', 'name': '创意总监'},
                {'id': 'world_architect', 'name': '世界观架构师'},
                {'id': 'character_designer', 'name': '人物设计师'},
            ],
            'structure': [
                {'id': 'plot_architect', 'name': '情节架构师'},
                {'id': 'event_validator', 'name': '事件验证官'},
            ],
            'content': [
                {'id': 'content_creator', 'name': '内容创作师'},
                {'id': 'style_optimizer', 'name': '文风优化师'},
            ],
            'review': [
                {'id': 'quality_reviewer', 'name': '质量评审官'},
            ],
            'iteration': [
                {'id': 'iteration_coordinator', 'name': '迭代协调官'},
                {'id': 'content_reviser', 'name': '内容修订师'},
                {'id': 'final_reviewer', 'name': '最终审核官'},
            ],
        }

        # 🆕 推送 Agent 开始工作状态
        stage_agents = STAGE_AGENTS.get(stage_enum.value, [])
        # 🔧 概念阶段的重生：仅按目标推送相关Agent（默认 story+world，不包含人物）
        if stage_enum.value == 'concept' and regenerate:
            target_set = set(targets or ['story', 'world'])
            selected_ids = []
            if 'story' in target_set:
                selected_ids.append('creative_director')
            if 'world' in target_set:
                selected_ids.append('world_architect')
            stage_agents = [a for a in stage_agents if a['id'] in selected_ids]
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
        logger.info(f"   📡 已发送 {len(stage_agents)} 个 Agent 开始状态")

        # 🆕 设置进度回调（用于任务分块执行）
        async def progress_callback(proj_id: int, t_id: str, progress: int, message: str):
            """进度回调函数，通过WebSocket发送进度更新"""
            try:
                await ws_manager.send_task_progress(
                    project_id=proj_id,
                    task_id=t_id,
                    progress=progress,
                    message=message
                )
                # 🆕 同步更新所有 Agent 进度
                for agent in stage_agents:
                    await ws_manager.send_agent_status(
                        project_id=proj_id,
                        stage=stage_enum.value,
                        agent_id=agent['id'],
                        agent_name=agent['name'],
                        status='working',
                        progress=progress,
                        message=message
                    )
                logger.info(f"   📡 进度推送: {progress}% - {message}")
            except Exception as e:
                logger.error(f"   ⚠️  进度推送失败: {e}")

        # 🆕 为 coordinator 设置进度回调（如果支持）
        if hasattr(coordinator, 'set_progress_callback'):
            coordinator.set_progress_callback(progress_callback, task_id, project_id)  # type: ignore
            logger.info(f"   ✅ 已启用任务分块执行模式")

        # 🔧 将重生信息注入到真实协调器的 project_context（供概念阶段条件执行使用）
        if stage_enum == StageType.CONCEPT:
            real_coord = coordinator.get_real_coordinator(project_id)
            if real_coord and hasattr(real_coord, 'project_context'):
                real_coord.project_context["regenerate"] = regenerate
                real_coord.project_context["regenerate_targets"] = targets or []
                logger.info(f"   🎯 概念阶段重生信息已注入: regenerate={regenerate}, targets={targets}")

        # 🔧 关键修复：将 requirement 传递给 execute_stage
        stage_output = await coordinator.execute_stage(
            stage_enum,
            {
                "project_id": project_id, 
                "user_id": user_id,
                "requirement": requirement,  # ✅ 传递真实的用户需求
                "regenerate": regenerate,
                "targets": targets,
                "feedback": feedback,
            },
        )
        
        # 更新任务状态为完成
        update_query = text("""
            UPDATE generation_history
            SET status = :status, result = :result, completed_at = :completed_at
            WHERE task_id = :task_id
        """)

        # 🔥 关键修复：根据阶段类型提取正确的内容字段
        output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
        if stage_enum == StageType.ITERATION:
            # 迭代优化阶段：提取 revised_content
            result_str = output_data.get("revised_content", "") or output_data.get("final_review", "")
            logger.info(f"   📝 迭代优化结果字数: {len(result_str) if result_str else 0}")
        elif stage_enum == StageType.CONTENT:
            # 内容创作阶段：提取 content 或 chapters
            result_str = output_data.get("content", "") or output_data.get("chapters", "")
            logger.info(f"   📝 章节内容字数: {len(result_str) if isinstance(result_str, str) else 0}")
        elif stage_enum == StageType.REVIEW:
            # 质量评审阶段：提取 review
            result_str = output_data.get("review", "")
            logger.info(f"   📝 评审报告字数: {len(result_str) if result_str else 0}")
        else:
            # 其他阶段：使用整个输出的字符串表示
            result_str = str(stage_output.output) if stage_output.output else ""

        db.execute(update_query, {
            "status": "completed",
            "result": result_str,
            "completed_at": utc_now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        logger.info(f"   ✅ 任务完成: {task_id}")
        
        # 🆕 保存阶段输出到 project_settings（关键修复！）
        try:
            if stage_enum == StageType.CONCEPT:
                # 保存概念开发结果（支持评审/重生的目标字段选择）
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                existing_storage_state = workflow_context_builder.load_concept_storage_state(project_id)
                existing_concept_val = existing_storage_state.concept_value
                existing_world_val = existing_storage_state.world_setting_value
                existing_characters_val = existing_storage_state.characters_value

                targets_set = set(targets or [])
                is_regen = bool(regenerate)

                # 计算要保存的字段：非重生则全部覆盖；重生则按目标覆盖
                concept_to_save = output_data.get("concept", "") if not is_regen or ("story" in targets_set) else existing_concept_val
                world_to_save = output_data.get("worldview", output_data.get("world_setting", "")) if not is_regen or ("world" in targets_set) else existing_world_val
                characters_to_save = output_data.get("characters", []) if not is_regen else existing_characters_val
                if not is_regen:
                    characters_to_save = _normalize_concept_stage_characters_for_storage(
                        project_id,
                        characters_to_save,
                        concept_text=str(concept_to_save or ""),
                        world_setting_text=str(world_to_save or ""),
                    )

                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    concept=json.dumps(concept_to_save, ensure_ascii=False),
                    world_setting=json.dumps(world_to_save, ensure_ascii=False),
                    characters=json.dumps(characters_to_save, ensure_ascii=False),
                    stage_one_status="completed",
                )
                logger.info(f"   💾 已保存概念开发结果到 project_settings（重生={is_regen}, targets={list(targets_set) if targets_set else []}）")
                
                # 🆕 从故事概念中提取日志标题，自动更新项目title
                if concept_to_save and isinstance(concept_to_save, str):
                    try:
                        _sync_project_title_from_concept(db, project_id, concept_to_save)
                    except Exception as e:
                        logger.warning(f"   ⚠️  提取日志标题失败: {e}")
                
                # 🆕 自动解析人物卡并同步到结构化characters表
                if characters_to_save and isinstance(characters_to_save, str):
                    await ws_manager.send_task_progress(
                        project_id=project_id,
                        task_id=task_id,
                        progress=85,
                        message="🔄 正在同步人物卡..."
                    )
                    
                    sync_result = {"parsed": 0, "created": 0, "updated": 0, "skipped": 0}
                    try:
                        from app.services.character_parser import parse_and_sync_characters
                        
                        sync_result = parse_and_sync_characters(
                            project_id=project_id,
                            characters_text=characters_to_save,
                            db_session=db
                        )
                        logger.info(f"   🔄 人物卡同步完成: 解析 {sync_result['parsed']} 个, "
                                   f"创建 {sync_result['created']} 个, 更新 {sync_result['updated']} 个")
                    except Exception as e:
                        logger.warning(f"   ⚠️  自动同步人物卡失败: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 🆕 同步概念开发结果到向量库
                try:
                    from app.services.vector_sync import sync_to_vector_db, upsert_character_to_vector_db, upsert_setting_to_vector_db
                    from app.models.character import Character
                    from app.models.setting import SettingItem
                    
                    logger.info(f"   🔄 开始同步概念开发结果到向量库...")
                    
                    # 同步世界观设定
                    if world_to_save and isinstance(world_to_save, str) and world_to_save.strip():
                        sync_to_vector_db(
                            kb_type="world",
                            name="世界观设定",
                            content=world_to_save,
                            metadata={
                                "project_id": str(project_id),
                                "title": "世界观设定",
                                "category": "world_setting"
                            }
                        )
                        logger.info(f"   ✅ 已同步世界观设定到向量库")
                    
                    # 同步人物设定(从数据库中查询已解析的人物)
                    characters_in_db = db.query(Character).filter(Character.project_id == project_id).all()
                    if characters_in_db:
                        for char in characters_in_db:
                            # 使用Character模型的实际字段
                            char_content = f"""
人物名称: {char.name}
故事立场: {char.role or '未设定'}
角色定位: {getattr(char, 'role_position', None) or '未设定'}
所属势力: {char.faction or '未设定'}
状态: {char.life_status or '未知'}
简介: {char.summary or ''}
详细信息: {char.profile or ''}
""".strip()
                            
                            upsert_character_to_vector_db(
                                character_id=char.id,
                                character_name=char.name,
                                content=char_content,
                                project_id=project_id,
                                metadata={
                                    "character_id": str(char.id),
                                    "name": char.name,
                                    "role": char.role or '',
                                    "role_position": getattr(char, "role_position", None) or "",
                                }
                            )
                        logger.info(f"   ✅ 已同步 {len(characters_in_db)} 个人物到向量库")
                    
                    # 同步已识别的设定项（通过 SettingCollection 关联查询）
                    from app.models.setting import SettingCollection
                    collections_in_db = db.query(SettingCollection).filter(SettingCollection.project_id == project_id).all()
                    settings_count = 0
                    for collection in collections_in_db:
                        for setting in collection.items:
                            # 构建设定完整描述
                            setting_content = f"""
**设定名称**: {setting.name}
**类别**: {collection.category or ''}
**详细描述**: {setting.content or ''}
""".strip()
                            
                            upsert_setting_to_vector_db(
                                setting_id=setting.id,
                                setting_name=setting.name,
                                content=setting_content,
                                project_id=project_id,
                                category=collection.category or 'unknown',
                                metadata={
                                    "setting_id": str(setting.id),
                                    "name": setting.name,
                                    "category": collection.category or ''
                                }
                            )
                            settings_count += 1
                    if settings_count > 0:
                        logger.info(f"   ✅ 已同步 {settings_count} 个设定项到向量库")
                        
                except Exception as vector_error:
                    logger.warning(f"   ⚠️  同步到向量库失败: {vector_error}")
                    import traceback
                    traceback.print_exc()
            
            elif stage_enum == StageType.STRUCTURE:
                # 保存结构设计结果
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                plot_outline_content = output_data.get("plot_outline", "")
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    plot_outline=json.dumps(plot_outline_content, ensure_ascii=False),
                    stage_two_status="completed",
                )
                logger.info(f"   💾 已保存结构设计结果到 project_settings")
                
                # 🆕 同步情节大纲到向量库
                try:
                    from app.services.vector_sync import sync_to_vector_db
                    
                    if plot_outline_content and isinstance(plot_outline_content, str) and plot_outline_content.strip():
                        sync_to_vector_db(
                            kb_type="plot",
                            name="情节大纲",
                            content=plot_outline_content,
                            metadata={
                                "project_id": str(project_id),
                                "title": "情节大纲",
                                "type": "plot_outline"
                            }
                        )
                        logger.info(f"   ✅ 已同步情节大纲到向量库")
                except Exception as vector_error:
                    logger.warning(f"   ⚠️  同步情节大纲到向量库失败: {vector_error}")
                
                # 🎉 异步触发体系自动检测（不阻塞主流程）
                asyncio.create_task(
                    trigger_auto_system_detection(
                        project_id=project_id,
                        content=plot_outline_content if isinstance(plot_outline_content, str) else json.dumps(plot_outline_content),
                        content_type="outline",
                        db=db
                    )
                )
            
            elif stage_enum == StageType.CONTENT:
                # 保存内容创作结果
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    chapter_draft=json.dumps(output_data.get("content", output_data.get("chapters", "")), ensure_ascii=False),
                    stage_three_status="completed",
                )
                logger.info(f"   💾 已保存内容创作结果到 project_settings")
            
            elif stage_enum == StageType.REVIEW:
                # 保存质量评审结果
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    review_report=json.dumps(output_data.get("review", ""), ensure_ascii=False),
                    stage_four_status="completed",
                )
                logger.info(f"   💾 已保存质量评审结果到 project_settings")
            
            elif stage_enum == StageType.ITERATION:
                # 保存迭代优化结果
                # 🔥 关键修复：直接使用已经解析好的 result_str，而不是重新解析
                final_version_content = result_str  # result_str 已经是正确的 revised_content
                workflow_context_builder.update_project_settings_fields(
                    project_id,
                    final_version=json.dumps(final_version_content, ensure_ascii=False),
                    stage_five_status="completed",
                )
                logger.info(f"   💾 已保存迭代优化结果到 project_settings，内容字数: {len(final_version_content) if final_version_content else 0}")
        
        except Exception as save_error:
            logger.error(f"   ⚠️  保存到 project_settings 失败: {save_error}")
            # 不影响主流程，继续执行
        
        # 🆕 推送任务完成通知（关键！前端依赖此事件停止轮询）
        await ws_manager.send_task_complete(
            project_id=project_id,
            task_id=task_id,
            result={"output": result_str}
        )
        logger.info(f"   📡 已发送任务完成通知: {task_id}")

        # 🆕 推送 Agent 完成状态
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
        logger.info(f"   📡 已发送 {len(stage_agents)} 个 Agent 完成状态")

        # 🔔 推送阶段完成状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='completed',
            output=result_str,
            progress=100
        )

        # 🆕 保存记忆到数据库（统一存储方案）
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
                # 获取用户ID
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
            logger.info(f"   💾 已保存阶段记忆到数据库: {stage_enum.value}")
        except Exception as mem_error:
            logger.error(f"   ⚠️  保存记忆失败: {mem_error}")
            # 不影响主流程

    except Exception as e:
        logger.error(f"❌ 后台任务失败: {task_id}, 错误: {str(e)}")
        try:
            db.rollback()
        except Exception as rollback_error:
            logger.warning(f"⚠️  后台任务失败后回滚事务失败: {rollback_error}")
        
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
        
        # 🆕 推送任务失败通知（关键！前端依赖此事件停止轮询）
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e)
        )
        logger.info(f"   📡 已发送任务失败通知: {task_id}")
        
        # 🔔 推送错误状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='error',
            progress=0
        )

