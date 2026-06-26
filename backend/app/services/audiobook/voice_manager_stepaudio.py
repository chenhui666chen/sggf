"""StepAudio 2.5 TTS voice manager."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .stepaudio_voice_assets import (
    StepAudioVoiceAssetError,
    merge_stepaudio_voice_asset_tts_params,
)
from .tts_model_ids import STEPAUDIO_25_TTS_MODEL, normalize_audiobook_tts_model
from .voice_catalog import load_voice_catalog_for_model
from .voice_manager import VoiceManager, VoiceProfile

logger = logging.getLogger(__name__)


@dataclass
class StepAudioVoiceProfile(VoiceProfile):
    asset_params: Dict[str, Any] = field(default_factory=dict)

    def get_tts_params(self, emotion: str = "") -> Dict[str, Any]:
        params = super().get_tts_params(emotion)
        if self.asset_params:
            params.update(self.asset_params)
        return params


class StepAudioVoiceManager(VoiceManager):
    """Voice manager for StepAudio preset and contextual TTS voices."""

    DEFAULT_NARRATOR_VOICE_ID = "cixingnansheng"

    def __init__(self, model: str = STEPAUDIO_25_TTS_MODEL):
        super().__init__()
        self.model = normalize_audiobook_tts_model(model)
        self.voice_catalog: Dict[str, Any] = {"voices": [], "voices_by_id": {}}
        self._load_catalog()
        logger.info("StepAudio VoiceManager initialized with %s voices", len(self.voice_catalog.get("voices", [])))

    def _load_catalog(self) -> None:
        try:
            self.voice_catalog = load_voice_catalog_for_model(self.model)
        except Exception as exc:
            logger.warning("Failed to load StepAudio voice catalog: %s", exc)
            self.voice_catalog = {"voices": [], "voices_by_id": {}}

    def get_voices(self) -> List[Dict[str, Any]]:
        return list(self.voice_catalog.get("voices") or [])

    def get_voice_entry(self, voice_id: str) -> Optional[Dict[str, Any]]:
        return self.voice_catalog.get("voices_by_id", {}).get(voice_id)

    def _build_profile(
        self,
        character_name: str,
        voice_id: str,
        voice_config: Optional[Dict[str, Any]] = None,
    ) -> VoiceProfile:
        config = voice_config or {}
        asset_id = str(config.get("stepaudio_voice_asset_id") or "").strip()
        is_asset_voice = voice_id.startswith("stepaudio_clone:") or bool(asset_id)
        entry = None if is_asset_voice else self.get_voice_entry(voice_id)
        entry = entry or self.get_voice_entry(self.DEFAULT_NARRATOR_VOICE_ID)
        if not entry:
            raise ValueError("StepAudio voice catalog is empty")

        defaults = entry.get("default_params") or {}
        profile_config = {
            "pitch_base": int(config.get("pitch", defaults.get("pitch", 50)) or 50),
            "speed_base": float(config.get("speed", defaults.get("speed", 1.0)) or 1.0),
            "volume_base": int(config.get("volume", defaults.get("volume", 50)) or 50),
            "default_emotion": "calm",
        }
        self._apply_voice_type_config(profile_config, config.get("voice_type"))
        speaker_id = str(entry.get("speaker") or entry.get("id") or voice_id)
        profile_voice_id = str(entry.get("id") or voice_id)
        if is_asset_voice:
            profile_voice_id = voice_id or f"stepaudio_clone:{asset_id}"
            speaker_id = profile_voice_id
        return StepAudioVoiceProfile(
            voice_id=profile_voice_id,
            character_name=character_name,
            gender=str(entry.get("gender") or "neutral").lower(),
            age_group=str(entry.get("category") or "adult").lower(),
            personality=str(config.get("personality") or entry.get("style") or "calm").lower(),
            tts_model=self.model,
            tts_speaker_id=speaker_id,
            pitch_base=profile_config["pitch_base"],
            speed_base=profile_config["speed_base"],
            volume_base=profile_config["volume_base"],
            default_emotion=profile_config["default_emotion"],
            asset_params=_resolve_stepaudio_asset_extra_params(config, speaker_id),
        )

    def get_narrator_voice(self) -> VoiceProfile:
        if "旁白" not in self.character_voices:
            self.character_voices["旁白"] = self._build_profile("旁白", self.DEFAULT_NARRATOR_VOICE_ID)
        return self.character_voices["旁白"]

    def get_voice(self, character_name: str) -> Optional[VoiceProfile]:
        return self.character_voices.get(character_name)

    def assign_voice(
        self,
        character_name: str,
        character_info: Optional[Dict[str, Any]] = None,
    ) -> VoiceProfile:
        voice_id = self.select_voice_for_character(character_name, character_info)
        profile = self._build_profile(character_name, voice_id)
        self.character_voices[character_name] = profile
        self.used_voice_ids.add(profile.voice_id)
        return profile

    def apply_project_voice_mapping(
        self,
        voice_mapping: Dict[str, Any],
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        del character_profiles
        for character_name, raw_config in (voice_mapping or {}).items():
            if not character_name:
                continue
            config = raw_config if isinstance(raw_config, dict) else {"voice_id": raw_config}
            voice_id = str(config.get("voice_id") or config.get("speaker") or "").strip()
            if str(config.get("stepaudio_voice_asset_id") or "").strip() and not voice_id:
                voice_id = f"stepaudio_clone:{config['stepaudio_voice_asset_id']}"
            if not voice_id or not self.validate_voice(voice_id):
                voice_id = self.select_voice_for_character(str(character_name))
            profile = self._build_profile(str(character_name), voice_id, config)
            self.character_voices[str(character_name)] = profile
            self.used_voice_ids.add(profile.voice_id)

    def select_voice_for_character(
        self,
        character_name: str,
        character_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        del character_name, character_info
        return self.DEFAULT_NARRATOR_VOICE_ID

    def validate_voice(self, voice_id: str) -> bool:
        if str(voice_id or "").strip().startswith("stepaudio_clone:"):
            return True
        return voice_id in self.voice_catalog.get("voices_by_id", {})

    def get_supported_emotions(self) -> List[str]:
        return ["happy", "sad", "angry", "fearful", "surprised", "calm", "tender", "tense"]

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "voices": self.get_voices(),
            "emotions": self.get_supported_emotions(),
            "supports_global_context": True,
            "supports_inline_context": True,
            "supports_voice_clone": True,
        }


def _resolve_stepaudio_asset_extra_params(config: Dict[str, Any], speaker_id: str) -> Dict[str, Any]:
    asset_id = str(config.get("stepaudio_voice_asset_id") or "").strip()
    if not asset_id and str(speaker_id or "").startswith("stepaudio_clone:"):
        asset_id = str(speaker_id).split(":", 1)[1].strip()
    if not asset_id:
        return {}
    try:
        return {
            key: value
            for key, value in merge_stepaudio_voice_asset_tts_params(
                {**config, "stepaudio_voice_asset_id": asset_id}
            ).items()
            if key.startswith("stepaudio_") or key == "voice_sample_path"
        }
    except StepAudioVoiceAssetError as exc:
        logger.warning("Failed to resolve StepAudio voice asset %s: %s", asset_id, exc)
        return {"stepaudio_voice_asset_id": asset_id}
