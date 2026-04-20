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

@router.get("/tasks/{task_id}/stream")
async def stream_task_progress(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """SSE 实时进度推送端点

    客户端连接后将持续接收任务进度事件
    """
    from fastapi.responses import StreamingResponse

    async def event_generator():
        async for event in sse_tracker.stream_events(task_id):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/previews/generate")
async def generate_preview(
    text: str = Body(..., embed=True),
    voice_id: str = Body(..., embed=True),
    tts_model: str = Body("qwen3-tts-flash", embed=True),
    emotion: Optional[str] = Body(None, embed=True),
    speed: Optional[float] = Body(None, embed=True),
    current_user: User = Depends(get_current_user),
):
    """快速生成试听片段（前 2 句）

    Args:
        text: 完整文本
        voice_id: 音色 ID
        tts_model: TTS 模型
        emotion: 情感参数
        speed: 语速参数
    """
    try:
        # 初始化 TTS 引擎
        from app.services.audiobook import get_engine_instance, set_engine_instance
        from core.unified_llm_client import get_llm_client

        llm_client = get_llm_client(strategy="conservative")
        engine = AudiobookEngine(
            enable_cache=False,
            max_concurrent=1,
            llm_client=llm_client,
            tts_model=tts_model,
        )

        # 生成预览
        preview = default_preview_generator.generate_preview(
            text=text,
            voice_id=voice_id,
            tts_engine=engine,
            emotion=emotion,
            speed=speed,
        )

        return {
            "success": True,
            "preview": preview,
        }

    except Exception as e:
        logger.error(f"❌ 预览生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"预览生成失败: {str(e)}")


@router.post("/retries/config")
async def configure_retry(
    max_retries: int = Body(3, embed=True),
    initial_delay: float = Body(1.0, embed=True),
    backoff_factor: float = Body(2.0, embed=True),
    enable_degraded: bool = Body(True, embed=True),
    current_user: User = Depends(get_current_user),
):
    """配置重试策略

    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒）
        backoff_factor: 退避因子
        enable_degraded: 是否启用降级
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        backoff_factor=backoff_factor,
        enable_degraded=enable_degraded,
    )
    return {
        "message": "重试配置已更新",
        "config": {
            "max_retries": config.max_retries,
            "initial_delay": config.initial_delay,
            "backoff_factor": config.backoff_factor,
            "enable_degraded": config.enable_degraded,
        },
    }
