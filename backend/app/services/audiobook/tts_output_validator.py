"""Lightweight validation for one TTS segment output."""

from __future__ import annotations

import html
import io
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

try:
    from pydub import AudioSegment
    from pydub.silence import detect_silence

    PYDUB_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional runtime package
    AudioSegment = None
    detect_silence = None
    PYDUB_AVAILABLE = False


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)?|\d+(?:[.,]\d+)*")
_BREAK_TAG_RE = re.compile(r"<break\b[^>]*/?>", re.IGNORECASE)
_PAUSE_TAG_RE = re.compile(r"\[(?:pause|break)(?::[^\]]+)?\]", re.IGNORECASE)
_SSML_CONTAINER_RE = re.compile(r"</?speak\b[^>]*>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class TTSValidationResult:
    passed: bool
    reason: str
    duration_ms: int = 0
    expected_duration_ms: int = 0
    min_duration_ms: int = 0
    max_duration_ms: int = 0
    silence_ratio: float = 0.0
    rms_dbfs: float = 0.0
    max_dbfs: float = 0.0
    decodable: bool = True
    skipped: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
            "expected_duration_ms": self.expected_duration_ms,
            "min_duration_ms": self.min_duration_ms,
            "max_duration_ms": self.max_duration_ms,
            "silence_ratio": self.silence_ratio,
            "rms_dbfs": self.rms_dbfs,
            "max_dbfs": self.max_dbfs,
            "decodable": self.decodable,
            "skipped": self.skipped,
            "warnings": list(self.warnings),
        }


def estimate_tts_duration_ms(text: str) -> int:
    cleaned = _clean_text_for_duration(text)
    if not cleaned:
        return 0

    cjk_chars = len(_CJK_RE.findall(cleaned))
    without_cjk = _CJK_RE.sub(" ", cleaned)
    words = _WORD_RE.findall(without_cjk)
    without_words = _WORD_RE.sub(" ", without_cjk)
    other_chars = sum(
        1
        for char in without_words
        if not char.isspace() and unicodedata.category(char)[0] not in {"P", "S"}
    )

    if cjk_chars + len(words) + other_chars == 0:
        return 0

    seconds = cjk_chars / 4.4 + len(words) / 2.7 + other_chars / 5.5
    sentence_pauses = min(6, len(re.findall(r"[。！？!?；;：:]", cleaned))) * 0.18
    comma_pauses = min(8, len(re.findall(r"[，,、]", cleaned))) * 0.08
    return int(max(350, (seconds + sentence_pauses + comma_pauses) * 1000))


