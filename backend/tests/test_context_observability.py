# -*- coding: utf-8 -*-
"""上下文观测模块测试（阶段 A）。"""
from app.services.context_observability import (
    ObservationBuilder,
    ObservationCollector,
    collector,
)

# 使用高 project_id 避免与其他测试/真实数据冲突
PROJECT_ID = 990001


def _seed_observations(project_id: int, count: int) -> None:
    for idx in range(count):
        builder = ObservationBuilder(project_id, idx + 1, "content")
        builder.add_section("section_a", "甲" * 100, layer="L0")
        builder.finish()


def test_finish_sums_tokens_and_remaining() -> None:
    builder = ObservationBuilder(PROJECT_ID, 1, "content").set_model(
        "test-model", context_limit=32000, safe_input_budget=20000
    )
    builder.add_section("section_a", "甲" * 100, layer="L0")
    builder.add_section("section_b", "乙" * 200, layer="L1")
    obs = builder.finish()

    # 100+200 字符 × 1.3
    assert obs.total_input_tokens == 390
    assert obs.remaining_budget == 20000 - 390
    assert obs.model_context_limit == 32000
    # UTC 带时区
    assert obs.created_at.endswith("+00:00")


def test_remaining_zero_when_budget_missing() -> None:
    obs = (
        ObservationBuilder(PROJECT_ID, 2, "content")
        .add_section("section_a", "甲" * 10, layer="L0")
        .finish()
    )
    assert obs.safe_input_budget == 0
    assert obs.remaining_budget == 0


def test_list_limit_normalization() -> None:
    project_id = 990002
    _seed_observations(project_id, 5)

    assert len(collector.list_for_project(project_id, limit=3)) == 3
    # limit=0 不再返回全部
    assert len(collector.list_for_project(project_id, limit=0)) == 1
    # 负数归一为 1
    assert len(collector.list_for_project(project_id, limit=-5)) == 1
    # 超过每项目上限被截断
    assert len(collector.list_for_project(project_id, limit=99999)) == 5


def test_collector_accepts_kwargs() -> None:
    # 单例 __new__ 必须透传参数，不抛 TypeError
    instance = ObservationCollector(max_per_project=30)
    assert instance is collector


def test_payload_bytes_and_outline_health() -> None:
    builder = ObservationBuilder(PROJECT_ID, 3, "plan")
    builder.set_context_payload({"a": "x" * 1000})
    builder.set_outline_health(outline_status="available", volume_matched=True)
    builder.set_correlation(task_id="task-123", request_id="req-1")
    obs = builder.finish()

    assert obs.context_payload_bytes > 1000
    assert obs.outline_status == "available"
    assert obs.volume_matched is True
    assert obs.task_id == "task-123"
    assert obs.request_id == "req-1"


def test_cache_lookup_and_conflict_result() -> None:
    # 执行缓存查询：命中数与 lookup 标记
    builder = ObservationBuilder(PROJECT_ID, 4, "content")
    builder.set_rag(hits=2, summary_cache_hits=1)
    builder.set_conflict_result(status="warning", warning_count=3)
    obs = builder.finish()

    assert obs.cache_lookup_performed is True
    assert obs.rag_summary_cache_hits == 1
    assert obs.conflict_status == "warning"
    assert obs.warning_conflict_count == 3
    assert obs.blocking_conflict_count == 0

    # 未执行缓存查询（如扩写链路）
    builder2 = ObservationBuilder(PROJECT_ID, 5, "expansion")
    builder2.set_rag(hits=0, summary_cache_hits=0, cache_lookup_performed=False)
    obs2 = builder2.finish()
    assert obs2.cache_lookup_performed is False

    # blocking 冲突
    builder3 = ObservationBuilder(PROJECT_ID, 6, "plan")
    builder3.set_conflict_result(status="blocked", blocking_count=2)
    obs3 = builder3.finish()
    assert obs3.blocking_conflict_count == 2


