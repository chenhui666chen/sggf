"""
工作流程API路由
支持流式输出 (Streaming) 功能
"""
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from pydantic import BaseModel
from app.db.base import get_db, SessionLocal
from app.services.agent_coordinator import (
    coordinator,
    StageType,
    AgentStatus,
)
from app.core.security import get_current_user
from app.models.project import Project, Chapter
from app.models.setting import SettingCollection
from app.websocket.manager import ws_manager
from app.services.setting_templates import build_project_settings_summary
import uuid
from datetime import datetime
import json
from sqlalchemy import text

# 🎉 导入体系自动检测服务
from app.services.auto_system_detector import auto_create_system_collections

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
    # 🆕 概念阶段评审/重生支持的可选参数
    regenerate: bool = False
    targets: Optional[list[str]] = None
    feedback: Optional[str] = None

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
    
    # 🔥 多模式扩展参数
    expansion_mode: str = "total"  # total(按总章数) / volume(按卷) / incremental(渐进式) / epic_framework(史诗框架) / volume_detail(单卷详细)
    target_volumes: Optional[int] = None  # 按卷模式:目标卷数
    chapters_per_volume_min: Optional[int] = 20  # 按卷模式:每卷最少章节数
    chapters_per_volume_max: Optional[int] = 30  # 按卷模式:每卷最多章节数
    incremental_step: Optional[int] = 10  # 渐进式模式:每次扩展章节数
    
    # 🌟 史诗框架模式参数(epic_framework)
    total_volumes: Optional[int] = None  # 史诗框架:总卷数(10-50卷)
    total_chapters_min: Optional[int] = None  # 史诗框架:总章节范围最小值
    total_chapters_max: Optional[int] = None  # 史诗框架:总章节范围最大值
    auto_expand_all_volumes: bool = False  # 🆕 是否自动扩展全部卷（默认仅生成框架）
    
    # 📖 单卷详细模式参数(volume_detail)
    framework_content: Optional[str] = None  # 基于的史诗框架内容
    target_volume_index: Optional[int] = None  # 扩展第几卷
    volume_chapters_min: Optional[int] = None  # 本卷章节范围最小值
    volume_chapters_max: Optional[int] = None  # 本卷章节范围最大值

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
    # 🔧 修复：CONCEPT 阶段需要结构化数据(concept/worldview/characters)，不适合流式模式
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
                execute_stage_background(task_id, project_id, stage_enum, current_user.id, db, getattr(request, 'regenerate', False), getattr(request, 'targets', None), getattr(request, 'feedback', None))
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


