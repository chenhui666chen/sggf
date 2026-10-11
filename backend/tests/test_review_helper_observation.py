# -*- coding: utf-8 -*-
"""阶段 A 观测：章节评审辅助函数 `_run_single_next_chapter_streaming_review` 真实调用埋点。

验证初评/静默复评/编辑复评共用的辅助函数在成功与失败路径均落一条独立
`review` 快照（真实调用次数、prompt 字节、request_status/error_type），
补齐第四轮覆盖后遗留的评审盲区。
"""
import asyncio

import pytest

from app.api.v1.workflow import routes_chapter
from app.api.v1.workflow.routes_chapter import (
    _run_single_next_chapter_streaming_review,
)
from app.services.context_observability import collector


async def _noop_chunk(chunk: str, idx: int) -> None:
    return


def _spy_context_payloads(monkeypatch):
    """捕获所有 set_context_payload 传入的 dict。

    ContextObservation 只保存 context_payload_bytes（序列化长度），不保留原始
    payload，故断言键集合须经此 spy 捕获传入值。
    """
    from app.services import context_observability as _co

    captured: list = []
    _orig = _co.ObservationBuilder.set_context_payload

    def _spy(self, payload):
        captured.append(payload)
        return _orig(self, payload)

    monkeypatch.setattr(_co.ObservationBuilder, "set_context_payload", _spy)
    return captured


class _FakeStreamingService:
    """模拟 generate_chapter_streaming：按 attempts 次触发 on_llm_attempt（含内部重试），
    再按 fail 决定返回报告或抛异常。辅助函数只调用它一次。"""

    def __init__(self, *, attempts: int = 1, fail: bool = False, report: str = "质量评审：无必改项。"):
        self.attempts = attempts
        self.fail = fail
        self.report = report
        self.calls = 0

    async def generate_chapter_streaming(self, **kwargs):
        self.calls += 1
        on_attempt = kwargs.get("on_llm_attempt")
        for _ in range(self.attempts):
            if on_attempt is not None:
                on_attempt()
        if self.fail:
            raise RuntimeError("review failed after retries")
        return self.report


