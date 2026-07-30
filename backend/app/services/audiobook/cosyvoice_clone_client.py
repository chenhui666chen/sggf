from __future__ import annotations

import os
import re
import time
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx


COSYVOICE_V35_PLUS_MODEL_ID = "cosyvoice-v3.5-plus"
COSYVOICE_V35_PLUS_VOICE_ID_PREFIX = "cosyvoice-v3.5-plus-"
_LEGACY_COSYVOICE_V3_PLUS_VOICE_ID_PREFIX = "cosyvoice-v3-plus-"
_LEGACY_COSYVOICE_SYSTEM_VOICES = {
    "longanyang",
    "longanhuan",
    "longanzhi_v3",
    "longanyun_v3",
    "longyichen_v3",
    "longwanjun_v3",
    "longanwen_v3",
}
_DEFAULT_CACHE_TTL_SECONDS = 30.0
_PREFIX_MAX_LEN = 10
_VOICE_CUSTOMIZATION_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
_VOICE_ENROLLMENT_MODEL = "voice-enrollment"


class CosyVoiceCloneError(RuntimeError):
    pass


def _require_dashscope_api_key() -> str:
    api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        raise CosyVoiceCloneError("未配置 DASHSCOPE_API_KEY")
    return api_key


def _extract_dashscope_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "").strip()

    if isinstance(payload, dict):
        output = payload.get("output")
        if isinstance(output, dict):
            for key in ("message", "msg", "code"):
                value = output.get(key)
                if value:
                    return str(value).strip()
        for key in ("message", "msg", "code", "request_id"):
            value = payload.get(key)
            if value:
                return str(value).strip()
    return (response.text or "").strip()


def _post_voice_customization(
    *,
    input_payload: Dict[str, Any],
    timeout: float = 30.0,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    api_key = _require_dashscope_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update({k: v for k, v in extra_headers.items() if k and v})

    try:
        response = httpx.post(
            _VOICE_CUSTOMIZATION_URL,
            json={
                "model": _VOICE_ENROLLMENT_MODEL,
                "input": input_payload,
            },
            headers=headers,
            timeout=timeout,
        )
    except httpx.RequestError as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"调用 DashScope 声音定制接口失败: {exc}") from exc

    if response.status_code != 200:
        detail = _extract_dashscope_error_detail(response)
        raise CosyVoiceCloneError(
            f"DashScope 声音定制接口失败: {response.status_code} {detail}".strip()
        )

    try:
        payload = response.json()
    except ValueError as exc:  # noqa: BLE001
        raise CosyVoiceCloneError("声音定制接口响应解析失败") from exc

    if not isinstance(payload, dict):
        raise CosyVoiceCloneError("声音定制接口响应格式无效")
    return payload


def is_cosyvoice_v35_plus_voice_id(voice_id: str) -> bool:
    return str(voice_id or "").strip().startswith(COSYVOICE_V35_PLUS_VOICE_ID_PREFIX)


def is_cosyvoice_custom_voice_id(voice_id: str) -> bool:
    normalized = str(voice_id or "").strip()
    return normalized.startswith(
        (
            COSYVOICE_V35_PLUS_VOICE_ID_PREFIX,
            _LEGACY_COSYVOICE_V3_PLUS_VOICE_ID_PREFIX,
        )
    )


def is_legacy_cosyvoice_system_voice(voice_id: str) -> bool:
    return str(voice_id or "").strip() in _LEGACY_COSYVOICE_SYSTEM_VOICES


def _build_safe_upload_filename(filename: str) -> str:
    name = Path(filename or "").name
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem).strip("_") or "audio"
    suffix = Path(name).suffix
    ext = re.sub(r"[^A-Za-z0-9.]+", "", suffix)
    token = secrets.token_hex(4)
    return f"{stem}_{token}{ext}"


def _get_dashscope_upload_policy(model: str) -> Dict[str, Any]:
    api_key = _require_dashscope_api_key()
    try:
        response = httpx.get(
            "https://dashscope.aliyuncs.com/api/v1/uploads",
            params={"action": "getPolicy", "model": model},
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=20.0,
        )
    except httpx.RequestError as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"获取上传凭证失败: {exc}") from exc

    if response.status_code != 200:
        detail = (response.text or "").strip()
        raise CosyVoiceCloneError(f"获取上传凭证失败: {response.status_code} {detail}")

    try:
        payload = response.json()
    except ValueError as exc:  # noqa: BLE001
        raise CosyVoiceCloneError("上传凭证响应解析失败") from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise CosyVoiceCloneError("上传凭证响应缺少 data")

    return data


