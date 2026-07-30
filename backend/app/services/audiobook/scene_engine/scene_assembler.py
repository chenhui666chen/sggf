"""Assemble finalized Seed Audio scenes into one chapter artifact."""

from __future__ import annotations

import os
import logging
import math
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

from pydub import AudioSegment

from app.services.audiobook.timed_subtitles import (
    subtitle_items,
    subtitle_time_seconds,
)

from .chapter_pipeline import ChapterSceneRender
from .loudness_normalizer import (
    FFmpegLoudnessNormalizer,
    LoudnessNormalizationError,
)
from .models import SceneRenderPlan


logger = logging.getLogger(__name__)


class SceneAssemblyError(RuntimeError):
    """Raised when finalized scene audio cannot be assembled."""


@dataclass(frozen=True)
class SceneAssemblyTiming:
    scene_id: str
    start_s: float
    end_s: float
    duration_s: float
    pause_before_s: float
    audio_source: str


@dataclass(frozen=True)
class SceneAssemblySubtitleEntry:
    index: int
    scene_id: str
    start_s: float
    end_s: float
    text: str
    speaker: str | None = None
    emotion: str | None = None


@dataclass(frozen=True)
class SceneAssemblyResult:
    audio_path: Path
    duration_s: float
    scene_timings: Tuple[SceneAssemblyTiming, ...]
    subtitle_entries: Tuple[SceneAssemblySubtitleEntry, ...]
    output_format: str
    loudness_normalized: bool = False
    loudness_report: Mapping[str, Any] | None = None


@dataclass
class _PreparedSceneAudio:
    scene: ChapterSceneRender
    audio_path: Path
    audio_source: str
    audio: AudioSegment
    measurement: dict[str, float] | None = None
    gain_db: float = 0.0
    requested_gain_db: float = 0.0
    limited_by_true_peak: bool = False


