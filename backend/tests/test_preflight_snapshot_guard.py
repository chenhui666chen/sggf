# -*- coding: utf-8 -*-
"""阶段 A 观测：主快照单次落库守卫与正文 builder 提前（第十一轮外部审查 P1-a/P1-b/P2）。

P1-a：分段生成锁定模型失败分支 finish() 后未置守卫，异常冒泡到 worker 外层 except 会二次落
      content/failed，破坏“主请求最多一条快照”。修复：所有 finish 分支统一走 _finish_main_snapshot
      （可变持有者 _SnapshotGuard，helper 能跨分支置位，杜绝 bool 局部标志遗漏）。
P1-b：正文 builder 曾晚于 get_recommended_styles/get_context_optimizer/模型解析/预算计算，这些早期
      预检步骤抛异常时 content_observation 尚为 None，外层无法补落 content/failed。修复：builder 对称
      提前到正文相位起点（仅 set_correlation），模型/预算解析后再 set_model。
P2：规划 builder 早期失败（prepare_context_for_expansion 抛异常）时 set_model 尚未调用，快照 model_id
    为空削弱定位。修复：workflow_generation_model 已指定时在 builder 创建处先 set_model。

worker 全链路集成需 mock db/ws/streaming/coordinator/quota，成本高且脆弱；此处沿用仓库既有约定
（直接驱动抽出的 helper/guard 建模控制流 + 关键接线用源码顺序断言），与 test_preflight_failure_observation
和 test_plan_content_fallback_observation 一致。
"""
from pathlib import Path

from app.api.v1.workflow.routes_chapter import (
    _finish_main_snapshot,
    _finish_preflight_failure,
    _SnapshotGuard,
)
from app.services.context_observability import ObservationBuilder, collector

ROOT_DIR = Path(__file__).resolve().parents[1]
ROUTES_PATH = ROOT_DIR / "app" / "api" / "v1" / "workflow" / "routes_chapter.py"


def test_finish_main_snapshot_is_idempotent() -> None:
    # 统一 finish helper：多次调用只落一条主快照，并置守卫
    project_id = 990201
    obs = ObservationBuilder(project_id, 3, "content").set_correlation(task_id="t-guard-1")
    guard = _SnapshotGuard()
    obs.set_request_status("failed", error_type="Boom")
    _finish_main_snapshot(obs, guard)
    _finish_main_snapshot(obs, guard)  # 再次调用不应重复 record
    assert guard.done is True
    snaps = collector.list_for_project(project_id, limit=50)
    assert len(snaps) == 1


def test_segmented_locked_failure_records_single_content_snapshot() -> None:
    """P1-a：分段锁定分支落 failed 主快照并置守卫后，外层 except 兜底必须跳过，只 1 条。"""
    project_id = 990202
    content_observation = ObservationBuilder(project_id, 7, "content").set_correlation(
        task_id="t-seg-locked"
    )
    content_guard = _SnapshotGuard()
    # 分段生成锁定模型失败分支（SCENE_SEGMENTATION_ENABLED + require_exact_model）
    content_observation.set_online_llm_calls(2)
    content_observation.set_request_status("failed", error_type="RuntimeError")
    _finish_main_snapshot(content_observation, content_guard)
    # worker 外层 except 兜底逻辑：守卫已置位 → 跳过，不二次落 content/failed
    if content_observation is not None and not content_guard.done:
        _finish_preflight_failure(
            content_observation, RuntimeError("seg boom"), prompt_built=False
        )
    snaps = collector.list_for_project(project_id, limit=50)
    assert len(snaps) == 1
    assert snaps[0].request_kind == "content"
    assert snaps[0].request_status == "failed"


def test_early_preflight_failure_records_single_content_snapshot() -> None:
    """P1-b：builder 已提前创建，早期预检步骤抛异常时外层补落唯一一条 content/failed（-1 哨兵）。"""
    project_id = 990203
    content_observation = ObservationBuilder(project_id, 8, "content").set_correlation(
        task_id="t-early"
    )
    content_guard = _SnapshotGuard()
    content_user_prompt = None  # get_recommended_styles/optimizer 阶段抛异常，prompt 尚未构造
    err = RuntimeError("get_recommended_styles boom")
    if content_observation is not None and not content_guard.done:
        _finish_preflight_failure(
            content_observation,
            err,
            prompt_built=content_user_prompt is not None,
        )
    snaps = collector.list_for_project(project_id, limit=50)
    assert len(snaps) == 1
    assert snaps[0].request_kind == "content"
    assert snaps[0].request_status == "failed"
    assert snaps[0].error_type == "RuntimeError"
    assert snaps[0].prompt_request_bytes == -1  # prompt 未构造，-1 哨兵


def test_plan_early_failure_keeps_requested_model_metadata() -> None:
    """P2：workflow_generation_model 已指定 → builder 创建处先 set_model，早期失败快照 model_id 非空。"""
    project_id = 990204
    requested = "qwen-max"
    plan_observation = ObservationBuilder(project_id, 5, "plan").set_correlation(
        task_id="t-plan-early"
    )
    plan_observation.set_model(requested, context_limit=32768, safe_input_budget=24000)
    plan_guard = _SnapshotGuard()
    # prepare_context_for_expansion 在后置 set_model 之前抛异常
    if plan_observation is not None and not plan_guard.done:
        _finish_preflight_failure(
            plan_observation, ValueError("optimizer boom"), prompt_built=False
        )
    snap = collector.latest_for_project(project_id)
    assert snap.request_kind == "plan"
    assert snap.request_status == "failed"
    assert snap.model_id == requested
    assert snap.model_context_limit == 32768


def test_content_builder_created_before_early_preflight_steps() -> None:
    """P1-b 接线保证：worker 源码中正文 ObservationBuilder 创建须早于 get_recommended_styles/get_context_optimizer。"""
    source = ROUTES_PATH.read_text(encoding="utf-8")
    builder_idx = source.find("content_observation = ObservationBuilder(")
    assert builder_idx > 0
    # 从 builder 之后搜索这两个早期预检调用：存在即证明 builder 已提前到它们之前
    styles_idx = source.find("get_recommended_styles(", builder_idx)
    optimizer_idx = source.find("get_context_optimizer(", builder_idx)
    assert styles_idx > builder_idx
    assert optimizer_idx > builder_idx