def _build_public_oss_url(upload_host: str, key: str) -> str:
    host = str(upload_host or "").strip()
    if not host:
        return ""
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"https://{host}"
    return f"{host.rstrip('/')}/{str(key).lstrip('/')}"


def _normalize_cosyvoice_audio_url(audio_url: str) -> str:
    url = (audio_url or "").strip()
    if url.startswith("oss://"):
        key = url[len("oss://"):]
        if not key:
            raise CosyVoiceCloneError("oss:// 地址不能为空")
        policy = _get_dashscope_upload_policy(COSYVOICE_V35_PLUS_MODEL_ID)
        public_url = _build_public_oss_url(policy.get("upload_host"), key)
        if public_url:
            return public_url
        raise CosyVoiceCloneError("oss:// 地址无法解析为公网 URL，请改用 http/https")
    return url


def _resolve_clone_name_store_path() -> Path:
    """Resolve a writable JSON file to persist voice_id -> display_name mapping."""
    current = Path(__file__).resolve()
    for ancestor in current.parents:
        backend_data = ancestor / "backend" / "data"
        if backend_data.exists():
            return backend_data / "cosyvoice_clone_names.json"
    # Fallback: relative to backend/app/services/audiobook
    return current.parents[3] / "data" / "cosyvoice_clone_names.json"


def _load_clone_name_store() -> Dict[str, Dict[str, Any]]:
    path = _resolve_clone_name_store_path()
    try:
        if not path.exists():
            return {}
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            normalized: Dict[str, Dict[str, Any]] = {}
            for key, value in data.items():
                voice_id = str(key or "").strip()
                if not voice_id:
                    continue
                if isinstance(value, dict):
                    normalized[voice_id] = {
                        "display_name": str(value.get("display_name") or "").strip(),
                        "owner_user_id": (
                            int(value["owner_user_id"])
                            if value.get("owner_user_id") not in (None, "")
                            else None
                        ),
                    }
                elif value:
                    normalized[voice_id] = {
                        "display_name": str(value).strip(),
                        "owner_user_id": None,
                    }
            return normalized
    except Exception:
        return {}
    return {}


def _save_clone_name_store(mapping: Dict[str, Dict[str, Any]]) -> None:
    path = _resolve_clone_name_store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # 不阻塞主流程；映射丢失只会影响 UI 展示
        return


def save_clone_display_name(
    *,
    voice_id: str,
    display_name: str,
    owner_user_id: int | None = None,
) -> None:
    voice_id = (voice_id or "").strip()
    display_name = (display_name or "").strip()
    if not voice_id or not display_name:
        return
    mapping = _load_clone_name_store()
    mapping[voice_id] = {
        "display_name": display_name[:50],
        "owner_user_id": owner_user_id,
    }
    _save_clone_name_store(mapping)


def get_clone_display_name(voice_id: str) -> Optional[str]:
    voice_id = (voice_id or "").strip()
    if not voice_id:
        return None
    mapping = _load_clone_name_store()
    value = mapping.get(voice_id)
    if not isinstance(value, dict):
        return None
    display_name = str(value.get("display_name") or "").strip()
    return display_name or None


def get_clone_owner_user_id(voice_id: str) -> Optional[int]:
    voice_id = (voice_id or "").strip()
    if not voice_id:
        return None
    value = _load_clone_name_store().get(voice_id)
    if not isinstance(value, dict):
        return None
    owner_user_id = value.get("owner_user_id")
    return int(owner_user_id) if owner_user_id not in (None, "") else None


def remove_clone_display_name(voice_id: str) -> None:
    voice_id = (voice_id or "").strip()
    if not voice_id:
        return
    mapping = _load_clone_name_store()
    if voice_id not in mapping:
        return
    mapping.pop(voice_id, None)
    _save_clone_name_store(mapping)


def _extract_prefix_from_voice_id(voice_id: str) -> str:
    voice_id = (voice_id or "").strip()
    known_prefix = ""
    if voice_id.startswith(COSYVOICE_V35_PLUS_VOICE_ID_PREFIX):
        known_prefix = COSYVOICE_V35_PLUS_VOICE_ID_PREFIX
    elif voice_id.startswith(_LEGACY_COSYVOICE_V3_PLUS_VOICE_ID_PREFIX):
        known_prefix = _LEGACY_COSYVOICE_V3_PLUS_VOICE_ID_PREFIX
    if not known_prefix:
        return ""
    # cosyvoice-v3.5-plus-{prefix}-{random}
    tail = voice_id[len(known_prefix) :]
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


