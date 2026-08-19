"""阶段 7 生产管线端到端收敛集成测试（指导文档阶段 7）。

真实 ChapterScenePipeline + fake renderer 产出真实 SceneRenderResult，
喂入 converge_chapter_production，验证渲染管线输出与 fallback_assets
合同之间的桥接端到端成立（§15 待接入清单第 1 项的回退收敛部分）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.fallback_assets import (  # noqa: E402
    DEFAULT_FALLBACK_ASSET_POLICY,
    FallbackAssetPolicy,
    converge_chapter_production,
)
from app.services.audiobook.scene_engine.chapter_pipeline import (  # noqa: E402
    ChapterScenePipeline,
)
from app.services.audiobook.scene_engine.planner import ScenePlanner  # noqa: E402
from app.services.audiobook.scene_engine.scene_renderer import (  # noqa: E402
    SceneRenderResult,
)
from app.services.audiobook.script_adapter_pkg._dataclasses import (  # noqa: E402
    ScriptSegment,
)


class FakeMaterializer:
    def materialize(self, config):
        raise AssertionError("本测试不应物化参考素材")


class FakeRenderer:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = list(statuses)

    def render(self, plan, **kwargs) -> SceneRenderResult:
        outcome = self.statuses.pop(0) if self.statuses else "passed"
        passed = outcome == "passed"
        return SceneRenderResult(
            scene_id=plan.scene_id,
            status="passed" if passed else "legacy_stems",
            action="assemble" if passed else "legacy_stems",
            attempts=1,
            audio_path=Path(f"{plan.scene_id}.mp3") if passed else None,
            subtitle_payload=None,
            quality_report=None,
            fallback_reason=None if passed else "transcript_fidelity_failed",
        )


def _segment(text: str, *, speaker: str, scene: str) -> ScriptSegment:
    return ScriptSegment(
        type="dialogue",
        text=text,
        speaker=speaker,
        emotion="tense",
        instruct_scene=scene,
        pause_after=5.0,
    )


def _pipeline(statuses: list[str]) -> ChapterScenePipeline:
    return ChapterScenePipeline(
        planner=ScenePlanner(
            target_min_duration_s=5,
            target_max_duration_s=100,
            soft_max_duration_s=110,
            hard_max_duration_s=120,
        ),
        reference_materializer=FakeMaterializer(),
        renderer=FakeRenderer(statuses),
    )


def _two_scene_segments() -> list[ScriptSegment]:
    return [
        _segment("她听着雨声，迟迟没有开口。", speaker="女主", scene="雨夜室内"),
        _segment("列车进站后，她终于说出了真相。", speaker="女主", scene="清晨站台"),
    ]


class TestPipelineWiring:
    def test_pipeline_with_policy_returns_convergence_matching_standalone(
        self,
    ) -> None:
        pipeline = ChapterScenePipeline(
            planner=ScenePlanner(
                target_min_duration_s=5,
                target_max_duration_s=100,
                soft_max_duration_s=110,
                hard_max_duration_s=120,
            ),
            reference_materializer=FakeMaterializer(),
            renderer=FakeRenderer(["passed", "quality_failure"]),
            fallback_asset_policy=DEFAULT_FALLBACK_ASSET_POLICY,
        )
        render = pipeline.render(_two_scene_segments())
        assert render.convergence is not None
        standalone = converge_chapter_production(
            render.results, DEFAULT_FALLBACK_ASSET_POLICY
        )
        assert render.convergence.convergence_hash == standalone.convergence_hash

    def test_pipeline_without_policy_keeps_backward_compatibility(self) -> None:
        render = _pipeline(["passed", "passed"]).render(_two_scene_segments())
        assert render.convergence is None
        assert len(render.results) == 2


class TestEndToEndConvergence:
    def test_all_passed_pipeline_yields_zero_fallback_cost(self) -> None:
        pipeline = _pipeline(["passed", "passed"])
        render = pipeline.render(_two_scene_segments())
        convergence = converge_chapter_production(
            render.results, DEFAULT_FALLBACK_ASSET_POLICY
        )
        assert convergence.summary["seed"] == 2
        assert convergence.fallback_plan.expected_asset_count == 0
        assert convergence.fallback_plan.has_fallback_cost is False

    def test_failed_scene_flows_to_fallback_with_scoped_plan(self) -> None:
        pipeline = _pipeline(["passed", "quality_failure"])
        render = pipeline.render(_two_scene_segments())
        convergence = converge_chapter_production(
            render.results, DEFAULT_FALLBACK_ASSET_POLICY
        )
        assert convergence.summary["seed"] == 1
        assert convergence.summary["legacy_fallback"] == 1
        plan = convergence.fallback_plan
        assert plan.expected_asset_count == 2
        requirement = plan.requirements[0]
        assert requirement.reason_code == "transcript_fidelity_failed"
        failed_scene = [
            scene.result.scene_id
            for scene in render.scenes
            if scene.result.status == "legacy_stems"
        ]
        assert requirement.scene_id in failed_scene

    def test_disabled_switch_routes_failure_to_manual_processing(self) -> None:
        pipeline = _pipeline(["passed", "quality_failure"])
        render = pipeline.render(_two_scene_segments())
        convergence = converge_chapter_production(
            render.results, FallbackAssetPolicy(enabled=False)
        )
        assert convergence.summary["manual_processing"] == 1
        assert convergence.summary["legacy_fallback"] == 0
        assert convergence.fallback_plan.disabled_reason == "fallback_disabled"
        assert convergence.fallback_plan.expected_asset_count == 0

    def test_convergence_hash_is_stable_for_same_pipeline_run(self) -> None:
        first = converge_chapter_production(
            _pipeline(["passed", "quality_failure"])
            .render(_two_scene_segments())
            .results,
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        second = converge_chapter_production(
            _pipeline(["passed", "quality_failure"])
            .render(_two_scene_segments())
            .results,
            DEFAULT_FALLBACK_ASSET_POLICY,
        )
        assert first.convergence_hash == second.convergence_hash
