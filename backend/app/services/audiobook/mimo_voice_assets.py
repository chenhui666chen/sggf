from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.services.audiobook.tts_model_ids import (
    MIMO_V25_TTS_VOICE_CLONE_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    normalize_audiobook_tts_model,
)

DEFAULT_MIMO_VOICE_ASSET_DIR = Path("backend/data/mimo_voice_assets")
_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^,;]+(?:;[^,;]+)*);base64,(?P<data>.+)$", re.DOTALL)
MIMO_CLONE_SUPPORTED_AUDIO_MIME_TYPES = {"audio/mpeg", "audio/wav"}
_MIMO_CLONE_AUDIO_MIME_ALIASES = {
    "audio/mp3": "audio/mpeg",
    "audio/x-mp3": "audio/mpeg",
    "audio/wave": "audio/wav",
    "audio/x-wav": "audio/wav",
}
_MIMO_CLONE_AUDIO_FORMAT_ERROR = "MiMo Voice Clone 仅支持 mp3 或 wav 音频，请重新上传支持格式的样本。"


class MiMoVoiceAssetError(ValueError):
    pass


@dataclass(frozen=True)
class MiMoVoiceAsset:
    id: str
    name: str
    asset_type: str
    model: str
    description: str = ""
    voice_design_prompt: str = ""
    mime_type: str = ""
    audio_path: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "MiMoVoiceAsset":
        return cls(
            id=str(payload.get("id") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            asset_type=str(payload.get("asset_type") or payload.get("type") or "").strip(),
            model=normalize_audiobook_tts_model(str(payload.get("model") or ""), default=""),
            description=str(payload.get("description") or "").strip(),
            voice_design_prompt=str(payload.get("voice_design_prompt") or "").strip(),
            mime_type=str(payload.get("mime_type") or "").strip(),
            audio_path=str(payload.get("audio_path") or "").strip(),
            created_at=str(payload.get("created_at") or "").strip(),
            updated_at=str(payload.get("updated_at") or "").strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "asset_type": self.asset_type,
            "model": self.model,
            "description": self.description,
            "voice_design_prompt": self.voice_design_prompt,
            "mime_type": self.mime_type,
            "audio_path": self.audio_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_voice_preset(self) -> Dict[str, Any]:
        prefix = "mimo_design" if self.asset_type == "design" else "mimo_clone"
        style = "voice_design" if self.asset_type == "design" else "voice_clone"
        return {
            "id": f"{prefix}:{self.id}",
            "speaker": f"{prefix}:{self.id}",
            "label": self.name or self.id,
            "category": "custom",
            "customType": self.asset_type,
            "description": self.description or self.voice_design_prompt or self.id,
            "style": style,
            "default_params": {"volume": 50, "speed": 1.0, "pitch": 50},
        }


class MiMoVoiceAssetStore:
    def __init__(self, root_dir: Path | str | None = None) -> None:
        self.root_dir = Path(root_dir or DEFAULT_MIMO_VOICE_ASSET_DIR)
        self.index_path = self.root_dir / "index.json"

    def list_assets(self, *, model: Optional[str] = None, asset_type: Optional[str] = None) -> List[MiMoVoiceAsset]:
        normalized_model = normalize_audiobook_tts_model(model, default="") if model else ""
        requested_type = str(asset_type or "").strip()
        assets = list(self._load_assets())
        if normalized_model:
            assets = [asset for asset in assets if asset.model == normalized_model]
        if requested_type:
            assets = [asset for asset in assets if asset.asset_type == requested_type]
        return sorted(assets, key=lambda asset: asset.created_at, reverse=True)

    def get_asset(self, asset_id: str) -> MiMoVoiceAsset:
        normalized_id = _strip_asset_voice_prefix(asset_id)
        for asset in self._load_assets():
            if asset.id == normalized_id:
                return asset
        raise MiMoVoiceAssetError(f"MiMo voice asset not found: {asset_id}")

    def create_design_asset(
        self,
        *,
        name: str,
        voice_design_prompt: str,
        description: str = "",
    ) -> MiMoVoiceAsset:
        clean_name = _require_text(name, "name")
        prompt = _require_text(voice_design_prompt, "voice_design_prompt")
        now = _utc_now()
        asset = MiMoVoiceAsset(
            id=_build_asset_id("design"),
            name=clean_name,
            asset_type="design",
            model=MIMO_V25_TTS_VOICE_DESIGN_MODEL,
            description=str(description or "").strip(),
            voice_design_prompt=prompt,
            created_at=now,
            updated_at=now,
        )
        self._append_asset(asset)
        return asset

    def create_clone_asset(
        self,
        *,
        name: str,
        audio_data_url: str,
        description: str = "",
    ) -> MiMoVoiceAsset:
        clean_name = _require_text(name, "name")
        mime_type, audio_bytes = _decode_audio_data_url(audio_data_url)
        return self._create_clone_asset_record(
            name=clean_name,
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            description=description,
        )

    def create_clone_asset_from_bytes(
        self,
        *,
        name: str,
        audio_bytes: bytes,
        mime_type: str,
        description: str = "",
    ) -> MiMoVoiceAsset:
        clean_name = _require_text(name, "name")
        audio_payload = bytes(audio_bytes or b"")
        if not audio_payload:
            raise MiMoVoiceAssetError("audio file cannot be empty")
        clean_mime_type = _require_mimo_clone_audio_mime_type(mime_type)
        return self._create_clone_asset_record(
            name=clean_name,
            audio_bytes=audio_payload,
            mime_type=clean_mime_type,
            description=description,
        )

    def _create_clone_asset_record(
        self,
        *,
        name: str,
        audio_bytes: bytes,
        mime_type: str,
        description: str = "",
    ) -> MiMoVoiceAsset:
        now = _utc_now()
        asset_id = _build_asset_id("clone")
        extension = mimetypes.guess_extension(mime_type) or ".bin"
        relative_path = f"clone_samples/{asset_id}{extension}"
        target_path = self.root_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(audio_bytes)
        asset = MiMoVoiceAsset(
            id=asset_id,
            name=name,
            asset_type="clone",
            model=MIMO_V25_TTS_VOICE_CLONE_MODEL,
            description=str(description or "").strip(),
            mime_type=mime_type,
            audio_path=relative_path,
            created_at=now,
            updated_at=now,
        )
        self._append_asset(asset)
        return asset

    def delete_asset(self, asset_id: str) -> bool:
        normalized_id = _strip_asset_voice_prefix(asset_id)
        assets = list(self._load_assets())
        kept = [asset for asset in assets if asset.id != normalized_id]
        if len(kept) == len(assets):
            return False
        removed = next(asset for asset in assets if asset.id == normalized_id)
        if removed.audio_path:
            audio_path = (self.root_dir / removed.audio_path).resolve()
            root = self.root_dir.resolve()
            if root in audio_path.parents and audio_path.exists():
                audio_path.unlink()
        self._save_assets(kept)
        return True

    def resolve_tts_params(self, asset_id: str) -> Dict[str, Any]:
        asset = self.get_asset(asset_id)
        if asset.asset_type == "design":
            return {
                "mimo_voice_asset_id": asset.id,
                "voice_design_prompt": asset.voice_design_prompt,
                "voice_description": asset.voice_design_prompt,
            }
        if asset.asset_type == "clone":
            return {
                "mimo_voice_asset_id": asset.id,
                "voice_clone_data_url": self._load_clone_asset_data_url(asset),
            }
        raise MiMoVoiceAssetError(f"Unsupported MiMo voice asset type: {asset.asset_type}")

    def _load_clone_asset_data_url(self, asset: MiMoVoiceAsset) -> str:
        if not asset.audio_path:
            raise MiMoVoiceAssetError(f"MiMo clone asset missing audio_path: {asset.id}")
        audio_path = (self.root_dir / asset.audio_path).resolve()
        root = self.root_dir.resolve()
        if root not in audio_path.parents or not audio_path.exists():
            raise MiMoVoiceAssetError(f"MiMo clone asset audio file not found: {asset.id}")
        encoded = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        mime_type = _require_mimo_clone_audio_mime_type(asset.mime_type)
        return f"data:{mime_type};base64,{encoded}"

    def _append_asset(self, asset: MiMoVoiceAsset) -> None:
        assets = list(self._load_assets())
        assets.append(asset)
        self._save_assets(assets)

    def _load_assets(self) -> Iterable[MiMoVoiceAsset]:
        if not self.index_path.exists():
            return []
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MiMoVoiceAssetError(f"Failed to load MiMo voice asset index: {exc}") from exc
        raw_assets = payload.get("assets") if isinstance(payload, dict) else []
        if not isinstance(raw_assets, list):
            return []
        return [
            asset
            for item in raw_assets
            if isinstance(item, dict)
            for asset in [MiMoVoiceAsset.from_dict(item)]
            if asset.id and asset.asset_type and asset.model
        ]

    def _save_assets(self, assets: Iterable[MiMoVoiceAsset]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        payload = {"assets": [asset.to_dict() for asset in assets]}
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def list_mimo_voice_asset_presets(model: str) -> List[Dict[str, Any]]:
    normalized_model = normalize_audiobook_tts_model(model, default="")
    if normalized_model not in {MIMO_V25_TTS_VOICE_CLONE_MODEL, MIMO_V25_TTS_VOICE_DESIGN_MODEL}:
        return []
    return [asset.to_voice_preset() for asset in MiMoVoiceAssetStore().list_assets(model=normalized_model)]


def resolve_mimo_voice_asset_tts_params(asset_id: str) -> Dict[str, Any]:
    return MiMoVoiceAssetStore().resolve_tts_params(asset_id)


def merge_mimo_voice_asset_tts_params(config: Dict[str, Any]) -> Dict[str, Any]:
    asset_id = str(config.get("mimo_voice_asset_id") or "").strip()
    if not asset_id:
        asset_id = _strip_asset_voice_prefix(str(config.get("voice_id") or config.get("speaker") or "").strip())
    if not asset_id:
        return dict(config)
    params = resolve_mimo_voice_asset_tts_params(asset_id)
    return {**config, **params}


def _require_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MiMoVoiceAssetError(f"{field_name} cannot be empty")
    return text


def _build_asset_id(asset_type: str) -> str:
    return f"mimo_{asset_type}_{secrets.token_hex(8)}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_asset_voice_prefix(value: str) -> str:
    text = str(value or "").strip()
    for prefix in ("mimo_clone:", "mimo_design:"):
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def _decode_audio_data_url(data_url: str) -> tuple[str, bytes]:
    match = _DATA_URL_RE.match(str(data_url or "").strip())
    if not match:
        raise MiMoVoiceAssetError("audio_data_url must be data:{MIME_TYPE};base64,...")
    mime_type = _require_mimo_clone_audio_mime_type(match.group("mime"))
    try:
        audio_bytes = base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MiMoVoiceAssetError("audio_data_url contains invalid base64") from exc
    if not audio_bytes:
        raise MiMoVoiceAssetError("audio_data_url cannot be empty")
    return mime_type, audio_bytes


def _require_audio_mime_type(value: str) -> str:
    mime_type = _normalize_audio_mime_type(value)
    if not mime_type.startswith("audio/"):
        raise MiMoVoiceAssetError("audio file must use an audio MIME type")
    return mime_type


def _require_mimo_clone_audio_mime_type(value: str) -> str:
    audio_mime_type = _require_audio_mime_type(value)
    mime_type = _MIMO_CLONE_AUDIO_MIME_ALIASES.get(audio_mime_type, audio_mime_type)
    if mime_type not in MIMO_CLONE_SUPPORTED_AUDIO_MIME_TYPES:
        raise MiMoVoiceAssetError(_MIMO_CLONE_AUDIO_FORMAT_ERROR)
    return mime_type


def _normalize_audio_mime_type(value: str) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()
