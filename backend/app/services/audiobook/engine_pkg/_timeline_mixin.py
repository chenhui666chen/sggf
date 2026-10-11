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
from ..duration_estimator import estimate_narration_duration_seconds
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
    SoundEffectDesigner,
    MusicComposer,
)

logger = logging.getLogger(__name__)

class TimelineMixin:
    @staticmethod
    def _normalize_editor_timeline_edits(edits: Any) -> Dict[str, Dict[str, float]]:
        if not isinstance(edits, dict):
            return {}

        normalized: Dict[str, Dict[str, float]] = {}
        for key, raw_edit in edits.items():
            key_text = str(key or "").strip()
            if not key_text or not isinstance(raw_edit, dict):
                continue
            try:
                start_unit = float(raw_edit.get("startUnit"))
                duration_units = float(raw_edit.get("durationUnits"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(start_unit) or not math.isfinite(duration_units):
                continue
            if start_unit < 0 or duration_units <= 0:
                continue
            normalized[key_text] = {
                "startUnit": start_unit,
                "durationUnits": duration_units,
            }
            if "volume" in raw_edit:
                try:
                    volume = float(raw_edit.get("volume"))
                except (TypeError, ValueError):
                    volume = math.nan
                if math.isfinite(volume):
                    normalized[key_text]["volume"] = max(0.0, min(1.0, volume))
        return normalized

    @staticmethod
    def _build_unit_offsets(segment_units: List[float]) -> List[Dict[str, float]]:
        offsets: List[Dict[str, float]] = []
        current = 0.0
        for unit in segment_units:
            safe_unit = max(0.0, float(unit or 0.0))
            offsets.append({"start": current, "duration": safe_unit})
            current += safe_unit
        return offsets

    @staticmethod
    def _resolve_editor_edit_seconds(
        edit: Dict[str, float],
        unit_offsets: List[Dict[str, float]],
        actual_offsets: List[Dict[str, float]],
        total_actual_duration: float,
    ) -> Optional[Dict[str, float]]:
        if not unit_offsets or not actual_offsets:
            return None

        edit_start_unit = float(edit["startUnit"])
        edit_duration_units = float(edit["durationUnits"])
        edit_end_unit = edit_start_unit + edit_duration_units

        start_seconds: Optional[float] = None
        end_seconds: Optional[float] = None

        for unit_offset, actual_offset in zip(unit_offsets, actual_offsets):
            unit_start = float(unit_offset["start"])
            unit_duration = float(unit_offset["duration"])
            unit_end = unit_start + unit_duration
            actual_start = float(actual_offset["start"])
            actual_duration = max(0.0, float(actual_offset["duration"]))

            if unit_duration <= 0:
                continue

            if start_seconds is None and unit_start <= edit_start_unit <= unit_end:
                ratio = max(0.0, min(1.0, (edit_start_unit - unit_start) / unit_duration))
                start_seconds = actual_start + ratio * actual_duration

            if end_seconds is None and unit_start <= edit_end_unit <= unit_end:
                ratio = max(0.0, min(1.0, (edit_end_unit - unit_start) / unit_duration))
                end_seconds = actual_start + ratio * actual_duration

        if start_seconds is None:
            if edit_start_unit <= 0:
                start_seconds = 0.0
            else:
                return None
        if end_seconds is None:
            end_seconds = total_actual_duration

        start_seconds = max(0.0, min(total_actual_duration, start_seconds))
        end_seconds = max(start_seconds, min(total_actual_duration, end_seconds))

        return {
            "timestamp": start_seconds,
            "duration": max(0.0, end_seconds - start_seconds),
        }

    @staticmethod
    def _parse_editor_timeline_key(key: str) -> Optional[Dict[str, int]]:
        parts = str(key or "").split("-")
        if len(parts) < 3:
            return None
        track = parts[0]
        if track not in {"sfx", "music"}:
            return None
        try:
            return {
                "track": track,
                "segment_index": int(parts[1]),
                "cue_index": int(parts[2]) if track == "sfx" else 0,
                "end_segment_index": int(parts[2]) if track == "music" else int(parts[1]),
            }
        except (TypeError, ValueError):
            return None

    def _apply_editor_timeline_edits(
        self,
        edits: Any,
        *,
        segment_units: List[float],
        actual_durations: List[float],
    ) -> None:
        normalized_edits = self._normalize_editor_timeline_edits(edits)
        if not normalized_edits:
            return

        unit_offsets = self._build_unit_offsets(segment_units)
        actual_offsets = self._build_segment_offsets(actual_durations)
        total_actual_duration = sum(max(0.0, float(duration or 0.0)) for duration in actual_durations)
        if total_actual_duration <= 0:
            return

        track_counters = {"sfx": {}, "music": {}}
        for key, edit in normalized_edits.items():
            parsed = self._parse_editor_timeline_key(key)
            if not parsed:
                continue

            seconds = self._resolve_editor_edit_seconds(
                edit,
                unit_offsets,
                actual_offsets,
                total_actual_duration,
            )
            if not seconds:
                continue

            timeline_attr = "_last_effect_timeline" if parsed["track"] == "sfx" else "_last_music_timeline"
            timeline_payload = getattr(self, timeline_attr, None)
            timeline_items = (
                timeline_payload.get("timeline")
                if isinstance(timeline_payload, dict)
                else None
            )
            if not isinstance(timeline_items, list):
                continue

            for item in timeline_items:
                if not isinstance(item, dict):
                    continue
                scene_index = self._parse_scene_index(str(item.get("scene_id") or ""))
                if scene_index != parsed["segment_index"]:
                    continue
                if parsed["track"] == "music":
                    item["timestamp"] = seconds["timestamp"]
                    item["duration"] = seconds["duration"]
                    if "volume" in edit:
                        item["volume"] = edit["volume"]
                    item["editor_timeline_key"] = key
                    break
                cue_count = track_counters[parsed["track"]].get(scene_index, 0)
                track_counters[parsed["track"]][scene_index] = cue_count + 1
                if cue_count != parsed["cue_index"]:
                    continue
                item["timestamp"] = seconds["timestamp"]
                item["duration"] = seconds["duration"]
                if "volume" in edit:
                    item["volume"] = edit["volume"]
                item["editor_timeline_key"] = key
                break

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
            durations.append(estimate_narration_duration_seconds(text))
        return durations

    # 场景内环境音允许超出所属片段结尾的宽限（秒），避免在片段边界被硬切
    ENVIRONMENT_SCENE_GRACE_SECONDS = 5.0

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
        item_scene_indices: List[Optional[int]] = []
        for item in timeline.get("timeline", []):
            new_item = dict(item)
            scene_id = str(item.get("scene_id") or "")
            item_scene_indices.append(self._parse_scene_index(scene_id))
            if new_item.get("editor_timeline_key"):
                adjusted_items.append(new_item)
                continue
            idx = item_scene_indices[-1]
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
                scene_idx = item_scene_indices[idx]
                if scene_idx is not None and scene_idx < len(actual_offsets):
                    # 剧本标注的场景环境音（如锁链、雨声）只覆盖所属场景并留少量宽限，
                    # 避免被拉伸到下一环境音/章尾而从章头响到章尾
                    scene_end = (
                        actual_offsets[scene_idx]["start"]
                        + actual_offsets[scene_idx]["duration"]
                    )
                    next_start = min(
                        scene_end + self.ENVIRONMENT_SCENE_GRACE_SECONDS,
                        total_actual_duration,
                    )
                else:
                    # 全章环境床（scene_id=ambient 等）仍覆盖到下一环境床或章节结尾
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

        actual_durations = self._audio_durations_for_segments(script_segments, audio_list)
        self._realign_timelines_with_durations(script_segments, actual_durations)

    def _realign_timelines_with_render_chunks(
        self,
        script_segments: List[ScriptSegment],
        render_chunks: List[Any],
        audio_list: List[bytes],
    ) -> None:
        if not audio_list or not script_segments or not render_chunks:
            return

        estimated_durations = self._estimate_segment_durations(script_segments)
        source_durations = [0.0 for _ in script_segments]
        chunk_durations = self._audio_durations_for_segments(render_chunks, audio_list)

        for chunk_index, chunk in enumerate(render_chunks):
            if chunk_index >= len(chunk_durations):
                break
            source_indices = getattr(chunk, "source_segment_indices", None) or []
            if not source_indices:
                continue
            try:
                source_index = int(source_indices[0])
            except Exception:
                continue
            if source_index < 0 or source_index >= len(source_durations):
                continue
            source_durations[source_index] += max(0.0, float(chunk_durations[chunk_index] or 0.0))

        for index, duration in enumerate(source_durations):
            if duration <= 0:
                source_durations[index] = estimated_durations[index] if index < len(estimated_durations) else 0.2

        self._realign_timelines_with_durations(script_segments, source_durations)

    def _realign_timelines_with_mixed_timing(
        self,
        script_segments: List[ScriptSegment],
        mixer_segments: List[Any],
        segment_timings: List[Dict[str, Any]],
    ) -> None:
        """Align automatic effect/music cues to the same post-mix timeline as speech."""
        if not script_segments or not mixer_segments or not segment_timings:
            return

        estimated_durations = self._estimate_segment_durations(script_segments)
        estimated_offsets = self._build_segment_offsets(estimated_durations)
        actual_offsets: List[Dict[str, float]] = [
            {"start": 0.0, "duration": 0.0} for _ in script_segments
        ]
        assigned = [False for _ in script_segments]

        for timing in segment_timings:
            if not isinstance(timing, dict):
                continue
            try:
                mixer_segment_index = int(timing.get("index"))
            except (TypeError, ValueError):
                continue
            if mixer_segment_index < 0 or mixer_segment_index >= len(mixer_segments):
                continue
            segment = mixer_segments[mixer_segment_index]
            source_indices = getattr(segment, "source_segment_indices", None) or []
            if not source_indices:
                continue
            try:
                source_index = int(source_indices[0])
                start = max(0.0, float(timing.get("start") or 0.0))
                duration = max(0.0, float(timing.get("duration") or 0.0))
            except (TypeError, ValueError):
                continue
            if source_index < 0 or source_index >= len(actual_offsets):
                continue
            if not assigned[source_index]:
                actual_offsets[source_index] = {"start": start, "duration": duration}
                assigned[source_index] = True
            else:
                current = actual_offsets[source_index]
                current["start"] = min(current["start"], start)
                current["duration"] += duration

        previous_end = 0.0
        for index, offset in enumerate(actual_offsets):
            if not assigned[index]:
                offset["start"] = previous_end
                offset["duration"] = estimated_durations[index] if index < len(estimated_durations) else 0.2
            previous_end = max(previous_end, offset["start"] + offset["duration"])

        total_actual = max(
            previous_end,
            max((float(item.get("end") or 0.0) for item in segment_timings if isinstance(item, dict)), default=0.0),
        )
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

    def _audio_durations_for_segments(
        self,
        segments: List[Any],
        audio_list: List[bytes],
    ) -> List[float]:
        estimated_durations = self._estimate_segment_durations(segments)
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
        return actual_durations

    def _realign_timelines_with_durations(
        self,
        script_segments: List[ScriptSegment],
        actual_durations: List[float],
    ) -> None:
        if not actual_durations or not script_segments:
            return

        estimated_durations = self._estimate_segment_durations(script_segments)
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

