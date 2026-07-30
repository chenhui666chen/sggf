from __future__ import annotations

import json
import shutil
import struct
import sys
import wave
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydub import AudioSegment


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.chapter_pipeline import ChapterSceneRender
from app.services.audiobook.scene_engine.loudness_normalizer import (
    FFmpegLoudnessNormalizer,
    LoudnessNormalizationError,
)
from app.services.audiobook.scene_engine.models import SceneRenderPlan
from app.services.audiobook.scene_engine.scene_assembler import (
    SceneAssemblyError,
    SceneAudioAssembler,
)
from app.services.audiobook.scene_engine.scene_renderer import SceneRenderResult


class PassthroughLoudnessNormalizer:
    def __init__(self) -> None:
        self.calls = []

    def normalize(self, input_path, output_path, *, output_format):
        self.calls.append(
            {
                "input_path": Path(input_path),
                "output_path": Path(output_path),
                "output_format": output_format,
            }
        )
        shutil.copyfile(input_path, output_path)
        return {
            "normalized": True,
            "target_i": -16.0,
            "output_i": -16.1,
        }


class MeasuringLoudnessNormalizer(PassthroughLoudnessNormalizer):
    def __init__(self, measurements: dict[str, dict[str, float]]) -> None:
        super().__init__()
        self.measurements = measurements
        self.measure_calls: list[Path] = []

    def measure(self, input_path):
        path = Path(input_path)
        self.measure_calls.append(path)
        return dict(self.measurements[path.name])


def _assembler(normalizer=None) -> SceneAudioAssembler:
    return SceneAudioAssembler(
        loudness_normalizer=normalizer or PassthroughLoudnessNormalizer()
    )


def _write_wav(
    path: Path,
    *,
    duration_ms: int = 1000,
    amplitude: int = 0,
) -> Path:
    sample_rate = 8000
    frame_count = sample_rate * duration_ms // 1000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(struct.pack("<h", amplitude) * frame_count)
    return path


def _plan(scene_id: str, *, before: str, after: str) -> SceneRenderPlan:
    return SceneRenderPlan(
        scene_id=scene_id,
        source_segment_indices=(0,),
        expected_text="测试台词",
        expected_duration_s=1.0,
        speaker_names=("旁白",),
        references=(),
        prompt="旁白说：\"测试台词\"。",
        prompt_hash=f"prompt-{scene_id}",
        reference_hashes=(),
        boundary_before=before,
        boundary_after=after,
    )


def _scene(
    plan: SceneRenderPlan,
    *,
    audio_path: Path | None,
    subtitle_payload=None,
    status: str = "passed",
) -> ChapterSceneRender:
    return ChapterSceneRender(
        plan=plan,
        result=SceneRenderResult(
            scene_id=plan.scene_id,
            status=status,
            action="assemble" if status == "passed" else "legacy_stems",
            attempts=1,
            audio_path=audio_path,
            subtitle_payload=subtitle_payload,
            quality_report=None,
        ),
    )


def test_scene_audio_assembler_is_available() -> None:
    assert SceneAudioAssembler is not None


def test_scene_assembler_uses_long_pause_for_location_change_and_offsets_subtitles(
    tmp_path: Path,
) -> None:
    first_audio = _write_wav(tmp_path / "first.wav")
    second_audio = _write_wav(tmp_path / "second.wav")
    scenes = (
        _scene(
            _plan(
                "scene_0001",
                before="开始tense情绪，深夜内殿",
                after="结束tense情绪，深夜内殿",
            ),
            audio_path=first_audio,
            subtitle_payload={
                "subtitles": [
                    {
                        "text": "第一句",
                        "speaker": "旁白",
                        "start_ms": 100,
                        "end_ms": 600,
                    }
                ]
            },
        ),
        _scene(
            _plan(
                "scene_0002",
                before="开始calm情绪，清晨城门",
                after="结束calm情绪，清晨城门",
            ),
            audio_path=second_audio,
            subtitle_payload=[{"text": "第二句", "start": 0.2, "end": 0.7}],
        ),
    )

    result = _assembler().assemble(
        scenes,
        output_path=tmp_path / "chapter.wav",
        output_format="wav",
    )

    assert result.audio_path.exists()
    assert result.duration_s == pytest.approx(2.75, abs=0.02)
    assert [(item.start_s, item.end_s, item.pause_before_s) for item in result.scene_timings] == [
        (0.0, 1.0, 0.0),
        (1.75, 2.75, 0.75),
    ]
    assert [item.text for item in result.subtitle_entries] == ["第一句", "第二句"]
    assert result.subtitle_entries[0].start_s == pytest.approx(0.1)
    assert result.subtitle_entries[0].end_s == pytest.approx(0.6)
    assert result.subtitle_entries[1].start_s == pytest.approx(1.95)
    assert result.subtitle_entries[1].end_s == pytest.approx(2.45)


