from __future__ import annotations

import asyncio
import base64
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
    TTSPreviewWithTimestampsRequest,
    TTSPreviewWithTimestampsResponse,
    ScriptSegmentPreviewRequest,
    SegmentRegenerateRequest,
    SegmentReviewRequest,
    AudiobookTaskStatus,
    CosyVoiceCloneCreateRequest,
    CosyVoiceDesignCreateRequest,
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
from app.services.audiobook.constants import normalize_speaker_id
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
    COSYVOICE_V35_PLUS_MODEL_ID,
    CosyVoiceCloneError,
    create_cosyvoice_v3_plus_clone,
    create_cosyvoice_v3_plus_design,
    delete_cosyvoice_clone,
    get_clone_display_name,
    is_cosyvoice_v35_plus_voice_id,
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
from core.model_resolution import normalize_model_id
from core.unified_media_runtime import (
    create_tts_engine as runtime_create_tts_engine,
    synthesize_speech as runtime_synthesize_speech,
)

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

DEFAULT_TTS_MODEL = "qwen3-tts-instruct-flash"
SUPPORTED_TTS_MODELS = {
    "qwen3-tts-instruct-flash",
    COSYVOICE_V35_PLUS_MODEL_ID,
    "minimax-speech-2.8-hd",
    "minimax-speech-2.8-turbo",
}


def _is_cosyvoice_v35_model(model: str) -> bool:
    return (normalize_model_id(model) or "").strip() == COSYVOICE_V35_PLUS_MODEL_ID


def _validate_cosyvoice_v35_voice_id(voice_id: str) -> str:
    resolved = str(voice_id or "").strip()
    if is_cosyvoice_v35_plus_voice_id(resolved):
        return resolved

    entry = get_voice_entry(resolved, model=COSYVOICE_V35_PLUS_MODEL_ID)
    if entry:
        return str(entry.get("speaker") or resolved)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="cosyvoice-v3.5-plus 不提供系统音色，请先创建并选择复刻/设计音色",
    )

def _build_cosyvoice_voice_prefix(display_name: str, current_user: User) -> str:
    import hashlib
    import re
    import secrets

    cleaned_name = (display_name or "").strip()
    if not cleaned_name:
        raise CosyVoiceCloneError("name 不能为空")

    slug = re.sub(r"[^A-Za-z0-9_]+", "_", cleaned_name).strip("_").lower()
    base = (slug[:4] if slug else "v").strip("_") or "v"
    user_id = str(getattr(current_user, "id", "0"))
    digest = hashlib.sha1(f"{user_id}:{cleaned_name}".encode("utf-8")).hexdigest()[:6]  # noqa: S324
    suffix = secrets.token_hex(1)
    return f"{base}{digest}{suffix}"[:10]


def _resolve_preview_text(request: TTSPreviewRequest) -> str:
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文本不能为空")
    if len(text) > 200:
        text = text[:200]
    return text


def _resolve_preview_model_name(request: TTSPreviewRequest) -> str:
    model_name = normalize_model_id(request.model or DEFAULT_TTS_MODEL) or DEFAULT_TTS_MODEL
    if model_name not in SUPPORTED_TTS_MODELS:
        model_name = DEFAULT_TTS_MODEL
    return model_name


def _resolve_preview_speaker_id(request: TTSPreviewRequest, model_name: str) -> str:
    if model_name.startswith("qwen3-tts"):
        preset = VoiceManager.PRESET_VOICES.get(request.voice_id)
        return normalize_speaker_id(preset["tts_speaker_id"] if preset else request.voice_id)

    entry = get_voice_entry(request.voice_id, model=model_name)
    speaker_id = entry.get("speaker") if entry else request.voice_id
    if _is_cosyvoice_v35_model(model_name):
        speaker_id = _validate_cosyvoice_v35_voice_id(speaker_id)
    return speaker_id


def _build_preview_voice_params(request: TTSPreviewRequest, speaker_id: str) -> dict:
    voice_params: dict = {
        "speaker": speaker_id,
        "volume": request.volume,
    }
    if request.speed is not None:
        voice_params["rate"] = request.speed
    if request.pitch is not None:
        voice_params["pitch"] = request.pitch

    instruction = str(getattr(request, "instruction", "") or "").strip()
    if instruction:
        voice_params["instruction"] = instruction

    if getattr(request, "word_timestamp_enabled", False):
        voice_params["word_timestamp_enabled"] = True
    if getattr(request, "phoneme_timestamp_enabled", False):
        voice_params["phoneme_timestamp_enabled"] = True

    return voice_params


