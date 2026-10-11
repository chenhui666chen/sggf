# -*- coding: utf-8 -*-
"""阶段 A 观测：规划/正文预检阶段（builder 创建后、主快照 finish 前）失败的兜底埋点（①，依据第十轮外部审查）。

上下文装配/prompt 构造在进入 LLM 调用之前失败时，此前 builder 尚未创建、或已创建却从不 finish，
context-health 面板看起来像“没有请求”而非“请求构造失败”。`_finish_preflight_failure` 在异常逃逸到
worker 外层 except 时补落一条 `request_status=failed` 主快照：
- prompt 未构造 → `prompt_request_bytes=-1` 哨兵（区别于发送空 prompt 的 0 B）；
- 预检阶段尚未进入任何 LLM 调用 → `online_llm_calls=0`（真实零值，非 -1）；
- builder 上已写入的 db_read/rag/payload 等部分上下文自然保留；
- 只 finish 一次（“最多一条主快照”由调用方 `*_main_snapshot_done` 守卫保证）。
"""
from app.api.v1.workflow.routes_chapter import _finish_preflight_failure
from app.services.context_observability import ObservationBuilder, collector


def test_preflight_failure_unbuilt_prompt_records_sentinel() -> None:
    # prompt 尚未构造（优化器/装配阶段失败）：-1 哨兵 + failed + 真实零调用；已获 db_read 保留
    project_id = 990101
    obs = ObservationBuilder(project_id, 3, "plan").set_correlation(task_id="t-preflight-1")
    obs.set_db_read(rows=7, columns=4)
    _finish_preflight_failure(obs, ValueError("optimizer boom"), prompt_built=False)
    snap = collector.latest_for_project(project_id)
    assert snap.request_kind == "plan"
    assert snap.request_status == "failed"
    assert snap.error_type == "ValueError"
    assert snap.prompt_request_bytes == -1  # prompt 未构造，-1 哨兵
    assert snap.online_llm_calls == 0  # 预检阶段未进入任何 LLM 调用
    assert snap.db_rows_read == 7  # 已获部分上下文保留
    assert snap.task_id == "t-preflight-1"


def test_preflight_failure_built_prompt_records_real_bytes() -> None:
    # prompt 已构造但后续装配/发送前失败：记真实 system+user 字节，仍为 failed
    project_id = 990102
    obs = ObservationBuilder(project_id, 4, "content").set_correlation(task_id="t-preflight-2")
    _finish_preflight_failure(
        obs,
        RuntimeError("rag boom"),
        prompt_built=True,
        system_prompt="abc",
        user_prompt="defgh",
    )
    snap = collector.latest_for_project(project_id)
    assert snap.request_kind == "content"
    assert snap.request_status == "failed"
    assert snap.error_type == "RuntimeError"
    assert snap.prompt_request_bytes == len("abcdefgh".encode("utf-8"))
    assert snap.online_llm_calls == 0


def test_preflight_failure_records_exactly_one_snapshot() -> None:
    # 兜底埋点只落一条主快照（不重复 record）
    project_id = 990103
    obs = ObservationBuilder(project_id, 5, "plan").set_correlation(task_id="t-preflight-3")
    _finish_preflight_failure(obs, KeyError("k"), prompt_built=False)
    snaps = collector.list_for_project(project_id, limit=50)
    assert len(snaps) == 1
    assert snaps[0].request_status == "failed"
