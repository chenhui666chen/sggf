from __future__ import annotations

import base64
import logging
from typing import Optional

from fastapi import Depends, File, HTTPException, Response, UploadFile, status

from app.core.security import get_current_user
from app.models.user import User
from app.schemas.audiobook import (
    TTSPreviewRequest,
    TTSPreviewWithTimestampsRequest,
    TTSPreviewWithTimestampsResponse,
    CosyVoiceCloneCreateRequest,
    CosyVoiceDesignCreateRequest,
)
from app.services.audiobook.constants import normalize_speaker_id
from app.services.audiobook.tts_engine import RetryConfig
from app.services.audiobook.tts_model_ids import (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    get_audiobook_tts_runtime_model_id,
    get_audiobook_tts_model_metadata,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.voice_manager import VoiceManager
from app.services.audiobook.voice_catalog import get_voice_entry, load_voice_catalog_for_model
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
        except CosyVoiceCloneError:
            pass
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
