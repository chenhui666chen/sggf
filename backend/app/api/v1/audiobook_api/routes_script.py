from __future__ import annotations

import asyncio
import logging
import os
import json
import math
from pathlib import Path
from urllib.parse import quote
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status, Response, Query, UploadFile, File, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.audiobook_delete_audit import AudiobookDeleteAudit
from app.models.character import Character
from app.models.audiobook_task import AudiobookTask
from app.schemas.audiobook import (
    AudiobookProjectCreate,
    GenerateAudioFromScriptsRequest,
    ChapterScriptUpdateRequest,
    AudiobookProjectResponse,
    ChapterAudioResponse,
    CharacterVoiceConfig,
    TTSPreviewRequest,
    ScriptSegmentPreviewRequest,
    SegmentRegenerateRequest,
    SegmentReviewRequest,
    AudiobookTaskStatus,
    CosyVoiceCloneCreateRequest,
    ChapterReviewStatus,
    NarrationStylePreset,
    SubtitleDownloadResponse,
    GenerationCheckpointResponse,
    SmartChunkConfig,
    ChunkStats,
    ChunkPreviewResponse,
    VoiceTypePresetResponse,
    VoiceTypeRecommendationRequest,
    VoiceTypeRecommendationResponse,
)
from app.celery_app import celery_app
from app.services.audiobook import AudiobookEngine
from app.services.audiobook.audio_mixer import AudioMixer
from app.services.audiobook.agents import SoundEffectDesigner
from app.services.audiobook.tts_engine import RetryConfig
from app.services.audiobook.voice_manager import VoiceManager
from app.services.audiobook.voice_manager_factory import create_voice_manager
from app.services.audiobook.voice_catalog import get_voice_entry, load_voice_catalog_for_model
from app.services.audiobook.project_audio_config import (
    parse_project_audio_config,
    get_characters_for_model,
    get_audio_fx,
)
from app.services.audiobook.cosyvoice_clone_client import (
    CosyVoiceCloneError,
    create_cosyvoice_v3_plus_clone,
    delete_cosyvoice_clone,
    get_clone_display_name,
    list_cosyvoice_v3_plus_clones,
    save_clone_display_name,
    upload_cosyvoice_v3_plus_clone_sample,
)
from app.services.audiobook.narration_styles import get_all_narration_styles, get_narration_style_preset, apply_narration_style_to_tts_params
from app.services.audiobook.subtitle_generator import SubtitleGenerator, SubtitleEntry
from app.services.audiobook.smart_chunker import SmartChunker, TextChunk
from app.services.audiobook.voice_types import (
    get_all_voice_types,
    get_voice_type_preset,
    recommend_voice_type,
    apply_voice_type_to_tts_params,
    create_character_voice_profile,
)
from app.services.audiobook.sse_progress import sse_tracker, create_progress_handler
from app.services.audiobook.smart_retrier import SmartRetrier, RetryConfig, retry_tts_call
from app.services.audiobook.preview_generator import PreviewGenerator, default_preview_generator
from app.services.audiobook.app_service import AudiobookAppService
from app.services.audiobook.repository import (
    AudiobookProjectRepository,
    ChapterAudioRepository,
    ProjectRepository,
    AudiobookTaskRepository,
)
from app.services.audiobook.task_support import (
    build_generation_checkpoint_payload as _build_generation_checkpoint_payload,
    build_task_status_response,
    enqueue_chapter_runs as _enqueue_chapter_runs,
    ensure_audiobook_points_precheck_passed as _ensure_audiobook_points_precheck_passed,
)
from app.services.points_task_precheck import (
    build_audiobook_task_points_precheck,
)
from app.services.user_center_points_events import (
    record_audiobook_billing_freeze,
)
from app.utils.datetime_utils import utc_now
from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/script", response_model=dict)
async def get_chapter_script(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取指定章节的有声剧本与评审结果。

    仅返回最近一次生成/保存的剧本快照，不做版本历史。
    """
    # 验证有声书项目
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在",
        )

    # 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问",
        )

    # 获取章节剧本记录
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()

    if not chapter_audio or not chapter_audio.script_json:
        fallback = (
            db.query(ChapterAudio)
            .join(AudiobookProject, ChapterAudio.audiobook_project_id == AudiobookProject.id)
            .filter(
                AudiobookProject.project_id == project.id,
                ChapterAudio.chapter_id == chapter_id,
                ChapterAudio.script_json.isnot(None),
            )
            .order_by(ChapterAudio.updated_at.desc())
            .first()
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
    except Exception as e:
        logger.error(f"❌ 解析章节剧本JSON失败 chapter_id={chapter_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="章节剧本数据损坏，请尝试重新生成",
        )

    script_review = None
    if chapter_audio.script_review_json:
        try:
            script_review = json.loads(chapter_audio.script_review_json)
        except Exception as e:
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新指定章节的有声剧本。

    - script_segments：覆盖写入最近一次剧本快照
    - script_status：可选，pending/reviewed/approved
    """
    # 验证有声书项目
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在",
        )

    # 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问",
        )

    # 验证章节是否属于该项目
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.project_id == project.id,
    ).first()

    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在或不属于该项目",
        )

    # 获取或创建章节音频记录
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()

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
    except Exception as e:
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


