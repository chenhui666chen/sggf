"""Transcript fidelity gate for generated Seed Audio scenes."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence, Tuple

from .quality_policy import (
    DEFAULT_SCENE_AUDIO_QUALITY_POLICY,
    SceneAudioQualityPolicy,
)


@dataclass(frozen=True)
class SceneAudioQualityReport:
    passed: bool
    status: str
    transcript_source: str
    transcript: str
    transcript_coverage: float
    missing_lines: Tuple[str, ...]
    extra_lines: Tuple[str, ...]
    order_valid: bool
    audio_decodable: bool | None = None
    clipping: bool | None = None
    silence: bool | None = None
    duration_s: float | None = None
    fallback_reason: str | None = None


class SceneAudioQualityGate:
    """Reject scene audio that changes the reviewed spoken-text contract."""

    def __init__(
        self,
        *,
        policy: SceneAudioQualityPolicy | None = None,
        min_transcript_coverage: float | None = None,
    ) -> None:
        resolved_policy = policy or DEFAULT_SCENE_AUDIO_QUALITY_POLICY
        if min_transcript_coverage is not None:
            resolved_policy = replace(
                resolved_policy,
                min_transcript_coverage=min_transcript_coverage,
            )
        self.policy = resolved_policy
        self.min_transcript_coverage = resolved_policy.min_transcript_coverage

    def evaluate(
        self,
        *,
        expected_texts: Sequence[str],
        subtitle_payload: Any = None,
        asr_transcript: str | None = None,
        expected_vocalizations: Sequence[str] = (),
        audio_metadata: Mapping[str, Any] | None = None,
    ) -> SceneAudioQualityReport:
        expected_lines = tuple(str(text or "") for text in expected_texts if str(text or "").strip())
        subtitle_lines = self._extract_subtitle_lines(subtitle_payload)
        if subtitle_lines:
            transcript_source = "provider_subtitle"
            transcript_lines = subtitle_lines
        elif str(asr_transcript or "").strip():
            transcript_source = "asr"
            transcript_lines = (str(asr_transcript).strip(),)
        else:
            return SceneAudioQualityReport(
                passed=False,
                status="needs_asr",
                transcript_source="none",
                transcript="",
                transcript_coverage=0.0,
                missing_lines=expected_lines,
                extra_lines=(),
                order_valid=False,
                fallback_reason="transcript_unavailable",
            )

        transcript = "\n".join(transcript_lines)
        normalized_expected_lines = tuple(self._normalize_text(line) for line in expected_lines)
        normalized_expected_lines = tuple(line for line in normalized_expected_lines if line)
        normalized_expected = "".join(normalized_expected_lines)
        normalized_transcript = self._normalize_text(transcript)

        coverage, extra_lines = self._coverage_and_extra_text(
            normalized_expected,
            normalized_transcript,
            expected_vocalizations,
        )
        missing_lines, order_valid = self._missing_lines_and_order(
            expected_lines,
            normalized_expected_lines,
            normalized_transcript,
        )
        technical = self._technical_status(audio_metadata)
        transcript_passed = (
            coverage >= self.min_transcript_coverage
            and not missing_lines
            and not extra_lines
            and order_valid
        )
        passed = transcript_passed and not technical["failed"]
        fallback_reason = None
        if technical["failed"]:
            fallback_reason = str(technical["reason"])
        elif not transcript_passed:
            fallback_reason = "transcript_fidelity_failed"

        return SceneAudioQualityReport(
            passed=passed,
            status="passed" if passed else "failed",
            transcript_source=transcript_source,
            transcript=transcript,
            transcript_coverage=round(coverage, 6),
            missing_lines=missing_lines,
            extra_lines=extra_lines,
            order_valid=order_valid,
            audio_decodable=technical["audio_decodable"],
            clipping=technical["clipping"],
            silence=technical["silence"],
            duration_s=technical["duration_s"],
            fallback_reason=fallback_reason,
        )

    @staticmethod
    def next_action(
        report: SceneAudioQualityReport,
        *,
        render_attempt_count: int,
        split_attempted: bool,
    ) -> str:
        if report.passed:
            return "assemble"
        if report.status == "needs_asr":
            return "run_asr"
        if render_attempt_count < 1:
            return "retry_scene"
        if not split_attempted:
            return "split_scene"
        return "legacy_stems"

    @classmethod
    def _extract_subtitle_lines(cls, payload: Any) -> Tuple[str, ...]:
        lines = []

        def collect(value: Any) -> None:
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    lines.append(cleaned)
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    collect(item)
                return
            if not isinstance(value, Mapping):
                return

            for key in ("text", "content", "transcript", "utterance"):
                direct = value.get(key)
                if isinstance(direct, str) and direct.strip():
                    lines.append(direct.strip())
                    return
            for key in ("subtitles", "subtitle", "utterances", "sentences", "segments", "data", "result"):
                nested = value.get(key)
                if nested is not None:
                    collect(nested)

        collect(payload)
        return tuple(lines)

    @classmethod
    def _normalize_text(cls, value: str) -> str:
        text = str(value or "").casefold()
        punctuation = (
            string.punctuation
            + "。！？；：，、（）【】《》「」『』"
            + "\u2014\u2013…“”‘’"
        )
        text = re.sub(f"[{re.escape(punctuation)}]", "", text)
        text = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff]", "", text)
        return text.replace("_", "")

    @classmethod
    def _coverage_and_extra_text(
        cls,
        expected: str,
        transcript: str,
        expected_vocalizations: Sequence[str],
    ) -> Tuple[float, Tuple[str, ...]]:
        if not expected:
            return (1.0 if not transcript else 0.0), (() if not transcript else (transcript,))
        if not transcript:
            return 0.0, ()

        matcher = SequenceMatcher(None, expected, transcript, autojunk=False)
        matched_chars = sum(block.size for block in matcher.get_matching_blocks())
        coverage = min(1.0, matched_chars / len(expected))
        vocalizations = sorted(
            {cls._normalize_text(value) for value in expected_vocalizations if cls._normalize_text(value)},
            key=len,
            reverse=True,
        )
        extras = []
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag not in {"insert", "replace"}:
                continue
            extra = transcript[j1:j2]
            for vocalization in vocalizations:
                extra = extra.replace(vocalization, "")
            if extra:
                extras.append(extra)
        return coverage, tuple(extras)

    @staticmethod
    def _missing_lines_and_order(
        expected_lines: Sequence[str],
        normalized_expected_lines: Sequence[str],
        transcript: str,
    ) -> Tuple[Tuple[str, ...], bool]:
        missing = []
        cursor = 0
        order_valid = True
        for original, normalized in zip(expected_lines, normalized_expected_lines):
            position = transcript.find(normalized, cursor)
            if position >= 0:
                cursor = position + len(normalized)
                continue
            if transcript.find(normalized) < 0:
                missing.append(original)
            order_valid = False
        return tuple(missing), order_valid

    def _technical_status(self, metadata: Mapping[str, Any] | None) -> dict[str, Any]:
        values = metadata or {}
        audio_decodable = values.get("audio_decodable")
        clipping_value = values.get("clipping")
        if clipping_value is None and values.get("clipping_ratio") is not None:
            clipping_value = (
                float(values["clipping_ratio"])
                > self.policy.clipping_ratio_threshold
            )
        silence_value = values.get("silence")
        if silence_value is None and values.get("silence_ratio") is not None:
            silence_value = (
                float(values["silence_ratio"])
                > self.policy.silence_ratio_threshold
            )
        duration_value = values.get("duration_s", values.get("duration"))
        duration_s = float(duration_value) if duration_value is not None else None

        reason = None
        if audio_decodable is False:
            reason = "audio_not_decodable"
        elif clipping_value is True:
            reason = "audio_clipping_detected"
        elif silence_value is True:
            reason = "abnormal_silence_detected"
        elif duration_s is not None and duration_s <= 0:
            reason = "invalid_audio_duration"
        return {
            "failed": reason is not None,
            "reason": reason,
            "audio_decodable": audio_decodable if isinstance(audio_decodable, bool) else None,
            "clipping": clipping_value if isinstance(clipping_value, bool) else None,
            "silence": silence_value if isinstance(silence_value, bool) else None,
            "duration_s": duration_s,
        }