def validate_tts_audio(
    audio_bytes: bytes,
    text: str,
    *,
    min_duration_ms: int = 250,
    min_duration_ratio: float = 0.12,
    max_min_duration_ms: int = 3500,
    max_duration_multiplier: float = 3.0,
    max_duration_grace_ms: int = 2500,
    max_duration_floor_ms: int = 4000,
    silence_threshold_dbfs: float = -45.0,
    max_silence_ratio: float = 0.90,
    min_rms_dbfs: float = -55.0,
    clipping_warning_dbfs: float = -0.1,
) -> TTSValidationResult:
    if not audio_bytes:
        return TTSValidationResult(passed=False, reason="empty_audio", decodable=False)

    expected_ms = estimate_tts_duration_ms(text)
    if not PYDUB_AVAILABLE or AudioSegment is None:
        return TTSValidationResult(
            passed=True,
            reason="pydub_unavailable",
            expected_duration_ms=expected_ms,
            skipped=True,
        )

    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
    except Exception as exc:
        logger.warning("TTS output decode failed: %s", exc)
        return TTSValidationResult(
            passed=False,
            reason="undecodable_audio",
            expected_duration_ms=expected_ms,
            decodable=False,
        )

    duration_ms = int(len(audio))
    min_allowed_ms = _min_allowed_duration_ms(
        expected_ms=expected_ms,
        min_duration_ms=min_duration_ms,
        min_duration_ratio=min_duration_ratio,
        max_min_duration_ms=max_min_duration_ms,
    )
    max_allowed_ms = _max_allowed_duration_ms(
        expected_ms=expected_ms,
        max_duration_multiplier=max_duration_multiplier,
        max_duration_grace_ms=max_duration_grace_ms,
        max_duration_floor_ms=max_duration_floor_ms,
    )

    rms_dbfs = _finite_dbfs(audio.dBFS, fallback=-120.0)
    max_dbfs = _finite_dbfs(audio.max_dBFS, fallback=-120.0)
    silence_ratio = _silence_ratio(audio, silence_threshold_dbfs)
    warnings: List[str] = []

    if max_dbfs >= clipping_warning_dbfs:
        warnings.append("possible_clipping")

    if duration_ms <= 0:
        return TTSValidationResult(
            passed=False,
            reason="zero_duration",
            duration_ms=duration_ms,
            expected_duration_ms=expected_ms,
            min_duration_ms=min_allowed_ms,
            max_duration_ms=max_allowed_ms,
            silence_ratio=silence_ratio,
            rms_dbfs=rms_dbfs,
            max_dbfs=max_dbfs,
            warnings=warnings,
        )

    if duration_ms < min_allowed_ms:
        return TTSValidationResult(
            passed=False,
            reason="too_short_for_text",
            duration_ms=duration_ms,
            expected_duration_ms=expected_ms,
            min_duration_ms=min_allowed_ms,
            max_duration_ms=max_allowed_ms,
            silence_ratio=silence_ratio,
            rms_dbfs=rms_dbfs,
            max_dbfs=max_dbfs,
            warnings=warnings,
        )

    if expected_ms > 0 and duration_ms > max_allowed_ms:
        return TTSValidationResult(
            passed=False,
            reason="duration_outlier",
            duration_ms=duration_ms,
            expected_duration_ms=expected_ms,
            min_duration_ms=min_allowed_ms,
            max_duration_ms=max_allowed_ms,
            silence_ratio=silence_ratio,
            rms_dbfs=rms_dbfs,
            max_dbfs=max_dbfs,
            warnings=warnings,
        )

    if rms_dbfs <= min_rms_dbfs:
        return TTSValidationResult(
            passed=False,
            reason="low_energy_audio",
            duration_ms=duration_ms,
            expected_duration_ms=expected_ms,
            min_duration_ms=min_allowed_ms,
            max_duration_ms=max_allowed_ms,
            silence_ratio=silence_ratio,
            rms_dbfs=rms_dbfs,
            max_dbfs=max_dbfs,
            warnings=warnings,
        )

    if silence_ratio >= max_silence_ratio:
        return TTSValidationResult(
            passed=False,
            reason="excessive_silence",
            duration_ms=duration_ms,
            expected_duration_ms=expected_ms,
            min_duration_ms=min_allowed_ms,
            max_duration_ms=max_allowed_ms,
            silence_ratio=silence_ratio,
            rms_dbfs=rms_dbfs,
            max_dbfs=max_dbfs,
            warnings=warnings,
        )

    return TTSValidationResult(
        passed=True,
        reason="ok",
        duration_ms=duration_ms,
        expected_duration_ms=expected_ms,
        min_duration_ms=min_allowed_ms,
        max_duration_ms=max_allowed_ms,
        silence_ratio=silence_ratio,
        rms_dbfs=rms_dbfs,
        max_dbfs=max_dbfs,
        warnings=warnings,
    )


def _clean_text_for_duration(text: str) -> str:
    value = html.unescape(str(text or ""))
    value = _PAUSE_TAG_RE.sub(" ", value)
    value = _BREAK_TAG_RE.sub(" ", value)
    value = _SSML_CONTAINER_RE.sub(" ", value)
    value = _HTML_TAG_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _min_allowed_duration_ms(
    *,
    expected_ms: int,
    min_duration_ms: int,
    min_duration_ratio: float,
    max_min_duration_ms: int,
) -> int:
    if expected_ms <= 0:
        return int(min_duration_ms)
    by_text = int(expected_ms * min_duration_ratio)
    return int(min(max(min_duration_ms, by_text), max_min_duration_ms))


def _max_allowed_duration_ms(
    *,
    expected_ms: int,
    max_duration_multiplier: float,
    max_duration_grace_ms: int,
    max_duration_floor_ms: int,
) -> int:
    if expected_ms <= 0:
        return int(max_duration_floor_ms)
    return int(max(max_duration_floor_ms, expected_ms * max_duration_multiplier + max_duration_grace_ms))


def _silence_ratio(audio: AudioSegment, silence_threshold_dbfs: float) -> float:
    if detect_silence is None or len(audio) <= 0:
        return 0.0

    min_silence_len = max(100, min(500, len(audio) // 5 or 100))
    try:
        ranges = detect_silence(
            audio,
            min_silence_len=min_silence_len,
            silence_thresh=silence_threshold_dbfs,
        )
    except Exception as exc:
        logger.debug("Silence detection skipped: %s", exc)
        return 0.0

    silent_ms = sum(max(0, end - start) for start, end in ranges)
    return max(0.0, min(1.0, silent_ms / max(1, len(audio))))


def _finite_dbfs(value: float, *, fallback: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isfinite(numeric):
        return numeric
    return fallback