async def execute_stage_background(task_id: str, project_id: int, stage_enum: StageType, user_id: int, db: Session, regenerate: bool = False, targets: Optional[list[str]] = None, feedback: Optional[str] = None):
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
        
        # 🆕 题材与篇幅规划注入（概念阶段首次启动时）
        if stage_enum == StageType.CONCEPT and not regenerate:
            try:
                # 读取项目的题材与篇幅信息
                project_info_query = text("""
                    SELECT genre, sub_genre, planned_length_type, 
                           planned_chapters_min, planned_chapters_max, user_outline_plan
                    FROM projects 
                    WHERE id = :project_id
                """)
                proj_info = db.execute(project_info_query, {"project_id": project_id}).fetchone()
                
                if proj_info:
                    genre = proj_info[0]
                    sub_genre = proj_info[1]
                    planned_length_type = proj_info[2]
                    planned_chapters_min = proj_info[3]
                    planned_chapters_max = proj_info[4]
                    user_outline_plan = proj_info[5]
                    
                    # 🆕 如果有自定义大纲规划，先解析
                    if user_outline_plan and user_outline_plan.strip():
                        logger.info("📝 检测到用户自定义大纲规划，开始解析...")
                        
                        # 调用规划解析Agent
                        if hasattr(coordinator, '_real_coordinator'):
                            real_coord = coordinator._real_coordinator
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
                ref_query = text("SELECT concept, world_setting, characters FROM project_settings WHERE project_id = :project_id")
                ref_row = db.execute(ref_query, {"project_id": project_id}).fetchone()
                existing_concept = ref_row[0] if ref_row else None
                existing_world = ref_row[1] if ref_row else None
                existing_characters = ref_row[2] if ref_row else None

                def safe_text(value):
                    try:
                        import json
                        val = json.loads(value) if value else ""
                        if isinstance(val, (list, dict)):
                            val = json.dumps(val, ensure_ascii=False)
                        return str(val)
                    except Exception:
                        return str(value or "")

                concept_txt = safe_text(existing_concept)
                world_txt = safe_text(existing_world)
                char_txt = safe_text(existing_characters)

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
        # 🔧 概念阶段的重生：仅按目标推送相关Agent（默认 story+world，不包含人物）
        if stage_enum.value == 'concept' and regenerate:
            target_set = set(targets or ['story', 'world'])
            selected_ids = []
            if 'story' in target_set:
                selected_ids.append('creative_director')
            if 'world' in target_set:
                selected_ids.append('worldview_architect')
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
        if stage_enum == StageType.CONCEPT and hasattr(coordinator, '_real_coordinator'):
            real_coord = coordinator._real_coordinator
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
            "completed_at": datetime.now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        logger.info(f"   ✅ 任务完成: {task_id}")
        
        # 🆕 保存阶段输出到 project_settings（关键修复！）
        try:
            import json
            
            if stage_enum == StageType.CONCEPT:
                # 保存概念开发结果（支持评审/重生的目标字段选择）
                output_data = stage_output.output if isinstance(stage_output.output, dict) else {}
                # 读取现有值以便选择性覆盖
                existing_query = text("""
                    SELECT concept, world_setting, characters FROM project_settings WHERE project_id = :project_id
                """)
                existing_row = db.execute(existing_query, {"project_id": project_id}).fetchone()
                existing_concept = existing_row[0] if existing_row else None
                existing_world = existing_row[1] if existing_row else None
                existing_characters = existing_row[2] if existing_row else None

                # 安全解析现有JSON字符串
                def safe_json(value, default):
                    try:
                        import json
                        if value is None:
                            return default
                        parsed = json.loads(value)
                        return parsed
                    except Exception:
                        return default

                existing_concept_val = safe_json(existing_concept, "")
                existing_world_val = safe_json(existing_world, "")
                existing_characters_val = safe_json(existing_characters, [])

                targets_set = set(targets or [])
                is_regen = bool(regenerate)

                # 计算要保存的字段：非重生则全部覆盖；重生则按目标覆盖
                concept_to_save = output_data.get("concept", "") if not is_regen or ("story" in targets_set) else existing_concept_val
                world_to_save = output_data.get("worldview", output_data.get("world_setting", "")) if not is_regen or ("world" in targets_set) else existing_world_val
                characters_to_save = output_data.get("characters", []) if not is_regen else existing_characters_val

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
                    "concept": json.dumps(concept_to_save, ensure_ascii=False),
                    "world_setting": json.dumps(world_to_save, ensure_ascii=False),
                    "characters": json.dumps(characters_to_save, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
                logger.info(f"   💾 已保存概念开发结果到 project_settings（重生={is_regen}, targets={list(targets_set) if targets_set else []}）")
                
                # 🆕 从故事概念中提取日志标题，自动更新项目title
                if concept_to_save and isinstance(concept_to_save, str):
                    try:
                        import re
                        # 匹配日志标题（支持多种格式）
                        # 格式1: **日志标题（短标题）**：《...》 或 **日志标题**：《...》
                        # 格式2: 2. **日志标题...**：《...》
                        patterns = [
                            r'\*\*日志标题[^：:*]*\*\*[：:]\s*《([^》]+)》',
                            r'\d+\.\s*\*\*日志标题[^：:*]*\*\*[：:]\s*《([^》]+)》',
                            r'日志标题[：:]\s*《([^》]+)》',
                            r'\*\*日志标题[^：:*]*\*\*[：:]\s*([^\n。]+)',
                        ]
                        
                        log_title = None
                        for pattern in patterns:
                            match = re.search(pattern, concept_to_save)
                            if match:
                                log_title = match.group(1).strip()
                                # 移除可能的《》书名号
                                log_title = log_title.strip('《》')
                                break
                        
                        if log_title and len(log_title) >= 2:
                            # 更新项目标题
                            update_title_query = text("""
                                UPDATE projects SET title = :title, updated_at = :updated_at
                                WHERE id = :project_id
                            """)
                            db.execute(update_title_query, {
                                "title": log_title,
                                "updated_at": datetime.now().isoformat(),
                                "project_id": project_id
                            })
                            db.commit()
                            logger.info(f"   📝 已从日志标题更新项目title: {log_title}")
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
角色类型: {char.role or '未设定'}
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
                                    "role": char.role or ''
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
                
                save_query = text("""
                    UPDATE project_settings
                    SET plot_outline = :plot_outline,
                        stage_two_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                
                db.execute(save_query, {
                    "plot_outline": json.dumps(plot_outline_content, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
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
    from app.db.base import SessionLocal  # 🔧 导入 SessionLocal

    logger = logging.getLogger("uvicorn.error")

    # 🔧 关键修复：创建新的独立 db session（避免使用请求级别的 session）
    db = SessionLocal()
    
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
            default_content_model = getattr(settings, "DEFAULT_CONTENT_MODEL", "qwen-max")
        except Exception:
            default_content_model = "qwen-max"
        stage_model = None
        if stage_enum == StageType.CONTENT:
            stage_model = default_content_model
        elif stage_enum == StageType.REVIEW:
            stage_model = "deepseek-reasoner"
        elif stage_enum == StageType.ITERATION:
            stage_model = "deepseek-reasoner"
        if stage_model:
            await ws_manager.send_model_used(
                project_id=project_id,
                stage=stage_enum.value,
                model=stage_model,
                extra={"source": "execute_stage_with_streaming"}
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
                        "对话开头": ("对话开头", "直接进入冲突或紧张场景，用对话抽出矛盾", ""),
                        "动作开头": ("动作开头", "从正在发生的动态事件开始，制造紧迫感", ""),
                        "悬念开头": ("悬念开头", "抛出问题或异常现象，引发读者好奇，创造独特的开场", ""),
                        "场景开头": ("场景开头", "通过环境氛围描写快速建立情境，融入题材特色", ""),
                    }
                    ending_styles = {
                        "悬念式": ("悬念式", "关键信息揭露一半，留下悬念让读者想继续阅读", ""),
                        "转折式": ("转折式", "意外事件发生，打破读者预期", ""),
                        "信息炸弹式": ("信息炸弹式", "揭露惊人真相或身份，制造震撼效果", ""),
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
                # 🆕 按阶段选择模型，避免使用默认deepseek-chat
                stage_model = None
                try:
                    from app.core.config import settings
                    default_content_model = getattr(settings, "DEFAULT_CONTENT_MODEL", "qwen-max")
                except Exception:
                    default_content_model = "qwen-max"
                
                if stage_enum == StageType.CONTENT:
                    stage_model = default_content_model  # 内容创作：优先qwen-max（或按配置）
                elif stage_enum == StageType.REVIEW:
                    stage_model = "deepseek-reasoner"   # 质量评审：R1
                elif stage_enum == StageType.ITERATION:
                    stage_model = "deepseek-reasoner"   # 迭代优化（通用入口）：R1（专用生成下一章流程已改为max改稿+R1打分）
                
                result_str = await streaming_service.generate_chapter_streaming(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    on_chunk=on_stream_chunk,
                    temperature=0.7,
                    model=stage_model,
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
            "completed_at": datetime.now().isoformat(),
            "task_id": task_id
        })
        db.commit()

        logger.info(f"   ✅ 流式任务完成: {task_id}")

        # 保存阶段输出到 project_settings
        print(f"\n{'='*50}")
        print(f"🔍 准备保存到 project_settings: stage={stage_enum.value}, project_id={project_id}, result_len={len(result_str) if result_str else 0}")
        print(f"{'='*50}\n")
        logger.info(f"   🔍 准备保存到 project_settings: stage={stage_enum.value}, project_id={project_id}, result_len={len(result_str) if result_str else 0}")
        try:
            # 🔧 添加 CONCEPT 阶段的保存（同时保存 concept, world_setting, characters）
            if stage_enum == StageType.CONCEPT:
                logger.info(f"   🔍 匹配到 CONCEPT 阶段，开始保存...")
                # 🔧 直接使用已定义的 output_data 变量
                concept_data = output_data.get("concept", result_str) if isinstance(output_data, dict) and output_data else result_str
                worldview_data = output_data.get("worldview", "") or output_data.get("world_setting", "") if isinstance(output_data, dict) and output_data else ""
                characters_data = output_data.get("characters", "") if isinstance(output_data, dict) and output_data else ""
                
                logger.info(f"   🔍 CONCEPT 数据: concept={len(str(concept_data))}字, worldview={len(str(worldview_data))}字, characters={len(str(characters_data))}字")
                
                save_query = text("""
                    UPDATE project_settings
                    SET concept = :concept,
                        world_setting = :world_setting,
                        characters = :characters,
                        stage_one_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                result = db.execute(save_query, {
                    "concept": json.dumps(concept_data, ensure_ascii=False) if concept_data else None,
                    "world_setting": json.dumps(worldview_data, ensure_ascii=False) if worldview_data else None,
                    "characters": json.dumps(characters_data, ensure_ascii=False) if characters_data else None,
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                logger.info(f"   🔍 UPDATE 执行完成，影响行数: {result.rowcount}")
                db.commit()
                logger.info(f"   💾 已保存概念/世界观/人物到 project_settings（流式模式）")
                
                # 🆕 从故事概念中提取日志标题，自动更新项目title（流式模式）
                if concept_data and isinstance(concept_data, str):
                    try:
                        import re
                        patterns = [
                            r'\*\*日志标题[^：:*]*\*\*[：:]\s*《([^》]+)》',
                            r'\d+\.\s*\*\*日志标题[^：:*]*\*\*[：:]\s*《([^》]+)》',
                            r'日志标题[：:]\s*《([^》]+)》',
                            r'\*\*日志标题[^：:*]*\*\*[：:]\s*([^\n。]+)',
                        ]
                        
                        log_title = None
                        for pattern in patterns:
                            match = re.search(pattern, concept_data)
                            if match:
                                log_title = match.group(1).strip().strip('《》')
                                break
                        
                        if log_title and len(log_title) >= 2:
                            update_title_query = text("""
                                UPDATE projects SET title = :title, updated_at = :updated_at
                                WHERE id = :project_id
                            """)
                            db.execute(update_title_query, {
                                "title": log_title,
                                "updated_at": datetime.now().isoformat(),
                                "project_id": project_id
                            })
                            db.commit()
                            logger.info(f"   📝 已从日志标题更新项目title: {log_title}（流式模式）")
                    except Exception as e:
                        logger.warning(f"   ⚠️  提取日志标题失败（流式模式）: {e}")
            # 🔧 添加 STRUCTURE 阶段的保存
            elif stage_enum == StageType.STRUCTURE:
                save_query = text("""
                    UPDATE project_settings
                    SET plot_outline = :plot_outline,
                        stage_two_status = 'completed',
                        updated_at = :updated_at
                    WHERE project_id = :project_id
                """)
                db.execute(save_query, {
                    "plot_outline": json.dumps(result_str, ensure_ascii=False),
                    "updated_at": datetime.now().isoformat(),
                    "project_id": project_id
                })
                db.commit()
                logger.info(f"   💾 已保存结构大纲到 project_settings（流式模式）")
            elif stage_enum == StageType.CONTENT:
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
    finally:
        # 🔧 关键修复：关闭独立创建的 db session
        db.close()
        logger.info(f"   📝 db session 已关闭")


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

        # 4. 如果continue_workflow为true，创建任务记录并启动后台任务
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

            # 🔥 关键修复：启动后台任务执行下一阶段
            logger.info(f"🚀 启动后台任务执行下一阶段，task_id={task_id}")
            
            # 确定下一阶段
            stage_sequence = ['concept', 'structure', 'content', 'review', 'iteration']
            try:
                current_index = stage_sequence.index(stage)
                if current_index < len(stage_sequence) - 1:
                    next_stage_name = stage_sequence[current_index + 1]
                    next_stage_enum = StageType(next_stage_name)
                    
                    logger.info(f"   📍 下一阶段: {next_stage_name}")
                    
                    # 🆕 根据阶段判断是否启用流式输出
                    streaming_stages = [StageType.CONCEPT, StageType.CONTENT, StageType.REVIEW, StageType.ITERATION]
                    streaming_enabled = next_stage_enum in streaming_stages
                    
                    # 启动后台任务
                    if streaming_enabled:
                        asyncio.create_task(
                            execute_stage_with_streaming(
                                task_id, project_id, next_stage_enum, current_user.id, db
                            )
                        )
                        logger.info(f"   🌊 流式后台任务已启动: {next_stage_name}")
                    else:
                        asyncio.create_task(
                            execute_stage_background(
                                task_id, project_id, next_stage_enum, current_user.id, db, False, None, None
                            )
                        )
                        logger.info(f"   🚀 后台任务已启动: {next_stage_name}")
                else:
                    logger.info(f"   ✅ 已完成所有阶段，无需继续")
            except ValueError:
                logger.error(f"   ❌ 无效的阶段名称: {stage}")

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
                
                # ✅ 修复：优先检查是否为 JSON 对象/数组，避免误解析 Markdown 文本
                # 大纲扩展后的内容以 "# " 或 "---" 开头，不应被解析为 JSON
                try:
                    # 只解析明确的 JSON 对象或数组格式
                    if content.startswith('{') or content.startswith('['):
                        parsed = json.loads(content)
                        if isinstance(parsed, str):
                            return parsed
                        elif isinstance(parsed, (dict, list)):
                            return json.dumps(parsed, ensure_ascii=False, indent=2)
                        else:
                            return str(parsed)
                    # ⚠️ 移除对 "..." 格式的 JSON 解析，避免将 Markdown 文本误识别
                    # 如果内容以 " 开头但不是有效 JSON 字符串，直接返回原内容
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
            """生成已完成章节的摘要，并构造供内容生成使用的高层摘要列表。
            
            策略：2章最近章节全文 + 8章更靠前章节的摘要
            - 最近2章：使用完整内容（保证衔接自然）
            - 往前8章：使用结构化摘要（覆盖更长历史）
            - 更早章节：使用简要摘要（节省token）
            """
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
            RECENT_FULL_COUNT = 2  # 最近2章使用全文
            SUMMARY_COUNT = 8      # 往前8章使用详细摘要

            for idx, chapter in enumerate(chapters):
                chapter_id, chapter_num, title, content, existing_summary = chapter
                content = content or ""
                title = title or ""
                summary_text = (existing_summary or "").strip()

                # 计算当前章节距离最后一章的距离
                distance_from_end = total - idx

                # 判断是否需要生成详细摘要（最近2章之后的8章）
                needs_detailed_summary = (distance_from_end > RECENT_FULL_COUNT and 
                                        distance_from_end <= RECENT_FULL_COUNT + SUMMARY_COUNT)

                if summarizer and needs_detailed_summary:
                    # 对需要详细摘要的章节，生成200字结构化摘要
                    try:
                        summary_data = summarizer.get_or_generate_summary(
                            chapter_id=chapter_id,
                            chapter_number=chapter_num,
                            chapter_title=title or f"第{chapter_num}章",
                            chapter_content=content,
                            summary_length=200,
                        )
                        summary_text = summary_data.get("core_summary", "").strip() or summary_text
                        logger.info(f"   ✅ 第{chapter_num}章使用详细摘要（距离末尾{distance_from_end}章）")
                    except Exception as e:
                        logger.error(f"   ⚠️ 生成第{chapter_num}章摘要失败，将回退简要摘要: {e}")

                # 如果没有摘要，使用前200字作为简要摘要
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

            # 输出策略统计
            if total > 0:
                recent_full_range = f"第{max(1, total-RECENT_FULL_COUNT+1)}-{total}章" if total > RECENT_FULL_COUNT else f"第1-{total}章"
                summary_range_start = max(1, total - RECENT_FULL_COUNT - SUMMARY_COUNT + 1)
                summary_range_end = max(0, total - RECENT_FULL_COUNT)
                
                logger.info(f"   📊 上下文策略：")
                logger.info(f"      - 最近{min(RECENT_FULL_COUNT, total)}章全文: {recent_full_range}")
                if summary_range_end > 0:
                    logger.info(f"      - 往前{min(SUMMARY_COUNT, summary_range_end)}章摘要: 第{summary_range_start}-{summary_range_end}章")
                if total > RECENT_FULL_COUNT + SUMMARY_COUNT:
                    logger.info(f"      - 更早{total - RECENT_FULL_COUNT - SUMMARY_COUNT}章简要摘要: 第1-{total-RECENT_FULL_COUNT-SUMMARY_COUNT}章")

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
        plan_project_genre = ""
        try:
            plan_genre_query = text("SELECT genre FROM projects WHERE id = :project_id")
            plan_genre_result = db.execute(plan_genre_query, {"project_id": project_id}).fetchone()
            if plan_genre_result:
                plan_project_genre = plan_genre_result[0] or ""
            logger.info(f"   🎯 项目题材: {plan_project_genre or '通用'}")
        except Exception as e:
            logger.warning(f"   ⚠️ 获取项目题材失败: {e}")
        
        # 🆕 获取题材专属章节规划指导
        plan_genre_module = GENRE_PROMPT_MODULES.get(plan_project_genre, DEFAULT_GENRE_MODULE)
        chapter_plan_guide = plan_genre_module.get('chapter_plan_guide', '')
        
        # 🎆 使用分层摘要策略优化上下文
        layered_summarizer = LayeredSummarizer()
        plan_context_result = layered_summarizer.prepare_context_for_expansion(
            outline=plot_outline or "",
            characters=characters or "",
            worldview=world_setting or "",
            scenario="chapter_generation",
            current_count=next_chapter_number,  # 使用当前章节数选择模型
            focus_range=(max(1, next_chapter_number - 5), next_chapter_number + 5)  # 聚焦当前章节前后5章
        )
        
        # 🔥 使用智能选择的模型和优化后的上下文
        selected_plan_model = plan_context_result["selected_model"]
        plan_optimized_context_text = plan_context_result["context"]
        plan_stats = plan_context_result["stats"]
        
        logger.info(f"   📊 上下文优化（章节规划 - 分层摘要）:")
        logger.info(f"      - 选择模型: {selected_plan_model}")
        logger.info(f"      - 原始总长: {len(plot_outline or '') + len(characters or '') + len(world_setting or ''):,}字符")
        logger.info(f"      - 优化后: {len(plan_optimized_context_text):,}字符 (压缩{(1-plan_stats['compression_ratio'])*100:.1f}%)")
        logger.info(f"      - Token使用: {plan_stats['total_tokens']:,} / {plan_stats['target_tokens']:,}")
        logger.info(f"      - 聚焦范围: 第{max(1, next_chapter_number - 5)}-{next_chapter_number + 5}章")
        
        # 构建包含各部分的上下文字典（用于后续提示词构建）
        plan_optimized_context = {
            'project_concept': concept or '',
            'plot_outline': plan_optimized_context_text,  # 使用优化后的完整上下文
            'world_setting': '',  # 已包含在优化上下文中
            'characters': '',  # 已包含在优化上下文中
            'previous_chapters_analysis': previous_chapters_summary or '',
            'previous_ending': previous_ending or ''
        }
        # 🆕 广播步骤1模型
        await ws_manager.send_model_used(
            project_id=project_id,
            stage='structure',
            model=selected_plan_model,
            extra={"step": "chapter_plan", "chapter_number": next_chapter_number}
        )

        # 🆕 构建章节规划提示词（使用模块化系统）
        plan_system_prompt = ChapterPlanningPrompts.get_system_prompt(plan_project_genre)

        plan_user_prompt = f"""请为第{next_chapter_number}章制定创作计划。

【整本书信息 - 智能优化上下文】
- 故事概念：{plan_optimized_context.get('project_concept', concept)}

【优化后的核心上下文】（已通过分层摘要策略压缩，聚焦第{max(1, next_chapter_number - 5)}-{next_chapter_number + 5}章）
{plan_optimized_context.get('plot_outline', plot_outline)}

【已完成章节摘要】
{plan_optimized_context.get('previous_chapters_analysis', previous_chapters_summary) if previous_chapters_summary else '（这是第一章）'}

【前一章结尾】
{plan_optimized_context.get('previous_ending', previous_ending) if previous_ending else '（这是第一章，没有前一章）'}
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
- 爽点和钩子必须具体、可执行
{f"""
【题材专属细化】（以下为通用规划要求的具体落地方式，请结合使用）
{chapter_plan_guide}""" if chapter_plan_guide else ''}"""

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
            "对话开头": ("对话开头", "直接进入冲突或紧张场景，用对话抽出矛盾", ""),
            "动作开头": ("动作开头", "从正在发生的动态事件开始，制造紧迫感", ""),
            "悬念开头": ("悬念开头", "抛出问题或异常现象，引发读者好奇，创造独特的开场", ""),
            "场景开头": ("场景开头", "通过环境氛围描写快速建立情境，融入题材特色", ""),
            "反转开头": ("反转开头", "与上章结尾形成对比或反差，制造意外效果", ""),
        }
        ending_styles = {
            "悬念式": ("悬念式", "关键信息揭露一半，留下悬念让读者想继续阅读", ""),
            "转折式": ("转折式", "意外事件发生，打破读者预期", ""),
            "动作中断式": ("动作中断式", "危机时刻戈然而止，制造紧张感", ""),
            "信息炸弹式": ("信息炸弹式", "揭露惊人真相或身份，制造震撼效果", ""),
            "选择困境式": ("选择困境式", "主角面临艰难拉择，强化情绪张力", ""),
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
            stage='content_creation'
        )
        
        # 🆕 获取优化器选择的模型（不再需要 optimize_for_chapter_generation，因为章节规划已消化上下文）
        selected_content_model = context_optimizer.selected_model
        logger.info(f"   🤖 内容创作使用模型: {selected_content_model}")
        # 🆕 广播步骤2模型
        await ws_manager.send_model_used(
            project_id=project_id,
            stage='content',
            model=selected_content_model,
            extra={"step": "chapter_content", "chapter_number": next_chapter_number}
        )

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
                    # 🆕 使用智能截断替代手动截断
                    from app.services.agents.intelligent_truncator import smart_truncate_for_context
                    rag_character_context = "\n".join([
                        f"- {d.metadata.get('name','未知角色')}: {smart_truncate_for_context(d.page_content, max_tokens=200, content_type='rag_doc', preserve_ratio=0.9)}"
                        for d in char_docs
                    ])
                if world_docs:
                    from app.services.agents.intelligent_truncator import smart_truncate_for_context
                    rag_world_context = "\n".join([
                        f"- {d.metadata.get('title','设定')}: {smart_truncate_for_context(d.page_content, max_tokens=250, content_type='rag_doc', preserve_ratio=0.9)}"
                        for d in world_docs
                    ])
                logger.info(f"   📚 RAG注入：人物{len(char_docs)}条，设定{len(world_docs)}条")
        except Exception as rag_e:
            logger.warning(f"   ⚠️ Typed-RAG 注入失败: {rag_e}")
            rag_character_context = ""
            rag_world_context = ""

        # 🆕 构建内容创作提示词（精简版 - 章节规划已消化大部分上下文）
        from app.services.agents.chapter_prompt_builder import ChapterPromptBuilder
        
        # 获取项目题材
        project_genre = ""
        try:
            genre_query = text("SELECT genre FROM projects WHERE id = :project_id")
            genre_result = db.execute(genre_query, {"project_id": project_id}).fetchone()
            if genre_result:
                project_genre = genre_result[0] or ""
        except Exception as e:
            logger.warning(f"   ⚠️ 获取项目题材失败: {e}")
        
        builder = ChapterPromptBuilder(genre=project_genre)
        content_system_prompt = builder.build_system_prompt()
        content_user_prompt = builder.build_user_prompt(
            next_chapter_number=next_chapter_number,
            chapter_plan=chapter_plan,
            previous_ending=previous_ending or "",
            rag_character_context=rag_character_context,
            rag_world_context=rag_world_context,
            selected_opening=selected_opening,
            selected_ending=selected_ending,
        )
        
        # 📊 输出精简版 prompt 统计
        logger.info(f"   📉 Prompt优化（精简版）：")
        logger.info(f"      - 章节规划: {len(chapter_plan)} 字")
        logger.info(f"      - 前一章结尾: {len(previous_ending or '')} 字")
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

         # 🆕 获取项目题材（用于题材自适应评审）
        review_project_genre = ""
        try:
            review_genre_query = text("SELECT genre FROM projects WHERE id = :project_id")
            review_genre_result = db.execute(review_genre_query, {"project_id": project_id}).fetchone()
            if review_genre_result:
                review_project_genre = review_genre_result[0] or ""
            logger.info(f"   🎯 评审使用题材: {review_project_genre or '通用'}")
        except Exception as e:
            logger.warning(f"   ⚠️ 获取项目题材失败: {e}")
        
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
            genre=review_project_genre
        )

        # 🆕 使用真流式 LLM 调用（R1 逻辑检查）
        try:
            review_report = await streaming_service.generate_chapter_streaming(
                prompt=review_user_prompt,
                system_prompt=review_system_prompt,
                on_chunk=on_review_chunk,
                temperature=0.7,
                model="deepseek-reasoner",  # 🔥 步骤3：质量评审使用R1做逻辑检查
            )
            logger.info(f"   ✓ 评审完成（真流式 + R1模型），报告长度: {len(review_report)}")
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

        # 🆕 使用迭代优化（max改稿 + R1打分循环,达到阈值后再输出）
        try:
            # 🎯 根据实际输入长度动态选择改稿模型
            def estimate_tokens(text: str) -> int:
                """估算文本的 token 数（中文按1.3倍字符数估算）"""
                return int(len(text) * 1.3)
            
            def select_model_by_length(chapter_content: str, reviews: str) -> str:
                """根据输入长度智能选择模型
                
                Args:
                    chapter_content: 当前章节内容
                    reviews: 累积的评审意见
                
                Returns:
                    选择的模型名称
                """
                # 估算总输入长度（章节 + 评审 + 系统提示词 + 用户提示词模板）
                chapter_tokens = estimate_tokens(chapter_content)
                reviews_tokens = estimate_tokens(reviews)
                prompt_overhead = 500  # 系统提示词和用户提示词模板的开销
                
                total_tokens = chapter_tokens + reviews_tokens + prompt_overhead
                
                # qwen-max 限制：30720 tokens
                # 保留 30% 安全余量：21504 tokens
                max_safe_limit = 21504
                
                if total_tokens < max_safe_limit:
                    return "qwen-max"
                else:
                    return "qwen-long"
            
            # 初始评审意见
            initial_reviews = review_report or ""
            
            # 选择初始模型
            selected_revision_model = select_model_by_length(chapter_draft, initial_reviews)
            logger.info(f"   🤖 迭代优化改稿模型: {selected_revision_model}")
            logger.info(f"      - 章节长度: {len(chapter_draft)} 字 ≈ {estimate_tokens(chapter_draft)} tokens")
            logger.info(f"      - 初始评审: {len(initial_reviews)} 字 ≈ {estimate_tokens(initial_reviews)} tokens")
            logger.info(f"      - 预估总计: ≈ {estimate_tokens(chapter_draft) + estimate_tokens(initial_reviews) + 500} tokens")
            
            # 🆕 广播步骤4改稿模型（首轮改稿前广播一次）
            await ws_manager.send_model_used(
                project_id=project_id,
                stage='iteration',
                model=selected_revision_model,
                extra={"step": "iteration_revision", "chapter_number": next_chapter_number}
            )

            # 配置：通过分值与最大轮次
            try:
                from app.core.config import settings
                pass_score_threshold = getattr(settings, 'ITERATION_PASS_SCORE', 9.0)
                max_rounds = getattr(settings, 'ITERATION_MAX_ROUNDS', 2)
            except Exception:
                pass_score_threshold = 8.5
                max_rounds = 2
            logger.info(f"   🎯 迭代优化目标分值: {pass_score_threshold} | 最大轮次: {max_rounds}")

            # 辅助：解析评审报告中的综合评分
            import re
            def extract_score(text: str) -> float:
                if not text:
                    return 0.0
                m = re.search(r"综合评分\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10", text)
                try:
                    return float(m.group(1)) if m else 0.0
                except Exception:
                    return 0.0

            # 初始版本与评审
            current_version = chapter_draft
            current_review = review_report
            final_version = current_version
            reached_pass = False
            best_version = current_version
            # 初始化最佳分数为已有评审的分数（若无法提取则为0）
            best_score = extract_score(current_review)
            # 🆕 累积所有轮次的评审意见，作为改稿参考
            all_reviews = [f"【第0轮评审（初稿）】\n{current_review}"]

            # 不透出中间稿的流式回调（前端只看最终稿）
            async def noop_chunk(chunk: str, idx: int):
                return

            for round_idx in range(1, max_rounds + 1):
                logger.info(f"   🔄 迭代优化第{round_idx}/{max_rounds}轮：开始改稿")
                # 🆕 推送迭代轮次信息到前端
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=min(95, 70 + round_idx * 5),
                    message=f"正在迭代第{round_idx}/{max_rounds}轮..."
                )
                # 第N轮：根据所有历史评审意见进行改稿
                # 🆕 将所有评审意见汇总，按轮次展示
                all_reviews_text = "\n\n".join(all_reviews)
                
                # 🎯 每轮动态选择模型（因为评审意见在累积）
                current_model = select_model_by_length(current_version, all_reviews_text)
                if current_model != selected_revision_model:
                    selected_revision_model = current_model
                    logger.info(f"   🔄 第{round_idx}轮模型切换: {selected_revision_model}")
                    logger.info(f"      - 当前章节: {len(current_version)} 字 ≈ {estimate_tokens(current_version)} tokens")
                    logger.info(f"      - 累积评审: {len(all_reviews_text)} 字 ≈ {estimate_tokens(all_reviews_text)} tokens")
                    logger.info(f"      - 预估总计: ≈ {estimate_tokens(current_version) + estimate_tokens(all_reviews_text) + 500} tokens")
                    # 广播模型切换
                    await ws_manager.send_model_used(
                        project_id=project_id,
                        stage='iteration',
                        model=selected_revision_model,
                        extra={"step": f"iteration_round_{round_idx}", "reason": "context_length_increase"}
                    )
                iteration_user_prompt_round = f"""【重要提示】请严格按照以下所有评审意见逐条修改第{next_chapter_number}章内容，不要遗漏或忽略任何一条建议。

【当前章节内容】
{current_version}

【必须执行的所有评审意见（包含历史轮次）】
{all_reviews_text}

【修改要求】
1. 必须逐条落实上述所有评审意见中的修改建议（包括历史轮次的意见）
2. 保持原章节的完整情节和篇幅（不少于原稿80%字数）
3. 直接输出优化后的完整章节内容（第一行为章节标题）
4. 不要附加任何修改说明、优化要点等额外内容

请立即输出优化后的章节："""

                # 仅在最后一轮向前端流式输出正文；前几轮不推送正文
                on_chunk_cb = on_iteration_chunk if round_idx == max_rounds else noop_chunk
                revised_version = await streaming_service.generate_chapter_streaming(
                    prompt=iteration_user_prompt_round,
                    system_prompt=iteration_system_prompt,
                    on_chunk=on_chunk_cb,
                    temperature=0.7,
                    model=selected_revision_model,
                )
                logger.info(f"   ✓ 第{round_idx}轮改稿完成（{selected_revision_model}），字数: {len(revised_version)}")
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=min(95, 72 + round_idx * 5),
                    message=f"第{round_idx}轮改稿完成，正在评审..."
                )

                # 评审打分（R1）
                review_system_prompt_loop = """你是一位专业的网络小说质量评审官。请使用网文6维度对上面的章节进行评审，并输出：\n1) 综合评分：X/10分\n2) 最重要的3条修改建议。\n请严格包含“综合评分：X/10分”这一行。"""
                review_user_prompt_loop = f"""请评审以下章节：

{revised_version}
"""
                new_review_report = await streaming_service.generate_chapter_streaming(
                    prompt=review_user_prompt_loop,
                    system_prompt=review_system_prompt_loop,
                    on_chunk=noop_chunk,  # 评分不流式推送正文
                    temperature=0.3,
                    model="deepseek-reasoner",
                )
                score = extract_score(new_review_report)
                logger.info(f"   🧮 第{round_idx}轮评分：{score:.1f}/10")
                await ws_manager.send_task_progress(
                    project_id=project_id,
                    task_id=task_id,
                    progress=min(95, 80 + round_idx * 3),
                    message=f"迭代优化第{round_idx}轮评分：{score:.1f}/10"
                )
                
                # 🆕 将本轮评审意见加入历史记录
                all_reviews.append(f"【第{round_idx}轮评审】\n{new_review_report}")

                # 🆕 记录最高评分版本
                if score > best_score:
                    best_score = score
                    best_version = revised_version

                # 判定是否达标
                if score >= pass_score_threshold:
                    final_version = revised_version
                    current_review = new_review_report
                    reached_pass = True
                    logger.info(f"   🎉 达到目标分值 {pass_score_threshold}，停止迭代")
                    break
                else:
                    # 继续下一轮
                    current_version = revised_version
                    current_review = new_review_report
                    final_version = revised_version

            if not reached_pass:
                logger.info(f"   ⚠️ 未达标，输出最高评分版本：{best_score:.1f}/10")
                final_version = best_version
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
            "completed_at": datetime.now().isoformat(),
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


