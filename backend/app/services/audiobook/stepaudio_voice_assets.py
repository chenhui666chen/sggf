from __future__ import annotations

import json
import mimetypes
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx

from app.services.audiobook.tts_model_ids import (
    STEPAUDIO_3_TTS_MODEL,
    normalize_audiobook_tts_model,
)

DEFAULT_STEPAUDIO_VOICE_ASSET_DIR = Path("backend/data/stepaudio_voice_assets")
STEPAUDIO_API_DEFAULT_BASE_URL = "https://api.stepfun.com/v1"
STEPAUDIO_FILE_UPLOAD_TIMEOUT_SECONDS = 60.0
STEPAUDIO_CLONE_SUPPORTED_AUDIO_MIME_TYPES = {"audio/mpeg", "audio/wav"}
_STEPAUDIO_CLONE_AUDIO_MIME_ALIASES = {
    "audio/mp3": "audio/mpeg",
    "audio/x-mp3": "audio/mpeg",
    "audio/wave": "audio/wav",
    "audio/x-wav": "audio/wav",
}
_STEPAUDIO_CLONE_AUDIO_FORMAT_ERROR = "StepAudio Voice Clone 参考样本仅支持 mp3 或 wav 音频"


class StepAudioVoiceAssetError(ValueError):
    pass