def _build_preview_retry_config() -> RetryConfig:
    return RetryConfig(max_retries=4, base_delay=1.0, max_delay=8.0, exponential_base=2.0, jitter=True)


async def _synthesize_preview_payload(
    *,
    text: str,
    model_name: str,
    voice_params: dict,
    retry_config: RetryConfig,
) -> dict:
    engine = runtime_create_tts_engine(
        model_id=model_name,
        strategy="balanced",
        enable_cache=False,
        max_concurrent=1,
        request_delay=0.0,
        retry_config=retry_config,
    )
    payload = await engine.synthesize_with_metadata(text, voice_params, "neutral")
    if not isinstance(payload, dict):
        raise RuntimeError("TTS 试听未返回有效 payload")
    return payload


@router.post("/tts/preview")
async def tts_preview(
    request: TTSPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """合成一小段音频用于前端试听"""
    text = _resolve_preview_text(request)
    model_name = _resolve_preview_model_name(request)
    preview_retry = _build_preview_retry_config()
    speaker_id = _resolve_preview_speaker_id(request, model_name)
    voice_params = _build_preview_voice_params(request, speaker_id)

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


@router.post("/tts/preview-with-timestamps", response_model=TTSPreviewWithTimestampsResponse)
async def tts_preview_with_timestamps(
    request: TTSPreviewWithTimestampsRequest,
    current_user: User = Depends(get_current_user),
):
    """合成短音频并返回可消费的词级时间戳。当前仅支持 CosyVoice v3.5 Plus。"""
    text = _resolve_preview_text(request)
    model_name = _resolve_preview_model_name(request)
    if not _is_cosyvoice_v35_model(model_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前时间戳试听接口仅支持 cosyvoice-v3.5-plus",
        )

    preview_retry = _build_preview_retry_config()
    speaker_id = _resolve_preview_speaker_id(request, model_name)
    voice_params = _build_preview_voice_params(request, speaker_id)

    try:
        payload = await _synthesize_preview_payload(
            text=text,
            model_name=model_name,
            voice_params=voice_params,
            retry_config=preview_retry,
        )
    except Exception as exc:
        logger.warning("带时间戳的 TTS 试听失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        ) from exc

    audio_bytes = payload.get("audio_bytes")
    if isinstance(audio_bytes, bytearray):
        audio_bytes = bytes(audio_bytes)
    if not isinstance(audio_bytes, bytes) or not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        )

    audio_format = str(payload.get("format") or ("wav" if audio_bytes.startswith(b"RIFF") else "mp3")).strip().lower()
    audio_mime_type = "audio/wav" if audio_format == "wav" or audio_bytes.startswith(b"RIFF") else "audio/mpeg"
    tts_timestamps = payload.get("tts_timestamps") if isinstance(payload.get("tts_timestamps"), list) else []
    tts_timestamp_sentences = (
        payload.get("tts_timestamp_sentences")
        if isinstance(payload.get("tts_timestamp_sentences"), list)
        else []
    )
    phoneme_timestamps = payload.get("phoneme_timestamps") if isinstance(payload.get("phoneme_timestamps"), list) else []

    return TTSPreviewWithTimestampsResponse(
        model=model_name,
        voice_id=speaker_id,
        audio_data_base64=base64.b64encode(audio_bytes).decode("utf-8"),
        audio_format=audio_format,
        audio_mime_type=audio_mime_type,
        audio_size_bytes=len(audio_bytes),
        provider=str(payload.get("provider") or "") or None,
        provider_model=str(payload.get("provider_model") or "") or None,
        transport=str(payload.get("transport") or "") or None,
        word_timestamp_enabled=bool(payload.get("word_timestamp_enabled")),
        phoneme_timestamp_enabled=bool(payload.get("phoneme_timestamp_enabled")),
        word_timestamps_available=bool(tts_timestamps),
        phoneme_timestamps_available=bool(phoneme_timestamps),
        tts_timestamps=tts_timestamps,
        tts_timestamp_sentences=tts_timestamp_sentences,
        phoneme_timestamps=phoneme_timestamps,
    )


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
            voice_count = meta.get("voice_count", len(voices))
            if model_name == COSYVOICE_V35_PLUS_MODEL_ID:
                try:
                    clones, _clone_meta = list_cosyvoice_v3_plus_clones()
                    voice_count += len(clones)
                except CosyVoiceCloneError:
                    pass
            models.append({
                "id": model_name,
                "name": _get_model_display_name(model_name),
                "description": _get_model_description(model_name),
                "voice_count": voice_count,
                "price_per_10k": _get_model_price(model_name),
                "features": _get_model_features(model_name),
            })
        except Exception:
            pass
    
    return {"models": models}


def _get_model_display_name(model: str) -> str:
    names = {
        "qwen3-tts-instruct-flash": "Qwen3-TTS Instruct Flash",
        "qwen3-tts-plus": "Qwen3-TTS Plus",
        COSYVOICE_V35_PLUS_MODEL_ID: "CosyVoice v3.5 Plus",
        "minimax-speech-2.8-hd": "MiniMax Speech 2.8 HD",
        "minimax-speech-2.8-turbo": "MiniMax Speech 2.8 Turbo",
    }
    return names.get(model, model)


def _get_model_description(model: str) -> str:
    descriptions = {
        "qwen3-tts-instruct-flash": "默认模型，49音色，支持自然语言 instructions",
        "qwen3-tts-plus": "高质量，支持SSML",
        COSYVOICE_V35_PLUS_MODEL_ID: "高表现力模型，支持 instruction 与音色复刻/设计，但无系统音色",
        "minimax-speech-2.8-hd": "最高音质，语气词标签，100+音色",
        "minimax-speech-2.8-turbo": "优秀音质，高性价比，高并发",
    }
    return descriptions.get(model, "")


def _get_model_price(model: str) -> float:
    prices = {
        "qwen3-tts-instruct-flash": 1.0,
        "qwen3-tts-plus": 2.0,
        COSYVOICE_V35_PLUS_MODEL_ID: 2.0,
        "minimax-speech-2.8-hd": 6.0,
        "minimax-speech-2.8-turbo": 3.0,
    }
    return prices.get(model, 1.0)


def _get_model_features(model: str) -> list:
    features_map = {
        "qwen3-tts-instruct-flash": ["默认模型", "49音色", "自然语言指令"],
        "qwen3-tts-plus": ["高质量", "SSML支持"],
        COSYVOICE_V35_PLUS_MODEL_ID: ["高表现力", "instruction", "复刻/设计音色", "无系统音色"],
        "minimax-speech-2.8-hd": ["最高音质", "语气词标签", "100+音色", "混合音色"],
        "minimax-speech-2.8-turbo": ["优秀音质", "高性价比", "高并发"],
    }
    return features_map.get(model, [])


def _get_model_description_legacy(model: str) -> str:
    descriptions = {
        "qwen3-tts-instruct-flash": "默认模型，24音色，支持自然语言 instructions",
        "qwen3-tts-plus": "高质量，支持SSML",
        COSYVOICE_V35_PLUS_MODEL_ID: "高表现力，支持 instruction，但需先创建复刻/设计音色",
        "minimax-speech-2.8-hd": "最高音质，语气词标签，100+音色",
        "minimax-speech-2.8-turbo": "优秀音质，高性价比，高并发",
    }
    return descriptions.get(model, "")


def _get_model_features_legacy(model: str) -> list:
    features_map = {
        "qwen3-tts-instruct-flash": ["默认模型", "24音色", "自然语言指令"],
        "qwen3-tts-plus": ["高质量", "SSML支持"],
        COSYVOICE_V35_PLUS_MODEL_ID: ["高表现力", "instruction", "复刻/设计音色", "无系统音色"],
        "minimax-speech-2.8-hd": ["最高音质", "语气词标签", "100+音色", "混合音色"],
        "minimax-speech-2.8-turbo": ["优秀音质", "高性价比", "高并发"],
    }
    return features_map.get(model, [])


@router.get("/tts/voices")
async def list_tts_voices(
    model: str = DEFAULT_TTS_MODEL,
    current_user: User = Depends(get_current_user),
):
    """Expose the supported voices to the frontend (model-specific)."""
    model = normalize_model_id(model or DEFAULT_TTS_MODEL) or DEFAULT_TTS_MODEL
    if model not in SUPPORTED_TTS_MODELS:
        if model.startswith("minimax-speech"):
            model = "minimax-speech-2.8-hd"
        elif model.startswith("qwen3-tts"):
            model = DEFAULT_TTS_MODEL
        else:
            model = DEFAULT_TTS_MODEL
    catalog = load_voice_catalog_for_model(model)
    meta = catalog.get("meta") or {}
    voices = list(catalog.get("voices") or [])

    # cosyvoice-v3.5-plus：官方静态目录为空，仅追加当前账号下的复刻/设计音色。
    if model == COSYVOICE_V35_PLUS_MODEL_ID:
        try:
            clones, _clone_meta = list_cosyvoice_v3_plus_clones()
            voices.extend([c.to_voice_preset(get_clone_display_name(c.voice_id)) for c in clones])
        except CosyVoiceCloneError:
            # 未配置 API Key 等情况下，不阻塞页面继续使用其他模型
            pass
    return {
        "model": meta.get("model", DEFAULT_TTS_MODEL),
        "updated_at": meta.get("updated_at"),
        "source": meta.get("source"),
        "voice_count": len(voices),
        "voices": voices,
    }


@router.post("/tts/voices/cosyvoice-v3.5-plus/clones")
@router.post("/tts/voices/cosyvoice-v3-plus/clones", include_in_schema=False)
async def create_cosyvoice_v3_plus_voice_clone(
    request: CosyVoiceCloneCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """创建 cosyvoice-v3.5-plus 复刻音色。

    说明：DashScope 克隆接口要求 input.url 为公网可访问地址或 oss:// 临时 URL。
    """
    try:
        import hashlib
        import re
        import secrets

        display_name = (request.name or "").strip()
        if not display_name:
            raise CosyVoiceCloneError("name 不能为空")

        prefix = (request.prefix or "").strip() or _build_cosyvoice_voice_prefix(display_name, current_user)
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


@router.post("/tts/voices/cosyvoice-v3.5-plus/designs")
async def create_cosyvoice_v3_plus_voice_design(
    request: CosyVoiceDesignCreateRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        display_name = (request.name or "").strip()
        if not display_name:
            raise CosyVoiceCloneError("name 不能为空")

        prefix = (request.prefix or "").strip() or _build_cosyvoice_voice_prefix(display_name, current_user)
        result = create_cosyvoice_v3_plus_design(
            prefix=prefix,
            voice_prompt=request.voice_prompt,
            preview_text=request.preview_text,
            sample_rate=int(request.sample_rate or 24000),
            response_format=str(request.response_format or "wav"),
        )
        save_clone_display_name(voice_id=result.get("voice_id", ""), display_name=display_name)
        result["display_name"] = display_name
        return result
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/cosyvoice-v3.5-plus/clones/upload")
@router.post("/tts/voices/cosyvoice-v3-plus/clones/upload", include_in_schema=False)
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


@router.get("/tts/voices/cosyvoice-v3.5-plus/clones")
@router.get("/tts/voices/cosyvoice-v3-plus/clones", include_in_schema=False)
async def list_cosyvoice_v3_plus_voice_clones(
    prefix: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """列出 cosyvoice-v3.5-plus 的复刻音色（当前 API Key 维度）。"""
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
                    "custom_type": c.custom_type,
                    "voice_prompt": c.voice_prompt,
                    "preview_text": c.preview_text,
                    "preview_audio": c.preview_audio,
                    "display_name": get_clone_display_name(c.voice_id),
                }
                for c in clones
            ],
        }
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/tts/voices/cosyvoice-v3.5-plus/clones/{voice_id}")
@router.delete("/tts/voices/cosyvoice-v3-plus/clones/{voice_id}", include_in_schema=False)
async def delete_cosyvoice_v3_plus_voice_clone(
    voice_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除 cosyvoice-v3.5-plus 复刻音色。"""
    try:
        return delete_cosyvoice_clone(voice_id=voice_id)
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ==================== API Endpoints ====================
