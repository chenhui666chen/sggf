from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


_COSYVOICE_V3_PLUS_VOICE_ID_PREFIX = "cosyvoice-v3-plus-"
_DEFAULT_CACHE_TTL_SECONDS = 30.0
_PREFIX_MAX_LEN = 10


class CosyVoiceCloneError(RuntimeError):
    pass


def _require_dashscope_api_key() -> str:
    api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        raise CosyVoiceCloneError("未配置 DASHSCOPE_API_KEY")
    return api_key


def _resolve_clone_name_store_path() -> Path:
    """Resolve a writable JSON file to persist voice_id -> display_name mapping."""
    current = Path(__file__).resolve()
    for ancestor in current.parents:
        backend_data = ancestor / "backend" / "data"
        if backend_data.exists():
            return backend_data / "cosyvoice_clone_names.json"
    # Fallback: relative to backend/app/services/audiobook
    return current.parents[3] / "data" / "cosyvoice_clone_names.json"


def _load_clone_name_store() -> Dict[str, str]:
    path = _resolve_clone_name_store_path()
    try:
        if not path.exists():
            return {}
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if k and v}
    except Exception:
        return {}
    return {}


def _save_clone_name_store(mapping: Dict[str, str]) -> None:
    path = _resolve_clone_name_store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # 不阻塞主流程；映射丢失只会影响 UI 展示
        return


def save_clone_display_name(*, voice_id: str, display_name: str) -> None:
    voice_id = (voice_id or "").strip()
    display_name = (display_name or "").strip()
    if not voice_id or not display_name:
        return
    mapping = _load_clone_name_store()
    mapping[voice_id] = display_name[:50]
    _save_clone_name_store(mapping)


def get_clone_display_name(voice_id: str) -> Optional[str]:
    voice_id = (voice_id or "").strip()
    if not voice_id:
        return None
    mapping = _load_clone_name_store()
    value = mapping.get(voice_id)
    return str(value).strip() if value else None


def _extract_prefix_from_voice_id(voice_id: str) -> str:
    voice_id = (voice_id or "").strip()
    if not voice_id.startswith(_COSYVOICE_V3_PLUS_VOICE_ID_PREFIX):
        return ""
    # cosyvoice-v3-plus-{prefix}-{random}
    tail = voice_id[len(_COSYVOICE_V3_PLUS_VOICE_ID_PREFIX) :]
    parts = tail.split("-")
    if len(parts) >= 2:
        return parts[0]
    return tail


def _build_clone_voice_preset(
    voice_id: str,
    status: str,
    gmt_create: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    prefix = _extract_prefix_from_voice_id(voice_id) or "clone"
    display_name = (display_name or "").strip()
    status_label = (status or "").strip() or "UNKNOWN"
    desc_parts = [f"复刻音色（状态: {status_label}）"]
    if gmt_create:
        desc_parts.append(f"创建时间: {gmt_create}")
    description = "；".join(desc_parts)
    return {
        "id": voice_id,
        "speaker": voice_id,
        "label": f"复刻-{display_name}" if display_name else f"复刻-{prefix}",
        "category": "custom",
        "description": description,
        "supportsInstruct": True,
    }


@dataclass(frozen=True)
class CosyVoiceClone:
    voice_id: str
    status: str
    gmt_create: Optional[str] = None
    gmt_modified: Optional[str] = None

    def to_voice_preset(self, display_name: Optional[str] = None) -> Dict[str, Any]:
        return _build_clone_voice_preset(self.voice_id, self.status, self.gmt_create, display_name)


class _CloneListCache:
    def __init__(self) -> None:
        self.expires_at: float = 0.0
        self.value: List[CosyVoiceClone] = []

    def get(self) -> Optional[List[CosyVoiceClone]]:
        now = time.time()
        if now < self.expires_at:
            return list(self.value)
        return None

    def set(self, value: List[CosyVoiceClone], ttl_seconds: float) -> None:
        self.value = list(value)
        self.expires_at = time.time() + float(max(0.0, ttl_seconds))

    def invalidate(self) -> None:
        self.expires_at = 0.0
        self.value = []


_CLONE_LIST_CACHE = _CloneListCache()


def invalidate_cosyvoice_clone_cache() -> None:
    _CLONE_LIST_CACHE.invalidate()


def create_cosyvoice_v3_plus_clone(*, prefix: str, audio_url: str) -> Dict[str, Any]:
    """创建 cosyvoice-v3-plus 复刻音色。

    说明：
    - DashScope 的克隆接口要求 input.url 为公网可访问地址。
    - 返回 voice_id 后，可能需要等待 status 变为 OK 才可用于合成。
    """
    prefix = (prefix or "").strip()
    audio_url = (audio_url or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,10}", prefix):
        raise CosyVoiceCloneError("prefix 仅支持大小写英文字母、数字和下划线，长度 1~10")
    if not (audio_url.startswith("http://") or audio_url.startswith("https://")):
        raise CosyVoiceCloneError("url 必须是 http/https 的公网可访问地址")

    api_key = _require_dashscope_api_key()

    try:
        from dashscope.audio.tts_v2 import VoiceEnrollmentService
    except Exception as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"dashscope 版本不支持 VoiceEnrollmentService（tts_v2）: {exc}") from exc

    service = VoiceEnrollmentService(api_key=api_key)
    try:
        voice_id = str(
            service.create_voice(
                target_model="cosyvoice-v3-plus",
                prefix=prefix,
                url=audio_url,
            )
        ).strip()
    except Exception as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"create_voice 失败: {exc}") from exc

    if not voice_id:
        raise CosyVoiceCloneError("create_voice 返回 voice_id 为空")

    invalidate_cosyvoice_clone_cache()
    return {
        "voice_id": voice_id,
        # SDK create_voice 仅返回 voice_id；状态需通过 list_voices 查询
        "status": "DEPLOYING",
    }