def test_scene_assembler_treats_seed_sentence_times_as_milliseconds(
    tmp_path: Path,
) -> None:
    audio_path = _write_wav(tmp_path / "seed.wav", duration_ms=2000)
    scene = _scene(
        _plan(
            "scene_0001",
            before="start:neutral:room",
            after="end:neutral:room",
        ),
        audio_path=audio_path,
        subtitle_payload={
            "text": "first line second line",
            "sentences": [
                {"text": "first line", "start_time": 100, "end_time": 600},
                {"text": "second line", "start_time": 900, "end_time": 1500},
            ],
        },
    )

    result = _assembler().assemble(
        (scene,),
        output_path=tmp_path / "seed-chapter.wav",
        output_format="wav",
    )

    assert [entry.text for entry in result.subtitle_entries] == [
        "first line",
        "second line",
    ]
    assert result.subtitle_entries[0].start_s == pytest.approx(0.1)
    assert result.subtitle_entries[0].end_s == pytest.approx(0.6)
    assert result.subtitle_entries[1].start_s == pytest.approx(0.9)
    assert result.subtitle_entries[1].end_s == pytest.approx(1.5)


def test_scene_assembler_uses_short_pause_inside_same_location() -> None:
    first = _plan(
        "scene_0001_split_01",
        before="开始tense情绪，深夜审讯室",
        after="结束tense情绪，深夜审讯室",
    )
    second = _plan(
        "scene_0001_split_02",
        before="开始calm情绪，深夜审讯室",
        after="结束calm情绪，深夜审讯室",
    )

    assert SceneAudioAssembler.transition_pause_ms(first, second) == 180


def test_scene_assembler_requires_audio_for_legacy_fallback_scene(tmp_path: Path) -> None:
    plan = _plan(
        "scene_0001",
        before="开始neutral情绪",
        after="结束neutral情绪",
    )
    scene = _scene(plan, audio_path=None, status="legacy_stems")
    assembler = _assembler()

    with pytest.raises(SceneAssemblyError, match="scene_audio_missing:scene_0001"):
        assembler.assemble(
            (scene,),
            output_path=tmp_path / "missing.wav",
            output_format="wav",
        )

    fallback_audio = _write_wav(tmp_path / "fallback.wav", duration_ms=500)
    result = assembler.assemble(
        (scene,),
        output_path=tmp_path / "fallback-chapter.wav",
        output_format="wav",
        fallback_audio_paths={"scene_0001": fallback_audio},
    )

    assert result.duration_s == pytest.approx(0.5, abs=0.02)
    assert result.scene_timings[0].audio_source == "legacy_stems"


def test_scene_assembler_exports_pcm_through_loudness_normalizer(
    tmp_path: Path,
) -> None:
    normalizer = PassthroughLoudnessNormalizer()
    plan = _plan(
        "scene_0001",
        before="开始neutral情绪，书房",
        after="结束neutral情绪，书房",
    )
    audio_path = _write_wav(tmp_path / "scene.wav")

    result = _assembler(normalizer).assemble(
        (_scene(plan, audio_path=audio_path),),
        output_path=tmp_path / "chapter.wav",
        output_format="wav",
    )

    assert result.audio_path.exists()
    assert result.loudness_normalized is True
    assert result.loudness_report["target_i"] == -16.0
    assert len(normalizer.calls) == 1
    assert normalizer.calls[0]["input_path"].suffix == ".wav"
    assert normalizer.calls[0]["output_format"] == "wav"


