"""阶段 7 生产管线接入：章节任务编排导演前置步骤测试（指导文档 §4.2/§9）。

章节任务编排串接的第一段：真实 SeedSceneDirectorService（注入 fake
LLM 客户端）→ 集成决策 → 按场景编译 Prompt → 产出渲染入参
（ChapterDirectorRun）。degrade_v1/manual_review 场景不产出 Prompt
并携带 reason code 供编排层按 V1 路径或人工流程继续。

覆盖：

- 成功导演：按 scene_key 产出编译 Prompt，台词中文引号冻结、
  场景描述来自导演 context；
- 失败降级：degrade_v1/manual_review 无 Prompt、reason code 可审计；
- 任务预算耗尽：零 LLM 调用即降级；
- checkpoint 复用：第二次编排零调用且 Prompt 一致；
- 编排守卫：导演声明说话人与源片段不一致时拒绝编译。
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

from app.services.audiobook.scene_direction.chapter_director_run import (  # noqa: E402
    ChapterDirectorRun,
    run_chapter_direction,
)
from app.services.audiobook.scene_direction.director import (  # noqa: E402
    DirectorBudgetLedger,
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


def _director_json(*, speaker_override: str | None = None) -> str:
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
                            "speaker": speaker_override or "林川",
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


class TestSuccessfulRun:
    def test_run_produces_compiled_prompt_per_scene(self) -> None:
        run = _run(
            run_chapter_direction(_segments(), llm_client=FakeLLM([_director_json()]))
        )
        assert run.action == "use_v2_direction"
        assert set(run.prompts_by_scene) == {"scene_0001"}
        prompt = run.prompts_by_scene["scene_0001"].prompt
        assert "“这里有人吗？”" in prompt
        assert "“别出声。”" in prompt
        assert run.prompts_by_scene["scene_0001"].expected_texts == (
            "这里有人吗？",
            "别出声。",
        )
        assert "深夜" in prompt
        assert "废弃车站" in prompt

    def test_run_carries_decision_hash(self) -> None:
        run = _run(
            run_chapter_direction(_segments(), llm_client=FakeLLM([_director_json()]))
        )
        assert isinstance(run, ChapterDirectorRun)
        assert run.decision_hash


class TestFallbackRuns:
    def test_invalid_output_degrades_without_prompts(self) -> None:
        run = _run(
            run_chapter_direction(
                _segments(), llm_client=FakeLLM(["not json", "still not json"])
            )
        )
        assert run.action == "degrade_v1"
        assert run.reason_code == "director_degraded_to_v1"
        assert run.prompts_by_scene == {}

    def test_unfaithful_overlap_annotation_goes_manual_review(self) -> None:
        segment = SimpleNamespace(
            type="dialogue",
            text="我们一起说。",
            speaker="林川",
            performance_notes="两人同时说话，声音重叠",
            instruct_scene="",
        )
        run = _run(
            run_chapter_direction(
                [segment], llm_client=FakeLLM(["not json", "still not json"])
            )
        )
        assert run.action == "manual_review"
        assert run.reason_code == "director_terminal_policy"
        assert run.prompts_by_scene == {}

    def test_job_budget_exhausted_blocks_before_any_call(self) -> None:
        llm = FakeLLM([_director_json()])
        run = _run(
            run_chapter_direction(
                _segments(),
                llm_client=llm,
                job_consumed=DirectorBudgetLedger(cost=10**6),
            )
        )
        assert run.action == "degrade_v1"
        assert run.reason_code == "director_budget_exceeded"
        assert llm.calls == []


class TestReuseAndGuards:
    def test_second_run_reuses_checkpoint_with_zero_calls(self) -> None:
        checkpoints: list = []
        first = _run(
            run_chapter_direction(
                _segments(),
                llm_client=FakeLLM([_director_json()]),
                checkpoints=checkpoints,
            )
        )
        second_llm = FakeLLM([])
        second = _run(
            run_chapter_direction(
                _segments(), llm_client=second_llm, checkpoints=checkpoints
            )
        )
        assert second_llm.calls == []
        assert second.action == "use_v2_direction"
        assert (
            second.prompts_by_scene["scene_0001"].prompt
            == first.prompts_by_scene["scene_0001"].prompt
        )

    def test_misdeclared_speaker_degrades_via_validator(self) -> None:
        # 误声明的说话人被 validator 拦截，纠错后仍不一致，
        # 保真可承载 → 降级 V1（不产出 Prompt）；编排层守卫为
        # 旁路校验的第二道防线。
        run = _run(
            run_chapter_direction(
                _segments(),
                llm_client=FakeLLM([_director_json(speaker_override="苏眠")]),
            )
        )
        assert run.action == "degrade_v1"
        assert run.prompts_by_scene == {}
