from __future__ import annotations

import json
import logging

from fastapi import Depends

from app.core.security import get_current_user
from app.models.user import User
from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_active_chapter_audio_for_project,
    get_owned_audiobook_project,
)
from app.services.audiobook.narration_styles import (
    get_all_narration_styles,
)

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)


@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/review-status")
async def get_chapter_review_status(
    audiobook_project_id: int,
    chapter_id: int,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """获取章节整体审查状态
    
    返回：
    - 总片段数
    - 已审查片段数
    - 平均质量评分
    - 标记需要重新生成的片段索引
    """
    chapter_audio = get_active_chapter_audio_for_project(
        db=owned.db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    
    # 加载剧本和审查记录
    try:
        segments = json.loads(chapter_audio.script_json or "[]")
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "章节审查状态忽略损坏剧本 JSON: chapter_audio_id=%s error=%s",
            chapter_audio.id,
            exc,
        )
        segments = []
    if not isinstance(segments, list):
        logger.warning(
            "章节审查状态忽略非数组剧本 JSON: chapter_audio_id=%s payload_type=%s",
            chapter_audio.id,
            type(segments).__name__,
        )
        segments = []
    
    review_data = {}
    if chapter_audio.segment_reviews_json:
        try:
            loaded_review_data = json.loads(chapter_audio.segment_reviews_json)
            if isinstance(loaded_review_data, dict):
                review_data = loaded_review_data
            else:
                logger.warning(
                    "章节审查状态忽略非对象审查 JSON: chapter_audio_id=%s payload_type=%s",
                    chapter_audio.id,
                    type(loaded_review_data).__name__,
                )
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "章节审查状态忽略损坏审查 JSON: chapter_audio_id=%s error=%s",
                chapter_audio.id,
                exc,
            )
    
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
