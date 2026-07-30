from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import httpx

from app.services.audiobook.cosyvoice_clone_client import (
    CosyVoiceCloneError,
    _build_public_oss_url,
    _build_safe_upload_filename,
    _get_dashscope_upload_policy,
)
from app.services.audiobook.tts_model_ids import (
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    get_audiobook_tts_model_metadata,
    get_audiobook_tts_runtime_model_id,
    normalize_audiobook_tts_model,
)


DASHSCOPE_MULTIMODAL_GENERATION_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
)
DEFAULT_MINIMAX_VOICE_CLONE_DIR = Path(__file__).resolve().parents[3] / "data" / "minimax_voice_clones"
MINIMAX_CUSTOM_VOICE_PREFIX = "mmx_"
MINIMAX_VOICE_CLONE_MODELS = {
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
}
MINIMAX_CLONE_SUPPORTED_AUDIO_MIME_TYPES = {"audio/mpeg", "audio/wav"}
_MINIMAX_AUDIO_MIME_ALIASES = {
    "audio/mp3": "audio/mpeg",
    "audio/x-mp3": "audio/mpeg",
    "audio/wave": "audio/wav",
    "audio/x-wav": "audio/wav",
}
_MINIMAX_VOICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")
_STORE_LOCK = threading.RLock()


class MiniMaxVoiceCloneError(RuntimeError):
    pass


def _normalize_minimax_clone_model(model: str) -> str:
    normalized = normalize_audiobook_tts_model(model, default="")
    if normalized not in MINIMAX_VOICE_CLONE_MODELS:
        raise MiniMaxVoiceCloneError("MiniMax 音色复刻仅支持 Speech 2.8 HD 或 Speech 2.8 Turbo")
    return normalized


def _provider_model_id(model: str) -> str:
    normalized = _normalize_minimax_clone_model(model)
    provider_model = get_audiobook_tts_runtime_model_id(normalized)
    if provider_model not in {"MiniMax/speech-2.8-hd", "MiniMax/speech-2.8-turbo"}:
        raise MiniMaxVoiceCloneError(f"MiniMax 复刻模型映射无效: {model}")
    return provider_model


