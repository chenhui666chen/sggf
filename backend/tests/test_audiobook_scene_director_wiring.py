"""阶段 7 生产管线接入：_scene_render_mixin 任务层导演编排串接（§4.2/§9）。

验收任务层最小闭环：

- 特性门控默认关闭：不发起导演调用，directed_prompts 不下发；
- 启用 + 导演成功：pipeline.render 收到按 scene_key 的编排 Prompt，
  stats.director 审计元数据为 use_v2_direction；
- 启用 + 导演降级：directed_prompts 不下发（走既有 V1 编译路径），
  章节照常渲染成功，reason code 可审计；
- LLM 客户端缺失与导演意外异常：降级不中断章节生产。
"""

from __future__ import annotations

import asyncio
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
from app.services.audiobook.script_adapter_pkg._dataclasses import (  # noqa: E402
    ScriptSegment,
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


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, *, messages, task_type=None, model=None, **kwargs):
        self.calls.append({"messages": messages, "model": model})
        if not self.responses:
            raise AssertionError("unexpected extra director call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _director_json() -> str:
    return json.dumps(
        {
            "scenes": [
                {
                    "scene_key": "scene_0001",
                    "source_segment_indices": [0, 1],
                    "context": {"time": "深夜", "location": "废弃车站"},
                    "speech": [
                        {
                            "source_segment_index": 0,
                            "speaker": "林川",
                            "verification_policy": "hard",
                        },
                        {
                            "source_segment_index": 1,
                            "speaker": "苏眠",
                            "verification_policy": "hard",
                        },
                    ],
                    "vocalizations": [],
                    "sounds": [],
                    "timeline_mode": "natural",
                }
            ]
        },
        ensure_ascii=False,
    )


def _segments() -> list:
    return [
        ScriptSegment("dialogue", "这里有人吗？", "林川", "neutral"),
        ScriptSegment("dialogue", "别出声。", "苏眠", "sad"),
    ]


class FakePipeline:
    def __init__(self, result: ChapterScenePipelineResult) -> None:
        self.result = result
        self.calls = []
        self.checkpoint_persist_callback = None

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
                    text="这里有人吗？",
                    speaker="林川",
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


class DirectorHarness(SceneRenderMixin):
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


def _passed_pipeline_result() -> ChapterScenePipelineResult:
    plan = _plan("scene_0001", (0, 1))
    return ChapterScenePipelineResult(
        scenes=(
            ChapterSceneRender(
                plan=plan,
                result=SceneRenderResult(
                    scene_id=plan.scene_id,
                    status="passed",
                    action="assemble",
                    attempts=1,
                    audio_path=Path(__file__).resolve(),
                    subtitle_payload=[{"text": "这里有人吗？"}],
                    quality_report=None,
                ),
            ),
        )
    )


def _run(harness, tmp_path: Path, **kwargs):
    return asyncio.run(
        harness._try_generate_seed_scene_chapter(
            script_segments=_segments(),
            chapter_id=3,
            task_id="task-director",
            output_path=str(tmp_path / "chapter.wav"),
            output_format="wav",
            enable_quality_review=False,
            **kwargs,
        )
    )


@pytest.fixture(autouse=True)
def isolate_scene_artifact_root(tmp_path, monkeypatch):
    """任务层测试不得写入正式产物根 ``backend/data/scene_audio_artifacts/``。"""
    monkeypatch.setattr(
        scene_render_mixin_module,
        "SCENE_ARTIFACT_ROOT",
        tmp_path / "scene_artifacts",
    )


class TestDirectorFeatureGate:
    def test_disabled_by_default_no_director_call(self, tmp_path) -> None:
        pipeline = FakePipeline(_passed_pipeline_result())
        harness = DirectorHarness(pipeline=pipeline, assembler=FakeAssembler())
        harness.llm_client = FakeLLM([_director_json()])

        result = _run(harness, tmp_path)

        assert result["success"] is True
        assert harness.llm_client.calls == []
        assert pipeline.calls[0]["directed_prompts"] is None
        assert result["stats"]["director"] is None

    def test_enabled_but_missing_llm_client_degrades(self, tmp_path) -> None:
        pipeline = FakePipeline(_passed_pipeline_result())
        harness = DirectorHarness(pipeline=pipeline, assembler=FakeAssembler())
        harness._seed_scene_director_enabled = True

        result = _run(harness, tmp_path)

        assert result["success"] is True
        assert pipeline.calls[0]["directed_prompts"] is None
        assert result["stats"]["director"] == {
            "action": "degrade_v1",
            "reason_code": "director_llm_client_missing",
            "decision_hash": "",
        }


class TestDirectorWiring:
    def test_successful_director_feeds_directed_prompts(self, tmp_path) -> None:
        pipeline = FakePipeline(_passed_pipeline_result())
        harness = DirectorHarness(pipeline=pipeline, assembler=FakeAssembler())
        harness._seed_scene_director_enabled = True
        harness.llm_client = FakeLLM([_director_json()])

        result = _run(harness, tmp_path, chapter_summary="深夜的车站")

        assert result["success"] is True
        directed = pipeline.calls[0]["directed_prompts"]
        assert set(directed) == {"scene_0001"}
        assert "这里有人吗" in directed["scene_0001"].prompt
        director_stats = result["stats"]["director"]
        assert director_stats["action"] == "use_v2_direction"
        assert director_stats["decision_hash"]

    def test_invalid_director_output_degrades_and_chapter_succeeds(
        self, tmp_path
    ) -> None:
        pipeline = FakePipeline(_passed_pipeline_result())
        harness = DirectorHarness(pipeline=pipeline, assembler=FakeAssembler())
        harness._seed_scene_director_enabled = True
        harness.llm_client = FakeLLM(["not json", "still not json"])

        result = _run(harness, tmp_path)

        assert result["success"] is True
        assert pipeline.calls[0]["directed_prompts"] is None
        assert result["stats"]["director"]["action"] == "degrade_v1"

    def test_unexpected_director_error_degrades_without_breaking_chapter(
        self, tmp_path, monkeypatch
    ) -> None:
        pipeline = FakePipeline(_passed_pipeline_result())
        harness = DirectorHarness(pipeline=pipeline, assembler=FakeAssembler())
        harness._seed_scene_director_enabled = True
        harness.llm_client = FakeLLM([_director_json()])

        async def explode(*args, **kwargs):
            raise RuntimeError("director exploded")

        monkeypatch.setattr(
            scene_render_mixin_module, "run_chapter_direction", explode
        )

        result = _run(harness, tmp_path)

        assert result["success"] is True
        assert pipeline.calls[0]["directed_prompts"] is None
        assert result["stats"]["director"] == {
            "action": "degrade_v1",
            "reason_code": "director_unexpected_error",
            "decision_hash": "",
        }
