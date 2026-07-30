from __future__ import annotations

import asyncio
import sys
import threading
import wave
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.engine_pkg._scene_render_mixin import SceneRenderMixin
from app.services.audiobook.engine_pkg import _scene_render_mixin as scene_render_mixin_module
from app.services.audiobook.scene_engine.chapter_pipeline import (
    ChapterScenePipelineResult,
    ChapterSceneRender,
)
from app.services.audiobook.scene_engine.models import SceneRenderPlan
from app.services.audiobook.scene_engine.scene_assembler import (
    SceneAssemblyResult,
    SceneAssemblySubtitleEntry,
    SceneAssemblyTiming,
)
from app.services.audiobook.scene_engine.scene_renderer import SceneRenderResult
from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment
from app.services.audiobook.task_tracker import StageType


def _write_wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(b"\x00\x00" * 8000)
    return path


def _plan(scene_id: str, indices: tuple[int, ...]) -> SceneRenderPlan:
    return SceneRenderPlan(
        scene_id=scene_id,
        source_segment_indices=indices,
        expected_text="测试台词",
        expected_duration_s=1.0,
        speaker_names=("旁白",),
        references=(),
        prompt="旁白说：\"测试台词\"。",
        prompt_hash=f"prompt-{scene_id}",
        reference_hashes=(),
        boundary_before="开始neutral情绪，室内",
        boundary_after="结束neutral情绪，室内",
    )


class FakeTaskTracker:
    def __init__(self) -> None:
        self.started = []
        self.completed = []
        self.completed_tasks = []

    def start_stage(self, task_id, stage):
        self.started.append((task_id, stage))

    def complete_stage(self, task_id, stage, metrics=None):
        self.completed.append((task_id, stage, metrics or {}))

    def complete_task(self, task_id):
        self.completed_tasks.append(task_id)


class FakePipeline:
    def __init__(
        self,
        result: ChapterScenePipelineResult,
        checkpoint_snapshots=(),
    ) -> None:
        self.result = result
        self.calls = []
        self.checkpoint_snapshots = tuple(checkpoint_snapshots)
        self.checkpoint_persist_callback = None

    def render(self, segments, **kwargs):
        self.calls.append({"segments": segments, **kwargs})
        for snapshot in self.checkpoint_snapshots:
            if self.checkpoint_persist_callback:
                current_checkpoint = next(reversed(snapshot.values()))
                self.checkpoint_persist_callback(snapshot, current_checkpoint)
        return self.result


class FakeAssembler:
    def __init__(self) -> None:
        self.calls = []

    def assemble(self, scenes, *, output_path, output_format, fallback_audio_paths):
        self.calls.append(
            {
                "scenes": scenes,
                "output_path": Path(output_path),
                "output_format": output_format,
                "fallback_audio_paths": dict(fallback_audio_paths),
            }
        )
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"CHAPTER_AUDIO")
        return SceneAssemblyResult(
            audio_path=target,
            duration_s=2.2,
            scene_timings=(
                SceneAssemblyTiming(
                    scene_id="scene_0001",
                    start_s=0.0,
                    end_s=1.0,
                    duration_s=1.0,
                    pause_before_s=0.0,
                    audio_source="legacy_stems",
                ),
                SceneAssemblyTiming(
                    scene_id="scene_0002",
                    start_s=1.2,
                    end_s=2.2,
                    duration_s=1.0,
                    pause_before_s=0.2,
                    audio_source="seed_scene",
                ),
            ),
            subtitle_entries=(
                SceneAssemblySubtitleEntry(
                    index=1,
                    scene_id="scene_0001",
                    start_s=0.1,
                    end_s=0.8,
                    text="第一句",
                    speaker="旁白",
                ),
                SceneAssemblySubtitleEntry(
                    index=2,
                    scene_id="scene_0002",
                    start_s=1.3,
                    end_s=2.0,
                    text="第二句",
                    speaker="女主",
                    emotion="sad",
                ),
            ),
            output_format=output_format,
            loudness_normalized=True,
            loudness_report={"target_i": -16.0, "output_i": -16.1},
        )


