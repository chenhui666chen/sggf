from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from .voice_catalog import get_voice_entry, list_supported_voices

logger = logging.getLogger(__name__)


@dataclass
class CosyVoiceV3PlusProfile:
    voice_id: str
    character_name: str
    tts_speaker_id: str
    pitch_base: int = 50
    speed_base: float = 1.0
    volume_base: int = 50
    default_emotion: str = "neutral"

    def get_tts_params(self, emotion: str = "neutral") -> Dict[str, Any]:
        emotion = (emotion or "").strip() or self.default_emotion or "neutral"
        # cosyvoice-v3-plus 支持 instruct；这里仅按 emotion 控制是否开启 instruct 模式。
        return {
            "speaker": self.tts_speaker_id,
            "pitch": int(max(0, min(100, self.pitch_base))),
            "speed": float(max(0.5, min(2.0, self.speed_base))),
            "volume": int(max(0, min(100, self.volume_base))),
            "emotion": emotion,
            "use_instruct_mode": emotion != "neutral",
        }

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CosyVoiceV3PlusVoiceManager:
    """
    CosyVoice v3-plus 专用 VoiceManager。

    目标：
    - 声线 ID 空间与 qwen3-tts-flash 完全隔离（不做 legacy 映射）
    - 项目级音色配置按模型独立存取（由上层负责选择）
    """

    def __init__(self) -> None:
        voices = list_supported_voices("cosyvoice-v3-plus")
        self._voices: List[Dict[str, Any]] = list(voices)
        self._voices_by_id: Dict[str, Dict[str, Any]] = {
            v.get("id"): v for v in self._voices if isinstance(v, dict) and v.get("id")
        }

        self._profiles_by_character: Dict[str, CosyVoiceV3PlusProfile] = {}

        self._narrator_voice_id = self._pick_default_narrator_voice_id()
        self._assign_cursor_male = 0
        self._assign_cursor_female = 0

    @property
    def voice_profiles(self) -> Dict[str, CosyVoiceV3PlusProfile]:
        return self._profiles_by_character

    def _pick_default_narrator_voice_id(self) -> str:
        for voice in self._voices:
            if (voice.get("category") or "").lower() == "narrator":
                return str(voice.get("id"))
        # fallback：取第一条
        if self._voices:
            return str(self._voices[0].get("id"))
        return "longanyang"

    def _available_voice_ids(self, gender: str = "") -> List[str]:
        gender = (gender or "").strip().lower()
        if gender in ("male", "female"):
            ids = [vid for vid, v in self._voices_by_id.items() if (v.get("gender") or "").lower() == gender]
            if ids:
                return ids
        return list(self._voices_by_id.keys())

    def get_narrator_voice(self) -> CosyVoiceV3PlusProfile:
        return self._profiles_by_character.get("旁白") or self._create_profile(
            character_name="旁白",
            voice_id=self._narrator_voice_id,
            overrides=None,
        )

    def get_voice(self, character_name: str) -> Optional[CosyVoiceV3PlusProfile]:
        character_name = (character_name or "").strip()
        if not character_name:
            return None
        return self._profiles_by_character.get(character_name)

    def assign_voice(self, character_name: str, character_info: Optional[dict] = None) -> CosyVoiceV3PlusProfile:
        character_name = (character_name or "").strip() or "未知角色"
        existing = self._profiles_by_character.get(character_name)
        if existing:
            return existing

        traits = character_info or {}
        gender = (traits.get("gender") or "").strip().lower()
        candidates = self._available_voice_ids(gender)
        if not candidates:
            candidates = [self._narrator_voice_id]

        if gender == "female":
            voice_id = candidates[self._assign_cursor_female % len(candidates)]
            self._assign_cursor_female += 1
        else:
            voice_id = candidates[self._assign_cursor_male % len(candidates)]
            self._assign_cursor_male += 1

        return self._create_profile(character_name=character_name, voice_id=voice_id, overrides=None)

    def apply_project_voice_mapping(self, mapping: Dict[str, Dict]) -> None:
        """
        mapping: { "角色名": {"voice_id": "...", "volume": 50, "speed": 1.0, "pitch": 50}, ... }
        """
        for character_name, cfg in (mapping or {}).items():
            if not character_name:
                continue
            voice_id = (cfg or {}).get("voice_id")
            if not voice_id:
                continue
            overrides = {
                "volume": cfg.get("volume"),
                "speed": cfg.get("speed"),
                "pitch": cfg.get("pitch"),
            }
            self._create_profile(character_name=str(character_name), voice_id=str(voice_id), overrides=overrides)

    def _create_profile(
        self,
        character_name: str,
        voice_id: str,
        overrides: Optional[dict],
    ) -> CosyVoiceV3PlusProfile:
        voice_id = (voice_id or "").strip()

        # 兼容旧占位音色 ID（历史项目配置可能写入这些值）
        legacy_aliases = {
            "longanzhi_v3": "longanyang",
            "longanyun_v3": "longanyang",
            "longyichen_v3": "longanyang",
            "longwanjun_v3": "longanhuan",
            "longanwen_v3": "longanhuan",
        }
        resolved_voice_id = legacy_aliases.get(voice_id, voice_id)

        entry = (
            self._voices_by_id.get(resolved_voice_id)
            or get_voice_entry(resolved_voice_id, "cosyvoice-v3-plus")
            or {}
        )
        # 允许用户输入“复刻音色 voice_id”等未收录于本地目录的声线。
        # 这类 voice_id 直接透传给 TTS 引擎；若无效将由提供商侧报错。

        speaker = str(entry.get("speaker") or resolved_voice_id)
        defaults = entry.get("default_params") if isinstance(entry.get("default_params"), dict) else {}
        pitch = int(defaults.get("pitch", 50))
        speed = float(defaults.get("speed", 1.0))
        volume = int(defaults.get("volume", 50))

        if overrides:
            if overrides.get("pitch") is not None:
                try:
                    pitch = int(overrides["pitch"])
                except Exception:
                    pass
            if overrides.get("speed") is not None:
                try:
                    speed = float(overrides["speed"])
                except Exception:
                    pass
            if overrides.get("volume") is not None:
                try:
                    volume = int(overrides["volume"])
                except Exception:
                    pass

        profile = CosyVoiceV3PlusProfile(
            voice_id=resolved_voice_id or speaker,
            character_name=character_name,
            tts_speaker_id=speaker,
            pitch_base=pitch,
            speed_base=speed,
            volume_base=volume,
            default_emotion="neutral",
        )
        self._profiles_by_character[character_name] = profile
        return profile
