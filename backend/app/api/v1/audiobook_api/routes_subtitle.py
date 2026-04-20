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

@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/subtitle")
async def get_chapter_subtitle(
    audiobook_project_id: int,
    chapter_id: int,
    format: str = Query("srt", regex="^(srt|vtt|ass)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取章节字幕文件"""
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
    
    if not chapter_audio.subtitle_path:
        raise HTTPException(status_code=404, detail="字幕文件不存在")
    
    subtitle_file = chapter_audio.subtitle_path
    if format == "vtt":
        subtitle_file = subtitle_file.replace(".srt", ".vtt")
    elif format == "ass":
        subtitle_file = subtitle_file.replace(".srt", ".ass")
    
    if not os.path.exists(subtitle_file):
        raise HTTPException(status_code=404, detail="字幕文件不存在")
    
    return FileResponse(
        subtitle_file,
        media_type="text/plain",
        filename=f"chapter_{chapter_id}.{format}",
    )


@router.get(
    "/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/checkpoint",
    response_model=GenerationCheckpointResponse,
)
async def get_generation_checkpoint(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取生成断点信息（用于断点续传）"""
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
    return _build_generation_checkpoint_payload(
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        run_type=None,
        db=db,
        audiobook_project_id=audiobook_project_id,
    )


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/resume-generation")
async def resume_chapter_generation(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从断点继续生成章节音频"""
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
    
    checkpoint_payload = _build_generation_checkpoint_payload(
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        run_type=None,
        db=db,
        audiobook_project_id=audiobook_project_id,
    )
    if not checkpoint_payload["can_resume"]:
        raise HTTPException(status_code=400, detail="没有可恢复的生成进度")

    logger.info(
        "Resume requested for audiobook_project_id=%s chapter_id=%s run_id=%s completed=%s/%s",
        audiobook_project_id,
        chapter_id,
        checkpoint_payload.get("run_id"),
        checkpoint_payload.get("completed_segments"),
        checkpoint_payload.get("total_segments"),
    )

    return {
        "message": "已获取最新断点信息，可用于继续生成",
        "run_id": checkpoint_payload.get("run_id"),
        "run_status": checkpoint_payload.get("run_status"),
        "current_stage": checkpoint_payload.get("current_stage"),
        "completed_segments": checkpoint_payload.get("completed_segments"),
        "total_segments": checkpoint_payload.get("total_segments"),
        "completed_segment_indices": checkpoint_payload.get("completed_segment_indices"),
        "cached_audio_paths": checkpoint_payload.get("cached_audio_paths"),
        "checkpoint_source": checkpoint_payload.get("checkpoint_source"),
    }

    if not chapter_audio.generation_progress_json:
        raise HTTPException(status_code=400, detail="没有可恢复的生成进度")
    
    progress_data = json.loads(chapter_audio.generation_progress_json)
    completed_indices = progress_data.get("completed_segment_indices", [])
    cached_paths = progress_data.get("cached_audio_paths", {})
    
    logger.info(f"🔄 恢复章节 {chapter_id} 生成: 已完成 {len(completed_indices)} 个片段")
    
    return {
        "message": "已恢复生成进度",
        "completed_segments": len(completed_indices),
        "cached_audio_paths": cached_paths,
    }


@router.get("/projects/{audiobook_project_id:int}/browser-player")
async def get_browser_player_data(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取浏览器播放器所需数据（章节列表、音频URL、字幕URL）"""
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
    
    chapters_data = []
    for chapter_audio in audiobook_project.chapter_audios:
        chapter = db.query(Chapter).filter(Chapter.id == chapter_audio.chapter_id).first()
        if not chapter:
            continue
        
        chapter_info = {
            "chapter_id": chapter_audio.chapter_id,
            "chapter_number": chapter.chapter_number,
            "chapter_title": chapter.title,
            "audio_url": f"/api/v1/audiobook/download/{audiobook_project_id}/{chapter_audio.chapter_id}",
            "duration": chapter_audio.duration,
            "has_subtitle": bool(chapter_audio.subtitle_path and os.path.exists(chapter_audio.subtitle_path)),
            "subtitle_url": f"/api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_audio.chapter_id}/subtitle" if chapter_audio.subtitle_path else None,
        }
        
        if chapter_audio.script_json:
            try:
                chapter_info["segments"] = json.loads(chapter_audio.script_json)
            except:
                chapter_info["segments"] = []
        
        chapters_data.append(chapter_info)
    
    return {
        "project_id": audiobook_project_id,
        "project_title": project.title,
        "chapters": chapters_data,
        "total_duration": audiobook_project.total_duration,
    }


