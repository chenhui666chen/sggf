from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def test_removed_long_context_qwen_is_not_registered_or_normalized() -> None:
    from core.model_hub import model_hub
    from core.model_resolution import normalize_model_id
    from core.model_runtime import ensure_model_hub_initialized, resolve_model_for_task

    ensure_model_hub_initialized()

    legacy_alias = "qwen-" + "plus"
    removed_model_id = "qwen-" + "long"

    assert normalize_model_id(legacy_alias) == legacy_alias
    assert model_hub.registry.get_spec(removed_model_id) is None
    assert resolve_model_for_task("book_synthesis", None) is None


def test_context_optimizer_uses_requested_workflow_model_without_removed_long_context_qwen() -> None:
    from app.services.agents.context_optimizer import ContextOptimizer, get_context_optimizer

    late_chapter_optimizer = ContextOptimizer(
        current_chapter=120,
        stage="content_creation",
        model_name="deepseek-flash",
    )

    assert late_chapter_optimizer.selected_model == "deepseek-flash"
    assert "qwen-" + "long" not in late_chapter_optimizer.MODEL_LIMITS

    default_optimizer = get_context_optimizer(current_chapter=120, stage="content_creation")
    assert default_optimizer.selected_model == "qwen-plus"


def test_workflow_generation_model_validation_lists_llm_models_without_removed_long_context_qwen() -> None:
    from app.api.v1.workflow.model_selection import (
        DEFAULT_WORKFLOW_GENERATION_MODEL,
        list_workflow_generation_models,
        resolve_workflow_generation_model,
    )

    models = list_workflow_generation_models()
    model_ids = {item["id"] for item in models}
    removed_model_id = "qwen-" + "long"

    assert DEFAULT_WORKFLOW_GENERATION_MODEL == "qwen-plus"
    assert "qwen-plus" in model_ids
    assert "deepseek-pro" in model_ids
    assert "minimax-m" in model_ids
    assert removed_model_id not in model_ids

    # 成本倍率以目录中最便宜模型为基准动态计算，不硬编码具体价格；
    # 只验证计算逻辑与稳定的相对价位关系，避免目录调价时测试失效。
    priced_models = [item for item in models if item["cost_multiplier"] is not None]
    assert priced_models, "目录中应至少有一个可估价模型"
    baseline_ids = {item["relative_cost_basis"] for item in priced_models}
    assert len(baseline_ids) == 1
    baseline_id = baseline_ids.pop()
    baseline_model = next(item for item in models if item["id"] == baseline_id)
    assert baseline_model["cost_multiplier"] == 1
    assert baseline_model["cost_label"] == "1×"

    by_id = {item["id"]: item for item in priced_models}
    for item in priced_models:
        assert item["cost_multiplier"] >= 1
        assert item["relative_cost_basis"] == baseline_id
        assert item["relative_cost_basis_label"] == "按 7:1 输入/输出比估算"
        assert item["cost_label"].endswith("×")

    # 稳定的相对价位关系：pro 贵于同名 flash/轻量档，默认创作模型贵于基准
    assert by_id["deepseek-pro"]["cost_multiplier"] > by_id["deepseek-flash"]["cost_multiplier"]
    assert by_id["mimo-pro"]["cost_multiplier"] > by_id["mimo-flash"]["cost_multiplier"]
    assert by_id["qwen-plus"]["cost_multiplier"] > by_id[baseline_id]["cost_multiplier"]
    assert by_id["minimax-m"]["cost_multiplier"] > 1
    assert by_id["kimi-preview"]["cost_multiplier"] > 1
    assert by_id["glm"]["cost_multiplier"] > 1

    assert resolve_workflow_generation_model("deepseek-pro") == "deepseek-pro"
    assert resolve_workflow_generation_model("minimax-m") == "minimax-m"

    with pytest.raises(ValueError):
        resolve_workflow_generation_model(removed_model_id)


