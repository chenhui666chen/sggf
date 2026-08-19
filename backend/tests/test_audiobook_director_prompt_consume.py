"""阶段 7 生产管线接入：导演事件进入 Prompt 编译消费测试（指导文档 §9/§4.2）。

DirectorIntegrationDecision（use_v2_direction）携带的事件序列与时长
估算进入 ScenePromptCompiler 消费：

- 场景描述从导演 context 确定性派生；
- 台词逐字事实守卫（expected_texts 必须与源片段逐字一致）；
- 时长预算核验（估算总时长不超过规划上限）；
- degrade_v1/manual_review 决策不携带可编译事件，由桥接层显式拒绝。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_direction.event_mapper import (  # noqa: E402
    estimate_scene_duration,
    map_direction_to_events,
)
from app.services.audiobook.scene_direction.models import (  # noqa: E402
    SeedSceneContext,
    SeedSceneDirection,
    SeedSoundDirection,
    SeedSpeechDirection,
    SeedVocalizationDirection,
    SegmentEvidenceRef,
)
from app.services.audiobook.scene_direction.pipeline_integration import (  # noqa: E402
    DirectorIntegrationDecision,
)
from app.services.audiobook.scene_engine.prompt_compiler import (  # noqa: E402
    ScenePromptCompiler,
)
from app.services.audiobook.scene_engine.prompt_consume import (  # noqa: E402
    DURATION_BUDGET_PLANNING_MAX_S,
    compile_decision_prompt,
    derive_scene_description,
    verify_director_dialogue_fidelity,
    verify_duration_budget,
)


def _segments() -> list:
    return [
        SimpleNamespace(
            type="dialogue",
            text=text,
            speaker=speaker,
            performance_notes="",
            instruct_scene="",
        )
        for speaker, text in [("林川", "这里有人吗？"), ("苏眠", "别出声。")]
    ]


def _direction(**extra) -> SeedSceneDirection:
    defaults = dict(
        scene_key="scene_0001",
        source_segment_indices=(0, 1),
        context=SeedSceneContext(
            time="深夜",
            location="废弃车站",
            acoustic_space="空旷回声明显",
            ambient_state="远处有风声",
        ),
        speech=(
            SeedSpeechDirection(source_segment_index=0, speaker="林川"),
            SeedSpeechDirection(source_segment_index=1, speaker="苏眠"),
        ),
        vocalizations=(),
        sounds=(),
    )
    defaults.update(extra)
    return SeedSceneDirection(**defaults)


def _completed_decision(direction: SeedSceneDirection) -> DirectorIntegrationDecision:
    segments = _segments()
    return DirectorIntegrationDecision(
        action="use_v2_direction",
        reason_code="director_completed",
        directions=(direction,),
        events_by_direction=(map_direction_to_events(direction, segments),),
        duration_estimates=(estimate_scene_duration(direction, segments),),
    )


class TestSceneDescription:
    def test_description_derived_from_director_context(self) -> None:
        description = derive_scene_description(_direction().context)
        assert "深夜" in description
        assert "废弃车站" in description
        assert "空旷回声明显" in description

    def test_empty_context_returns_empty_description(self) -> None:
        assert derive_scene_description(SeedSceneContext()) == ""

    def test_description_is_deterministic(self) -> None:
        context = _direction().context
        assert derive_scene_description(context) == derive_scene_description(context)


class TestDialogueFidelity:
    def test_expected_texts_match_segments_verbatim(self) -> None:
        decision = _completed_decision(_direction())
        compiler = ScenePromptCompiler()
        verify_director_dialogue_fidelity(decision, _segments(), compiler)

    def test_mismatched_speaker_rejected(self) -> None:
        bad = _direction(
            speech=(
                SeedSpeechDirection(source_segment_index=0, speaker="苏眠"),
                SeedSpeechDirection(source_segment_index=1, speaker="苏眠"),
            )
        )
        decision = _completed_decision(bad)
        with pytest.raises(ValueError):
            verify_director_dialogue_fidelity(
                decision, _segments(), ScenePromptCompiler()
            )

    def test_non_completed_decision_rejected(self) -> None:
        decision = DirectorIntegrationDecision(
            action="degrade_v1", reason_code="director_degraded_to_v1"
        )
        with pytest.raises(ValueError):
            verify_director_dialogue_fidelity(
                decision, _segments(), ScenePromptCompiler()
            )


class TestDurationBudget:
    def test_estimate_within_planning_max_passes(self) -> None:
        decision = _completed_decision(_direction())
        assert verify_duration_budget(decision) <= DURATION_BUDGET_PLANNING_MAX_S

    def test_long_scene_estimate_exceeding_budget_rejected(self) -> None:
        # 大量顺序台词叠加停顿，把估算总时长推过规划上限。
        long_segments = [
            SimpleNamespace(
                type="dialogue",
                text="这是一句足够长的台词，用于把场景的朗读时长不断向上推高。" * 4,
                speaker="林川",
                performance_notes="",
                instruct_scene="",
                pause_after=9.0,
            )
            for _ in range(12)
        ]
        direction = SeedSceneDirection(
            scene_key="scene_0001",
            source_segment_indices=tuple(range(12)),
            context=SeedSceneContext(),
            speech=tuple(
                SeedSpeechDirection(source_segment_index=i, speaker="林川")
                for i in range(12)
            ),
            vocalizations=(),
            sounds=(),
        )
        estimate = estimate_scene_duration(direction, long_segments)
        assert estimate.total_s > DURATION_BUDGET_PLANNING_MAX_S
        decision = DirectorIntegrationDecision(
            action="use_v2_direction",
            reason_code="director_completed",
            directions=(direction,),
            events_by_direction=(map_direction_to_events(direction, long_segments),),
            duration_estimates=(estimate,),
        )
        with pytest.raises(ValueError):
            verify_duration_budget(decision)

    def test_empty_decision_rejected(self) -> None:
        decision = DirectorIntegrationDecision(
            action="manual_review", reason_code="director_terminal_policy"
        )
        with pytest.raises(ValueError):
            verify_duration_budget(decision)


class TestPromptConsumption:
    def test_compile_decision_prompt_renders_events_verbatim(self) -> None:
        direction = _direction(
            sounds=(
                SeedSoundDirection(
                    kind="ambient",
                    description="远处风声",
                    anchor="throughout",
                ),
            ),
        )
        decision = _completed_decision(direction)
        result = compile_decision_prompt(decision, _segments())
        assert "“这里有人吗？”" in result.prompt
        assert "“别出声。”" in result.prompt
        assert result.expected_texts == ("这里有人吗？", "别出声。")
        assert "深夜" in result.prompt
        assert "废弃车站" in result.prompt
        assert result.requires_split is False

    def test_vocalization_directive_renders_as_non_language_sound(self) -> None:
        direction = _direction(
            vocalizations=(
                SeedVocalizationDirection(
                    speaker="林川",
                    description="倒吸冷气",
                    anchor="before",
                    relative_to_segment_index=0,
                    evidence=SegmentEvidenceRef(
                        segment_index=0, field="performance_notes", excerpt="她笑了一声"
                    ),
                ),
            ),
        )
        decision = _completed_decision(direction)
        result = compile_decision_prompt(decision, _segments())
        assert "倒吸冷气" in result.prompt
        assert "非语言" in result.prompt

    def test_compile_rejects_non_v2_decision(self) -> None:
        decision = DirectorIntegrationDecision(
            action="degrade_v1", reason_code="director_degraded_to_v1"
        )
        with pytest.raises(ValueError):
            compile_decision_prompt(decision, _segments())

    def test_compile_is_deterministic(self) -> None:
        decision = _completed_decision(_direction())
        first = compile_decision_prompt(decision, _segments())
        second = compile_decision_prompt(decision, _segments())
        assert first.prompt == second.prompt
