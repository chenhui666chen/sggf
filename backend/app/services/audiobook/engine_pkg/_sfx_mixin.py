from __future__ import annotations

import asyncio
import logging
import time
import math
import json
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from dataclasses import asdict, is_dataclass

from ..script_adapter import AudiobookScriptAgent, ScriptSegment, ChapterStructure
from ..voice_manager_factory import create_voice_manager
from ..audio_mixer import AudioMixer
from app.services.chapter_adaptation_assets import build_audio_adaptation_hint
from core.unified_media_runtime import create_tts_engine
from app.services.audiobook.audio_library_paths import get_audio_library_dir

try:
    from ..agent_dispatch_client import client as tts_dispatch_client
    from ..agent_dispatch_client import TTSDispatchResult
    TTS_DISPATCH_AVAILABLE = True
except ImportError:
    TTS_DISPATCH_AVAILABLE = False
    tts_dispatch_client = None
    TTSDispatchResult = None

# 导入专业Agent
from ..agents import (
    AudioDirector,
    VoiceDesigner,
    SoundEffectDesigner,
    MusicComposer,
)

logger = logging.getLogger(__name__)

class SfxMixin:
    def _apply_sound_effects(
        self,
        audio_data: bytes,
        effect_timeline: Dict[str, Any],
    ) -> bytes:
        """根据音效时间线，将音效叠加到音频上"""
        if not audio_data:
            return audio_data
        
        timeline_items = effect_timeline.get("timeline") or []
        if not timeline_items:
            return audio_data
        
        mixed_audio = audio_data
        base_dir = get_audio_library_dir()
        audio_fx = getattr(self, "_audio_fx_config", None) or {}
        ducking_enabled = audio_fx.get("sound_effect_ducking", True)
        ducking_priority = audio_fx.get("sound_effect_priority", "dialogue")
        ducking_threshold_dbfs = audio_fx.get("sound_effect_ducking_threshold_dbfs", -35.0)
        ducking_reduction_db = audio_fx.get("sound_effect_ducking_reduction_db", -6.0)
        ducking_chunk_ms = audio_fx.get("sound_effect_ducking_chunk_ms", 250)
        applied_count = 0
        skipped_count = 0
        
        for item in timeline_items:
            file_ref = item.get("file")
            timestamp = item.get("timestamp", 0.0)

            # 根据时间线中的类型和音量，计算对应的音量衰减（dB）
            effect_type_str = item.get("type", "action")
            # 🔧 已降低所有音效约 5-6dB，使其相对人声更小
            base_gain_map = {
                "environment": -14.0,  # 环境音（降低 6dB）
                "action": -14.0,       # 动作音（降低 6dB）
                "emotion": -16.0,      # 情绪音（降低 6dB）
                "transition": -18.0,   # 过渡音（降低 6dB）
            }
            base_gain = base_gain_map.get(effect_type_str, -16.0)
            duration = item.get("duration")
            fade_in = item.get("fade_in", 0.0)
            fade_out = item.get("fade_out", 0.0)
            loop = bool(item.get("loop")) or effect_type_str == "environment"

            # timeline volume 约定为 0.0~1.0，0.5 视为“默认音量”
            timeline_volume = item.get("volume", 0.5)
            try:
                timeline_volume = float(timeline_volume)
            except (TypeError, ValueError):
                timeline_volume = 0.5
            # 避免 0 导致 log10 计算错误，做一点下限保护
            timeline_volume = max(0.05, min(1.0, timeline_volume))

            # 以 0.5 为基准做相对音量调整
            relative = timeline_volume / 0.5
            volume_adjust_db = 20 * math.log10(relative)
            effect_volume_offset = base_gain + volume_adjust_db

            if not file_ref:
                skipped_count += 1
                continue
            
            effect_path = Path(file_ref)
            if not effect_path.is_absolute():
                # 相对路径：相对于 audio_library 根目录
                effect_path = base_dir / file_ref
            if not effect_path.exists():
                effect_name = Path(file_ref).stem or str(item.get("description") or "").strip()
                if effect_name:
                    for candidate in (base_dir / "sound_effects").rglob(f"{effect_name}.*"):
                        effect_path = candidate
                        break
            if not effect_path.exists():
                logger.warning(f"⚠️ 音效文件不存在: {effect_path}")
                skipped_count += 1
                continue
            
            try:
                with effect_path.open("rb") as f:
                    effect_bytes = f.read()
                position_ms = int(timestamp * 1000)
                effect_duration_ms = None
                try:
                    if duration is not None:
                        duration_val = float(duration)
                        if duration_val <= 0:
                            effect_duration_ms = max(0, len(mixed_audio) - position_ms) if loop else None
                        else:
                            effect_duration_ms = int(duration_val * 1000)
                except (TypeError, ValueError):
                    effect_duration_ms = None
                fade_in_ms = int(float(fade_in) * 1000) if fade_in else 0
                fade_out_ms = int(float(fade_out) * 1000) if fade_out else 0
                mixed_audio = self.audio_mixer.add_sound_effect(
                    mixed_audio,
                    effect_bytes,
                    position_ms=position_ms,
                    effect_volume_offset=effect_volume_offset,
                    effect_duration_ms=effect_duration_ms,
                    fade_in_ms=fade_in_ms,
                    fade_out_ms=fade_out_ms,
                    loop_fill=bool(loop),
                    ducking_enabled=bool(ducking_enabled),
                    ducking_priority=str(ducking_priority or "dialogue"),
                    ducking_threshold_dbfs=float(ducking_threshold_dbfs),
                    ducking_reduction_db=float(ducking_reduction_db),
                    ducking_chunk_ms=int(ducking_chunk_ms),
                )
                applied_count += 1
            except Exception as e:
                logger.warning(f"⚠️ 叠加音效失败 {effect_path}: {e}")
                skipped_count += 1

        logger.info("🎛 音效时间线处理完成: applied=%s skipped=%s", applied_count, skipped_count)
        return mixed_audio

