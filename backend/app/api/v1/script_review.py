"""
剧本审核与调整 API。

这组接口保留给旧路由使用，但底层数据源已经切到
`ChapterAudio.script_json / script_review_json`，不再依赖已移除的
`ChapterAudio.task_id` 运行态字段。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/script-review", tags=["script-review"])


class QualityIssueResponse(BaseModel):
    """质量问题响应"""

    location: str
    severity: str
    category: str
    description: str
    suggestion: str


class ScriptQualityReportResponse(BaseModel):
    """剧本质量报告响应"""

    script_quality: Dict[str, Any]
    audio_balance: Dict[str, Any]
    pacing: Dict[str, Any]
    issues: List[QualityIssueResponse]
    overall_grade: str
    overall_score: float
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
    feedback: Optional[str] = None


def _get_authorized_chapter_audio(
    *,
    db: Session,
    audiobook_project_id: int,
    chapter_id: int,
    user_id: int,
) -> ChapterAudio:
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在",
        )

    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == user_id,
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问",
        )

    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频记录不存在，可能尚未生成",
        )

    return chapter_audio


def _load_json_text(
    raw_value: Optional[str],
    *,
    not_found_detail: str,
    invalid_detail: str,
) -> Any:
    if not raw_value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )
    try:
        return json.loads(raw_value)
    except Exception as exc:
        logger.warning("script_review JSON 解析失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=invalid_detail,
        ) from exc


@router.get("/report/{audiobook_project_id}/{chapter_id}", response_model=dict)
async def get_script_review_report(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取章节剧本审核报告。"""

    logger.info(
        "用户 %s 请求剧本审核报告: audiobook_project_id=%s, chapter_id=%s",
        current_user.id,
        audiobook_project_id,
        chapter_id,
    )

    chapter_audio = _get_authorized_chapter_audio(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        user_id=current_user.id,
    )
    quality_report = _load_json_text(
        chapter_audio.script_review_json,
        not_found_detail="章节剧本审核报告不存在，请先生成或重新评审剧本",
        invalid_detail="章节剧本审核报告已损坏，请重新生成",
    )

    return {
        "success": True,
        "chapter_id": chapter_id,
        "audiobook_project_id": audiobook_project_id,
        "script_status": chapter_audio.script_status or "pending",
        "quality_report": quality_report,
    }


@router.get("/script/{audiobook_project_id}/{chapter_id}", response_model=dict)
async def get_script_segments(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取章节剧本片段列表。"""

    logger.info(
        "用户 %s 请求剧本片段: audiobook_project_id=%s, chapter_id=%s",
        current_user.id,
        audiobook_project_id,
        chapter_id,
    )

    chapter_audio = _get_authorized_chapter_audio(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        user_id=current_user.id,
    )
    script_segments = _load_json_text(
        chapter_audio.script_json,
        not_found_detail="章节剧本不存在，请先生成剧本",
        invalid_detail="章节剧本数据已损坏，请重新生成",
    )

    script_review = None
    if chapter_audio.script_review_json:
        try:
            script_review = json.loads(chapter_audio.script_review_json)
        except Exception as exc:
            logger.warning("章节剧本评审 JSON 解析失败: chapter_id=%s error=%s", chapter_id, exc)

    return {
        "success": True,
        "chapter_id": chapter_id,
        "audiobook_project_id": audiobook_project_id,
        "script_status": chapter_audio.script_status or "pending",
        "segment_count": len(script_segments) if isinstance(script_segments, list) else 0,
        "script_segments": script_segments,
        "script_review": script_review,
    }


@router.post("/adjust")
async def adjust_script_segment(
    request: ScriptAdjustmentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    调整剧本片段。

    当前仍是占位接口，但权限校验和数据源已经对齐到持久化剧本字段。
    """

    logger.info("用户 %s 请求调整剧本片段", current_user.id)
    _get_authorized_chapter_audio(
        db=db,
        audiobook_project_id=request.audiobook_project_id,
        chapter_id=request.chapter_id,
        user_id=current_user.id,
    )

    return {
        "success": False,
        "message": "剧本调整功能正在开发中，将在后续版本中提供",
        "requested_changes": {
            "segment_index": request.segment_index,
            "text": request.text,
            "emotion": request.emotion,
        },
    }


@router.post("/regenerate")
async def regenerate_script(
    request: ScriptRegenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    重新生成剧本。

    当前仍是占位接口，但权限校验已经和新的章节剧本持久化结构一致。
    """

    logger.info("用户 %s 请求重新生成剧本", current_user.id)
    _get_authorized_chapter_audio(
        db=db,
        audiobook_project_id=request.audiobook_project_id,
        chapter_id=request.chapter_id,
        user_id=current_user.id,
    )

    return {
        "success": False,
        "message": "剧本重新生成功能正在开发中，将在后续版本中提供",
        "feedback": request.feedback,
    }


@router.post("/feedback")
async def submit_review_feedback(
    audiobook_project_id: int,
    chapter_id: int,
    feedback: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交审核反馈。"""

    logger.info("用户 %s 提交审核反馈", current_user.id)
    _get_authorized_chapter_audio(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        user_id=current_user.id,
    )

    return {
        "success": True,
        "message": "反馈已提交",
        "feedback": feedback,
    }