@dataclass(frozen=True)
class StepAudioVoiceAsset:
    id: str
    name: str
    asset_type: str
    model: str
    description: str = ""
    sample_text: str = ""
    file_id: str = ""
    mime_type: str = ""
    audio_path: str = ""
    created_at: str = ""
    updated_at: str = ""
    owner_user_id: Optional[int] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "StepAudioVoiceAsset":
        return cls(
            id=str(payload.get("id") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            asset_type=str(payload.get("asset_type") or payload.get("type") or "").strip(),
            model=normalize_audiobook_tts_model(str(payload.get("model") or ""), default=""),
            description=str(payload.get("description") or "").strip(),
            sample_text=str(payload.get("sample_text") or "").strip(),
            file_id=str(payload.get("file_id") or "").strip(),
            mime_type=str(payload.get("mime_type") or "").strip(),
            audio_path=str(payload.get("audio_path") or "").strip(),
            created_at=str(payload.get("created_at") or "").strip(),
            updated_at=str(payload.get("updated_at") or "").strip(),
            owner_user_id=(
                int(payload["owner_user_id"])
                if payload.get("owner_user_id") not in (None, "")
                else None
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "asset_type": self.asset_type,
            "model": self.model,
            "description": self.description,
            "sample_text": self.sample_text,
            "file_id": self.file_id,
            "mime_type": self.mime_type,
            "audio_path": self.audio_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "owner_user_id": self.owner_user_id,
        }

    def to_voice_preset(self) -> Dict[str, Any]:
        description = self.description or self.sample_text or self.file_id or self.id
        preset = {
            "id": f"stepaudio_clone:{self.id}",
            "speaker": f"stepaudio_clone:{self.id}",
            "label": self.name or self.id,
            "category": "custom",
            "customType": "clone",
            "provider": "stepaudio",
            "description": description,
            "style": "voice_clone_reference",
            "supportsInstruct": True,
            "default_params": {"volume": 50, "speed": 1.0},
        }
        if not self.file_id:
            preset["disabled"] = True
            preset["disabledReason"] = "StepAudio clone reference requires file_id for official voice preview"
        return preset


class StepAudioVoiceAssetStore:
    def __init__(self, root_dir: Path | str | None = None) -> None:
        self.root_dir = Path(root_dir or DEFAULT_STEPAUDIO_VOICE_ASSET_DIR)
        self.index_path = self.root_dir / "index.json"

    def list_assets(
        self,
        *,
        model: Optional[str] = None,
        asset_type: Optional[str] = None,
        owner_user_id: Optional[int] = None,
    ) -> List[StepAudioVoiceAsset]:
        normalized_model = normalize_audiobook_tts_model(model, default="") if model else ""
        requested_type = str(asset_type or "").strip()
        assets = list(self._load_assets())
        if owner_user_id is not None:
            assets = [asset for asset in assets if asset.owner_user_id == owner_user_id]
        if normalized_model:
            assets = [asset for asset in assets if asset.model == normalized_model]
        if requested_type:
            assets = [asset for asset in assets if asset.asset_type == requested_type]
        return sorted(assets, key=lambda asset: asset.created_at, reverse=True)

    def get_asset(self, asset_id: str, *, owner_user_id: Optional[int] = None) -> StepAudioVoiceAsset:
        normalized_id = _strip_asset_voice_prefix(asset_id)
        for asset in self._load_assets():
            if asset.id == normalized_id:
                if asset.owner_user_id is not None and asset.owner_user_id != owner_user_id:
                    raise StepAudioVoiceAssetError("StepAudio voice asset does not belong to this user")
                return asset
        raise StepAudioVoiceAssetError(f"StepAudio voice asset not found: {asset_id}")

    def create_clone_asset_from_bytes(
        self,
        *,
        name: str,
        audio_bytes: bytes,
        mime_type: str,
        sample_text: str = "",
        file_id: str = "",
        description: str = "",
        owner_user_id: Optional[int] = None,
    ) -> StepAudioVoiceAsset:
        clean_name = _require_text(name, "name")
        audio_payload = bytes(audio_bytes or b"")
        if not audio_payload:
            raise StepAudioVoiceAssetError("audio file cannot be empty")
        clean_mime_type = _require_stepaudio_clone_audio_mime_type(mime_type)
        now = _utc_now()
        asset_id = _build_asset_id("clone")
        extension = mimetypes.guess_extension(clean_mime_type) or ".bin"
        relative_path = f"clone_samples/{asset_id}{extension}"
        target_path = self.root_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(audio_payload)
        asset = StepAudioVoiceAsset(
            id=asset_id,
            name=clean_name,
            asset_type="clone",
            model=STEPAUDIO_3_TTS_MODEL,
            description=str(description or "").strip(),
            sample_text=str(sample_text or "").strip(),
            file_id=str(file_id or "").strip(),
            mime_type=clean_mime_type,
            audio_path=relative_path,
            created_at=now,
            updated_at=now,
            owner_user_id=owner_user_id,
        )
        self._append_asset(asset)
        return asset

    def delete_asset(self, asset_id: str, *, owner_user_id: Optional[int] = None) -> bool:
        normalized_id = _strip_asset_voice_prefix(asset_id)
        assets = list(self._load_assets())
        owner_assets = (
            [asset for asset in assets if asset.owner_user_id == owner_user_id]
            if owner_user_id is not None
            else assets
        )
        removed = next((asset for asset in owner_assets if asset.id == normalized_id), None)
        if removed is None:
            raise StepAudioVoiceAssetError("StepAudio voice asset does not belong to this user")
        kept = [asset for asset in assets if asset is not removed]
        if len(kept) == len(assets):
            return False
        if removed.audio_path:
            audio_path = (self.root_dir / removed.audio_path).resolve()
            root = self.root_dir.resolve()
            if root in audio_path.parents and audio_path.exists():
                audio_path.unlink()
        self._save_assets(kept)
        return True

    def resolve_tts_params(self, asset_id: str, *, owner_user_id: Optional[int] = None) -> Dict[str, Any]:
        asset = self.get_asset(asset_id, owner_user_id=owner_user_id)
        if asset.asset_type != "clone":
            raise StepAudioVoiceAssetError(f"Unsupported StepAudio voice asset type: {asset.asset_type}")
        audio_path = self._resolve_clone_asset_audio_path(asset)
        params: Dict[str, Any] = {
            "stepaudio_voice_asset_id": asset.id,
            "stepaudio_voice_sample_text": asset.sample_text,
            "stepaudio_voice_sample_mime_type": asset.mime_type,
            "voice_sample_path": str(audio_path),
        }
        if asset.file_id:
            params["stepaudio_voice_file_id"] = asset.file_id
        return params

    def _resolve_clone_asset_audio_path(self, asset: StepAudioVoiceAsset) -> Path:
        if not asset.audio_path:
            raise StepAudioVoiceAssetError(f"StepAudio clone asset missing audio_path: {asset.id}")
        audio_path = (self.root_dir / asset.audio_path).resolve()
        root = self.root_dir.resolve()
        if root not in audio_path.parents or not audio_path.exists():
            raise StepAudioVoiceAssetError(f"StepAudio clone asset audio file not found: {asset.id}")
        _require_stepaudio_clone_audio_mime_type(asset.mime_type)
        return audio_path

    def _append_asset(self, asset: StepAudioVoiceAsset) -> None:
        assets = list(self._load_assets())
        assets.append(asset)
        self._save_assets(assets)

    def _load_assets(self) -> Iterable[StepAudioVoiceAsset]:
        if not self.index_path.exists():
            return []
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StepAudioVoiceAssetError(f"Failed to load StepAudio voice asset index: {exc}") from exc
        raw_assets = payload.get("assets") if isinstance(payload, dict) else []
        if not isinstance(raw_assets, list):
            return []
        return [
            asset
            for item in raw_assets
            if isinstance(item, dict)
            for asset in [StepAudioVoiceAsset.from_dict(item)]
            if asset.id and asset.asset_type and asset.model
        ]

    def _save_assets(self, assets: Iterable[StepAudioVoiceAsset]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        payload = {"assets": [asset.to_dict() for asset in assets]}
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def list_stepaudio_voice_asset_presets(
    model: str,
    *,
    owner_user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    normalized_model = normalize_audiobook_tts_model(model, default="")
    if normalized_model != STEPAUDIO_3_TTS_MODEL:
        return []
    return [
        asset.to_voice_preset()
        for asset in StepAudioVoiceAssetStore().list_assets(
            model=normalized_model,
            owner_user_id=owner_user_id,
        )
    ]


def resolve_stepaudio_voice_asset_tts_params(
    asset_id: str,
    *,
    owner_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    return StepAudioVoiceAssetStore().resolve_tts_params(asset_id, owner_user_id=owner_user_id)


def merge_stepaudio_voice_asset_tts_params(
    config: Dict[str, Any],
    *,
    owner_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    asset_id = str(config.get("stepaudio_voice_asset_id") or "").strip()
    if not asset_id:
        asset_id = _strip_asset_voice_prefix(str(config.get("voice_id") or config.get("speaker") or "").strip())
    if not asset_id:
        return dict(config)
    params = resolve_stepaudio_voice_asset_tts_params(
        asset_id,
        owner_user_id=owner_user_id,
    )
    return {**config, **params}


def get_stepaudio_api_key() -> str:
    return str(os.getenv("STEP_API_KEY") or os.getenv("STEPFUN_API_KEY") or "").strip()


def validate_stepaudio_clone_audio_mime_type(mime_type: str) -> str:
    return _require_stepaudio_clone_audio_mime_type(mime_type)


async def upload_stepaudio_voice_reference_file(
    *,
    filename: str,
    content: bytes,
    mime_type: str,
    api_key: str,
) -> str:
    audio_payload = bytes(content or b"")
    if not audio_payload:
        raise StepAudioVoiceAssetError("audio file cannot be empty")
    clean_api_key = str(api_key or "").strip()
    if not clean_api_key:
        raise StepAudioVoiceAssetError("STEP_API_KEY or STEPFUN_API_KEY is required for StepAudio file upload")
    clean_mime_type = _require_stepaudio_clone_audio_mime_type(mime_type)
    safe_filename = str(filename or "").strip() or f"stepaudio-reference{mimetypes.guess_extension(clean_mime_type) or '.wav'}"
    base_url = str(os.getenv("STEPAUDIO_TTS_BASE_URL") or STEPAUDIO_API_DEFAULT_BASE_URL).rstrip("/")
    endpoint = f"{base_url}/files"
    try:
        async with httpx.AsyncClient(timeout=STEPAUDIO_FILE_UPLOAD_TIMEOUT_SECONDS) as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {clean_api_key}"},
                data={"purpose": "storage"},
                files={"file": (safe_filename, audio_payload, clean_mime_type)},
            )
    except httpx.HTTPError as exc:
        raise StepAudioVoiceAssetError(f"StepAudio file upload failed: {exc}") from exc
    if response.status_code not in {200, 201}:
        raise StepAudioVoiceAssetError(
            f"StepAudio file upload failed: {response.status_code} - {response.text[:200]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise StepAudioVoiceAssetError("StepAudio file upload response is not valid JSON") from exc
    file_id = str(payload.get("id") or "").strip() if isinstance(payload, dict) else ""
    if not file_id:
        raise StepAudioVoiceAssetError("StepAudio file upload response missing id")
    return file_id


def _require_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise StepAudioVoiceAssetError(f"{field_name} cannot be empty")
    return text


def _build_asset_id(asset_type: str) -> str:
    return f"stepaudio_{asset_type}_{secrets.token_hex(8)}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_asset_voice_prefix(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("stepaudio_clone:"):
        return text[len("stepaudio_clone:") :].strip()
    return text


def _require_audio_mime_type(value: str) -> str:
    mime_type = _normalize_audio_mime_type(value)
    if not mime_type.startswith("audio/"):
        raise StepAudioVoiceAssetError("audio file must use an audio MIME type")
    return mime_type


def _require_stepaudio_clone_audio_mime_type(value: str) -> str:
    audio_mime_type = _require_audio_mime_type(value)
    mime_type = _STEPAUDIO_CLONE_AUDIO_MIME_ALIASES.get(audio_mime_type, audio_mime_type)
    if mime_type not in STEPAUDIO_CLONE_SUPPORTED_AUDIO_MIME_TYPES:
        raise StepAudioVoiceAssetError(_STEPAUDIO_CLONE_AUDIO_FORMAT_ERROR)
    return mime_type


def _normalize_audio_mime_type(value: str) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()