@router.get("/epic-framework-state/{project_id}")
async def get_epic_framework_state(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🔍 检测史诗框架状态
    
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
        logger.info(f"🔍 检测史诗框架状态，项目ID: {project_id}")
        
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
        query = text("""
            SELECT epic_framework, epic_framework_generated_at, plot_outline
            FROM project_settings
            WHERE project_id = :project_id
        """)
        result = db.execute(query, {"project_id": project_id}).fetchone()
        
        if not result:
            logger.info(f"   ✅ 未找到项目设置，返回空状态")
            return {
                "has_framework": False,
                "total_volumes": 0,
                "expanded_volumes": [],
                "framework_generated_at": None
            }
        
        epic_framework = result[0]
        framework_generated_at = result[1]
        plot_outline = result[2] or ""
        
        # 🔑 关键修复：使用 epic_framework 来检测状态，而不是 plot_outline
        # 如果 epic_framework 为空，退耋检查 plot_outline
        content_to_check = epic_framework if epic_framework else plot_outline
        
        if not content_to_check:
            logger.info(f"   ✅ 未找到框架内容，返回空状态")
            return {
                "has_framework": False,
                "total_volumes": 0,
                "expanded_volumes": [],
                "framework_generated_at": None
            }
        
        # 使用状态检测函数
        state = detect_framework_state(content_to_check)
        
        logger.info(f"   ✅ 框架状态: {state}")
        
        return {
            "has_framework": state["hasFramework"],
            "total_volumes": state["totalVolumes"],
            "expanded_volumes": state["expandedVolumes"],
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


@router.post("/expand-outline")
async def expand_outline(
    request: ExpandOutlineRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    扩展情节大纲（异步后台执行）
    
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
        "task_id": "xxx-xxx-xxx",
        "message": "大纲扩展任务已启动，正在后台执行..."
    }
    """
    import logging
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"📖 开始扩展大纲，项目ID: {request.project_id}")
        
        # 1. 严格校验目标章节数
        target_count = request.target_total_chapters or 100
        if target_count < 10 or target_count > 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"目标章节数必须在 10-200 之间，当前输入: {target_count}"
            )
        
        # 2. 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == request.project_id) & (Project.user_id == current_user.id)
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        
        # 3. 生成任务ID
        task_id = f"expand-outline-{uuid.uuid4()}"
        logger.info(f"   ✅ 任务ID: {task_id}")
        
        # 4. 🆕 启动后台任务
        asyncio.create_task(
            execute_expand_outline_task(
                task_id=task_id,
                project_id=request.project_id,
                user_id=current_user.id,
                current_outline=request.current_outline,
                world_setting=request.world_setting,
                characters=request.characters,
                current_chapter_count=request.current_chapter_count,
                increment=request.increment,
                target_total_chapters=target_count,  # 使用严格校验后的目标数
                # 🔥 多模式参数
                expansion_mode=request.expansion_mode,
                target_volumes=request.target_volumes,
                chapters_per_volume_min=request.chapters_per_volume_min,
                chapters_per_volume_max=request.chapters_per_volume_max,
                incremental_step=request.incremental_step,
                # 🌟 史诗框架参数
                total_volumes=request.total_volumes,
                total_chapters_min=request.total_chapters_min,
                total_chapters_max=request.total_chapters_max,
                auto_expand_all_volumes=request.auto_expand_all_volumes,
                # 📖 单卷详细参数
                framework_content=request.framework_content,
                target_volume_index=request.target_volume_index,
                volume_chapters_min=request.volume_chapters_min,
                volume_chapters_max=request.volume_chapters_max,
            )
        )
        
        logger.info(f"   🚀 后台任务已启动，目标章节数: {target_count}")
        
        # 5. 立即返回
        return {
            "success": True,
            "task_id": task_id,
            "message": f"📖 大纲扩展任务已启动，将扩展至 {target_count} 章..."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 启动扩展大纲任务失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


async def execute_expand_outline_task(
    task_id: str,
    project_id: int,
    user_id: int,
    current_outline: str,
    world_setting: str,
    characters: str,
    current_chapter_count: int,
    increment: int,
    target_total_chapters: Optional[int],
    # 🔥 多模式参数
    expansion_mode: str = "total",
    target_volumes: Optional[int] = None,
    chapters_per_volume_min: Optional[int] = 20,
    chapters_per_volume_max: Optional[int] = 30,
    incremental_step: Optional[int] = 10,
    # 🌟 史诗框架参数
    total_volumes: Optional[int] = None,
    total_chapters_min: Optional[int] = None,
    total_chapters_max: Optional[int] = None,
    auto_expand_all_volumes: bool = False,
    # 📖 单卷详细参数
    framework_content: Optional[str] = None,
    target_volume_index: Optional[int] = None,
    volume_chapters_min: Optional[int] = None,
    volume_chapters_max: Optional[int] = None,
):
    """后台执行大纲扩展任务（严格遵守目标数）"""
    from sqlalchemy import text
    from app.db.base import SessionLocal
    
    logger = logging.getLogger("uvicorn.error")
    logger.info(f"🚀 开始执行后台任务: {task_id}, 扩展大纲")
    
    # 创建独立的数据库会话
    db = SessionLocal()
    
    try:
        # 发送任务开始消息
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=0,
            message="📖 开始扩展大纲..."
        )
        
        # 导入大纲扩展器
        from app.services.agents.outline_expander import create_outline_expander
        logger.info("   ✅ 成功导入 outline_expander")
        
        # 🎯 任务6：获取项目题材和章节数
        from sqlalchemy import text
        project_query = text("""
            SELECT genre, planned_chapters_max
            FROM projects
            WHERE id = :project_id
        """)
        project_result = db.execute(project_query, {"project_id": project_id}).fetchone()
        project_genre = project_result[0] if project_result else ""
        project_planned_chapters = project_result[1] if project_result else 0
        logger.info(f"   🎯 项目题材：{project_genre}，规划章节：{project_planned_chapters}")
        
        # 创建扩展器实例（🎯 传入题材参数）
        expander = create_outline_expander(
            genre=project_genre,
            planned_chapters_max=project_planned_chapters
        )
        logger.info("   ✅ 扩展器实例已创建（含题材配置）")
        
        # 生成类型化设定摘要并注入世界观
        settings_summary = build_project_settings_summary(project_id, db)
        combined_world_setting = world_setting or ""
        if settings_summary:
            combined_world_setting = (
                f"{combined_world_setting}\n\n{settings_summary}"
                if combined_world_setting
                else settings_summary
            )
        logger.info("   📚 已生成设定摘要并合并到世界观上下文")
        
        # 🌟 根据扩展模式选择不同的执行路径
        if expansion_mode == "epic_framework":
            # ==================== 史诗框架模式 ====================
            logger.info(f"🌟 史诗框架模式: {total_volumes}卷, {total_chapters_min}-{total_chapters_max}章")
            
            await ws_manager.send_task_progress(
                project_id=project_id,
                task_id=task_id,
                progress=20,
                message=f"🎨 正在生成{total_volumes}卷的史诗框架..."
            )
            
            result = await asyncio.to_thread(
                expander.generate_epic_framework,
                world_setting=combined_world_setting,
                characters=characters,
                total_volumes=total_volumes,
                total_chapters_range=(total_chapters_min, total_chapters_max),
            )
            
            logger.info("   ✅ 史诗框架生成完成")
            
            # 🆕 如果需要自动扩全部卷，在框架生成后循环扩展每一卷
            if auto_expand_all_volumes:
                logger.info(f"🔄 自动扩展全部卷模式：开始扩展 {total_volumes} 卷...")
                framework_content_for_volumes = result["expanded_outline"]
                avg_total_chapters = (total_chapters_min + total_chapters_max) // 2
                avg_per_volume = avg_total_chapters // total_volumes
                all_volumes_outline = ""
                
                # ✅ 修复：计算每一卷的实际起始和结束章节号
                accumulated_chapters = 0  # 累计已生成的章节数
                
                for vol_index in range(1, total_volumes + 1):
                    # 计算本卷的章节数
                    volume_chapter_count = avg_per_volume
                    
                    # ✅ 计算实际章节号范围
                    start_chapter = accumulated_chapters + 1
                    end_chapter = accumulated_chapters + volume_chapter_count
                    logger.info(f"📖 正在扩展第 {vol_index}/{total_volumes} 卷...")
                    await ws_manager.send_task_progress(project_id=project_id, task_id=task_id, progress=20 + int((vol_index / total_volumes) * 60), message=f"📖 正在详细扩展第 {vol_index}/{total_volumes} 卷...")
                    vol_result = await asyncio.to_thread(
                        expander.expand_volume_detail, 
                        framework_content=framework_content_for_volumes, 
                        target_volume_index=vol_index, 
                        world_setting=combined_world_setting, 
                        characters=characters, 
                        chapters_range=(start_chapter, end_chapter)  # ✅ 实际章节号（第81-152章）
                    )
                    all_volumes_outline += f"\n\n{'='*70}\n第{vol_index}卷 详细大纲\n{'='*70}\n\n{vol_result['expanded_outline']}"
                    
                    # ✅ 更新累计章节数
                    accumulated_chapters += volume_chapter_count
                    
                    logger.info(f"✅ 第 {vol_index}/{total_volumes} 卷扩展完成（第{start_chapter}-{end_chapter}章）")
                result["expanded_outline"] = f"【史诗框架概览】\n{framework_content_for_volumes}\n\n{'='*70}\n【分卷详细大纲】\n{all_volumes_outline}"
                result["auto_expanded"] = True
                result["total_volume_count"] = total_volumes
                logger.info(f"✅ 自动扩全部卷完成！共 {total_volumes} 卷，{accumulated_chapters} 章")
            
        elif expansion_mode == "volume_detail":
            # ==================== 单卷详细模式 ====================
            logger.info(f"📖 单卷详细模式: 扩展第{target_volume_index}卷, 输入章节数量范围: {volume_chapters_min}-{volume_chapters_max}章")
            
            # 🆕 导入拼接模块（提前导入）
            from app.services.outline_merger import (
                parse_volumes_detail_json,
                build_volumes_detail_json,
                merge_framework_with_volumes
            )
            
            # 🔍 读取原有框架和已有卷细纲，计算章节编号
            original_data_query = text("""
                SELECT epic_framework, epic_volumes_detail 
                FROM project_settings 
                WHERE project_id = :project_id
            """)
            original_result = db.execute(original_data_query, {"project_id": project_id}).fetchone()
            
            if not original_result or not original_result[0]:
                raise ValueError("⚠️  未找到史诗框架！请先生成史诗框架后再扩展单卷")
            
            # 解析已有卷细纲
            stored_volumes_json = original_result[1] or '{}'
            volumes_detail_dict = parse_volumes_detail_json(stored_volumes_json)
            logger.info(f"   📚 已加载 {len(volumes_detail_dict)} 个已有卷细纲")
            
            # ✅ 检测是否覆盖：如果目标卷已存在，记录警告
            if target_volume_index in volumes_detail_dict:
                existing_vol = volumes_detail_dict[target_volume_index]
                logger.warning(
                    f"   ⚠️  第{target_volume_index}卷已存在（第{existing_vol.get('chapters_start', '?')}-{existing_vol.get('chapters_end', '?')}章），将被覆盖！"
                )
            
            # 📊 计算章节编号：基于前面所有卷的累计章节数
            accumulated_chapters = 0
            for vol_num in range(1, target_volume_index):
                if vol_num in volumes_detail_dict:
                    vol_data = volumes_detail_dict[vol_num]
                    vol_chapters = vol_data.get('chapters_end', 0) - vol_data.get('chapters_start', 0) + 1
                    accumulated_chapters += vol_chapters
                    logger.info(f"   📖 第{vol_num}卷: 第{vol_data.get('chapters_start')}-{vol_data.get('chapters_end')}章（{vol_chapters}章）")
            
            # ✅ 计算实际章节编号范围：从累计章节数+1开始
            start_chapter = accumulated_chapters + 1
            
            logger.info(f"   🎯 计算结果：第{target_volume_index}卷将从第{start_chapter}章开始，生成{volume_chapters_min}-{volume_chapters_max}章（AI自由发挥）")
            
            await ws_manager.send_task_progress(
                project_id=project_id,
                task_id=task_id,
                progress=20,
                message=f"📝 正在详细扩展第{target_volume_index}卷（从第{start_chapter}章开始，预计{volume_chapters_min}-{volume_chapters_max}章）..."
            )
            
            result = await asyncio.to_thread(
                expander.expand_volume_detail,
                framework_content=framework_content,
                target_volume_index=target_volume_index,
                world_setting=combined_world_setting,
                characters=characters,
                start_chapter_num=start_chapter,  # ✅ 起始章节号
                chapters_count_range=(volume_chapters_min, volume_chapters_max),  # ✅ 章节数量范围（让AI自由发挥）
            )
            
            logger.info("   ✅ 单卷详细扩展完成")
            
        else:
            # ==================== 原有模式(total/volume/incremental) ====================
            # 🔥 智能识别当前章节数
            if current_chapter_count == 0:
                logger.info("🔍 开始自动识别当前章节数...")
                # 匹配章节标记，如 "第1章"、"第 1 章" 等
                import re
                chapter_pattern = r'第\s*\d+\s*章'
                detected_count = len(re.findall(chapter_pattern, current_outline))
                if detected_count > 0:
                    current_chapter_count = detected_count
                    logger.info(f"🎯 识别成功！当前已有 {current_chapter_count} 章")
                else:
                    logger.info("🆕 未识别到章节，从 0 章开始扩展")
            
            # 🔥 计算实际需要新增的章节数
            increment = target_total_chapters - current_chapter_count
            if increment <= 0:
                raise ValueError(f"目标章节数 ({target_total_chapters}) 必须大于当前章节数 ({current_chapter_count})")
            
            logger.info(f"📊 当前 {current_chapter_count} 章 → 目标 {target_total_chapters} 章 = 需新增 {increment} 章")
            
            # 执行大纲扩展
            await ws_manager.send_task_progress(
                project_id=project_id,
                task_id=task_id,
                progress=20,
                message=f"🔄 正在扩展大纲（从 {current_chapter_count} 章扩展到 {target_total_chapters} 章）..."
            )
            
            # 使用线程池执行同步扩展，避免阻塞事件循环
            result = await asyncio.to_thread(
                expander.expand_plot_outline_incremental,
                current_outline=current_outline,
                world_setting=combined_world_setting,
                characters=characters,
                current_chapter_count=current_chapter_count,
                increment=increment,
                target_total_chapters=target_total_chapters,
            )
            
            logger.info("   ✅ 大纲扩展完成")
        
        # 保存扩展结果到project_settings
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=80,
            message="💾 正在保存扩展结果..."
        )
        
        # 🆕 导入拼接模块
        from app.services.outline_merger import (
            add_volume_anchors,
            merge_framework_with_volumes,
            parse_volumes_detail_json,
            build_volumes_detail_json
        )
        
        # 🌟 处理史诗框架：添加特殊标记
        outline_content = result["expanded_outline"]
        epic_framework = None  # 纯框架内容
        epic_volumes_detail_json = None  # 已扩展卷细纲（JSON格式）
        
        if expansion_mode == "epic_framework":
            # ==================== 史诗框架模式 ====================
            # 🔑 关键：为框架添加锚点标记
            framework_with_anchors = add_volume_anchors(
                result["expanded_outline"],
                total_volumes
            )
            
            # 保存纯框架到 epic_framework 字段
            epic_framework = framework_with_anchors
            
            # 添加 YAML 头部标记到完整大纲
            outline_content = f"""---
类型: 史诗框架
总卷数: {total_volumes}
总章节范围: [{total_chapters_min}, {total_chapters_max}]
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
---

{framework_with_anchors}"""
            logger.info(f"   🌟 史诗框架已添加元数据标记和锚点")
            
            # 🆕 如果自动扩展全部卷，需要保存卷细纲到 epic_volumes_detail
            if auto_expand_all_volumes:
                volumes_detail_dict = {}
                accumulated_chapters = 0
                avg_total_chapters = (total_chapters_min + total_chapters_max) // 2
                avg_per_volume = avg_total_chapters // total_volumes
                
                # 从结果中提取每一卷的细纲（需要AI返回结构化数据）
                # 暂时使用简单存储方式
                for vol_index in range(1, total_volumes + 1):
                    start_chapter = accumulated_chapters + 1
                    end_chapter = accumulated_chapters + avg_per_volume
                    
                    volumes_detail_dict[vol_index] = {
                        "chapters_start": start_chapter,
                        "chapters_end": end_chapter,
                        "outline": f"第{vol_index}卷细纲（自动生成）",  # 简化存储
                        "generated_at": datetime.now().isoformat()
                    }
                    
                    accumulated_chapters += avg_per_volume
                
                epic_volumes_detail_json = build_volumes_detail_json(volumes_detail_dict)
                logger.info(f"   📦 已保存 {len(volumes_detail_dict)} 个卷的细纲到JSON")
        
        elif expansion_mode == "volume_detail":
            # 📖 单卷详细模式：合并到原有框架
            logger.info(f"   🔄 单卷详细模式：将第{target_volume_index}卷合并到原有框架")
            
            # ✅ 复用前面读取的数据，避免重复查询
            stored_framework = original_result[0]  # 已在上面读取
            # volumes_detail_dict 已在上面解析
            
            # 🔍 解析AI实际生成的章节数
            import re
            chapter_pattern = r'第\s*(\d+)\s*章'
            chapter_matches = re.findall(chapter_pattern, result["expanded_outline"])
            if chapter_matches:
                actual_start = int(chapter_matches[0])
                actual_end = int(chapter_matches[-1])
                logger.info(f"   📊 AI实际生成：第{actual_start}-{actual_end}章（共{actual_end - actual_start + 1}章）")
            else:
                # 如果解析失败，使用预估值
                actual_start = start_chapter
                actual_end = start_chapter + volume_chapters_min - 1
                logger.warning(f"   ⚠️  未能解析实际章节数，使用预估值：第{actual_start}-{actual_end}章")
            
            # 更新/添加当前卷的细纲
            volumes_detail_dict[target_volume_index] = {
                "chapters_start": actual_start,  # ✅ 使用AI实际生成的起始章节号
                "chapters_end": actual_end,      # ✅ 使用AI实际生成的结束章节号
                "outline": result["expanded_outline"],
                "generated_at": datetime.now().isoformat()
            }
            logger.info(f"   ✅ 已更新第{target_volume_index}卷细纲（第{actual_start}-{actual_end}章）")
            
            # 🌟 智能拼接：框架 + 所有已扩展卷
            # 提取纯细纲内容（不含章节范围元数据）
            volumes_outline_only = {
                vol_num: vol_data["outline"] 
                for vol_num, vol_data in volumes_detail_dict.items()
            }
            
            merged_outline = merge_framework_with_volumes(
                stored_framework,
                volumes_outline_only
            )
            
            outline_content = merged_outline
            
            # 保存纯框架和更新后的JSON
            epic_framework = stored_framework  # 框架保持不变
            epic_volumes_detail_json = build_volumes_detail_json(volumes_detail_dict)
            
            logger.info(f"   🎯 智能拼接完成：框架 + {len(volumes_detail_dict)} 个卷细纲")
        
        # 🆕 根据模式选择更新策略
        if expansion_mode in ["epic_framework", "volume_detail"]:
            # 史诗框架模式：同时更新 epic_framework 和 epic_volumes_detail
            update_query = text("""
                UPDATE project_settings
                SET plot_outline = :plot_outline,
                    epic_framework = :epic_framework,
                    epic_volumes_detail = :epic_volumes_detail,
                    epic_framework_generated_at = :generated_at,
                    updated_at = :updated_at
                WHERE project_id = :project_id
            """)
            
            db.execute(update_query, {
                "plot_outline": outline_content,
                "epic_framework": epic_framework,
                "epic_volumes_detail": epic_volumes_detail_json,
                "generated_at": datetime.now().isoformat() if epic_framework else None,
                "updated_at": datetime.now().isoformat(),
                "project_id": project_id
            })
            logger.info("   💾 史诗框架模式：已分离保存框架和卷细纲")
        else:
            # 原有模式：只更新 plot_outline
            update_query = text("""
                UPDATE project_settings
                SET plot_outline = :plot_outline,
                    updated_at = :updated_at
                WHERE project_id = :project_id
            """)
            
            db.execute(update_query, {
                "plot_outline": outline_content,
                "updated_at": datetime.now().isoformat(),
                "project_id": project_id
            })
        db.commit()
        logger.info("   💾 扩展大纲已保存到数据库")
        
        # 🆕 同步扩展大纲到向量库
        try:
            from app.services.vector_sync import sync_to_vector_db
            
            await ws_manager.send_task_progress(
                project_id=project_id,
                task_id=task_id,
                progress=90,
                message="🔄 正在同步到向量库..."
            )
            
            if result["expanded_outline"] and isinstance(result["expanded_outline"], str) and result["expanded_outline"].strip():
                sync_to_vector_db(
                    kb_type="plot",
                    name="情节大纲",
                    content=result["expanded_outline"],
                    metadata={
                        "project_id": str(project_id),
                        "title": "情节大纲",
                        "type": "plot_outline"
                    }
                )
                logger.info("   ✅ 已同步扩展大纲到向量库")
        except Exception as vector_error:
            logger.warning(f"   ⚠️  同步扩展大纲到向量库失败: {vector_error}")
            import traceback
            traceback.print_exc()
        
        # 发送完成消息
        if expansion_mode == "epic_framework":
            # 🌟 史诗框架模式:不显示章节数
            await ws_manager.send_task_complete(
                project_id=project_id,
                task_id=task_id,
                result={
                    "expanded_outline": result["expanded_outline"],
                    "total_volumes": result.get("total_volumes", total_volumes),
                    "estimated_chapters": result.get("estimated_chapters", 0),
                    "framework_type": "epic",
                    "message": f"✅ 史诗框架生成完成！{result.get('total_volumes', total_volumes)}卷，预计{result.get('estimated_chapters', 0)}章"
                }
            )
        elif expansion_mode == "volume_detail":
            # 📖 单卷详细模式:显示单卷信息
            await ws_manager.send_task_complete(
                project_id=project_id,
                task_id=task_id,
                result={
                    "expanded_outline": result["expanded_outline"],
                    "volume_index": result.get("volume_index", target_volume_index),
                    "chapter_count": result.get("chapter_count", 0),
                    "message": f"✅ 第{result.get('volume_index', target_volume_index)}卷详细大纲生成完成！约{result.get('chapter_count', 0)}章"
                }
            )
        else:
            # 原有模式(total/volume/incremental):显示章节数
            final_count = result.get("current_chapter_count", target_total_chapters)
            ai_suggestion = {
                "should_continue": result.get("should_continue", False),
                "reason": result.get("continue_reason", "")
            }
            
            await ws_manager.send_task_complete(
                project_id=project_id,
                task_id=task_id,
                result={
                    "expanded_outline": result["expanded_outline"],
                    "current_chapter_count": final_count,
                    "target_chapter_count": target_total_chapters,
                    "ai_suggestion": ai_suggestion,
                    "message": f"✅ 大纲扩展完成！当前 {final_count} 章（目标: {target_total_chapters}）"
                }
            )
        
    except Exception as e:
        logger.error(f"❌ 后台扩展大纲失败: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # 发送错误消息
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e)
        )
    finally:
        db.close()


@router.post("/expand-characters")
async def expand_characters(
    request: ExpandCharactersRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    扩展人物体系（异步后台执行）
    
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
        "task_id": "xxx-xxx-xxx",
        "message": "人物扩展任务已启动，正在后台执行..."
    }
    """
    import logging
    
    logger = logging.getLogger("uvicorn.error")
    
    try:
        logger.info(f"👥 开始扩展人物，项目ID: {request.project_id}")
        
        # 1. 严格校验目标人物数
        target_count = request.target_total_characters or 25
        if target_count < 5 or target_count > 50:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"目标人物数必须在 5-50 之间，当前输入: {target_count}"
            )
        
        # 2. 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == request.project_id) & (Project.user_id == current_user.id)
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        
        # 3. 生成任务ID
        task_id = f"expand-characters-{uuid.uuid4()}"
        logger.info(f"   ✅ 任务ID: {task_id}")
        
        # 4. 🆕 启动后台任务
        asyncio.create_task(
            execute_expand_characters_task(
                task_id=task_id,
                project_id=request.project_id,
                user_id=current_user.id,
                main_characters=request.main_characters,
                world_setting=request.world_setting,
                plot_outline=request.plot_outline,
                current_character_count=request.current_character_count,
                target_total_characters=target_count,  # 使用严格校验后的目标数
            )
        )
        
        logger.info(f"   🚀 后台任务已启动，目标人物数: {target_count}")
        
        # 5. 立即返回
        return {
            "success": True,
            "task_id": task_id,
            "message": f"👥 人物扩展任务已启动，将扩展至 {target_count} 个人物..."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 启动扩展人物任务失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


async def execute_expand_characters_task(
    task_id: str,
    project_id: int,
    user_id: int,
    main_characters: str,
    world_setting: str,
    plot_outline: str,
    current_character_count: int,
    target_total_characters: int,
):
    """后台执行人物扩展任务（严格遵守目标数）"""
    from sqlalchemy import text
    from app.db.base import SessionLocal
    
    logger = logging.getLogger("uvicorn.error")
    logger.info(f"🚀 开始执行后台任务: {task_id}, 扩展人物")
    
    # 创建独立的数据库会话
    db = SessionLocal()
    
    try:
        # 发送任务开始消息
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=0,
            message="👥 开始扩展人物..."
        )
        
        # 导入扩展器
        from app.services.agents.outline_expander import create_outline_expander
        logger.info("   ✅ 成功导入 outline_expander")
        
        # 创建扩展器实例
        expander = create_outline_expander()
        logger.info("   ✅ 扩展器实例已创建")
        
        # 生成类型化设定摘要并注入世界观
        settings_summary = build_project_settings_summary(project_id, db)
        combined_world_setting = world_setting or ""
        if settings_summary:
            combined_world_setting = (
                f"{combined_world_setting}\n\n{settings_summary}"
                if combined_world_setting
                else settings_summary
            )
        logger.info("   📚 已生成设定摘要并合并到世界观上下文")
        
        # 🔥 智能识别当前人物数
        if current_character_count == 0:
            logger.info("🔍 开始自动识别当前人物数...")
            # 简单计数：匹配「姓名】关键字
            import re
            name_pattern = r'【姓名】：'
            detected_count = len(re.findall(name_pattern, main_characters))
            if detected_count > 0:
                current_character_count = detected_count
                logger.info(f"🎯 识别成功！当前已有 {current_character_count} 个人物")
            else:
                logger.info("🆕 未识别到人物，从 0 个开始扩展")
        
        # 🔥 计算实际需要新增的人物数
        increment = target_total_characters - current_character_count
        if increment <= 0:
            raise ValueError(f"目标人物数 ({target_total_characters}) 必须大于当前人物数 ({current_character_count})")
        
        logger.info(f"📊 当前 {current_character_count} 个人物 → 目标 {target_total_characters} 个人物 = 需新增 {increment} 个")
        
        # 执行人物扩展
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=20,
            message=f"🔄 正在扩展人物（从 {current_character_count} 个扩展到 {target_total_characters} 个）..."
        )
        
        # 使用线程池执行同步扩展，避免阻塞事件循环
        result = await asyncio.to_thread(
            expander.expand_characters_incremental,
            main_characters=main_characters,
            world_setting=combined_world_setting,
            plot_outline=plot_outline,
            current_character_count=current_character_count,
            increment=increment,
            target_total_characters=target_total_characters,
        )
        
        logger.info(f"   ✅ 人物扩展完成，当前总数: {result.get('current_character_count', target_total_characters)}")
        
        # 保存扩展结果到project_settings
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=70,
            message="💾 正在保存扩展结果..."
        )
        
        update_query = text("""
            UPDATE project_settings
            SET characters = :characters,
                updated_at = :updated_at
            WHERE project_id = :project_id
        """)
        
        db.execute(update_query, {
            "characters": result["all_characters"],
            "updated_at": datetime.now().isoformat(),
            "project_id": project_id
        })
        db.commit()
        logger.info("   💾 扩展人物已保存到数据库")
        
        # 自动解析人物卡并同步到结构化characters表
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
                characters_text=result["all_characters"],
                db_session=db
            )
            logger.info(f"   🔄 人物卡同步完成: 解析 {sync_result['parsed']} 个, "
                       f"创建 {sync_result['created']} 个, 更新 {sync_result['updated']} 个")
            
            # 🆕 同步扩展人物到向量库
            await ws_manager.send_task_progress(
                project_id=project_id,
                task_id=task_id,
                progress=90,
                message="🔄 正在同步到向量库..."
            )
            
            try:
                from app.services.vector_sync import upsert_character_to_vector_db
                from app.models.character import Character
                
                logger.info(f"   🔄 开始同步扩展人物到向量库...")
                
                # 查询所有人物(包括新增的)
                characters_in_db = db.query(Character).filter(
                    Character.project_id == project_id
                ).all()
                
                if characters_in_db:
                    for char in characters_in_db:
                        # 使用Character模型的实际字段: name, role, faction, summary, profile等
                        char_content = f"""
人物名称: {char.name}
角色类型: {char.role or '未设定'}
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
                                "role": char.role or ''
                            }
                        )
                    
                    logger.info(f"   ✅ 已同步 {len(characters_in_db)} 个人物到向量库")
            except Exception as vector_error:
                logger.warning(f"   ⚠️  同步人物到向量库失败: {vector_error}")
                import traceback
                traceback.print_exc()
            
            # 🆕 解析人物关系文本并写入Character.relations
            if result.get("character_relationships"):
                from app.services.character_parser import parse_and_sync_relationships
                
                rel_result = parse_and_sync_relationships(
                    project_id=project_id,
                    relationships_text=result["character_relationships"],
                    db_session=db
                )
                logger.info(f"   🔗 人物关系同步完成: 解析 {rel_result['parsed']} 条, "
                           f"保存 {rel_result['saved']} 条, 更新 {rel_result['characters_updated']} 个人物")
                sync_result["relationships"] = rel_result
        except Exception as e:
            logger.warning(f"   ⚠️  自动同步人物卡失败: {e}")
            import traceback
            traceback.print_exc()
        
        # 发送完成消息
        final_count = result.get("current_character_count", target_total_characters)
        ai_suggestion = {
            "should_continue": result.get("should_continue", False),
            "reason": result.get("continue_reason", "")
        }
        
        await ws_manager.send_task_complete(
            project_id=project_id,
            task_id=task_id,
            result={
                "all_characters": result["all_characters"],
                "current_character_count": final_count,
                "target_character_count": target_total_characters,
                "ai_suggestion": ai_suggestion,  # AI建议，仅供参考
                "character_sync": sync_result,
                "message": f"✅ 人物扩展完成！当前 {final_count} 个人物（目标: {target_total_characters}）"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ 后台扩展人物失败: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # 发送错误消息
        await ws_manager.send_task_error(
            project_id=project_id,
            task_id=task_id,
            error=str(e)
        )
    finally:
        db.close()


@router.get("/epic-framework/{project_id}")
async def get_epic_framework(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取项目的史诗框架
    
    返回:
    {
        "has_framework": true,
        "framework_content": "史诗框架内容...",
        "metadata": {
            "total_volumes": 30,
            "total_chapters_range": [1000, 2500],
            "generated_at": "2025-12-08T..."
        }
    }
    """
    import re
    from sqlalchemy import text
    
    try:
        # 验证项目所有权
        project = db.query(Project).filter(
            (Project.id == project_id) & (Project.user_id == current_user.id)
        ).first()
        
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found"
            )
        
        # 获取 plot_outline
        query = text("""
            SELECT plot_outline
            FROM project_settings
            WHERE project_id = :project_id
        """)
        
        result = db.execute(query, {"project_id": project_id}).fetchone()
        
        if not result or not result[0]:
            return {
                "has_framework": False,
                "framework_content": "",
                "metadata": None
            }
        
        plot_outline = result[0]
        
        # 检查是否是史诗框架（查找 YAML 头部，兼容中英文字段）
        # 中文字段格式
        yaml_pattern_cn = r'^---\s*\n类型:\s*史诗框架\s*\n总卷数:\s*(\d+)\s*\n总章节范围:\s*\[(\d+),\s*(\d+)\]\s*\n生成时间:\s*([^\n]+)\s*\n---\s*\n'
        # 英文字段格式（兼容旧数据）
        yaml_pattern_en = r'^---\s*\ntype:\s*epic_framework\s*\ntotal_volumes:\s*(\d+)\s*\ntotal_chapters_range:\s*\[(\d+),\s*(\d+)\]\s*\ngenerated_at:\s*([^\n]+)\s*\n---\s*\n'
        
        match = re.match(yaml_pattern_cn, plot_outline, re.MULTILINE)
        if not match:
            match = re.match(yaml_pattern_en, plot_outline, re.MULTILINE)
        
        if match:
            # 是史诗框架，提取元数据
            total_volumes = int(match.group(1))
            chapters_min = int(match.group(2))
            chapters_max = int(match.group(3))
            generated_at = match.group(4)
            
            # 移除 YAML 头部，只返回内容
            framework_content = plot_outline[match.end():]
            
            return {
                "has_framework": True,
                "framework_content": framework_content.strip(),
                "metadata": {
                    "total_volumes": total_volumes,
                    "total_chapters_range": [chapters_min, chapters_max],
                    "generated_at": generated_at
                }
            }
        else:
            # 不是史诗框架
            return {
                "has_framework": False,
                "framework_content": "",
                "metadata": None
            }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/optimize-chapter")
async def optimize_chapter(
    request: dict,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    再次优化章节：对当前章节再进行一轮迭代优化
    
    请求体：
    {
        "project_id": 1,
        "chapter_id": 10,
        "current_content": "当前章节内容..."
    }
    
    返回：
    {
        "task_id": "optimize_xxx",
        "message": "优化任务已提交"
    }
    """
    import uuid
    import logging
    
    logger = logging.getLogger(__name__)
    
    project_id = request.get("project_id")
    chapter_id = request.get("chapter_id")
    current_content = request.get("current_content", "")
    user_feedback = request.get("user_feedback", "")  # 🆕 用户额外意见
    
    if not project_id or not chapter_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少 project_id 或 chapter_id"
        )
    
    # 验证项目所有权
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在"
        )
    
    # 验证章节存在
    chapter = db.query(Chapter).filter(
        (Chapter.id == chapter_id) & (Chapter.project_id == project_id)
    ).first()
    
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在"
        )
    
    # 生成任务ID
    task_id = f"optimize_{uuid.uuid4().hex[:8]}"
    
    # 创建任务记录（使用 generation_history 表）
    insert_query = text("""
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :created_at)
    """)
    
    db.execute(insert_query, {
        "project_id": project_id,
        "task_type": "optimize_chapter",
        "task_id": task_id,
        "status": "running",
        "created_at": datetime.now().isoformat()
    })
    db.commit()
    logger.info(f"✅ 任务记录已创建: {task_id}")
    
    # 使用线程异步执行优化（FastAPI的BackgroundTasks不支持async函数）
    import threading
    thread = threading.Thread(
        target=lambda: asyncio.run(
            _optimize_chapter_task(
                task_id=task_id,
                project_id=project_id,
                chapter_id=chapter_id,
                current_content=current_content,
                user_feedback=user_feedback,
            )
        ),
        daemon=True
    )
    thread.start()
    logger.info(f"🚀 [{task_id}] 优化线程已启动")
    
    return {
        "task_id": task_id,
        "message": "优化任务已提交"
    }


async def _optimize_chapter_task(
    task_id: str,
    project_id: int,
    chapter_id: int,
    current_content: str,
    user_feedback: str = "",  # 🆕 用户额外意见
):
    """
    异步执行章节优化任务
    """
    from app.services.agents.agents import QualityReviewerAgent, ContentCreatorAgent
    from app.services.prompts.review_prompts import GenreAdaptiveReviewPrompts
    from sqlalchemy import text
    import logging
    
    logger = logging.getLogger(__name__)
    db = SessionLocal()
    
    try:
        # 更新任务状态：开始优化
        update_query = text("""
            UPDATE generation_history
            SET status = :status, progress = :progress, message = :message, updated_at = :updated_at
            WHERE task_id = :task_id
        """)
        db.execute(update_query, {
            "task_id": task_id,
            "status": "running",
            "progress": 0,
            "message": "🔄 开始优化章节...",
            "updated_at": datetime.now().isoformat()
        })
        db.commit()
        logger.info(f"🔄 [{task_id}] 开始优化章节...")
        
        # 获取项目信息
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise Exception("项目不存在")
        
        # 获取章节信息
        chapter = db.query(Chapter).filter(
            (Chapter.id == chapter_id) & (Chapter.project_id == project_id)
        ).first()
        if not chapter:
            raise Exception("章节不存在")
        
        # 获取章节计划（可选）
        chapter_plan = ""
        try:
            query = text("""
                SELECT chapter_plan
                FROM chapter_plans
                WHERE project_id = :project_id AND chapter_number = :chapter_number
                ORDER BY id DESC
                LIMIT 1
            """)
            plan_result = db.execute(query, {
                "project_id": project_id,
                "chapter_number": chapter.chapter_number
            }).fetchone()
            
            chapter_plan = plan_result[0] if plan_result else ""
        except Exception as e:
            logger.warning(f"获取章节计划失败: {e}，将继续执行")
        
        # 获取项目题材
        genre = ""
        try:
            genre_query = text("SELECT genre FROM projects WHERE id = :project_id")
            genre_result = db.execute(genre_query, {"project_id": project_id}).fetchone()
            if genre_result:
                genre = genre_result[0] or ""
        except Exception as e:
            logger.warning(f"获取项目题材失败: {e}")
        
        # 📝 步骤1：质量评审
        update_query = text("""
            UPDATE generation_history
            SET progress = :progress, message = :message, updated_at = :updated_at
            WHERE task_id = :task_id
        """)
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 20,
            "message": "📝 正在评审章节质量...",
            "updated_at": datetime.now().isoformat()
        })
        db.commit()
        logger.info(f"📝 [{task_id}] 开始评审章节质量...")
        
        # 使用QualityReviewerAgent进行评审
        review_agent = QualityReviewerAgent()
        
        # 构造评审提示词
        review_prompt = f"""请对以下章节内容进行详细的质量评审：