class FakeTtsEngine:
    def __init__(self) -> None:
        self.model = "qwen3-tts-instruct-flash"
        self.estimated_cost_yuan = 0.0

    def get_cost_stats(self):
        return {
            "total_characters": 0,
            "total_segments": 0,
            "cache_hits": 0,
            "cache_hit_rate": "0.0%",
            "api_calls": 0,
            "failed_segments": 0,
            "failed_characters": 0,
            "estimated_cost": f"¥{self.estimated_cost_yuan:.2f}",
        }


class Harness(SceneRenderMixin):
    def __init__(self, *, pipeline=None, assembler=None) -> None:
        self._audio_engine_mode = "legacy_stems"
        self._scene_voice_mapping = {}
        self.task_tracker = FakeTaskTracker()
        self.tts_engine = FakeTtsEngine()
        self.fallback_tts_cost_increment = 0.0
        self.pipeline = pipeline
        self.assembler = assembler
        self.pipeline_factory_calls = []
        self.fallback_calls = []

    def _create_chapter_scene_pipeline(self, **kwargs):
        self.pipeline_factory_calls.append(kwargs)
        if self.pipeline is not None:
            self.pipeline.checkpoint_persist_callback = kwargs.get(
                "checkpoint_persist_callback"
            )
        return self.pipeline

    def _create_scene_audio_assembler(self):
        return self.assembler

    async def _render_legacy_scene_fallback(self, scene, script_segments, output_root):
        self.fallback_calls.append((scene.plan.scene_id, tuple(script_segments)))
        self.tts_engine.estimated_cost_yuan += self.fallback_tts_cost_increment
        return _write_wav(Path(output_root) / f"{scene.plan.scene_id}-fallback.wav")


class ReviewCaptureHarness(Harness):
    def __init__(self, *, pipeline=None, assembler=None) -> None:
        super().__init__(pipeline=pipeline, assembler=assembler)
        self.review_calls = []

    def _final_audio_review(self, **kwargs):
        self.review_calls.append(kwargs)
        return {"summary": "通过"}


class FakeLegacyFallbackMixer:
    def __init__(self) -> None:
        self.mix_calls = []

    def build_segment_timeline(self, audio_list, **kwargs):
        return [
            {"index": 0, "start": 0.0, "end": 3.0, "duration": 3.0},
            {"index": 1, "start": 3.5, "end": 5.0, "duration": 1.5},
        ]

    def mix_chapter(self, audio_list, **kwargs):
        self.mix_calls.append({"audio_list": list(audio_list), **kwargs})
        return b"MIXED_VOICE"


class LegacyFallbackHarness(SceneRenderMixin):
    def __init__(self) -> None:
        self.audio_mixer = FakeLegacyFallbackMixer()
        self._last_effect_timeline = {
            "timeline": [
                {
                    "scene_id": "scene_0",
                    "timestamp": 0.5,
                    "type": "action",
                    "duration": 1.0,
                },
                {
                    "scene_id": "scene_1",
                    "timestamp": 2.25,
                    "type": "environment",
                    "duration": 10.0,
                    "loop": True,
                },
                {
                    "scene_id": "scene_2",
                    "timestamp": 4.5,
                    "type": "action",
                    "duration": 2.0,
                },
            ]
        }
        self._last_music_timeline = {
            "timeline": [
                {
                    "scene_id": "shift_0",
                    "timestamp": 0.25,
                    "duration": 2.0,
                },
                {
                    "scene_id": "climax_2",
                    "timestamp": 4.2,
                    "duration": 10.0,
                },
            ]
        }
        self.synthesized_segments = []
        self.applied_tracks = []

    async def _synthesize_segments_with_resume(self, segments, **kwargs):
        self.synthesized_segments = list(segments)
        return {"audio_list": [b"VOICE_1", b"VOICE_2"]}

    @staticmethod
    def _build_mixer_segment_types(segments):
        return [segment.type for segment in segments]

    @staticmethod
    def _build_mixer_pause_after_ms(segments):
        return [100, 200]

    def _apply_sound_effects(self, audio_data, timeline):
        self.applied_tracks.append(("sfx", timeline))
        return audio_data + b"+SFX"

    def _apply_background_music(self, audio_data, timeline):
        self.applied_tracks.append(("music", timeline))
        return audio_data + b"+BGM"


def test_scene_render_mixin_is_available() -> None:
    assert SceneRenderMixin is not None


