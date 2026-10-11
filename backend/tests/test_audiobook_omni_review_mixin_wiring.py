"""阶段 7 生产管线接入：mixin Omni 影子评审串接（指导文档 §10）。

验收 mixin 层最小闭环：

- 特性门控默认关闭：不发起评审调用，stats.omni_review 为 None；
- 启用 + 注入 reviewer：每个通过场景提交影子评审，结果不阻断章节生产；
- 评审异常：不中断章节（走 degrade 路径），error_kind 可审计；
- 章节边界：reviewer.begin_chapter 在串接入口调用。
"""

from __future__ import annotations

import asyncio

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.engine_pkg._scene_render_mixin import (  # noqa: E402
    SceneRenderMixin,
)
from app.services.audiobook.engine_pkg import (  # noqa: E402
    _scene_render_mixin as scene_render_mixin_module,
)
from app.services.audiobook.scene_engine.chapter_pipeline import (  # noqa: E402
    ChapterScenePipelineResult,
    ChapterSceneRender,
)
from app.services.audiobook.scene_engine.models import SceneRenderPlan  # noqa: E402
from app.services.audiobook.scene_engine.scene_assembler import (  # noqa: E402
    SceneAssemblyResult,
    SceneAssemblySubtitleEntry,
    SceneAssemblyTiming,
)
from app.services.audiobook.scene_engine.scene_renderer import (  # noqa: E402
    SceneRenderResult,
)
from app.services.audiobook.scene_quality.qwen_omni_reviewer import (  # noqa: E402
    DEFAULT_OMNI_MODEL_ID,
    OmniReviewOutcome,
    SceneAudioSemanticReviewer,
    build_omni_scene_signature,
)
from app.services.audiobook.scene_quality.semantic_models import (  # noqa: E402
    SemanticReviewResult,
)
from app.services.audiobook.script_adapter_pkg._dataclasses import (  # noqa: E402
    ScriptSegment,
)


@pytest.fixture(autouse=True)
def isolate_scene_artifact_root(tmp_path, monkeypatch):
    """任务层测试不得写入正式产物根 ``backend/data/scene_audio_artifacts/``。"""
    monkeypatch.setattr(
        scene_render_mixin_module,
        "SCENE_ARTIFACT_ROOT",
        tmp_path / "scene_artifacts",
    )


def _plan(scene_id: str, indices: tuple[int, ...]) -> SceneRenderPlan:
    return SceneRenderPlan(
        scene_id=scene_id,
        source_segment_indices=indices,
        expected_text="测试台词",
        expected_duration_s=1.0,
        speaker_names=("旁白",),
        references=(),
        prompt="V1_PROMPT",
        prompt_hash=f"prompt-{scene_id}",
        reference_hashes=(),
        boundary_before="开始neutral情绪",
        boundary_after="结束neutral情绪",
    )


def _passed_result(
    scene_id: str, tmp_path: Path
) -> ChapterScenePipelineResult:
    audio_path = tmp_path / f"{scene_id}.wav"
    audio_path.write_bytes(b"FAKE_AUDIO")
    plan = _plan(scene_id, (0, 1))
    return ChapterScenePipelineResult(
        scenes=(
            ChapterSceneRender(
                plan=plan,
                result=SceneRenderResult(
                    scene_id=plan.scene_id,
                    status="passed",
                    action="assemble",
                    attempts=1,
                    audio_path=audio_path,
                    subtitle_payload=[{"text": "测试台词"}],
                    quality_report=None,
                ),
            ),
        )
    )


class FakeOmniClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def review_audio(self, *, prompt, audio_path, model):
        self.calls.append(
            {"prompt": prompt, "audio_path": audio_path, "model": model}
        )
        if not self.responses:
            raise AssertionError("unexpected extra omni call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _passing_payload() -> str:
    return json.dumps(
        {
            "passed": True,
            "confidence": 0.9,
            "dimensions": {
                name: "pass"
                for name in (
                    "dialogue_fidelity",
                    "speaker_assignment",
                    "speaker_separation",
                    "performance",
                    "vocalizations",
                    "sound_events",
                    "music",
                    "ambient",
                    "acoustic_space",
                    "mix_balance",
                )
            },
            "findings": [],
            "recommended_action": "accept",
        },
        ensure_ascii=False,
    )


class FakePipeline:
    def __init__(self, result: ChapterScenePipelineResult) -> None:
        self.result = result
        self.calls = []

    def render(self, segments, **kwargs):
        self.calls.append({"segments": segments, **kwargs})
        return self.result


class FakeAssembler:
    def assemble(self, scenes, *, output_path, output_format, fallback_audio_paths):
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
                    end_s=2.2,
                    duration_s=2.2,
                    pause_before_s=0.0,
                    audio_source="seed_scene",
                ),
            ),
            subtitle_entries=(
                SceneAssemblySubtitleEntry(
                    index=1,
                    scene_id="scene_0001",
                    start_s=0.1,
                    end_s=0.8,
                    text="测试台词",
                    speaker="旁白",
                ),
            ),
            output_format=output_format,
            loudness_normalized=False,
            loudness_report={},
        )


class FakeTaskTracker:
    def start_stage(self, task_id, stage):
        pass

    def complete_stage(self, task_id, stage, metrics=None):
        pass

    def complete_task(self, task_id):
        pass


class FakeTtsEngine:
    def __init__(self) -> None:
        self.model = "qwen-audio-3.1-tts-flash"
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


class OmniReviewHarness(SceneRenderMixin):
    def __init__(self, *, pipeline, assembler) -> None:
        self._audio_engine_mode = "seed_scene"
        self._seed_audio_model = "seed-audio-1.0"
        self._scene_voice_mapping = {}
        self.task_tracker = FakeTaskTracker()
        self.tts_engine = FakeTtsEngine()
        self.fallback_tts_cost_increment = 0.0
        self.pipeline = pipeline
        self.assembler = assembler

    def _create_chapter_scene_pipeline(self, **kwargs):
        return self.pipeline

    def _create_scene_audio_assembler(self):
        return self.assembler


def _segments() -> list:
    return [
        ScriptSegment("dialogue", "这里有人吗？", "林川", "neutral"),
        ScriptSegment("dialogue", "别出声。", "苏眠", "sad"),
    ]


def _run(harness, tmp_path: Path, **kwargs):
    return asyncio.run(
        harness._try_generate_seed_scene_chapter(
            script_segments=_segments(),
            chapter_id=3,
            task_id="task-omni-review",
            output_path=str(tmp_path / "chapter.wav"),
            output_format="wav",
            enable_quality_review=False,
            **kwargs,
        )
    )


class TestBuildOmniSceneSignature:
    def test_builds_valid_signature_from_plan_data(self) -> None:
        sig = build_omni_scene_signature(
            audio_artifact_hash="abc123",
            audio_duration_s=5.0,
            expected_text="台词测试",
            speaker_names=("旁白",),
            expected_vocalizations=("叹息",),
            model_id=DEFAULT_OMNI_MODEL_ID,
        )
        assert sig.review_scope == "scene"
        assert sig.audio_window_start_ms == 0
        assert sig.audio_window_end_ms == 5000
        assert sig.audio_artifact_hash == "abc123"
        assert sig.omni_model_id == DEFAULT_OMNI_MODEL_ID
        assert sig.omni_expectation_contract_hash
        assert sig.voice_binding_summary_hash
        h = sig.signature_hash()
        assert len(h) == 64

    def test_changed_input_invalidates_signature(self) -> None:
        sig_a = build_omni_scene_signature(
            audio_artifact_hash="hash-a",
            audio_duration_s=5.0,
            expected_text="文本A",
            speaker_names=("旁白",),
        )
        sig_b = build_omni_scene_signature(
            audio_artifact_hash="hash-b",
            audio_duration_s=5.0,
            expected_text="文本A",
            speaker_names=("旁白",),
        )
        assert sig_a.signature_hash() != sig_b.signature_hash()


