# -*- coding: utf-8 -*-
"""兼容层：CharacterProfile / AudioMarker（与旧 scripter.py 字段完全一致的契约对象）。

下游消费方（storyboarder_pkg/_prompts 的 to_wanx_audio_description 探测、
dreamweaver 的 character_profiles / audio_markers payload 键）依赖这些结构，
重写时原样保留，禁止改字段名。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List


@dataclass
class CharacterProfile:
    """角色档案 - 用于通义万相2.6角色一致性"""

    character_id: str
    name: str
    reference_video_path: str = ""
    reference_image_path: str = ""
    voice_reference_path: str = ""
    appearance_description: str = ""
    personality_traits: List[str] = field(default_factory=list)
    voice_style: str = "natural"
    voice_id: str = ""
    voice_profile_id: str = ""
    importance: str = "secondary"
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_id": self.character_id,
            "name": self.name,
            "reference_video_path": self.reference_video_path,
            "reference_image_path": self.reference_image_path,
            "voice_reference_path": self.voice_reference_path,
            "appearance_description": self.appearance_description,
            "personality_traits": self.personality_traits,
            "voice_style": self.voice_style,
            "voice_id": self.voice_id,
            "voice_profile_id": self.voice_profile_id,
            "importance": self.importance,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CharacterProfile":
        return cls(
            character_id=data.get("character_id", ""),
            name=data.get("name", ""),
            reference_video_path=data.get("reference_video_path", ""),
            reference_image_path=data.get("reference_image_path", ""),
            voice_reference_path=data.get("voice_reference_path", ""),
            appearance_description=data.get("appearance_description", ""),
            personality_traits=data.get("personality_traits", []),
            voice_style=data.get("voice_style", "natural"),
            voice_id=data.get("voice_id", ""),
            voice_profile_id=data.get("voice_profile_id", ""),
            importance=data.get("importance", "secondary"),
            created_at=data.get("created_at", ""),
        )


@dataclass
class AudioMarker:
    """音频标记 - 用于通义万相2.6声画同步"""

    scene_number: int
    character_name: str
    dialogue_line: str
    start_time: float = 0.0
    end_time: float = 0.0
    voice_style: str = "natural"
    emotion: str = "neutral"
    background_music: str = ""
    sound_effects: List[str] = field(default_factory=list)

    voice_tone: str = ""
    voice_speed: str = ""
    voice_color: str = ""
    voice_accent: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene_number": self.scene_number,
            "character_name": self.character_name,
            "dialogue_line": self.dialogue_line,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "voice_style": self.voice_style,
            "emotion": self.emotion,
            "background_music": self.background_music,
            "sound_effects": self.sound_effects,
            "voice_tone": self.voice_tone,
            "voice_speed": self.voice_speed,
            "voice_color": self.voice_color,
            "voice_accent": self.voice_accent,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioMarker":
        return cls(
            scene_number=data.get("scene_number", 0),
            character_name=data.get("character_name", ""),
            dialogue_line=data.get("dialogue_line", ""),
            start_time=data.get("start_time", 0.0),
            end_time=data.get("end_time", 0.0),
            voice_style=data.get("voice_style", "natural"),
            emotion=data.get("emotion", "neutral"),
            background_music=data.get("background_music", ""),
            sound_effects=data.get("sound_effects", []),
            voice_tone=data.get("voice_tone", ""),
            voice_speed=data.get("voice_speed", ""),
            voice_color=data.get("voice_color", ""),
            voice_accent=data.get("voice_accent", ""),
        )

    def to_wanx_audio_description(self) -> str:
        """转换为阿里云百炼的声音描述格式（storyboarder_pkg/_prompts 依赖此方法）。"""
        parts: List[str] = []

        if self.dialogue_line:
            voice_parts = [f"{self.character_name}说道：{self.dialogue_line}"]

            if self.emotion:
                emotion_map = {
                    "neutral": "平静",
                    "happy": "开心",
                    "sad": "悲伤",
                    "angry": "愤怒",
                    "fearful": "恐惧",
                    "surprised": "惊讶",
                    "tense": "紧张",
                    "calm": "温和",
                    "excited": "兴奋",
                }
                voice_parts.append(f"语气{emotion_map.get(self.emotion, self.emotion)}")

            if self.voice_speed:
                speed_map = {
                    "slow": "缓慢",
                    "normal": "适中",
                    "fast": "急促",
                    "very_fast": "极快",
                }
                voice_parts.append(f"语速{speed_map.get(self.voice_speed, self.voice_speed)}")

            if self.voice_tone:
                voice_parts.append(self.voice_tone)

            if self.voice_color:
                voice_parts.append(f"声音{self.voice_color}")

            if self.voice_accent:
                voice_parts.append(f"{self.voice_accent}口音")

            parts.append("人声：" + "，".join(voice_parts))

        if self.sound_effects:
            for effect in self.sound_effects:
                parts.append(f"音效：{effect}")

        if self.background_music:
            parts.append(f"背景音乐：{self.background_music}")

        return "；".join(parts) if parts else ""