def _truncate_custom_voice_text(value: Optional[str], max_len: int = 36) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return f"{text[:max_len].rstrip()}..."


def _build_custom_voice_preset(
    voice_id: str,
    status: str,
    gmt_create: Optional[str] = None,
    display_name: Optional[str] = None,
    *,
    custom_type: Optional[str] = None,
    voice_prompt: Optional[str] = None,
    preview_text: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_type = str(custom_type or "").strip().lower()
    if resolved_type not in {"clone", "design"}:
        resolved_type = "design" if str(voice_prompt or "").strip() or str(preview_text or "").strip() else "clone"

    prefix = _extract_prefix_from_voice_id(voice_id) or resolved_type
    display_name = (display_name or "").strip()
    status_label = (status or "").strip() or "UNKNOWN"
    short_kind_label = "设计" if resolved_type == "design" else "复刻"
    long_kind_label = "设计音色" if resolved_type == "design" else "复刻音色"

    desc_parts = [f"{long_kind_label}（状态: {status_label}）"]
    if gmt_create:
        desc_parts.append(f"创建时间: {gmt_create}")
    if resolved_type == "design":
        short_prompt = _truncate_custom_voice_text(voice_prompt)
        short_preview = _truncate_custom_voice_text(preview_text)
        if short_prompt:
            desc_parts.append(f"音色描述: {short_prompt}")
        if short_preview:
            desc_parts.append(f"试听文本: {short_preview}")

    return {
        "id": voice_id,
        "speaker": voice_id,
        "label": f"{short_kind_label}-{display_name}" if display_name else f"{short_kind_label}-{prefix}",
        "category": "custom",
        "customType": resolved_type,
        "description": "；".join(desc_parts),
        "supportsInstruct": True,
    }


@dataclass(frozen=True)
class CosyVoiceClone:
    voice_id: str
    status: str
    gmt_create: Optional[str] = None
    gmt_modified: Optional[str] = None
    custom_type: str = "clone"
    voice_prompt: Optional[str] = None
    preview_text: Optional[str] = None
    preview_audio: Optional[str] = None

    def to_voice_preset(self, display_name: Optional[str] = None) -> Dict[str, Any]:
        return _build_custom_voice_preset(
            self.voice_id,
            self.status,
            self.gmt_create,
            display_name,
            custom_type=self.custom_type,
            voice_prompt=self.voice_prompt,
            preview_text=self.preview_text,
        )


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


def upload_cosyvoice_v3_plus_clone_sample(
    *,
    filename: str,
    content: bytes,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    if not content:
        raise CosyVoiceCloneError("音频文件为空")

    policy = _get_dashscope_upload_policy(COSYVOICE_V35_PLUS_MODEL_ID)
    required_fields = (
        "upload_host",
        "upload_dir",
        "oss_access_key_id",
        "signature",
        "policy",
        "x_oss_object_acl",
        "x_oss_forbid_overwrite",
    )
    missing = [field for field in required_fields if policy.get(field) in (None, "")]
    if missing:
        raise CosyVoiceCloneError(f"上传凭证缺少字段: {', '.join(missing)}")

    max_file_size_mb = policy.get("max_file_size_mb")
    if max_file_size_mb:
        try:
            max_bytes = float(max_file_size_mb) * 1024 * 1024
        except (TypeError, ValueError):
            max_bytes = 0
        if max_bytes and len(content) > max_bytes:
            raise CosyVoiceCloneError(f"文件大小超出限制（最大 {max_file_size_mb} MB）")

    safe_name = _build_safe_upload_filename(filename)
    upload_dir = str(policy["upload_dir"]).rstrip("/")
    key = f"{upload_dir}/{safe_name}"

    form_data = {
        "OSSAccessKeyId": policy["oss_access_key_id"],
        "Signature": policy["signature"],
        "policy": policy["policy"],
        "x-oss-object-acl": policy["x_oss_object_acl"],
        "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"],
        "key": key,
        "success_action_status": "200",
    }

    files = {
        "file": (safe_name, content, content_type or "application/octet-stream"),
    }

    try:
        response = httpx.post(
            str(policy["upload_host"]),
            data=form_data,
            files=files,
            timeout=30.0,
        )
    except httpx.RequestError as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"上传文件失败: {exc}") from exc

    if response.status_code != 200:
        detail = (response.text or "").strip()
        raise CosyVoiceCloneError(f"上传文件失败: {response.status_code} {detail}")

    return {
        "url": f"oss://{key}",
        "key": key,
        "file_name": safe_name,
    }


