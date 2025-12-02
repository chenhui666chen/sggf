"""
工作流程API路由
支持流式输出 (Streaming) 功能
"""
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from pydantic import BaseModel
from app.db.base import get_db
from app.services.agent_coordinator import (
    coordinator,
    StageType,
    AgentStatus,
)
from app.core.security import get_current_user
from app.models.project import Project
from app.websocket.manager import ws_manager
from app.services.setting_templates import build_project_settings_summary
import uuid
from datetime import datetime
import json

# 🔧 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 🆕 导入流式输出服务
try:
    from app.services.streaming_service import get_streaming_service
    STREAMING_AVAILABLE = True
except ImportError:
    STREAMING_AVAILABLE = False
    get_streaming_service = None  # type: ignore

# 请求模型
class StartWorkflowRequest(BaseModel):
    project_id: int
    requirement: str
    # 🆕 可选的目标章节数配置，用于长篇规划（默认100章）
    target_chapter_count: Optional[int] = 100
    # 🆕 是否清空现有内容（重新开始时使用）
    clear_existing: bool = False

class ExecuteStageRequest(BaseModel):
    project_id: int
    stage: str
    # 🆕 是否启用流式输出（默认启用）
    enable_streaming: bool = True

class RegenerateStageRequest(BaseModel):
    project_id: int
    stage: str

class SaveStageContentRequest(BaseModel):
    content: str
    continue_workflow: bool = False

class ExpandOutlineRequest(BaseModel):
    project_id: int
    current_outline: str
    world_setting: str
    characters: str
    current_chapter_count: int = 0  # 🆕 当前已有的章节数
    increment: int = 10  # 🆕 本次扩展的章节数（5-10章）
    target_total_chapters: Optional[int] = 100  # 🆕 长篇小说目标总章节数（默认按100章规划）

class ExpandCharactersRequest(BaseModel):
    project_id: int
    main_characters: str
    world_setting: str
    plot_outline: str
    current_character_count: int = 0  # 🆕 当前已有的人物数
    increment: int = 5  # 🆕 本次扩展的人物数（3-6个）
    target_total_characters: Optional[int] = 25  # 🆕 长篇小说目标人物数（默认按25人规划）

