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
from app.api.v1.workflow.helpers import (
    _estimate_tokens_by_chars,
    _select_text_model_by_input_tokens,
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
        "created_at": utc_now().isoformat()
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


def _update_history_progress(
    db: Session,
    *,
    task_id: str,
    progress: int,
    message: str,
) -> None:
    db.execute(
        text(
            """
            UPDATE generation_history
            SET progress = :progress, message = :message, updated_at = :updated_at
            WHERE task_id = :task_id
            """
        ),
        {
            "task_id": task_id,
            "progress": progress,
            "message": message,
            "updated_at": utc_now().isoformat(),
        },
    )
    db.commit()


def _safe_db_rollback(db: Session, reason: Optional[str] = None) -> None:
    try:
        db.rollback()
    except Exception as rollback_error:
        if reason:
            logger.warning(f"⚠️ 数据库回滚失败（{reason}）: {rollback_error}")
        else:
            logger.warning(f"⚠️ 数据库回滚失败: {rollback_error}")


def _create_generated_chapter(
    db: Session,
    *,
    project_id: int,
    chapter_number: int,
    title: str,
    content: str,
) -> Chapter:
    chapter = Chapter(
        project_id=project_id,
        chapter_number=chapter_number,
        title=title,
        content=content,
        status="draft",
        word_count=len(content or ""),
    )

    try:
        db.add(chapter)
        db.commit()
        db.refresh(chapter)
        return chapter
    except Exception:
        _safe_db_rollback(db, "保存生成章节失败")
        raise


def _extract_iteration_review_score(text: str) -> float:
    if not text:
        return 0.0

    patterns = [
        r"综合评分(?:\*\*)?\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10",
        r"\*\*?\s*综合评分\s*\*\*?\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10",
        r"综合评分[^0-9\n]{0,12}([0-9]+(?:\.[0-9]+)?)\s*分",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            continue

    return 0.0


def _load_latest_chapter_plan(db: Session, *, project_id: int, chapter_id: int) -> str:
    query = text("""
        SELECT content
        FROM chapter_plans
        WHERE project_id = :project_id AND chapter_id = :chapter_id
        ORDER BY id DESC
        LIMIT 1
    """)
    plan_result = db.execute(query, {
        "project_id": project_id,
        "chapter_id": chapter_id,
    }).fetchone()

    if not plan_result or not plan_result[0]:
        return ""

    return plan_result[0]


def _load_project_chapter_context(db: Session, *, project_id: int) -> Dict[str, str]:
    workflow_context_builder = WorkflowContextBuilder(db)
    project_profile = workflow_context_builder.get_project_profile(project_id)
    stage_context = workflow_context_builder.load_stage_text_context(project_id)
    outline = (stage_context.plot_outline or "").strip() or (project_profile.user_outline_plan or "").strip()

    return {
        "genre": project_profile.genre or "",
        "outline": outline,
        "world_setting": stage_context.world_setting or "",
        "characters": stage_context.characters or "",
    }


def _clip_context(text: str, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."

def _build_editor_chapter_context(db: Session, *, project_id: int, chapter_number: int, chapter_plan: str = "") -> Dict[str, Any]:
    project_context = _load_project_chapter_context(db, project_id=project_id)
    builder = WorkflowContextBuilder(db)
    stage_context = builder.load_stage_text_context(project_id)
    generation_context = builder.build_chapter_generation_context(
        project_id,
        chapter_number,
        plot_outline=stage_context.plot_outline or project_context["outline"],
        characters=stage_context.characters or project_context["characters"],
    )
    previous_chapter = db.query(Chapter).filter((Chapter.project_id == project_id) & (Chapter.chapter_number == chapter_number - 1)).first()
    previous_ending = ""
    if previous_chapter and previous_chapter.content:
        previous_ending = _clip_context(previous_chapter.content, 800)
    chapter_outline = (chapter_plan or "").strip() or (generation_context.current_chapter_outline or "").strip()
    return {
        "genre": project_context["genre"],
        "world_setting": project_context["world_setting"],
        "characters": generation_context.content_character_context or generation_context.character_prompt_context or project_context["characters"],
        "chapter_outline": chapter_outline,
        "volume_context": generation_context.current_volume_context or "",
        "character_state": generation_context.character_state_context or "",
        "character_anchor": generation_context.core_character_anchor_context or "",
        "focus_relationships": generation_context.focus_character_relationship_context or "",
        "previous_ending": previous_ending,
        "focus_character_names": list(generation_context.focus_character_names or []),
    }

def _build_regenerate_user_prompt(*, chapter, user_feedback: str, context: Dict[str, Any]) -> str:
    feedback = (user_feedback or "").strip()
    feedback_block = ("USER_REWRITE: " + feedback) if feedback else "No extra user instruction. Rewrite strictly from this chapter outline/plan."
    names = ", ".join(context.get("focus_character_names") or []) or "characters from outline"
    parts = [
        "Rewrite this chapter body and replace the old draft. Do not continue into the next chapter.",
        f"Chapter {chapter.chapter_number}: {chapter.title or ''}",
        "Genre: " + (context.get("genre") or "general"),
        "Chapter outline/plan:",
        _clip_context(context.get("chapter_outline") or "", 2400),
        "Volume context:",
        _clip_context(context.get("volume_context") or "", 1200),
        "World setting excerpt:",
        _clip_context(context.get("world_setting") or "", 1200),
        "Focus characters: " + names,
        "Character runtime state:",
        _clip_context(context.get("character_state") or "", 1200),
        "Character anchors:",
        _clip_context(context.get("character_anchor") or context.get("characters") or "", 1600),
        "Focus relationships:",
        _clip_context(context.get("focus_relationships") or "", 800),
        "Previous chapter ending:",
        context.get("previous_ending") or "None",
        feedback_block,
        "Output only the complete chapter body. Follow the previous ending, realize this chapter outline events and ending hook, and do not repeat an already written full plot loop.",
    ]
    return chr(10).join(part for part in parts if part)

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
            "updated_at": utc_now().isoformat()
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
            chapter_plan = _load_latest_chapter_plan(
                db,
                project_id=project_id,
                chapter_id=chapter.id,
            )
        except Exception as e:
            _safe_db_rollback(db, "加载章节计划失败")
            logger.warning(f"获取章节计划失败: {e}，将继续执行")
        
        # 获取项目题材
        genre = ""
        try:
            project_context = _load_project_chapter_context(db, project_id=project_id)
            genre = project_context["genre"]
        except Exception as e:
            _safe_db_rollback(db, "加载项目上下文失败")
            logger.warning(f"获取项目题材失败: {e}")
        
        # 📝 步骤1：质量评审
        update_query = text("""
            UPDATE generation_history
            SET progress = :progress, message = :message, updated_at = :updated_at
            WHERE task_id = :task_id
        """)
        _update_history_progress(
            db,
            task_id=task_id,
            progress=20,
            message="📝 正在评审章节质量...",
        )
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
        
        current_score = _extract_iteration_review_score(review_report)
        
        logger.info(f"📊 当前章节评分: {current_score}")
        
        # 🔧 步骤2：迭代优化
        _update_history_progress(
            db,
            task_id=task_id,
            progress=50,
            message=f"🔧 正在优化章节（当前评分: {current_score}）...",
        )
        db.commit()
        logger.info(f"🔧 [{task_id}] 开始优化章节...")
        
        # 使用ContentCreatorAgent进行改稿（但需要明确指示修改而非重写）
        editor_context = _build_editor_chapter_context(
            db,
            project_id=project_id,
            chapter_number=chapter.chapter_number,
            chapter_plan=chapter_plan or "",
        )
        chapter_plan = editor_context.get("chapter_outline") or chapter_plan
        outline_excerpt = _clip_context(editor_context.get("chapter_outline") or chapter_plan or "", 1800)
        state_excerpt = _clip_context(editor_context.get("character_state") or "", 800)
        prev_excerpt = editor_context.get("previous_ending") or "无"

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
- 本章细纲/规划：{outline_excerpt}
- 人物运行态：{state_excerpt}
- 上一章结尾：{prev_excerpt}

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
            return _estimate_tokens_by_chars(text)
        
        total_tokens = estimate_tokens(current_content) + estimate_tokens(review_report) + 500
        model_name, max_safe_limit = _select_text_model_by_input_tokens(total_tokens)
        
        logger.info(f"🤖 使用模型: {model_name} (预计tokens: {total_tokens}, qwen3.7-plus安全预算: {max_safe_limit})")
        
        # 执行改稿（使用较低temperature保持原文结构）
        optimized_content = content_agent.process(
            revision_prompt,
            temperature=0.3  # 使用低temperature保持忠于原文，避免过度创作
        )
        
        if not optimized_content:
            raise Exception("优化结果为空")
        chapter.content = optimized_content
        chapter.word_count = len(optimized_content or "")
        chapter.updated_at = utc_now()
        db.commit()

        try:
            from app.services.chapter_post_save import start_chapter_post_save_task

            start_chapter_post_save_task(
                chapter_id=chapter.id,
                chapter_title=chapter.title or f"第{chapter.chapter_number}章",
                chapter_content=optimized_content,
                chapter_number=chapter.chapter_number,
                project_id=project_id,
                generate_summary=True,
                chapter_plan=chapter_plan or "",
                auto_merge_settings=True,
            )
        except Exception as post_save_error:
            logger.warning(f"optimize post_save failed: {post_save_error}")

        
        # 完成 - 更新进度
        db.execute(update_query, {
            "task_id": task_id,
            "progress": 100,
            "message": "✅ 章节优化完成",
            "updated_at": utc_now().isoformat()
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
                "content": optimized_content,
                "original_score": current_score,
                "review_report": review_report,
            }, ensure_ascii=False),
            "completed_at": utc_now().isoformat()
        })
        db.commit()
        
        logger.info(f"✅ 章节优化任务完成: {task_id}")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"❌ 章节优化任务失败: {e}")
        _safe_db_rollback(db, "章节优化任务异常")
        
        # 更新任务状态为失败
        update_query = text("""
            UPDATE generation_history
            SET status = :status,
                error = :error,
                completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        
        try:
            db.execute(update_query, {
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
                "completed_at": utc_now().isoformat()
            })
            db.commit()
        except Exception as status_error:
            _safe_db_rollback(db, "写入章节优化失败状态")
            logger.error(f"❌ 写入章节优化失败状态失败: {status_error}")
    finally:
        db.close()

        db.close()


@router.post("/regenerate-chapter")
async def regenerate_chapter(
    request: dict,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    重新生成章节：完全重新创作指定章节的内容
    
    请求体：
    {
        "project_id": 1,
        "chapter_id": 10,
        "user_feedback": "用户反馈意见（可选）"
    }
    
    返回：
    {
        "task_id": "regenerate_xxx",
        "message": "重新生成任务已提交"
    }
    """
    import uuid
    import logging
    
    logger = logging.getLogger(__name__)
    
    project_id = request.get("project_id")
    chapter_id = request.get("chapter_id")
    user_feedback = request.get("user_feedback") or request.get("reason") or ""
    
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
    task_id = f"regenerate_{uuid.uuid4().hex[:8]}"
    
    # 创建任务记录
    insert_query = text("""
        INSERT INTO generation_history
        (project_id, task_type, task_id, status, created_at)
        VALUES (:project_id, :task_type, :task_id, :status, :created_at)
    """)
    
    db.execute(insert_query, {
        "project_id": project_id,
        "task_type": "regenerate_chapter",
        "task_id": task_id,
        "status": "running",
        "created_at": utc_now().isoformat()
    })
    db.commit()
    logger.info(f"✅ 重新生成任务记录已创建: {task_id}")
    
    # 使用线程异步执行重新生成
    import threading
    thread = threading.Thread(
        target=lambda: asyncio.run(
            _regenerate_chapter_task(
                task_id=task_id,
                project_id=project_id,
                chapter_id=chapter_id,
                user_feedback=user_feedback,
            )
        ),
        daemon=True
    )
    thread.start()
    logger.info(f"🚀 [{task_id}] 重新生成线程已启动")
    
    return {
        "task_id": task_id,
        "message": "重新生成任务已提交"
    }


async def _regenerate_chapter_task(
    task_id: str,
    project_id: int,
    chapter_id: int,
    user_feedback: str = "",
):
    """
    异步执行章节重新生成任务
    """
    from app.services.agents.agents import ContentCreatorAgent
    from sqlalchemy import text
    import logging
    
    logger = logging.getLogger(__name__)
    db = SessionLocal()
    
    try:
        # 更新任务状态：开始生成
        update_query = text("""
            UPDATE generation_history
            SET status = :status, progress = :progress, message = :message, updated_at = :updated_at
            WHERE task_id = :task_id
        """)
        db.execute(update_query, {
            "task_id": task_id,
            "status": "running",
            "progress": 0,
            "message": "🔄 开始重新生成章节...",
            "updated_at": utc_now().isoformat()
        })
        db.commit()
        logger.info(f"🔄 [{task_id}] 开始重新生成章节...")
        
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
        
        # 获取章节计划
        chapter_plan = ""
        try:
            chapter_plan = _load_latest_chapter_plan(
                db,
                project_id=project_id,
                chapter_id=chapter.id,
            )
        except Exception as e:
            _safe_db_rollback(db, "加载章节计划失败")
            logger.warning(f"获取章节计划失败: {e}，将继续执行")
        
        outline = ""
        genre = ""
        world_setting = ""
        characters = ""
        try:
            project_context = _load_project_chapter_context(db, project_id=project_id)
            outline = project_context["outline"]
            genre = project_context["genre"]
            world_setting = project_context["world_setting"]
            characters = project_context["characters"]
        except Exception as e:
            _safe_db_rollback(db, "加载项目上下文失败")
            logger.warning(f"获取项目设定失败: {e}")
        
        # 更新进度：准备生成
        _update_history_progress(
            db,
            task_id=task_id,
            progress=20,
            message="📝 正在准备生成章节...",
        )
        
        editor_context = _build_editor_chapter_context(
            db,
            project_id=project_id,
            chapter_number=chapter.chapter_number,
            chapter_plan=chapter_plan or "",
        )
        regenerate_prompt = _build_regenerate_user_prompt(
            chapter=chapter,
            user_feedback=user_feedback,
            context=editor_context,
        )
        chapter_plan = editor_context.get("chapter_outline") or chapter_plan

        # 更新进度：生成中
        _update_history_progress(
            db,
            task_id=task_id,
            progress=50,
            message="正在生成章节内容...",
        )

        content_agent = ContentCreatorAgent()
        content_agent.set_project_context(project_id)
        new_content = content_agent.process(regenerate_prompt)
        result = {"content": new_content}
        
        if not new_content:
            raise Exception("生成内容为空")
        
        # 更新进度：保存中
        _update_history_progress(
            db,
            task_id=task_id,
            progress=80,
            message="💾 正在保存章节内容...",
        )
        
        # 更新章节内容
        chapter.content = new_content
        chapter.word_count = len(new_content or "")
        chapter.updated_at = utc_now()
        db.commit()
        try:
            from app.services.chapter_post_save import start_chapter_post_save_task

            start_chapter_post_save_task(
                chapter_id=chapter.id,
                chapter_title=chapter.title or f"第{chapter.chapter_number}章",
                chapter_content=new_content,
                chapter_number=chapter.chapter_number,
                project_id=project_id,
                generate_summary=True,
                chapter_plan=chapter_plan or "",
                auto_merge_settings=True,
            )
        except Exception as post_save_error:
            logger.warning(f"regenerate post_save failed: {post_save_error}")

        
        # 完成 - 更新进度
        _update_history_progress(
            db,
            task_id=task_id,
            progress=100,
            message="✅ 章节重新生成完成",
        )
        logger.info(f"✅ [{task_id}] 章节重新生成完成")
        
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
                "content": new_content,
                "regenerated_content": new_content,
                "consistency_analysis": result.get("consistency_analysis", {}),
                "optimization_info": result.get("optimization_info", {}),
            }, ensure_ascii=False),
            "completed_at": utc_now().isoformat()
        })
        db.commit()
        
        logger.info(f"✅ 章节重新生成任务完成: {task_id}")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"❌ 章节重新生成任务失败: {e}")
        _safe_db_rollback(db, "章节重新生成任务异常")
        
        # 更新任务状态为失败
        update_query = text("""
            UPDATE generation_history
            SET status = :status,
                error = :error,
                completed_at = :completed_at
            WHERE task_id = :task_id
        """)
        
        try:
            db.execute(update_query, {
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
                "completed_at": utc_now().isoformat()
            })
            db.commit()
        except Exception as status_error:
            _safe_db_rollback(db, "写入章节重生成失败状态")
            logger.error(f"❌ 写入章节重生成失败状态失败: {status_error}")
    finally:
        db.close()

