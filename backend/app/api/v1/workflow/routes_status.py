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
from app.api.v1.workflow.execute_background import (
    _run_execute_stage_background_serialized,
    _run_execute_stage_with_streaming_serialized,
)


def _normalize_generation_history_result_payload(raw_result: Any) -> Any:
    """将 generation_history.result 统一规范为可直接返回给前端的 Python 值。"""
    if raw_result is None:
        return None
    if isinstance(raw_result, (dict, list)):
        return raw_result
    if not isinstance(raw_result, str):
        return raw_result

    result_text = raw_result.strip()
    if not result_text:
        return raw_result

    try:
        return json.loads(result_text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to parse workflow task result payload: %s", exc)
        return raw_result


DEFAULT_TASK_TIMEOUT_MINUTES = 30
EXPAND_STORY_TASK_TIMEOUT_MINUTES = 180
WORKFLOW_STATUS_PROCESS_STARTED_AT = utc_now()

IN_MEMORY_WORKFLOW_TASK_TYPES = {
    "expand_story",
    "optimize_chapter",
    "regenerate_chapter",
    "generate_next_chapter",
    "review",
    "chapter",
}
IN_MEMORY_WORKFLOW_TASK_TYPE_PREFIXES = (
    "workflow_stage_",
)


def _resolve_task_timeout_minutes(task_type: Any) -> int:
    normalized_task_type = str(task_type or "").strip().lower()
    if normalized_task_type == "expand_story":
        return EXPAND_STORY_TASK_TIMEOUT_MINUTES
    return DEFAULT_TASK_TIMEOUT_MINUTES


def _build_task_timeout_error(task_type: Any, timeout_minutes: int) -> str:
    normalized_task_type = str(task_type or "").strip().lower()
    if normalized_task_type == "expand_story":
        return f"协同扩展任务超时（运行超过{timeout_minutes}分钟）"
    return f"任务超时（运行超过{timeout_minutes}分钟）"


def _normalize_task_type(task_type: Any) -> str:
    return str(task_type or "").strip().lower()


def _is_in_memory_workflow_task(task_type: Any) -> bool:
    normalized_task_type = _normalize_task_type(task_type)
    if normalized_task_type in IN_MEMORY_WORKFLOW_TASK_TYPES:
        return True
    return any(
        normalized_task_type.startswith(prefix)
        for prefix in IN_MEMORY_WORKFLOW_TASK_TYPE_PREFIXES
    )


def _can_sync_task_completed_from_stage_state(task_type: Any) -> bool:
    return _normalize_task_type(task_type).startswith("workflow_stage_")


def _build_task_interrupted_error(task_type: Any) -> str:
    normalized_task_type = _normalize_task_type(task_type)
    if normalized_task_type == "expand_story":
        return "协同扩展任务因服务重启或热重载中断，请重新发起"
    if normalized_task_type == "optimize_chapter":
        return "章节优化任务因服务重启或热重载中断，请重新发起"
    if normalized_task_type == "regenerate_chapter":
        return "章节重写任务因服务重启或热重载中断，请重新发起"
    if normalized_task_type == "generate_next_chapter":
        return "生成下一章任务因服务重启或热重载中断，请重新发起"
    if normalized_task_type.startswith("workflow_stage_"):
        return "工作流阶段任务因服务重启或热重载中断，请重新发起"
    return "后台任务因服务重启或热重载中断，请重新发起"


def _build_inactive_generate_next_chapter_error() -> str:
    return "生成下一章任务已不在后端执行队列中，请重新发起"


def _is_inactive_generate_next_chapter_task(task_type: Any, task_id: Any) -> bool:
    if _normalize_task_type(task_type) != "generate_next_chapter":
        return False
    try:
        from app.api.v1.workflow.routes_chapter import is_generate_next_chapter_task_active
    except Exception:
        return False
    return not is_generate_next_chapter_task_active(str(task_id))


def _should_mark_task_as_interrupted(task_type: Any, created_at: datetime) -> bool:
    if not _is_in_memory_workflow_task(task_type):
        return False
    return created_at < WORKFLOW_STATUS_PROCESS_STARTED_AT

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

        status_data = await coordinator.get_workflow_status(project_id)
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

        # 2. 从统一工作流上下文读取内容
        workflow_context_builder = WorkflowContextBuilder(db)
        if not workflow_context_builder.get_stage_field_name(stage):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid stage: {stage}"
            )

        content = workflow_context_builder.read_stage_content(
            project_id,
            stage,
            pretty_json=True,
        )
        # 迭代终稿可能是「复评未达线但已交付」的降级版本，前端需要提示用户
        degraded = False
        best_score = None
        if stage == "iteration":
            review_meta = workflow_context_builder.load_review_meta(project_id) or {}
            iteration_meta = review_meta.get("first_chapter_iteration") or {}
            degraded = bool(iteration_meta.get("degraded", False))
            raw_score = iteration_meta.get("best_score")
            if raw_score is not None:
                best_score = float(raw_score)
        return {
            "content": content,
            "stage": stage,
            "degraded": degraded,
            "best_score": best_score,
        }

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
    from sqlalchemy import text
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

        # 2. 内容阶段可原地更新当前最后一章；评审继续不得改写章节正文。
        deleted_chapter = None
        deleted_chapters_count = 0

        # 内容创作保存：原地更新当前最后一章正文，不得删除章节行。
        # 评审保存并继续：不得改写/删除章节正文（request.content 是评审报告，不是章节）。
        updated_chapter = None
        if stage == 'content':
            logger.info("🔍 检测到内容创作阶段，检查是否需要更新当前章节旧稿...")
            chapters_query = text("""
                SELECT id, chapter_number, title, word_count
                FROM chapters
                WHERE project_id = :project_id
                ORDER BY chapter_number DESC
            """)
            chapters_result = db.execute(chapters_query, {"project_id": project_id}).fetchall()
            chapters = [{"id": r[0], "chapter_number": r[1], "title": r[2], "word_count": r[3]} for r in chapters_result]
            if chapters:
                target = chapters[0]
                logger.info(f"   📊 已有章节数: {len(chapters)}，原地更新第{target['chapter_number']}章")
                db.execute(
                    text("""
                        UPDATE chapters
                        SET content = :content,
                            word_count = :word_count
                        WHERE id = :chapter_id
                    """),
                    {
                        "content": request.content or "",
                        "word_count": len(request.content or ""),
                        "chapter_id": target["id"],
                    },
                )
                db.commit()
                updated_chapter = {
                    "id": target["id"],
                    "chapter_number": target["chapter_number"],
                    "title": target["title"],
                    "word_count": len(request.content or ""),
                }
                logger.info(f"   ✅ 已原地更新第{target['chapter_number']}章，未删除章节行")
            else:
                logger.info("   ✅ 未发现已保存章节，仅写入阶段草稿")

        # 3. 保存内容到 project_settings 表
        workflow_context_builder = WorkflowContextBuilder(db)
        if not workflow_context_builder.get_stage_field_name(stage):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid stage: {stage}"
            )

        workflow_context_builder.write_stage_content(project_id, stage, request.content)

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
                "created_at": utc_now().isoformat()
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
                    streaming_stages = [StageType.CONCEPT, StageType.STRUCTURE, StageType.CONTENT, StageType.REVIEW, StageType.ITERATION]
                    streaming_enabled = next_stage_enum in streaming_stages
                    
                    # 启动后台任务
                    if streaming_enabled:
                        asyncio.create_task(
                            _run_execute_stage_with_streaming_serialized(
                                task_id, project_id, next_stage_enum, current_user.id, db
                            )
                        )
                        logger.info(f"   🌊 流式后台任务已启动: {next_stage_name}")
                    else:
                        asyncio.create_task(
                            _run_execute_stage_background_serialized(
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

        if updated_chapter:
            response["updated_chapter"] = updated_chapter
            # 兼容旧前端：仍返回 deleted_chapter 字段名，但语义已变为原地更新。
            response["deleted_chapter"] = updated_chapter
            response["message"] = f"已更新第{updated_chapter['chapter_number']}章并保存新内容"

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
            SELECT gh.task_id, gh.task_type, gh.status, gh.result, gh.error, gh.created_at, gh.completed_at
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

        task_id_value = result[0]
        task_type_value = result[1]
        status_value = result[2]
        result_value = result[3]
        error_value = result[4]
        created_at_value = result[5]
        completed_at_value = result[6]

        if status_value == "running":
            now = utc_now()
            created_at = parse_datetime_utc(created_at_value, default=now) or now
            task_timeout_minutes = _resolve_task_timeout_minutes(task_type_value)
            task_age_minutes = max(0.0, (now - created_at).total_seconds() / 60)

            if _should_mark_task_as_interrupted(task_type_value, created_at):
                interrupted_error = _build_task_interrupted_error(task_type_value)

                update_query = text("""
                    UPDATE generation_history
                    SET status = 'failed',
                        error = :error,
                        completed_at = :completed_at
                    WHERE task_id = :task_id AND status = 'running'
                """)

                db.execute(update_query, {
                    "task_id": task_id_value,
                    "error": interrupted_error,
                    "completed_at": now.isoformat(),
                })
                db.commit()

                status_value = "failed"
                error_value = interrupted_error
                completed_at_value = now.isoformat()

            elif task_age_minutes > task_timeout_minutes:
                timeout_error = _build_task_timeout_error(task_type_value, task_timeout_minutes)

                update_query = text("""
                    UPDATE generation_history
                    SET status = 'timeout',
                        error = :error,
                        completed_at = :completed_at
                    WHERE task_id = :task_id AND status = 'running'
                """)

                db.execute(update_query, {
                    "task_id": task_id_value,
                    "error": timeout_error,
                    "completed_at": now.isoformat(),
                })
                db.commit()

                status_value = "timeout"
                error_value = timeout_error
                completed_at_value = now.isoformat()

        # 计算进度
        progress = 0
        if status_value == "completed":
            progress = 100
        elif status_value == "running":
            progress = 50
        elif status_value == "failed":
            progress = 0

        return {
            "task_id": task_id_value,
            "status": status_value,
            "progress": progress,
            "result": _normalize_generation_history_result_payload(result_value),
            "error": error_value,
            "created_at": created_at_value,
            "completed_at": completed_at_value
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
    logger = logging.getLogger("uvicorn.error")

    try:
        logger.info(f"🔍 查询项目 {project_id} 的正在运行任务...")

        # 🆕 首先检查 project_settings 中的 stage 状态
        # 如果所有 stage 都已完成，则将 running 任务标记为 completed（状态不一致修复）
        stage_result = None
        try:
            stage_statuses = WorkflowContextBuilder(db).load_stage_status_snapshot(project_id)
            stage_result = tuple(stage_statuses.values())
        except Exception as exc:
            err_text = str(exc)
            if "project_settings" in err_text and "does not exist" in err_text:
                logger.warning("   ⚠️ project_settings 表不存在，跳过 stage 状态检查")
            else:
                raise

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
        interrupted_tasks = []  # 🆕 服务重启/热重载后丢失执行体的孤儿任务
        now = utc_now()

        for row in results:
            task_id = row[0]
            task_type = row[1]
            status = row[2]
            created_at_str = row[3]
            task_timeout_minutes = _resolve_task_timeout_minutes(task_type)

            # 解析创建时间
            created_at = parse_datetime_utc(created_at_str, default=now) or now

            # 🔧 检测超时：如果任务运行超过30分钟，标记为超时
            task_age_minutes = max(0.0, (now - created_at).total_seconds() / 60)

            # 🆕 优先检查：如果所有 stage 都已完成，将 running 任务标记为 completed（状态不一致修复）
            if all_stages_completed and _can_sync_task_completed_from_stage_state(task_type):
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

            elif _should_mark_task_as_interrupted(task_type, created_at):
                interrupted_error = _build_task_interrupted_error(task_type)
                logger.warning(f"🧯 检测到孤儿任务: {task_id}（服务已重启，原执行体不存在）")

                update_query = text("""
                    UPDATE generation_history
                    SET status = 'failed',
                        error = :error,
                        completed_at = :completed_at
                    WHERE task_id = :task_id
                """)

                db.execute(update_query, {
                    "error": interrupted_error,
                    "completed_at": now.isoformat(),
                    "task_id": task_id
                })
                db.commit()

                interrupted_tasks.append({
                    "task_id": task_id,
                    "task_type": task_type,
                    "status": "failed",
                    "created_at": created_at_str,
                    "age_minutes": round(task_age_minutes, 1),
                    "reason": interrupted_error,
                })

                logger.info(f"   ✅ 已将孤儿任务 {task_id} 标记为 failed")

            elif _is_inactive_generate_next_chapter_task(task_type, task_id):
                inactive_error = _build_inactive_generate_next_chapter_error()
                logger.warning(f"🧯 检测到已结束但状态残留的生成下一章任务: {task_id}")

                update_query = text("""
                    UPDATE generation_history
                    SET status = 'failed',
                        error = :error,
                        completed_at = :completed_at
                    WHERE task_id = :task_id
                """)

                db.execute(update_query, {
                    "error": inactive_error,
                    "completed_at": now.isoformat(),
                    "task_id": task_id
                })
                db.commit()

                interrupted_tasks.append({
                    "task_id": task_id,
                    "task_type": task_type,
                    "status": "failed",
                    "created_at": created_at_str,
                    "age_minutes": round(task_age_minutes, 1),
                    "reason": inactive_error,
                })

                logger.info(f"   ✅ 已将残留任务 {task_id} 标记为 failed")

            elif task_age_minutes > task_timeout_minutes:
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
                    "error": _build_task_timeout_error(task_type, task_timeout_minutes),
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

        logger.info(
            f"   ✅ 找到 {len(running_tasks)} 个正在运行的任务, "
            f"{len(timeout_tasks)} 个超时任务, {len(stale_tasks)} 个已同步的过时任务, "
            f"{len(interrupted_tasks)} 个已清理的孤儿任务"
        )

        return {
            "running_tasks": running_tasks,
            "timeout_tasks": timeout_tasks,
            "stale_tasks": stale_tasks,  # 🆕 已同步的过时任务
            "interrupted_tasks": interrupted_tasks,
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

        workflow_context_builder = WorkflowContextBuilder(db)
        response = {
            "project_id": project_id,
            "stages": workflow_context_builder.load_stage_contents_snapshot(
                project_id,
                pretty_json=True,
            ),
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{project_id}/review-meta")
async def get_review_meta(
    project_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取工作流评审元信息，不混入阶段文本快照。"""
    try:
        query = text(
            """
            SELECT id FROM projects
            WHERE id = :project_id AND user_id = :user_id
            """
        )
        result = db.execute(
            query,
            {"project_id": project_id, "user_id": current_user.id},
        ).fetchone()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="项目不存在",
            )

        workflow_context_builder = WorkflowContextBuilder(db)
        return {
            "project_id": project_id,
            "review_meta": workflow_context_builder.load_review_meta(project_id),
        }

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

        workflow_context_builder = WorkflowContextBuilder(db)
        response = {
            "project_id": project_id,
            **workflow_context_builder.load_stage_status_snapshot(project_id),
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )




