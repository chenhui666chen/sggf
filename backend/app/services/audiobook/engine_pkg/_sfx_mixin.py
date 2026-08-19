from __future__ import annotations

import asyncio
import logging
import time
import json
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from dataclasses import asdict, is_dataclass

from ..script_adapter import AudiobookScriptAgent, ScriptSegment, ChapterStructure
from ..voice_manager_factory import create_voice_manager
from ..audio_mixer import AudioMixer, sfx_loudness_plan
from app.services.chapter_adaptation_assets import build_audio_adaptation_hint
from core.unified_media_runtime import create_tts_engine
from app.services.audiobook.audio_library_paths import (
    get_audio_library_dir,
    resolve_audio_library_file_path,
)

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
        ducking_reduction_db = audio_fx.get("sound_effect_ducking_reduction_db", -4.0)
        ducking_chunk_ms = audio_fx.get("sound_effect_ducking_chunk_ms", 250)
        applied_count = 0
        skipped_count = 0
        
        for item in timeline_items:
            file_ref = item.get("file")
            timestamp = item.get("timestamp", 0.0)

            # 根据时间线中的类型和音量，计算响度归一化目标与相对音量偏移：
            # 归一化把不同源能量的素材统一到类型响度基准（见 audio_mixer.SFX_TARGET_LOUDNESS_DBFS），
            # volume 参数（0~1，0.5 为默认）由此成为真实相对响度，避免触发音被人声掩蔽
            effect_type_str = item.get("type", "action")
            normalize_target_dbfs, effect_volume_offset = sfx_loudness_plan(
                effect_type_str, item.get("volume", 0.5)
            )
            duration = item.get("duration")
            fade_in = item.get("fade_in", 0.0)
            fade_out = item.get("fade_out", 0.0)
            loop = bool(item.get("loop")) or effect_type_str == "environment"

            if not file_ref:
                skipped_count += 1
                continue
            
            effect_path = resolve_audio_library_file_path(file_ref, base_dir)
            if not effect_path:
                effect_name = Path(file_ref).stem or str(item.get("description") or "").strip()
                if effect_name:
                    sound_effect_root = (base_dir / "sound_effects").resolve()
                    for candidate in sound_effect_root.rglob("*"):
                        if not candidate.is_file() or candidate.stem != effect_name:
                            continue
                        effect_path = resolve_audio_library_file_path(candidate, base_dir)
                        if effect_path:
                            break
            if not effect_path:
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
                result_audio = self.audio_mixer.add_sound_effect(
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
                    normalize_target_dbfs=normalize_target_dbfs,
                )
                # add_sound_effect 内部失败/空窗时原样返回入参对象：
                # 用对象同一性区分真实叠加与静默跳过，避免 applied 计数误导
                if result_audio is mixed_audio:
                    logger.warning("⚠️ 音效叠加未生效（静默跳过）: %s @%sms", effect_path, position_ms)
                    skipped_count += 1
                else:
                    mixed_audio = result_audio
                    applied_count += 1
            except Exception as e:
                logger.warning(f"⚠️ 叠加音效失败 {effect_path}: {e}")
                skipped_count += 1

        logger.info("🎛 音效时间线处理完成: applied=%s skipped=%s", applied_count, skipped_count)
        return mixed_audio

