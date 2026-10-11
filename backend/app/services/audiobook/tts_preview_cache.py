"""TTS 试听云端缓存服务 (OSS HEAD 方案，无 Redis 依赖)。

通过确定性 cache_key 构建 OSS object_key，用 HEAD 请求检查文件是否存在。
命中 → 返回 CDN URL → 前端 302 重定向播放。
未命中 → TTS 合成 → 上传 OSS → 返回 CDN URL。

仅当云端存储已配置时启用，否则降级为原有行为。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from app.services.audiobook.tts_model_ids import model_uses_basic_numeric_speed_control
from app.services.audiobook.voice_identity_policy import (
    VOICE_IDENTITY_POLICY_VERSION,
    is_voice_design_creation_request,
)

logger = logging.getLogger(__name__)

_OSS_SUBDIR = "tts_preview"
_CACHE_SCHEMA_VERSION = "tts-preview-cache-v4"


def _normalize_preview_cache_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_preview_cache_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_preview_cache_value(item) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _build_preview_cache_key(
    *,
    model: str,
    voice_id: str,
    text: str,
    volume: int = 50,
    speed: float = 1.0,
    pitch: int = 50,
    emotion: str = "neutral",
    voice_type: str = "",
    mimo_voice_asset_id: str = "",
    stepaudio_voice_asset_id: str = "",
    voice_params: Optional[dict[str, Any]] = None,
) -> str:
    """根据试听参数构建缓存键 (SHA256)。"""
    payload = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION,
        "model": str(model or "").strip(),
        "text": str(text or "").strip(),
    }
    if voice_params is not None:
        payload["voice_params"] = _normalize_preview_cache_value(voice_params)
    else:
        fallback_voice_params = {
            "speaker": str(voice_id or "").strip(),
            "volume": int(volume),
            "emotion": str(emotion or "neutral").strip().lower(),
            "voice_type": str(voice_type or "").strip(),
            "mimo_voice_asset_id": str(mimo_voice_asset_id or "").strip(),
            "stepaudio_voice_asset_id": str(stepaudio_voice_asset_id or "").strip(),
        }
        if model_uses_basic_numeric_speed_control(model):
            fallback_voice_params["speed"] = round(float(speed), 6)
        if is_voice_design_creation_request(model, fallback_voice_params):
            fallback_voice_params["pitch"] = int(pitch)
        payload["voice_params"] = _normalize_preview_cache_value(fallback_voice_params)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_default_preview_cache_key(*, model: str, voice_id: str) -> str:
    """Build the cache key used by the character voice preview control."""
    from app.services.audiobook.constants import normalize_speaker_id
    from app.services.audiobook.tts_model_ids import (
        DEFAULT_AUDIOBOOK_TTS_MODEL,
        normalize_audiobook_tts_model,
    )
    from app.services.audiobook.voice_catalog import (
        get_preview_quote_for_voice,
        get_voice_entry,
    )
    from app.services.audiobook.voice_manager import VoiceManager

    normalized_model = normalize_audiobook_tts_model(
        model or DEFAULT_AUDIOBOOK_TTS_MODEL,
    )
    normalized_voice_id = str(voice_id or "").strip()
    if not normalized_voice_id:
        raise ValueError("voice_id is required to resolve a preview cache key")

    entry = get_voice_entry(normalized_voice_id, model=normalized_model)
    if entry is None and normalized_model == DEFAULT_AUDIOBOOK_TTS_MODEL:
        # 目录未命中：兼容历史别名（male_narrator 等）与旧 CosyVoice speaker 写法。
        preset = VoiceManager.PRESET_VOICES.get(normalized_voice_id)
        speaker_id = normalize_speaker_id(
            preset["tts_speaker_id"] if preset else normalized_voice_id
        )
    else:
        speaker_id = str(entry.get("speaker") if entry else normalized_voice_id)

    voice_params = {
        "speaker": speaker_id,
        "volume": 50,
        "voice_id": normalized_voice_id,
    }
    return _build_preview_cache_key(
        model=normalized_model,
        voice_id=speaker_id,
        text=get_preview_quote_for_voice(normalized_model, normalized_voice_id),
        volume=50,
        speed=1.0,
        pitch=50,
        emotion="neutral",
        voice_type="",
        mimo_voice_asset_id="",
        stepaudio_voice_asset_id="",
        voice_params=voice_params,
    )


def _build_preview_object_key(cache_key: str, ext: str) -> str:
    """构建 OSS object_key: {prefix}/tts_preview/{前两位}/{hash}.{ext}"""
    prefix = str(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX") or "shared/audio_library").strip().strip("/")
    if not prefix:
        prefix = "shared/audio_library"
    bucket_dir = cache_key[:2]
    return f"{prefix}/{_OSS_SUBDIR}/{bucket_dir}/{cache_key}.{ext}"


def _build_public_url_from_object_key(object_key: str) -> str:
    """从 object_key 构建 CDN public URL。"""
    from app.services.audiobook.audio_asset_cloud_storage import build_audio_library_public_url

    return build_audio_library_public_url(
        object_key=object_key,
        storage_driver="aliyun_oss",
    )


def check_oss_preview_exists(cache_key: str, ext: str = "mp3") -> Optional[str]:
    """检查 OSS 中是否已存在试听文件。

    命中 → 返回 public_url；未命中或检查失败 → 返回 None。
    """
    from app.services.audiobook.audio_asset_cloud_storage import (
        get_audio_library_storage_driver,
        is_audio_library_cloud_storage_enabled,
    )

    if not is_audio_library_cloud_storage_enabled():
        return None

    driver = get_audio_library_storage_driver()
    if driver != "aliyun_oss":
        # dashscope_oss 无法做 HEAD 检查，跳过
        return None

    object_key = _build_preview_object_key(cache_key, ext)
    try:
        from app.services.audiobook.audio_asset_cloud_storage import head_audio_library_object

        result = head_audio_library_object(object_key=object_key)
        if result.get("exists"):
            public_url = _build_public_url_from_object_key(object_key)
            if public_url:
                logger.debug("TTS 试听 OSS 命中: %s", cache_key[:12])
                return public_url
    except Exception as exc:
        logger.debug("TTS 试听 OSS HEAD 检查失败 (视为未命中): %s", exc)

    return None


def upload_preview_to_oss(
    *,
    audio_bytes: bytes,
    cache_key: str,
    response_format: str = "mp3",
) -> Optional[str]:
    """将试听音频上传到 OSS。

    Returns:
        成功返回 public_url；云端未配置或上传失败时返回 None。
    """
    from app.services.audiobook.audio_asset_cloud_storage import (
        is_audio_library_cloud_storage_enabled,
        get_audio_library_storage_driver,
    )

    if not is_audio_library_cloud_storage_enabled():
        return None

    ext = "wav" if response_format == "wav" else "mp3"
    object_key = _build_preview_object_key(cache_key, ext)

    tmp_file: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
            f.write(audio_bytes)
            tmp_file = Path(f.name)

        driver = get_audio_library_storage_driver()
        if driver == "aliyun_oss":
            from app.services.audiobook.audio_asset_cloud_storage import _upload_to_aliyun_oss
            public_url = _upload_to_aliyun_oss(local_path=tmp_file, object_key=object_key)
        elif driver == "dashscope_oss":
            from app.services.audiobook.audio_asset_cloud_storage import _upload_to_dashscope_oss
            public_url = _upload_to_dashscope_oss(local_path=tmp_file, object_key=object_key)
        else:
            return None

        logger.info("TTS 试听已上传 OSS: %s (%d bytes)", cache_key[:12], len(audio_bytes))
        return public_url

    except Exception as exc:
        logger.warning("TTS 试听 OSS 上传失败: %s", exc)
        return None
    finally:
        if tmp_file and tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass


__all__ = [
    "_build_preview_cache_key",
    "build_default_preview_cache_key",
    "check_oss_preview_exists",
    "upload_preview_to_oss",
]
