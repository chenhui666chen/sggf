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

@router.post("/smart-chunk/preview")
async def preview_smart_chunking(
    segments: List[dict],
    max_tokens: int = 1800,
    min_tokens: int = 50,
    current_user: User = Depends(get_current_user),
):
    """预览智能分块结果（不实际执行）

    Args:
        segments: 原始剧本片段列表
        max_tokens: 单个分块最大 token 数
        min_tokens: 最小分块 token 数
    """
    chunker = SmartChunker(max_tokens=max_tokens, min_tokens=min_tokens)

    # 对片段列表进行分块
    chunked_segments = chunker.chunk_segments(segments)

    # 计算统计信息
    total_tokens = sum(chunker.estimate_tokens(s.get("text", "")) for s in chunked_segments)
    token_list = [chunker.estimate_tokens(s.get("text", "")) for s in chunked_segments]

    stats = {
        "total_chunks": len(chunked_segments),
        "total_tokens": total_tokens,
        "avg_tokens_per_chunk": total_tokens / len(chunked_segments) if chunked_segments else 0,
        "max_tokens_in_chunk": max(token_list) if token_list else 0,
        "min_tokens_in_chunk": min(token_list) if token_list else 0,
    }

    return {
        "original_segments": len(segments),
        "chunked_segments": len(chunked_segments),
        "total_tokens": total_tokens,
        "chunks": chunked_segments,
        "stats": stats,
    }


@router.post("/smart-chunk/estimate")
async def estimate_text_tokens(
    text: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
):
    """估算文本的 token 数量"""
    chunker = SmartChunker()
    estimated = chunker.estimate_tokens(text)
    needs_chunking = chunker.needs_chunking(text)

    return {
        "text_length": len(text),
        "estimated_tokens": estimated,
        "needs_chunking": needs_chunking,
        "max_tokens": chunker.max_tokens,
    }


@router.get("/voice-types")
async def list_voice_types(
    current_user: User = Depends(get_current_user),
):
    """获取所有声音类型预设列表"""
    return get_all_voice_types()


@router.get("/voice-types/{voice_type}")
async def get_voice_type_detail(
    voice_type: str,
    current_user: User = Depends(get_current_user),
):
    """获取指定声音类型详情"""
    preset = get_voice_type_preset(voice_type)
    if not preset:
        raise HTTPException(status_code=404, detail="声音类型不存在")
    return {
        "voice_type": preset.voice_type,
        "name": preset.name,
        "description": preset.description,
        "speed_modifier": preset.speed_modifier,
        "pitch_modifier": preset.pitch_modifier,
        "volume_modifier": preset.volume_modifier,
        "emotion_intensity": preset.emotion_intensity,
        "emotion_tendency": preset.emotion_tendency,
        "default_emotion": preset.default_emotion,
        "preferred_gender": preset.preferred_gender,
        "preferred_age_range": preset.preferred_age_range,
        "compatible_personalities": preset.compatible_personalities,
        "suitable_scenarios": preset.suitable_scenarios,
    }


@router.post("/voice-types/recommend")
async def recommend_voice_types(
    request: VoiceTypeRecommendationRequest,
    current_user: User = Depends(get_current_user),
):
    """根据角色属性推荐声音类型"""
    recommended = recommend_voice_type(
        personality=request.personality,
        gender=request.gender,
        age_range=request.age_range,
    )
    return {
        "recommended_types": recommended,
        "character_name": None,
    }