def test_workflow_request_schemas_accept_generation_model_but_story_expansion_rejects_it() -> None:
    from pydantic import ValidationError

    from app.api.v1.workflow.schemas import ExecuteStageRequest, ExpandStoryRequest, StartWorkflowRequest

    start = StartWorkflowRequest(
        project_id=1,
        requirement="write",
        workflow_generation_model="deepseek-pro",
    )
    execute = ExecuteStageRequest(
        project_id=1,
        stage="content",
        workflow_generation_model="deepseek-flash",
    )

    assert start.workflow_generation_model == "deepseek-pro"
    assert execute.workflow_generation_model == "deepseek-flash"

    with pytest.raises(ValidationError):
        ExpandStoryRequest(
            project_id=1,
            current_outline="outline",
            world_setting="world",
            characters="characters",
            workflow_generation_model="deepseek-pro",
        )


def test_generate_next_chapter_route_imports_real_coordinator_context_sync_helper() -> None:
    import app.api.v1.workflow.routes_chapter as routes_chapter

    assert callable(routes_chapter._sync_real_coordinator_project_context)
    assert callable(routes_chapter._build_recent_full_chapter_excerpt)
    assert callable(routes_chapter._build_recent_chapter_assets_summary)
    assert callable(routes_chapter._estimate_tokens_by_chars)
    assert callable(routes_chapter._get_safe_input_token_budget)
    assert callable(routes_chapter._select_text_model_by_input_tokens)
    assert callable(routes_chapter._select_previous_chapter_context_strategy)
    assert callable(routes_chapter._build_iteration_revision_prompt)
    assert callable(routes_chapter._build_iteration_review_prompt)
    assert callable(routes_chapter._extract_iteration_review_score)
    assert callable(routes_chapter._create_generated_chapter)


def test_iteration_fallback_keeps_best_version_when_revisions_do_not_improve() -> None:
    import app.api.v1.workflow.routes_chapter as routes_chapter

    assert routes_chapter._select_iteration_fallback_version(
        initial_version="初稿",
        latest_revised_version="第一轮改稿",
        best_version="初稿",
    ) == "初稿"
    assert routes_chapter._select_iteration_fallback_version(
        initial_version="初稿",
        latest_revised_version="第二轮改稿",
        best_version="第一轮高分改稿",
    ) == "第一轮高分改稿"
    assert routes_chapter._select_iteration_fallback_version(
        initial_version="初稿",
        latest_revised_version="",
        best_version="初稿",
    ) == "初稿"


def test_iteration_review_detects_unresolved_required_items() -> None:
    import app.api.v1.workflow.routes_chapter as routes_chapter

    unresolved_review = """
综合评分：8.8/10分

## 评审要求执行核验表
| 要求ID/来源 | 状态（已执行/部分执行/未执行） | 修改后证据 | 未完成原因 |
|---|---|---|---|
| R0-MUST-1 | 未执行 | 无 | 仍未把冲突提前 |
| R0-SUGGEST-1 | 已执行 | 第三段补足环境 |  |
"""
    partially_resolved_review = """
综合评分：8.8/10分

## 评审要求执行核验表
| 要求ID/来源 | 状态（已执行/部分执行/未执行） | 修改后证据 | 未完成原因 |
|---|---|---|---|
| R0-MUST-1 | 已执行 | 开场第二段已经提前冲突 |  |
| R1-MUST-2 | 部分执行 | 已补足动机，但冲突还可更强 |  |
"""
    fully_resolved_review = """
综合评分：9.2/10分

## 评审要求执行核验表
| 要求ID/来源 | 状态（已执行/部分执行/未执行） | 修改后证据 | 未完成原因 |
|---|---|---|---|
| R0-MUST-1 | 已执行 | 开场第二段已经提前冲突 |  |
| R1-MUST-2 | 已执行 | 已补足动机并强化冲突 |  |
"""

    assert routes_chapter._iteration_review_has_unresolved_required_items(unresolved_review) is True
    # 与首章验收原则对齐：必改项部分执行同样阻断通过
    assert routes_chapter._iteration_review_has_unresolved_required_items(partially_resolved_review) is True
    # 核验表全部已执行时，表格行不得被 fallback 扫描误判为残留必改
    assert routes_chapter._iteration_review_has_unresolved_required_items(fully_resolved_review) is False


