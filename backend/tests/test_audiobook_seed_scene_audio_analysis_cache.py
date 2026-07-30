from __future__ import annotations

import math
import struct
import sys
import wave
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.audio_analysis import (
    SceneAudioAnalysisCache,
    SceneAudioTechnicalAnalyzer,
    SceneAudioTechnicalReport,
)


def _write_wav(path: Path, *, mode: str = "tone", duration_s: float = 1.0, sample_rate: int = 16000) -> None:
    frame_count = int(duration_s * sample_rate)
    frames = bytearray()
    for index in range(frame_count):
        if mode == "silence":
            sample = 0
        else:
            sample = int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def test_cache_round_trip_preserves_report(tmp_path: Path) -> None:
    cache = SceneAudioAnalysisCache(tmp_path / "cache")
    report = SceneAudioTechnicalReport(
        audio_decodable=True,
        duration_s=1.0,
        sample_rate=16000,
        channels=1,
        clipping=False,
        clipping_ratio=0.0,
        silence=False,
        silence_ratio=0.12,
    )
    assert cache.get("sha-a") is None
    cache.put("sha-a", report)
    assert cache.get("sha-a") == report


def test_analyzer_reuses_cache_without_redecoding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio_path = tmp_path / "valid.wav"
    _write_wav(audio_path)
    cache = SceneAudioAnalysisCache(tmp_path / "cache")
    analyzer = SceneAudioTechnicalAnalyzer(cache=cache)

    first = analyzer.analyze(audio_path)
    assert first.audio_decodable is True

    def _boom(_path):
        raise AssertionError("cached analysis must not re-decode audio")

    monkeypatch.setattr(analyzer, "_analyze_uncached", _boom)
    second = analyzer.analyze(audio_path)
    assert second == first


def test_analyzer_without_cache_is_unchanged(tmp_path: Path) -> None:
    audio_path = tmp_path / "valid.wav"
    _write_wav(audio_path)

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.audio_decodable is True
    assert report.duration_s == 1.0


def test_decode_failure_is_not_cached(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"not-an-audio-file")
    cache = SceneAudioAnalysisCache(tmp_path / "cache")
    analyzer = SceneAudioTechnicalAnalyzer(cache=cache)

    report = analyzer.analyze(broken)

    assert report.audio_decodable is False
    key = analyzer._file_sha256(broken)
    assert key is not None
    assert cache.get(key) is None


def test_distinct_audio_have_separate_cache_entries(tmp_path: Path) -> None:
    tone = tmp_path / "tone.wav"
    silent = tmp_path / "silent.wav"
    _write_wav(tone, mode="tone")
    _write_wav(silent, mode="silence")
    cache = SceneAudioAnalysisCache(tmp_path / "cache")
    analyzer = SceneAudioTechnicalAnalyzer(cache=cache)

    tone_report = analyzer.analyze(tone)
    silent_report = analyzer.analyze(silent)

    assert tone_report.silence is False
    assert silent_report.silence is True
    assert cache.get(analyzer._file_sha256(tone)) == tone_report
    assert cache.get(analyzer._file_sha256(silent)) == silent_report