def test_scene_assembler_balances_dialogue_scenes_before_final_loudnorm(
    tmp_path: Path,
) -> None:
    first_audio = _write_wav(tmp_path / "first.wav", amplitude=1000)
    second_audio = _write_wav(tmp_path / "second.wav", amplitude=1000)
    normalizer = MeasuringLoudnessNormalizer(
        {
            "first.wav": {"input_i": -24.0, "input_tp": -12.0},
            "second.wav": {"input_i": -18.0, "input_tp": -12.0},
        }
    )
    first_plan = _plan(
        "scene_0001",
        before="开始neutral情绪，书房",
        after="结束neutral情绪，书房",
    )
    second_plan = _plan(
        "scene_0002",
        before="开始neutral情绪，书房",
        after="结束neutral情绪，书房",
    )

    result = _assembler(normalizer).assemble(
        (
            _scene(first_plan, audio_path=first_audio),
            _scene(second_plan, audio_path=second_audio),
        ),
        output_path=tmp_path / "balanced.wav",
        output_format="wav",
    )

    rendered = AudioSegment.from_file(result.audio_path)
    first_segment = rendered[:1000]
    second_segment = rendered[1180:2180]
    balancing = result.loudness_report["scene_balancing"]

    assert balancing["applied"] is True
    assert balancing["target_i"] == pytest.approx(-21.0)
    assert balancing["eligible_scene_count"] == 2
    assert [item["gain_db"] for item in balancing["scenes"]] == [3.0, -3.0]
    assert first_segment.dBFS - second_segment.dBFS == pytest.approx(6.0, abs=0.2)
    assert len(normalizer.calls) == 1


def test_scene_assembler_excludes_non_dialogue_scene_from_loudness_baseline(
    tmp_path: Path,
) -> None:
    dialogue_audio = _write_wav(tmp_path / "dialogue.wav", amplitude=1000)
    ambience_audio = _write_wav(tmp_path / "ambience.wav", amplitude=1000)
    normalizer = MeasuringLoudnessNormalizer(
        {
            "dialogue.wav": {"input_i": -20.0, "input_tp": -10.0},
            "ambience.wav": {"input_i": -8.0, "input_tp": -3.0},
        }
    )
    dialogue_plan = _plan(
        "scene_dialogue",
        before="开始neutral情绪，庭院",
        after="结束neutral情绪，庭院",
    )
    ambience_plan = replace(
        _plan(
            "scene_ambience",
            before="开始neutral情绪，庭院",
            after="结束neutral情绪，庭院",
        ),
        expected_text="",
    )

    result = _assembler(normalizer).assemble(
        (
            _scene(dialogue_plan, audio_path=dialogue_audio),
            _scene(ambience_plan, audio_path=ambience_audio),
        ),
        output_path=tmp_path / "environment.wav",
        output_format="wav",
    )

    balancing = result.loudness_report["scene_balancing"]

    assert balancing["applied"] is False
    assert balancing["reason"] == "insufficient_dialogue_scenes"
    assert balancing["eligible_scene_count"] == 1
    assert [item["gain_db"] for item in balancing["scenes"]] == [0.0, 0.0]


def test_scene_assembler_caps_positive_gain_by_true_peak_headroom(
    tmp_path: Path,
) -> None:
    quiet_audio = _write_wav(tmp_path / "quiet.wav", amplitude=1000)
    normal_audio = _write_wav(tmp_path / "normal.wav", amplitude=1000)
    normalizer = MeasuringLoudnessNormalizer(
        {
            "quiet.wav": {"input_i": -30.0, "input_tp": -2.0},
            "normal.wav": {"input_i": -18.0, "input_tp": -8.0},
        }
    )
    scenes = tuple(
        _scene(
            _plan(
                scene_id,
                before="开始neutral情绪，房间",
                after="结束neutral情绪，房间",
            ),
            audio_path=audio_path,
        )
        for scene_id, audio_path in (
            ("scene_quiet", quiet_audio),
            ("scene_normal", normal_audio),
        )
    )

    result = _assembler(normalizer).assemble(
        scenes,
        output_path=tmp_path / "true-peak.wav",
        output_format="wav",
    )

    balancing = result.loudness_report["scene_balancing"]
    quiet_report = balancing["scenes"][0]

    assert balancing["target_i"] == pytest.approx(-24.0)
    assert quiet_report["requested_gain_db"] == 3.0
    assert quiet_report["gain_db"] == pytest.approx(0.5)
    assert quiet_report["limited_by_true_peak"] is True


