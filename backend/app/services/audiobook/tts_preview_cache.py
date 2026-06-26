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

logger = logging.getLogger(__name__)

_OSS_SUBDIR = "tts_preview"
_CACHE_SCHEMA_VERSION = "tts-preview-cache-v2"


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
        "model": str(model or "").strip(),
        "text": str(text or "").strip(),
    }
    if voice_params is not None:
        payload["voice_params"] = _normalize_preview_cache_value(voice_params)
    else:
        payload["voice_params"] = _normalize_preview_cache_value(
            {
                "speaker": str(voice_id or "").strip(),
                "volume": int(volume),
                "speed": round(float(speed), 6),
                "pitch": int(pitch),
                "emotion": str(emotion or "neutral").strip().lower(),
                "voice_type": str(voice_type or "").strip(),
                "mimo_voice_asset_id": str(mimo_voice_asset_id or "").strip(),
                "stepaudio_voice_asset_id": str(stepaudio_voice_asset_id or "").strip(),
            }
        )
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    "check_oss_preview_exists",
    "upload_preview_to_oss",
]
