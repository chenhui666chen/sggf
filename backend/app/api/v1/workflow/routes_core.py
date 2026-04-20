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
from app.api.v1.workflow.lock_manager import _get_workflow_execution_lock
from app.api.v1.workflow.helpers import *
from app.api.v1.workflow.story_helpers import *
from app.api.v1.workflow.story_resolve import *
from app.api.v1.workflow.requirement import *
from app.api.v1.workflow.execute_background import execute_stage_background
from app.api.v1.workflow.execute_streaming import execute_stage_with_streaming

@router.post("/start")
async def start_workflow(
    request: StartWorkflowRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    启动工作流程

    请求体:
    {
        "project_id": 1,
        "requirement": "创作需求描述"
    }
    """
    import logging
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info("🚀 开始启动工作流程...")
        logger.info(f"   用户ID: {current_user.id}")
        logger.info(f"   项目ID: {request.project_id}")
        logger.info(f"   需求: {request.requirement[:50]}...")
        
        project_id = request.project_id
        requirement = request.requirement
        # 目标章节数配置（可选）
        target_chapter_count = request.target_chapter_count
        if target_chapter_count is None or target_chapter_count <= 0:
            target_chapter_count = 100

        if not project_id or not requirement:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing project_id or requirement",
            )

        # 初始化Agent
        logger.info("   正在初始化Agent...")
        await coordinator.initialize_agents()
        logger.info("   ✅ Agent初始化完成")
        logger.info(f"   目标章节数: {target_chapter_count}")

        # 🔧 关键修复：保存requirement到数据库
        from sqlalchemy import text
        from datetime import datetime

        # 🆕 如果是重新开始模式，清空所有旧数据
        cleared_data = {"chapters": 0, "settings": False}
        if request.clear_existing:
            logger.info("🗑️  重新开始模式：开始清空现有内容...")
            try:
                # 1. 删除所有章节
                delete_chapters_query = text("DELETE FROM chapters WHERE project_id = :project_id")
                result = db.execute(delete_chapters_query, {"project_id": project_id})
                cleared_data["chapters"] = result.rowcount
                logger.info(f"   ✅ 已删除 {cleared_data['chapters']} 个章节")

                # 2. 清空 project_settings 中的旧内容
                WorkflowContextBuilder(db).update_project_settings_fields(
                    project_id,
                    concept=None,
                    world_setting=None,
                    characters=None,
                    plot_outline=None,
                    chapter_draft=None,
                    review_report=None,
                    final_version=None,
                    epic_framework=None,
                    epic_volumes_detail=None,
                    epic_framework_generated_at=None,
                    stage_one_status="pending",
                    stage_two_status="pending",
                    stage_three_status="pending",
                    stage_four_status="pending",
                    stage_five_status="pending",
                )
                cleared_data["settings"] = True
                logger.info(f"   ✅ 已清空项目设定与阶段状态（概念、大纲、世界观、人物、长篇框架等）")

                # 4. 清理记忆管理
                try:
                    clear_memory_query = text("""
                        UPDATE memory SET current_chapter = NULL
                        WHERE project_id = :project_id
                    """)
                    db.execute(clear_memory_query, {"project_id": project_id})
                    logger.info(f"   ✅ 已清理记忆管理")
                except Exception as e:
                    logger.warning(f"   ⚠️  记忆清理失败（非致命）: {e}")

                db.commit()
                logger.info("✅ 重新开始模式：所有旧内容已清空")

            except Exception as e:
                logger.error(f"❌ 清空旧内容失败: {e}")
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"清空旧内容失败: {str(e)}"
                )

        try:
            storage_mode = _save_workflow_requirement(
                db=db,
                project_id=project_id,
                user_id=current_user.id,
                requirement=requirement,
            )

            # 🆕 同时更新 projects 表的 description 字段（关键修复！）
            update_project_query = text(
                "UPDATE projects SET description = :description WHERE id = :project_id"
            )
            db.execute(update_project_query, {
                "description": requirement,
                "project_id": project_id
            })

            db.commit()
            logger.info(f"   ✅ 工作流会话已保存到数据库（模式: {storage_mode}）")
            logger.info(f"   ✅ 项目描述已更新为用户需求")
        except Exception as e:
            logger.error(f"   ⚠️  保存工作流会话失败: {e}")
            db.rollback()
            # 不抛出异常，继续执行工作流

        # 保存工作流程状态（内存中）
        coordinator.set_workflow_state(project_id, {
            "project_id": project_id,
            "user_id": current_user.id,
            "requirement": requirement,
            "status": "running",
            "target_chapter_count": target_chapter_count,
        })

        # 返回初始化的阶段信息
        stages = {
            "concept": {
                "id": "concept",
                "name": "概念开发",
                "status": "pending",
                "progress": 0,
                "agents": coordinator.get_stage_agents(project_id, StageType.CONCEPT),
            },
            "structure": {
                "id": "structure",
                "name": "结构设计",
                "status": "pending",
                "progress": 0,
                "agents": coordinator.get_stage_agents(project_id, StageType.STRUCTURE),
            },
            "content": {
                "id": "content",
                "name": "内容创作",
                "status": "pending",
                "progress": 0,
                "agents": coordinator.get_stage_agents(project_id, StageType.CONTENT),
            },
            "review": {
                "id": "review",
                "name": "质量评审",
                "status": "pending",
                "progress": 0,
                "agents": coordinator.get_stage_agents(project_id, StageType.REVIEW),
            },
            "iteration": {
                "id": "iteration",
                "name": "迭代优化",
                "status": "pending",
                "progress": 0,
                "agents": coordinator.get_stage_agents(project_id, StageType.ITERATION),
            },
        }

        return {"status": "success", "stages": stages}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/execute-stage")
async def execute_stage(
    request: ExecuteStageRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    执行阶段（同步）

    请求体:
    {
        "project_id": 1,
        "stage": "concept"
    }
    """
    # 先提取参数，确保在异常处理中可访问
    project_id = request.project_id
    stage = request.stage
    
    try:
        if not project_id or not stage:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing project_id or stage",
            )

        # 执行阶段
        stage_enum = StageType(stage)
        
        # 🔔 推送阶段开始状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage,
            status='active',
            progress=0
        )
        
        stage_output = await coordinator.execute_stage(
            stage_enum,
            {"project_id": project_id, "user_id": current_user.id},
        )
        
        # 🔔 推送阶段完成状态
        output_str = str(stage_output.output) if stage_output.output else None
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage,
            status='completed',
            output=output_str,
            progress=100
        )

        return {
            "status": "success",
            "stage": stage,
            "output": stage_output.output,
            "agents": [
                coordinator.get_agents(project_id)[agent_id]
                for agent_id in stage_output.agents_involved
            ],
        }

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stage: {stage}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/execute-stage-async")
async def execute_stage_async(
    request: ExecuteStageRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    异步执行阶段（立即返回task_id，后台执行）
    🆕 支持流式输出：content/review/iteration 阶段可实时推送生成内容

    请求体:
    {
        "project_id": 1,
        "stage": "concept",
        "enable_streaming": true  // 🆕 是否启用流式输出
    }

    响应:
    {
        "task_id": "uuid-string",
        "status": "running",
        "streaming_enabled": true  // 🆕 是否启用了流式输出
    }
    """
    import asyncio
    from sqlalchemy import text

    project_id = request.project_id
    stage = request.stage
    requirement = (request.requirement or "").strip()
    enable_streaming = request.enable_streaming

    # 🔧 添加请求日志
    logger.info(f"📥 收到异步执行请求: project_id={project_id}, stage={stage}, streaming={enable_streaming}")

    # 🆕 判断是否支持流式输出（concept/structure/content/review/iteration 阶段都支持）
    streaming_stages = ["concept", "structure", "content", "review", "iteration"]
    streaming_enabled = (
        enable_streaming and
        stage in streaming_stages and
        STREAMING_AVAILABLE
    )

    try:
        if not project_id or not stage:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing project_id or stage",
            )

        # 验证stage值
        stage_enum = StageType(stage)

        if requirement:
            storage_mode = _save_workflow_requirement(
                db=db,
                project_id=project_id,
                user_id=current_user.id,
                requirement=requirement,
            )
            db.execute(
                text("UPDATE projects SET description = :description WHERE id = :project_id"),
                {
                    "description": requirement,
                    "project_id": project_id,
                },
            )
            db.commit()
            logger.info(f"   ✅ 已保存异步执行需求（模式: {storage_mode}）")

        # 生成task_id
        task_id = str(uuid.uuid4())
        logger.info(f"🎯 创建异步任务: {task_id} (stage={stage}, project_id={project_id}, streaming={streaming_enabled})")

        # 创建任务记录
        insert_query = text("""
            INSERT INTO generation_history
            (project_id, task_type, task_id, status, created_at)
            VALUES (:project_id, :task_type, :task_id, :status, :created_at)
        """)

        db.execute(insert_query, {
            "project_id": project_id,
            "task_type": f"workflow_stage_{stage}",
            "task_id": task_id,
            "status": "running",
            "created_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"   ✅ 任务记录已创建")

        # 🆕 根据是否启用流式输出选择执行方式
        if streaming_enabled:
            # 使用流式输出执行
            asyncio.create_task(
                _run_execute_stage_with_streaming_serialized(
                    task_id,
                    project_id,
                    stage_enum,
                    current_user.id,
                    db,
                )
            )
            logger.info(f"   🌊 流式后台任务已启动")
        else:
    # 使用传统方式执行
            asyncio.create_task(
                _run_execute_stage_background_serialized(
                    task_id,
                    project_id,
                    stage_enum,
                    current_user.id,
                    db,
                    getattr(request, "regenerate", False),
                    getattr(request, "targets", None),
                    getattr(request, "feedback", None),
                )
            )
            logger.info(f"   🚀 后台任务已启动")

        return {
            "task_id": task_id,
            "status": "running",
            "streaming_enabled": streaming_enabled  # 🆕 返回是否启用了流式输出
        }

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stage: {stage}",
        )
    except Exception as e:
        logger.error(f"❌ 异步任务创建失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


async def trigger_auto_system_detection(
    project_id: int,
    content: str,
    content_type: str,
    db: Session
):
    """
    触发体系自动检测（异步后台执行，不阻塞主流程）
    
    Args:
        project_id: 项目ID
        content: 待分析的内容
        content_type: 内容类型（outline 或 chapter）
        db: 数据库会话
    """
    try:
        logger.info(f"🎉 触发体系自动检测: {content_type}, 项目ID={project_id}")
        
        # 调用检测服务
        result = await auto_create_system_collections(
            project_id=project_id,
            content=content,
            db=db,
            content_type=content_type
        )
        
        # 如果有创建的集合，通过WebSocket通知前端
        if result.get("created_collections"):
            created_names = result["created_collections"]
            message = f"✨ 已自动添加 {len(created_names)} 个体系：{', '.join(created_names)}"
            
            await ws_manager.send_notification(
                project_id=project_id,
                message=message,
                type="system_collections_created",
                data=result
            )
            
            logger.info(f"✅ {message}")
        else:
            logger.info("ℹ️ 未检测到需要添加的新体系")
            
    except Exception as e:
        logger.error(f"❌ 体系自动检测失败（不影响主流程）: {e}")
        import traceback
        traceback.print_exc()

