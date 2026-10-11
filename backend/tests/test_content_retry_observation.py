# -*- coding: utf-8 -*-
"""阶段 A 观测：正文流式失败→同步 fallback 后截断重试的独立 content_retry 快照（第十一轮外部审查 P1）。

fail→fallback 路径下主 content 快照已在流式失败处 finish（守卫置位），3055 的守卫块被跳过；fallback
返回后触发的截断重试（真实 LLM 调用）及其 retry_*/最终 output_status/真实调用数无处落库，latest 会停
在 fallback/ok 掩盖重试结果（重试成功看不到、重试失败被 accepted 掩盖）。修复：补一条独立的
request_kind="content_retry" 快照（与 plan_retry 对称），仅在“主快照已提前 finish 且确曾重试”时落，
成功路径的重试仍折叠进 content 主快照、不重复记。

worker 全链路集成需 mock db/ws/streaming/coordinator/quota，成本高且脆弱；沿用仓库既有约定（直接驱动
抽出的模块级 helper 建模控制流 + 关键接线用源码顺序断言）。
"""
from pathlib import Path

from app.api.v1.workflow.routes_chapter import _record_content_retry_observation
from app.services.context_observability import ObservationBuilder, collector

ROOT_DIR = Path(__file__).resolve().parents[1]
ROUTES_PATH = ROOT_DIR / "app" / "api" / "v1" / "workflow" / "routes_chapter.py"


def test_content_retry_snapshot_records_retry_and_final_output() -> None:
    # 重试调用成功且产出被采用：request_status=ok、retry_status=succeeded、真实调用数
    project_id = 990211
    _record_content_retry_observation(
        project_id=project_id,
        next_chapter_number=6,
        task_id="t-retry-1",
        model="qwen-max",
        system_prompt="sys",
        user_prompt="usr",
        calls=2,
        retry_status="succeeded",
        fallback_to_previous_output=False,
        output_status="accepted",
        request_status="ok",
    )
    snap = collector.latest_for_project(project_id)
    assert snap.request_kind == "content_retry"
    assert snap.request_status == "ok"
    assert snap.retry_attempted is True
    assert snap.retry_status == "succeeded"
    assert snap.fallback_to_previous_output is False
    assert snap.online_llm_calls == 2
    assert snap.output_status == "accepted"
    assert snap.model_id == "qwen-max"
    assert snap.task_id == "t-retry-1"
    assert snap.prompt_request_bytes == len("sysusr".encode("utf-8"))


def test_content_retry_failed_call_records_failed_and_rejected() -> None:
    # 重试仍截断/抛异常：保留上一版、最终输出被拒，须如实记 failed/rejected 而非掩盖
    project_id = 990212
    _record_content_retry_observation(
        project_id=project_id,
        next_chapter_number=7,
        task_id="t-retry-2",
        model="qwen-max",
        system_prompt="s",
        user_prompt="u",
        calls=1,
        retry_status="failed",
        fallback_to_previous_output=True,
        output_status="rejected",
        output_reject_reason="TruncatedOutput",
        request_status="failed",
        error_type="RuntimeError",
    )
    snap = collector.latest_for_project(project_id)
    assert snap.request_kind == "content_retry"
    assert snap.request_status == "failed"
    assert snap.error_type == "RuntimeError"
    assert snap.retry_status == "failed"
    assert snap.fallback_to_previous_output is True
    assert snap.output_status == "rejected"
    assert snap.output_reject_reason == "TruncatedOutput"


def test_content_retry_not_masked_by_prior_fallback_ok() -> None:
    # 复现审查场景：content/failed → fallback/ok → 截断重试；latest 必须是 content_retry，不被 fallback/ok 掩盖
    project_id = 990213
    (
        ObservationBuilder(project_id, 8, "content")
        .set_correlation(task_id="t-retry-3")
        .set_request_status("failed", error_type="StreamError")
        .finish()
    )
    (
        ObservationBuilder(project_id, 8, "fallback")
        .set_correlation(task_id="t-retry-3")
        .set_request_status("ok")
        .set_output_status("accepted")
        .finish()
    )
    _record_content_retry_observation(
        project_id=project_id,
        next_chapter_number=8,
        task_id="t-retry-3",
        model="qwen-max",
        system_prompt="s",
        user_prompt="u",
        calls=1,
        retry_status="failed",
        fallback_to_previous_output=True,
        output_status="rejected",
        output_reject_reason="TruncatedOutput",
        request_status="ok",
    )
    latest = collector.latest_for_project(project_id)
    assert latest.request_kind == "content_retry"
    assert latest.output_status == "rejected"  # 最终失败不被 fallback/ok 掩盖
    kinds = [s.request_kind for s in collector.list_for_project(project_id, limit=50)]
    assert len(kinds) == 3
    assert set(kinds) == {"content", "fallback", "content_retry"}


def test_worker_wires_content_retry_after_guarded_content_snapshot() -> None:
    # 接线保证：守卫块之后，fail→fallback 孤立重试须落 content_retry；触发条件为主快照已提前 finish 且确曾重试
    source = ROUTES_PATH.read_text(encoding="utf-8")
    assert "_content_snapshot_prefinished and content_retry_attempted" in source
    guard_idx = source.find("if not content_guard.done:")
    assert guard_idx > 0
    call_idx = source.find("_record_content_retry_observation(", guard_idx)
    assert call_idx > guard_idx  # 调用点在守卫块之后（def 在守卫块之前，故此处定位到的是 call）