def test_split_stream_text_preserves_final_iteration_content_order() -> None:
    import app.api.v1.workflow.routes_chapter as routes_chapter

    assert routes_chapter._split_stream_text("一二三四五", chunk_size=2) == ["一二", "三四", "五"]
    assert routes_chapter._split_stream_text("", chunk_size=2) == []


def test_chapter_plan_prompt_budget_guard_preserves_labels_and_shrinks_payload() -> None:
    import app.api.v1.workflow.routes_chapter as routes_chapter

    prompt = routes_chapter._build_chapter_plan_user_prompt(
        next_chapter_number=3,
        concept="测试故事",
        current_chapter_outline="第3章：黑市试探\n" + ("- 场景目标：确认卷宗下落。\n" * 300),
        current_volume_context="第一卷目标：旧案重启。\n" * 180,
        core_character_anchor_context="林舟：追查师父失踪真相。\n" * 180,
        focus_character_relationship_context="林舟与顾晚：互相试探转向有限合作。\n" * 180,
        planning_character_context="人物候选：林舟、顾晚、黑市线人。\n" * 500,
        epic_framework_context="长篇约束：旧案线不能提前揭底。\n" * 180,
        optimized_context_text="第1章到第8章核心上下文。\n" * 700,
        structured_memory_text="【结构化记忆】卷宗最后一页失踪。\n" * 180,
        previous_chapters_summary="前文摘要：林舟已入城。\n" * 220,
        recent_chapter_assets_summary="连续性资产：城门暗号异常。\n" * 220,
        previous_ending="前一章结尾：顾晚递出半枚铜钱。\n" * 160,
        climax_instruction="",
        chapter_plan_guide="题材指导：线索递进。\n" * 160,
        model_name="doubao-seed-character",
        max_prompt_tokens=2400,
    )

    assert routes_chapter._estimate_tokens_by_chars(prompt) <= 2400
    assert "【人物规划候选摘要】" in prompt
    assert "【优化后的核心上下文】" in prompt
    assert "【输出要求】" in prompt
    assert "请为第3章制定创作计划" in prompt
    assert len(prompt) < 6000


def test_doubao_chapter_plan_prompt_budget_uses_balanced_input_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.workflow.routes_chapter as routes_chapter

    monkeypatch.delenv("DOUBAO_CHAPTER_PLAN_PROMPT_BUDGET", raising=False)

    assert routes_chapter._get_chapter_plan_prompt_token_budget("doubao-seed-character") == 80000


def test_doubao_seed_character_declares_32k_output_capacity() -> None:
    from core.model_hub import model_hub
    from core.model_runtime import ensure_model_hub_initialized

    ensure_model_hub_initialized()
    spec = model_hub.registry.get_spec("doubao-seed-character")

    assert spec is not None
    assert spec.constraints.max_context_tokens == 131072
    assert spec.constraints.max_output_tokens == 32768