【章节信息】
- 章节号：第{chapter.chapter_number}章
- 题材：{genre or '通用'}

【章节计划】
{chapter_plan}

【章节内容】
{current_content}

---

请按照以下维度进行评估，每个维度给出1-10分的评分：
1. 故事性：情节紧凑度、冲突设置、节奏把控
2. 人物塑造：人物立体度、性格一致性、成长弧光
3. 语言表达：语言流畅度、修辞手法、风格独特性、画面感
4. 结构完整性：情节连贯性、逻辑合理性、章节衔接
5. 创新性：设定新颖性、情节原创性、视角独特性

请提供：
1. 每个维度的评分和反馈
2. 主要优点（至少3个）
3. 主要缺点（至少3个）
4. 改进建议（至少5个）
5. 综合评分（加权平均）
"""
        
        review_report = review_agent.process(review_prompt)
        
        # 解析评分
        import re
        score_match = re.search(r'综合评分[:\uff1a]\s*(\d+(?:\.\d+)?)', review_report)
        current_score = float(score_match.group(1)) if score_match else 0.0
        
        logger.info(f"📊 当前章节评分: {current_score}")
        
        # 🔧 步骤2：迭代优化
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 50,
            "message": f"🔧 正在优化章节（当前评分: {current_score}）...",
            "updated_at": datetime.now().isoformat()
        })
        db.commit()
        logger.info(f"🔧 [{task_id}] 开始优化章节...")
        
        # 使用ContentCreatorAgent进行改稿（但需要明确指示修改而非重写）
        content_agent = ContentCreatorAgent()
        
        # 构造改稿提示词（强调修改而非重写）
        user_feedback_section = ""
        if user_feedback and user_feedback.strip():
            user_feedback_section = f"""