def _require_dashscope_api_key(api_key: Optional[str] = None) -> str:
    resolved = str(api_key or os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not resolved:
        raise MiniMaxVoiceCloneError("未配置 DASHSCOPE_API_KEY")
    return resolved


def _normalize_audio_mime_type(content_type: str, filename: str = "") -> str:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    normalized = _MINIMAX_AUDIO_MIME_ALIASES.get(normalized, normalized)
    if not normalized:
        suffix = Path(filename or "").suffix.lower()
        normalized = "audio/mpeg" if suffix == ".mp3" else "audio/wav" if suffix == ".wav" else ""
    if normalized not in MINIMAX_CLONE_SUPPORTED_AUDIO_MIME_TYPES:
        raise MiniMaxVoiceCloneError("MiniMax 音色复刻参考样本仅支持 mp3 或 wav 音频")
    return normalized


def is_minimax_custom_voice_id(voice_id: str) -> bool:
    value = str(voice_id or "").strip()
    return value.startswith(MINIMAX_CUSTOM_VOICE_PREFIX) and bool(_MINIMAX_VOICE_ID_RE.fullmatch(value))


def build_minimax_custom_voice_id(*, owner_user_id: str, name: str) -> str:
    clean_name = str(name or "").strip()
    if not clean_name:
        raise MiniMaxVoiceCloneError("name 不能为空")
    unique_source = f"{owner_user_id}:{clean_name}:{os.urandom(16).hex()}"
    digest = hashlib.sha256(unique_source.encode("utf-8")).hexdigest()[:16]
    return f"{MINIMAX_CUSTOM_VOICE_PREFIX}{digest}"


def upload_minimax_voice_clone_sample(
    *,
    model: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> Dict[str, str]:
    if not content:
        raise MiniMaxVoiceCloneError("参考音频文件为空")
    provider_model = _provider_model_id(model)
    mime_type = _normalize_audio_mime_type(content_type, filename)

    try:
        policy = _get_dashscope_upload_policy(provider_model)
    except CosyVoiceCloneError as exc:
        raise MiniMaxVoiceCloneError(str(exc)) from exc

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
        raise MiniMaxVoiceCloneError(f"上传凭证缺少字段: {', '.join(missing)}")

    max_file_size_mb = policy.get("max_file_size_mb")
    try:
        max_bytes = float(max_file_size_mb) * 1024 * 1024 if max_file_size_mb else 0
    except (TypeError, ValueError):
        max_bytes = 0
    if max_bytes and len(content) > max_bytes:
        raise MiniMaxVoiceCloneError(f"文件大小超出限制（最大 {max_file_size_mb} MB）")

    safe_name = _build_safe_upload_filename(filename or "minimax-reference.wav")
    key = f"{str(policy['upload_dir']).rstrip('/')}/{safe_name}"
    form_data = {
        "OSSAccessKeyId": policy["oss_access_key_id"],
        "Signature": policy["signature"],
        "policy": policy["policy"],
        "x-oss-object-acl": policy["x_oss_object_acl"],
        "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"],
        "key": key,
        "success_action_status": "200",
    }
    try:
        response = httpx.post(
            str(policy["upload_host"]),
            data=form_data,
            files={"file": (safe_name, content, mime_type)},
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        raise MiniMaxVoiceCloneError(f"上传 MiniMax 参考音频失败: {exc}") from exc
    if response.status_code != 200:
        raise MiniMaxVoiceCloneError(
            f"上传 MiniMax 参考音频失败: {response.status_code} {(response.text or '').strip()}".strip()
        )

    public_url = _build_public_oss_url(str(policy["upload_host"]), key)
    if not public_url:
        raise MiniMaxVoiceCloneError("参考音频上传成功，但无法生成公网 audio_url")
    return {"audio_url": public_url, "object_key": key, "file_name": safe_name}


def _decode_preview_audio(value: Any) -> bytes:
    raw = str(value or "").strip()
    if not raw:
        return b""
    if len(raw) % 2 == 0 and _HEX_RE.fullmatch(raw):
        try:
            return bytes.fromhex(raw)
        except ValueError:
            return b""
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, TypeError):
        return b""


def _extract_provider_error(payload: Dict[str, Any]) -> str:
    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    base_resp = output.get("base_resp") if isinstance(output.get("base_resp"), dict) else {}
    for container in (base_resp, output, payload):
        for key in ("status_msg", "message", "msg", "code"):
            value = container.get(key)
            if value not in (None, "", 0, "0"):
                return str(value).strip()
    return "未知供应商错误"


def create_minimax_voice_clone(
    *,
    model: str,
    voice_id: str,
    audio_url: str,
    sample_text: str,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    provider_model = _provider_model_id(model)
    clean_voice_id = str(voice_id or "").strip()
    clean_audio_url = str(audio_url or "").strip()
    clean_sample_text = str(sample_text or "").strip()
    if not _MINIMAX_VOICE_ID_RE.fullmatch(clean_voice_id):
        raise MiniMaxVoiceCloneError("voice_id 仅支持英文字母、数字、下划线和连字符，长度 8~64")
    if not clean_audio_url.startswith(("http://", "https://")):
        raise MiniMaxVoiceCloneError("audio_url 必须是公网可访问的 http/https 地址")
    if not clean_sample_text:
        raise MiniMaxVoiceCloneError("参考音频逐字内容不能为空")

    payload = {
        "model": provider_model,
        "input": {
            "action": "voice_clone",
            "voice_id": clean_voice_id,
            "audio_url": clean_audio_url,
            "text": clean_sample_text,
        },
    }
    try:
        response = httpx.post(
            DASHSCOPE_MULTIMODAL_GENERATION_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {_require_dashscope_api_key(api_key)}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )
    except httpx.RequestError as exc:
        raise MiniMaxVoiceCloneError(f"调用 MiniMax 音色复刻接口失败: {exc}") from exc
    if response.status_code != 200:
        raise MiniMaxVoiceCloneError(
            f"MiniMax 音色复刻接口失败: {response.status_code} {(response.text or '').strip()}".strip()
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise MiniMaxVoiceCloneError("MiniMax 音色复刻响应解析失败") from exc
    if not isinstance(result, dict):
        raise MiniMaxVoiceCloneError("MiniMax 音色复刻响应格式无效")

    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    base_resp = output.get("base_resp") if isinstance(output.get("base_resp"), dict) else {}
    status_code = base_resp.get("status_code")
    top_code = result.get("code")
    if status_code not in (None, 0, "0") or top_code not in (None, 0, "0"):
        raise MiniMaxVoiceCloneError(f"MiniMax 音色复刻失败: {_extract_provider_error(result)}")

    data = output.get("data") if isinstance(output.get("data"), dict) else {}
    audio_info = output.get("audio") if isinstance(output.get("audio"), dict) else {}
    preview_audio_bytes = _decode_preview_audio(data.get("audio") or audio_info.get("data"))
    preview_audio_url = str(
        data.get("audio_url")
        or data.get("url")
        or audio_info.get("url")
        or result.get("audio_url")
        or ""
    ).strip()
    provider_request_id = str(
        result.get("request_id")
        or output.get("request_id")
        or response.headers.get("X-DashScope-Request-Id")
        or ""
    ).strip()
    return {
        "voice_id": clean_voice_id,
        "provider_model": provider_model,
        "provider_request_id": provider_request_id,
        "preview_audio_bytes": preview_audio_bytes,
        "preview_audio_url": preview_audio_url,
    }


@dataclass(frozen=True)
class MiniMaxVoiceClone:
    owner_user_id: str
    voice_id: str
    name: str
    model: str
    sample_text: str
    created_at: str
    provider_request_id: str = ""

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "MiniMaxVoiceClone":
        return cls(
            owner_user_id=str(value.get("owner_user_id") or ""),
            voice_id=str(value.get("voice_id") or ""),
            name=str(value.get("name") or ""),
            model=str(value.get("model") or ""),
            sample_text=str(value.get("sample_text") or ""),
            created_at=str(value.get("created_at") or ""),
            provider_request_id=str(value.get("provider_request_id") or ""),
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "owner_user_id": self.owner_user_id,
            "voice_id": self.voice_id,
            "name": self.name,
            "model": self.model,
            "sample_text": self.sample_text,
            "created_at": self.created_at,
            "provider_request_id": self.provider_request_id,
        }

    def to_voice_preset(self) -> Dict[str, Any]:
        model_name = str(get_audiobook_tts_model_metadata(self.model).get("name") or self.model)
        return {
            "id": self.voice_id,
            "speaker": self.voice_id,
            "label": f"复刻-{self.name or self.voice_id}",
            "category": "custom",
            "customType": "clone",
            "provider": "minimax",
            "description": f"{model_name} 复刻音色；创建时间: {self.created_at}",
            "default_params": {"volume": 50, "speed": 1.0, "pitch": 0},
        }


class MiniMaxVoiceCloneStore:
    def __init__(self, root_dir: Path | str | None = None) -> None:
        self.root_dir = Path(root_dir or DEFAULT_MINIMAX_VOICE_CLONE_DIR)
        self.index_path = self.root_dir / "index.json"

    def list(self, *, owner_user_id: str, model: Optional[str] = None) -> list[MiniMaxVoiceClone]:
        normalized_model = _normalize_minimax_clone_model(model) if model else ""
        owner = str(owner_user_id)
        clones = [clone for clone in self._load() if clone.owner_user_id == owner]
        if normalized_model:
            clones = [clone for clone in clones if clone.model == normalized_model]
        return sorted(clones, key=lambda clone: clone.created_at, reverse=True)

    def save(self, clone: MiniMaxVoiceClone) -> None:
        if not clone.owner_user_id or not clone.voice_id:
            raise MiniMaxVoiceCloneError("MiniMax 复刻音色缺少 owner_user_id 或 voice_id")
        with _STORE_LOCK:
            clones = list(self._load())
            if any(item.voice_id == clone.voice_id and item.owner_user_id != clone.owner_user_id for item in clones):
                raise MiniMaxVoiceCloneError("voice_id 已属于其他用户")
            clones = [
                item
                for item in clones
                if not (item.owner_user_id == clone.owner_user_id and item.voice_id == clone.voice_id)
            ]
            clones.append(clone)
            self._save(clones)

    def remove(self, *, owner_user_id: str, voice_id: str) -> bool:
        owner = str(owner_user_id)
        target = str(voice_id or "").strip()
        with _STORE_LOCK:
            clones = list(self._load())
            remaining = [
                clone
                for clone in clones
                if not (clone.owner_user_id == owner and clone.voice_id == target)
            ]
            if len(remaining) == len(clones):
                return False
            self._save(remaining)
            return True

    def _load(self) -> Iterable[MiniMaxVoiceClone]:
        if not self.index_path.exists():
            return []
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MiniMaxVoiceCloneError(f"读取 MiniMax 复刻音色索引失败: {exc}") from exc
        items = payload.get("clones") if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return []
        return [
            clone
            for item in items
            if isinstance(item, dict)
            for clone in [MiniMaxVoiceClone.from_dict(item)]
            if clone.owner_user_id and clone.voice_id and clone.model
        ]

    def _save(self, clones: Iterable[MiniMaxVoiceClone]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        payload = {"clones": [clone.to_dict() for clone in clones]}
        temp_path = self.root_dir / f"index.{os.urandom(6).hex()}.tmp"
        try:
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(self.index_path)
        except OSError as exc:
            raise MiniMaxVoiceCloneError(f"保存 MiniMax 复刻音色索引失败: {exc}") from exc
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass


def build_minimax_voice_clone_billing(model: str) -> Dict[str, Any]:
    normalized = _normalize_minimax_clone_model(model)
    pricing = get_audiobook_tts_model_metadata(normalized).get("custom_voice_pricing") or {}
    preview_price = float(pricing.get("preview_price_per_10k") or 0.0)
    first_use_fee = float(pricing.get("first_formal_use_yuan") or 0.0)
    return {
        "preview_price_per_10k": preview_price,
        "first_formal_use_fee_yuan": first_use_fee,
        "billing_notice": (
            f"创建复刻试听按当前 MiniMax 模型 {preview_price:g} 元/万字符计费；"
            f"该复刻音色首次用于正式语音合成时，阿里云百炼将另收 {first_use_fee:g} 元音色解锁费，"
            "后续重复使用不会再次按章节收取该解锁费。"
        ),
    }


def create_minimax_voice_clone_from_bytes(
    *,
    owner_user_id: str,
    model: str,
    name: str,
    sample_text: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> Dict[str, Any]:
    normalized_model = _normalize_minimax_clone_model(model)
    clean_name = str(name or "").strip()
    clean_sample_text = str(sample_text or "").strip()
    if not clean_name:
        raise MiniMaxVoiceCloneError("音色名称不能为空")
    if not clean_sample_text:
        raise MiniMaxVoiceCloneError("参考音频逐字内容不能为空")
    upload = upload_minimax_voice_clone_sample(
        model=normalized_model,
        filename=filename,
        content=content,
        content_type=content_type,
    )
    voice_id = build_minimax_custom_voice_id(owner_user_id=str(owner_user_id), name=clean_name)
    provider_result = create_minimax_voice_clone(
        model=normalized_model,
        voice_id=voice_id,
        audio_url=upload["audio_url"],
        sample_text=clean_sample_text,
    )
    clone = MiniMaxVoiceClone(
        owner_user_id=str(owner_user_id),
        voice_id=voice_id,
        name=clean_name[:80],
        model=normalized_model,
        sample_text=clean_sample_text,
        created_at=datetime.now(timezone.utc).isoformat(),
        provider_request_id=str(provider_result.get("provider_request_id") or ""),
    )
    try:
        MiniMaxVoiceCloneStore().save(clone)
    except MiniMaxVoiceCloneError as exc:
        raise MiniMaxVoiceCloneError(
            f"供应商已创建 voice_id={voice_id}，但本系统登记失败，请保留该 ID 后重试登记: {exc}"
        ) from exc
    return {"clone": clone, **provider_result}


def list_minimax_voice_clone_presets(*, owner_user_id: str, model: str) -> list[Dict[str, Any]]:
    return [
        clone.to_voice_preset()
        for clone in MiniMaxVoiceCloneStore().list(owner_user_id=str(owner_user_id), model=model)
    ]