@pytest.mark.asyncio
async def test_generate_next_chapter_failure_updates_generation_history_error_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.db.base as db_base
    import app.api.v1.workflow.routes_chapter as routes_chapter

    class FakeDBSession:
        def __init__(self) -> None:
            self.execute_calls: list[tuple[Any, Any]] = []
            self.committed = False
            self.closed = False

        def execute(self, query: Any, params: Any = None) -> SimpleNamespace:
            self.execute_calls.append((query, params))
            return SimpleNamespace(fetchone=lambda: None)

        def commit(self) -> None:
            self.committed = True

        def close(self) -> None:
            self.closed = True

    class RaisingWorkflowContextBuilder:
        def __init__(self, db: Any) -> None:
            self.db = db

        def get_project_profile(self, project_id: int) -> Any:
            raise RuntimeError("profile exploded")

    fake_db = FakeDBSession()
    error_events: list[dict[str, Any]] = []

    async def fake_send_task_error(**kwargs: Any) -> None:
        error_events.append(kwargs)

    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(routes_chapter, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(routes_chapter, "WorkflowContextBuilder", RaisingWorkflowContextBuilder)
    monkeypatch.setattr(routes_chapter, "get_streaming_service", lambda: object())
    monkeypatch.setattr(routes_chapter.ws_manager, "send_task_error", fake_send_task_error)

    await routes_chapter.execute_generate_next_chapter_task(
        task_id="generate-next-chapter-failed",
        project_id=1,
        user_id=99,
        next_chapter_number=2,
        concept="concept",
        world_setting="world",
        characters="characters",
        plot_outline="outline",
        previous_ending="ending",
        previous_chapters_summary="summary",
        previous_chapters_payload=[],
        recent_chapter_assets_summary="assets",
        workflow_generation_model="deepseek-pro",
    )

    history_updates = [
        (str(query), params)
        for query, params in fake_db.execute_calls
        if "UPDATE generation_history" in str(query)
    ]

    assert any(
        "error = :error" in query
        and "error_message" not in query
        and params["status"] == "failed"
        and params["error"] == "profile exploded"
        for query, params in history_updates
    )
    assert error_events == [
        {
            "project_id": 1,
            "task_id": "generate-next-chapter-failed",
            "error": "profile exploded",
        }
    ]
    assert fake_db.committed is True
    assert fake_db.closed is True


@pytest.mark.asyncio
async def test_running_tasks_marks_inactive_generate_next_chapter_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.workflow.routes_status as routes_status

    class FakeWorkflowContextBuilder:
        def __init__(self, db: Any) -> None:
            self.db = db

        def load_stage_status_snapshot(self, project_id: int) -> dict[str, str]:
            return {
                "stage_one_status": "completed",
                "stage_two_status": "pending",
                "stage_three_status": "pending",
                "stage_four_status": "pending",
                "stage_five_status": "pending",
            }

    class FakeRunningTasksDBSession:
        def __init__(self) -> None:
            self.execute_calls: list[tuple[Any, Any]] = []
            self.updated_rows: list[dict[str, Any]] = []
            self.committed = False

        def execute(self, query: Any, params: Any = None) -> SimpleNamespace:
            self.execute_calls.append((query, params))
            query_text = str(query)
            if "SELECT task_id, task_type, status, created_at" in query_text:
                return SimpleNamespace(
                    fetchall=lambda: [
                        (
                            "inactive-generate-next-chapter",
                            "generate_next_chapter",
                            "running",
                            "2026-04-27T03:00:00+00:00",
                        )
                    ]
                )
            if "UPDATE generation_history" in query_text:
                self.updated_rows.append(dict(params or {}))
            return SimpleNamespace(fetchall=lambda: [])

        def commit(self) -> None:
            self.committed = True

    fake_db = FakeRunningTasksDBSession()
    now = routes_status.parse_datetime_utc("2026-04-27T03:05:00+00:00")

    monkeypatch.setattr(routes_status, "WorkflowContextBuilder", FakeWorkflowContextBuilder)
    monkeypatch.setattr(routes_status, "utc_now", lambda: now)
    monkeypatch.setattr(
        routes_status,
        "WORKFLOW_STATUS_PROCESS_STARTED_AT",
        routes_status.parse_datetime_utc("2026-04-27T02:00:00+00:00"),
    )

    result = await routes_status.get_running_tasks(
        project_id=1,
        current_user=SimpleNamespace(id=99),
        db=fake_db,
    )

    assert result["running_tasks"] == []
    assert result["interrupted_tasks"] == [
        {
            "task_id": "inactive-generate-next-chapter",
            "task_type": "generate_next_chapter",
            "status": "failed",
            "created_at": "2026-04-27T03:00:00+00:00",
            "age_minutes": 5.0,
            "reason": "生成下一章任务已不在后端执行队列中，请重新发起",
        }
    ]
    assert fake_db.updated_rows == [
        {
            "error": "生成下一章任务已不在后端执行队列中，请重新发起",
            "completed_at": "2026-04-27T03:05:00+00:00",
            "task_id": "inactive-generate-next-chapter",
        }
    ]
    assert fake_db.committed is True