def test_legacy_scene_fallback_applies_only_rebased_local_sfx_and_music(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        scene_render_mixin_module,
        "estimate_narration_duration_seconds",
        lambda _text: 2.0,
    )
    harness = LegacyFallbackHarness()
    plan = _plan("scene_0002", (1, 2))
    scene = ChapterSceneRender(
        plan=plan,
        result=SceneRenderResult(
            scene_id=plan.scene_id,
            status="legacy_stems",
            action="legacy_stems",
            attempts=1,
            audio_path=None,
            subtitle_payload=None,
            quality_report=None,
            fallback_reason="transcript_fidelity_failed",
        ),
    )
    segments = [
        ScriptSegment("narration", "第一段", "旁白", "neutral"),
        ScriptSegment("dialogue", "第二段", "女主", "fearful"),
        ScriptSegment("narration", "第三段", "旁白", "tense"),
    ]

    output_path = asyncio.run(
        harness._render_legacy_scene_fallback(scene, segments, tmp_path)
    )

    assert [segment.text for segment in harness.synthesized_segments] == [
        "第二段",
        "第三段",
    ]
    assert output_path.read_bytes() == b"MIXED_VOICE+SFX+BGM"
    assert [track for track, _timeline in harness.applied_tracks] == ["sfx", "music"]

    effect_items = harness.applied_tracks[0][1]["timeline"]
    assert [item["scene_id"] for item in effect_items] == ["scene_1", "scene_2"]
    assert effect_items[0]["timestamp"] == pytest.approx(0.25)
    assert effect_items[0]["duration"] == pytest.approx(4.75)
    assert effect_items[1]["timestamp"] == pytest.approx(4.0)
    assert effect_items[1]["duration"] == pytest.approx(1.0)

    music_items = harness.applied_tracks[1][1]["timeline"]
    assert [item["scene_id"] for item in music_items] == ["climax_2"]
    assert music_items[0]["timestamp"] == pytest.approx(3.7)
    assert music_items[0]["duration"] == pytest.approx(1.3)


@pytest.mark.parametrize("mode", ["legacy_stems", "auto"])
def test_scene_render_mixin_keeps_non_explicit_modes_on_legacy_pipeline(mode: str) -> None:
    harness = Harness()
    harness._audio_engine_mode = mode

    result = asyncio.run(
        harness._try_generate_seed_scene_chapter(
            script_segments=[],
            chapter_id=3,
            task_id="task-1",
            output_path=None,
            output_format="mp3",
        )
    )

    assert result is None
    assert harness.pipeline_factory_calls == []


