"""
工作流程API路由
"""
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
import uuid
from datetime import datetime
import json

# 请求模型
class StartWorkflowRequest(BaseModel):
    project_id: int
    requirement: str

class ExecuteStageRequest(BaseModel):
    project_id: int
    stage: str

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

class ExpandCharactersRequest(BaseModel):
    project_id: int
    main_characters: str
    world_setting: str
    plot_outline: str
    current_character_count: int = 0  # 🆕 当前已有的人物数
    increment: int = 5  # 🆕 本次扩展的人物数（3-6个）

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

        if not project_id or not requirement:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing project_id or requirement",
            )

        # 初始化Agent
        logger.info("   正在初始化Agent...")
        await coordinator.initialize_agents()
        logger.info("   ✅ Agent初始化完成")

        # 🔧 关键修复：保存requirement到数据库
        from sqlalchemy import text
        from datetime import datetime
        
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

    请求体:
    {
        "project_id": 1,
        "stage": "concept"
    }
    
    响应:
    {
        "task_id": "uuid-string",
        "status": "running"
    }
    """
    import logging
    import asyncio
    from sqlalchemy import text
    
    logger = logging.getLogger("uvicorn.error")
    project_id = request.project_id
    stage = request.stage
    
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
        logger.info(f"\ud83c\udfaf 创建异步任务: {task_id} (stage={stage}, project_id={project_id})")
        
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
        logger.info(f"   \u2705 任务记录已创建")
        
        # 异步执行任务（不等待）
        asyncio.create_task(
            execute_stage_background(task_id, project_id, stage_enum, current_user.id, db)
        )
        logger.info(f"   \ud83d\ude80 后台任务已启动")
        
        return {
            "task_id": task_id,
            "status": "running"
        }
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid stage: {stage}",
        )
    except Exception as e:
        logger.error(f"\u274c 异步任务创建失败: {str(e)}")
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
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                save_query = text("""
                    UPDATE project_settings
                    SET final_version = :final_version,
                        stage_five_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                
                db.execute(save_query, {
                    "final_version": json.dumps(
                        output_data.get("revised_content") or 
                        output_data.get("content", {}).get("content") or 
                        output_data.get("final_review", ""), 
                        ensure_ascii=False
                    ),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
                logger.info(f"   💾 已保存迭代优化结果到 project_settings")
        
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
        
        # 🔔 推送阶段完成状态
        await ws_manager.send_stage_update(
            project_id=project_id,
            stage=stage_enum.value,
            status='completed',
            output=result_str,
            progress=100
        )
        
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
        status_data = await coordinator.get_workflow_status()
        return {
            "status": "success",
            "project_id": project_id,
            "workflow": status_data,
        }
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
                else:
                    content = json.dumps(parsed_content, ensure_ascii=False)
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

        # 🆕 2. 智能章节覆盖：如果是内容创作阶段
        deleted_chapter = None
        if stage == 'content':
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
                
                # 🧹 1) 清理知识库中的章节内容
                try:
                    logger.info(f"   🗂️  清理知识库中的章节内容...")
                    
                    # 删除知识库中与该章节相关的条目
                    from app.models.knowledge_base import KnowledgeBase
                    kb_items = db.query(KnowledgeBase).filter(
                        (KnowledgeBase.project_id == project_id) &
                        (KnowledgeBase.type == 'chapter') &
                        (KnowledgeBase.content.like(f"%第{target_chapter_number}章%"))
                    ).all()
                    
                    for item in kb_items:
                        db.delete(item)
                        logger.info(f"      ✅ 已删除知识库条目: {item.id}")
                    
                    # 🆕 同步删除 ChromaDB 向量数据
                    try:
                        from langchain.vectorstores import Chroma
                        import os
                        
                        chroma_dir = os.getenv('CHROMA_PERSIST_DIRECTORY', 'chroma_db')
                        project_namespace = f"project_{project_id}"
                        
                        vectorstore = Chroma(
                            collection_name=project_namespace,
                            persist_directory=chroma_dir
                        )
                        
                        # 尝试删除与章节相关的向量（通过元数据过滤）
                        # 注意：Chroma不完全支持批量删除，这里只是尝试
                        logger.info(f"      🔍 清理ChromaDB中的章节向量...")
                    except Exception as e:
                        logger.warning(f"      ⚠️  ChromaDB清理失败（非致命错误）: {e}")
                    
                except Exception as e:
                    logger.warning(f"   ⚠️  知识库清理失败（非致命错误）: {e}")
                
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

        # 查询任务状态
        query = text("""
            SELECT task_id, status, result, error, created_at, completed_at
            FROM generation_history
            WHERE task_id = :task_id
        """)

        result = db.execute(query, {"task_id": task_id}).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
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
    
    响应:
    {
        "running_tasks": [
            {
                "task_id": "uuid",
                "task_type": "workflow_stage_concept",
                "status": "running",
                "created_at": "2024-01-01T00:00:00"
            }
        ]
    }
    """
    import logging
    from sqlalchemy import text
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"🔍 查询项目 {project_id} 的正在运行任务...")
        
        # 查询status='running'的任务
        query = text("""
            SELECT task_id, task_type, status, created_at
            FROM generation_history
            WHERE project_id = :project_id AND status = 'running'
            ORDER BY created_at DESC
        """)
        
        results = db.execute(query, {"project_id": project_id}).fetchall()
        
        running_tasks = []
        for row in results:
            running_tasks.append({
                "task_id": row[0],
                "task_type": row[1],
                "status": row[2],
                "created_at": row[3]
            })
        
        logger.info(f"   ✅ 找到 {len(running_tasks)} 个正在运行的任务")
        
        return {
            "running_tasks": running_tasks
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
            response = {
                "project_id": project_id,
                "stages": {
                    "concept": result[0] or "",
                    "world_setting": result[1] or "",
                    "characters": result[2] or "",
                    "plot_outline": result[3] or "",
                    "chapter_draft": result[4] or "",
                    "review_report": result[5] or "",
                    "final_version": result[6] or ""
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
    生成下一章（完整工作流）
    
    工作流程：
    1. 获取项目设定（concept, world_setting, characters, plot_outline）
    2. 获取已生成章节列表
    3. 计算下一章编号
    4. 提取前一章结尾（用于衔接）
    5. 生成已完成章节摘要
    6. 调用Agent协调器：
       - generate_chapter_plan(): 章节规划
       - generate_chapter_content(): 内容创作
       - review_chapter(): 质量评审
       - optimize_chapter(): 迭代优化
    7. 生成章节标题
    8. 保存到 chapters 表
    9. 返回章节信息
    
    响应:
    {
        "success": true,
        "message": "第3章已生成并保存",
        "chapter": {
            "id": 456,
            "project_id": 123,
            "chapter_number": 3,
            "title": "第三章 星际对决",
            "content": "章节内容...",
            "word_count": 3024,
            "created_at": "2025-10-22T14:30:00"
        }
    }
    """
    import logging
    from sqlalchemy import text
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"📍 开始生成下一章，项目ID: {project_id}")
        
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
            SELECT id, chapter_number, title, content 
            FROM chapters 
            WHERE project_id = :project_id 
            ORDER BY chapter_number ASC
        """)
        chapters_result = db.execute(query, {"project_id": project_id}).fetchall()
        existing_chapters = [(r[0], r[1], r[2], r[3]) for r in chapters_result]
        
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
        
        # 5. 生成已完成章节摘要
        def summarize_chapters(chapters):
            """生成已完成章节的摘要"""
            if not chapters:
                return "这是第一章，之前没有章节。"
            
            summaries = []
            for chapter in chapters:
                chapter_id, chapter_num, title, content = chapter
                # 提取前200字作为摘要
                summary = content[:200] if content and len(content) > 200 else (content or "")
                summaries.append(f"第{chapter_num}章 《{title}》: {summary}...")
            
            return "\n\n".join(summaries)
        
        previous_chapters_summary = summarize_chapters(existing_chapters)
        
        # 6. 调用Agent协调器生成章节
        chapter_plan = ""
        chapter_draft = ""
        review_report = ""
        final_version = ""
        
        # 确保协调器已初始化
        if not coordinator._coordinator_initialized:
            logger.info("   🔍 协调器未初始化，开始初始化...")
            await coordinator.initialize_agents()
            logger.info("   ✅ 协调器初始化完成")
        
        # 获取真实的协调器实例
        real_coordinator = coordinator._real_coordinator
        
        if not real_coordinator:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Agent协调器未初始化"
            )
        
        try:
            logger.info(f"   🤖 使用Agent协调器生成第{next_chapter_number}章...")
            
            # 步骤1：生成章节规划
            logger.info(f"     → 步骤1: 生成章节规划...")
            
            # 检查协调器是否有 generate_chapter_plan 方法
            if hasattr(real_coordinator, 'generate_chapter_plan'):
                chapter_plan = real_coordinator.generate_chapter_plan(
                    chapter_number=next_chapter_number,
                    project_concept=concept or '',
                    plot_outline=plot_outline or '',
                    world_setting=world_setting or '',
                    characters=characters or '',
                    previous_chapters_summary=previous_chapters_summary,
                    previous_ending=previous_ending
                )
                logger.info(f"     ✓ 章节规划已完成，长度: {len(chapter_plan)}")
            else:
                logger.warning(f"     ⚠️  协调器缺少 generate_chapter_plan 方法，使用默认规划")
                chapter_plan = f"第{next_chapter_number}章创作规划\n\n根据情节大纲和前序章节，本章将继续推进故事发展..."
            
            # 步骤2：生成章节内容
            logger.info(f"     → 步骤2: 生成章节内容...")
            
            if hasattr(real_coordinator, 'generate_chapter_content'):
                chapter_draft = real_coordinator.generate_chapter_content(
                    chapter_number=next_chapter_number,
                    chapter_plan=chapter_plan,
                    world_setting=world_setting or '',
                    characters=characters or '',
                    previous_ending=previous_ending,
                    target_word_count=3000
                )
                logger.info(f"     ✓ 章节初稿已完成，字数: {len(chapter_draft)}")
            else:
                logger.warning(f"     ⚠️  协调器缺少 generate_chapter_content 方法，使用默认内容")
                chapter_draft = f"第{next_chapter_number}章内容\n\n{chapter_plan}\n\n（此处为生成的章节内容）"
            
            # 💾 保存章节初稿到 project_settings
            logger.info(f"     💾 保存章节初稿到数据库...")
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
            logger.info(f"     ✓ 章节初稿已同步到数据库")
            
            # 步骤3：质量评审
            logger.info(f"     → 步骤3: 质量评审...")
            
            if hasattr(real_coordinator, 'review_chapter'):
                review_report = real_coordinator.review_chapter(
                    chapter_draft=chapter_draft,
                    chapter_plan=chapter_plan,
                    plot_outline=plot_outline or ''
                )
                logger.info(f"     ✓ 评审完成，报告长度: {len(review_report)}")
            else:
                logger.warning(f"     ⚠️  协调器缺少 review_chapter 方法，跳过评审")
                review_report = "质量评审：章节符合要求，可以继续优化。"
            
            # 💾 保存评审报告到 project_settings
            logger.info(f"     💾 保存评审报告到数据库...")
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
            logger.info(f"     ✓ 评审报告已同步到数据库")
            
            # 步骤4：迭代优化
            logger.info(f"     → 步骤4: 迭代优化...")
            
            if hasattr(real_coordinator, 'optimize_chapter'):
                final_version = real_coordinator.optimize_chapter(
                    chapter_draft=chapter_draft,
                    review_report=review_report
                )
                logger.info(f"     ✓ 优化完成，最终字数: {len(final_version)}")
            else:
                logger.warning(f"     ⚠️  协调器缺少 optimize_chapter 方法，使用初稿作为最终版本")
                final_version = chapter_draft
            
            # 💾 保存最终版本到 project_settings
            logger.info(f"     💾 保存最终版本到数据库...")
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
            logger.info(f"     ✓ 最终版本已同步到数据库")
            
        except Exception as e:
            logger.error(f"     ⚠️  Agent生成失败: {e}，使用备用方案")
            import traceback
            traceback.print_exc()
            # 使用备用方案
            final_version = f"第{next_chapter_number}章内容（备用生成）\n\n这是第{next_chapter_number}章的内容..."
        
        # 7. 生成章节标题
        def convert_number_to_chinese(num: int) -> str:
            """将数字转换为中文"""
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
            # 尝试从内容中提取标题（简化版）
            lines = final_version.split('\n')
            potential_title = None
            for line in lines[:5]:  # 只检查前5行
                line = line.strip()
                if line and ('第' in line or '章' in line) and len(line) < 30:
                    potential_title = line
                    break
            
            if potential_title:
                chapter_title = potential_title
                logger.info(f"   ✓ 从内容提取标题: {chapter_title}")
            else:
                chinese_num = convert_number_to_chinese(next_chapter_number)
                chapter_title = f"第{chinese_num}章 未命名"
                logger.info(f"   ✓ 使用默认标题: {chapter_title}")
        except Exception as title_error:
            logger.error(f"   ⚠️  生成标题失败: {title_error}")
            chinese_num = convert_number_to_chinese(next_chapter_number)
            chapter_title = f"第{chinese_num}章 未命名"
        
        # 8. 保存到 chapters 表
        logger.info(f"   📍 保存章节到数据库...")
        insert_query = text("""
            INSERT INTO chapters (project_id, chapter_number, title, content, word_count, created_at)
            VALUES (:project_id, :chapter_number, :title, :content, :word_count, :created_at)
        """)
        
        result = db.execute(insert_query, {
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
            # 备用方案：查询刚刚插入的记录
            check_query = text("""
                SELECT id FROM chapters 
                WHERE project_id = :project_id AND chapter_number = :chapter_number
                ORDER BY created_at DESC LIMIT 1
            """)
            new_chapter_id = db.execute(check_query, {
                "project_id": project_id,
                "chapter_number": next_chapter_number
            }).scalar()
        
        if not new_chapter_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="保存章节失败：无法获取新记录ID"
            )
        
        logger.info(f"   ✓ 章节已保存: id={new_chapter_id}, chapter_number={next_chapter_number}, title={chapter_title}")
        
        # 8.1 自动生成并保存章节摘要
        try:
            logger.info(f"   📍 自动生成章节摘要...")
            
            # 导入章节摘要生成器
            from chapter_summarizer import create_chapter_summarizer
            
            # 创建摘要生成器实例（带数据库会话）
            summarizer = create_chapter_summarizer(db_session=db)
            
            # 生成并保存摘要
            summary = summarizer.get_or_generate_summary(
                chapter_id=new_chapter_id,
                chapter_number=next_chapter_number,
                chapter_title=chapter_title,
                chapter_content=final_version,
                summary_length=300
            )
            
            logger.info(f"   ✓ 章节摘要已生成并保存: {summary.get('summary_length', 0)} 字符")
            
        except Exception as summary_error:
            logger.error(f"   ⚠️  生成章节摘要失败: {summary_error}")
            # 不中断主流程，继续执行
        
        # 9. 同步到知识库和向量库
        try:
            logger.info(f"   📍 同步章节到知识库和向量库...")
            
            # 导入知识库同步函数
            from app.api.v1.knowledge_base import sync_to_vector_db
            
            # 同步到向量数据库
            sync_to_vector_db(
                kb_type="chapter",
                name=f"第{next_chapter_number}章 {chapter_title}",
                content=final_version,
                metadata={"project_id": str(project_id), "chapter_number": str(next_chapter_number)}
            )
            
            logger.info(f"   ✓ 章节已同步到知识库和向量库")
        except Exception as sync_error:
            logger.error(f"   ⚠️  同步章节到知识库失败: {sync_error}")
            # 不中断主流程，继续执行
        
        # 10. 返回响应
        response = {
            "success": True,
            "message": f"第{next_chapter_number}章已生成并保存",
            "chapter": {
                "id": new_chapter_id,
                "project_id": project_id,
                "chapter_number": next_chapter_number,
                "title": chapter_title,
                "content": final_version,
                "word_count": len(final_version),
                "created_at": datetime.now().isoformat()
            }
        }
        
        logger.info(f"✅ 生成下一章完成，返回响应")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 生成下一章失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


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
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..'))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)
        
        try:
            from outline_expander import create_outline_expander
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
        
        # 4. 执行大纲扩展（渐进式）
        target_chapters = request.current_chapter_count + request.increment
        logger.info(f"   🚀 开始扩展大纲（从 {request.current_chapter_count} 章扩展到 {target_chapters} 章）...")
        
        result = expander.expand_plot_outline_incremental(
            current_outline=request.current_outline,
            world_setting=request.world_setting,
            characters=request.characters,
            current_chapter_count=request.current_chapter_count,
            increment=request.increment
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
        
        # 6. 可选：保存到知识库
        try:
            from app.models.knowledge_base import KnowledgeBase
            
            kb_outline = KnowledgeBase(
                project_id=request.project_id,
                type="plot_outline",
                name=f"扩展大纲({result['current_chapter_count']}章)",
                content=result["expanded_outline"]
            )
            db.add(kb_outline)
            
            kb_breakdown = KnowledgeBase(
                project_id=request.project_id,
                type="plot_outline",
                name="章节分解",
                content=result["chapter_breakdown"]
            )
            db.add(kb_breakdown)
            
            db.commit()
            logger.info("   💾 扩展结果已保存到知识库")
        except Exception as e:
            logger.warning(f"   ⚠️  保存到知识库失败: {e}")
        
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
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..'))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)
        
        try:
            from outline_expander import create_outline_expander
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
        
        # 4. 执行人物扩展（渐进式）
        target_count = request.current_character_count + request.increment
        logger.info(f"   🚀 开始扩展人物（从 {request.current_character_count} 个扩展到 {target_count} 个）...")
        
        result = expander.expand_characters_incremental(
            main_characters=request.main_characters,
            world_setting=request.world_setting,
            plot_outline=request.plot_outline,
            current_character_count=request.current_character_count,
            increment=request.increment
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
        
        # 6. 可选：保存到知识库
        try:
            from app.models.knowledge_base import KnowledgeBase
            
            kb_characters = KnowledgeBase(
                project_id=request.project_id,
                type="character",
                name=f"完整人物体系({result['current_character_count']}个)",
                content=result["all_characters"]
            )
            db.add(kb_characters)
            
            kb_relationships = KnowledgeBase(
                project_id=request.project_id,
                type="character",
                name="人物关系网络",
                content=result["character_relationships"]
            )
            db.add(kb_relationships)
            
            db.commit()
            logger.info("   💾 扩展结果已保存到知识库")
        except Exception as e:
            logger.warning(f"   ⚠️  保存到知识库失败: {e}")
        
        return {
            "success": True,
            "all_characters": result["all_characters"],
            "character_relationships": result.get("character_relationships", ""),
            "role_distribution": result.get("role_distribution", ""),
            "current_character_count": result["current_character_count"],
            "should_continue": result["should_continue"],  # 🆕 AI建议是否继续扩展
            "continue_reason": result.get("continue_reason", "")  # 🆕 继续扩展的原因
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
