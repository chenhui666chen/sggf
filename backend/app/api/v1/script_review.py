"""
剧本审核与调整 API

功能：
1. 获取章节剧本审核报告
2. 提交审核反馈
3. 调整剧本片段
4. 重新生成剧本
"""
import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.audiobook import ChapterAudio, AudiobookProject
from app.models.project import Chapter, Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/script-review", tags=["script-review"])


# ==================== Pydantic Schemas ====================

class QualityIssueResponse(BaseModel):
    """质量问题响应"""
    location: str
    severity: str  # critical/major/minor
    category: str  # script/audio/pacing
    description: str
    suggestion: str


class ScriptQualityReportResponse(BaseModel):
    """剧本质量报告响应"""
    # 剧本质量
    script_quality: Dict[str, Any]
    # 音频平衡
    audio_balance: Dict[str, Any]
    # 节奏评估
    pacing: Dict[str, Any]
    # 问题列表
    issues: List[QualityIssueResponse]
    # 总评
    overall_grade: str
    overall_score: float
    # 修订建议
    revision_suggestions: List[str]


class ScriptSegmentResponse(BaseModel):
    """剧本片段响应"""
    type: str
    text: str
    speaker: str
    emotion: str
    performance_notes: str = ""
    pause_before: float = 0.0
    pause_after: float = 0.0
    voice_params: Optional[Dict[str, float]] = None
    sound_effects: List[str] = []
    music_cue: str = ""
    original_text: str = ""
    adaptation_reason: str = ""


class ScriptReviewRequest(BaseModel):
    """剧本审核请求"""
    chapter_id: int
    audiobook_project_id: int


class ScriptAdjustmentRequest(BaseModel):
    """剧本调整请求"""
    chapter_id: int
    audiobook_project_id: int
    segment_index: int
    # 可调整的字段
    text: Optional[str] = None
    emotion: Optional[str] = None
    performance_notes: Optional[str] = None
    voice_params: Optional[Dict[str, float]] = None
    sound_effects: Optional[List[str]] = None
    music_cue: Optional[str] = None


class ScriptRegenerateRequest(BaseModel):
    """剧本重新生成请求"""
    chapter_id: int
    audiobook_project_id: int
    feedback: Optional[str] = None  # 用户反馈


# ==================== API Endpoints ====================

