# -*- coding: utf-8 -*-
"""Phase 3.4 有声书增强：声音 DNA 卡 + AM-15 演播评价变体 + sound_design 注入。

声音 DNA 卡（角色×音色×语速×情感基线）——规范 voice_consistency_manager；
演播评价标准（AM-15 变体：感知=ASR+音频特征，评价=演播标准）；
sound_design 4 项注入 BGM/音效（emotion_first_music / music_scene_matching /
sound_design_formula / sfx_search_method）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VoiceDNA:
    """声音 DNA 卡：角色 × 音色 × 语速 × 情感基线（规范 voice_consistency_manager）。"""
    character_id: str
    character_name: str
    voice_id: str = ""
    voice_style: str = "natural"          # natural / warm / bright / deep / youthful
    speech_rate: str = "normal"           # slow / normal / fast / very_fast
    emotion_baseline: str = "neutral"     # neutral / warm / tense / melancholic
    pitch_range: str = "medium"           # low / medium / high
    accent: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_id": self.character_id, "character_name": self.character_name,
            "voice_id": self.voice_id, "voice_style": self.voice_style,
            "speech_rate": self.speech_rate, "emotion_baseline": self.emotion_baseline,
            "pitch_range": self.pitch_range, "accent": self.accent,
        }


# 情感基线 → 音色/语速推荐（emotion_first_music 联动）
EMOTION_VOICE_MAP: Dict[str, Dict[str, str]] = {
    "neutral": {"voice_style": "natural", "speech_rate": "normal", "pitch_range": "medium"},
    "happy": {"voice_style": "bright", "speech_rate": "fast", "pitch_range": "high"},
    "sad": {"voice_style": "deep", "speech_rate": "slow", "pitch_range": "low"},
    "angry": {"voice_style": "deep", "speech_rate": "fast", "pitch_range": "low"},
    "fearful": {"voice_style": "natural", "speech_rate": "very_fast", "pitch_range": "high"},
    "surprised": {"voice_style": "bright", "speech_rate": "fast", "pitch_range": "high"},
    "tense": {"voice_style": "deep", "speech_rate": "normal", "pitch_range": "low"},
    "calm": {"voice_style": "warm", "speech_rate": "slow", "pitch_range": "medium"},
    "excited": {"voice_style": "bright", "speech_rate": "very_fast", "pitch_range": "high"},
}


def build_voice_dna_from_character(
    *,
    character_id: str,
    name: str,
    emotion: str = "neutral",
    voice_id: str = "",
) -> VoiceDNA:
    """从角色 + 当前情感基线生成声音 DNA 卡。"""
    rec = EMOTION_VOICE_MAP.get(emotion, EMOTION_VOICE_MAP["neutral"])
    return VoiceDNA(
        character_id=character_id, character_name=name, voice_id=voice_id,
        voice_style=rec["voice_style"], speech_rate=rec["speech_rate"],
        emotion_baseline=emotion, pitch_range=rec["pitch_range"],
    )


def audiobook_am15_eval(
    *,
    audio_paths: Optional[List[str]] = None,
    voice_dna_cards: Optional[List[VoiceDNA]] = None,
    asr_transcript: str = "",
) -> Dict[str, Any]:
    """AM-15 演播评价变体：感知=ASR+音频特征，评价=演播标准。

    无音频文件时降级骨架输出（可测）。
    """
    perception: Dict[str, Any] = {"asr_transcript_chars": len(asr_transcript)}
    if audio_paths:
        perception["audio_files"] = len(audio_paths)
    else:
        perception["audio_files"] = 0

    evaluation: Dict[str, Any] = {
        "voice_consistency": "pending",  # 检查 DNA 卡一致性
        "speech_rate_alignment": "pending",  # 语速 vs 情感基线
        "emotion_delivery": "pending",  # 情感表达准确度
        "narrative_pacing": "pending",  # 叙事节奏
    }
    if voice_dna_cards:
        evaluation["voice_dna_count"] = len(voice_dna_cards)
        evaluation["voice_consistency"] = "checked" if len({c.voice_id for c in voice_dna_cards if c.voice_id}) <= 1 else "mismatch"

    return {
        "schema": "am15_audiobook_variant/1.0",
        "perception": perception,
        "evaluation": evaluation,
        "verdict": "pass" if voice_dna_cards else "pending_voice_dna",
    }


# sound_design 4 项注入（emotion_first_music / music_scene_matching /
# sound_design_formula / sfx_search_method）
SOUND_DESIGN_PRESETS = {
    "emotion_first_music": {
        "principle": "情绪优先配乐：先定本场情绪基调 → 再选 BGM 风格与速度",
        "emotion_to_genre": {
            "neutral": "ambient", "happy": "uplifting", "sad": "melancholic",
            "angry": "intense", "fearful": "tension", "tense": "suspense",
            "calm": "serene", "excited": "energetic",
        },
    },
    "music_scene_matching": {
        "principle": "场景音乐匹配：BGM 速度/乐器/混响随场景类型调整",
        "scene_to_mix": {"室内": "dry_close", "室外": "ambient_wide", "回忆": "reverb_long"},
    },
    "sound_design_formula": {
        "principle": "声音设计公式：人声(对话+情感+语速) + 音效(材质+行为+环境) + BGM(情绪+风格)",
        "layers": ["voice", "sfx", "bgm"],
    },
    "sfx_search_method": {
        "principle": "音效检索：动作关键词 + 材质 + 环境三层匹配",
        "example": "金属碰撞声 = 材质(金属) + 行为(碰撞) + 环境(室内回响)",
    },
}


def inject_sound_design(
    *,
    storyboard: Optional[List[Dict[str, Any]]] = None,
    emotion: str = "neutral",
    scene_type: str = "室内",
) -> Dict[str, Any]:
    """sound_design 4 项注入：为有声书混音管线输出 BGM/音效配置。"""
    music_genre = SOUND_DESIGN_PRESETS["emotion_first_music"]["emotion_to_genre"].get(emotion, "ambient")
    mix_style = SOUND_DESIGN_PRESETS["music_scene_matching"]["scene_to_mix"].get(scene_type, "dry_close")
    sfx_hints: List[str] = []
    for shot in (storyboard or [])[:20]:
        if isinstance(shot, dict):
            action = str(shot.get("motion_desc") or shot.get("desc") or "").strip()
            if action:
                sfx_hints.append(f"{action[:40]} → 音效候选（材质+行为+环境）")
    return {
        "bgm": {"genre": music_genre, "mix_style": mix_style, "emotion": emotion},
        "sfx_count": len(sfx_hints), "sfx_hints": sfx_hints[:10],
        "formula": SOUND_DESIGN_PRESETS["sound_design_formula"]["principle"],
        "sfx_method": SOUND_DESIGN_PRESETS["sfx_search_method"]["principle"],
    }