def create_cosyvoice_v3_plus_clone(*, prefix: str, audio_url: str) -> Dict[str, Any]:
    """创建 cosyvoice-v3.5-plus 复刻音色。

    说明：
    - 使用 oss:// 临时 URL 时，需要通过 X-DashScope-OssResourceResolve 进行解析。
    - 返回 voice_id 后，可能需要等待 status 变为 OK 才可用于合成。
    """
    prefix = (prefix or "").strip()
    audio_url = (audio_url or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,10}", prefix):
        raise CosyVoiceCloneError("prefix 仅支持大小写英文字母、数字和下划线，长度 1~10")
    if not (
        audio_url.startswith("http://")
        or audio_url.startswith("https://")
        or audio_url.startswith("oss://")
    ):
        raise CosyVoiceCloneError("url 必须是 http/https 或 oss:// 临时地址")

    api_key = _require_dashscope_api_key()

    try:
        from dashscope.audio.tts_v2 import VoiceEnrollmentService
    except Exception as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"dashscope 版本不支持 VoiceEnrollmentService（tts_v2）: {exc}") from exc

    def _create_voice(url: str, headers: Optional[Dict[str, str]] = None) -> str:
        service = VoiceEnrollmentService(api_key=api_key, headers=headers or {})
        return str(
            service.create_voice(
                target_model=COSYVOICE_V35_PLUS_MODEL_ID,
                prefix=prefix,
                url=url,
            )
        ).strip()

    is_oss = audio_url.startswith("oss://")
    try:
        voice_id = _create_voice(
            audio_url,
            headers={"X-DashScope-OssResourceResolve": "enable"} if is_oss else None,
        )
    except Exception as exc:  # noqa: BLE001
        if not is_oss:
            raise CosyVoiceCloneError(f"create_voice 失败: {exc}") from exc
        try:
            fallback_url = _normalize_cosyvoice_audio_url(audio_url)
        except CosyVoiceCloneError:
            raise CosyVoiceCloneError(f"create_voice 失败: {exc}") from exc
        if not (fallback_url.startswith("http://") or fallback_url.startswith("https://")):
            raise CosyVoiceCloneError(f"create_voice 失败: {exc}") from exc
        try:
            voice_id = _create_voice(fallback_url)
        except Exception as retry_exc:  # noqa: BLE001
            raise CosyVoiceCloneError(f"create_voice 失败: {retry_exc}") from retry_exc

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
    """列出 cosyvoice-v3.5-plus 的复刻音色（按当前 API Key 下的 voice_id 过滤）。"""
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
        if not voice_id.startswith(COSYVOICE_V35_PLUS_VOICE_ID_PREFIX):
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


def create_cosyvoice_v3_plus_design(
    *,
    prefix: str,
    voice_prompt: str,
    preview_text: str,
    sample_rate: int = 24000,
    response_format: str = "wav",
) -> Dict[str, Any]:
    prefix = (prefix or "").strip()
    voice_prompt = (voice_prompt or "").strip()
    preview_text = (preview_text or "").strip()
    response_format = (response_format or "wav").strip().lower() or "wav"

    if not re.fullmatch(r"[A-Za-z0-9_]{1,10}", prefix):
        raise CosyVoiceCloneError("prefix 仅支持大小写英文字母、数字和下划线，长度 1~10")
    if not voice_prompt:
        raise CosyVoiceCloneError("voice_prompt 不能为空")
    if not preview_text:
        raise CosyVoiceCloneError("preview_text 不能为空")
    if response_format not in {"wav", "mp3", "pcm"}:
        raise CosyVoiceCloneError("response_format 仅支持 wav / mp3 / pcm")
    if sample_rate not in {8000, 16000, 22050, 24000, 32000, 44100, 48000}:
        raise CosyVoiceCloneError("sample_rate 不在允许范围内")

    payload = _post_voice_customization(
        input_payload={
            "action": "create_voice",
            "target_model": COSYVOICE_V35_PLUS_MODEL_ID,
            "prefix": prefix,
            "voice_prompt": voice_prompt,
            "preview_text": preview_text,
            "parameters": {
                "sample_rate": sample_rate,
                "format": response_format,
            },
        },
        timeout=45.0,
    )
    output = payload.get("output") if isinstance(payload, dict) else None
    if not isinstance(output, dict):
        raise CosyVoiceCloneError("创建设计音色失败：响应缺少 output")

    voice_id = str(output.get("voice_id") or "").strip()
    if not voice_id:
        raise CosyVoiceCloneError("创建设计音色失败：未返回 voice_id")

    invalidate_cosyvoice_clone_cache()
    return {
        "voice_id": voice_id,
        "status": "DEPLOYING",
        "preview_audio": output.get("preview_audio"),
    }


