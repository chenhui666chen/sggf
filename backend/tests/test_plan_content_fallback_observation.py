# -*- coding: utf-8 -*-
"""阶段 A 观测：规划/正文流式失败后的同步回退独立埋点（P1，依据第七轮外部审查）。

验证 _run_plan_sync_fallback / _run_content_sync_fallback 在“协调器成功、协调器失败、
无协调器降级默认模板”三种路径均落独立 fallback 快照：
- 回退在协调器内部构造 prompt 且不暴露重试回调 → online_llm_calls=-1、prompt_request_bytes=-1 哨兵；
- 规划回退失败落 fallback/failed 后 raise；
- 正文回退失败/降级返回默认模板但不 raise，且必须记 failed，绝不伪装 content/ok。

修正此前盲区：同步回退 `+=1` 冒充精确调用数、默认模板被记为 content/ok、
规划回退异常未落快照即抛出。
"""
import asyncio

import pytest

from app.api.v1.workflow.routes_chapter import (
    _run_content_sync_fallback,
    _run_plan_sync_fallback,
)
from app.services.context_observability import collector


class _FakePlanCoordinator:
    """模拟 real_coordinator.generate_chapter_plan 同步回退：可成功返回或抛异常。"""

    def __init__(self, *, fail: bool = False, plan: str = "同步回退规划：本章推进主线。"):
        self.fail = fail
        self.plan = plan
        self.calls = 0

    def generate_chapter_plan(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("plan sync fallback failed")
        return self.plan


# F.6：有效回退草稿须 >200 字且句末收尾，否则被 evaluate_chapter_output 判为过短/截断（rejected）
_VALID_FALLBACK_DRAFT = "同步回退正文：" + "他推开门，夜风灌进来，走廊尽头的灯忽明忽暗。" * 10 + "他终于停下脚步。"


class _FakeContentCoordinator:
    """模拟 real_coordinator.generate_chapter_content 同步回退：可成功返回或抛异常。"""

    def __init__(self, *, fail: bool = False, draft: str = _VALID_FALLBACK_DRAFT):
        self.fail = fail
        self.draft = draft
        self.calls = 0

    def generate_chapter_content(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("content sync fallback failed")
        return self.draft


def _fallback_snapshots(project_id: int):
    return collector.list_for_project(project_id, limit=50, request_kind="fallback")


def test_plan_sync_fallback_success_records_fallback_ok() -> None:
    project_id = 990030
    coord = _FakePlanCoordinator(fail=False)
    result = asyncio.run(
        _run_plan_sync_fallback(
            real_coordinator=coord,
            fallback_kwargs={"chapter_number": 1},
            default_template="默认规划模板",
            project_id=project_id,
            next_chapter_number=1,
            task_id="task-plan-fb-1",
            plan_model="qwen-plus",
        )
    )
    assert result == coord.plan
    assert coord.calls == 1
    snaps = _fallback_snapshots(project_id)
    assert len(snaps) == 1
    fb = snaps[0]
    assert fb.request_status == "ok"
    assert fb.online_llm_calls == -1  # 回退真实调用数不可知，-1 哨兵
    assert fb.prompt_request_bytes == -1  # prompt 在协调器内部构造，-1 哨兵
    latest = collector.latest_for_project(project_id)
    assert latest.request_kind == "fallback" and latest.request_status == "ok"


def test_plan_sync_fallback_failure_records_failed_and_raises() -> None:
    project_id = 990031
    coord = _FakePlanCoordinator(fail=True)
    with pytest.raises(RuntimeError):
        asyncio.run(
            _run_plan_sync_fallback(
                real_coordinator=coord,
                fallback_kwargs={"chapter_number": 1},
                default_template="默认规划模板",
                project_id=project_id,
                next_chapter_number=1,
                task_id="task-plan-fb-2",
                plan_model="qwen-plus",
            )
        )
    snaps = _fallback_snapshots(project_id)
    assert len(snaps) == 1
    assert snaps[0].request_status == "failed"
    assert snaps[0].error_type == "RuntimeError"
    assert snaps[0].online_llm_calls == -1


def test_plan_sync_fallback_no_coordinator_records_default_template_degraded() -> None:
    project_id = 990032
    result = asyncio.run(
        _run_plan_sync_fallback(
            real_coordinator=None,
            fallback_kwargs={"chapter_number": 1},
            default_template="默认规划模板",
            project_id=project_id,
            next_chapter_number=1,
            task_id="task-plan-fb-3",
            plan_model="qwen-plus",
        )
    )
    assert result == "默认规划模板"
    snaps = _fallback_snapshots(project_id)
    assert len(snaps) == 1
    assert snaps[0].request_status == "failed"  # 降级默认模板不是成功
    assert snaps[0].context_payload_bytes > 0  # payload 标明 fallback_mode=default_template


def test_content_sync_fallback_success_records_fallback_ok() -> None:
    project_id = 990033
    coord = _FakeContentCoordinator(fail=False)
    result = asyncio.run(
        _run_content_sync_fallback(
            real_coordinator=coord,
            fallback_kwargs={"chapter_number": 1},
            default_template="默认正文模板",
            project_id=project_id,
            next_chapter_number=1,
            task_id="task-content-fb-1",
            content_model="qwen-plus",
        )
    )
    assert result == coord.draft
    assert coord.calls == 1
    snaps = _fallback_snapshots(project_id)
    assert len(snaps) == 1
    assert snaps[0].request_status == "ok"
    assert snaps[0].online_llm_calls == -1
    assert snaps[0].prompt_request_bytes == -1
    # ②：协调器返回有效草稿 → 输出被采用
    assert snaps[0].output_status == "accepted"
    assert snaps[0].output_reject_reason == ""


def test_content_sync_fallback_invalid_draft_records_output_rejected() -> None:
    # ②：协调器调用成功但返回占位模板/空串 → request_status=ok（调用成功）
    # 但 output_status=rejected，避免 fallback/ok 掩盖后续有效性校验的最终失败。
    project_id = 990036
    coord = _FakeContentCoordinator(
        fail=False, draft="第1章内容\n\n（此处为生成的章节内容）"
    )
    result = asyncio.run(
        _run_content_sync_fallback(
            real_coordinator=coord,
            fallback_kwargs={"chapter_number": 1},
            default_template="默认正文模板",
            project_id=project_id,
            next_chapter_number=1,
            task_id="task-content-fb-invalid",
            content_model="qwen-plus",
            previous_full_text="",
        )
    )
    assert result == coord.draft
    snaps = _fallback_snapshots(project_id)
    assert len(snaps) == 1
    assert snaps[0].request_status == "ok"  # 调用成功
    assert snaps[0].output_status == "rejected"  # 但输出被拒
    assert snaps[0].output_reject_reason == "PlaceholderOutput"


def test_content_sync_fallback_failure_records_degraded_not_ok() -> None:
    # 正文回退失败不 raise（业务用默认模板继续），但必须记 failed 降级，绝不记 ok。
    project_id = 990034
    coord = _FakeContentCoordinator(fail=True)
    result = asyncio.run(
        _run_content_sync_fallback(
            real_coordinator=coord,
            fallback_kwargs={"chapter_number": 1},
            default_template="默认正文模板",
            project_id=project_id,
            next_chapter_number=1,
            task_id="task-content-fb-2",
            content_model="qwen-plus",
        )
    )
    assert result == "默认正文模板"
    snaps = _fallback_snapshots(project_id)
    assert len(snaps) == 1
    assert snaps[0].request_status == "failed"
    assert snaps[0].error_type == "RuntimeError"
    latest = collector.latest_for_project(project_id)
    assert latest.request_status == "failed"  # 不伪装成功


def test_content_sync_fallback_no_coordinator_records_default_template_degraded() -> None:
    project_id = 990035
    result = asyncio.run(
        _run_content_sync_fallback(
            real_coordinator=None,
            fallback_kwargs={"chapter_number": 1},
            default_template="默认正文模板",
            project_id=project_id,
            next_chapter_number=1,
            task_id="task-content-fb-3",
            content_model="qwen-plus",
        )
    )
    assert result == "默认正文模板"
    snaps = _fallback_snapshots(project_id)
    assert len(snaps) == 1
    assert snaps[0].request_status == "failed"
    assert snaps[0].context_payload_bytes > 0