def test_prompt_request_bytes_utf8() -> None:
    # 完整请求字节 = system+user 的 UTF-8 编码长度（中文 3 字节/字）
    builder = ObservationBuilder(PROJECT_ID, 7, "content")
    builder.set_prompt_request_bytes(system_prompt="sys", user_prompt="用" * 10)
    obs = builder.finish()
    assert obs.prompt_request_bytes == len(("sys" + "用" * 10).encode("utf-8"))
    # 未采集真实调用时 online_llm_calls 保持 0，不冒充
    assert obs.online_llm_calls == 0


def test_logical_step_count_for_expansion() -> None:
    # 扩写用 logical_step_count 记计划轮数，不写入 online_llm_calls
    builder = ObservationBuilder(PROJECT_ID, 8, "expansion")
    builder.set_logical_step_count(4)
    obs = builder.finish()
    assert obs.logical_step_count == 4
    assert obs.online_llm_calls == 0


def test_cache_lookup_status_tri_state() -> None:
    # queried：确实执行过缓存查询（即使命中 0）
    b1 = ObservationBuilder(PROJECT_ID, 9, "plan")
    b1.set_rag(hits=0, summary_cache_hits=0, cache_lookup_performed=True, cache_lookup_status="queried")
    assert b1.finish().cache_lookup_status == "queried"

    # unavailable：摘要器创建失败
    b2 = ObservationBuilder(PROJECT_ID, 10, "plan")
    b2.set_rag(cache_lookup_performed=False, cache_lookup_status="unavailable")
    o2 = b2.finish()
    assert o2.cache_lookup_status == "unavailable"
    assert o2.cache_lookup_performed is False

    # not_eligible：首章或无符合条件章节
    b3 = ObservationBuilder(PROJECT_ID, 11, "plan")
    b3.set_rag(cache_lookup_performed=False, cache_lookup_status="not_eligible")
    assert b3.finish().cache_lookup_status == "not_eligible"


def test_cache_lookup_status_fallback_derivation() -> None:
    # 未显式给三态时从 cache_lookup_performed 回退推导，保证旧调用方语义确定
    b4 = ObservationBuilder(PROJECT_ID, 12, "content")
    b4.set_rag(hits=1, summary_cache_hits=1)  # performed 默认 True
    assert b4.finish().cache_lookup_status == "queried"

    b5 = ObservationBuilder(PROJECT_ID, 13, "content")
    b5.set_rag(cache_lookup_performed=False)
    assert b5.finish().cache_lookup_status == "not_eligible"


def test_conflict_status_preserved_for_panel_coloring() -> None:
    # 面板按状态着色依赖这些状态值原样保存；not_checked/unknown/repaired 不得被当作 passed
    for status in ("passed", "warning", "blocked", "not_checked", "unknown", "repaired"):
        b = ObservationBuilder(PROJECT_ID, 14, "plan")
        b.set_conflict_result(status=status)
        obs = b.finish()
        assert obs.conflict_status == status
        assert obs.blocking_conflict_count == 0
        assert obs.warning_conflict_count == 0


def test_request_status_default_ok() -> None:
    # 默认 ok；旧调用方无需显式设置
    obs = ObservationBuilder(PROJECT_ID, 15, "content").finish()
    assert obs.request_status == "ok"
    assert obs.error_type == ""


def test_request_status_failed_serializes() -> None:
    # 失败兜底：写入 failed + 异常类型，并随 to_dict 序列化供 API/面板消费
    b = ObservationBuilder(PROJECT_ID, 16, "plan")
    b.set_online_llm_calls(2)
    b.set_request_status("failed", error_type="RuntimeError")
    obs = b.finish()
    assert obs.request_status == "failed"
    assert obs.error_type == "RuntimeError"
    assert obs.online_llm_calls == 2
    d = obs.to_dict()
    assert d["request_status"] == "failed"
    assert d["error_type"] == "RuntimeError"


