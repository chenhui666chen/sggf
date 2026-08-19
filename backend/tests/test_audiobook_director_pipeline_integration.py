"""阶段 7 生产管线接入：V2 导演编排层测试（指导文档阶段 3/§4.3/阶段 7）。

把 SeedSceneDirector 的 DirectorOutcome 收敛为管线可消费的集成决策：
completed → 使用 V2 导演计划并映射为 SceneAudioEvent 序列与时常估算；
degrade_v1/manual_review → 空计划分流，reason code 全程可审计。
SeedSceneDirectorService 为 async 编排包装：导演调用 → 决策 → 事件。

覆盖：

- 三类结局到三类集成动作的确定性映射与非法组合拒绝；
- 决策哈希确定性（动作/原因码/计划内容入哈希，运行元数据不入）；
- 事件映射一致性（台词事件数与 speech 指令数一致）；
- 服务编排端到端（fake LLM 成功/失败降级/预算拦截/checkpoint 复用）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_direction.director import (  # noqa: E402
    ACTION_DEGRADE_V1,
    ACTION_MANUAL_REVIEW,
    ACTION_REUSE,
    DirectorBudgetLedger,
    DirectorOutcome,
    SeedSceneDirector,
    STATUS_COMPLETED,
    STATUS_RETRYABLE_FAILED,
    STATUS_TERMINAL_FAILED,
)
from app.services.audiobook.scene_direction.models import (  # noqa: E402
    SeedSceneContext,
    SeedSceneDirection,
    SeedSpeechDirection,
)
from app.services.audiobook.scene_direction.pipeline_integration import (  # noqa: E402
    SeedSceneDirectorService,
    resolve_director_integration,
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


def _directions() -> tuple:
    return (
        SeedSceneDirection(
            scene_key="scene_0001",
            source_segment_indices=(0, 1),
            context=SeedSceneContext(location="废弃车站"),
            speech=(
                SeedSpeechDirection(source_segment_index=0, speaker="林川"),
                SeedSpeechDirection(source_segment_index=1, speaker="苏眠"),
            ),
            vocalizations=(),
            sounds=(),
        ),
    )


def _valid_director_json() -> str:
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


def _run(coro):
    return asyncio.run(coro)


class TestDecisionMapping:
    def test_completed_outcome_maps_to_v2_direction_with_events(self) -> None:
        outcome = DirectorOutcome(
            status=STATUS_COMPLETED,
            next_action=ACTION_REUSE,
            directions=_directions(),
        )
        decision = resolve_director_integration(outcome, _segments())
        assert decision.action == "use_v2_direction"
        assert decision.reason_code == "director_completed"
        assert decision.directions == _directions()
        assert len(decision.events_by_direction) == 1
        events = decision.events_by_direction[0]
        speech_events = [e for e in events if e.kind == "speech"]
        assert len(speech_events) == 2
        assert speech_events[0].exact_text == "这里有人吗？"
        assert decision.duration_estimates[0].total_s > 0

    def test_completed_without_directions_rejected(self) -> None:
        outcome = DirectorOutcome(
            status=STATUS_COMPLETED, next_action=ACTION_REUSE, directions=()
        )
        with pytest.raises(ValueError):
            resolve_director_integration(outcome, _segments())

    def test_degrade_v1_maps_to_empty_direction_decision(self) -> None:
        outcome = DirectorOutcome(
            status=STATUS_RETRYABLE_FAILED,
            next_action=ACTION_DEGRADE_V1,
            reason_code="director_degraded_to_v1",
        )
        decision = resolve_director_integration(outcome, _segments())
        assert decision.action == "degrade_v1"
        assert decision.reason_code == "director_degraded_to_v1"
        assert decision.directions == ()
        assert decision.events_by_direction == ()

    def test_terminal_failure_maps_to_manual_review(self) -> None:
        outcome = DirectorOutcome(
            status=STATUS_TERMINAL_FAILED,
            next_action=ACTION_MANUAL_REVIEW,
            reason_code="director_terminal_policy",
        )
        decision = resolve_director_integration(outcome, _segments())
        assert decision.action == "manual_review"
        assert decision.reason_code == "director_terminal_policy"

    def test_unknown_status_rejected(self) -> None:
        outcome = DirectorOutcome(status="corrupted", next_action=ACTION_REUSE)
        with pytest.raises(ValueError):
            resolve_director_integration(outcome, _segments())

    def test_degrade_with_directions_rejected(self) -> None:
        outcome = DirectorOutcome(
            status=STATUS_RETRYABLE_FAILED,
            next_action=ACTION_DEGRADE_V1,
            directions=_directions(),
        )
        with pytest.raises(ValueError):
            resolve_director_integration(outcome, _segments())


class TestDecisionHash:
    def test_hash_is_deterministic(self) -> None:
        outcome = DirectorOutcome(
            status=STATUS_COMPLETED,
            next_action=ACTION_REUSE,
            directions=_directions(),
        )
        first = resolve_director_integration(outcome, _segments())
        second = resolve_director_integration(outcome, _segments())
        assert first.decision_hash == second.decision_hash

    def test_hash_differs_across_actions(self) -> None:
        completed = DirectorOutcome(
            status=STATUS_COMPLETED,
            next_action=ACTION_REUSE,
            directions=_directions(),
        )
        degraded = DirectorOutcome(
            status=STATUS_RETRYABLE_FAILED,
            next_action=ACTION_DEGRADE_V1,
            reason_code="director_degraded_to_v1",
        )
        a = resolve_director_integration(completed, _segments())
        b = resolve_director_integration(degraded, _segments())
        assert a.decision_hash != b.decision_hash


class TestServiceOrchestration:
    def _service(self, responses, *, checkpoints=None):
        llm = FakeLLM(responses)
        director = SeedSceneDirector(llm, model="director-model-x")
        service = SeedSceneDirectorService(
            director, checkpoints=checkpoints if checkpoints is not None else []
        )
        return service, llm

    def test_successful_director_yields_v2_decision(self) -> None:
        service, llm = self._service([_valid_director_json()])
        decision = _run(service.direct_chapter(_segments()))
        assert decision.action == "use_v2_direction"
        assert len(llm.calls) == 1
        assert decision.duration_estimates[0].total_s > 0

    def test_invalid_output_degrades_to_v1(self) -> None:
        service, llm = self._service(["not json", "still not json"])
        decision = _run(service.direct_chapter(_segments()))
        assert decision.action == "degrade_v1"
        assert decision.reason_code == "director_degraded_to_v1"
        assert decision.directions == ()

    def test_budget_exceeded_blocks_before_any_call(self) -> None:
        service, llm = self._service([_valid_director_json()])
        job_consumed = DirectorBudgetLedger(cost=10**6)
        decision = _run(
            service.direct_chapter(_segments(), job_consumed=job_consumed)
        )
        assert decision.action == "degrade_v1"
        assert decision.reason_code == "director_budget_exceeded"
        assert llm.calls == []

    def test_checkpoint_reuse_produces_zero_calls_and_same_decision(self) -> None:
        checkpoints: list = []
        first_service, first_llm = self._service(
            [_valid_director_json()], checkpoints=checkpoints
        )
        first = _run(first_service.direct_chapter(_segments()))
        second_service, second_llm = self._service([], checkpoints=checkpoints)
        second = _run(second_service.direct_chapter(_segments()))
        assert len(first_llm.calls) == 1
        assert second_llm.calls == []
        assert second.action == "use_v2_direction"
        assert second.decision_hash == first.decision_hash

    def test_chapter_budget_ledger_accumulates(self) -> None:
        service, _ = self._service([_valid_director_json()])
        ledger = DirectorBudgetLedger()
        _run(service.direct_chapter(_segments(), chapter_consumed=ledger))
        assert ledger.calls == 1
        assert ledger.tokens > 0
        assert ledger.cost > 0
