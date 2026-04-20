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

class TimelineMixin:
    @staticmethod
    def _parse_scene_index(scene_id: str) -> Optional[int]:
        if not scene_id:
            return None
        for prefix in ("scene_", "climax_", "shift_"):
            if scene_id.startswith(prefix):
                try:
                    return int(scene_id[len(prefix):])
                except ValueError:
                    return None
        return None

    @staticmethod
    def _build_segment_offsets(durations: List[float]) -> List[Dict[str, float]]:
        offsets: List[Dict[str, float]] = []
        current = 0.0
        for duration in durations:
            safe_duration = max(0.0, float(duration))
            offsets.append({"start": current, "duration": safe_duration})
            current += safe_duration
        return offsets

    @staticmethod
    def _estimate_segment_durations(script_segments: List[ScriptSegment]) -> List[float]:
        durations = []
        for seg in script_segments:
            text = getattr(seg, "text", "") or ""
            duration = len(text) / 10.0
            durations.append(max(duration, 0.2))
        return durations

    def _align_timeline_with_audio(
        self,
        timeline: Optional[Dict[str, Any]],
        estimated_offsets: List[Dict[str, float]],
        actual_offsets: List[Dict[str, float]],
        total_actual_duration: float,
        *,
        align_environment: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not timeline or not timeline.get("timeline"):
            return timeline

        adjusted_items: List[Dict[str, Any]] = []
        for item in timeline.get("timeline", []):
            new_item = dict(item)
            scene_id = str(item.get("scene_id") or "")
            idx = self._parse_scene_index(scene_id)
            if idx is not None and idx < len(estimated_offsets) and idx < len(actual_offsets):
                est_start = estimated_offsets[idx]["start"]
                actual_start = actual_offsets[idx]["start"]
                relative = max(0.0, float(item.get("timestamp", 0.0)) - est_start)
                new_item["timestamp"] = actual_start + relative
            elif scene_id == "ending":
                duration = float(item.get("duration") or 0.0)
                new_item["timestamp"] = max(0.0, total_actual_duration - duration)
            elif scene_id == "opening":
                new_item["timestamp"] = 0.0
            adjusted_items.append(new_item)

        if align_environment:
            env_indices = [
                idx for idx, item in enumerate(adjusted_items)
                if item.get("type") == "environment" or item.get("loop")
            ]
            for pos, idx in enumerate(env_indices):
                item = adjusted_items[idx]
                start = float(item.get("timestamp", 0.0))
                next_start = total_actual_duration
                if pos + 1 < len(env_indices):
                    next_start = float(adjusted_items[env_indices[pos + 1]].get("timestamp", total_actual_duration))
                if next_start <= start:
                    continue
                item["duration"] = max(0.0, next_start - start)
                item["loop"] = True

        timeline_copy = dict(timeline)
        timeline_copy["timeline"] = adjusted_items
        return timeline_copy

    def _realign_timelines_with_audio(
        self,
        script_segments: List[ScriptSegment],
        audio_list: List[bytes],
    ) -> None:
        if not audio_list or not script_segments:
            return

        estimated_durations = self._estimate_segment_durations(script_segments)
        actual_durations: List[float] = []
        for idx, audio in enumerate(audio_list):
            if not audio:
                actual_durations.append(estimated_durations[idx] if idx < len(estimated_durations) else 0.2)
                continue
            info = self.audio_mixer.get_audio_info(audio)
            duration = float(info.get("duration_seconds", 0.0) or 0.0)
            if duration <= 0 and idx < len(estimated_durations):
                duration = estimated_durations[idx]
            actual_durations.append(duration)

        estimated_offsets = self._build_segment_offsets(estimated_durations)
        actual_offsets = self._build_segment_offsets(actual_durations)
        total_actual = sum(actual_durations)

        self._last_effect_timeline = self._align_timeline_with_audio(
            self._last_effect_timeline,
            estimated_offsets,
            actual_offsets,
            total_actual,
            align_environment=True,
        )
        self._last_music_timeline = self._align_timeline_with_audio(
            self._last_music_timeline,
            estimated_offsets,
            actual_offsets,
            total_actual,
            align_environment=False,
        )

