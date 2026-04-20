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
from app.services.audiobook.smart_retrier import SmartRetrier, retry_tts_call
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

@router.post("/tts/preview")
async def tts_preview(
    request: TTSPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """合成一小段音频用于前端试听"""
    # 简单防护：限制文本长度
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文本不能为空")
    if len(text) > 200:
        text = text[:200]

    # 选择模型：默认使用 qwen3-tts-flash，支持多种 TTS 模型
    model_name = (request.model or "qwen3-tts-flash").strip()
    supported_models = {
        "qwen3-tts-flash",
        "cosyvoice-v3-plus",
        "minimax-speech-2.8-hd",
        "minimax-speech-2.8-turbo",
    }
    if model_name not in supported_models:
        model_name = "qwen3-tts-flash"

    # 试听场景优先“快速恢复”而非长时间等待：
    # - 额外多 1 次重试（应对偶发断连）
    # - 基础退避更小，避免前端等待过久
    preview_retry = RetryConfig(max_retries=4, base_delay=1.0, max_delay=8.0, exponential_base=2.0, jitter=True)
    # 将前端的 voice_id（如 'male_young_energetic'）映射为真实的 TTS 音色ID
    if model_name == "qwen3-tts-flash":
        preset = VoiceManager.PRESET_VOICES.get(request.voice_id)
        speaker_id = preset["tts_speaker_id"] if preset else request.voice_id
    else:
        entry = get_voice_entry(request.voice_id, model=model_name)
        speaker_id = entry.get("speaker") if entry else request.voice_id

    voice_params: dict = {
        "speaker": speaker_id,
        "volume": request.volume,
    }
    if request.speed is not None:
        voice_params["rate"] = request.speed
    if request.pitch is not None:
        voice_params["pitch"] = request.pitch

    try:
        audio_bytes = await runtime_synthesize_speech(
            text=text,
            voice_params=voice_params,
            model_id=model_name,
            enable_cache=False,
            max_concurrent=1,
            request_delay=0.0,
            retry_config=preview_retry,
        )
    except Exception as exc:
        logger.warning("TTS试听失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        ) from exc
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        )

    media_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
    return Response(content=audio_bytes, media_type=media_type)


@router.get("/tts/models")
async def list_tts_models(
    current_user: User = Depends(get_current_user),
):
    """列出所有支持的 TTS 模型及其基本信息"""
    from app.services.audiobook.voice_manager_factory import list_all_models, MODEL_VOICE_MAPPING
    from app.services.audiobook.voice_catalog import load_voice_catalog_for_model
    
    models = []
    for model_name in list_all_models():
        try:
            catalog = load_voice_catalog_for_model(model_name)
            voices = catalog.get("voices", [])
            meta = catalog.get("meta", {})
            models.append({
                "id": model_name,
                "name": _get_model_display_name(model_name),
                "description": _get_model_description(model_name),
                "voice_count": meta.get("voice_count", len(voices)),
                "price_per_10k": _get_model_price(model_name),
                "features": _get_model_features(model_name),
            })
        except Exception:
            pass
    
    return {"models": models}


def _get_model_display_name(model: str) -> str:
    names = {
        "qwen3-tts-flash": "Qwen3-TTS Flash",
        "qwen3-tts-plus": "Qwen3-TTS Plus",
        "cosyvoice-v3-plus": "CosyVoice v3 Plus",
        "minimax-speech-2.8-hd": "MiniMax Speech 2.8 HD",
        "minimax-speech-2.8-turbo": "MiniMax Speech 2.8 Turbo",
    }
    return names.get(model, model)


def _get_model_description(model: str) -> str:
    descriptions = {
        "qwen3-tts-flash": "高性价比，49音色，适合批量生成",
        "qwen3-tts-plus": "高质量，支持SSML",
        "cosyvoice-v3-plus": "顶级音质，情绪控制，Instruct模式",
        "minimax-speech-2.8-hd": "最高音质，语气词标签，100+音色",
        "minimax-speech-2.8-turbo": "优秀音质，高性价比，高并发",
    }
    return descriptions.get(model, "")


def _get_model_price(model: str) -> float:
    prices = {
        "qwen3-tts-flash": 1.0,
        "qwen3-tts-plus": 2.0,
        "cosyvoice-v3-plus": 2.0,
        "minimax-speech-2.8-hd": 6.0,
        "minimax-speech-2.8-turbo": 3.0,
    }
    return prices.get(model, 1.0)


def _get_model_features(model: str) -> list:
    features_map = {
        "qwen3-tts-flash": ["高性价比", "49音色", "批量合成"],
        "qwen3-tts-plus": ["高质量", "SSML支持"],
        "cosyvoice-v3-plus": ["顶级音质", "情绪控制", "Instruct模式"],
        "minimax-speech-2.8-hd": ["最高音质", "语气词标签", "100+音色", "混合音色"],
        "minimax-speech-2.8-turbo": ["优秀音质", "高性价比", "高并发"],
    }
    return features_map.get(model, [])


@router.get("/tts/voices")
async def list_tts_voices(
    model: str = "qwen3-tts-flash",
    current_user: User = Depends(get_current_user),
):
    """Expose the supported voices to the frontend (model-specific)."""
    model = (model or "qwen3-tts-flash").strip()
    if model not in {"qwen3-tts-flash", "cosyvoice-v3-plus", "minimax-speech-2.8-hd", "minimax-speech-2.8-turbo"}:
        if model.startswith("minimax-speech"):
            model = "minimax-speech-2.8-hd"
        elif model.startswith("qwen3-tts"):
            model = "qwen3-tts-flash"
        else:
            model = "qwen3-tts-flash"
    catalog = load_voice_catalog_for_model(model)
    meta = catalog.get("meta") or {}
    voices = list(catalog.get("voices") or [])

    # cosyvoice-v3-plus：合并“官方内置音色”与“复刻音色”（DashScope VoiceEnrollmentService）
    if model == "cosyvoice-v3-plus":
        try:
            clones, _clone_meta = list_cosyvoice_v3_plus_clones()
            voices.extend([c.to_voice_preset(get_clone_display_name(c.voice_id)) for c in clones])
        except CosyVoiceCloneError:
            # 未配置 API Key 等情况下，不阻塞页面使用内置音色
            pass
    return {
        "model": meta.get("model", "qwen3-tts-flash"),
        "updated_at": meta.get("updated_at"),
        "source": meta.get("source"),
        "voice_count": len(voices),
        "voices": voices,
    }


@router.post("/tts/voices/cosyvoice-v3-plus/clones")
async def create_cosyvoice_v3_plus_voice_clone(
    request: CosyVoiceCloneCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """创建 cosyvoice-v3-plus 复刻音色。

    说明：DashScope 克隆接口要求 input.url 为公网可访问地址或 oss:// 临时 URL。
    """
    try:
        import hashlib
        import re
        import secrets

        display_name = (request.name or "").strip()
        if not display_name:
            raise CosyVoiceCloneError("name 不能为空")

        prefix = (request.prefix or "").strip()
        if not prefix:
            # 生成策略：
            # - 允许 name 任意字符（含中文），但 prefix 必须满足 SDK 要求：字母/数字/下划线，1~32
            # - 注意：cosyvoice clone 要求 prefix 最长 10 个字符
            # - 尽量从 name 提取可读片段，否则退化为 v，再拼接 hash 提升唯一性
            slug = re.sub(r"[^A-Za-z0-9_]+", "_", display_name).strip("_").lower()
            base = (slug[:4] if slug else "v").strip("_") or "v"
            uid = str(getattr(current_user, "id", "0"))
            # 防碰撞：加一个稳定 hash 片段（避免同名同用户频繁生成完全一致）
            h = hashlib.sha1(f"{uid}:{display_name}".encode("utf-8")).hexdigest()[:6]  # noqa: S324
            rand = secrets.token_hex(1)  # 2 hex chars
            prefix = f"{base}{h}{rand}"[:10]

        result = create_cosyvoice_v3_plus_clone(prefix=prefix, audio_url=request.url)
        save_clone_display_name(voice_id=result.get("voice_id", ""), display_name=display_name)
        result["display_name"] = display_name
        return result
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/cosyvoice-v3-plus/clones/upload")
async def upload_cosyvoice_v3_plus_clone_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传本地音频，生成临时 oss:// URL。"""
    try:
        content = await file.read()
        if not content:
            raise CosyVoiceCloneError("file 不能为空")
        return upload_cosyvoice_v3_plus_clone_sample(
            filename=file.filename or "audio",
            content=content,
            content_type=file.content_type,
        )
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception:
            pass


@router.get("/tts/voices/cosyvoice-v3-plus/clones")
async def list_cosyvoice_v3_plus_voice_clones(
    prefix: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """列出 cosyvoice-v3-plus 的复刻音色（当前 API Key 维度）。"""
    try:
        clones, meta = list_cosyvoice_v3_plus_clones(prefix=prefix)
        return {
            "meta": meta,
            "voices": [
                {
                    "voice_id": c.voice_id,
                    "status": c.status,
                    "gmt_create": c.gmt_create,
                    "gmt_modified": c.gmt_modified,
                }
                for c in clones
            ],
        }
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/tts/voices/cosyvoice-v3-plus/clones/{voice_id}")
async def delete_cosyvoice_v3_plus_voice_clone(
    voice_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除 cosyvoice-v3-plus 复刻音色。"""
    try:
        return delete_cosyvoice_clone(voice_id=voice_id)
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ==================== API Endpoints ====================
