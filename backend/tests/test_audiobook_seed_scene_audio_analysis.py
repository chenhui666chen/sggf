from __future__ import annotations

import math
import struct
import sys
import wave
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.audio_analysis import SceneAudioTechnicalAnalyzer


def _write_wav(path: Path, *, mode: str, duration_s: float = 1.0, sample_rate: int = 16000) -> None:
    frame_count = int(duration_s * sample_rate)
    frames = bytearray()
    for index in range(frame_count):
        if mode == "silence":
            sample = 0
        elif mode == "clipped":
            sample = 32767
        else:
            sample = int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _write_tone_then_silence_wav(
    path: Path,
    *,
    tone_duration_s: float,
    silence_duration_s: float,
    sample_rate: int = 16000,
) -> None:
    tone_frames = int(tone_duration_s * sample_rate)
    silence_frames = int(silence_duration_s * sample_rate)
    frames = bytearray()
    for index in range(tone_frames):
        sample = int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    frames.extend(struct.pack("<h", 0) * silence_frames)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _write_stereo_wav(
    path: Path,
    *,
    left_mode: str,
    right_mode: str,
    duration_s: float = 1.0,
    sample_rate: int = 16000,
) -> None:
    import random

    rng = random.Random(20260722)
    frame_count = int(duration_s * sample_rate)
    frames = bytearray()

    def _sample(mode: str, index: int) -> int:
        if mode == "tone":
            return int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        if mode == "tone2":
            return int(10000 * math.sin(2 * math.pi * 523 * index / sample_rate))
        if mode == "noise":
            return rng.randint(-9000, 9000)
        return 0

    for index in range(frame_count):
        frames.extend(struct.pack("<h", _sample(left_mode, index)))
        frames.extend(struct.pack("<h", _sample(right_mode, index)))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _write_speech_with_pauses_wav(
    path: Path,
    *,
    sample_rate: int = 16000,
    burst_s: float = 0.25,
    gap_s: float = 0.25,
    bursts: int = 4,
) -> None:
    frames = bytearray()
    burst_frames = int(burst_s * sample_rate)
    gap_frames = int(gap_s * sample_rate)
    for _ in range(bursts):
        for index in range(burst_frames):
            sample = int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        frames.extend(struct.pack("<h", 0) * gap_frames)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def _write_tone_with_reverb_tail_wav(
    path: Path,
    *,
    sample_rate: int = 16000,
    tone_s: float = 0.3,
    tail_s: float = 0.6,
    tau_s: float = 0.18,
    trailing_silence_s: float = 0.2,
) -> None:
    frames = bytearray()
    tone_frames = int(tone_s * sample_rate)
    tail_frames = int(tail_s * sample_rate)
    silence_frames = int(trailing_silence_s * sample_rate)
    for index in range(tone_frames):
        sample = int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate))
        frames.extend(struct.pack("<h", sample))
    for index in range(tail_frames):
        decay = math.exp(-index / (tau_s * sample_rate))
        sample = int(
            10000 * decay * math.sin(2 * math.pi * 440 * (tone_frames + index) / sample_rate)
        )
        frames.extend(struct.pack("<h", sample))
    frames.extend(struct.pack("<h", 0) * silence_frames)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def test_audio_analyzer_reports_decodable_scene_metadata(tmp_path: Path) -> None:
    audio_path = tmp_path / "valid.wav"
    _write_wav(audio_path, mode="tone")

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.audio_decodable is True
    assert report.duration_s == 1.0
    assert report.sample_rate == 16000
    assert report.channels == 1
    assert report.clipping is False
    assert report.silence is False
    assert report.to_quality_metadata()["audio_decodable"] is True


def test_audio_analyzer_detects_clipping(tmp_path: Path) -> None:
    audio_path = tmp_path / "clipped.wav"
    _write_wav(audio_path, mode="clipped")

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.audio_decodable is True
    assert report.clipping is True
    assert report.clipping_ratio > 0.99