router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])


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
                clear_settings_query = text("""
                    UPDATE project_settings
                    SET concept = NULL,
                        world_setting = NULL,
                        characters = NULL,
                        plot_outline = NULL,
                        chapter_draft = NULL,
                        review_report = NULL,
                        final_version = NULL,
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                db.execute(clear_settings_query, {
                    "project_id": project_id,
                    "updated_at": datetime.now().isoformat()
                })
                cleared_data["settings"] = True
                logger.info(f"   ✅ 已清空项目设定（概念、大纲、世界观、人物等）")

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
            # 删除旧的工作流会话
            delete_query = text(
                "DELETE FROM workflow_sessions WHERE project_id = :project_id"
            )
            db.execute(delete_query, {"project_id": project_id})

            # 保存新的工作流会话
            insert_query = text(
                """INSERT INTO workflow_sessions
                   (project_id, user_id, requirement, created_at)
                   VALUES (:project_id, :user_id, :requirement, :created_at)"""
            )
            db.execute(insert_query, {
                "project_id": project_id,
                "user_id": current_user.id,
                "requirement": requirement,
                "created_at": datetime.now().isoformat()
            })

            # 🆕 同时更新 projects 表的 description 字段（关键修复！）
            update_project_query = text(
                "UPDATE projects SET description = :description WHERE id = :project_id"
            )
            db.execute(update_project_query, {
                "description": requirement,
                "project_id": project_id
            })

            db.commit()
            logger.info(f"   ✅ 工作流会话已保存到数据库")
            logger.info(f"   ✅ 项目描述已更新为用户需求")
        except Exception as e:
            logger.error(f"   ⚠️  保存工作流会话失败: {e}")
            db.rollback()
            # 不抛出异常，继续执行工作流

        # 保存工作流程状态（内存中）
        coordinator.workflow_state = {
            "project_id": project_id,
            "user_id": current_user.id,
            "requirement": requirement,
            "status": "running",
            "target_chapter_count": target_chapter_count,
        }

        # 返回初始化的阶段信息
        stages = {
            "concept": {
                "id": "concept",
                "name": "概念开发",
                "status": "pending",
                "progress": 0,
                "agents": [
                    agent
                    for agent in coordinator.agents.values()
                    if agent["stage"] == StageType.CONCEPT
                ],
            },
            "structure": {
                "id": "structure",
                "name": "结构设计",
                "status": "pending",
                "progress": 0,
                "agents": [
                    agent
                    for agent in coordinator.agents.values()
                    if agent["stage"] == StageType.STRUCTURE
                ],
            },
            "content": {
                "id": "content",
                "name": "内容创作",
                "status": "pending",
                "progress": 0,
                "agents": [
                    agent
                    for agent in coordinator.agents.values()
                    if agent["stage"] == StageType.CONTENT
                ],
            },
            "review": {
                "id": "review",
                "name": "质量评审",
                "status": "pending",
                "progress": 0,
                "agents": [
                    agent
                    for agent in coordinator.agents.values()
                    if agent["stage"] == StageType.REVIEW
                ],
            },
            "iteration": {
                "id": "iteration",
                "name": "迭代优化",
                "status": "pending",
                "progress": 0,
                "agents": [
                    agent
                    for agent in coordinator.agents.values()
                    if agent["stage"] == StageType.ITERATION
                ],
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
                coordinator.agents[agent_id]
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
    enable_streaming = request.enable_streaming

    # 🔧 添加请求日志
    logger.info(f"📥 收到异步执行请求: project_id={project_id}, stage={stage}, streaming={enable_streaming}")

    # 🆕 判断是否支持流式输出（仅 content/review/iteration 阶段）
    streaming_stages = ["content", "review", "iteration"]
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
            "created_at": datetime.now().isoformat()
        })
        db.commit()
        logger.info(f"   ✅ 任务记录已创建")

        # 🆕 根据是否启用流式输出选择执行方式
        if streaming_enabled:
            # 使用流式输出执行
            asyncio.create_task(
                execute_stage_with_streaming(task_id, project_id, stage_enum, current_user.id, db)
            )
            logger.info(f"   🌊 流式后台任务已启动")
        else:
            # 使用传统方式执行
            asyncio.create_task(
                execute_stage_background(task_id, project_id, stage_enum, current_user.id, db)
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


async def execute_stage_background(task_id: str, project_id: int, stage_enum: StageType, user_id: int, db: Session):
    """后台执行阶段任务"""
    import logging
    from sqlalchemy import text
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"🔥 开始执行后台任务: {task_id}")
        
        # 🆕 关键修复：确保协调器已初始化
        if not coordinator._coordinator_initialized:
            logger.info("   🔍 检测到协调器未初始化，开始初始化...")
            await coordinator.initialize_agents()
            logger.info("   ✅ 协调器初始化完成")
        
        # 🆕 确保 project_settings 记录存在（关键修复！）
        check_query = text("""
            SELECT id FROM project_settings WHERE project_id = :project_id
        """)
        existing = db.execute(check_query, {"project_id": project_id}).fetchone()
        
        if not existing:
            logger.info(f"   📝 初始化 project_settings 记录")
            init_query = text("""
                INSERT INTO project_settings 
                (project_id, stage_one_status, stage_two_status, stage_three_status, 
                 stage_four_status, stage_five_status, created_at, updated_at)
                VALUES 
                (:project_id, 'pending', 'pending', 'pending', 'pending', 'pending', 
                 :created_at, :updated_at)
            """)
            db.execute(init_query, {
                "project_id": project_id,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            })
            db.commit()
            logger.info(f"   ✅ project_settings 记录已创建")
        
        # 🔧 关键修复：从数据库读取用户需求
        requirement_query = text(
            """SELECT requirement FROM workflow_sessions 
               WHERE project_id = :project_id 
               ORDER BY created_at DESC LIMIT 1"""
        )
        result = db.execute(requirement_query, {"project_id": project_id}).fetchone()
        
        if result and result[0]:
            requirement = result[0]
            logger.info(f"   ✅ 从数据库读取到用户需求: {requirement[:50]}...")
        else:
            # 🔧 降级方案：从 projects 表读取 description
            project_query = text(
                "SELECT description FROM projects WHERE id = :project_id"
            )
            project_result = db.execute(project_query, {"project_id": project_id}).fetchone()
            
            if project_result and project_result[0]:
                requirement = project_result[0]
                logger.info(f"   ✅ 从项目描述读取到用户需求: {requirement[:50]}...")
            else:
                requirement = "根据项目设定进行创作"
                logger.warning(f"   ⚠️  未找到用户需求，使用默认值: {requirement}")
        
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
                {'id': 'worldview_architect', 'name': '世界观架构师'},
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

        # 🔧 关键修复：将 requirement 传递给 execute_stage
        stage_output = await coordinator.execute_stage(
            stage_enum,
            {
                "project_id": project_id, 
                "user_id": user_id,
                "requirement": requirement  # ✅ 传递真实的用户需求
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
            "completed_at": datetime.now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        logger.info(f"   ✅ 任务完成: {task_id}")
        
        # 🆕 保存阶段输出到 project_settings（关键修复！）
        try:
            import json
            
            if stage_enum == StageType.CONCEPT:
                # 保存概念开发结果
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                save_query = text("""
                    UPDATE project_settings
                    SET concept = :concept,
                        world_setting = :world_setting,
                        characters = :characters,
                        stage_one_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                
                db.execute(save_query, {
                    "concept": json.dumps(output_data.get("concept", ""), ensure_ascii=False),
                    "world_setting": json.dumps(output_data.get("worldview", output_data.get("world_setting", "")), ensure_ascii=False),
                    "characters": json.dumps(output_data.get("characters", []), ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
                logger.info(f"   💾 已保存概念开发结果到 project_settings")
            
            elif stage_enum == StageType.STRUCTURE:
                # 保存结构设计结果
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                save_query = text("""
                    UPDATE project_settings
                    SET plot_outline = :plot_outline,
                        stage_two_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                
                db.execute(save_query, {
                    "plot_outline": json.dumps(output_data.get("plot_outline", ""), ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
                logger.info(f"   💾 已保存结构设计结果到 project_settings")
            
            elif stage_enum == StageType.CONTENT:
                # 保存内容创作结果
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                save_query = text("""
                    UPDATE project_settings
                    SET chapter_draft = :chapter_draft,
                        stage_three_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                
                db.execute(save_query, {
                    "chapter_draft": json.dumps(output_data.get("content", output_data.get("chapters", "")), ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
                logger.info(f"   💾 已保存内容创作结果到 project_settings")
            
            elif stage_enum == StageType.REVIEW:
                # 保存质量评审结果
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                save_query = text("""
                    UPDATE project_settings
                    SET review_report = :review_report,
                        stage_four_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                
                db.execute(save_query, {
                    "review_report": json.dumps(output_data.get("review", ""), ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
                logger.info(f"   💾 已保存质量评审结果到 project_settings")
            
            elif stage_enum == StageType.ITERATION:
                # 保存迭代优化结果
                # 🔥 关键修复：直接使用已经解析好的 result_str，而不是重新解析
                final_version_content = result_str  # result_str 已经是正确的 revised_content

                save_query = text("""
                    UPDATE project_settings
                    SET final_version = :final_version,
                        stage_five_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)

                db.execute(save_query, {
                    "final_version": json.dumps(final_version_content, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
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
                "timestamp": datetime.now().isoformat()
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
        
        # 更新任务状态为失败
        update_query = text("""
            UPDATE generation_history
            SET status = :status, error = :error, completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        
        db.execute(update_query, {
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.now().isoformat(),
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


async def execute_stage_with_streaming(task_id: str, project_id: int, stage_enum: StageType, user_id: int, db: Session):
    """
    🆕 使用流式输出执行阶段任务

    支持 content/review/iteration 阶段的实时内容推送
    """
    import logging
    from sqlalchemy import text

    logger = logging.getLogger("uvicorn.error")

    try:
        logger.info(f"🌊 开始流式执行后台任务: {task_id}")

        # 确保协调器已初始化
        if not coordinator._coordinator_initialized:
            logger.info("   🔍 检测到协调器未初始化，开始初始化...")
            await coordinator.initialize_agents()
            logger.info("   ✅ 协调器初始化完成")

        # 确保 project_settings 记录存在
        check_query = text("""
            SELECT id FROM project_settings WHERE project_id = :project_id
        """)
        existing = db.execute(check_query, {"project_id": project_id}).fetchone()

        if not existing:
            logger.info(f"   📝 初始化 project_settings 记录")
            init_query = text("""
                INSERT INTO project_settings
                (project_id, stage_one_status, stage_two_status, stage_three_status,
                 stage_four_status, stage_five_status, created_at, updated_at)
                VALUES
                (:project_id, 'pending', 'pending', 'pending', 'pending', 'pending',
                 :created_at, :updated_at)
            """)
            db.execute(init_query, {
                "project_id": project_id,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            })
            db.commit()

        # 从数据库读取用户需求
        requirement_query = text(
            """SELECT requirement FROM workflow_sessions
               WHERE project_id = :project_id
               ORDER BY created_at DESC LIMIT 1"""
        )
        result = db.execute(requirement_query, {"project_id": project_id}).fetchone()

        if result and result[0]:
            requirement = result[0]
        else:
            project_query = text("SELECT description FROM projects WHERE id = :project_id")
            project_result = db.execute(project_query, {"project_id": project_id}).fetchone()
            requirement = project_result[0] if project_result and project_result[0] else "根据项目设定进行创作"

        # 🌊 发送流式输出开始通知
        await ws_manager.send_stream_start(project_id, stage_enum.value)

        # 推送阶段开始状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='active',
            progress=0
        )

        # 🆕 定义每个阶段的 Agent 配置（流式版本）
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
                context_query = text("""
                    SELECT concept, world_setting, characters, plot_outline, chapter_draft, review_report
                    FROM project_settings WHERE project_id = :project_id
                """)
                context_result = db.execute(context_query, {"project_id": project_id}).fetchone()

                # 构建流式调用的提示词
                if stage_enum == StageType.CONTENT:
                    # 内容创作阶段
                    plot_outline = ""
                    world_setting = ""
                    characters = ""
                    if context_result:
                        plot_outline = context_result[3] or ""
                        world_setting = context_result[1] or ""
                        characters = context_result[2] or ""
                        # 尝试解析 JSON
                        try:
                            import json
                            if plot_outline.startswith('"'):
                                plot_outline = json.loads(plot_outline)
                            if world_setting.startswith('"'):
                                world_setting = json.loads(world_setting)
                            if characters.startswith('"') or characters.startswith('['):
                                characters = json.loads(characters)
                                if isinstance(characters, list):
                                    characters = "\n".join(str(c) for c in characters)
                        except:
                            pass

                    # 🆕 开头/结尾方式定义（从头创作共享模块）
                    opening_styles = {
                        "对话开头": ("对话开头", "直接进入冲突或紧张场景", "'站住！'身后传来一声厉喝。"),
                        "动作开头": ("动作开头", "正在发生的动态事件", "刀光闪过，血珠在空中划出一道弧线。"),
                        "悬念开头": ("悬念开头", "抛出问题，引发好奇", "三天后回想起这个决定时，她依然后悔不已。"),
                        "场景开头": ("场景开头", "氛围渲染，快速建立情境", "暴雨倾盆，整个长安城笼罩在一片灰蒙蒙的水雾中。"),
                    }
                    ending_styles = {
                        "悬念式": ("悬念式", "关键信息揭露一半", "信封里只有一张纸，上面写着三个字——"),
                        "转折式": ("转折式", "意外事件发生", "就在她以为一切结束时，门外响起了敲门声。"),
                        "信息炸弹式": ("信息炸弹式", "惊人真相揭露", "'你以为我是谁？'他摘下面具，露出一张熟悉的脸。"),
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
- 参考示例：{selected_opening[2]}

❌ 禁止使用：用"XXX醒来/睁开眼睛/阳光照进房间"开头

【本章结尾方式 - 建议】
建议使用【{selected_ending[0]}】结尾，让读者想点下一章
- 技巧说明：{selected_ending[1]}
- 参考示例：{selected_ending[2]}

❌ 禁止使用：总结式内心独白 + 对未来的展望（如"她知道，从这一刻起..."）

请开始创作第一章内容："""

                elif stage_enum == StageType.REVIEW:
                    # 质量评审阶段
                    chapter_draft = ""
                    if context_result:
                        chapter_draft = context_result[4] or ""
                        try:
                            import json
                            if chapter_draft.startswith('"'):
                                chapter_draft = json.loads(chapter_draft)
                        except:
                            pass

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
- 章节开头是否吸引人？（是否避免了"醒来/阳光照进"的套路开头）
- 章节结尾是否有悬念/钩子？
- 读者是否有"想点下一章"的冲动？

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
                    chapter_draft = ""
                    review_report = ""
                    if context_result:
                        chapter_draft = context_result[4] or ""
                        review_report = context_result[5] or ""
                        try:
                            import json
                            if chapter_draft.startswith('"'):
                                chapter_draft = json.loads(chapter_draft)
                            if review_report.startswith('"'):
                                review_report = json.loads(review_report)
                        except:
                            pass

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
                result_str = await streaming_service.generate_chapter_streaming(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    on_chunk=on_stream_chunk,
                    temperature=0.7,
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
            else:
                result_str = str(stage_output.output) if stage_output.output else ""

        # 🌊 发送流式输出结束通知
        await ws_manager.send_stream_end(
            project_id=project_id,
            stage=stage_enum.value,
            total_chars=len(result_str) if result_str else 0
        )

        # 更新任务状态为完成
        update_query = text("""
            UPDATE generation_history
            SET status = :status, result = :result, completed_at = :completed_at
            WHERE task_id = :task_id
        """)

        db.execute(update_query, {
            "status": "completed",
            "result": result_str,
            "completed_at": datetime.now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        logger.info(f"   ✅ 流式任务完成: {task_id}")

        # 保存阶段输出到 project_settings
        try:
            if stage_enum == StageType.CONTENT:
                save_query = text("""
                    UPDATE project_settings
                    SET chapter_draft = :chapter_draft,
                        stage_three_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                db.execute(save_query, {
                    "chapter_draft": json.dumps(result_str, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
            elif stage_enum == StageType.REVIEW:
                save_query = text("""
                    UPDATE project_settings
                    SET review_report = :review_report,
                        stage_four_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                db.execute(save_query, {
                    "review_report": json.dumps(result_str, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
            elif stage_enum == StageType.ITERATION:
                save_query = text("""
                    UPDATE project_settings
                    SET final_version = :final_version,
                        stage_five_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                db.execute(save_query, {
                    "final_version": json.dumps(result_str, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
        except Exception as save_error:
            logger.error(f"   ⚠️  保存到 project_settings 失败: {save_error}")

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
                "timestamp": datetime.now().isoformat()
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

        # 更新任务状态为失败
        update_query = text("""
            UPDATE generation_history
            SET status = :status, error = :error, completed_at = :completed_at
            WHERE task_id = :task_id
        """)

        db.execute(update_query, {
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.now().isoformat(),
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


@router.post("/regenerate-stage")
async def regenerate_stage(
    request: RegenerateStageRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    重新生成阶段

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

        # 重新执行阶段
        stage_enum = StageType(stage)
        stage_output = await coordinator.execute_stage(
            stage_enum,
            {"project_id": project_id, "user_id": current_user.id},
        )

        return {
            "status": "success",
            "stage": stage,
            "output": stage_output.output,
            "agents": [
                coordinator.agents[agent_id]
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


@router.get("/status/{project_id}")
async def get_workflow_status(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取工作流程状态"""
    try:
        # ✅ 验证项目所有权
        from app.models.project import Project
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.user_id == current_user.id
        ).first()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found or access denied"
            )

        status_data = await coordinator.get_workflow_status()
        return {
            "status": "success",
            "project_id": project_id,
            "workflow": status_data,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{project_id}/stage/{stage}/content")
async def get_stage_content(
    project_id: int,
    stage: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取阶段内容

    响应:
    {
        "content": "内容文本",
        "stage": "iteration"
    }
    """
    try:
        # 1. 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == project_id) & (Project.user_id == current_user.id)
        ).first()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )

        # 2. 从 project_settings 表读取内容
        from sqlalchemy import text

        # 映射阶段名称到数据库列名
        stage_column_map = {
            'concept': 'concept',
            'world_builder': 'world_setting',
            'character_designer': 'characters',
            'structure': 'plot_outline',
            'content': 'chapter_draft',
            'review': 'review_report',
            'iteration': 'final_version',
        }

        column_name = stage_column_map.get(stage)
        if not column_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid stage: {stage}"
            )

        # 查询内容
        query = text(f"""
            SELECT {column_name}
            FROM project_settings
            WHERE project_id = :project_id
        """)

        result = db.execute(query, {"project_id": project_id}).fetchone()

        if not result:
            # 如果没有记录，返回空内容
            return {
                "content": "",
                "stage": stage
            }

        content = result[0] or ""

        # 🔧 修复JSON解码错误：如果内容是JSON字符串，先解析
        import json
        try:
            if content and (content.startswith('{') or content.startswith('[') or content.startswith('"')):
                parsed_content = json.loads(content)
                # 如果是字符串，直接使用；如果是对象/数组，转回字符串
                if isinstance(parsed_content, str):
                    content = parsed_content
                elif isinstance(parsed_content, (dict, list)):
                    # 如果是对象或数组，转回格式化的字符串
                    content = json.dumps(parsed_content, ensure_ascii=False, indent=2)
                else:
                    content = str(parsed_content)
        except json.JSONDecodeError:
            # 如枟解析失败，直接使用原内容
            pass

        return {
            "content": content,
            "stage": stage
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.put("/{project_id}/stage/{stage}/content")
async def save_stage_content(
    project_id: int,
    stage: str,
    request: SaveStageContentRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    保存阶段内容并可选继续工作流

    请求体:
    {
        "content": "内容文本",
        "continue_workflow": true
    }

    响应:
    {
        "success": true,
        "message": "内容已保存",
        "stage": "content",
        "task_id": "uuid-string",  // 如果continue_workflow为true
        "continue_workflow": true,
        "deleted_chapter": {...}  // 如果删除了已保存章节
    }
    """
    import logging
    logger = logging.getLogger("uvicorn.error")
    
    try:
        # 1. 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == project_id) & (Project.user_id == current_user.id)
        ).first()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )

        # 🆕 2. 智能章节覆盖：如果是内容创作阶段或质量评审阶段
        deleted_chapter = None
        deleted_chapters_count = 0

        # 质量评审阶段：用户修改评审报告后继续，需要删除所有现有章节重新生成
        if stage == 'review' and request.continue_workflow:
            logger.info(f"🔍 检测到质量评审阶段继续工作流，检查是否需要清理现有章节...")

            from sqlalchemy import text
            # 获取当前已保存的所有章节
            chapters_query = text("""
                SELECT id, chapter_number, title, word_count
                FROM chapters
                WHERE project_id = :project_id
                ORDER BY chapter_number
            """)
            chapters_result = db.execute(chapters_query, {"project_id": project_id}).fetchall()
            chapters = [{"id": r[0], "chapter_number": r[1], "title": r[2], "word_count": r[3]} for r in chapters_result]

            if chapters:
                logger.info(f"   📊 发现 {len(chapters)} 个已保存章节，准备清理...")

                # 清理记忆管理中的章节引用
                try:
                    from app.models.memory import Memory
                    db.query(Memory).filter(
                        Memory.project_id == project_id
                    ).update({Memory.current_chapter: None}, synchronize_session=False)
                    logger.info(f"      ✅ 已清理记忆管理中的章节引用")
                except Exception as e:
                    logger.warning(f"   ⚠️  记忆清理失败（非致命错误）: {e}")

                # 删除所有章节记录
                delete_chapters_query = text("""
                    DELETE FROM chapters
                    WHERE project_id = :project_id
                """)
                db.execute(delete_chapters_query, {"project_id": project_id})
                db.commit()

                deleted_chapters_count = len(chapters)
                logger.info(f"   ✅ 已删除 {deleted_chapters_count} 个章节，准备重新生成")
            else:
                logger.info(f"   ✅ 未发现已保存章节，无需清理")

        # 内容创作阶段：智能覆盖最后一章
        elif stage == 'content':
            logger.info(f"🔍 检测到内容创作阶段，检查是否需要更新现有章节...")
            
            # 获取当前已保存的章节列表
            from sqlalchemy import text
            # 使用原生SQL替代ORM查询
            chapters_query = text("""
                SELECT id, chapter_number, title, word_count 
                FROM chapters 
                WHERE project_id = :project_id 
                ORDER BY chapter_number DESC
            """)
            chapters_result = db.execute(chapters_query, {"project_id": project_id}).fetchall()
            chapters = [{"id": r[0], "chapter_number": r[1], "title": r[2], "word_count": r[3]} for r in chapters_result]
            
            # 目标章节号应该是当前最大章节号（用户想更新这一章）
            if chapters:
                # 如果已有章节，检查最后一章（用户可能想更新）
                target_chapter_number = chapters[0]["chapter_number"]
            else:
                # 如果没有章节，说明这是第一章
                target_chapter_number = 1
            
            logger.info(f"   📊 已有章节数: {len(chapters)}，目标章节编号: {target_chapter_number}")
            
            # 检查是否已存在目标章节
            # 使用原生SQL替代ORM查询
            existing_chapter_query = text("""
                SELECT id, chapter_number, title, word_count 
                FROM chapters 
                WHERE project_id = :project_id AND chapter_number = :chapter_number
            """)
            existing_chapter_result = db.execute(existing_chapter_query, {
                "project_id": project_id,
                "chapter_number": target_chapter_number
            }).fetchone()
            
            if existing_chapter_result:
                existing_chapter = {
                    "id": existing_chapter_result[0],
                    "chapter_number": existing_chapter_result[1],
                    "title": existing_chapter_result[2],
                    "word_count": existing_chapter_result[3]
                }
                
                logger.info(f"   ⚠️  发现已存在第{target_chapter_number}章（ID={existing_chapter['id']}），准备更新...")
                
                # 更新现有章节信息
                deleted_chapter_info = {
                    "id": existing_chapter["id"],
                    "chapter_number": existing_chapter["chapter_number"],
                    "title": existing_chapter["title"],
                    "word_count": existing_chapter["word_count"]
                }
                
                # 🧹 1) 清理 ChromaDB 向量数据
                try:
                    logger.info(f"   🗂️  清理ChromaDB中的章节向量...")
                    from app.services.agents.knowledge_base import NovelKnowledgeBase
                    kb = NovelKnowledgeBase()
                    deleted_count = kb.delete_chapter(
                        chapter_number=target_chapter_number,
                        project_id=project_id
                    )
                    if deleted_count > 0:
                        logger.info(f"      ✅ 已删除 {deleted_count} 个向量文档")
                except Exception as e:
                    logger.warning(f"   ⚠️  ChromaDB清理失败（非致命错误）: {e}")

                # 🧹 2) 清理记忆管理中的章节引用
                try:
                    logger.info(f"   🧠 清理记忆管理中的章节引用...")
                    
                    from app.models.memory import Memory
                    db.query(Memory).filter(
                        (Memory.project_id == project_id) &
                        (Memory.current_chapter == target_chapter_number)
                    ).update({Memory.current_chapter: None})
                    
                    logger.info(f"      ✅ 已清理记忆管理中的章节引用")
                except Exception as e:
                    logger.warning(f"   ⚠️  记忆清理失败（非致命错误）: {e}")
                
                # 🗑️ 删除章节记录（会自动级联删除评审记录）
                logger.info(f"   🗑️  删除旧章节记录...")
                # 使用原生SQL删除章节
                delete_chapter_query = text("""
                    DELETE FROM chapters 
                    WHERE id = :chapter_id
                """)
                db.execute(delete_chapter_query, {"chapter_id": existing_chapter["id"]})
                db.commit()
                
                deleted_chapter = deleted_chapter_info
                logger.info(f"   ✅ 已删除第{target_chapter_number}章，准备更新为新内容")
            else:
                logger.info(f"   ✅ 未发现重复章节，将创建新章节")

        # 3. 保存内容到project_settings表
        from sqlalchemy import text

        # 映射阶段名称到数据库列名
        stage_column_map = {
            'concept': 'concept',
            'world_builder': 'world_setting',
            'character_designer': 'characters',
            'structure': 'plot_outline',
            'content': 'chapter_draft',
            'review': 'review_report',
            'iteration': 'final_version',
        }

        column_name = stage_column_map.get(stage)
        if not column_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid stage: {stage}"
            )

        # 更新project_settings表
        update_query = text(f"""
            UPDATE project_settings
            SET {column_name} = :content, updated_at = :updated_at
            WHERE project_id = :project_id
        """)

        db.execute(update_query, {
            "content": request.content,
            "updated_at": datetime.now().isoformat(),
            "project_id": project_id
        })
        db.commit()

        # 4. 如果continue_workflow为true，创建任务记录
        task_id = None
        if request.continue_workflow:
            task_id = str(uuid.uuid4())

            # 创建任务记录到generation_history表
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
                "created_at": datetime.now().isoformat()
            })
            db.commit()

        response = {
            "success": True,
            "message": "内容已保存",
            "stage": stage,
            "task_id": task_id,
            "continue_workflow": request.continue_workflow
        }

        # 🆕 如果删除了章节，包含在响应中
        if deleted_chapter:
            response["deleted_chapter"] = deleted_chapter
            response["message"] = f"已删除第{deleted_chapter['chapter_number']}章并保存新内容"

        # 🆕 如果是评审阶段删除了多个章节
        if deleted_chapters_count > 0:
            response["deleted_chapters_count"] = deleted_chapters_count
            response["message"] = f"已删除 {deleted_chapters_count} 个章节，准备重新生成"

        return response

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/task/{task_id}")
async def get_task_status(
    task_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取任务状态

    响应:
    {
        "task_id": "uuid-string",
        "status": "running|completed|failed",
        "progress": 0-100,
        "result": "任务结果",
        "error": "错误信息（如果有）"
    }
    """
    try:
        from sqlalchemy import text

        # ✅ 查询任务状态并验证项目所有权
        query = text("""
            SELECT gh.task_id, gh.status, gh.result, gh.error, gh.created_at, gh.completed_at
            FROM generation_history gh
            INNER JOIN projects p ON gh.project_id = p.id
            WHERE gh.task_id = :task_id AND p.user_id = :user_id
        """)

        result = db.execute(query, {
            "task_id": task_id,
            "user_id": current_user.id
        }).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found or access denied"
            )

        # 计算进度
        progress = 0
        if result[1] == "completed":
            progress = 100
        elif result[1] == "running":
            progress = 50
        elif result[1] == "failed":
            progress = 0

        return {
            "task_id": result[0],
            "status": result[1],
            "progress": progress,
            "result": result[2],
            "error": result[3],
            "created_at": result[4],
            "completed_at": result[5]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/project/{project_id}/running-tasks")
async def get_running_tasks(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 获取项目的正在运行的任务

    用于页面重新加载时恢复工作流状态

    🔧 新增：自动检测并标记超时任务（超过30分钟的任务自动标记为 timeout）

    响应:
    {
        "running_tasks": [
            {
                "task_id": "uuid",
                "task_type": "workflow_stage_concept",
                "status": "running",
                "created_at": "2024-01-01T00:00:00"
            }
        ],
        "timeout_tasks": [...]  // 被标记为超时的任务
    }
    """
    import logging
    from sqlalchemy import text
    from datetime import datetime, timedelta

    logger = logging.getLogger("uvicorn.error")

    # 🔧 超时阈值：30分钟
    TASK_TIMEOUT_MINUTES = 30

    try:
        logger.info(f"🔍 查询项目 {project_id} 的正在运行任务...")

        # 🆕 首先检查 project_settings 中的 stage 状态
        # 如果所有 stage 都已完成，则将 running 任务标记为 completed（状态不一致修复）
        stage_query = text("""
            SELECT stage_one_status, stage_two_status, stage_three_status,
                   stage_four_status, stage_five_status
            FROM project_settings
            WHERE project_id = :project_id
        """)
        stage_result = db.execute(stage_query, {"project_id": project_id}).fetchone()

        all_stages_completed = False
        if stage_result:
            statuses = [stage_result[i] for i in range(5)]
            all_stages_completed = all(s == 'completed' for s in statuses if s)
            logger.debug(f"   Stage 状态: {statuses}, 全部完成: {all_stages_completed}")

        # 查询status='running'的任务
        query = text("""
            SELECT task_id, task_type, status, created_at
            FROM generation_history
            WHERE project_id = :project_id AND status = 'running'
            ORDER BY created_at DESC
        """)

        results = db.execute(query, {"project_id": project_id}).fetchall()

        running_tasks = []
        timeout_tasks = []
        stale_tasks = []  # 🆕 已过时的任务（stage 已完成但任务状态仍为 running）
        now = datetime.now()

        for row in results:
            task_id = row[0]
            task_type = row[1]
            status = row[2]
            created_at_str = row[3]

            # 解析创建时间
            try:
                if isinstance(created_at_str, str):
                    created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00').replace('+00:00', ''))
                else:
                    created_at = created_at_str
            except:
                created_at = now  # 解析失败时使用当前时间

            # 🔧 检测超时：如果任务运行超过30分钟，标记为超时
            task_age_minutes = (now - created_at).total_seconds() / 60

            # 🆕 优先检查：如果所有 stage 都已完成，将 running 任务标记为 completed（状态不一致修复）
            if all_stages_completed:
                logger.warning(f"🔄 检测到过时任务: {task_id}（所有阶段已完成，但任务仍为 running）")

                update_query = text("""
                    UPDATE generation_history
                    SET status = 'completed',
                        completed_at = :completed_at
                    WHERE task_id = :task_id
                """)

                db.execute(update_query, {
                    "completed_at": now.isoformat(),
                    "task_id": task_id
                })
                db.commit()

                stale_tasks.append({
                    "task_id": task_id,
                    "task_type": task_type,
                    "status": "completed",
                    "created_at": created_at_str,
                    "age_minutes": round(task_age_minutes, 1),
                    "reason": "所有阶段已完成，自动同步任务状态"
                })

                logger.info(f"   ✅ 已将过时任务 {task_id} 标记为 completed")

            elif task_age_minutes > TASK_TIMEOUT_MINUTES:
                # 标记为超时
                logger.warning(f"⏰ 检测到超时任务: {task_id}, 运行时间: {task_age_minutes:.1f}分钟")

                update_query = text("""
                    UPDATE generation_history
                    SET status = 'timeout',
                        error = :error,
                        completed_at = :completed_at
                    WHERE task_id = :task_id
                """)

                db.execute(update_query, {
                    "error": f"任务超时（运行超过{TASK_TIMEOUT_MINUTES}分钟）",
                    "completed_at": now.isoformat(),
                    "task_id": task_id
                })
                db.commit()

                timeout_tasks.append({
                    "task_id": task_id,
                    "task_type": task_type,
                    "status": "timeout",
                    "created_at": created_at_str,
                    "age_minutes": round(task_age_minutes, 1)
                })

                logger.info(f"   ✅ 已将任务 {task_id} 标记为超时")
            else:
                running_tasks.append({
                    "task_id": task_id,
                    "task_type": task_type,
                    "status": status,
                    "created_at": created_at_str,
                    "age_minutes": round(task_age_minutes, 1)
                })

        logger.info(f"   ✅ 找到 {len(running_tasks)} 个正在运行的任务, {len(timeout_tasks)} 个超时任务, {len(stale_tasks)} 个已同步的过时任务")

        return {
            "running_tasks": running_tasks,
            "timeout_tasks": timeout_tasks,
            "stale_tasks": stale_tasks  # 🆕 已同步的过时任务
        }

    except Exception as e:
        logger.error(f"❌ 查询运行中任务失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{project_id}/all-stages-content")
async def get_all_stages_content(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    批量获取所有阶段内容（性能优化）

    响应:
    {
        "project_id": 1,
        "stages": {
            "concept": "故事概念内容...",
            "world_setting": "世界观设定...",
            "characters": "人物设定...",
            "plot_outline": "情节大纲...",
            "chapter_draft": "章节初稿...",
            "review_report": "评审报告...",
            "final_version": "最终版本..."
        }
    }
    """
    try:
        from sqlalchemy import text

        # 验证项目存在且属于用户
        query = text("""
            SELECT id FROM projects 
            WHERE id = :project_id AND user_id = :user_id
        """)
        result = db.execute(query, {"project_id": project_id, "user_id": current_user.id}).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="项目不存在"
            )

        # 一次查询获取所有阶段内容
        query = text("""
            SELECT 
                concept, 
                world_setting, 
                characters, 
                plot_outline, 
                chapter_draft, 
                review_report, 
                final_version 
            FROM project_settings 
            WHERE project_id = :project_id
        """)
        result = db.execute(query, {"project_id": project_id}).fetchone()

        if result:
            import json

            # 辅助函数：解析 JSON 存储的内容
            def parse_json_content(content):
                if not content:
                    return ""
                try:
                    if content.startswith('{') or content.startswith('[') or content.startswith('"'):
                        parsed = json.loads(content)
                        if isinstance(parsed, str):
                            return parsed
                        elif isinstance(parsed, (dict, list)):
                            return json.dumps(parsed, ensure_ascii=False, indent=2)
                        else:
                            return str(parsed)
                except (json.JSONDecodeError, AttributeError):
                    pass
                return content

            response = {
                "project_id": project_id,
                "stages": {
                    "concept": parse_json_content(result[0]),
                    "world_setting": parse_json_content(result[1]),
                    "characters": parse_json_content(result[2]),
                    "plot_outline": parse_json_content(result[3]),
                    "chapter_draft": parse_json_content(result[4]),
                    "review_report": parse_json_content(result[5]),
                    "final_version": parse_json_content(result[6])
                }
            }
        else:
            # 如果没有记录，返回空内容
            response = {
                "project_id": project_id,
                "stages": {
                    "concept": "",
                    "world_setting": "",
                    "characters": "",
                    "plot_outline": "",
                    "chapter_draft": "",
                    "review_report": "",
                    "final_version": ""
                }
            }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{project_id}/stage-status")
async def get_stage_status(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取所有阶段状态

    响应:
    {
        "project_id": 1,
        "stage_one_status": "pending",
        "stage_two_status": "completed",
        ...
    }
    """
    try:
        from sqlalchemy import text

        # 验证项目存在且属于用户
        query = text("""
            SELECT id FROM projects 
            WHERE id = :project_id AND user_id = :user_id
        """)
        result = db.execute(query, {"project_id": project_id, "user_id": current_user.id}).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="项目不存在"
            )

        # 获取所有阶段状态
        query = text("""
            SELECT 
                stage_one_status, 
                stage_two_status, 
                stage_three_status, 
                stage_four_status, 
                stage_five_status 
            FROM project_settings 
            WHERE project_id = :project_id
        """)
        result = db.execute(query, {"project_id": project_id}).fetchone()

        if result:
            response = {
                "project_id": project_id,
                "stage_one_status": result[0] or "pending",
                "stage_two_status": result[1] or "pending",
                "stage_three_status": result[2] or "pending",
                "stage_four_status": result[3] or "pending",
                "stage_five_status": result[4] or "pending"
            }
        else:
            # 如果没有记录，返回默认状态
            response = {
                "project_id": project_id,
                "stage_one_status": "pending",
                "stage_two_status": "pending",
                "stage_three_status": "pending",
                "stage_four_status": "pending",
                "stage_five_status": "pending"
            }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )





@router.post("/{project_id}/generate-next-chapter")
async def generate_next_chapter(
    project_id: int,
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
        query = text("""
            SELECT concept, world_setting, characters, plot_outline 
            FROM project_settings 
            WHERE project_id = :project_id
        """)
        settings = db.execute(query, {"project_id": project_id}).fetchone()
        
        if not settings:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="项目设定不存在，请先完成工作流程初始化"
            )
        
        concept, world_setting, characters, plot_outline = settings
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
            """生成已完成章节的摘要，并构造供内容生成使用的高层摘要列表。"""
            if not chapters:
                return "这是第一章，之前没有章节。", []

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
            recent_limit = 10  # 对最近若干部章节优先使用结构化摘要

            for idx, chapter in enumerate(chapters):
                chapter_id, chapter_num, title, content, existing_summary = chapter
                content = content or ""
                title = title or ""
                summary_text = (existing_summary or "").strip()

                # 仅对最近若干部章节尝试使用结构化摘要，其他章节直接使用已存在摘要或前200字
                is_recent = (total - idx) <= recent_limit

                if summarizer and is_recent:
                    try:
                        summary_data = summarizer.get_or_generate_summary(
                            chapter_id=chapter_id,
                            chapter_number=chapter_num,
                            chapter_title=title or f"第{chapter_num}章",
                            chapter_content=content,
                            summary_length=200,
                        )
                        summary_text = summary_data.get("core_summary", "").strip() or summary_text
                    except Exception as e:
                        logger.error(f"   ⚠️ 生成第{chapter_num}章摘要失败，将回退简要摘要: {e}")

                if not summary_text:
                    summary_text = content[:200] if content and len(content) > 200 else content

                summaries.append(f"第{chapter_num}章 《{title}》: {summary_text}...")
                previous_chapters_payload.append(
                    {
                        "chapter_number": chapter_num,
                        "title": title,
                        "content": content,
                        "summary": summary_text,
                    }
                )

            return "\n\n".join(summaries), previous_chapters_payload

        previous_chapters_summary, previous_chapters_payload = summarize_chapters(existing_chapters)

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
            "created_at": datetime.now().isoformat()
        })
        db.commit()
        logger.info(f"   ✅ 任务记录已创建")

        # 7. 启动后台任务
        asyncio.create_task(
            execute_generate_next_chapter_task(
                task_id=task_id,
                project_id=project_id,
                user_id=current_user.id,
                next_chapter_number=next_chapter_number,
                concept=concept or '',
                world_setting=world_setting or '',
                characters=characters or '',
                plot_outline=plot_outline or '',
                previous_ending=previous_ending,
                previous_chapters_summary=previous_chapters_summary,
                previous_chapters_payload=previous_chapters_payload,
            )
        )
        logger.info(f"   🚀 后台任务已启动")

        # 8. 立即返回响应
        return {
            "task_id": task_id,
            "status": "running",
            "message": f"已开始生成第{next_chapter_number}章",
            "next_chapter_number": next_chapter_number
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

    # 获取流式服务
    streaming_service = get_streaming_service()

    # 创建独立的数据库会话
    db = SessionLocal()

    # 🆕 定义四个步骤对应的 Agent 列表
    STEP_AGENTS = {
        'structure': [  # 步骤1：章节规划
            {'id': 'plot_architect', 'name': '情节架构师', 'stage': 'structure'},
            {'id': 'event_validator', 'name': '事件验证官', 'stage': 'structure'},
        ],
        'content': [  # 步骤2：内容创作
            {'id': 'content_creator', 'name': '内容创作师', 'stage': 'content'},
            {'id': 'style_optimizer', 'name': '文风优化师', 'stage': 'content'},
        ],
        'review': [  # 步骤3：质量评审
            {'id': 'quality_reviewer', 'name': '质量评审官', 'stage': 'review'},
        ],
        'iteration': [  # 步骤4：迭代优化
            {'id': 'iteration_coordinator', 'name': '迭代协调官', 'stage': 'iteration'},
            {'id': 'content_reviser', 'name': '内容修订师', 'stage': 'iteration'},
            {'id': 'final_reviewer', 'name': '最终审核官', 'stage': 'iteration'},
        ],
    }

    try:
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

        real_coordinator = coordinator._real_coordinator
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

        # 🆕 根据章节编号判断爽点节奏（复刻 generate_chapter_plan 的逻辑）
        is_climax_chapter = next_chapter_number % 5 == 0  # 每5章一个小高潮
        is_major_climax = next_chapter_number % 25 == 0   # 每25章一个大高潮

        climax_instruction = ""
        if is_major_climax:
            climax_instruction = f"""
⚠️ 【卷末大高潮章节】第{next_chapter_number}章是本卷结尾，需要：
- 设计一个让读者拍案叫绝的大爽点
- 本卷主要矛盾要有阶段性解决
- 为下一卷埋下新的悬念"""
        elif is_climax_chapter:
            climax_instruction = f"""
⚠️ 【小高潮章节】第{next_chapter_number}章需要设计一个明确的爽点：
- 可以是：打脸嘲讽者/突破升级/获得宝物/反转翻盘/装逼成功"""

        # 🆕 构建章节规划提示词（网文化版本）
        plan_system_prompt = """你是一位资深网络小说情节规划师，精通爽点设计和读者心理。
你的任务是为章节制定详细的创作计划，确保情节吸引人、节奏紧凑、爽点分明。"""

        plan_user_prompt = f"""请为第{next_chapter_number}章制定创作计划。

【整本书信息】
- 故事概念：{concept}
- 情节大纲：{plot_outline}
- 世界观：{world_setting}
- 主要人物：{characters}

【已完成章节摘要】
{previous_chapters_summary if previous_chapters_summary else '（这是第一章）'}

【前一章结尾】
{previous_ending if previous_ending else '（这是第一章，没有前一章）'}
{climax_instruction}

---

请为第{next_chapter_number}章制定创作计划，必须包含以下内容：

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

## 4. 人物发展
- 主角本章的成长或变化
- 重要配角的表现
- 人物关系推进

## 5. 结尾钩子设计 🎣
- 钩子类型：【悬念式/危机式/反转式/信息炸弹式/选择困境式】
- 钩子具体内容
- 确保读者有"想点下一章"的冲动

## 6. 场景安排
- 时间、地点、氛围
- 场景转换节点

---

要求：
- 确保与整本书的情节大纲保持一致
- 确保与前面章节的剧情连贯
- 推进故事发展，不能原地踏步
- 爽点和钩子必须具体、可执行"""

        # 🆕 使用真流式 LLM 调用
        try:
            chapter_plan = await streaming_service.generate_chapter_streaming(
                prompt=plan_user_prompt,
                system_prompt=plan_system_prompt,
                on_chunk=on_plan_chunk,
                temperature=0.7,
            )
            logger.info(f"   ✓ 章节规划已完成（真流式），长度: {len(chapter_plan)}")
        except Exception as e:
            logger.error(f"   ⚠️ 真流式调用失败，回退到同步调用: {e}")
            # 回退到同步调用
            if hasattr(real_coordinator, 'generate_chapter_plan'):
                chapter_plan = await asyncio.to_thread(
                    real_coordinator.generate_chapter_plan,
                    chapter_number=next_chapter_number,
                    project_concept=concept,
                    plot_outline=plot_outline,
                    world_setting=world_setting,
                    characters=characters,
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
            "对话开头": ("对话开头", "直接进入冲突或紧张场景", "'站住！'身后传来一声厉喝。"),
            "动作开头": ("动作开头", "正在发生的动态事件", "刀光闪过，血珠在空中划出一道弧线。"),
            "悬念开头": ("悬念开头", "抛出问题，引发好奇", "三天后回想起这个决定时，她依然后悔不已。"),
            "场景开头": ("场景开头", "氛围渲染，快速建立情境", "暴雨倾盆，整个长安城笼罩在一片灰蒙蒙的水雾中。"),
            "反转开头": ("反转开头", "与上章结尾形成对比或反差", "然而他睁开眼时，发现自己躺在一张软榻上。"),
        }
        ending_styles = {
            "悬念式": ("悬念式", "关键信息揭露一半", "信封里只有一张纸，上面写着三个字——"),
            "转折式": ("转折式", "意外事件发生", "就在她以为一切结束时，门外响起了敲门声。来人是——"),
            "动作中断式": ("动作中断式", "危机时刻戛然而止", "刀锋距离她的咽喉只有一寸。她闭上眼睛——"),
            "信息炸弹式": ("信息炸弹式", "惊人真相揭露", "'你以为我是谁？'他摘下面具，露出一张与她父亲一模一样的脸。"),
            "选择困境式": ("选择困境式", "主角面临艰难抉择", "救左边的师父，还是右边的爱人？她只有三秒钟做出决定。"),
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

        # 🆕 Typed-RAG（按类型检索并注入提示）
        try:
            from app.core.config import settings
            from app.services.vector_sync import get_vector_kb
            kb = get_vector_kb()
            rag_character_context = ""
            rag_world_context = ""
            if kb and getattr(settings, "ENABLE_TYPED_RAG", True):
                # 使用章节规划作为查询上下文
                char_docs = kb.search(query=chapter_plan, k=getattr(settings, "TYPED_RAG_K_CHAR", 4), filter_type="character", project_id=project_id)
                world_docs = kb.search(query=chapter_plan, k=getattr(settings, "TYPED_RAG_K_WORLD", 5), filter_type="world_setting", project_id=project_id)
                if char_docs:
                    rag_character_context = "\n".join([f"- {d.metadata.get('name','未知角色')}: {d.page_content[:300]}" for d in char_docs])
                if world_docs:
                    rag_world_context = "\n".join([f"- {d.metadata.get('title','设定')}: {d.page_content[:400]}" for d in world_docs])
                logger.info(f"   📚 RAG注入：人物{len(char_docs)}条，设定{len(world_docs)}条")
        except Exception as rag_e:
            logger.warning(f"   ⚠️ Typed-RAG 注入失败: {rag_e}")
            rag_character_context = ""
            rag_world_context = ""

        # 🆕 构建内容创作提示词（增强版）
        content_system_prompt = """你是一位经验丰富的网络小说作家。请根据提供的章节规划、世界观设定和人物设定，创作精彩的章节内容。

创作要求：
1. 语言生动，描写细腻，符合网文风格
2. 对话自然，符合人物性格
3. 情节紧凑，引人入胜，注意爽点节奏
4. 场景描写要有画面感
5. 注意段落分隔，便于阅读
6. 开头要有吸引力，结尾要有悬念
7. 使用场景描写、对话、心理描写等多种手法

【质量标准】
- ✅ 与前面章节的情节连贯一致
- ✅ 人物性格和行为符合已有描写
- ✅ 遵循已建立的世界观规则和设定
- ✅ 延续已有的叙事风格和文笔特点
- ✅ 推进主线情节，避免原地踏步
- ✅ 注重细节的合理性和真实感

【输出格式要求】⚠️
请直接输出章节内容，格式必须如下：

第X章 章节标题

章节正文内容...

注意：
- 第一行必须是章节标题，格式为"第X章 标题名称"（X为章节数字）
- 章节标题要简洁有力，能概括本章核心内容或悬念
- 不要包含任何额外的说明文字、作者话语等"""

        content_user_prompt = f"""请创作第{next_chapter_number}章内容：

【章节规划】
{chapter_plan}

【世界观设定】
{world_setting}

【人物设定】
{characters}

【RAG检索-人物（自动注入）】
{rag_character_context if rag_character_context else '（无）'}

【RAG检索-世界设定（自动注入）】
{rag_world_context if rag_world_context else '（无）'}

【情节大纲】
{plot_outline}

【前一章结尾】
{previous_ending if previous_ending else '（这是第一章，请设计一个引人入胜的开场）'}

【目标字数】约3000字

【本章开头方式 - 强制要求】⚠️
本章必须使用【{selected_opening[0]}】方式开头！
- 技巧说明：{selected_opening[1]}
- 参考示例：{selected_opening[2]}

❌ 禁止使用：每章都用"XXX醒来/睁开眼睛/阳光照进房间"开头

【本章结尾方式 - 强制要求】⚠️
本章必须使用【{selected_ending[0]}】结尾！
- 技巧说明：{selected_ending[1]}
- 参考示例：{selected_ending[2]}

❌ 禁止使用：总结式内心独白 + 对未来的展望（如"她知道，从这一刻起..."）
✅ 结尾要制造钩子，让读者想点下一章

请开始创作第{next_chapter_number}章内容："""

        # 🆕 使用真流式 LLM 调用
        logger.info(f"   🚀 开始调用流式 LLM 服务生成章节内容...")
        try:
            chapter_draft = await streaming_service.generate_chapter_streaming(
                prompt=content_user_prompt,
                system_prompt=content_system_prompt,
                on_chunk=on_content_chunk,
                temperature=0.7,
            )
            logger.info(f"   ✓ 章节初稿已完成（真流式），字数: {len(chapter_draft)}")
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
                        characters=characters,
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
        update_query = text("""
            UPDATE project_settings
            SET chapter_draft = :chapter_draft, updated_at = :updated_at
            WHERE project_id = :project_id
        """)
        db.execute(update_query, {
            "chapter_draft": chapter_draft,
            "updated_at": datetime.now().isoformat(),
            "project_id": project_id
        })
        db.commit()
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

        # 🆕 构建评审提示词（网文6维度评审体系）
        review_system_prompt = """你是一位专业的网络小说质量评审官。请使用【网文6维度评审体系】对章节内容进行评审。

## 📊 网文6维度评审体系

### 1. 爽点效果（权重25%）
- 本章是否有明确的爽点（打脸/升级/获得宝物/装逼成功/反转翻盘等）？
- 爽点铺垫是否充分？释放是否有力？
- 如果是过渡章节，是否为后续爽点做了必要铺垫？

### 2. 节奏把控（权重20%）
- 紧张与舒缓是否平衡？
- 信息密度是否适中（不过载也不空洞）？
- 场景转换是否流畅？
- 对话与叙述比例是否合理（建议30-50%对话）？

### 3. 钩子效果（权重15%）
- 章节开头是否吸引人？（是否避免了"醒来/阳光照进"的套路开头）
- 章节结尾是否有悬念/钩子？（是否避免了"她知道从这一刻起..."的总结式结尾）
- 读者是否有"想点下一章"的冲动？
- 伏笔铺设是否自然？

### 4. 代入感（权重15%）
- 主角视角是否清晰？
- 读者能否代入主角的处境和情感？
- 配角是否有存在感而不抢戏？
- 情感共鸣是否充分？

### 5. 文笔流畅度（权重10%）
- 是否有明显的AI痕迹或机械感？
- 对话是否自然、符合人物性格？
- 是否有病句、重复、啰嗦？
- 描写是否生动有画面感？

### 6. 内容一致性（权重15%）
- 人物设定是否与前文一致（性格、能力、外貌、背景）？
- 世界观规则是否与前文一致？
- 时间线是否合理？
- 道具/物品是否与前文一致？"""

        review_user_prompt = f"""请评审以下第{next_chapter_number}章内容：

【章节规划】
{chapter_plan}

【情节大纲】
{plot_outline}

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

        # 🆕 使用真流式 LLM 调用
        try:
            review_report = await streaming_service.generate_chapter_streaming(
                prompt=review_user_prompt,
                system_prompt=review_system_prompt,
                on_chunk=on_review_chunk,
                temperature=0.7,
            )
            logger.info(f"   ✓ 评审完成（真流式），报告长度: {len(review_report)}")
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
        update_query = text("""
            UPDATE project_settings
            SET review_report = :review_report, updated_at = :updated_at
            WHERE project_id = :project_id
        """)
        db.execute(update_query, {
            "review_report": review_report,
            "updated_at": datetime.now().isoformat(),
            "project_id": project_id
        })
        db.commit()
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
        for agent in step4_agents:
            await ws_manager.send_agent_status(
                project_id=project_id,
                stage=agent['stage'],
                agent_id=agent['id'],
                agent_name=agent['name'],
                status='working',
                progress=0,
                message=f'{agent["name"]}正在优化章节内容...'
            )
        logger.info(f"   📡 已发送 {len(step4_agents)} 个 Agent 开始状态（步骤4）")

        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=80,
            message=f"步骤 4/4: 正在优化第{next_chapter_number}章内容..."
        )
        logger.info(f"   → 步骤4: 迭代优化（真流式）...")

        # 🆕 发送流式开始通知
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
        iteration_system_prompt = """你是一位资深的网络小说编辑。请根据评审意见对章节内容进行优化修改。

优化要求：
1. 保持原有故事框架和主要情节不变
2. 改进语言表达，使文笔更加流畅
3. 增强细节描写，提升画面感
4. 优化对话内容，使其更符合人物性格
5. 提升整体可读性和爽感
6. 修正任何语病或不连贯之处
7. 优化后的章节应完整保留原有情节发展，篇幅不应少于原稿字数的80%

【输出格式要求】⚠️
请直接输出优化后的章节内容，格式必须如下：

第X章 章节标题

章节正文内容...

注意：
- 第一行必须是章节标题，格式为"第X章 标题名称"（X为章节数字）
- 如果原稿有章节标题则保留或优化，如果没有则根据内容新增一个
- 不要包含任何评论、解释、优化说明等额外文字
- 只输出：章节标题 + 章节正文内容"""

        iteration_user_prompt = f"""请根据以下评审意见优化第{next_chapter_number}章：

【原始章节内容】
{chapter_draft}

【评审意见】
{review_report}

请直接输出优化后的章节内容（第一行为章节标题）："""

        # 🆕 使用真流式 LLM 调用
        try:
            final_version = await streaming_service.generate_chapter_streaming(
                prompt=iteration_user_prompt,
                system_prompt=iteration_system_prompt,
                on_chunk=on_iteration_chunk,
                temperature=0.7,
            )
            logger.info(f"   ✓ 优化完成（真流式），最终字数: {len(final_version)}")
        except Exception as e:
            logger.error(f"   ⚠️ 真流式调用失败，回退到同步调用: {e}")
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
        update_query = text("""
            UPDATE project_settings
            SET final_version = :final_version, updated_at = :updated_at
            WHERE project_id = :project_id
        """)
        db.execute(update_query, {
            "final_version": final_version,
            "updated_at": datetime.now().isoformat(),
            "project_id": project_id
        })
        db.commit()
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

        # 保存到 chapters 表
        insert_query = text("""
            INSERT INTO chapters (project_id, chapter_number, title, content, word_count, created_at)
            VALUES (:project_id, :chapter_number, :title, :content, :word_count, :created_at)
        """)
        db.execute(insert_query, {
            "project_id": project_id,
            "chapter_number": next_chapter_number,
            "title": chapter_title,
            "content": final_version,
            "word_count": len(final_version),
            "created_at": datetime.now().isoformat()
        })
        db.commit()

        # 获取新插入记录的ID
        new_chapter_id = db.execute(text("SELECT last_insert_rowid()")).scalar()
        if not new_chapter_id:
            check_query = text("""
                SELECT id FROM chapters
                WHERE project_id = :project_id AND chapter_number = :chapter_number
                ORDER BY created_at DESC LIMIT 1
            """)
            new_chapter_id = db.execute(check_query, {
                "project_id": project_id,
                "chapter_number": next_chapter_number
            }).scalar()

        logger.info(f"   ✓ 章节已保存: id={new_chapter_id}")

        # 🆕 阶段2：从章节自动抽取设定候选并入库（供人工确认）
        try:
            import re
            import json
            from app.models.setting import SettingCollection, SettingItem

            # 确保存在“设定候选”集合
            candidate_collection = db.query(SettingCollection).filter(
                SettingCollection.project_id == project_id,
                SettingCollection.category == "candidate"
            ).first()
            if not candidate_collection:
                candidate_collection = SettingCollection(
                    project_id=project_id,
                    name="设定候选",
                    category="candidate",
                    description="自动从章节抽取的待确认设定项",
                    order=999
                )
                db.add(candidate_collection)
                db.commit()
                db.refresh(candidate_collection)

            chapter_text = final_version or ""
            patterns = [
                ("功法", r"([一-龥A-Za-z0-9]{2,12})功法|功法《(.{1,20})》"),
                ("丹药", r"([一-龥A-Za-z0-9]{2,12})丹药|丹药《(.{1,20})》"),
                ("阵法", r"([一-龥A-Za-z0-9]{2,12})阵法|阵法《(.{1,20})》"),
                ("门派/宗门", r"([一-龥A-Za-z0-9]{2,12})(宗门|门派)"),
                ("秘境/遗迹", r"([一-龥A-Za-z0-9]{2,12})(秘境|遗迹)"),
                ("城市/城镇", r"([一-龥A-Za-z0-9]{2,12})(城|城镇|都市)"),
            ]

            # 推荐目标集合类别映射
            typ_to_category_map = {
                "功法": "technique_system",
                "丹药": "pill_system",
                "阵法": "formation_system",
                "门派/宗门": None,
                "秘境/遗迹": "map_system",
                "城市/城镇": "map_system",
            }

            extracted = []
            for typ, pat in patterns:
                for m in re.finditer(pat, chapter_text):
                    name = (m.group(1) or (m.group(2) if m.lastindex and m.lastindex >= 2 else "")).strip()
                    if not name:
                        continue
                    if any(x["name"] == name and x["type"] == typ for x in extracted):
                        continue
                    start = max(m.start() - 50, 0)
                    end = min(m.end() + 50, len(chapter_text))
                    excerpt = chapter_text[start:end]
                    extracted.append({"type": typ, "name": name, "excerpt": excerpt})

            # 限制一次入库数量，避免刷屏
            for item in extracted[:10]:
                # 计算推荐目标集合
                recommended_category = typ_to_category_map.get(item['type'])
                target_collection = None
                if recommended_category:
                    target_collection = db.query(SettingCollection).filter(
                        SettingCollection.project_id == project_id,
                        SettingCollection.category == recommended_category
                    ).first()
                # 选择写入集合：优先正式集合，否则候选集合
                write_collection_id = (target_collection.id if target_collection else candidate_collection.id)
                # 标记标签与推荐信息
                tag_list = (["自动抽取"] if target_collection else ["候选","自动抽取"])
                recommended_note = (f"\n推荐目标集合：{recommended_category}" if (recommended_category and not target_collection) else "")
                si = SettingItem(
                    collection_id=write_collection_id,
                    name=f"{item['name']}（{item['type']}）",
                    code=None,
                    level=1,
                    tags=json.dumps(tag_list, ensure_ascii=False),
                    content=f"来源：第{next_chapter_number}章\n上下文：{item['excerpt']}\n类型：{item['type']}" + recommended_note,
                    relations=None,
                    order=0
                )
                db.add(si)
            if extracted:
                db.commit()
                logger.info(f"   ✓ 抽取设定 {len(extracted[:10])} 项并入库（含推荐集合规则）")
        except Exception as e:
            logger.warning(f"   ⚠️ 设定候选抽取失败: {e}")

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

        # 生成章节摘要
        try:
            from app.services.agents.chapter_summarizer import create_chapter_summarizer
            summarizer = create_chapter_summarizer(db_session=db)
            summarizer.get_or_generate_summary(
                chapter_id=new_chapter_id,
                chapter_number=next_chapter_number,
                chapter_title=chapter_title,
                chapter_content=final_version,
                summary_length=300
            )
            logger.info(f"   ✓ 章节摘要已生成")
        except Exception as e:
            logger.error(f"   ⚠️ 生成章节摘要失败: {e}")

        # 同步到知识库
        try:
            from app.services.vector_sync import sync_to_vector_db
            sync_to_vector_db(
                kb_type="chapter",
                name=f"第{next_chapter_number}章 {chapter_title}",
                content=final_version,
                metadata={"project_id": str(project_id), "chapter_number": str(next_chapter_number)}
            )
            logger.info(f"   ✓ 章节已同步到知识库")
        except Exception as e:
            logger.error(f"   ⚠️ 同步知识库失败: {e}")

        # 更新任务状态为完成
        update_query = text("""
            UPDATE generation_history
            SET status = :status, completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        db.execute(update_query, {
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        # 发送完成事件
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

        logger.info(f"✅ 后台任务完成: {task_id}, 第{next_chapter_number}章已生成")

    except Exception as e:
        logger.error(f"❌ 后台任务失败: {task_id}, 错误: {e}")
        import traceback
        traceback.print_exc()

        # 更新任务状态为失败
        try:
            update_query = text("""
                UPDATE generation_history
                SET status = :status, error_message = :error_message, completed_at = :completed_at
                WHERE task_id = :task_id
            """)
            db.execute(update_query, {
                "status": "failed",
                "error_message": str(e),
                "completed_at": datetime.now().isoformat(),
                "task_id": task_id
            })
            db.commit()
        except Exception:
            pass

        # 发送错误事件
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e)
        )
    finally:
        db.close()


@router.post("/expand-outline")
async def expand_outline(
    request: ExpandOutlineRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    扩展情节大纲
    
    请求体:
    {
        "project_id": 1,
        "current_outline": "当前的简短大纲...",
        "world_setting": "世界观设定...",
        "characters": "人物设定...",
        "target_chapters": 50
    }
    
    响应:
    {
        "success": true,
        "expanded_outline": "扩展后的完整大纲...",
        "chapter_breakdown": "章节分解...",
        "plot_arcs": "情节线索...",
        "target_chapters": 50
    }
    """
    import logging
    import sys
    import os
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"📖 开始扩展大纲，项目ID: {request.project_id}")
        
        # 1. 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == request.project_id) & (Project.user_id == current_user.id)
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        
        # 2. 导入大纲扩展器
        try:
            from app.services.agents.outline_expander import create_outline_expander
            logger.info("   ✅ 成功导入 outline_expander")
        except ImportError as e:
            logger.error(f"   ❌ 导入失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"大纲扩展器未安装: {str(e)}"
            )
        
        # 3. 创建扩展器实例
        expander = create_outline_expander()
        logger.info("   ✅ 扩展器实例已创建")

        # 3.5 生成类型化设定摘要并注入世界观
        settings_summary = build_project_settings_summary(request.project_id, db)
        combined_world_setting = request.world_setting or ""
        if settings_summary:
            combined_world_setting = (
                f"{combined_world_setting}\n\n{settings_summary}"
                if combined_world_setting
                else settings_summary
            )
        logger.info("   📚 已生成设定摘要并合并到世界观上下文")

        # 4. 执行大纲扩展（渐进式）
        target_chapters = request.current_chapter_count + request.increment
        logger.info(f"   🚀 开始扩展大纲（从 {request.current_chapter_count} 章扩展到 {target_chapters} 章）...")

        result = expander.expand_plot_outline_incremental(
            current_outline=request.current_outline,
            world_setting=combined_world_setting,
            characters=request.characters,
            current_chapter_count=request.current_chapter_count,
            increment=request.increment,
            target_total_chapters=request.target_total_chapters,
        )

        logger.info("   ✅ 大纲扩展完成")
        
        # 5. 保存扩展结果到project_settings
        from sqlalchemy import text
        
        update_query = text("""
            UPDATE project_settings
            SET plot_outline = :plot_outline,
                updated_at = :updated_at
            WHERE project_id = :project_id
        """)
        
        db.execute(update_query, {
            "plot_outline": result["expanded_outline"],
            "updated_at": datetime.now().isoformat(),
            "project_id": request.project_id
        })
        db.commit()
        logger.info("   💾 扩展大纲已保存到数据库")

        return {
            "success": True,
            "expanded_outline": result["expanded_outline"],
            "chapter_breakdown": result["chapter_breakdown"],
            "plot_arcs": result.get("plot_arcs", ""),
            "current_chapter_count": result["current_chapter_count"],
            "should_continue": result["should_continue"],  # 🆕 AI建议是否继续扩展
            "continue_reason": result.get("continue_reason", "")  # 🆕 继续扩展的原因
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 扩展大纲失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/expand-characters")
async def expand_characters(
    request: ExpandCharactersRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    扩展人物体系
    
    请求体:
    {
        "project_id": 1,
        "main_characters": "当前主要人物...",
        "world_setting": "世界观设定...",
        "plot_outline": "情节大纲...",
        "target_count": 15
    }
    
    响应:
    {
        "success": true,
        "all_characters": "完整人物档案...",
        "character_relationships": "人物关系网络...",
        "role_distribution": "角色定位...",
        "target_count": 15
    }
    """
    import logging
    import sys
    import os
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"👥 开始扩展人物，项目ID: {request.project_id}")
        
        # 1. 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == request.project_id) & (Project.user_id == current_user.id)
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        
        # 2. 导入扩展器
        try:
            from app.services.agents.outline_expander import create_outline_expander
            logger.info("   ✅ 成功导入 outline_expander")
        except ImportError as e:
            logger.error(f"   ❌ 导入失败: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"人物扩展器未安装: {str(e)}"
            )
        
        # 3. 创建扩展器实例
        expander = create_outline_expander()
        logger.info("   ✅ 扩展器实例已创建")

        # 3.5 生成类型化设定摘要并注入世界观
        settings_summary = build_project_settings_summary(request.project_id, db)
        combined_world_setting = request.world_setting or ""
        if settings_summary:
            combined_world_setting = (
                f"{combined_world_setting}\n\n{settings_summary}"
                if combined_world_setting
                else settings_summary
            )
        logger.info("   📚 已生成设定摘要并合并到世界观上下文")

        # 4. 执行人物扩展（渐进式）
        target_count = request.current_character_count + request.increment
        logger.info(f"   🚀 开始扩展人物（从 {request.current_character_count} 个扩展到 {target_count} 个）...")

        result = expander.expand_characters_incremental(
            main_characters=request.main_characters,
            world_setting=combined_world_setting,
            plot_outline=request.plot_outline,
            current_character_count=request.current_character_count,
            increment=request.increment,
            target_total_characters=request.target_total_characters,
        )

        logger.info("   ✅ 人物扩展完成")
        
        # 5. 保存扩展结果到project_settings
        from sqlalchemy import text
        
        update_query = text("""
            UPDATE project_settings
            SET characters = :characters,
                updated_at = :updated_at
            WHERE project_id = :project_id
        """)
        
        db.execute(update_query, {
            "characters": result["all_characters"],
            "updated_at": datetime.now().isoformat(),
            "project_id": request.project_id
        })
        db.commit()
        logger.info("   💾 扩展人物已保存到数据库")

        # 6. 🆕 自动解析人物卡并同步到结构化characters表
        sync_result = {"parsed": 0, "created": 0, "updated": 0, "skipped": 0}
        try:
            from app.services.character_parser import parse_and_sync_characters

            sync_result = parse_and_sync_characters(
                project_id=request.project_id,
                characters_text=result["all_characters"],
                db_session=db
            )
            logger.info(f"   🔄 人物卡同步完成: 解析 {sync_result['parsed']} 个, "
                       f"创建 {sync_result['created']} 个, 更新 {sync_result['updated']} 个")
        except Exception as e:
            logger.warning(f"   ⚠️  自动同步人物卡失败: {e}")
            import traceback
            traceback.print_exc()

        return {
            "success": True,
            "all_characters": result["all_characters"],
            "character_relationships": result.get("character_relationships", ""),
            "role_distribution": result.get("role_distribution", ""),
            "current_character_count": result["current_character_count"],
            "should_continue": result["should_continue"],  # 🆕 AI建议是否继续扩展
            "continue_reason": result.get("continue_reason", ""),  # 🆕 继续扩展的原因
            "character_sync": sync_result  # 🆕 人物卡同步统计
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 扩展人物失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