【用户额外意见】
{user_feedback.strip()}
"""
        
        revision_prompt = f"""你是一位网络小说修改专家，请根据评审意见**修改**以下章节内容。

⚠️ **重要：你的任务是修改和优化现有内容，而不是重新创作或编写全新的章节。**

修改原则：
1. 保持原有故事线和主要情节不变
2. 保留原文中的精彩描写和对话
3. 根据评审意见针对性地修改问题部分
4. 不要添加新的人物、地点或大型情节

【章节信息】
- 章节号：第{chapter.chapter_number}章
- 题材：{genre or '通用'}

【系统评审意见】
{review_report}{user_feedback_section}

【当前章节内容（需要修改的原文）】
{current_content}

---

请仔细阅读以上原文和评审意见，然后：
1. 找出需要改进的具体位置
2. 在保持整体结构和故事线的基础上，针对性地修改这些问题
3. 直接输出修改后的完整章节内容

注意：不要输出任何解释性文字，直接输出修改后的章节正文。
"""
        
        # 选择模型（根据内容长度）
        def estimate_tokens(text: str) -> int:
            return int(len(text) * 1.3)
        
        total_tokens = estimate_tokens(current_content) + estimate_tokens(review_report) + 500
        max_safe_limit = 21504
        
        model_name = "qwen-max" if total_tokens < max_safe_limit else "qwen-long"
        
        logger.info(f"🤖 使用模型: {model_name} (预计tokens: {total_tokens})")
        
        # 执行改稿（使用较低temperature保持原文结构）
        optimized_content = content_agent.process(
            revision_prompt,
            temperature=0.3  # 使用低temperature保持忠于原文，避免过度创作
        )
        
        if not optimized_content:
            raise Exception("优化结果为空")
        
        # 完成 - 更新进度
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 100,
            "message": "✅ 章节优化完成",
            "updated_at": datetime.now().isoformat()
        })
        db.commit()
        logger.info(f"✅ [{task_id}] 章节优化完成")
        
        # 更新任务状态为完成，并存储结果
        update_query = text("""
            UPDATE generation_history
            SET status = :status,
                result = :result,
                completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        
        import json
        db.execute(update_query, {
            "task_id": task_id,
            "status": "completed",
            "result": json.dumps({
                "optimized_content": optimized_content,
                "original_score": current_score,
                "review_report": review_report,
            }, ensure_ascii=False),
            "completed_at": datetime.now().isoformat()
        })
        db.commit()
        
        logger.info(f"✅ 章节优化任务完成: {task_id}")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"❌ 章节优化任务失败: {e}")
        
        # 更新任务状态为失败
        update_query = text("""
            UPDATE generation_history
            SET status = :status,
                error = :error,
                completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        
        db.execute(update_query, {
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.now().isoformat()
        })
        db.commit()
    finally:
        db.close()