def test_audio_analyzer_detects_abnormal_silence(tmp_path: Path) -> None:
    audio_path = tmp_path / "silent.wav"
    _write_wav(audio_path, mode="silence")

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.audio_decodable is True
    assert report.silence is True
    assert report.silence_ratio == 1.0


def test_audio_analyzer_allows_deliberate_scene_silence(tmp_path: Path) -> None:
    audio_path = tmp_path / "dramatic-pause.wav"
    _write_tone_then_silence_wav(
        audio_path,
        tone_duration_s=1.0,
        silence_duration_s=3.0,
    )

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.silence_ratio is not None and 0.7 < report.silence_ratio < 0.8
    assert report.silence is False


def test_audio_analyzer_returns_structured_decode_failure(tmp_path: Path) -> None:
    audio_path = tmp_path / "broken.mp3"
    audio_path.write_bytes(b"not-an-audio-file")

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.audio_decodable is False
    assert report.error
    assert report.to_quality_metadata() == {"audio_decodable": False}


def test_audio_analyzer_treats_mono_as_single_voice(tmp_path: Path) -> None:
    audio_path = tmp_path / "mono.wav"
    _write_wav(audio_path, mode="tone")

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.channels == 1
    assert report.channel_correlation is None
    assert report.single_voice is True


def test_audio_analyzer_flags_decorrelated_stereo_as_multi_source(tmp_path: Path) -> None:
    audio_path = tmp_path / "stereo-decorrelated.wav"
    _write_stereo_wav(audio_path, left_mode="tone", right_mode="noise")

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.channels == 2
    assert report.channel_correlation is not None
    assert report.channel_correlation < 0.2
    assert report.single_voice is False


def test_audio_analyzer_keeps_correlated_stereo_as_single_voice(tmp_path: Path) -> None:
    audio_path = tmp_path / "stereo-correlated.wav"
    _write_stereo_wav(audio_path, left_mode="tone", right_mode="tone")

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.channel_correlation is not None
    assert report.channel_correlation > 0.99
    assert report.single_voice is True


def test_audio_analyzer_flags_continuous_energy_bed_as_background(tmp_path: Path) -> None:
    audio_path = tmp_path / "continuous.wav"
    _write_wav(audio_path, mode="tone")

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.background_energy_ratio is not None
    assert report.background_energy_ratio > 0.9
    assert report.background_music is True


def test_audio_analyzer_keeps_speech_with_pauses_free_of_background(tmp_path: Path) -> None:
    audio_path = tmp_path / "speech-pauses.wav"
    _write_speech_with_pauses_wav(audio_path)

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.background_energy_ratio is not None
    assert report.background_energy_ratio < 0.35
    assert report.background_music is False


def test_audio_analyzer_detects_reverb_tail(tmp_path: Path) -> None:
    audio_path = tmp_path / "reverb.wav"
    _write_tone_with_reverb_tail_wav(audio_path)

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.reverb_tail_s is not None
    assert report.reverb_tail_s > 0.12
    assert report.reverb is True


def test_audio_analyzer_keeps_dry_offset_free_of_reverb(tmp_path: Path) -> None:
    audio_path = tmp_path / "dry.wav"
    _write_tone_then_silence_wav(
        audio_path,
        tone_duration_s=0.4,
        silence_duration_s=0.6,
    )

    report = SceneAudioTechnicalAnalyzer().analyze(audio_path)

    assert report.reverb_tail_s is not None
    assert report.reverb_tail_s < 0.12
    assert report.reverb is False


def test_audio_analyzer_exposes_acoustic_signals_in_quality_metadata(tmp_path: Path) -> None:
    audio_path = tmp_path / "signals.wav"
    _write_speech_with_pauses_wav(audio_path)

    metadata = SceneAudioTechnicalAnalyzer().analyze(audio_path).to_quality_metadata()

    assert metadata["single_voice"] is True
    assert "background_energy_ratio" in metadata
    assert "background_music" in metadata
    assert "reverb_tail_s" in metadata
    assert "reverb" in metadata