@router.get("/report/{audiobook_project_id}/{chapter_id}", response_model=dict)
async def get_script_review_report(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取章节剧本审核报告
    
    工作流：
    1. 验证权限
    2. 从AudiobookEngine获取task_id
    3. 重新运行质量审核（或从缓存获取）
    4. 返回质量报告
    """
    logger.info(f"🔍 用户 {current_user.id} 请求剧本审核报告: audiobook_project_id={audiobook_project_id}, chapter_id={chapter_id}")
    
    # 1. 验证权限
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    # 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问"
        )
    
    # 2. 获取ChapterAudio记录（包含task_id）
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id
    ).first()
    
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频记录不存在，可能尚未生成"
        )
    
    # 3. 从AudiobookEngine获取任务状态（包含quality_report）
    from app.services.audiobook import get_engine_instance
    
    engine = get_engine_instance()
    if not engine:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="有声书引擎未初始化"
        )
    
    task_id = chapter_audio.task_id
    if not task_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务ID不存在，无法获取审核报告"
        )
    
    task_status = engine.get_task_status(task_id)
    
    if not task_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务状态不存在: {task_id}"
        )
    
    # 4. 提取quality_report（从任务状态的quality_review阶段）
    quality_review_stage = task_status.get("stages", {}).get("quality_review", {})
    quality_metrics = quality_review_stage.get("metrics", {})
    
    # 如果quality_report不在metrics中，则说明尚未完成评审
    if not quality_metrics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="质量评审尚未完成，请稍后再试"
        )
    
    # 返回质量报告（包装为API响应格式）
    return {
        "success": True,
        "chapter_id": chapter_id,
        "audiobook_project_id": audiobook_project_id,
        "task_id": task_id,
        "quality_report": quality_metrics
    }


@router.get("/script/{audiobook_project_id}/{chapter_id}", response_model=dict)
async def get_script_segments(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取章节剧本片段列表
    
    返回剧本的所有片段（用于前端展示和编辑）
    """
    logger.info(f"📝 用户 {current_user.id} 请求剧本片段: audiobook_project_id={audiobook_project_id}, chapter_id={chapter_id}")
    
    # 验证权限（复用上面的逻辑）
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问"
        )
    
    # 获取ChapterAudio记录
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id
    ).first()
    
    if not chapter_audio or not chapter_audio.task_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节任务不存在"
        )
    
    # 从AudiobookEngine获取任务状态
    from app.services.audiobook import get_engine_instance
    
    engine = get_engine_instance()
    if not engine:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="有声书引擎未初始化"
        )
    
    task_status = engine.get_task_status(chapter_audio.task_id)
    
    if not task_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务状态不存在"
        )
    
    # 从script_adaptation阶段提取剧本片段
    script_stage = task_status.get("stages", {}).get("script_adaptation", {})
    script_metrics = script_stage.get("metrics", {})
    
    # script_metrics中应该包含segments_count，但实际的剧本片段需要从别处获取
    # 由于当前任务追踪器没有存储完整的剧本片段，我们只能返回元数据
    # TODO: 在未来版本中，可以在task_tracker中存储完整的剧本片段
    
    return {
        "success": True,
        "chapter_id": chapter_id,
        "audiobook_project_id": audiobook_project_id,
        "task_id": chapter_audio.task_id,
        "message": "当前版本仅支持查看质量报告，完整剧本编辑功能将在后续版本中提供",
        "script_metadata": script_metrics
    }


@router.post("/adjust")
async def adjust_script_segment(
    request: ScriptAdjustmentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    调整剧本片段
    
    允许用户修改单个剧本片段的属性（文本、情感、音效等）
    注意：当前版本为占位实现，完整功能需要集成剧本存储
    """
    logger.info(f"✏️ 用户 {current_user.id} 请求调整剧本片段")
    
    # 验证权限
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == request.audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问"
        )
    
    # TODO: 实现剧本片段调整逻辑
    # 1. 从存储中加载剧本片段
    # 2. 应用用户修改
    # 3. 重新验证质量
    # 4. 保存修改后的剧本
    
    return {
        "success": False,
        "message": "剧本调整功能正在开发中，将在后续版本中提供",
        "requested_changes": {
            "segment_index": request.segment_index,
            "text": request.text,
            "emotion": request.emotion
        }
    }


@router.post("/regenerate")
async def regenerate_script(
    request: ScriptRegenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    重新生成剧本
    
    基于用户反馈重新生成整个章节的剧本
    注意：当前版本为占位实现，完整功能需要集成AudiobookEngine
    """
    logger.info(f"🔄 用户 {current_user.id} 请求重新生成剧本")
    
    # 验证权限
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == request.audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问"
        )
    
    # TODO: 实现剧本重新生成逻辑
    # 1. 获取原始章节内容
    # 2. 应用用户反馈
    # 3. 调用AudiobookScriptAgent重新生成
    # 4. 更新任务状态
    
    return {
        "success": False,
        "message": "剧本重新生成功能正在开发中，将在后续版本中提供",
        "feedback": request.feedback
    }


@router.post("/feedback")
async def submit_review_feedback(
    audiobook_project_id: int,
    chapter_id: int,
    feedback: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    提交审核反馈
    
    允许用户对剧本质量报告提交反馈意见
    """
    logger.info(f"💬 用户 {current_user.id} 提交审核反馈")
    
    # 验证权限
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问"
        )
    
    # TODO: 存储用户反馈
    # 可以存储到数据库的feedback表，或者直接关联到ChapterAudio记录
    
    return {
        "success": True,
        "message": "反馈已提交",
        "feedback": feedback
    }