def test_scene_render_mixin_renders_seed_scenes_and_only_falls_back_failed_scene(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed_audio = _write_wav(tmp_path / "seed.wav")
    fallback_plan = _plan("scene_0001", (0,))
    passed_plan = _plan("scene_0002", (1,))
    pipeline_result = ChapterScenePipelineResult(
        scenes=(
            ChapterSceneRender(
                plan=fallback_plan,
                result=SceneRenderResult(
                    scene_id=fallback_plan.scene_id,
                    status="legacy_stems",
                    action="legacy_stems",
                    attempts=1,
                    audio_path=None,
                    subtitle_payload=None,
                    quality_report=None,
                    fallback_reason="transcript_fidelity_failed",
                ),
            ),
            ChapterSceneRender(
                plan=passed_plan,
                result=SceneRenderResult(
                    scene_id=passed_plan.scene_id,
                    status="passed",
                    action="assemble",
                    attempts=1,
                    audio_path=seed_audio,
                    subtitle_payload=[
                        {"text": "第二句", "start": 0.1, "end": 0.8}
                    ],
                    quality_report=None,
                ),
            ),
        )
    )
    pipeline = FakePipeline(pipeline_result)
    assembler = FakeAssembler()
    harness = Harness(pipeline=pipeline, assembler=assembler)
    harness._audio_engine_mode = "seed_scene"
    harness._seed_audio_model = "seed-audio-1.0"
    harness._scene_voice_mapping = {"旁白": {"voice_id": "narrator"}}
    harness.fallback_tts_cost_increment = 0.05
    segments = [
        ScriptSegment("narration", "第一句", "旁白", "neutral"),
        ScriptSegment("dialogue", "第二句", "女主", "sad"),
    ]

    result = asyncio.run(
        harness._try_generate_seed_scene_chapter(
            script_segments=segments,
            chapter_id=3,
            task_id="task-1",
            output_path=str(tmp_path / "chapter.wav"),
            output_format="wav",
            resume_checkpoint={
                "scene_checkpoints": {
                    "scene_0002": {
                        "status": "passed",
                        "billing_duration_s": 10.0,
                        "provider_request_ids": ["provider-request-1"],
                    }
                }
            },
            enable_quality_review=False,
        )
    )

    assert result is not None
    assert result["success"] is True
    assert result["audio_data"] == b"CHAPTER_AUDIO"
    assert result["duration"] == pytest.approx(2.2)
    assert result["stats"]["audio_info"]["loudness_normalized"] is True
    assert result["stats"]["audio_info"]["loudness_report"]["output_i"] == -16.1
    assert result["stats"]["scene_billing"]["actual_cost_yuan"] == 0.1667
    assert result["stats"]["tts_stats"]["estimated_cost"] == "¥0.2167"
    assert result["stats"]["tts_stats"]["cost_components"] == {
        "seed_audio_yuan": 0.1667,
        "legacy_fallback_tts_yuan": 0.05,
        "total_yuan": 0.2167,
    }
    assert result["stats"]["mode"] == "seed_scene"
    assert result["stats"]["scene_billing"]["model"] == "seed-audio-1.0"
    assert result["scene_render"]["fallback_scene_count"] == 1
    assert [item[0] for item in harness.fallback_calls] == ["scene_0001"]
    assert set(assembler.calls[0]["fallback_audio_paths"]) == {"scene_0001"}
    assert pipeline.calls[0]["voice_mapping"] == harness._scene_voice_mapping
    assert pipeline.calls[0]["model"] == "seed-audio-1.0"
    assert pipeline.calls[0]["checkpoints"] == {
        "scene_0002": {
            "status": "passed",
            "billing_duration_s": 10.0,
            "provider_request_ids": ["provider-request-1"],
        }
    }
    assert result["timing_segments_payload"] == [
        {"text": "第一句", "speaker": "旁白", "emotion": None},
        {"text": "第二句", "speaker": "女主", "emotion": "sad"},
    ]
    assert result["segment_timings"] == [
        {"index": 0, "start": 0.1, "end": 0.8, "duration": 0.7},
        {"index": 1, "start": 1.3, "end": 2.0, "duration": 0.7},
    ]
    assert ("task-1", StageType.TTS_SYNTHESIS) in harness.task_tracker.started
    assert ("task-1", StageType.AUDIO_MIXING) in harness.task_tracker.started
    assert ("task-1", StageType.FINAL_AUDIO_REVIEW) in harness.task_tracker.started
    assert harness.task_tracker.completed_tasks == ["task-1"]


def test_scene_render_mixin_reuses_valid_local_fallback_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DOUBAO_SEED_AUDIO_PRICE_PER_SECOND_YUAN", "0.02")
    fallback_plan = _plan("scene_0001", (0,))
    pipeline_result = ChapterScenePipelineResult(
        scenes=(
            ChapterSceneRender(
                plan=fallback_plan,
                result=SceneRenderResult(
                    scene_id=fallback_plan.scene_id,
                    status="legacy_stems",
                    action="legacy_stems",
                    attempts=1,
                    audio_path=None,
                    subtitle_payload=None,
                    quality_report=None,
                    fallback_reason="transcript_fidelity_failed",
                ),
            ),
        )
    )
    pipeline = FakePipeline(pipeline_result)
    harness = Harness(pipeline=pipeline, assembler=FakeAssembler())
    harness._audio_engine_mode = "seed_scene"
    segments = [ScriptSegment("narration", "第一句", "旁白", "neutral")]

    first = asyncio.run(
        harness._try_generate_seed_scene_chapter(
            script_segments=segments,
            chapter_id=3,
            task_id="fallback-resume-task",
            output_path=str(tmp_path / "chapter-first.wav"),
            output_format="wav",
            enable_quality_review=False,
        )
    )
    second = asyncio.run(
        harness._try_generate_seed_scene_chapter(
            script_segments=segments,
            chapter_id=3,
            task_id="fallback-resume-task",
            output_path=str(tmp_path / "chapter-second.wav"),
            output_format="wav",
            resume_checkpoint={
                "scene_checkpoints": first["scene_checkpoints"],
            },
            enable_quality_review=False,
        )
    )

    artifact = first["scene_checkpoints"]["scene_0001"]["fallback_artifact"]
    assert Path(artifact["audio_path"]).exists()
    assert artifact["audio_sha256"]
    assert artifact["file_size"] > 0
    assert artifact["quality_policy_hash"] == fallback_plan.quality_policy_hash
    assert len(harness.fallback_calls) == 1
    assert second["scene_checkpoints"]["scene_0001"]["fallback_artifact"] == artifact


def test_scene_render_mixin_final_review_uses_segment_presence_not_scene_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DOUBAO_SEED_AUDIO_PRICE_PER_SECOND_YUAN", "0.02")
    seed_audio = _write_wav(tmp_path / "seed.wav")
    first_plan = _plan("scene_0001", (0, 1))
    second_plan = _plan("scene_0002", (2,))
    pipeline = FakePipeline(
        ChapterScenePipelineResult(
            scenes=(
                ChapterSceneRender(
                    plan=first_plan,
                    result=SceneRenderResult(
                        scene_id=first_plan.scene_id,
                        status="passed",
                        action="assemble",
                        attempts=1,
                        audio_path=seed_audio,
                        subtitle_payload=None,
                        quality_report=None,
                    ),
                ),
                ChapterSceneRender(
                    plan=second_plan,
                    result=SceneRenderResult(
                        scene_id=second_plan.scene_id,
                        status="passed",
                        action="assemble",
                        attempts=1,
                        audio_path=seed_audio,
                        subtitle_payload=None,
                        quality_report=None,
                    ),
                ),
            )
        )
    )
    harness = ReviewCaptureHarness(pipeline=pipeline, assembler=FakeAssembler())
    harness._audio_engine_mode = "seed_scene"

    asyncio.run(
        harness._try_generate_seed_scene_chapter(
            script_segments=[
                ScriptSegment("narration", "第一句", "旁白", "neutral"),
                ScriptSegment("narration", "第二句", "旁白", "neutral"),
                ScriptSegment("narration", "第三句", "旁白", "neutral"),
            ],
            chapter_id=3,
            task_id="review-memory-task",
            output_path=str(tmp_path / "chapter.wav"),
            output_format="wav",
            enable_quality_review=True,
        )
    )

    assert len(harness.review_calls) == 1
    assert harness.review_calls[0]["audio_list"] is None
    assert harness.review_calls[0]["audio_presence"] == [True, True, True]


def test_scene_render_mixin_persists_each_checkpoint_on_event_loop_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plan = _plan("scene_0001", (0,))
    seed_audio = _write_wav(tmp_path / "seed.wav")
    pipeline = FakePipeline(
        ChapterScenePipelineResult(
            scenes=(
                ChapterSceneRender(
                    plan=plan,
                    result=SceneRenderResult(
                        scene_id=plan.scene_id,
                        status="passed",
                        action="assemble",
                        attempts=1,
                        audio_path=seed_audio,
                        subtitle_payload=None,
                        quality_report=None,
                    ),
                ),
            )
        ),
        checkpoint_snapshots=(
            {
                "scene_0001": {
                    "scene_id": "scene_0001",
                    "status": "passed",
                    "source_segment_indices": [0],
                }
            },
            {
                "scene_0001": {
                    "scene_id": "scene_0001",
                    "status": "passed",
                    "source_segment_indices": [0],
                },
                "scene_0002": {
                    "scene_id": "scene_0002",
                    "status": "passed",
                    "source_segment_indices": [1],
                },
            },
        ),
    )
    harness = Harness(pipeline=pipeline, assembler=FakeAssembler())
    harness._audio_engine_mode = "seed_scene"
    callback_calls = []
    websocket_calls = []
    event_loop_thread_id = threading.get_ident()

    class FakeWebSocketManager:
        async def send_audiobook_progress(self, **payload):
            websocket_calls.append((threading.get_ident(), payload))

    monkeypatch.setattr(scene_render_mixin_module, "WEBSOCKET_AVAILABLE", True)
    monkeypatch.setattr(
        scene_render_mixin_module,
        "ws_manager",
        FakeWebSocketManager(),
    )

    def persist_progress(payload):
        callback_calls.append((threading.get_ident(), payload))

    asyncio.run(
        harness._try_generate_seed_scene_chapter(
            script_segments=[
                ScriptSegment("narration", "first line", "narrator", "neutral"),
                ScriptSegment("narration", "second line", "narrator", "neutral"),
            ],
            chapter_id=3,
            audiobook_project_id=9,
            task_id="task-scene-progress",
            output_path=str(tmp_path / "chapter.wav"),
            output_format="wav",
            enable_quality_review=False,
            tts_progress_callback=persist_progress,
        )
    )

    assert [thread_id for thread_id, _ in callback_calls] == [
        event_loop_thread_id,
        event_loop_thread_id,
    ]
    assert callback_calls[0][1]["scene_checkpoints"] == {
        "scene_0001": {
            "scene_id": "scene_0001",
            "status": "passed",
            "source_segment_indices": [0],
        }
    }
    assert set(callback_calls[1][1]["scene_checkpoints"]) == {
        "scene_0001",
        "scene_0002",
    }
    assert callback_calls[1][1]["task_id"] == "task-scene-progress"
    assert callback_calls[0][1]["completed_segment_indices"] == [0]
    assert callback_calls[1][1]["completed_segment_indices"] == [0, 1]
    assert callback_calls[1][1]["total_segments"] == 2
    assert [thread_id for thread_id, _ in websocket_calls] == [
        event_loop_thread_id,
        event_loop_thread_id,
        event_loop_thread_id,
    ]
    assert [call["stage"] for _, call in websocket_calls] == [
        "scene_rendering",
        "scene_rendering",
        "scene_rendering",
    ]
    assert [call["progress"] for _, call in websocket_calls] == [0, 50, 100]
    assert websocket_calls[-1][1]["stage_metrics"]["scene_id"] == "scene_0002"


def test_scene_render_mixin_waits_for_same_loop_progress_tasks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed_audio = _write_wav(tmp_path / "seed-progress.wav")
    plan = _plan("scene_0001", (0,))
    pipeline = FakePipeline(
        ChapterScenePipelineResult(
            scenes=(
                ChapterSceneRender(
                    plan=plan,
                    result=SceneRenderResult(
                        scene_id=plan.scene_id,
                        status="passed",
                        action="assemble",
                        attempts=1,
                        audio_path=seed_audio,
                        subtitle_payload=None,
                        quality_report=None,
                    ),
                ),
            )
        ),
        checkpoint_snapshots=(
            {
                "scene_0001": {
                    "scene_id": "scene_0001",
                    "status": "passed",
                    "source_segment_indices": [0],
                }
            },
        ),
    )
    harness = Harness(pipeline=pipeline, assembler=FakeAssembler())
    harness._audio_engine_mode = "seed_scene"
    release_progress = asyncio.Event()
    completed_progress = []

    class DelayedWebSocketManager:
        async def send_audiobook_progress(self, **payload):
            if payload.get("progress") == 100:
                await release_progress.wait()
                completed_progress.append(payload["progress"])

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(scene_render_mixin_module, "WEBSOCKET_AVAILABLE", True)
    monkeypatch.setattr(
        scene_render_mixin_module,
        "ws_manager",
        DelayedWebSocketManager(),
    )
    monkeypatch.setattr(scene_render_mixin_module.asyncio, "to_thread", run_inline)

    async def run_scene():
        async def release_later():
            await asyncio.sleep(0.01)
            release_progress.set()

        asyncio.create_task(release_later())
        await harness._try_generate_seed_scene_chapter(
            script_segments=[
                ScriptSegment("narration", "first line", "narrator", "neutral")
            ],
            chapter_id=3,
            audiobook_project_id=9,
            task_id="task-same-loop-progress",
            output_path=str(tmp_path / "chapter-progress.wav"),
            output_format="wav",
            enable_quality_review=False,
        )

    asyncio.run(run_scene())

    assert completed_progress == [100]


def test_scene_pipeline_factory_forwards_accumulated_checkpoints(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from adapters.registry import registry

    requested_models = []

    def get_adapter(model):
        requested_models.append(model)
        return object()

    monkeypatch.setattr(registry, "get_adapter", get_adapter)
    checkpoint_updates = {
        "scene_0001": {"scene_id": "scene_0001", "status": "passed"}
    }
    persisted_snapshots = []

    pipeline = SceneRenderMixin._create_chapter_scene_pipeline(
        object(),
        run_root=tmp_path,
        checkpoint_updates=checkpoint_updates,
        checkpoint_persist_callback=(
            lambda snapshot, _current: persisted_snapshots.append(snapshot)
        ),
        model="seed-audio-1.0-multilingual",
    )
    pipeline.renderer.checkpoint_writer(
        {"scene_id": "scene_0002", "status": "passed"}
    )

    assert set(checkpoint_updates) == {"scene_0001", "scene_0002"}
    assert set(persisted_snapshots[0]) == {"scene_0001", "scene_0002"}
    assert pipeline.provider_attempt_ledger.path == tmp_path / "provider_attempts.jsonl"
    assert pipeline.renderer.provider_attempt_recorder == pipeline.provider_attempt_ledger.record
    assert requested_models == ["seed-audio-1.0-multilingual"]


def test_scene_pipeline_factory_injects_configured_asr_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from adapters.registry import registry

    class FakeAsrResult:
        transcript = "识别后的台词"
        provider = "fake-asr"
        model = "fake-asr-v1"
        metadata = {
            "request_id": "asr-request-1",
            "usage": {"duration": 3},
            "raw_output": {"must_not_persist": True},
        }
        subtitle_payload = {
            "segments": [
                {"text": "识别后的台词", "start_ms": 120, "end_ms": 980}
            ]
        }

    class FakeAsrProvider:
        supports_timestamps = True

        def __init__(self) -> None:
            self.paths = []

        def transcribe(self, audio_path: str):
            self.paths.append(audio_path)
            return FakeAsrResult()

    asr_provider = FakeAsrProvider()
    monkeypatch.setenv("PROMPT_AUDIO_ASR_MAX_ATTEMPTS_PER_SCENE", "1")
    monkeypatch.setenv("PROMPT_AUDIO_ASR_MAX_COST_YUAN_PER_SCENE", "0.05")
    monkeypatch.setattr(registry, "get_adapter", lambda _model: object())
    monkeypatch.setattr(
        scene_render_mixin_module,
        "create_prompt_audio_asr_provider",
        lambda: asr_provider,
        raising=False,
    )

    pipeline = SceneRenderMixin._create_chapter_scene_pipeline(
        object(),
        run_root=tmp_path,
        checkpoint_updates={},
    )
    audio_path = tmp_path / "scene.wav"

    transcription = pipeline.renderer.asr_provider(audio_path)

    assert transcription == {
        "transcript": "识别后的台词",
        "subtitle_payload": {
            "segments": [
                {"text": "识别后的台词", "start_ms": 120, "end_ms": 980}
            ]
        },
        "provider": "fake-asr",
        "model": "fake-asr-v1",
        "metadata": {
            "request_id": "asr-request-1",
            "usage": {"duration": 3},
        },
    }
    assert pipeline.renderer.asr_provider.supports_timestamps is True
    assert pipeline.renderer.max_asr_attempts_per_scene == 1
    assert pipeline.renderer.max_asr_cost_yuan_per_scene == 0.05
    assert asr_provider.paths == [str(audio_path)]


def test_scene_pipeline_factory_injects_resolved_db_session_factory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from adapters.registry import registry

    sentinel_factory = object()
    monkeypatch.setattr(registry, "get_adapter", lambda _model: object())
    monkeypatch.setattr(
        scene_render_mixin_module,
        "_resolve_db_session_factory",
        lambda: sentinel_factory,
        raising=False,
    )

    pipeline = SceneRenderMixin._create_chapter_scene_pipeline(
        object(),
        run_root=tmp_path,
        checkpoint_updates={},
    )

    assert pipeline.db_session_factory is sentinel_factory


def test_resolve_db_session_factory_returns_session_local() -> None:
    from app.db.base import SessionLocal

    assert scene_render_mixin_module._resolve_db_session_factory() is SessionLocal


@pytest.mark.parametrize(
    "relative_path",
    [
        "app/services/audiobook/engine_pkg/_generation_mixin.py",
        "app/services/audiobook/engine_pkg/_audio_from_script_mixin.py",
    ],
)
def test_both_chapter_entries_call_shared_scene_pipeline_before_legacy_tts(
    relative_path: str,
) -> None:
    source = (ROOT_DIR / relative_path).read_text(encoding="utf-8")

    assert source.count("await self._try_generate_seed_scene_chapter(") == 1
    assert source.index("await self._try_generate_seed_scene_chapter(") < source.index(
        "await self._synthesize_segments_with_resume("
    )
    assert "tts_progress_callback=tts_progress_callback" in source
    assert "audiobook_project_id=audiobook_project_id" in source
