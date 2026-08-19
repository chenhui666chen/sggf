"""阶段 7 生产管线接入：渲染层按 scene_key 消费导演编排 Prompt（§9/§4.2）。

三层验收：

- apply_directed_prompt 桥接：V2 编译结果替换 SceneRenderPlan 的
  prompt/prompt_hash/expected_text/expected_vocalizations 并恢复
  seed_scene 渲染模式；requires_split 的编译结果拒绝注入；
- ChapterScenePipeline directed_prompts 参数：按 scene_id 命中注入，
  台词与源片段逐字不符时保留 V1 计划（末道保真防线），
  未命中/未注入时行为不变；
- 降级语义：directed_prompts 缺省即既有 V1 确定性编译路径。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.chapter_pipeline import (  # noqa: E402
    ChapterScenePipeline,
)
from app.services.audiobook.scene_engine.models import (  # noqa: E402
    ScenePromptCompileResult,
    SceneRenderPlan,
)
from app.services.audiobook.scene_engine.prompt_consume import (  # noqa: E402
    apply_directed_prompt,
)
from app.services.audiobook.scene_engine.scene_renderer import (  # noqa: E402
    SceneRenderResult,
)


def _v1_plan() -> SceneRenderPlan:
    return SceneRenderPlan(
        scene_id="scene_0001",
        source_segment_indices=(0, 1),
        expected_text="这里有人吗？\n别出声。",
        expected_duration_s=6.0,
        speaker_names=("林川", "苏眠"),
        references=(),
        prompt="V1_PROMPT",
        prompt_hash="v1-hash",
        reference_hashes=(),
        boundary_before="开始neutral情绪",
        boundary_after="结束neutral情绪",
        render_mode="seed_scene",
    )


def _compiled(
    *, requires_split: bool = False, vocalization: bool = False
) -> ScenePromptCompileResult:
    events = ()
    if vocalization:
        events = (
            SimpleNamespace(kind="vocalization", exact_text="吸气声", performance=""),
        )
    return ScenePromptCompileResult(
        prompt="V2_PROMPT",
        events=events,
        expected_texts=("这里有人吗？", "别出声。"),
        references=(),
        reference_speakers=(),
        requires_split=requires_split,
        split_reason="split_needed" if requires_split else None,
    )


class TestApplyDirectedPrompt:
    def test_replaces_prompt_fields_and_restores_seed_mode(self) -> None:
        plan = _v1_plan()
        plan = SceneRenderPlan(
            **{
                **plan.__dict__,
                "render_mode": "legacy_stems",
                "fallback_reason": "requires_split",
            }
        )
        resolved = apply_directed_prompt(plan, _compiled())
        assert resolved.prompt == "V2_PROMPT"
        assert resolved.prompt_hash == hashlib.sha256(
            b"V2_PROMPT"
        ).hexdigest()
        assert resolved.expected_text == "这里有人吗？\n别出声。"
        assert resolved.render_mode == "seed_scene"
        assert resolved.fallback_reason is None

    def test_vocalization_events_carry_into_quality_gate(self) -> None:
        resolved = apply_directed_prompt(_v1_plan(), _compiled(vocalization=True))
        assert resolved.expected_vocalizations == ("吸气声",)

    def test_requires_split_compilation_refused(self) -> None:
        with pytest.raises(ValueError):
            apply_directed_prompt(_v1_plan(), _compiled(requires_split=True))


class FakeRenderer:
    def __init__(self, statuses=("passed",)) -> None:
        self.statuses = list(statuses)
        self.calls = []

    def render(self, plan, *, model, audio_config=None, checkpoint=None):
        self.calls.append(plan)
        status = self.statuses.pop(0) if self.statuses else "passed"
        return SceneRenderResult(
            scene_id=plan.scene_id,
            status=status,
            action="assemble" if status == "passed" else "legacy_stems",
            attempts=1,
            audio_path=None,
            subtitle_payload=None,
            quality_report=None,
            fallback_reason=None if status == "passed" else "scene_failed",
        )


def _segments() -> list:
    return [
        SimpleNamespace(
            type="dialogue",
            text="这里有人吗？",
            speaker="林川",
            performance_notes="",
            instruct_scene="",
            pause_after=5.0,
        ),
        SimpleNamespace(
            type="dialogue",
            text="别出声。",
            speaker="苏眠",
            performance_notes="",
            instruct_scene="",
            pause_after=5.0,
        ),
    ]


def _pipeline(renderer) -> ChapterScenePipeline:
    return ChapterScenePipeline(
        reference_materializer=SimpleNamespace(),
        renderer=renderer,
    )


def _compiled_single(texts) -> ScenePromptCompileResult:
    return ScenePromptCompileResult(
        prompt="V2_PROMPT",
        events=(),
        expected_texts=tuple(texts),
        references=(),
        reference_speakers=(),
        requires_split=False,
        split_reason=None,
    )


class TestPipelineDirectedPromptWiring:
    def test_directed_prompt_consumed_by_matching_scene(self) -> None:
        renderer = FakeRenderer()
        pipeline = _pipeline(renderer)
        result = pipeline.render(
            _segments(),
            directed_prompts={
                "scene_0001": _compiled_single(("这里有人吗？", "别出声。"))
            },
        )
        # 两个短片段合为单场景，命中注入后渲染层消费 V2 Prompt。
        assert len(renderer.calls) == 1
        assert renderer.calls[0].prompt == "V2_PROMPT"
        assert renderer.calls[0].expected_text == "这里有人吗？\n别出声。"
        assert result.scenes[0].plan.prompt == "V2_PROMPT"

    def test_mismatched_expected_texts_keeps_v1_plan(self) -> None:
        renderer = FakeRenderer()
        pipeline = _pipeline(renderer)
        wrong = ScenePromptCompileResult(
            prompt="V2_PROMPT",
            events=(),
            expected_texts=("被篡改的台词",),
            references=(),
            reference_speakers=(),
            requires_split=False,
            split_reason=None,
        )
        pipeline.render(_segments(), directed_prompts={"scene_0001": wrong})
        assert renderer.calls[0].prompt != "V2_PROMPT"

    def test_absent_scene_key_keeps_v1_plan(self) -> None:
        renderer = FakeRenderer()
        pipeline = _pipeline(renderer)
        pipeline.render(
            _segments(),
            directed_prompts={
                "scene_9999": _compiled_single(("这里有人吗？", "别出声。"))
            },
        )
        assert all(call.prompt != "V2_PROMPT" for call in renderer.calls)

    def test_no_directed_prompts_keeps_legacy_behavior(self) -> None:
        renderer = FakeRenderer()
        pipeline = _pipeline(renderer)
        result = pipeline.render(_segments())
        assert result.scenes
        assert all(call.prompt != "V2_PROMPT" for call in renderer.calls)