def list_cosyvoice_v3_plus_clones(
    *,
    prefix: Optional[str] = None,
    page_index: int = 1,
    page_size: int = 50,
    cache_ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
) -> Tuple[List[CosyVoiceClone], Dict[str, Any]]:
    """列出 cosyvoice-v3-plus 的复刻音色（按当前 API Key 下的 voice_id 过滤）。"""
    prefix = (prefix or "").strip() or None

    if prefix and not re.fullmatch(r"[A-Za-z0-9_]{1,10}", prefix):
        raise CosyVoiceCloneError("prefix 仅支持大小写英文字母、数字和下划线，长度 1~10")

    cached = _CLONE_LIST_CACHE.get()
    if cached is not None and not prefix and int(page_index) == 1 and int(page_size) == 50:
        return cached, {"cached": True}

    api_key = _require_dashscope_api_key()

    try:
        from dashscope.audio.tts_v2 import VoiceEnrollmentService
    except Exception as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"dashscope 版本不支持 VoiceEnrollmentService（tts_v2）: {exc}") from exc

    service = VoiceEnrollmentService(api_key=api_key)
    try:
        # SDK page_index 为 0 起始；对外 API 仍按 1 起始
        sdk_page_index = max(0, int(page_index) - 1)
        voice_list = service.list_voices(prefix=prefix, page_index=sdk_page_index, page_size=int(page_size))
    except Exception as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"list_voices 失败: {exc}") from exc

    if not isinstance(voice_list, list):
        voice_list = []

    clones: List[CosyVoiceClone] = []
    for item in voice_list:
        if not isinstance(item, dict):
            continue
        voice_id = (item.get("voice_id") or "").strip()
        if not voice_id.startswith(_COSYVOICE_V3_PLUS_VOICE_ID_PREFIX):
            continue
        clones.append(
            CosyVoiceClone(
                voice_id=voice_id,
                status=str(item.get("status") or "").strip() or "UNKNOWN",
                gmt_create=item.get("gmt_create"),
                gmt_modified=item.get("gmt_modified"),
            )
        )

    meta = {
        "page_index": int(page_index),
        "page_size": int(page_size),
        "cached": False,
    }

    if not prefix and int(page_index) == 1 and int(page_size) == 50:
        _CLONE_LIST_CACHE.set(clones, cache_ttl_seconds)

    return clones, meta


def delete_cosyvoice_clone(*, voice_id: str) -> Dict[str, Any]:
    voice_id = (voice_id or "").strip()
    if not voice_id.startswith(_COSYVOICE_V3_PLUS_VOICE_ID_PREFIX):
        raise CosyVoiceCloneError("仅允许删除 cosyvoice-v3-plus 的复刻音色")

    api_key = _require_dashscope_api_key()
    try:
        from dashscope.audio.tts_v2 import VoiceEnrollmentService
    except Exception as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"dashscope 版本不支持 VoiceEnrollmentService（tts_v2）: {exc}") from exc

    service = VoiceEnrollmentService(api_key=api_key)
    try:
        service.delete_voice(voice_id=voice_id)
    except Exception as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"delete_voice 失败: {exc}") from exc

    invalidate_cosyvoice_clone_cache()
    return {"voice_id": voice_id, "deleted": True}
