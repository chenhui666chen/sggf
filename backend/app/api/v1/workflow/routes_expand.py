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

from app.api.v1.workflow import router
from app.api.v1.workflow.schemas import *
from app.api.v1.workflow.helpers import *
from app.api.v1.workflow.story_helpers import *
from app.api.v1.workflow.story_resolve import *

from app.schemas.story_expansion import (
    StoryExpansionAnalysisPayload,
    StoryExpansionAnalysisRouteResponse,
    StoryExpansionStartResponse,
    StoryExpansionTaskResultResponse,
)

@router.get("/epic-framework-state/{project_id}")
async def get_epic_framework_state(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🔍 检测长篇框架状态
    
    返回:
    {
        "has_framework": true/false,
        "total_volumes": 17,
        "expanded_volumes": [1, 3, 5],
        "framework_generated_at": "2025-12-12T10:00:00"
    }
    """
    import logging
    from app.services.outline_merger import detect_framework_state
    from sqlalchemy import text
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"🔍 检测长篇框架状态，项目ID: {project_id}")
        
        # 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == project_id) & (Project.user_id == current_user.id)
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        
        # 读取框架数据
        epic_framework_state = WorkflowContextBuilder(db).load_epic_framework_state(project_id)
        
        if not (
            epic_framework_state.epic_framework
            or epic_framework_state.framework_generated_at
            or epic_framework_state.plot_outline
            or epic_framework_state.epic_volumes_detail
        ):
            logger.info(f"   ✅ 未找到项目设置，返回空状态")
            return {
                "has_framework": False,
                "total_volumes": 0,
                "expanded_volumes": [],
                "framework_generated_at": None
            }
        
        epic_framework = epic_framework_state.epic_framework
        framework_generated_at = epic_framework_state.framework_generated_at
        plot_outline = epic_framework_state.plot_outline or ""
        epic_volumes_detail_json = epic_framework_state.epic_volumes_detail or ""
        
        # 🌟 新架构：使用 parse_epic_volumes_json 和 get_volume_state
        from app.services.outline_merger import parse_epic_volumes_json, get_volume_state
        
        # 解析卷数据
        volumes_data = parse_epic_volumes_json(epic_volumes_detail_json)
        
        # 如果新架构有数据，直接使用
        if volumes_data.get("volumes"):
            state = get_volume_state(volumes_data)
            logger.info(f"   ✅ 新架构状态: has_framework={state['hasFramework']}, total_volumes={state['totalVolumes']}, expanded_volumes={state['expandedVolumes']}")
            return {
                "has_framework": state["hasFramework"],
                "total_volumes": state["totalVolumes"],
                "expanded_volumes": state["expandedVolumes"],
                "framework_generated_at": state["frameworkGeneratedAt"] or framework_generated_at
            }
        
        # 🔄 回退：老结构或空数据，使用原有逻辑
        import re
        has_framework = bool(framework_generated_at) or bool(epic_framework and len(epic_framework) > 100)
        
        total_volumes = 0
        yaml_match = re.search(r'总卷数:\s*(\d+)', plot_outline)
        if yaml_match:
            total_volumes = int(yaml_match.group(1))
        else:
            vol_matches = re.findall(r'第\s*(\d+)\s*卷', plot_outline or epic_framework or '')
            if vol_matches:
                total_volumes = max(int(v) for v in vol_matches)
        
        # 老格式兼容：从旧JSON读取已扩展卷
        from app.services.outline_merger import parse_volumes_detail_json
        expanded_volumes = []
        if epic_volumes_detail_json:
            try:
                volumes_dict = parse_volumes_detail_json(epic_volumes_detail_json)
                expanded_volumes = sorted(volumes_dict.keys())
            except Exception as e:
                logger.warning(f"   ⚠️  解析 epic_volumes_detail 失败: {e}")
        
        logger.info(f"   ✅ 框架状态(回退): has_framework={has_framework}, total_volumes={total_volumes}, expanded_volumes={expanded_volumes}")
        
        return {
            "has_framework": has_framework,
            "total_volumes": total_volumes,
            "expanded_volumes": expanded_volumes,
            "framework_generated_at": framework_generated_at
        }
        
    except Exception as e:
        logger.error(f"❌ 检测框架状态失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/expand-story/analysis", response_model=StoryExpansionAnalysisRouteResponse)
async def analyze_expand_story(
    request: ExpandStoryRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分析协同扩展请求，返回推荐方向、模式和模型适配信息。"""
    try:
        _validate_expand_story_request(request, allow_empty_targets_for_analysis=True)

        _ensure_project_owned(request.project_id, current_user.id, db)
        _validate_story_framework_mode_switch(request, db)

        request = _normalize_story_request_text_fields(request)
        preview = _build_story_written_chapter_preview(request, db)
        analysis_request = request.model_copy(
            update={
                "current_outline": preview["effective_outline"],
                "current_chapter_count": preview["effective_current_chapter_count"],
            }
        )
        analysis_bundle = _build_story_expansion_analysis(
            request=analysis_request,
            db=db,
        )
        analysis = dict(analysis_bundle["analysis"])
        warnings = list(analysis.get("warnings") or [])
        warnings.extend(preview.get("warnings") or [])
        analysis["warnings"] = list(dict.fromkeys(item for item in warnings if item))
        analysis["written_chapter_context"] = {
            "applied": bool(preview.get("applied")),
            "written_chapter_count": int(preview.get("written_chapter_count") or 0),
            "preserve_written_mode": request.preserve_written_mode,
        }

        response_payload = StoryExpansionAnalysisRouteResponse.model_validate(
            {
                "success": True,
                "analysis": StoryExpansionAnalysisPayload.model_validate(analysis).model_dump(
                    mode="python",
                    exclude_none=True,
                ),
            }
        )
        return response_payload.model_dump(mode="python", exclude_none=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 协同扩展预检分析失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/expand-story", response_model=StoryExpansionStartResponse)
async def expand_story(
    request: ExpandStoryRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """协同拓展大纲与人物，采用真正的 delta 策略异步执行。"""
    try:
        _validate_expand_story_request(request)

        _ensure_project_owned(request.project_id, current_user.id, db)
        _validate_story_framework_mode_switch(request, db)

        task_id = f"expand-story-{uuid.uuid4()}"

        _create_story_expansion_history_record(
            db,
            project_id=request.project_id,
            task_id=task_id,
        )

        _enqueue_story_expansion_task(
            task_id=task_id,
            request=request,
            user_id=current_user.id,
        )

        response_payload = StoryExpansionStartResponse.model_validate(
            _build_task_start_response(
                task_id=task_id,
                message="协同拓展任务已启动，正在后台分析人物与大纲的增量缺口...",
            )
        )
        return response_payload.model_dump(mode="python", exclude_none=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 启动协同拓展任务失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


async def execute_expand_story_task(
    task_id: str,
    project_id: int,
    user_id: int,
    current_outline: str,
    world_setting: str,
    characters: str,
    current_chapter_count: int,
    current_character_count: int,
    target_total_chapters: Optional[int],
    target_total_characters: Optional[int],
    strategy: str,
    intent: str,
    enable_auto_supplement: bool,
    expansion_mode: str,
    total_volumes: Optional[int],
    total_chapters_min: Optional[int],
    total_chapters_max: Optional[int],
    target_volume_index: Optional[int],
    volume_chapters_min: Optional[int],
    volume_chapters_max: Optional[int],
    preserve_written_mode: str,
    volume_character_increment: Optional[int] = None,
    reset_epic_framework: bool = False,
):
    """后台执行协同拓展任务。"""
    from app.db.base import SessionLocal

    logger.info(f"🚀 开始执行后台任务: {task_id}, 协同拓展")
    db = SessionLocal()

    try:
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=0,
            message="🧭 开始分析大纲与人物的协同缺口...",
        )

        prepared_request_bundle = await _prepare_story_execution_request(
            ExpandStoryRequest(
                project_id=project_id,
                current_outline=current_outline,
                world_setting=world_setting,
                characters=characters,
                current_chapter_count=current_chapter_count,
                current_character_count=current_character_count,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                intent=intent,
                enable_auto_supplement=enable_auto_supplement,
                expansion_mode=expansion_mode,
                total_volumes=total_volumes,
                total_chapters_min=total_chapters_min,
                total_chapters_max=total_chapters_max,
                target_volume_index=target_volume_index,
                volume_chapters_min=volume_chapters_min,
                volume_chapters_max=volume_chapters_max,
                volume_character_increment=volume_character_increment,
                preserve_written_mode=preserve_written_mode,
                reset_epic_framework=reset_epic_framework,
            ),
            db,
        )
        prepared_request = prepared_request_bundle["request"]
        _validate_story_framework_mode_switch(prepared_request, db)
        execution_context_warnings = list(prepared_request_bundle.get("warnings") or [])
        written_chapter_context = {
            "applied": bool(prepared_request_bundle.get("applied")),
            "written_chapter_count": int(prepared_request_bundle.get("written_chapter_count") or 0),
            "preserve_written_mode": preserve_written_mode,
        }

        analysis_bundle = _build_story_expansion_analysis(
            request=prepared_request,
            db=db,
        )
        coordinator = analysis_bundle["coordinator"]
        combined_world_setting = analysis_bundle["combined_world_setting"]
        analysis = analysis_bundle["analysis"]
        volume_detail_config = analysis_bundle.get("volume_detail_config")
        effective_target_total_chapters = analysis.get("effective_target_chapter_count")
        effective_target_total_characters = analysis.get("effective_target_character_count")
        effective_strategy = analysis.get("effective_strategy") or strategy
        effective_intent = analysis.get("effective_intent") or intent
        effective_expansion_mode = analysis.get("effective_expansion_mode") or expansion_mode
        epic_config = analysis.get("epic_config") or _resolve_story_epic_config(
            ExpandStoryRequest(
                project_id=project_id,
                current_outline=current_outline,
                world_setting=world_setting,
                characters=characters,
                current_chapter_count=current_chapter_count,
                current_character_count=current_character_count,
                target_total_chapters=target_total_chapters,
                target_total_characters=target_total_characters,
                strategy=strategy,
                intent=intent,
                enable_auto_supplement=enable_auto_supplement,
                expansion_mode=expansion_mode,
                total_volumes=total_volumes,
                total_chapters_min=total_chapters_min,
                total_chapters_max=total_chapters_max,
                target_volume_index=target_volume_index,
                volume_chapters_min=volume_chapters_min,
                volume_chapters_max=volume_chapters_max,
                volume_character_increment=volume_character_increment,
                preserve_written_mode=preserve_written_mode,
            )
        )
        warnings = list(analysis.get("warnings") or [])
        warnings.extend(execution_context_warnings)
        analysis["warnings"] = list(dict.fromkeys(item for item in warnings if item))
        analysis["written_chapter_context"] = written_chapter_context
        analysis = StoryExpansionAnalysisPayload.model_validate(analysis).model_dump(
            mode="python",
            exclude_none=True,
        )
        auto_supplement_plan = (
            analysis.get("auto_supplement")
            if enable_auto_supplement and prepared_request.target_total_characters is None
            else None
        )

        mode_info = {
            "mode": analysis.get("execution_mode", "delta"),
            "reason": analysis.get("execution_mode_reason", ""),
        }
        mode_messages = {
            "delta": "🧠 正在生成单轮协同 delta 计划...",
            "iterative": "🧠 正在编排分轮协同扩展计划...",
            "epic": "🧠 正在规划长篇框架优先的协同扩展...",
            "volume_detail": "🧠 正在编排单卷细化协同计划...",
        }

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=18,
            message=mode_messages.get(mode_info.get("mode", "delta"), "🧠 正在生成协同扩展计划..."),
        )

        result = await asyncio.to_thread(
            coordinator.execute,
            current_outline=prepared_request.current_outline,
            characters=characters,
            world_setting=combined_world_setting,
            target_total_chapters=effective_target_total_chapters,
            target_total_characters=effective_target_total_characters,
            strategy=effective_strategy,
            expansion_mode=effective_expansion_mode,
            epic_config=epic_config,
            volume_detail_config=volume_detail_config,
            auto_supplement_plan=auto_supplement_plan,
        )

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=72,
            message="💾 正在保存协同拓展结果...",
        )

        workflow_context_builder = WorkflowContextBuilder(db)
        update_fields = {
            "plot_outline": result["plot_outline"],
            "characters": result["characters"],
        }
        if result.get("execution_mode") == "epic" and result.get("epic_framework"):
            update_fields.update(
                {
                    "epic_framework": result.get("epic_framework", result["plot_outline"]),
                    "epic_volumes_detail": result.get("epic_volumes_detail", ""),
                    "epic_framework_generated_at": utc_now().isoformat(),
                }
            )
        elif result.get("execution_mode") == "volume_detail" and result.get("epic_framework"):
            update_fields.update(
                {
                    "epic_framework": result.get("epic_framework", result["plot_outline"]),
                    "epic_volumes_detail": result.get("epic_volumes_detail", ""),
                }
            )
        elif reset_epic_framework:
            update_fields.update(
                {
                    "epic_framework": None,
                    "epic_volumes_detail": None,
                    "epic_framework_generated_at": None,
                }
            )

        workflow_context_builder.update_project_settings_fields(project_id, **update_fields)

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=84,
            message="👥 正在同步人物卡与关系...",
        )

        sync_result = {"parsed": 0, "created": 0, "updated": 0, "skipped": 0}
        relationship_result = {"parsed": 0, "saved": 0, "characters_updated": 0}

        try:
            from app.services.character_parser import (
                parse_and_sync_characters,
                parse_and_sync_relationships,
            )

            character_sync_text, character_sync_source = _select_story_character_sync_source(result)
            if character_sync_text:
                sync_result = parse_and_sync_characters(
                    project_id=project_id,
                    characters_text=character_sync_text,
                    db_session=db,
                )
                logger.info(
                    "✅ 协同拓展人物卡同步完成：project_id=%s, source=%s, parsed=%s, created=%s, updated=%s",
                    project_id,
                    character_sync_source,
                    sync_result.get("parsed", 0),
                    sync_result.get("created", 0),
                    sync_result.get("updated", 0),
                )
            else:
                logger.info(
                    "ℹ️ 协同拓展未检测到可解析人物卡，跳过同步：project_id=%s",
                    project_id,
                )

            if result.get("character_relationships"):
                relationship_result = parse_and_sync_relationships(
                    project_id=project_id,
                    relationships_text=result["character_relationships"],
                    db_session=db,
                )
                sync_result["relationships"] = relationship_result
        except Exception as sync_error:
            logger.warning(f"⚠️ 协同拓展后同步人物失败: {sync_error}")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=92,
            message="📚 正在同步向量库...",
        )

        try:
            from app.models.character import Character
            from app.services.vector_sync import sync_to_vector_db, upsert_character_to_vector_db

            if result["plot_outline"]:
                sync_to_vector_db(
                    kb_type="plot",
                    name=f"project_{project_id}_plot_outline",
                    content=result["plot_outline"],
                    metadata={
                        "project_id": str(project_id),
                        "type": "plot_outline",
                    },
                )

            characters_in_db = db.query(Character).filter(Character.project_id == project_id).all()
            for char in characters_in_db:
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
                        "role": char.role or "",
                        "role_position": getattr(char, "role_position", None) or "",
                    },
                )
        except Exception as vector_error:
            logger.warning(f"⚠️ 协同拓展后同步向量库失败: {vector_error}")

        before_stats = result.get("validation_before") or {}
        after_stats = result.get("validation_after") or {}
        final_chapter_count = _resolve_story_result_count(
            reported_count=result.get("current_chapter_count"),
            parsed_count=_estimate_chapter_count_from_text(result.get("plot_outline", "")),
            validation_count=after_stats.get("chapter_count"),
            fallback_count=prepared_request.current_chapter_count,
        )
        final_character_count = _resolve_story_result_count(
            reported_count=result.get("current_character_count"),
            parsed_count=_estimate_character_count_from_text(result.get("characters", "")),
            validation_count=after_stats.get("character_count"),
            fallback_count=current_character_count,
        )
        normalized_character_sync, character_sync_warnings = _normalize_story_character_sync_result(sync_result)
        alignment_warnings = list(result.get("alignment_warnings", []))
        alignment_warnings.extend(character_sync_warnings)
        alignment_warnings = list(dict.fromkeys(str(item).strip() for item in alignment_warnings if str(item).strip()))
        result_plan = result.get("plan") or {}

        task_result_payload = StoryExpansionTaskResultResponse.model_validate(
            {
                "expanded_outline": result["plot_outline"],
                "all_characters": result["characters"],
                "outline_delta": result.get("outline_delta", ""),
                "character_delta": result.get("character_delta", ""),
                "character_relationships": result.get("character_relationships", ""),
                "outline_ops": _normalize_story_result_outline_ops(result),
                "execution_mode": result.get("execution_mode", mode_info.get("mode", "delta")),
                "execution_mode_reason": result.get("execution_mode_reason", mode_info.get("reason", "")),
                "execution_rounds": result.get("execution_rounds", []),
                "new_characters": result.get("new_characters", []),
                "alignment_repairs": result.get("alignment_repairs", []),
                "story_strategy": result.get("strategy", effective_strategy),
                "story_intent": effective_intent,
                "story_expansion_mode": effective_expansion_mode,
                "story_preserve_written_mode": preserve_written_mode,
                "written_chapter_context": written_chapter_context,
                "volume_index": result.get("volume_index"),
                "volume_chapter_range": result.get("volume_chapter_range"),
                "coordination_summary": result.get("coordination_summary", ""),
                "current_chapter_count": final_chapter_count,
                "target_chapter_count": (
                    result_plan.get("target_chapter_count")
                    or effective_target_total_chapters
                    or target_total_chapters
                    or final_chapter_count
                ),
                "current_character_count": final_character_count,
                "target_character_count": (
                    result_plan.get("target_character_count")
                    or effective_target_total_characters
                    or target_total_characters
                    or final_character_count
                ),
                "validation_before": before_stats,
                "validation_after": after_stats,
                "alignment_warnings": alignment_warnings,
                "character_sync": normalized_character_sync,
                "stop_reasons": result.get("stop_reasons", []),
                "expansion_analysis": analysis,
                "epic_total_volumes": result.get("epic_total_volumes"),
                "epic_chapter_range": result.get("epic_chapter_range"),
                "message": (
                    f"✅ 协同拓展完成！章节 {before_stats.get('chapter_count', prepared_request.current_chapter_count)}"
                    f" → {final_chapter_count}，人物 {before_stats.get('character_count', current_character_count)}"
                    f" → {final_character_count}"
                ),
            }
        ).model_dump(mode="python", exclude_none=True)

        _update_story_expansion_history_record(
            db,
            task_id=task_id,
            status="completed",
            result=task_result_payload,
        )
        await ws_manager.send_task_complete(
            project_id=project_id,
            task_id=task_id,
            result=task_result_payload,
        )

    except Exception as e:
        logger.error(f"❌ 后台协同拓展失败: {str(e)}")
        _update_story_expansion_history_record(
            db,
            task_id=task_id,
            status="failed",
            error=str(e),
        )
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e),
        )
    finally:
        db.close()