def test_ffmpeg_loudness_normalizer_runs_measurement_then_linear_render(
    tmp_path: Path,
) -> None:
    commands = []
    measurement = {
        "input_i": "-23.10",
        "input_tp": "-4.20",
        "input_lra": "5.30",
        "input_thresh": "-33.40",
        "target_offset": "0.15",
    }
    output_measurement = {
        **measurement,
        "output_i": "-16.05",
        "output_tp": "-1.55",
        "output_lra": "5.20",
        "output_thresh": "-26.20",
    }

    def run(command, **_kwargs):
        commands.append(command)
        if len(commands) == 1:
            return SimpleNamespace(
                returncode=0,
                stdout="",
                stderr=f"ffmpeg log\n{json.dumps(measurement)}\n",
            )
        Path(command[-1]).write_bytes(b"normalized-audio")
        return SimpleNamespace(
            returncode=0,
            stdout="",
            stderr=f"ffmpeg log\n{json.dumps(output_measurement)}\n",
        )

    source = tmp_path / "source.wav"
    source.write_bytes(b"pcm")
    target = tmp_path / "target.mp3"
    normalizer = FFmpegLoudnessNormalizer(
        ffmpeg_path="ffmpeg",
        command_runner=run,
    )

    report = normalizer.normalize(source, target, output_format="mp3")

    assert target.read_bytes() == b"normalized-audio"
    assert len(commands) == 2
    assert "print_format=json" in commands[0][commands[0].index("-af") + 1]
    second_filter = commands[1][commands[1].index("-af") + 1]
    assert "measured_I=-23.10" in second_filter
    assert "measured_TP=-4.20" in second_filter
    assert "measured_LRA=5.30" in second_filter
    assert "measured_thresh=-33.40" in second_filter
    assert "offset=0.15" in second_filter
    assert "linear=true" in second_filter
    assert report["normalized"] is True
    assert report["output_i"] == pytest.approx(-16.05)


def test_ffmpeg_loudness_normalizer_exposes_measurement_without_rendering(
    tmp_path: Path,
) -> None:
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout="",
            stderr=json.dumps(
                {
                    "input_i": "-21.25",
                    "input_tp": "-3.50",
                    "input_lra": "4.20",
                    "input_thresh": "-31.40",
                    "target_offset": "0.10",
                }
            ),
        )

    source = tmp_path / "source.wav"
    source.write_bytes(b"pcm")
    normalizer = FFmpegLoudnessNormalizer(
        ffmpeg_path="ffmpeg",
        command_runner=run,
    )

    report = normalizer.measure(source)

    assert len(commands) == 1
    assert commands[0][-2:] == ["null", "-"]
    assert report["input_i"] == pytest.approx(-21.25)
    assert report["input_tp"] == pytest.approx(-3.5)


def test_ffmpeg_loudness_normalizer_rejects_non_finite_measurement(
    tmp_path: Path,
) -> None:
    def run(_command, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="",
            stderr=json.dumps(
                {
                    "input_i": "-inf",
                    "input_tp": "-inf",
                    "input_lra": "0.00",
                    "input_thresh": "-70.00",
                    "target_offset": "inf",
                }
            ),
        )

    source = tmp_path / "source.wav"
    source.write_bytes(b"silence")
    normalizer = FFmpegLoudnessNormalizer(
        ffmpeg_path="ffmpeg",
        command_runner=run,
    )

    with pytest.raises(
        LoudnessNormalizationError,
        match="loudnorm_measurement_invalid",
    ):
        normalizer.normalize(source, tmp_path / "target.wav", output_format="wav")
