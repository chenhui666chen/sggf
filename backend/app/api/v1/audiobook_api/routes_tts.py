from __future__ import annotations

import base64
import logging
from typing import Optional

from fastapi import Depends, File, Form, HTTPException, Response, UploadFile, status

from app.core.security import get_current_user
from app.models.user import User
from app.schemas.audiobook import (
    TTSPreviewRequest,
    TTSPreviewWithTimestampsRequest,
    TTSPreviewWithTimestampsResponse,
    CosyVoiceCloneCreateRequest,
    CosyVoiceDesignCreateRequest,
    MiMoVoiceCloneAssetCreateRequest,
    MiMoVoiceDesignAssetCreateRequest,
    StepAudioVoiceCloneAssetCreateRequest,
)
from app.services.audiobook.constants import normalize_speaker_id
from app.services.audiobook.tts_engine import RetryConfig, TTSUserInputError
from app.services.audiobook.tts_model_ids import (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    STEPAUDIO_25_TTS_MODEL,
    get_audiobook_tts_runtime_model_id,
    get_audiobook_tts_model_metadata,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.voice_types import apply_voice_type_to_tts_params
from app.services.audiobook.voice_manager import VoiceManager
from app.services.audiobook.voice_catalog import get_preview_quote_for_voice, get_voice_entry, load_voice_catalog_for_model
from app.services.audiobook.mimo_voice_assets import (
    MiMoVoiceAssetError,
    MiMoVoiceAssetStore,
    list_mimo_voice_asset_presets,
    merge_mimo_voice_asset_tts_params,
)
from app.services.audiobook.stepaudio_voice_assets import (
    StepAudioVoiceAssetError,
    StepAudioVoiceAssetStore,
    get_stepaudio_api_key,
    list_stepaudio_voice_asset_presets,
    merge_stepaudio_voice_asset_tts_params,
    upload_stepaudio_voice_reference_file,
    validate_stepaudio_clone_audio_mime_type,
)
from app.services.audiobook.tts_preview_cache import (
    _build_preview_cache_key,
    check_oss_preview_exists,
    upload_preview_to_oss,
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
from core.unified_media_runtime import (
    create_tts_engine as runtime_create_tts_engine,
    get_media_runtime,
    synthesize_speech as runtime_synthesize_speech,
)

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

DEFAULT_TTS_MODEL = DEFAULT_AUDIOBOOK_TTS_MODEL
DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT = "当你真的喜欢一个人的时候就容易说傻话办蠢事。"
DEFAULT_STEPAUDIO_CLONE_PREVIEW_INSTRUCTION = "语气自然，语速中等，保持参考音色特征。"

_PREVIEW_RETRY_CONFIG = RetryConfig(
    max_retries=4,
    base_delay=1.0,
    max_delay=8.0,
    exponential_base=2.0,
    jitter=True,
)


def _is_cosyvoice_v35_model(model: str) -> bool:
    return normalize_audiobook_tts_model(model) == COSYVOICE_V35_PLUS_MODEL_ID


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


def _build_model_voice_catalog_status(model_name: str) -> tuple[int, str, str | None]:
    model_meta = get_audiobook_tts_model_metadata(model_name)
    capabilities = model_meta.get("capabilities") if isinstance(model_meta.get("capabilities"), dict) else {}
    if not capabilities.get("has_system_voices", True):
        return 0, "not_applicable", None

    try:
        catalog = load_voice_catalog_for_model(model_name)
    except Exception as exc:
        logger.warning("加载 TTS 模型音色目录失败: model=%s error=%s", model_name, exc)
        return 0, "unavailable", "音色目录加载失败，请检查后端 voice catalog 配置"

    voices = catalog.get("voices", [])
    meta = catalog.get("meta", {})
    raw_voice_count = meta.get("voice_count")
    voice_count = raw_voice_count if isinstance(raw_voice_count, int) and raw_voice_count >= 0 else len(voices)
    if model_name == COSYVOICE_V35_PLUS_MODEL_ID:
        try:
            clones, _clone_meta = list_cosyvoice_v3_plus_clones()
            voice_count += len(clones)
        except CosyVoiceCloneError as exc:
            logger.info(
                "CosyVoice 自定义音色列表不可用，模型音色计数仅使用静态目录: model=%s error=%s",
                model_name,
                exc,
            )
    return voice_count, "ready", None


def _build_model_runtime_status(model_name: str) -> tuple[str, str, str | None]:
    runtime_model_id = get_audiobook_tts_runtime_model_id(model_name)
    if not runtime_model_id:
        return "", "unavailable", "TTS 运行时模型未配置"

    try:
        spec = get_media_runtime().select_model(
            operation="synthesize_speech",
            modality="text_to_speech",
            preferred_model=runtime_model_id,
        )
    except Exception as exc:
        logger.warning("TTS 运行时模型不可用: model=%s runtime_model=%s error=%s", model_name, runtime_model_id, exc)
        return runtime_model_id, "unavailable", "TTS 运行时模型未注册或不可用"

    if spec.id != runtime_model_id:
        logger.warning(
            "TTS 运行时模型被重路由: model=%s runtime_model=%s selected=%s",
            model_name,
            runtime_model_id,
            spec.id,
        )
        return runtime_model_id, "unavailable", f"TTS 运行时模型当前不可直用，已被路由到 {spec.id}"

    return runtime_model_id, "ready", None


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
    digest = hashlib.sha256(f"{user_id}:{cleaned_name}".encode("utf-8")).hexdigest()[:6]
    suffix = secrets.token_hex(1)
    return f"{base}{digest}{suffix}"[:10]


def _require_stepaudio_clone_sample_text(sample_text: str) -> str:
    clean_sample_text = str(sample_text or "").strip()
    if not clean_sample_text:
        raise StepAudioVoiceAssetError(
            "sample_text cannot be empty; it must match the exact spoken content in the reference audio"
        )
    return clean_sample_text


async def _resolve_stepaudio_clone_file_id(
    *,
    file_id: str,
    filename: str,
    content: bytes,
    mime_type: str,
) -> str:
    resolved_file_id = str(file_id or "").strip()
    if resolved_file_id:
        return resolved_file_id

    stepaudio_api_key = get_stepaudio_api_key()
    if not stepaudio_api_key:
        raise StepAudioVoiceAssetError(
            "STEP_API_KEY or STEPFUN_API_KEY is required before StepAudio clone preview or save"
        )
    return await upload_stepaudio_voice_reference_file(
        filename=filename or "stepaudio-reference.wav",
        content=content,
        mime_type=mime_type,
        api_key=stepaudio_api_key,
    )


def _resolve_preview_text(request: TTSPreviewRequest, model_name: str) -> str:
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文本不能为空")
    if len(text) > 200:
        text = text[:200]
    # 当用户传入默认试听文本时，按音色从名言列表选取对应文本，保证与 warmup 缓存键一致
    if text == DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT:
        text = get_preview_quote_for_voice(model_name, request.voice_id)
    return text


def _resolve_preview_model_name(request: TTSPreviewRequest) -> str:
    return normalize_audiobook_tts_model(request.model or DEFAULT_TTS_MODEL)


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
    base_params = {
        "volume": request.volume,
        "speed": request.speed,
        "pitch": request.pitch,
    }
    voice_type = str(request.voice_type or "").strip()
    if voice_type:
        base_params = apply_voice_type_to_tts_params(
            voice_type,
            {
                "volume": request.volume,
                "speed": request.speed if request.speed is not None else 1.0,
                "pitch": request.pitch if request.pitch is not None else 50,
            },
        )

    voice_params: dict = {
        "speaker": speaker_id,
        "volume": base_params.get("volume"),
    }
    if base_params.get("speed") is not None:
        voice_params["rate"] = base_params["speed"]
        voice_params["speed"] = base_params["speed"]
    if base_params.get("pitch") is not None:
        voice_params["pitch"] = base_params["pitch"]
    if base_params.get("emotion"):
        voice_params["emotion"] = base_params["emotion"]

    instruction = str(getattr(request, "instruction", "") or "").strip()
    if instruction:
        voice_params["instruction"] = instruction

    voice_clone_data_url = str(getattr(request, "voice_clone_data_url", "") or "").strip()
    if voice_clone_data_url:
        voice_params["voice_clone_data_url"] = voice_clone_data_url

    voice_design_prompt = str(getattr(request, "voice_design_prompt", "") or "").strip()
    if voice_design_prompt:
        voice_params["voice_design_prompt"] = voice_design_prompt

    mimo_voice_asset_id = str(getattr(request, "mimo_voice_asset_id", "") or "").strip()
    if mimo_voice_asset_id:
        voice_params["mimo_voice_asset_id"] = mimo_voice_asset_id
        try:
            voice_params = merge_mimo_voice_asset_tts_params(voice_params)
        except MiMoVoiceAssetError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    stepaudio_voice_asset_id = str(getattr(request, "stepaudio_voice_asset_id", "") or "").strip()
    if stepaudio_voice_asset_id:
        voice_params["stepaudio_voice_asset_id"] = stepaudio_voice_asset_id
        try:
            voice_params = merge_stepaudio_voice_asset_tts_params(voice_params)
        except StepAudioVoiceAssetError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if getattr(request, "word_timestamp_enabled", False):
        voice_params["word_timestamp_enabled"] = True
    if getattr(request, "phoneme_timestamp_enabled", False):
        voice_params["phoneme_timestamp_enabled"] = True

    return voice_params


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
    emotion = str(voice_params.get("emotion") or "neutral")
    payload = await engine.synthesize_with_metadata(text, voice_params, emotion)
    if not isinstance(payload, dict):
        raise RuntimeError("TTS 试听未返回有效 payload")
    return payload


@router.post("/tts/preview")
async def tts_preview(
    request: TTSPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """合成一小段音频用于前端试听"""
    model_name = _resolve_preview_model_name(request)
    text = _resolve_preview_text(request, model_name)
    preview_retry = _PREVIEW_RETRY_CONFIG
    speaker_id = _resolve_preview_speaker_id(request, model_name)
    voice_params = _build_preview_voice_params(request, speaker_id)

    try:
        audio_bytes = await runtime_synthesize_speech(
            text=text,
            voice_params=voice_params,
            emotion=str(voice_params.get("emotion") or "neutral"),
            model_id=model_name,
            enable_cache=False,
            max_concurrent=1,
            request_delay=0.0,
            retry_config=preview_retry,
        )
    except TTSUserInputError as exc:
        logger.info("TTS试听输入参数无效: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "code": getattr(exc, "code", "tts_user_input_error"), "retryable": False},
        ) from exc
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


@router.post("/tts/preview-cached")
async def tts_preview_cached(
    request: TTSPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """试听接口 (带云端 OSS 缓存，无 Redis 依赖)。

    缓存命中 → 302 重定向到 CDN URL。
    缓存未命中 → TTS 合成 → 上传 OSS → 302 重定向。
    云端未配置 → 降级返回原始音频 blob。
    """
    model_name = _resolve_preview_model_name(request)
    text = _resolve_preview_text(request, model_name)
    speaker_id = _resolve_preview_speaker_id(request, model_name)
    voice_params = _build_preview_voice_params(request, speaker_id)

    # 构建缓存键
    cache_key = _build_preview_cache_key(
        model=model_name,
        voice_id=speaker_id,
        text=text,
        volume=int(request.volume),
        speed=float(request.speed or 1.0),
        pitch=int(request.pitch or 50),
        emotion=str(voice_params.get("emotion") or "neutral"),
        voice_type=str(request.voice_type or ""),
        mimo_voice_asset_id=str(getattr(request, "mimo_voice_asset_id", "") or ""),
        stepaudio_voice_asset_id=str(getattr(request, "stepaudio_voice_asset_id", "") or ""),
        voice_params=voice_params,
    )

    # 检查 OSS 是否已有缓存文件
    cached_url = check_oss_preview_exists(cache_key, ext="mp3")
    cached_format = "mp3"
    if not cached_url:
        cached_url = check_oss_preview_exists(cache_key, ext="wav")
        cached_format = "wav"
    if cached_url:
        logger.info("TTS 试听 OSS 缓存命中: %s", cache_key[:12])
        return {
            "audio_url": cached_url,
            "blob": None,
            "cache_hit": True,
            "storage": "oss",
            "response_format": cached_format,
        }

    # 未命中: TTS 合成
    preview_retry = _PREVIEW_RETRY_CONFIG
    try:
        audio_bytes = await runtime_synthesize_speech(
            text=text,
            voice_params=voice_params,
            emotion=str(voice_params.get("emotion") or "neutral"),
            model_id=model_name,
            enable_cache=False,
            max_concurrent=1,
            request_delay=0.0,
            retry_config=preview_retry,
        )
    except TTSUserInputError as exc:
        logger.info("TTS试听输入参数无效: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "code": getattr(exc, "code", "tts_user_input_error"), "retryable": False},
        ) from exc
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

    response_format = "wav" if audio_bytes.startswith(b"RIFF") else "mp3"
    cloud_url = upload_preview_to_oss(
        audio_bytes=audio_bytes,
        cache_key=cache_key,
        response_format=response_format,
    )

    if cloud_url:
        return {
            "audio_url": cloud_url,
            "blob": None,
            "cache_hit": False,
            "storage": "oss",
            "response_format": response_format,
        }

    # 云端未配置
    return {
        "audio_url": None,
        "blob": base64.b64encode(audio_bytes).decode("utf-8"),
        "cache_hit": False,
        "storage": "blob",
        "response_format": response_format,
    }


@router.post("/tts/preview-with-timestamps", response_model=TTSPreviewWithTimestampsResponse)
async def tts_preview_with_timestamps(
    request: TTSPreviewWithTimestampsRequest,
    current_user: User = Depends(get_current_user),
):
    """合成短音频并返回可消费的词级时间戳。当前仅支持 CosyVoice v3.5 Plus。"""
    model_name = _resolve_preview_model_name(request)
    text = _resolve_preview_text(request, model_name)
    if not _is_cosyvoice_v35_model(model_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前时间戳试听接口仅支持 cosyvoice-v3.5-plus",
        )

    preview_retry = _PREVIEW_RETRY_CONFIG
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
    from app.services.audiobook.voice_manager_factory import list_all_models
    
    models = []
    for model_name in list_all_models():
        model_meta = get_audiobook_tts_model_metadata(model_name)
        voice_count, catalog_status, catalog_error = _build_model_voice_catalog_status(model_name)
        runtime_model_id, runtime_status, runtime_error = _build_model_runtime_status(model_name)
        models.append({
            "id": model_name,
            "name": _get_model_display_name(model_name),
            "description": _get_model_description(model_name, voice_count),
            "voice_count": voice_count,
            "price_per_10k": _get_model_price(model_name),
            "features": _get_model_features(model_name, voice_count),
            "cost_level": model_meta.get("cost_level"),
            "quality_level": model_meta.get("quality_level"),
            "catalog_note": model_meta.get("catalog_note"),
            "capabilities": model_meta.get("capabilities") or {},
            "catalog_status": catalog_status,
            "catalog_error": catalog_error,
            "runtime_model_id": runtime_model_id,
            "runtime_status": runtime_status,
            "runtime_error": runtime_error,
        })
    
    return {"models": models}


def _get_model_display_name(model: str) -> str:
    return str(get_audiobook_tts_model_metadata(model).get("name") or model)


def _get_model_description(model: str, voice_count: int = 0) -> str:
    template = str(get_audiobook_tts_model_metadata(model).get("description") or "")
    return template.format(voice_count=voice_count) if template else ""


def _get_model_price(model: str) -> float:
    try:
        return float(get_audiobook_tts_model_metadata(model).get("price_per_10k", 1.0))
    except (TypeError, ValueError):
        return 1.0


def _get_model_features(model: str, voice_count: int = 0) -> list:
    raw_features = get_audiobook_tts_model_metadata(model).get("features") or []
    return [str(feature).format(voice_count=voice_count) for feature in raw_features]


@router.get("/tts/voices")
async def list_tts_voices(
    model: str = DEFAULT_TTS_MODEL,
    current_user: User = Depends(get_current_user),
):
    """Expose the supported voices to the frontend (model-specific)."""
    model = normalize_audiobook_tts_model(model or DEFAULT_TTS_MODEL)
    catalog = load_voice_catalog_for_model(model)
    meta = catalog.get("meta") or {}
    voices = list(catalog.get("voices") or [])

    # cosyvoice-v3.5-plus：官方静态目录为空，仅追加当前账号下的复刻/设计音色。
    if model == COSYVOICE_V35_PLUS_MODEL_ID:
        try:
            clones, _clone_meta = list_cosyvoice_v3_plus_clones()
            voices.extend([c.to_voice_preset(get_clone_display_name(c.voice_id)) for c in clones])
        except CosyVoiceCloneError as exc:
            # 未配置 API Key 等情况下，不阻塞页面继续使用其他模型
            logger.info(
                "CosyVoice 自定义音色列表不可用，返回静态音色目录: model=%s error=%s",
                model,
                exc,
            )
    else:
        voices.extend(list_mimo_voice_asset_presets(model))
        voices.extend(list_stepaudio_voice_asset_presets(model))
    return {
        "model": meta.get("model", DEFAULT_TTS_MODEL),
        "updated_at": meta.get("updated_at"),
        "source": meta.get("source"),
        "voice_count": len(voices),
        "voices": voices,
    }


@router.post("/tts/voices/cosyvoice-v3.5-plus/clones")
async def create_cosyvoice_v3_plus_voice_clone(
    request: CosyVoiceCloneCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """创建 cosyvoice-v3.5-plus 复刻音色。

    说明：DashScope 克隆接口要求 input.url 为公网可访问地址或 oss:// 临时 URL。
    """
    try:
        display_name = (request.name or "").strip()
        if not display_name:
            raise CosyVoiceCloneError("name 不能为空")

        prefix = (request.prefix or "").strip() or _build_cosyvoice_voice_prefix(display_name, current_user)
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
        except Exception as exc:
            logger.debug(
                "关闭 CosyVoice 上传文件失败，已忽略清理错误: filename=%s error=%s",
                file.filename,
                exc,
            )


@router.get("/tts/voices/cosyvoice-v3.5-plus/clones")
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
async def delete_cosyvoice_v3_plus_voice_clone(
    voice_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除 cosyvoice-v3.5-plus 复刻音色。"""
    try:
        return delete_cosyvoice_clone(voice_id=voice_id)
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/tts/voices/mimo/assets")
async def list_mimo_voice_assets(
    model: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """列出 MiMo 本地可复用音色资产。"""
    del current_user
    try:
        assets = MiMoVoiceAssetStore().list_assets(model=model)
        return {
            "assets": [asset.to_dict() for asset in assets],
            "voices": [asset.to_voice_preset() for asset in assets],
            "total": len(assets),
        }
    except MiMoVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/mimo/clone-assets")
async def create_mimo_voice_clone_asset(
    request: MiMoVoiceCloneAssetCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """保存 MiMo Voice Clone 本地音频样本资产。"""
    del current_user
    try:
        asset = MiMoVoiceAssetStore().create_clone_asset(
            name=request.name,
            audio_data_url=request.audio_data_url,
            description=request.description or "",
        )
        return {"asset": asset.to_dict(), "voice": asset.to_voice_preset()}
    except MiMoVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/mimo/clone-assets/upload")
async def upload_mimo_voice_clone_asset(
    name: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传本地音频并保存为 MiMo Voice Clone 本地音色资产。"""
    del current_user
    try:
        content = await file.read()
        asset = MiMoVoiceAssetStore().create_clone_asset_from_bytes(
            name=name,
            audio_bytes=content,
            mime_type=file.content_type or "",
        )
        return {"asset": asset.to_dict(), "voice": asset.to_voice_preset()}
    except MiMoVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception as exc:
            logger.debug(
                "关闭 MiMo 上传文件失败，已忽略清理错误: filename=%s error=%s",
                file.filename,
                exc,
            )


@router.post("/tts/voices/mimo/design-assets")
async def create_mimo_voice_design_asset(
    request: MiMoVoiceDesignAssetCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """保存 MiMo Voice Design 本地声音描述资产。"""
    del current_user
    try:
        asset = MiMoVoiceAssetStore().create_design_asset(
            name=request.name,
            voice_design_prompt=request.voice_design_prompt,
            description=request.description or "",
        )
        return {"asset": asset.to_dict(), "voice": asset.to_voice_preset()}
    except MiMoVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/tts/voices/mimo/assets/{asset_id}")
async def delete_mimo_voice_asset(
    asset_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除 MiMo 本地音色资产。"""
    del current_user
    try:
        deleted = MiMoVoiceAssetStore().delete_asset(asset_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MiMo voice asset not found")
        return {"deleted": True, "asset_id": asset_id}
    except MiMoVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/tts/voices/stepaudio/assets")
async def list_stepaudio_voice_assets(
    model: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """列出 StepAudio 本地复刻参考样本资产。"""
    del current_user
    try:
        assets = StepAudioVoiceAssetStore().list_assets(model=model)
        return {
            "assets": [asset.to_dict() for asset in assets],
            "voices": [asset.to_voice_preset() for asset in assets],
            "total": len(assets),
        }
    except StepAudioVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/stepaudio/clone-assets")
async def create_stepaudio_voice_clone_asset(
    request: StepAudioVoiceCloneAssetCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """创建 StepAudio 复刻参考样本元数据资产。

    当前官方资料只给出 /audio/voices/preview 使用 file_id 的合同，未给出正式音色创建接口；
    因此该接口只保存可复用的本地参考资产元数据，不伪造正式 voice_id。
    """
    del current_user
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="StepAudio clone asset requires an uploaded mp3/wav sample; use /clone-assets/upload",
    )


@router.post("/tts/voices/stepaudio/clone-assets/preview")
async def preview_stepaudio_voice_clone_asset(
    name: str = Form(""),
    sample_text: str = Form(""),
    preview_text: str = Form(DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT),
    instruction: str = Form(DEFAULT_STEPAUDIO_CLONE_PREVIEW_INSTRUCTION),
    file_id: str = Form(""),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Preview a StepAudio Voice Clone sample before saving the local voice asset."""
    del current_user
    try:
        del name
        content = await file.read()
        validate_stepaudio_clone_audio_mime_type(file.content_type or "")
        clean_sample_text = _require_stepaudio_clone_sample_text(sample_text)
        resolved_file_id = await _resolve_stepaudio_clone_file_id(
            file_id=file_id,
            filename=file.filename or "stepaudio-reference.wav",
            content=content,
            mime_type=file.content_type or "",
        )
        stepaudio_api_key = get_stepaudio_api_key()
        if not stepaudio_api_key:
            raise StepAudioVoiceAssetError(
                "STEP_API_KEY or STEPFUN_API_KEY is required before StepAudio clone preview"
            )

        engine = runtime_create_tts_engine(
            model_id=STEPAUDIO_25_TTS_MODEL,
            strategy="balanced",
            enable_cache=False,
            max_concurrent=1,
            request_delay=0.0,
            retry_config=_PREVIEW_RETRY_CONFIG,
        )
        audio_bytes = await engine._call_stepaudio_voice_preview_http(
            model=STEPAUDIO_25_TTS_MODEL,
            api_key=stepaudio_api_key,
            text=(str(preview_text or "").strip() or DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT),
            file_id=resolved_file_id,
            sample_text=clean_sample_text,
            instruction=str(instruction or "").strip() or DEFAULT_STEPAUDIO_CLONE_PREVIEW_INSTRUCTION,
        )
        audio_mime_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
        audio_format = "wav" if audio_mime_type == "audio/wav" else "mp3"
        return {
            "file_id": resolved_file_id,
            "sample_text": clean_sample_text,
            "preview_text": str(preview_text or "").strip() or DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT,
            "instruction": str(instruction or "").strip() or DEFAULT_STEPAUDIO_CLONE_PREVIEW_INSTRUCTION,
            "audio_data_base64": base64.b64encode(audio_bytes).decode("utf-8"),
            "audio_mime_type": audio_mime_type,
            "audio_format": audio_format,
            "audio_size_bytes": len(audio_bytes),
            "billing_notice": "StepAudio preview only returns audio; confirm save only after you accept the result.",
        }
    except TTSUserInputError as exc:
        logger.info("StepAudio 复刻预试听输入参数无效: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "code": getattr(exc, "code", "tts_user_input_error"), "retryable": False},
        ) from exc
    except StepAudioVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception as exc:
            logger.debug(
                "关闭 StepAudio 预试听上传文件失败，已忽略清理错误: filename=%s error=%s",
                file.filename,
                exc,
            )


@router.post("/tts/voices/stepaudio/clone-assets/upload")
async def upload_stepaudio_voice_clone_asset(
    name: str = Form(...),
    sample_text: str = Form(""),
    file_id: str = Form(""),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传本地音频并保存为 StepAudio Voice Clone 参考样本资产。"""
    del current_user
    try:
        content = await file.read()
        validate_stepaudio_clone_audio_mime_type(file.content_type or "")
        clean_sample_text = _require_stepaudio_clone_sample_text(sample_text)
        resolved_file_id = await _resolve_stepaudio_clone_file_id(
            file_id=file_id,
            filename=file.filename or "stepaudio-reference.wav",
            content=content,
            mime_type=file.content_type or "",
        )
        asset = StepAudioVoiceAssetStore().create_clone_asset_from_bytes(
            name=name,
            audio_bytes=content,
            mime_type=file.content_type or "",
            sample_text=clean_sample_text,
            file_id=resolved_file_id,
        )
        return {"asset": asset.to_dict(), "voice": asset.to_voice_preset()}
    except StepAudioVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception as exc:
            logger.debug(
                "关闭 StepAudio 上传文件失败，已忽略清理错误: filename=%s error=%s",
                file.filename,
                exc,
            )


@router.delete("/tts/voices/stepaudio/assets/{asset_id}")
async def delete_stepaudio_voice_asset(
    asset_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除 StepAudio 本地复刻参考样本资产。"""
    del current_user
    try:
        deleted = StepAudioVoiceAssetStore().delete_asset(asset_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="StepAudio voice asset not found")
        return {"deleted": True, "asset_id": asset_id}
    except StepAudioVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ==================== API Endpoints ====================
