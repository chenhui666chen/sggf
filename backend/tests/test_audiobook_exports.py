from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.services.audiobook.audio_mixer import AudioMixer, FFMPEG_AVAILABLE
from app.services.audiobook.background_jobs_shared import (
    build_chapter_audio_output_path,
    generate_subtitle_artifacts,
    normalize_audiobook_output_format,
)
from app.services.audiobook.subtitle_generator import SubtitleGenerator


try:
    from pydub import AudioSegment
    from pydub.generators import Sine
except ImportError:  # pragma: no cover
    AudioSegment = None
    Sine = None


pytestmark = pytest.mark.skipif(AudioSegment is None, reason="pydub unavailable")


def _silent_audio_bytes(duration_ms: int = 1000, fmt: str = "wav") -> bytes:
    buffer = io.BytesIO()
    AudioSegment.silent(duration=duration_ms).export(buffer, format=fmt)
    return buffer.getvalue()


def _tone_with_gap_bytes(gap_ms: int, fmt: str = "wav") -> bytes:
    tone = Sine(440).to_audio_segment(duration=300).apply_gain(-6)
    audio = tone + AudioSegment.silent(duration=gap_ms) + tone
    buffer = io.BytesIO()
    audio.export(buffer, format=fmt)
    return buffer.getvalue()


def test_segment_timeline_matches_mixer_semantic_pause_rules():
    mixer = AudioMixer(
        enable_silence_trim=False,
        enable_loudness_norm=False,
        enable_semantic_pause=True,
        paragraph_pause_ms=1500,
        sentence_pause_ms=500,
        phrase_pause_ms=250,
    )

    timeline = mixer.build_segment_timeline(
        [_silent_audio_bytes(1000), _silent_audio_bytes(700)],
        segment_types=["paragraph", "sentence"],
    )

    assert len(timeline) == 2
    assert timeline[0]["index"] == 0
    assert timeline[0]["start"] == pytest.approx(0.0, abs=0.001)
    assert timeline[0]["end"] == pytest.approx(1.0, abs=0.001)
    assert timeline[1]["index"] == 1
    assert timeline[1]["start"] == pytest.approx(2.5, abs=0.001)
    assert timeline[1]["end"] == pytest.approx(3.2, abs=0.001)


def test_segment_timeline_and_mix_use_explicit_pause_override():
    mixer = AudioMixer(
        enable_silence_trim=False,
        enable_loudness_norm=False,
        enable_semantic_pause=True,
        paragraph_pause_ms=1500,
        sentence_pause_ms=500,
        phrase_pause_ms=250,
    )
    segments = [_silent_audio_bytes(100), _silent_audio_bytes(100)]

    timeline = mixer.build_segment_timeline(
        segments,
        segment_types=["sentence", "sentence"],
        pause_after_ms=[2000, None],
    )
    audio_bytes = mixer.mix_chapter(
        segments,
        output_format="wav",
        segment_types=["sentence", "sentence"],
        pause_after_ms=[2000, None],
    )

    mixed = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
    assert timeline[1]["start"] == pytest.approx(2.1, abs=0.001)
    assert len(mixed) == pytest.approx(2200, abs=5)


def test_audio_mixer_limits_internal_tts_silence_without_touching_segment_pause():
    mixer = AudioMixer(
        enable_silence_trim=False,
        enable_loudness_norm=False,
        enable_semantic_pause=True,
        enable_internal_silence_limit=True,
        max_internal_silence_ms=500,
        sentence_pause_ms=700,
    )
    segments = [_tone_with_gap_bytes(2200), _tone_with_gap_bytes(100)]

    timeline = mixer.build_segment_timeline(
        segments,
        segment_types=["sentence", "sentence"],
    )
    audio_bytes = mixer.mix_chapter(
        segments,
        output_format="wav",
        segment_types=["sentence", "sentence"],
    )

    mixed = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
    assert timeline[0]["duration"] == pytest.approx(1.1, abs=0.03)
    assert timeline[1]["start"] == pytest.approx(1.8, abs=0.03)
    assert len(mixed) == pytest.approx(2500, abs=30)


def test_audacity_label_export_uses_indexed_segment_timeline(tmp_path: Path):
    segments = [
        {"text": "第一句旁白。", "speaker": "旁白", "emotion": "neutral"},
        {"text": "这句没有成功合成，不应出现在标签里。", "speaker": "甲"},
        {"text": "你好。", "speaker": "乙", "emotion": "calm"},
    ]
    timings = [
        {"index": 0, "start": 0.0, "end": 1.2, "duration": 1.2},
        {"index": 2, "start": 1.7, "end": 2.1, "duration": 0.4},
    ]

    entries = SubtitleGenerator.from_segment_timings(segments, timings)
    output_path = tmp_path / "chapter_001.labels.txt"
    SubtitleGenerator.generate_audacity_labels(entries, str(output_path))

    content = output_path.read_text(encoding="utf-8")
    assert "0.000000\t1.200000\t[旁白] 第一句旁白。" in content
    assert "1.700000\t2.100000\t[乙] 你好。" in content
    assert "没有成功合成" not in content


def test_generate_subtitle_artifacts_writes_all_review_files(tmp_path: Path):
    segments = [
        {"text": "开场。", "speaker": "旁白", "emotion": "neutral"},
        {"text": "我们出发。", "speaker": "主角", "emotion": "firm"},
    ]
    timings = [
        {"index": 0, "start": 0.0, "end": 1.0, "duration": 1.0},
        {"index": 1, "start": 1.5, "end": 2.3, "duration": 0.8},
    ]

    result = generate_subtitle_artifacts(
        script_segments=segments,
        segment_timings=timings,
        output_path=str(tmp_path / "chapter_001.mp3"),
        title="第一章",
    )

    assert result["generated"] is True
    assert result["entry_count"] == 2
    for key in ("srt", "vtt", "ass", "audacity_labels"):
        assert Path(result["paths"][key]).exists()
    assert Path(result["paths"]["audacity_labels"]).read_text(encoding="utf-8").startswith(
        "0.000000\t1.000000\t[旁白] 开场。"
    )


def test_output_format_normalization_and_output_path():
    assert normalize_audiobook_output_format("m4a") == "m4b"
    assert normalize_audiobook_output_format("bad") == "mp3"
    assert build_chapter_audio_output_path(
        project_id=12,
        chapter_number=3,
        output_format="m4b",
    ) == "audiobooks/project_12/chapter_003.m4b"
    # 同一小说项目的多个有声书项目必须按 audiobook_project_id 隔离输出路径
    assert build_chapter_audio_output_path(
        project_id=12,
        chapter_number=3,
        output_format="m4b",
        audiobook_project_id=77,
    ) == "audiobooks/project_12/audiobook_77/chapter_003.m4b"


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg unavailable")
def test_audio_mixer_exports_m4b_container_when_ffmpeg_available():
    mixer = AudioMixer(
        enable_silence_trim=False,
        enable_loudness_norm=False,
        enable_semantic_pause=False,
    )

    audio_bytes = mixer.mix_chapter(
        [_silent_audio_bytes(500), _silent_audio_bytes(500)],
        output_format="m4b",
        segment_types=["sentence", "sentence"],
    )

    assert len(audio_bytes) > 0
    assert b"ftyp" in audio_bytes[:32]
