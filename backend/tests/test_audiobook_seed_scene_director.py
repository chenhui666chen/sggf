"""阶段 3 Seed 场景导演合同：SeedSceneDirector 与导演计划 checkpoint 测试。

覆盖指导文档 §4.3/§12.2 与阶段 3 验收：

- JSON/Schema/事实校验失败时每批次最多一次纠错重试；
- 超预算不继续调用；
- 可保真场景降级 V1 并记录 reason code（director_degraded_to_v1）；
- 不可保真场景进入 terminal policy（manual_review）；
- 恢复任务不会重新获得 Director 预算；
- 导演计划输入签名命中时不产生任何导演调用；
- attempt ledger 始终保留，不因输入变化而删除历史计费事实。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_direction.director import (  # noqa: E402
    DirectorBudgetLedger,
    SeedSceneDirector,
)
from app.services.audiobook.scene_direction.policy import (  # noqa: E402
    SeedSceneDirectorPolicy,
)


class FakeLLM:
    """可控导演 LLM：按序返回响应或抛出异常。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, *, messages, task_type=None, model=None, **kwargs):
        self.calls.append({"messages": messages, "model": model, "kwargs": kwargs})
        if not self.responses:
            raise AssertionError("unexpected extra director call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _segments(speaker_overrides=None) -> list:
    overrides = speaker_overrides or {}
    specs = [(0, "林川", "这里有人吗？"), (1, "苏眠", "别出声。")]
    return [
        SimpleNamespace(
            type="dialogue",
            text=text,
            speaker=overrides.get(index, speaker),
            performance_notes="",
            instruct_scene="",
        )
        for index, speaker, text in specs
    ]


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


def _director(responses, *, policy=None):
    return SeedSceneDirector(
        FakeLLM(responses),
        model="director-model-x",
        policy=policy or SeedSceneDirectorPolicy(),
    )


def _run(coro):
    return asyncio.run(coro)


class TestDirectorStateMachine:
    def test_valid_first_attempt_completes_and_records_checkpoint(self):
        director = _director([_valid_director_json()])
        checkpoints: list = []
        ledger = DirectorBudgetLedger()
        outcome = _run(
            director.direct(_segments(), checkpoints=checkpoints, chapter_consumed=ledger)
        )
        assert outcome.status == "completed"
        assert outcome.next_action == "reuse"
        assert outcome.directions[0].speech[1].speaker == "苏眠"
        assert len(director.llm.calls) == 1
        assert ledger.calls == 1
        assert checkpoints and checkpoints[-1]["status"] == "completed"
        assert checkpoints[-1]["validated_plan_hash"]

    def test_parse_failure_uses_exactly_one_corrective_retry(self):
        director = _director(["not json at all", _valid_director_json()])
        outcome = _run(director.direct(_segments(), checkpoints=[]))
        assert outcome.status == "completed"
        assert len(director.llm.calls) == 2
        # 纠错请求必须携带上一轮错误码。
        corrective_messages = director.llm.calls[1]["messages"]
        assert any("invalid_json" in message["content"] for message in corrective_messages)

    def test_exhausted_attempts_degrade_v1_for_faithful_content(self):
        director = _director(["broken {", "still broken"])
        checkpoints: list = []
        outcome = _run(director.direct(_segments(), checkpoints=checkpoints))
        assert outcome.status == "retryable_failed"
        assert outcome.next_action == "degrade_v1"
        assert outcome.reason_code == "director_degraded_to_v1"
        assert len(director.llm.calls) == 2  # 首次 + 纠错一次，绝不第三次
        assert checkpoints[-1]["next_action"] == "degrade_v1"

    def test_unfaithful_content_enters_terminal_policy(self):
        # 审定片段含 V1 无法承载的重叠插话标注 → manual_review 终态。
        segments = _segments()
        segments[1].performance_notes = "与前景台词同时说，抢话"
        director = _director(["bad", "worse"])
        checkpoints: list = []
        outcome = _run(director.direct(segments, checkpoints=checkpoints))
        assert outcome.status == "terminal_failed"
        assert outcome.next_action == "manual_review"
        assert checkpoints[-1]["status"] == "terminal_failed"

    def test_validation_failure_counts_as_failed_attempt(self):
        # speaker 与审定说话人不一致 → 事实校验失败。
        invalid = json.loads(_valid_director_json())
        invalid["scenes"][0]["speech"][1]["speaker"] = "旁白"
        director = _director([json.dumps(invalid, ensure_ascii=False), _valid_director_json()])
        outcome = _run(director.direct(_segments(), checkpoints=[]))
        assert outcome.status == "completed"
        assert len(director.llm.calls) == 2

    def test_timeout_is_retryable_once(self):
        director = _director([asyncio.TimeoutError(), _valid_director_json()])
        outcome = _run(director.direct(_segments(), checkpoints=[]))
        assert outcome.status == "completed"
        assert len(director.llm.calls) == 2


class TestBudgetEnforcement:
    def test_chapter_call_budget_blocks_corrective_retry(self):
        policy = SeedSceneDirectorPolicy(max_calls_per_chapter=1)
        director = _director(["broken"], policy=policy)
        ledger = DirectorBudgetLedger()
        outcome = _run(
            director.direct(_segments(), checkpoints=[], chapter_consumed=ledger)
        )
        # 首次失败后纠错调用被章节预算拦截，直接进入降级分流。
        assert len(director.llm.calls) == 1
        assert outcome.next_action == "degrade_v1"

    def test_pre_consumed_job_budget_blocks_all_calls(self):
        job = DirectorBudgetLedger(cost=999.0)
        director = _director([_valid_director_json()])
        outcome = _run(
            director.direct(_segments(), checkpoints=[], job_consumed=job)
        )
        assert len(director.llm.calls) == 0
        assert outcome.reason_code == "director_budget_exceeded"

    def test_attempt_ledger_records_provider_model_tokens_cost(self):
        director = _director([_valid_director_json()])
        checkpoints: list = []
        _run(director.direct(_segments(), checkpoints=checkpoints))
        attempt = checkpoints[-1]["attempts"][0]
        assert attempt["model"] == "director-model-x"
        assert attempt["tokens"] > 0
        assert attempt["cost_estimate"] > 0
        assert attempt["status"] == "success"


class TestCheckpointRecovery:
    def _completed_state(self):
        director = _director([_valid_director_json()])
        checkpoints: list = []
        ledger = DirectorBudgetLedger()
        _run(director.direct(_segments(), checkpoints=checkpoints, chapter_consumed=ledger))
        return checkpoints, ledger

    def test_signature_hit_reuses_plan_without_any_call(self):
        checkpoints, _ = self._completed_state()
        replay_llm = FakeLLM([])  # 任何调用都会失败 → 证明零调用
        director = SeedSceneDirector(replay_llm, model="director-model-x")
        outcome = _run(director.direct(_segments(), checkpoints=checkpoints))
        assert outcome.status == "completed"
        assert outcome.next_action == "reuse"
        assert outcome.directions[0].speech[1].speaker == "苏眠"
        assert replay_llm.calls == []

    def test_terminal_failed_decision_is_reused_without_retry_budget(self):
        segments = _segments()
        segments[1].performance_notes = "与前景台词同时说，抢话"
        first = _director(["bad", "worse"])
        checkpoints: list = []
        _run(first.direct(segments, checkpoints=checkpoints))
        replay_llm = FakeLLM([])
        director = SeedSceneDirector(replay_llm, model="director-model-x")
        outcome = _run(director.direct(segments, checkpoints=checkpoints))
        assert outcome.status == "terminal_failed"
        assert outcome.next_action == "manual_review"
        assert replay_llm.calls == []

    def test_degrade_decision_is_reused_without_calls(self):
        first = _director(["bad", "worse"])
        checkpoints: list = []
        _run(first.direct(_segments(), checkpoints=checkpoints))
        replay_llm = FakeLLM([])
        director = SeedSceneDirector(replay_llm, model="director-model-x")
        outcome = _run(director.direct(_segments(), checkpoints=checkpoints))
        assert outcome.next_action == "degrade_v1"
        assert replay_llm.calls == []

    def test_retryable_recovery_carries_consumed_budget(self):
        # 第一次运行消耗 2 次调用后仍 retryable_failed（预算宽松），
        # 恢复时沿用已消费预算：纠错机会已用完，不得重新获得重试次数。
        policy = SeedSceneDirectorPolicy(max_calls_per_chapter=8)
        first = SeedSceneDirector(
            FakeLLM(["bad", "worse"]), model="director-model-x", policy=policy
        )
        checkpoints: list = []
        ledger = DirectorBudgetLedger()
        first_outcome = _run(
            first.direct(_segments(), checkpoints=checkpoints, chapter_consumed=ledger)
        )
        assert first_outcome.status == "retryable_failed"
        assert ledger.calls == 2

        # 恢复：新 ledger 从 checkpoint 读取已消费量；纠错机会耗尽 → 直接降级分流。
        replay_llm = FakeLLM([])
        second = SeedSceneDirector(replay_llm, model="director-model-x", policy=policy)
        fresh_ledger = DirectorBudgetLedger()
        outcome = _run(
            second.direct(_segments(), checkpoints=checkpoints, chapter_consumed=fresh_ledger)
        )
        assert fresh_ledger.calls == 2  # 恢复不重置已消费预算
        assert replay_llm.calls == []  # 不重新获得重试次数
        assert outcome.next_action == "degrade_v1"

    def test_signature_change_keeps_history_ledger_and_accumulates_job_cost(self):
        checkpoints, _ = self._completed_state()
        job = DirectorBudgetLedger(cost=0.4)
        # 导演 Prompt 合同变化 → 签名失配，需重新导演；但历史账本保留、任务成本累计。
        second = SeedSceneDirector(
            FakeLLM([_valid_director_json()]), model="director-model-other"
        )
        outcome = _run(
            second.direct(_segments(), checkpoints=checkpoints, job_consumed=job)
        )
        assert outcome.status == "completed"
        assert len(checkpoints) == 2  # append-only：历史 checkpoint 与账本保留
        assert checkpoints[0]["attempts"], "历史 attempt ledger 不得删除"
        assert job.cost > 0.4  # 单任务预算跨章节累计，不重置
