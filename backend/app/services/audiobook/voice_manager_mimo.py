"""MiMo V2.5 TTS voice manager."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from .tts_model_ids import (
    MIMO_V25_TTS_MODEL,
    MIMO_V25_TTS_VOICE_CLONE_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    normalize_audiobook_tts_model,
)
from .mimo_voice_assets import MiMoVoiceAssetError, merge_mimo_voice_asset_tts_params
from .voice_catalog import load_voice_catalog_for_model
from .voice_manager import VoiceManager, VoiceProfile

logger = logging.getLogger(__name__)


@dataclass
class MiMoInlineVoiceProfile:
    voice_id: str
    character_name: str
    tts_model: str
    pitch_base: int = 50
    speed_base: float = 1.0
    volume_base: int = 50
    default_emotion: str = "neutral"
    voice_clone_data_url: str = ""
    voice_design_prompt: str = ""
    mimo_voice_asset_id: str = ""
    personality: str = "calm"

    @property
    def tts_speaker_id(self) -> str:
        return self.voice_id

    def get_tts_params(self, emotion: str = "") -> Dict[str, Any]:
        emotion = (emotion or "").strip() or self.default_emotion or "neutral"
        params: Dict[str, Any] = {
            "speaker": self.voice_id,
            "pitch": int(max(0, min(100, self.pitch_base))),
            "speed": float(max(0.5, min(2.0, self.speed_base))),
            "volume": int(max(0, min(100, self.volume_base))),
            "emotion": emotion,
            "voice_description": self.voice_design_prompt,
        }
        if self.voice_clone_data_url:
            params["voice_clone_data_url"] = self.voice_clone_data_url
        if self.voice_design_prompt:
            params["voice_design_prompt"] = self.voice_design_prompt
        if self.mimo_voice_asset_id:
            params["mimo_voice_asset_id"] = self.mimo_voice_asset_id
        return params

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MiMoVoiceManager(VoiceManager):
    """Voice manager for the MiMo preset-voice model."""

    DEFAULT_NARRATOR_VOICE_ID = "mimo_default"
    DEFAULT_FEMALE_VOICE_ID = "冰糖"
    DEFAULT_MALE_VOICE_ID = "苏打"

    def __init__(self, model: str = MIMO_V25_TTS_MODEL):
        super().__init__()
        self.model = normalize_audiobook_tts_model(model)
        self.voice_catalog: Dict[str, Any] = {"voices": [], "voices_by_id": {}}
        self._load_catalog()
        logger.info("MiMo VoiceManager initialized with %s voices", len(self.voice_catalog.get("voices", [])))

    def _uses_inline_custom_voice(self) -> bool:
        return self.model in {
            MIMO_V25_TTS_VOICE_CLONE_MODEL,
            MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        }

    def _load_catalog(self) -> None:
        try:
            self.voice_catalog = load_voice_catalog_for_model(self.model)
        except Exception as exc:
            logger.warning("Failed to load MiMo voice catalog: %s", exc)
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
    ) -> VoiceProfile | MiMoInlineVoiceProfile:
        if self._uses_inline_custom_voice():
            return self._build_inline_profile(character_name, voice_id, voice_config)

        entry = self.get_voice_entry(voice_id) or self.get_voice_entry(self.DEFAULT_NARRATOR_VOICE_ID)
        if not entry:
            raise ValueError("MiMo voice catalog is empty")

        defaults = entry.get("default_params") or {}
        config = voice_config or {}
        profile_config = {
            "pitch_base": int(config.get("pitch", defaults.get("pitch", 50)) or 50),
            "speed_base": float(config.get("speed", defaults.get("speed", 1.0)) or 1.0),
            "volume_base": int(config.get("volume", defaults.get("volume", 50)) or 50),
            "default_emotion": "calm",
        }
        self._apply_voice_type_config(profile_config, config.get("voice_type"))
        return VoiceProfile(
            voice_id=str(entry.get("id") or voice_id),
            character_name=character_name,
            gender=str(entry.get("gender") or "neutral").lower(),
            age_group=str(entry.get("category") or "adult").lower(),
            personality=str(config.get("personality") or entry.get("style") or "calm").lower(),
            tts_model=self.model,
            tts_speaker_id=str(entry.get("speaker") or entry.get("id") or voice_id),
            pitch_base=profile_config["pitch_base"],
            speed_base=profile_config["speed_base"],
            volume_base=profile_config["volume_base"],
            default_emotion=profile_config["default_emotion"],
        )

    def _build_inline_profile(
        self,
        character_name: str,
        voice_id: str,
        voice_config: Optional[Dict[str, Any]] = None,
    ) -> MiMoInlineVoiceProfile:
        config = voice_config or {}
        try:
            config = merge_mimo_voice_asset_tts_params(config)
        except MiMoVoiceAssetError as exc:
            logger.warning("Failed to resolve MiMo voice asset for %s: %s", character_name, exc)

        def _int_value(value: Any, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        def _float_value(value: Any, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        pitch = _int_value(config.get("pitch"), 50)
        speed = _float_value(config.get("speed"), 1.0)
        volume = _int_value(config.get("volume"), 50)
        profile_config = {
            "pitch_base": pitch,
            "speed_base": speed,
            "volume_base": volume,
            "default_emotion": "neutral",
        }
        self._apply_voice_type_config(profile_config, config.get("voice_type"))
        return MiMoInlineVoiceProfile(
            voice_id=str(voice_id or config.get("speaker") or "").strip(),
            character_name=character_name,
            tts_model=self.model,
            pitch_base=profile_config["pitch_base"],
            speed_base=profile_config["speed_base"],
            volume_base=profile_config["volume_base"],
            default_emotion=profile_config["default_emotion"],
            voice_clone_data_url=str(config.get("voice_clone_data_url") or "").strip(),
            voice_design_prompt=str(config.get("voice_design_prompt") or "").strip(),
            mimo_voice_asset_id=str(config.get("mimo_voice_asset_id") or "").strip(),
            personality=str(config.get("personality") or "calm").lower(),
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
            if self._uses_inline_custom_voice():
                profile = self._build_profile(str(character_name), voice_id, config)
                self.character_voices[str(character_name)] = profile
                if profile.voice_id:
                    self.used_voice_ids.add(profile.voice_id)
                continue
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
        character_info = character_info or {}
        gender = str(character_info.get("gender") or "").strip().lower()
        voices = self.get_voices()
        candidates: List[Dict[str, Any]] = []

        for voice in voices:
            voice_id = str(voice.get("id") or "")
            if voice_id == self.DEFAULT_NARRATOR_VOICE_ID:
                continue
            voice_gender = str(voice.get("gender") or "").strip().lower()
            if gender in {"male", "female"} and voice_gender and voice_gender != gender:
                continue
            candidates.append(voice)

        available = [voice for voice in candidates if voice.get("id") not in self.used_voice_ids] or candidates
        if available:
            return str(available[0].get("id"))

        return self.DEFAULT_FEMALE_VOICE_ID if gender == "female" else self.DEFAULT_MALE_VOICE_ID

    def validate_voice(self, voice_id: str) -> bool:
        return voice_id in self.voice_catalog.get("voices_by_id", {})

    def get_supported_emotions(self) -> List[str]:
        return ["happy", "sad", "angry", "fearful", "surprised", "calm", "tender", "tense"]

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "voices": self.get_voices(),
            "emotions": self.get_supported_emotions(),
            "supports_director_mode": True,
            "supports_audio_tags": True,
            "supports_singing": True,
        }