class SceneAudioAssembler:
    """Concatenate finalized scene audio and offset timed subtitles."""

    SAME_CONTEXT_PAUSE_MS = 180
    UNKNOWN_CONTEXT_PAUSE_MS = 350
    LOCATION_CHANGE_PAUSE_MS = 750
    SCENE_BALANCE_MAX_GAIN_DB = 3.0
    SCENE_BALANCE_MIN_GAIN_DB = 0.25
    SCENE_BALANCE_TRUE_PEAK_CEILING_DBTP = -1.5

    def __init__(self, *, loudness_normalizer: Any | None = None) -> None:
        self.loudness_normalizer = (
            loudness_normalizer or FFmpegLoudnessNormalizer()
        )

    def assemble(
        self,
        scenes: Sequence[ChapterSceneRender],
        *,
        output_path: str | Path,
        output_format: str = "mp3",
        fallback_audio_paths: Mapping[str, str | Path] | None = None,
    ) -> SceneAssemblyResult:
        if not scenes:
            raise SceneAssemblyError("chapter_scenes_empty")

        prepared_scenes = self._prepare_scenes(scenes, fallback_audio_paths or {})
        scene_balancing = self._balance_scene_loudness(prepared_scenes)

        combined = AudioSegment.empty()
        scene_timings = []
        subtitle_entries = []
        previous_plan: SceneRenderPlan | None = None

        for prepared in prepared_scenes:
            scene = prepared.scene
            audio_source = prepared.audio_source
            audio = prepared.audio.apply_gain(prepared.gain_db)

            pause_ms = (
                0
                if previous_plan is None
                else self.transition_pause_ms(previous_plan, scene.plan)
            )
            if pause_ms:
                combined += AudioSegment.silent(
                    duration=pause_ms,
                    frame_rate=audio.frame_rate,
                )
            scene_start_s = len(combined) / 1000
            scene_duration_s = len(audio) / 1000
            combined += audio
            scene_end_s = len(combined) / 1000
            scene_timings.append(
                SceneAssemblyTiming(
                    scene_id=scene.plan.scene_id,
                    start_s=scene_start_s,
                    end_s=scene_end_s,
                    duration_s=scene_duration_s,
                    pause_before_s=pause_ms / 1000,
                    audio_source=audio_source,
                )
            )
            subtitle_entries.extend(
                self._offset_subtitles(
                    scene,
                    scene_start_s=scene_start_s,
                    scene_duration_s=scene_duration_s,
                    start_index=len(subtitle_entries) + 1,
                )
            )
            previous_plan = scene.plan

        normalized_format = self._normalize_output_format(output_format)
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        loudness_report = self._export_atomic(combined, target, normalized_format)
        loudness_report["scene_balancing"] = scene_balancing
        return SceneAssemblyResult(
            audio_path=target,
            duration_s=len(combined) / 1000,
            scene_timings=tuple(scene_timings),
            subtitle_entries=tuple(subtitle_entries),
            output_format=normalized_format,
            loudness_normalized=bool(loudness_report.get("normalized")),
            loudness_report=loudness_report,
        )

    def _prepare_scenes(
        self,
        scenes: Sequence[ChapterSceneRender],
        fallback_audio_paths: Mapping[str, str | Path],
    ) -> list[_PreparedSceneAudio]:
        prepared = []
        for scene in scenes:
            audio_path, audio_source = self._resolve_audio_path(
                scene,
                fallback_audio_paths,
            )
            try:
                audio = AudioSegment.from_file(audio_path)
            except Exception as exc:
                raise SceneAssemblyError(
                    f"scene_audio_not_decodable:{scene.plan.scene_id}"
                ) from exc
            if len(audio) <= 0:
                raise SceneAssemblyError(f"scene_audio_empty:{scene.plan.scene_id}")
            prepared.append(
                _PreparedSceneAudio(
                    scene=scene,
                    audio_path=audio_path,
                    audio_source=audio_source,
                    audio=audio,
                    measurement=self._measure_scene(audio_path, scene.plan),
                )
            )
        return prepared

    def _measure_scene(
        self,
        audio_path: Path,
        plan: SceneRenderPlan,
    ) -> dict[str, float] | None:
        measure = getattr(self.loudness_normalizer, "measure", None)
        if not callable(measure):
            return None
        try:
            raw_measurement = measure(audio_path)
        except Exception as exc:
            logger.warning(
                "场景响度测量失败，将跳过场景级校准: scene=%s error=%s",
                plan.scene_id,
                exc.__class__.__name__,
            )
            return None
        if not isinstance(raw_measurement, Mapping):
            return None
        input_i = self._finite_number(raw_measurement.get("input_i"))
        if input_i is None:
            return None
        input_tp = self._finite_number(raw_measurement.get("input_tp"))
        measurement = {"input_i": input_i}
        if input_tp is not None:
            measurement["input_tp"] = input_tp
        return measurement

    def _balance_scene_loudness(
        self,
        prepared_scenes: Sequence[_PreparedSceneAudio],
    ) -> dict[str, Any]:
        eligible = [
            item
            for item in prepared_scenes
            if item.scene.plan.expected_text.strip() and item.measurement is not None
        ]
        eligible_identities = {id(item) for item in eligible}
        report: dict[str, Any] = {
            "applied": False,
            "strategy": "dialogue_scene_median",
            "max_gain_db": self.SCENE_BALANCE_MAX_GAIN_DB,
            "min_gain_db": self.SCENE_BALANCE_MIN_GAIN_DB,
            "true_peak_ceiling_dbtp": self.SCENE_BALANCE_TRUE_PEAK_CEILING_DBTP,
            "eligible_scene_count": len(eligible),
            "scenes": [],
        }
        if len(eligible) < 2:
            report["reason"] = "insufficient_dialogue_scenes"
            report["scenes"] = [
                self._scene_balance_entry(item) for item in prepared_scenes
            ]
            return report

        target_i = float(
            statistics.median(
                item.measurement["input_i"] for item in eligible
            )
        )
        report["target_i"] = round(target_i, 4)
        for item in prepared_scenes:
            measurement = item.measurement
            if id(item) not in eligible_identities or measurement is None:
                report["scenes"].append(self._scene_balance_entry(item))
                continue

            requested_gain = self._clamp(
                target_i - measurement["input_i"],
                -self.SCENE_BALANCE_MAX_GAIN_DB,
                self.SCENE_BALANCE_MAX_GAIN_DB,
            )
            applied_gain = requested_gain
            limited_by_true_peak = False
            input_tp = measurement.get("input_tp")
            if applied_gain > 0:
                if input_tp is None:
                    applied_gain = 0.0
                    limited_by_true_peak = True
                else:
                    headroom = self.SCENE_BALANCE_TRUE_PEAK_CEILING_DBTP - input_tp
                    if headroom < applied_gain:
                        applied_gain = max(0.0, headroom)
                        limited_by_true_peak = True
            if abs(applied_gain) < self.SCENE_BALANCE_MIN_GAIN_DB:
                applied_gain = 0.0

            item.requested_gain_db = round(requested_gain, 4)
            item.gain_db = round(applied_gain, 4)
            item.limited_by_true_peak = limited_by_true_peak
            report["applied"] = report["applied"] or bool(item.gain_db)
            report["scenes"].append(self._scene_balance_entry(item))
        return report

    @staticmethod
    def _scene_balance_entry(item: _PreparedSceneAudio) -> dict[str, Any]:
        measurement = item.measurement or {}
        return {
            "scene_id": item.scene.plan.scene_id,
            "audio_source": item.audio_source,
            "eligible": bool(
                item.scene.plan.expected_text.strip() and item.measurement is not None
            ),
            "input_i": measurement.get("input_i"),
            "input_tp": measurement.get("input_tp"),
            "requested_gain_db": item.requested_gain_db,
            "gain_db": item.gain_db,
            "limited_by_true_peak": item.limited_by_true_peak,
        }

    @staticmethod
    def _finite_number(value: Any) -> float | None:
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return None
        return normalized if math.isfinite(normalized) else None

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    @classmethod
    def transition_pause_ms(
        cls,
        previous: SceneRenderPlan,
        following: SceneRenderPlan,
    ) -> int:
        previous_context = cls._boundary_context(previous.boundary_after)
        following_context = cls._boundary_context(following.boundary_before)
        if previous_context and following_context:
            if previous_context == following_context:
                return cls.SAME_CONTEXT_PAUSE_MS
            return cls.LOCATION_CHANGE_PAUSE_MS
        return cls.UNKNOWN_CONTEXT_PAUSE_MS

    @staticmethod
    def _boundary_context(value: str) -> str:
        parts = str(value or "").split("，", 1)
        return parts[1].strip().casefold() if len(parts) == 2 else ""

    @staticmethod
    def _resolve_audio_path(
        scene: ChapterSceneRender,
        fallback_audio_paths: Mapping[str, str | Path],
    ) -> tuple[Path, str]:
        path_value = scene.result.audio_path
        audio_source = "seed_scene"
        if scene.result.status == "legacy_stems":
            path_value = fallback_audio_paths.get(scene.plan.scene_id) or path_value
            audio_source = "legacy_stems"
        if not path_value:
            raise SceneAssemblyError(f"scene_audio_missing:{scene.plan.scene_id}")
        path = Path(path_value)
        if not path.exists() or not path.is_file():
            raise SceneAssemblyError(f"scene_audio_missing:{scene.plan.scene_id}")
        return path, audio_source

    @classmethod
    def _offset_subtitles(
        cls,
        scene: ChapterSceneRender,
        *,
        scene_start_s: float,
        scene_duration_s: float,
        start_index: int,
    ) -> list[SceneAssemblySubtitleEntry]:
        entries = []
        for raw_item in subtitle_items(scene.result.subtitle_payload):
            text = str(raw_item.get("text") or raw_item.get("transcript") or "").strip()
            if not text:
                continue
            local_start = subtitle_time_seconds(raw_item, "start")
            local_end = subtitle_time_seconds(raw_item, "end")
            if local_start is None or local_end is None:
                continue
            local_start = max(0.0, min(local_start, scene_duration_s))
            local_end = max(local_start, min(local_end, scene_duration_s))
            entries.append(
                SceneAssemblySubtitleEntry(
                    index=start_index + len(entries),
                    scene_id=scene.plan.scene_id,
                    start_s=scene_start_s + local_start,
                    end_s=scene_start_s + local_end,
                    text=text,
                    speaker=str(
                        raw_item.get("speaker") or raw_item.get("character") or ""
                    ).strip()
                    or None,
                    emotion=str(raw_item.get("emotion") or "").strip() or None,
                )
            )
        return entries

    @staticmethod
    def _normalize_output_format(value: str) -> str:
        normalized = str(value or "mp3").strip().lower().lstrip(".")
        if normalized == "m4a":
            return "m4b"
        return normalized if normalized in {"mp3", "wav", "m4b"} else "mp3"

    def _export_atomic(
        self,
        audio: AudioSegment,
        target: Path,
        output_format: str,
    ) -> dict[str, Any]:
        source_path: Path | None = None
        output_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".source.wav",
                dir=target.parent,
                delete=False,
            ) as source_file:
                source_path = Path(source_file.name)
            with tempfile.NamedTemporaryFile(
                suffix=f".{output_format}",
                dir=target.parent,
                delete=False,
            ) as output_file:
                output_path = Path(output_file.name)
            audio.export(str(source_path), format="wav", codec="pcm_s16le")
            try:
                report = self.loudness_normalizer.normalize(
                    source_path,
                    output_path,
                    output_format=output_format,
                )
            except LoudnessNormalizationError as exc:
                raise SceneAssemblyError(str(exc)) from exc
            if not output_path.exists() or output_path.stat().st_size <= 0:
                raise SceneAssemblyError("loudnorm_output_missing")
            os.replace(output_path, target)
            output_path = None
            return dict(report or {})
        finally:
            for temp_path in (source_path, output_path):
                if temp_path is None:
                    continue
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


__all__ = [
    "SceneAssemblyError",
    "SceneAssemblyResult",
    "SceneAssemblySubtitleEntry",
    "SceneAssemblyTiming",
    "SceneAudioAssembler",
]