def test_set_request_status_ok_clears_error_type() -> None:
    # 显式 ok 时 error_type 归空，避免残留误导
    b = ObservationBuilder(PROJECT_ID, 17, "revision")
    b.set_request_status("ok")
    obs = b.finish()
    assert obs.request_status == "ok"
    assert obs.error_type == ""


def test_output_status_separates_call_from_acceptance() -> None:
    # ②：output_status 与 request_status 解耦——调用成功(ok)但输出被拒(rejected)。
    # 默认 not_checked（未做输出校验），避免旧路径被误读为已采用。
    obs = (
        ObservationBuilder(PROJECT_ID, 20, "content")
        .set_request_status("ok")
        .set_output_status("rejected", reject_reason="PlaceholderOutput")
        .finish(record=False)
    )
    assert obs.request_status == "ok"
    assert obs.output_status == "rejected"
    assert obs.output_reject_reason == "PlaceholderOutput"
    default_obs = ObservationBuilder(PROJECT_ID, 20, "content").finish(record=False)
    assert default_obs.output_status == "not_checked"
    assert default_obs.output_reject_reason == ""


def test_set_retry_records_regeneration_revision_outcome() -> None:
    # ③：重生成/改稿的重试与回退语义写入顶层字段。
    obs = (
        ObservationBuilder(PROJECT_ID, 21, "regeneration")
        .set_output_status("rejected", reject_reason="EmptyOrShortOutput")
        .set_retry(attempted=True, status="failed", fallback_to_previous=True)
        .finish(record=False)
    )
    assert obs.output_status == "rejected"
    assert obs.retry_attempted is True
    assert obs.retry_status == "failed"
    assert obs.fallback_to_previous_output is True
    default_obs = ObservationBuilder(PROJECT_ID, 21, "revision").finish(record=False)
    assert default_obs.retry_attempted is False
    assert default_obs.retry_status == "not_needed"
    assert default_obs.fallback_to_previous_output is False


def test_output_and_retry_fields_serialize() -> None:
    # 新字段进入 to_dict(asdict)，供 API/结构化日志序列化
    d = (
        ObservationBuilder(PROJECT_ID, 22, "content")
        .set_output_status("accepted")
        .set_retry(attempted=False, status="not_needed")
        .finish(record=False)
        .to_dict()
    )
    assert d["output_status"] == "accepted"
    assert d["output_reject_reason"] == ""
    assert d["retry_attempted"] is False
    assert d["retry_status"] == "not_needed"
    assert d["fallback_to_previous_output"] is False


def test_downstream_request_kinds_accepted() -> None:
    # 拆分后的正文后续请求类型均可作为 request_kind 落库并按类型过滤
    project_id = 990003
    for kind in ("plan_retry", "regeneration", "iteration_plan", "revision", "review"):
        ObservationBuilder(project_id, 18, kind).set_online_llm_calls(1).finish()
    assert len(collector.list_for_project(project_id, limit=50, request_kind="revision")) == 1
    assert len(collector.list_for_project(project_id, limit=50, request_kind="review")) == 1


def test_list_filter_by_chapter_number() -> None:
    # context-health API 暴露 chapter_number 过滤，守卫 collector 按章节号筛选
    project_id = 990004
    _seed_observations(project_id, 5)  # 章节 1..5，均 content
    assert len(collector.list_for_project(project_id, limit=50, chapter_number=3)) == 1
    # 不存在的章节号返回空
    assert len(collector.list_for_project(project_id, limit=50, chapter_number=99)) == 0
    # 章节号 + request_kind 组合过滤
    assert (
        len(collector.list_for_project(project_id, limit=50, chapter_number=3, request_kind="content"))
        == 1
    )
    assert (
        len(collector.list_for_project(project_id, limit=50, chapter_number=3, request_kind="review"))
        == 0
    )
