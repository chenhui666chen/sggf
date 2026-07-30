"""Doubao Seed-TTS 2.0 voice manager."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .tts_model_ids import SEED_TTS_20_EXPRESSIVE_MODEL, normalize_audiobook_tts_model
from .voice_catalog import load_voice_catalog_for_model
from .voice_manager import VoiceManager, VoiceProfile

logger = logging.getLogger(__name__)


class SeedTTSVoiceManager(VoiceManager):
    """Voice manager for Doubao Seed-TTS preset voices."""

    DEFAULT_NARRATOR_VOICE_ID = "zh_female_vv_uranus_bigtts"

    def __init__(self, model: str = SEED_TTS_20_EXPRESSIVE_MODEL):
        super().__init__()
        self.model = normalize_audiobook_tts_model(model)
        self.voice_catalog: Dict[str, Any] = {"voices": [], "voices_by_id": {}}
        self._load_catalog()
        logger.info("Seed-TTS VoiceManager initialized with %s voices", len(self.voice_catalog.get("voices", [])))

    def _load_catalog(self) -> None:
        try:
            self.voice_catalog = load_voice_catalog_for_model(self.model)
        except Exception as exc:
            logger.warning("Failed to load Seed-TTS voice catalog: %s", exc)
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
        entry = self.get_voice_entry(voice_id)
        if entry is None:
            entry = {
                "id": voice_id,
                "speaker": voice_id,
                "gender": config.get("gender") or "neutral",
                "category": config.get("age_group") or "adult",
                "style": config.get("personality") or "calm",
                "default_params": {},
            }
        if not entry.get("id") or not entry.get("speaker"):
            raise ValueError("Seed-TTS voice catalog is empty")

        defaults = entry.get("default_params") or {}
        profile_config = {
            "pitch_base": int(config.get("pitch", defaults.get("pitch", 50)) or 50),
            "speed_base": float(config.get("speed", defaults.get("speed", 1.0)) or 1.0),
            "volume_base": int(config.get("volume", defaults.get("volume", 50)) or 50),
            "default_emotion": "calm",
        }
        self._apply_voice_type_config(profile_config, config.get("voice_type"))
        speaker_id = str(entry.get("speaker") or entry.get("id") or voice_id)
        return VoiceProfile(
            voice_id=str(entry.get("id") or voice_id),
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
            if not voice_id:
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
        # 账号级声音复刻 ID 不会出现在静态系统音色目录中，只能由供应商校验。
        return bool(str(voice_id or "").strip())

    def get_supported_emotions(self) -> List[str]:
        return ["happy", "sad", "angry", "fearful", "surprised", "calm", "tender", "tense"]

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "voices": self.get_voices(),
            "emotions": self.get_supported_emotions(),
            "supports_query_response": True,
            "supports_voice_clone": True,
            "supports_emotion_mixing": True,
        }
