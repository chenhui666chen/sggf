from __future__ import annotations

import logging
import json

from fastapi import Depends, HTTPException, status

from app.models.audiobook import ChapterAudio
from app.schemas.audiobook import (
    ChapterScriptUpdateRequest,
)
from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_owned_audiobook_project,
)
from app.services.audiobook.repository import ChapterAudioRepository, ChapterRepository

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/script", response_model=dict)
async def get_chapter_script(
    audiobook_project_id: int,
    chapter_id: int,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """获取指定章节的有声剧本与评审结果。

    仅返回最近一次生成/保存的剧本快照，不做版本历史。
    """
    db = owned.db
    project = owned.project

    # 获取章节剧本记录
    chapter_audio = ChapterAudioRepository.get_active_by_project_chapter(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    if not chapter_audio or not chapter_audio.script_json:
        fallback = ChapterAudioRepository.find_latest_reusable_script(
            db,
            project_id=project.id,
            chapter_id=chapter_id,
        )

        if fallback:
            if not chapter_audio:
                chapter_audio = ChapterAudio(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                )
                db.add(chapter_audio)

            chapter_audio.script_json = fallback.script_json
            chapter_audio.script_review_json = fallback.script_review_json
            chapter_audio.script_status = fallback.script_status or "pending"
            chapter_audio.segment_count = fallback.segment_count
            chapter_audio.dialogue_count = fallback.dialogue_count
            chapter_audio.narration_count = fallback.narration_count
            chapter_audio.character_count = fallback.character_count
            db.commit()
            logger.info(
                "♻️ 章节 %s 复用历史剧本供 audiobook_project_id=%s 使用",
                chapter_id,
                audiobook_project_id,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="章节剧本不存在，请先生成剧本",
            )

    try:
        script_segments = json.loads(chapter_audio.script_json)
    except json.JSONDecodeError as e:
        logger.error(f"❌ 解析章节剧本JSON失败 chapter_id={chapter_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="章节剧本数据损坏，请尝试重新生成",
        )

    script_review = None
    if chapter_audio.script_review_json:
        try:
            script_review = json.loads(chapter_audio.script_review_json)
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ 解析章节剧本评审JSON失败 chapter_id={chapter_id}: {e}")

    return {
        "chapter_id": chapter_id,
        "script_status": chapter_audio.script_status or "pending",
        "script_segments": script_segments,
        "script_review": script_review,
    }


@router.put("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/script", response_model=dict)
async def update_chapter_script(
    audiobook_project_id: int,
    chapter_id: int,
    request: ChapterScriptUpdateRequest,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """更新指定章节的有声剧本。

    - script_segments：覆盖写入最近一次剧本快照
    - script_status：可选，pending/reviewed/approved
    """
    db = owned.db
    project = owned.project

    # 验证章节是否属于该项目
    chapter = ChapterRepository.get_active_project_chapter(
        db,
        project_id=project.id,
        chapter_id=chapter_id,
    )

    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在或不属于该项目",
        )

    # 获取或创建章节音频记录
    chapter_audio = ChapterAudioRepository.get_active_by_project_chapter(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    if not chapter_audio:
        chapter_audio = ChapterAudio(
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        )
        db.add(chapter_audio)

    # 覆盖写入剧本
    try:
        chapter_audio.script_json = json.dumps(
            request.script_segments or [], ensure_ascii=False
        )
    except (TypeError, ValueError) as e:
        logger.error(f"❌ 序列化章节剧本失败 chapter_id={chapter_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="剧本数据格式不合法",
        )

    # 更新脚本状态（如有）
    if request.script_status:
        if request.script_status not in {"pending", "reviewed", "approved"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的script_status，必须为 pending/reviewed/approved",
            )
        chapter_audio.script_status = request.script_status

    # 剧本变化后，清空最终音频评审，防止混淆
    chapter_audio.final_audio_review_json = None

    db.commit()
    db.refresh(chapter_audio)

    return {
        "success": True,
        "chapter_id": chapter_id,
        "script_status": chapter_audio.script_status,
    }


