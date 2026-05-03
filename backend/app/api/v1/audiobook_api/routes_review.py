from __future__ import annotations

import json

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.services.audiobook.narration_styles import (
    find_narration_style_preset,
    get_all_narration_styles,
)

from app.api.v1.audiobook_api import router

@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/review-status")
async def get_chapter_review_status(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取章节整体审查状态
    
    返回：
    - 总片段数
    - 已审查片段数
    - 平均质量评分
    - 标记需要重新生成的片段索引
    """
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="有声书项目不存在")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="无权限访问")
    
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    if not chapter_audio:
        raise HTTPException(status_code=404, detail="章节音频记录不存在")
    
    # 加载剧本和审查记录
    try:
        segments = json.loads(chapter_audio.script_json or "[]")
    except Exception:
        segments = []
    if not isinstance(segments, list):
        segments = []
    
    review_data = {}
    if chapter_audio.segment_reviews_json:
        try:
            loaded_review_data = json.loads(chapter_audio.segment_reviews_json)
            if isinstance(loaded_review_data, dict):
                review_data = loaded_review_data
        except Exception:
            review_data = {}
    
    total_segments = len(segments)
    reviewed_segments = 0
    
    # 计算平均质量评分
    scores = []
    flagged = []
    for idx, review in review_data.items():
        if not isinstance(review, dict):
            continue
        try:
            segment_idx = int(idx)
        except (TypeError, ValueError):
            continue
        if segment_idx < 0 or segment_idx >= total_segments:
            continue

        reviewed_segments += 1
        if review.get("quality_score"):
            scores.append(review["quality_score"])
        if review.get("needs_regenerate"):
            flagged.append(segment_idx)
    
    avg_score = sum(scores) / len(scores) if scores else None
    
    return {
        "chapter_id": chapter_id,
        "total_segments": total_segments,
        "reviewed_segments": reviewed_segments,
        "avg_quality_score": avg_score,
        "flagged_segments": flagged,
    }


@router.get("/narration-styles")
async def list_narration_styles(
    current_user: User = Depends(get_current_user),
):
    """获取所有叙事风格预设列表"""
    return get_all_narration_styles()


@router.get("/narration-styles/{style_id}")
async def get_narration_style(
    style_id: str,
    current_user: User = Depends(get_current_user),
):
    """获取指定叙事风格预设详情"""
    preset = find_narration_style_preset(style_id)
    if not preset:
        raise HTTPException(status_code=404, detail="叙事风格预设不存在")
    return preset