class _FakeCoordinator:
    """模拟 real_coordinator.review_chapter 同步回退：可成功返回或抛异常。
    回退在协调器内部构造 prompt 并调用 LLM，本层拿不到真实调用数。"""

    def __init__(self, *, fail: bool = False, report: str = "同步回退评审：符合要求。"):
        self.fail = fail
        self.report = report
        self.calls = 0

    def review_chapter(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("sync fallback failed")
        return self.report


def _call_helper(service, *, project_id: int, require_exact_model: bool, real_coordinator=None):
    return asyncio.run(
        _run_single_next_chapter_streaming_review(
            chapter_draft="草稿正文",
            chapter_plan="本章计划",
            plot_outline="总体细纲",
            genre="",
            next_chapter_number=1,
            recent_chapter_assets_summary="",
            streaming_service=service,
            on_review_chunk=_noop_chunk,
            real_coordinator=real_coordinator,
            review_model="qwen-plus",
            max_llm_attempts=3,
            require_exact_model=require_exact_model,
            project_id=project_id,
            task_id="task-review-1",
        )
    )


def _review_snapshots(project_id: int):
    return collector.list_for_project(project_id, limit=50, request_kind="review")


def test_review_success_records_snapshot() -> None:
    project_id = 990010
    service = _FakeStreamingService(attempts=2, fail=False)
    _call_helper(service, project_id=project_id, require_exact_model=False)

    snaps = _review_snapshots(project_id)
    assert len(snaps) == 1
    obs = snaps[0]
    assert obs.request_kind == "review"
    assert obs.request_status == "ok"
    assert obs.error_type == ""
    # 真实调用次数反映内部重试（2 次），不冒充逻辑步骤
    assert obs.online_llm_calls == 2
    assert obs.prompt_request_bytes > 0
    assert obs.task_id == "task-review-1"


def test_review_locked_model_failure_records_failed_snapshot() -> None:
    project_id = 990011
    service = _FakeStreamingService(attempts=3, fail=True)
    # 锁定模型档位失败直接 raise，仍须先落 failed 快照
    with pytest.raises(RuntimeError):
        _call_helper(service, project_id=project_id, require_exact_model=True)

    snaps = _review_snapshots(project_id)
    assert len(snaps) == 1
    obs = snaps[0]
    assert obs.request_status == "failed"
    assert obs.error_type == "RuntimeError"
    assert obs.online_llm_calls == 3
    assert obs.prompt_request_bytes > 0


def test_review_fallback_path_still_records_failed_snapshot() -> None:
    # 非锁定模型：流式失败后回退（real_coordinator=None → 返回默认评审串），
    # 失败的真实流式调用仍应留痕为 failed 快照。
    project_id = 990012
    service = _FakeStreamingService(attempts=1, fail=True)
    result = _call_helper(service, project_id=project_id, require_exact_model=False)

    assert isinstance(result, str) and result
    snaps = _review_snapshots(project_id)
    assert len(snaps) == 1
    assert snaps[0].request_status == "failed"
    assert snaps[0].error_type == "RuntimeError"


def test_review_sync_fallback_success_records_fallback_snapshot() -> None:
    # 非锁定模型：流式失败 → real_coordinator.review_chapter 同步回退成功。
    # 除流式 failed 快照外，应补一条 fallback/ok，使 latest 反映“最终回退成功”，
    # 修正此前“仅失败快照导致健康面板误显示评审失败”的盲区。
    project_id = 990013
    service = _FakeStreamingService(attempts=2, fail=True)
    coord = _FakeCoordinator(fail=False)
    result = _call_helper(
        service, real_coordinator=coord, project_id=project_id, require_exact_model=False
    )

    assert isinstance(result, str) and result
    assert coord.calls == 1  # 确实走了同步回退
    review_snaps = _review_snapshots(project_id)
    assert len(review_snaps) == 1 and review_snaps[0].request_status == "failed"
    fb_snaps = collector.list_for_project(project_id, limit=50, request_kind="fallback")
    assert len(fb_snaps) == 1
    fb = fb_snaps[0]
    assert fb.request_status == "ok"
    assert fb.online_llm_calls == -1  # 同步回退真实调用数不可知，-1 哨兵
    assert fb.prompt_request_bytes == -1  # prompt 在协调器内部构造，-1 哨兵
    # latest 不再是失败态，而是回退成功
    latest = collector.latest_for_project(project_id)
    assert latest.request_kind == "fallback" and latest.request_status == "ok"


def test_review_sync_fallback_failure_records_fallback_failed_snapshot() -> None:
    # 非锁定模型：流式失败 → 同步回退也失败，应落 fallback/failed 快照并抛出。
    project_id = 990014
    service = _FakeStreamingService(attempts=1, fail=True)
    coord = _FakeCoordinator(fail=True)
    with pytest.raises(RuntimeError):
        _call_helper(
            service, real_coordinator=coord, project_id=project_id, require_exact_model=False
        )

    fb_snaps = collector.list_for_project(project_id, limit=50, request_kind="fallback")
    assert len(fb_snaps) == 1
    assert fb_snaps[0].request_status == "failed"
    assert fb_snaps[0].error_type == "RuntimeError"
    assert fb_snaps[0].online_llm_calls == -1


def test_multi_model_exception_records_failed_review_then_fallback_ok(monkeypatch) -> None:
    # 多模型服务抛异常 → 补一条 review/failed（多模型失败留痕），内部已发生的 reviewer
    # 调用数不可知用 -1 哨兵（避免 0 被误读为“未调用”），prompt 在服务内部构造 →
    # prompt_built=False 记 -1；随后单模型降级成功 → 独立记 fallback/ok（F.5：降级链路
    # 必须落 fallback 快照，不得混入 review）。
    project_id = 990020
    monkeypatch.setattr(
        routes_chapter,
        "_resolve_next_chapter_multi_model_review_preset",
        lambda *a, **k: "preset_x",
    )
    monkeypatch.setattr(
        routes_chapter.review_feature_gate,
        "get_multi_model_review_config",
        lambda *a, **k: {},
    )

    class _BoomService:
        def __init__(self, *a, **k):
            # 模拟服务已构造成功但 review() 抛错：实例持有评审团组成，
            # 供外层异常路径从 service 补齐 chief_model/reviewer_models/reviewer_profiles。
            self.chief_model = "chief-boom"
            self.reviewers = [
                {"model": "m1", "profile": "剧情"},
                {"model": "m2", "profile": "文笔"},
            ]

        async def review(self, *a, **k):
            raise RuntimeError("multi model boom")

    monkeypatch.setattr(routes_chapter, "MultiModelReviewService", _BoomService)
    captured = _spy_context_payloads(monkeypatch)

    service = _FakeStreamingService(attempts=1, fail=False, report="单模型评审：通过。")
    report, meta = asyncio.run(
        routes_chapter._run_next_chapter_quality_review(
            project_context={},
            chapter_draft="草稿",
            chapter_plan="计划",
            plot_outline="细纲",
            genre="",
            next_chapter_number=1,
            recent_chapter_assets_summary="",
            streaming_service=service,
            on_review_chunk=_noop_chunk,
            real_coordinator=None,
            project_id=project_id,
            task_id="task-mm-1",
        )
    )
    assert isinstance(report, str) and report
    assert meta.get("fallback_required") is True
    snaps = collector.list_for_project(project_id, limit=50, request_kind="review")
    failed = [s for s in snaps if s.request_status == "failed"]
    assert len(failed) == 1  # 多模型失败留痕
    assert failed[0].error_type == "RuntimeError"
    assert failed[0].online_llm_calls == -1  # 内部调用数不可知
    assert failed[0].prompt_request_bytes == -1  # 服务内部构造 prompt
    assert failed[0].context_payload_bytes > 0  # 记录 preset/失败原因/是否回退
    # 异常路径 review_model 应从 service 实例补齐（此前恒为 None → 面板显示模型未知）
    assert failed[0].model_id == "chief-boom"
    mm = [p for p in captured if isinstance(p, dict) and p.get("review_mode") == "multi_model"]
    assert len(mm) == 1
    payload = mm[0]
    assert set(payload) == {
        "review_mode", "preset", "chief_model", "reviewer_models",
        "reviewer_profiles", "fallback_required", "fallback_reason",
    }
    assert payload["chief_model"] == "chief-boom"
    assert payload["reviewer_models"] == ["m1", "m2"]
    assert payload["reviewer_profiles"] == ["剧情", "文笔"]
    # review 只剩多模型失败快照，降级成功不再混入 review
    ok = [s for s in snaps if s.request_status == "ok"]
    assert len(ok) == 0
    # 单模型降级成功 → 独立 fallback/ok 快照（F.5）
    fb_snaps = collector.list_for_project(project_id, limit=50, request_kind="fallback")
    assert len(fb_snaps) == 1
    assert fb_snaps[0].request_status == "ok"


def test_multi_model_insufficient_result_records_failed_review_then_fallback_ok(monkeypatch) -> None:
    # 多模型服务未抛异常但产出不足（multi_model=False）→ 补一条 review/failed，覆盖
    # “未产出足够结果”这条此前无快照的回退路径；随后单模型降级成功 → 独立记 fallback/ok（F.5）。
    project_id = 990021
    monkeypatch.setattr(
        routes_chapter,
        "_resolve_next_chapter_multi_model_review_preset",
        lambda *a, **k: "preset_x",
    )
    monkeypatch.setattr(
        routes_chapter.review_feature_gate,
        "get_multi_model_review_config",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        routes_chapter, "_build_next_chapter_review_meta", lambda *a, **k: {}
    )

    class _WeakService:
        def __init__(self, *a, **k):
            pass

        async def review(self, *a, **k):
            return {
                "multi_model": False,
                "review": "",
                "preset": "preset_x",
                "chief_model": "chief-weak",
                "reviewer_models": ["m1", "m2"],
                "reviewer_profiles": ["剧情", "文笔"],
            }

    monkeypatch.setattr(routes_chapter, "MultiModelReviewService", _WeakService)
    captured = _spy_context_payloads(monkeypatch)

    service = _FakeStreamingService(attempts=1, fail=False, report="单模型评审：通过。")
    report, meta = asyncio.run(
        routes_chapter._run_next_chapter_quality_review(
            project_context={},
            chapter_draft="草稿",
            chapter_plan="计划",
            plot_outline="细纲",
            genre="",
            next_chapter_number=1,
            recent_chapter_assets_summary="",
            streaming_service=service,
            on_review_chunk=_noop_chunk,
            real_coordinator=None,
            project_id=project_id,
            task_id="task-mm-2",
        )
    )
    assert isinstance(report, str) and report
    snaps = collector.list_for_project(project_id, limit=50, request_kind="review")
    failed = [s for s in snaps if s.request_status == "failed"]
    assert len(failed) == 1
    assert failed[0].online_llm_calls == -1
    assert failed[0].prompt_request_bytes == -1
    mm = [p for p in captured if isinstance(p, dict) and p.get("review_mode") == "multi_model"]
    assert len(mm) == 1
    payload = mm[0]
    assert set(payload) == {
        "review_mode", "preset", "chief_model", "reviewer_models",
        "reviewer_profiles", "fallback_required", "fallback_reason",
    }
    assert payload["reviewer_profiles"] == ["剧情", "文笔"]
    ok = [s for s in snaps if s.request_status == "ok"]
    assert len(ok) == 0  # 降级成功不再混入 review
    fb_snaps = collector.list_for_project(project_id, limit=50, request_kind="fallback")
    assert len(fb_snaps) == 1
    assert fb_snaps[0].request_status == "ok"


def test_multi_model_exception_single_model_failure_records_fallback_failed(monkeypatch) -> None:
    # 多模型服务异常 → review/failed；单模型降级也失败（非锁定、无协调器 → 返回默认模板）
    # → 独立记 fallback/failed（F.5：降级链路最终失败也须在 fallback 类型留痕，
    # 不得与多模型本身的 review/failed 混为同一类型）。
    project_id = 990023
    monkeypatch.setattr(
        routes_chapter,
        "_resolve_next_chapter_multi_model_review_preset",
        lambda *a, **k: "preset_x",
    )
    monkeypatch.setattr(
        routes_chapter.review_feature_gate,
        "get_multi_model_review_config",
        lambda *a, **k: {},
    )

    class _BoomService:
        def __init__(self, *a, **k):
            self.chief_model = "chief-boom"
            self.reviewers = []

        async def review(self, *a, **k):
            raise RuntimeError("multi model boom")

    monkeypatch.setattr(routes_chapter, "MultiModelReviewService", _BoomService)

    service = _FakeStreamingService(attempts=1, fail=True)
    report, meta = asyncio.run(
        routes_chapter._run_next_chapter_quality_review(
            project_context={},
            chapter_draft="草稿",
            chapter_plan="计划",
            plot_outline="细纲",
            genre="",
            next_chapter_number=1,
            recent_chapter_assets_summary="",
            streaming_service=service,
            on_review_chunk=_noop_chunk,
            real_coordinator=None,
            project_id=project_id,
            task_id="task-mm-3",
        )
    )
    assert isinstance(report, str) and report
    review_snaps = collector.list_for_project(project_id, limit=50, request_kind="review")
    assert len(review_snaps) == 1 and review_snaps[0].request_status == "failed"
    assert review_snaps[0].error_type == "RuntimeError"  # 多模型失败
    fb_snaps = collector.list_for_project(project_id, limit=50, request_kind="fallback")
    assert len(fb_snaps) == 1
    assert fb_snaps[0].request_status == "failed"  # 单模型降级也失败
    assert fb_snaps[0].error_type == "RuntimeError"


def test_multi_model_insufficient_single_model_failure_records_fallback_failed(monkeypatch) -> None:
    # 多模型产出不足 → review/failed（InsufficientMultiModelResult）；单模型降级也失败
    # → 独立记 fallback/failed（F.5）。
    project_id = 990024
    monkeypatch.setattr(
        routes_chapter,
        "_resolve_next_chapter_multi_model_review_preset",
        lambda *a, **k: "preset_x",
    )
    monkeypatch.setattr(
        routes_chapter.review_feature_gate,
        "get_multi_model_review_config",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        routes_chapter, "_build_next_chapter_review_meta", lambda *a, **k: {}
    )

    class _WeakService:
        def __init__(self, *a, **k):
            pass

        async def review(self, *a, **k):
            return {
                "multi_model": False,
                "review": "",
                "preset": "preset_x",
                "chief_model": "chief-weak",
                "reviewer_models": ["m1", "m2"],
                "reviewer_profiles": ["剧情", "文笔"],
            }

    monkeypatch.setattr(routes_chapter, "MultiModelReviewService", _WeakService)

    service = _FakeStreamingService(attempts=1, fail=True)
    report, meta = asyncio.run(
        routes_chapter._run_next_chapter_quality_review(
            project_context={},
            chapter_draft="草稿",
            chapter_plan="计划",
            plot_outline="细纲",
            genre="",
            next_chapter_number=1,
            recent_chapter_assets_summary="",
            streaming_service=service,
            on_review_chunk=_noop_chunk,
            real_coordinator=None,
            project_id=project_id,
            task_id="task-mm-4",
        )
    )
    assert isinstance(report, str) and report
    review_snaps = collector.list_for_project(project_id, limit=50, request_kind="review")
    assert len(review_snaps) == 1 and review_snaps[0].request_status == "failed"
    assert review_snaps[0].error_type == "InsufficientMultiModelResult"
    fb_snaps = collector.list_for_project(project_id, limit=50, request_kind="fallback")
    assert len(fb_snaps) == 1
    assert fb_snaps[0].request_status == "failed"


def test_multi_model_success_records_sentinel_calls_and_logical_step_count(monkeypatch) -> None:
    # 多模型评审成功路径：reviewer/chief 各自经 create_task_llm().ainvoke() → ModelHub.call
    # 的重试循环（max_retries 由模型配置决定），供应商真实请求数不可知 →
    # online_llm_calls 记 -1 哨兵；逻辑模型调用数（报告数 + 主导）写入 logical_step_count，
    # 不冒充真实调用数（对齐 F.5 与扩写 logical_step_count 先例）。
    project_id = 990022
    monkeypatch.setattr(
        routes_chapter,
        "_resolve_next_chapter_multi_model_review_preset",
        lambda *a, **k: "preset_x",
    )
    monkeypatch.setattr(
        routes_chapter.review_feature_gate,
        "get_multi_model_review_config",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        routes_chapter, "_build_next_chapter_review_meta", lambda *a, **k: {}
    )

    class _SuccessService:
        def __init__(self, *a, **k):
            pass

        async def review(self, *a, **k):
            return {
                "multi_model": True,
                "review": "多模型综合评审：通过。",
                "per_model_reports": [
                    {"status": "success", "model_id": "m1"},
                    {"status": "success", "model_id": "m2"},
                    {"status": "success", "model_id": "m3"},
                ],
                "chief_model": "chief-1",
                "preset": "preset_x",
                "reviewer_models": ["m1", "m2", "m3"],
                "reviewer_profiles": ["剧情", "文笔", "设定"],
            }

    monkeypatch.setattr(routes_chapter, "MultiModelReviewService", _SuccessService)
    captured = _spy_context_payloads(monkeypatch)

    service = _FakeStreamingService(attempts=1, fail=False, report="不应被调用的单模型评审。")
    report, meta = asyncio.run(
        routes_chapter._run_next_chapter_quality_review(
            project_context={},
            chapter_draft="草稿",
            chapter_plan="计划",
            plot_outline="细纲",
            genre="",
            next_chapter_number=1,
            recent_chapter_assets_summary="",
            streaming_service=service,
            on_review_chunk=_noop_chunk,
            real_coordinator=None,
            project_id=project_id,
            task_id="task-mm-ok",
        )
    )
    assert report == "多模型综合评审：通过。"
    assert service.calls == 0  # 多模型成功直接返回，不回退单模型
    snaps = collector.list_for_project(project_id, limit=50, request_kind="review")
    ok = [s for s in snaps if s.request_status == "ok"]
    assert len(ok) == 1
    obs = ok[0]
    assert obs.request_kind == "review"
    assert obs.prompt_request_bytes == -1  # 服务内部构造 prompt，本层未捕获
    assert obs.online_llm_calls == -1  # 真实供应商请求数（含重试/fallback）不可知
    assert obs.logical_step_count == 4  # 3 份报告 + 1 主导综合
    assert obs.context_payload_bytes > 0  # 记录 preset/chief/reviewer 组成
    mm = [p for p in captured if isinstance(p, dict) and p.get("review_mode") == "multi_model"]
    assert len(mm) == 1
    payload = mm[0]
    assert set(payload) == {
        "review_mode", "preset", "chief_model", "reviewer_models",
        "reviewer_profiles", "logical_model_calls",
    }
    assert payload["reviewer_profiles"] == ["剧情", "文笔", "设定"]
    assert payload["logical_model_calls"] == 4