def _build_cosyvoice_custom_voice(item: Dict[str, Any]) -> Optional[CosyVoiceClone]:
    voice_id = str(item.get("voice_id") or "").strip()
    if not voice_id.startswith(COSYVOICE_V35_PLUS_VOICE_ID_PREFIX):
        return None

    voice_prompt = str(item.get("voice_prompt") or "").strip() or None
    preview_text = str(item.get("preview_text") or "").strip() or None
    preview_audio = str(item.get("preview_audio") or "").strip() or None
    custom_type = "design" if voice_prompt or preview_text else "clone"

    return CosyVoiceClone(
        voice_id=voice_id,
        status=str(item.get("status") or "").strip() or "UNKNOWN",
        gmt_create=item.get("gmt_create"),
        gmt_modified=item.get("gmt_modified"),
        custom_type=custom_type,
        voice_prompt=voice_prompt,
        preview_text=preview_text,
        preview_audio=preview_audio,
    )


def list_cosyvoice_v3_plus_clones(
    *,
    prefix: Optional[str] = None,
    page_index: int = 1,
    page_size: int = 50,
    cache_ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
) -> Tuple[List[CosyVoiceClone], Dict[str, Any]]:
    prefix = (prefix or "").strip() or None

    if prefix and not re.fullmatch(r"[A-Za-z0-9_]{1,10}", prefix):
        raise CosyVoiceCloneError("prefix 仅支持大小写英文字母、数字和下划线，长度 1~10")

    cached = _CLONE_LIST_CACHE.get()
    if cached is not None and not prefix and int(page_index) == 1 and int(page_size) == 50:
        return cached, {"cached": True}

    payload = _post_voice_customization(
        input_payload={
            "action": "list_voice",
            "target_model": COSYVOICE_V35_PLUS_MODEL_ID,
            "page_index": max(0, int(page_index) - 1),
            "page_size": int(page_size),
            **({"prefix": prefix} if prefix else {}),
        },
        timeout=30.0,
    )
    output = payload.get("output") if isinstance(payload, dict) else None
    voice_list = output.get("voice_list") if isinstance(output, dict) else None
    if not isinstance(voice_list, list):
        voice_list = []

    clones: List[CosyVoiceClone] = []
    for item in voice_list:
        if not isinstance(item, dict):
            continue
        parsed = _build_cosyvoice_custom_voice(item)
        if parsed is not None:
            clones.append(parsed)

    meta = {
        "page_index": int(page_index),
        "page_size": int(page_size),
        "cached": False,
    }

    if not prefix and int(page_index) == 1 and int(page_size) == 50:
        _CLONE_LIST_CACHE.set(clones, cache_ttl_seconds)

    return clones, meta


def delete_cosyvoice_clone(
    *,
    voice_id: str,
    remove_local_mapping: bool = True,
    missing_ok: bool = False,
) -> Dict[str, Any]:
    voice_id = (voice_id or "").strip()
    if not is_cosyvoice_custom_voice_id(voice_id):
        raise CosyVoiceCloneError("仅允许删除已知 CosyVoice 自定义音色")

    api_key = _require_dashscope_api_key()
    try:
        from dashscope.audio.tts_v2 import VoiceEnrollmentService
    except Exception as exc:  # noqa: BLE001
        raise CosyVoiceCloneError(f"dashscope 版本不支持 VoiceEnrollmentService（tts_v2）: {exc}") from exc

    service = VoiceEnrollmentService(api_key=api_key)
    already_absent = False
    try:
        service.delete_voice(voice_id=voice_id)
    except Exception as exc:  # noqa: BLE001
        if missing_ok and "BadRequest.ResourceNotExist" in str(exc):
            already_absent = True
        else:
            raise CosyVoiceCloneError(f"delete_voice 失败: {exc}") from exc

    if remove_local_mapping:
        remove_clone_display_name(voice_id)
    invalidate_cosyvoice_clone_cache()
    if already_absent:
        return {
            "voice_id": voice_id,
            "deleted": False,
            "already_absent": True,
        }
    return {"voice_id": voice_id, "deleted": True}