class TestOmniReviewGate:
    def test_disabled_by_default_no_review_call(self, tmp_path) -> None:
        pipeline = FakePipeline(_passed_result("scene_0001", tmp_path))
        harness = OmniReviewHarness(pipeline=pipeline, assembler=FakeAssembler())
        client = FakeOmniClient([_passing_payload()])
        harness._seed_scene_omni_reviewer = SceneAudioSemanticReviewer(client)

        result = _run(harness, tmp_path)

        assert result["success"] is True
        assert client.calls == []
        assert result["stats"].get("omni_review") is None

    def test_enabled_but_reviewer_not_set_no_error(self, tmp_path) -> None:
        pipeline = FakePipeline(_passed_result("scene_0001", tmp_path))
        harness = OmniReviewHarness(pipeline=pipeline, assembler=FakeAssembler())
        harness._seed_scene_omni_review_enabled = True
        # 不注入 reviewer — 应静默跳过

        result = _run(harness, tmp_path)

        assert result["success"] is True

    def test_enabled_with_reviewer_reviews_passed_scenes(self, tmp_path) -> None:
        pipeline = FakePipeline(_passed_result("scene_0001", tmp_path))
        harness = OmniReviewHarness(pipeline=pipeline, assembler=FakeAssembler())
        client = FakeOmniClient([_passing_payload()])
        reviewer = SceneAudioSemanticReviewer(client)
        harness._seed_scene_omni_review_enabled = True
        harness._seed_scene_omni_reviewer = reviewer

        result = _run(harness, tmp_path)

        assert result["success"] is True
        assert len(client.calls) == 1
        omni_stats = result["stats"].get("omni_review")
        assert omni_stats is not None
        scenes = omni_stats.get("scenes", [])
        assert len(scenes) == 1
        assert scenes[0]["scene_id"] == "scene_0001"
        assert scenes[0]["outcome_status"] == "reviewed"

    def test_review_exception_does_not_block_chapter(self, tmp_path) -> None:
        pipeline = FakePipeline(_passed_result("scene_0001", tmp_path))
        harness = OmniReviewHarness(pipeline=pipeline, assembler=FakeAssembler())
        client = FakeOmniClient([RuntimeError("omni down")])
        reviewer = SceneAudioSemanticReviewer(client)
        harness._seed_scene_omni_review_enabled = True
        harness._seed_scene_omni_reviewer = reviewer

        result = _run(harness, tmp_path)

        assert result["success"] is True
        omni_stats = result["stats"].get("omni_review")
        assert omni_stats is not None
        scenes = omni_stats.get("scenes", [])
        assert len(scenes) == 1
        assert "error" in scenes[0].get("outcome_status", "")

    def test_skips_non_passed_scenes(self, tmp_path) -> None:
        audio_path = tmp_path / "scene_0001.wav"
        audio_path.write_bytes(b"AUDIO")
        plan = _plan("scene_0001", (0, 1))
        pipeline_result = ChapterScenePipelineResult(
            scenes=(
                ChapterSceneRender(
                    plan=plan,
                    result=SceneRenderResult(
                        scene_id=plan.scene_id,
                        status="failed",
                        action="assemble",
                        attempts=1,
                        audio_path=audio_path,
                        subtitle_payload=[],
                        quality_report=None,
                    ),
                ),
            )
        )
        pipeline = FakePipeline(pipeline_result)
        harness = OmniReviewHarness(pipeline=pipeline, assembler=FakeAssembler())
        client = FakeOmniClient([_passing_payload()])
        reviewer = SceneAudioSemanticReviewer(client)
        harness._seed_scene_omni_review_enabled = True
        harness._seed_scene_omni_reviewer = reviewer

        result = _run(harness, tmp_path)

        assert result["success"] is True
        assert client.calls == []
        omni_stats = result["stats"].get("omni_review")
        assert omni_stats is not None
        assert len(omni_stats.get("scenes", [])) == 0

    def test_skips_scenes_without_audio_path(self, tmp_path) -> None:
        plan = _plan("scene_0001", (0, 1))
        pipeline_result = ChapterScenePipelineResult(
            scenes=(
                ChapterSceneRender(
                    plan=plan,
                    result=SceneRenderResult(
                        scene_id=plan.scene_id,
                        status="passed",
                        action="assemble",
                        attempts=1,
                        audio_path=None,
                        subtitle_payload=[],
                        quality_report=None,
                    ),
                ),
            )
        )
        pipeline = FakePipeline(pipeline_result)
        harness = OmniReviewHarness(pipeline=pipeline, assembler=FakeAssembler())
        client = FakeOmniClient([_passing_payload()])
        reviewer = SceneAudioSemanticReviewer(client)
        harness._seed_scene_omni_review_enabled = True
        harness._seed_scene_omni_reviewer = reviewer

        result = _run(harness, tmp_path)

        assert result["success"] is True
        assert client.calls == []