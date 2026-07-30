"""Two-pass EBU R128 loudness normalization for finalized scene chapters."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


class LoudnessNormalizationError(RuntimeError):
    """Raised when FFmpeg cannot produce a verified normalized artifact."""


class FFmpegLoudnessNormalizer:
    """Measure with loudnorm, then render once with the measured values."""

    REQUIRED_MEASUREMENT_KEYS = (
        "input_i",
        "input_tp",
        "input_lra",
        "input_thresh",
        "target_offset",
    )

    def __init__(
        self,
        *,
        target_i: float = -16.0,
        target_tp: float = -1.5,
        target_lra: float = 11.0,
        ffmpeg_path: str | None = None,
        command_runner: Callable[..., Any] = subprocess.run,
        timeout_seconds: int = 600,
    ) -> None:
        self.target_i = float(target_i)
        self.target_tp = float(target_tp)
        self.target_lra = float(target_lra)
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        self.command_runner = command_runner
        self.timeout_seconds = max(1, int(timeout_seconds))

    def normalize(
        self,
        input_path: str | Path,
        output_path: str | Path,
        *,
        output_format: str,
    ) -> dict[str, Any]:
        if not self.ffmpeg_path:
            raise LoudnessNormalizationError("ffmpeg_unavailable_for_loudnorm")

        source = Path(input_path)
        target = Path(output_path)
        measurement = self._measure(source)

        render_result = self._run(
            [
                self.ffmpeg_path,
                "-y",
                "-hide_banner",
                "-nostats",
                "-i",
                str(source),
                "-af",
                self._render_filter(measurement),
                *self._output_arguments(output_format),
                str(target),
            ],
            error_code="loudnorm_render_failed",
        )
        if not target.exists() or not target.is_file() or target.stat().st_size <= 0:
            raise LoudnessNormalizationError("loudnorm_output_missing")

        output_measurement = self._parse_json_object(render_result.stderr) or {}
        return {
            "normalized": True,
            "target_i": self.target_i,
            "target_tp": self.target_tp,
            "target_lra": self.target_lra,
            **self._numeric_values(measurement),
            **self._numeric_values(
                output_measurement,
                keys=("output_i", "output_tp", "output_lra", "output_thresh"),
            ),
        }

    def measure(self, input_path: str | Path) -> dict[str, float]:
        """Measure integrated loudness without rendering a new audio file."""
        if not self.ffmpeg_path:
            raise LoudnessNormalizationError("ffmpeg_unavailable_for_loudnorm")
        return self._numeric_values(self._measure(Path(input_path)))

    def _measure(self, source: Path) -> dict[str, Any]:
        measurement_result = self._run(
            [
                self.ffmpeg_path,
                "-hide_banner",
                "-nostats",
                "-i",
                str(source),
                "-af",
                self._measurement_filter(),
                "-f",
                "null",
                "-",
            ],
            error_code="loudnorm_measurement_failed",
        )
        return self._parse_measurement(measurement_result.stderr)

    def _run(
        self,
        command: Sequence[str],
        *,
        error_code: str,
    ) -> Any:
        try:
            result = self.command_runner(
                list(command),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LoudnessNormalizationError(f"{error_code}:{exc}") from exc
        if int(getattr(result, "returncode", 1)) != 0:
            stderr_tail = str(getattr(result, "stderr", "") or "")[-500:].strip()
            raise LoudnessNormalizationError(
                f"{error_code}:{stderr_tail or result.returncode}"
            )
        return result

    def _measurement_filter(self) -> str:
        return (
            f"loudnorm=I={self.target_i}:LRA={self.target_lra}:"
            f"TP={self.target_tp}:print_format=json"
        )

    def _render_filter(self, measurement: Mapping[str, Any]) -> str:
        return (
            f"loudnorm=I={self.target_i}:LRA={self.target_lra}:TP={self.target_tp}:"
            f"measured_I={measurement['input_i']}:"
            f"measured_LRA={measurement['input_lra']}:"
            f"measured_TP={measurement['input_tp']}:"
            f"measured_thresh={measurement['input_thresh']}:"
            f"offset={measurement['target_offset']}:"
            "linear=true:print_format=json"
        )

    @staticmethod
    def _output_arguments(output_format: str) -> list[str]:
        normalized = str(output_format or "mp3").strip().lower().lstrip(".")
        if normalized == "wav":
            return ["-codec:a", "pcm_s16le", "-f", "wav"]
        if normalized == "m4b":
            return [
                "-codec:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
            ]
        return ["-codec:a", "libmp3lame", "-b:a", "128k", "-f", "mp3"]

    def _parse_measurement(self, stderr: Any) -> dict[str, Any]:
        payload = self._parse_json_object(stderr)
        if not payload or any(
            key not in payload for key in self.REQUIRED_MEASUREMENT_KEYS
        ):
            raise LoudnessNormalizationError("loudnorm_measurement_missing")
        for key in self.REQUIRED_MEASUREMENT_KEYS:
            try:
                value = float(payload[key])
            except (TypeError, ValueError) as exc:
                raise LoudnessNormalizationError(
                    "loudnorm_measurement_invalid"
                ) from exc
            if not math.isfinite(value):
                raise LoudnessNormalizationError("loudnorm_measurement_invalid")
        return payload

    @staticmethod
    def _parse_json_object(value: Any) -> dict[str, Any] | None:
        text = str(value or "")
        decoder = json.JSONDecoder()
        candidate = None
        for index, character in enumerate(text):
            if character != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                candidate = payload
        return candidate

    @staticmethod
    def _numeric_values(
        payload: Mapping[str, Any],
        *,
        keys: Sequence[str] = REQUIRED_MEASUREMENT_KEYS,
    ) -> dict[str, float]:
        result = {}
        for key in keys:
            if key not in payload:
                continue
            try:
                value = float(payload[key])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                result[key] = value
        return result


__all__ = ["FFmpegLoudnessNormalizer", "LoudnessNormalizationError"]
