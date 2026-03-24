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

import app.db.base as db_base
import app.services.character_parser as character_parser
import app.services.vector_sync as vector_sync
import backend.app.api.v1.workflow as workflow


class _FakeQuery:
    def __init__(self, *, first_result: Any = None, all_result: list[Any] | None = None) -> None:
        self._first_result = first_result
        self._all_result = list(all_result or [])

    def filter(self, *args: Any, **kwargs: Any) -> "_FakeQuery":
        return self

    def first(self) -> Any:
        return self._first_result

    def all(self) -> list[Any]:
        return list(self._all_result)


class _FakeDBSession:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[Any, Any]] = []
        self.query_models: list[Any] = []
        self.committed = False
        self.closed = False

    def query(self, model: Any) -> _FakeQuery:
        self.query_models.append(model)
        return _FakeQuery(first_result=object(), all_result=[])

    def execute(self, query: Any, params: Any = None) -> SimpleNamespace:
        self.execute_calls.append((query, params))
        return SimpleNamespace()

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


class _FrameworkGuardDBSession(_FakeDBSession):
    def __init__(
        self,
        *,
        epic_framework: str = "第1卷：旧卷\n第2卷：新卷",
        framework_generated_at: str | None = "2026-03-20T00:00:00+00:00",
    ) -> None:
        super().__init__()
        self.epic_framework = epic_framework
        self.framework_generated_at = framework_generated_at

    def execute(self, query: Any, params: Any = None) -> Any:
        self.execute_calls.append((query, params))
        query_text = str(query)
        if "SELECT epic_framework, epic_framework_generated_at" in query_text:
            return SimpleNamespace(fetchone=lambda: (self.epic_framework, self.framework_generated_at))
        return SimpleNamespace()


def test_legacy_expand_routes_are_hidden_from_schema() -> None:
    route_schema_flags = {
        getattr(route, "path", ""): getattr(route, "include_in_schema", None)
        for route in workflow.router.routes
    }

    assert route_schema_flags["/api/v1/workflow/expand-outline"] is False
    assert route_schema_flags["/api/v1/workflow/expand-characters"] is False
    assert route_schema_flags["/api/v1/workflow/expand-story"] is True
    assert route_schema_flags["/api/v1/workflow/expand-story/analysis"] is True


def test_select_text_model_by_input_tokens_uses_dynamic_model_budget() -> None:
    safe_budget = workflow._get_safe_input_token_budget("qwen3-max")

    assert safe_budget > 10000
    assert workflow._select_text_model_by_input_tokens(safe_budget - 1)[0] == "qwen3-max"
    assert workflow._select_text_model_by_input_tokens(safe_budget + 1)[0] == "qwen-long"


@pytest.mark.asyncio
async def test_analyze_expand_story_returns_analysis_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}
    expected_analysis = {
        "recommended_intent": "outline_led",
        "effective_target_chapter_count": 18,
        "effective_target_character_count": 4,
        "analysis_summary": "推荐采用大纲主导；执行模式为单轮增量；预计 1 轮",
    }

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        captured["request"] = request
        captured["db"] = db
        return {"analysis": expected_analysis}

    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)

    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=18,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
    )

    result = await workflow.analyze_expand_story(
        request=request,
        current_user=SimpleNamespace(id=99),
        db=fake_db,
    )

    assert result["success"] is True
    assert result["analysis"]["recommended_intent"] == "outline_led"
    assert result["analysis"]["effective_target_chapter_count"] == 18
    assert result["analysis"]["effective_target_character_count"] == 4
    assert result["analysis"]["analysis_summary"] == expected_analysis["analysis_summary"]
    assert result["analysis"]["warnings"] == []
    assert result["analysis"]["written_chapter_context"] == {
        "applied": False,
        "written_chapter_count": 0,
        "preserve_written_mode": "extract_extend",
    }
    assert captured["request"].project_id == 1
    assert captured["request"].enable_auto_supplement is True
    assert captured["db"] is fake_db


@pytest.mark.asyncio
async def test_analyze_expand_story_passes_explicit_epic_framework_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        captured["request"] = request
        return {
            "analysis": {
                "execution_mode": "epic",
                "effective_expansion_mode": "epic_framework",
                "epic_config": {
                    "total_volumes": 12,
                    "chapter_range": [900, 1200],
                },
            }
        }

    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)

    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_characters=12,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="epic_framework",
        total_volumes=12,
        total_chapters_min=900,
        total_chapters_max=1200,
    )

    result = await workflow.analyze_expand_story(
        request=request,
        current_user=SimpleNamespace(id=99),
        db=fake_db,
    )

    assert result["analysis"]["effective_expansion_mode"] == "epic_framework"
    assert captured["request"].expansion_mode == "epic_framework"
    assert captured["request"].total_volumes == 12
    assert captured["request"].total_chapters_max == 1200


@pytest.mark.asyncio
async def test_analyze_expand_story_requires_reset_when_switching_from_epic_framework() -> None:
    fake_db = _FrameworkGuardDBSession()
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="第1卷：旧卷\n第2卷：新卷",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=0,
        current_character_count=1,
        target_total_chapters=18,
        expansion_mode="total",
    )

    with pytest.raises(workflow.HTTPException) as exc_info:
        await workflow.analyze_expand_story(
            request=request,
            current_user=SimpleNamespace(id=99),
            db=fake_db,
        )

    assert exc_info.value.status_code == 400
    assert "清空旧框架" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_analyze_expand_story_includes_written_chapter_preview_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}

    def fake_preview(request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        return {
            "effective_outline": "第1章：已写开场\n- 已写摘要：主角入城。",
            "effective_current_chapter_count": 3,
            "written_chapter_count": 3,
            "warnings": ["检测到已写正文，预检阶段先按摘要预览。"],
            "applied": True,
        }

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        captured["request"] = request
        return {
            "analysis": {
                "execution_mode": "delta",
                "warnings": ["原始分析 warning"],
            }
        }

    monkeypatch.setattr(workflow, "_build_story_written_chapter_preview", fake_preview)
    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)

    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="旧大纲",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        target_total_chapters=12,
        preserve_written_mode="extract_extend",
    )

    result = await workflow.analyze_expand_story(
        request=request,
        current_user=SimpleNamespace(id=99),
        db=fake_db,
    )

    assert captured["request"].current_outline.startswith("第1章：已写开场")
    assert captured["request"].current_chapter_count == 3
    assert result["analysis"]["written_chapter_context"]["applied"] is True
    assert result["analysis"]["written_chapter_context"]["written_chapter_count"] == 3
    assert "原始分析 warning" in result["analysis"]["warnings"]
    assert "检测到已写正文" in " ".join(result["analysis"]["warnings"])


@pytest.mark.asyncio
async def test_execute_expand_story_task_uses_analysis_effective_targets_and_reports_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    analysis = {
        "effective_target_chapter_count": 20,
        "effective_target_character_count": 5,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "total",
        "execution_mode": "iterative",
        "execution_mode_reason": "超出单轮阈值，改为分轮协同。",
        "analysis_summary": "推荐采用大纲主导；执行模式为分轮协同；预计 2 轮",
        "warnings": ["会分轮逐步逼近目标。"],
    }
    captured: dict[str, Any] = {}
    progress_events: list[dict[str, Any]] = []
    complete_events: list[dict[str, Any]] = []
    error_events: list[dict[str, Any]] = []

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            captured["execute_kwargs"] = kwargs
            return {
                "plot_outline": "第1章：雨夜入城\n- 主要内容：主角抵达青石城。\n\n第2章：旧案浮现\n- 主要内容：顾晚加入调查。",
                "characters": "### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
                "outline_delta_text": "第2章：旧案浮现\n- 主要内容：顾晚加入调查。",
                "character_delta_text": "### 【姓名】：顾晚\n【角色定位】：盟友",
                "relationship_patch": "- 林舟 ↔ 顾晚：盟友（共同调查旧案）",
                "outline_ops_executed": [{"round": 1, "mode": "iterative"}],
                "execution_mode": "iterative",
                "execution_mode_reason": "超出单轮阈值，改为分轮协同。",
                "execution_rounds": [{"round": 1, "mode": "iterative"}],
                "new_character_names": ["顾晚"],
                "strategy": "plot_first",
                "summary": "已按分轮协同完成本轮扩展。",
                "current_chapter_count": 20,
                "current_character_count": 5,
                "validation_before": {"chapter_count": 8, "character_count": 2},
                "validation_after": {"chapter_count": 20, "character_count": 5},
                "stop_reasons": ["达到当前目标"],
            }

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        captured["analysis_request"] = request
        captured["analysis_db"] = db
        return {
            "coordinator": _FakeCoordinator(),
            "combined_world_setting": "蒸汽仙侠世界\n\n【项目设定摘要】旧神遗迹与三大宗门并存。",
            "analysis": analysis,
        }

    async def fake_send_task_progress(**kwargs: Any) -> None:
        progress_events.append(kwargs)

    async def fake_send_task_complete(**kwargs: Any) -> None:
        complete_events.append(kwargs)

    async def fake_send_task_error(**kwargs: Any) -> None:
        error_events.append(kwargs)

    async def fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", lambda **kwargs: {"parsed": 1, "created": 1, "updated": 0, "skipped": 0})
    monkeypatch.setattr(
        character_parser,
        "parse_and_sync_relationships",
        lambda **kwargs: {"parsed": 1, "saved": 1, "characters_updated": 0},
    )
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-test",
        project_id=1,
        user_id=99,
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=8,
        current_character_count=2,
        target_total_chapters=18,
        target_total_characters=None,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="total",
        total_volumes=None,
        total_chapters_min=None,
        total_chapters_max=None,
        target_volume_index=None,
        volume_chapters_min=None,
        volume_chapters_max=None,
        preserve_written_mode="extract_extend",
    )

    assert error_events == []
    assert fake_db.committed is True
    assert fake_db.closed is True
    assert len(progress_events) >= 4
    assert captured["analysis_request"].target_total_chapters == 18
    assert captured["analysis_request"].target_total_characters is None
    assert captured["analysis_request"].enable_auto_supplement is True
    assert captured["execute_kwargs"]["world_setting"].startswith("蒸汽仙侠世界")
    assert captured["execute_kwargs"]["target_total_chapters"] == 20
    assert captured["execute_kwargs"]["target_total_characters"] == 5
    assert captured["execute_kwargs"]["strategy"] == "plot_first"
    assert len(complete_events) == 1

    result = complete_events[0]["result"]
    assert result["story_intent"] == "outline_led"
    assert result["story_expansion_mode"] == "total"
    assert result["story_strategy"] == "plot_first"
    assert result["target_chapter_count"] == 20
    assert result["target_character_count"] == 5
    assert result["execution_mode"] == "iterative"
    assert result["expansion_analysis"] == analysis
    assert result["character_sync"]["relationships"]["saved"] == 1
    assert result["message"].startswith("✅ 协同拓展完成！")
    assert fake_db.execute_calls[-1][1]["project_id"] == 1


@pytest.mark.asyncio
async def test_execute_expand_story_task_uses_prepared_written_chapter_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}
    complete_events: list[dict[str, Any]] = []

    async def fake_prepare(request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        return {
            "request": request.model_copy(
                update={
                    "current_outline": "第1章：已写开场\n- 已写摘要：主角入城。",
                    "current_chapter_count": 3,
                }
            ),
            "written_chapter_count": 3,
            "warnings": ["执行前已根据已写正文提取章节细纲。"],
            "applied": True,
        }

    analysis = {
        "effective_target_chapter_count": 12,
        "effective_target_character_count": 4,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "total",
        "execution_mode": "delta",
        "execution_mode_reason": "单轮协同。",
        "warnings": [],
    }

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            captured["execute_kwargs"] = kwargs
            return {
                "plot_outline": "第1章：已写开场\n- 已写摘要：主角入城。\n\n第4章：新推进\n- 主要内容：新冲突展开。",
                "characters": "### 【姓名】：林舟\n【角色定位】：主角",
                "outline_ops_executed": [{"round": 1, "mode": "delta"}],
                "execution_mode": "delta",
                "execution_mode_reason": "单轮协同。",
                "execution_rounds": [{"round": 1, "mode": "delta"}],
                "strategy": "plot_first",
                "summary": "已完成扩展。",
                "current_chapter_count": 12,
                "current_character_count": 4,
                "validation_before": {"chapter_count": 3, "character_count": 1},
                "validation_after": {"chapter_count": 12, "character_count": 4},
                "stop_reasons": [],
            }

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        captured["analysis_request"] = request
        return {
            "coordinator": _FakeCoordinator(),
            "combined_world_setting": "蒸汽仙侠世界",
            "analysis": dict(analysis),
        }

    async def fake_send_task_progress(**kwargs: Any) -> None:
        return None

    async def fake_send_task_complete(**kwargs: Any) -> None:
        complete_events.append(kwargs)

    async def fake_send_task_error(**kwargs: Any) -> None:
        raise AssertionError(f"unexpected error event: {kwargs}")

    async def fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(workflow, "_prepare_story_execution_request", fake_prepare)
    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", lambda **kwargs: {"parsed": 0, "created": 0, "updated": 0, "skipped": 0})
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-written",
        project_id=1,
        user_id=99,
        current_outline="旧大纲",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=1,
        current_character_count=1,
        target_total_chapters=12,
        target_total_characters=4,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="total",
        total_volumes=None,
        total_chapters_min=None,
        total_chapters_max=None,
        target_volume_index=None,
        volume_chapters_min=None,
        volume_chapters_max=None,
        preserve_written_mode="extract_extend",
    )

    assert captured["analysis_request"].current_outline.startswith("第1章：已写开场")
    assert captured["execute_kwargs"]["current_outline"].startswith("第1章：已写开场")
    result = complete_events[0]["result"]
    assert result["story_preserve_written_mode"] == "extract_extend"
    assert result["written_chapter_context"]["applied"] is True
    assert result["written_chapter_context"]["written_chapter_count"] == 3
    assert "执行前已根据已写正文提取章节细纲" in " ".join(result["expansion_analysis"]["warnings"])


@pytest.mark.asyncio
async def test_execute_expand_story_task_passes_epic_framework_mode_to_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}
    complete_events: list[dict[str, Any]] = []

    analysis = {
        "effective_target_chapter_count": 1200,
        "effective_target_character_count": 18,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "epic_framework",
        "execution_mode": "epic",
        "execution_mode_reason": "已显式选择长篇框架协同。",
        "epic_config": {
            "total_volumes": 12,
            "chapter_range": [900, 1200],
        },
    }

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            captured["execute_kwargs"] = kwargs
            return {
                "plot_outline": "第1卷：星火入局\n- 主线：世界框架展开。",
                "characters": "### 【姓名】：林舟\n【角色定位】：主角",
                "outline_ops_executed": [{"stage": "epic_framework"}],
                "execution_mode": "epic",
                "execution_mode_reason": "已显式选择长篇框架协同。",
                "execution_rounds": [{"stage": "epic_framework"}],
                "strategy": "plot_first",
                "summary": "已生成长篇框架。",
                "current_chapter_count": 1200,
                "current_character_count": 18,
                "validation_before": {"chapter_count": 20, "character_count": 6},
                "validation_after": {"chapter_count": 1200, "character_count": 18},
                "epic_framework": "第1卷：星火入局\n- 主线：世界框架展开。",
                "epic_volumes_detail": "",
                "epic_total_volumes": 12,
                "epic_chapter_range": [900, 1200],
                "stop_reasons": [],
            }

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        captured["analysis_request"] = request
        return {
            "coordinator": _FakeCoordinator(),
            "combined_world_setting": "蒸汽仙侠世界",
            "analysis": analysis,
        }

    async def fake_send_task_progress(**kwargs: Any) -> None:
        return None

    async def fake_send_task_complete(**kwargs: Any) -> None:
        complete_events.append(kwargs)

    async def fake_send_task_error(**kwargs: Any) -> None:
        raise AssertionError(f"unexpected error event: {kwargs}")

    async def fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", lambda **kwargs: {"parsed": 0, "created": 0, "updated": 0, "skipped": 0})
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-epic",
        project_id=1,
        user_id=99,
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=20,
        current_character_count=6,
        target_total_chapters=None,
        target_total_characters=18,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="epic_framework",
        total_volumes=12,
        total_chapters_min=900,
        total_chapters_max=1200,
        target_volume_index=None,
        volume_chapters_min=None,
        volume_chapters_max=None,
        preserve_written_mode="extract_extend",
    )

    assert captured["analysis_request"].expansion_mode == "epic_framework"
    assert captured["execute_kwargs"]["expansion_mode"] == "epic_framework"
    assert captured["execute_kwargs"]["epic_config"] == {
        "total_volumes": 12,
        "chapter_range": [900, 1200],
    }
    result = complete_events[0]["result"]
    assert result["story_expansion_mode"] == "epic_framework"
    assert result["epic_total_volumes"] == 12
    assert result["epic_chapter_range"] == [900, 1200]


@pytest.mark.asyncio
async def test_execute_expand_story_task_passes_volume_detail_mode_to_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}
    complete_events: list[dict[str, Any]] = []

    analysis = {
        "effective_target_chapter_count": 60,
        "effective_target_character_count": 4,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "volume_detail",
        "execution_mode": "volume_detail",
        "execution_mode_reason": "已显式选择单卷细化协同。",
        "volume_detail": {
            "target_volume_index": 2,
            "chapter_range": [21, 60],
            "existing_detail": True,
        },
        "volume_detail_config": {
            "target_volume_index": 2,
            "chapter_range": [21, 60],
            "existing_detail": True,
        },
    }
    volume_detail_config = {
        "framework_content": "第1卷：旧卷\n第2卷：新卷",
        "target_volume_index": 2,
        "chapters_count_range": (30, 40),
        "start_chapter_num": 21,
        "framework_header": "## 整体节奏",
        "framework_footer": "## 伏笔布局",
        "volumes_data": {
            "total_volumes": 2,
            "framework_header": "## 整体节奏",
            "framework_footer": "## 伏笔布局",
            "volumes": {},
        },
        "expected_chapter_range": (21, 60),
        "expected_total_chapter_count": 60,
        "current_total_chapter_count": 20,
        "total_volumes": 2,
        "existing_volume_detail": "旧细纲",
    }

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            captured["execute_kwargs"] = kwargs
            return {
                "plot_outline": "### 【第2卷】《第二卷》\n\n第21章：新卷开场",
                "characters": "### 【姓名】：林舟\n【角色定位】：主角",
                "outline_delta_text": "第21章：新卷开场",
                "outline_ops_executed": [{"stage": "volume_detail"}],
                "execution_mode": "volume_detail",
                "execution_mode_reason": "已显式选择单卷细化协同。",
                "execution_rounds": [{"stage": "volume_detail"}],
                "strategy": "plot_first",
                "summary": "已细化第2卷。",
                "current_chapter_count": 60,
                "current_character_count": 4,
                "validation_before": {"chapter_count": 20, "character_count": 2},
                "validation_after": {"chapter_count": 60, "character_count": 4},
                "epic_framework": "第1卷：旧卷\n第2卷：新卷",
                "epic_volumes_detail": "{\"volumes\":{}}",
                "epic_total_volumes": 2,
                "volume_index": 2,
                "volume_chapter_range": [21, 60],
                "stop_reasons": [],
            }

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        captured["analysis_request"] = request
        return {
            "coordinator": _FakeCoordinator(),
            "combined_world_setting": "蒸汽仙侠世界",
            "analysis": analysis,
            "volume_detail_config": volume_detail_config,
        }

    async def fake_send_task_progress(**kwargs: Any) -> None:
        return None

    async def fake_send_task_complete(**kwargs: Any) -> None:
        complete_events.append(kwargs)

    async def fake_send_task_error(**kwargs: Any) -> None:
        raise AssertionError(f"unexpected error event: {kwargs}")

    async def fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", lambda **kwargs: {"parsed": 0, "created": 0, "updated": 0, "skipped": 0})
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-volume",
        project_id=1,
        user_id=99,
        current_outline="## 📚 分卷概要",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=20,
        current_character_count=2,
        target_total_chapters=None,
        target_total_characters=4,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="volume_detail",
        total_volumes=None,
        total_chapters_min=None,
        total_chapters_max=None,
        target_volume_index=2,
        volume_chapters_min=30,
        volume_chapters_max=40,
        preserve_written_mode="extract_extend",
    )

    assert captured["analysis_request"].expansion_mode == "volume_detail"
    assert captured["analysis_request"].target_volume_index == 2
    assert captured["execute_kwargs"]["expansion_mode"] == "volume_detail"
    assert captured["execute_kwargs"]["volume_detail_config"] == volume_detail_config
    result = complete_events[0]["result"]
    assert result["story_expansion_mode"] == "volume_detail"
    assert result["volume_index"] == 2
    assert result["volume_chapter_range"] == [21, 60]


@pytest.mark.asyncio
async def test_execute_expand_story_task_clears_epic_framework_when_reset_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FrameworkGuardDBSession()
    complete_events: list[dict[str, Any]] = []

    analysis = {
        "effective_target_chapter_count": 18,
        "effective_target_character_count": 4,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "total",
        "execution_mode": "iterative",
        "execution_mode_reason": "常规协同执行",
        "warnings": [],
    }

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "plot_outline": "第1章：重建主线\n- 主要内容：以常规章节结构重建故事。",
                "characters": "### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
                "outline_delta_text": "第1章：重建主线\n- 主要内容：以常规章节结构重建故事。",
                "character_delta_text": "### 【姓名】：顾晚\n【角色定位】：盟友",
                "relationship_patch": "- 林舟 -> 顾晚：盟友（共同推进新主线）",
                "outline_ops_executed": [{"round": 1, "mode": "iterative"}],
                "execution_mode": "iterative",
                "execution_mode_reason": "常规协同执行",
                "execution_rounds": [{"round": 1, "mode": "iterative"}],
                "new_character_names": ["顾晚"],
                "strategy": "plot_first",
                "summary": "已切回常规协同并完成本轮补强。",
                "current_chapter_count": 18,
                "current_character_count": 4,
                "validation_before": {"chapter_count": 0, "character_count": 1},
                "validation_after": {"chapter_count": 18, "character_count": 4},
                "stop_reasons": ["达到当前目标"],
            }

    async def fake_prepare(request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        return {
            "request": request,
            "written_chapter_count": 0,
            "warnings": [],
            "applied": False,
        }

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        return {
            "coordinator": _FakeCoordinator(),
            "combined_world_setting": "蒸汽仙侠世界",
            "analysis": analysis,
        }

    async def fake_send_task_progress(**kwargs: Any) -> None:
        return None

    async def fake_send_task_complete(**kwargs: Any) -> None:
        complete_events.append(kwargs)

    async def fake_send_task_error(**kwargs: Any) -> None:
        raise AssertionError(f"unexpected error event: {kwargs}")

    async def fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(workflow, "_prepare_story_execution_request", fake_prepare)
    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", lambda **kwargs: {"parsed": 0, "created": 0, "updated": 0, "skipped": 0})
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-reset-framework",
        project_id=1,
        user_id=99,
        current_outline="第1卷：旧卷\n第2卷：新卷",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=0,
        current_character_count=1,
        target_total_chapters=18,
        target_total_characters=4,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=True,
        expansion_mode="total",
        total_volumes=None,
        total_chapters_min=None,
        total_chapters_max=None,
        target_volume_index=None,
        volume_chapters_min=None,
        volume_chapters_max=None,
        preserve_written_mode="extract_extend",
        reset_epic_framework=True,
    )

    update_calls = [
        params
        for query, params in fake_db.execute_calls
        if "UPDATE project_settings" in str(query)
    ]

    assert update_calls
    assert update_calls[0]["epic_framework"] is None
    assert update_calls[0]["epic_volumes_detail"] is None
    assert update_calls[0]["epic_framework_generated_at"] is None
    assert complete_events[0]["result"]["story_expansion_mode"] == "total"


@pytest.mark.asyncio
async def test_execute_expand_characters_task_passes_project_profile_to_expander(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.agents.outline_expander as outline_expander

    captured: dict[str, Any] = {}
    complete_events: list[dict[str, Any]] = []

    class _FetchOneResult:
        def __init__(self, row: Any) -> None:
            self._row = row

        def fetchone(self) -> Any:
            return self._row

    class _LegacyCharactersDBSession(_FakeDBSession):
        def execute(self, query: Any, params: Any = None) -> Any:
            self.execute_calls.append((query, params))
            if "SELECT genre, planned_chapters_max" in str(query):
                return _FetchOneResult(("修仙", 1200))
            return SimpleNamespace()

    class _FakeLegacyCharacterExpander:
        def expand_characters_incremental(self, **kwargs: Any) -> dict[str, Any]:
            captured["expand_kwargs"] = kwargs
            return {
                "all_characters": "### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
                "current_character_count": 2,
                "should_continue": False,
                "continue_reason": "已达到目标",
                "post_validation_score": 82,
            }

    def fake_create_outline_expander(**kwargs: Any) -> _FakeLegacyCharacterExpander:
        captured["expander_kwargs"] = kwargs
        return _FakeLegacyCharacterExpander()

    async def fake_send_task_progress(**kwargs: Any) -> None:
        return None

    async def fake_send_task_complete(**kwargs: Any) -> None:
        complete_events.append(kwargs)

    async def fake_send_task_error(**kwargs: Any) -> None:
        raise AssertionError(f"unexpected error event: {kwargs}")

    async def fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    fake_db = _LegacyCharactersDBSession()

    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(workflow, "build_project_settings_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        workflow,
        "_build_legacy_character_story_analysis",
        lambda **kwargs: {
            "available": True,
            "source": "legacy_characters",
            "analysis_summary": "推荐采用人物主导；执行模式为单轮增量；预计 1 轮",
        },
    )
    monkeypatch.setattr(outline_expander, "create_outline_expander", fake_create_outline_expander)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", lambda **kwargs: {"parsed": 0, "created": 0, "updated": 0, "skipped": 0})
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_characters_task(
        task_id="expand-characters-legacy-profile",
        project_id=1,
        user_id=99,
        main_characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="山海修真世界",
        plot_outline="第1章：少年入山门。",
        current_character_count=1,
        target_total_characters=2,
    )

    assert fake_db.committed is True
    assert fake_db.closed is True
    assert captured["expander_kwargs"] == {
        "genre": "修仙",
        "planned_chapters_max": 1200,
        "project_id": 1,
    }
    assert captured["expand_kwargs"]["target_total_characters"] == 2
    assert len(complete_events) == 1
    assert complete_events[0]["result"]["current_character_count"] == 2
    assert complete_events[0]["result"]["story_expansion_analysis"]["source"] == "legacy_characters"


@pytest.mark.asyncio
async def test_execute_expand_outline_task_returns_legacy_story_analysis_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.agents.outline_expander as outline_expander

    captured: dict[str, Any] = {}
    complete_events: list[dict[str, Any]] = []

    class _FetchOneResult:
        def __init__(self, row: Any) -> None:
            self._row = row

        def fetchone(self) -> Any:
            return self._row

    class _LegacyOutlineDBSession(_FakeDBSession):
        def execute(self, query: Any, params: Any = None) -> Any:
            self.execute_calls.append((query, params))
            if "SELECT genre, planned_chapters_max" in str(query):
                return _FetchOneResult(("悬疑", 60))
            return SimpleNamespace()

    class _FakeLegacyOutlineExpander:
        def __init__(self) -> None:
            self.llm = object()

        def expand_plot_outline_incremental(self, **kwargs: Any) -> dict[str, Any]:
            captured["expand_kwargs"] = kwargs
            return {
                "expanded_outline": "第1章：雨夜入城\n- 主要内容：主角抵达青石城。\n\n第2章：旧案浮现\n- 主要内容：旧案被重新提起。",
                "current_chapter_count": 2,
                "should_continue": False,
                "continue_reason": "已达到当前目标",
            }

    def fake_create_outline_expander(**kwargs: Any) -> _FakeLegacyOutlineExpander:
        captured["expander_kwargs"] = kwargs
        return _FakeLegacyOutlineExpander()

    async def fake_process_written_chapters(**kwargs: Any) -> tuple[int, str]:
        return (0, "")

    async def fake_send_task_progress(**kwargs: Any) -> None:
        return None

    async def fake_send_task_complete(**kwargs: Any) -> None:
        complete_events.append(kwargs)

    async def fake_send_task_error(**kwargs: Any) -> None:
        raise AssertionError(f"unexpected error event: {kwargs}")

    async def fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    fake_db = _LegacyOutlineDBSession()

    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(workflow, "build_project_settings_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        workflow,
        "_build_legacy_outline_story_analysis",
        lambda **kwargs: {
            "available": True,
            "source": "legacy_outline",
            "analysis_summary": "推荐采用大纲主导；执行模式为单轮增量；预计 1 轮",
        },
    )
    monkeypatch.setattr(outline_expander, "create_outline_expander", fake_create_outline_expander)
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    monkeypatch.setitem(sys.modules, "app.services.agents.written_chapters_handler", SimpleNamespace(process_written_chapters=fake_process_written_chapters))

    await workflow.execute_expand_outline_task(
        task_id="expand-outline-legacy-analysis",
        project_id=1,
        user_id=99,
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽迷城",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=1,
        increment=1,
        target_total_chapters=2,
        expansion_mode="total",
        preserve_written_mode="extract_extend",
    )

    assert fake_db.committed is True
    assert fake_db.closed is True
    assert captured["expander_kwargs"] == {
        "genre": "悬疑",
        "planned_chapters_max": 60,
        "project_id": 1,
    }
    assert captured["expand_kwargs"]["target_total_chapters"] == 2
    assert len(complete_events) == 1
    assert complete_events[0]["result"]["story_expansion_analysis"]["source"] == "legacy_outline"


@pytest.mark.asyncio
async def test_execute_expand_outline_task_reuses_provided_legacy_story_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.agents.outline_expander as outline_expander

    complete_events: list[dict[str, Any]] = []
    provided_analysis = {
        "available": True,
        "source": "legacy_outline",
        "analysis_summary": "直接复用的兼容分析",
    }

    class _FetchOneResult:
        def __init__(self, row: Any) -> None:
            self._row = row

        def fetchone(self) -> Any:
            return self._row

    class _LegacyOutlineDBSession(_FakeDBSession):
        def execute(self, query: Any, params: Any = None) -> Any:
            self.execute_calls.append((query, params))
            if "SELECT genre, planned_chapters_max" in str(query):
                return _FetchOneResult(("悬疑", 60))
            return SimpleNamespace()

    class _FakeLegacyOutlineExpander:
        def __init__(self) -> None:
            self.llm = object()

        def expand_plot_outline_incremental(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "expanded_outline": "第1章：雨夜入城\n- 主要内容：主角抵达青石城。\n\n第2章：旧案浮现\n- 主要内容：旧案被重新提起。",
                "current_chapter_count": 2,
                "should_continue": False,
                "continue_reason": "已达到当前目标",
            }

    async def fake_process_written_chapters(**kwargs: Any) -> tuple[int, str]:
        return (0, "")

    async def fake_send_task_progress(**kwargs: Any) -> None:
        return None

    async def fake_send_task_complete(**kwargs: Any) -> None:
        complete_events.append(kwargs)

    async def fake_send_task_error(**kwargs: Any) -> None:
        raise AssertionError(f"unexpected error event: {kwargs}")

    async def fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    fake_db = _LegacyOutlineDBSession()

    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(workflow, "build_project_settings_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        workflow,
        "_build_legacy_outline_story_analysis_from_task",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not rebuild legacy outline analysis")),
    )
    monkeypatch.setattr(outline_expander, "create_outline_expander", lambda **kwargs: _FakeLegacyOutlineExpander())
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)
    monkeypatch.setitem(
        sys.modules,
        "app.services.agents.written_chapters_handler",
        SimpleNamespace(process_written_chapters=fake_process_written_chapters),
    )

    await workflow.execute_expand_outline_task(
        task_id="expand-outline-reuse-analysis",
        project_id=1,
        user_id=99,
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽迷城",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=1,
        increment=1,
        target_total_chapters=2,
        expansion_mode="total",
        preserve_written_mode="extract_extend",
        legacy_story_analysis=provided_analysis,
    )

    assert fake_db.committed is True
    assert fake_db.closed is True
    assert len(complete_events) == 1
    assert complete_events[0]["result"]["story_expansion_analysis"] is provided_analysis


def test_build_legacy_outline_story_analysis_maps_request_to_story_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}

    def fake_preview(request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        return {
            "effective_outline": request.current_outline,
            "effective_current_chapter_count": request.current_chapter_count,
            "written_chapter_count": 0,
            "warnings": [],
            "applied": False,
        }

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        captured["request"] = request
        return {
            "analysis": {
                "recommended_intent": "outline_led",
                "effective_intent": "outline_led",
                "effective_strategy": "plot_first",
                "execution_mode": "iterative",
                "execution_mode_reason": "超出单轮阈值。",
                "effective_target_chapter_count": 24,
                "effective_target_character_count": 5,
                "estimated_rounds": 2,
                "analysis_summary": "推荐采用大纲主导；执行模式为分轮协同；预计 2 轮",
                "model_plan": {
                    "outline_expansion_model": "qwen3-max",
                    "character_expansion_model": "deepseek-reasoner",
                },
                "warnings": ["原始分析 warning"],
            }
        }

    monkeypatch.setattr(workflow, "_build_story_written_chapter_preview", fake_preview)
    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)

    result = workflow._build_legacy_outline_story_analysis(
        request=workflow.ExpandOutlineRequest(
            project_id=1,
            current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
            world_setting="蒸汽仙侠世界",
            characters="### 【姓名】：林舟\n【角色定位】：主角",
            current_chapter_count=1,
            target_total_chapters=24,
            expansion_mode="incremental",
            preserve_written_mode="extract_extend",
        ),
        db=fake_db,
        target_total_chapters=24,
    )

    assert captured["request"].intent == "outline_led"
    assert captured["request"].strategy == "plot_first"
    assert captured["request"].enable_auto_supplement is True
    assert captured["request"].expansion_mode == "total"
    assert captured["request"].current_character_count == 1
    assert result["available"] is True
    assert result["requested_mode"] == "incremental"
    assert result["mapped_story_mode"] == "total"
    assert result["effective_target_character_count"] == 5
    assert "旧模式 incremental 映射为协同模式 total" in " ".join(result["warnings"])


def test_build_legacy_character_story_analysis_maps_request_to_story_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}

    def fake_preview(request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        return {
            "effective_outline": request.current_outline,
            "effective_current_chapter_count": request.current_chapter_count,
            "written_chapter_count": 0,
            "warnings": [],
            "applied": False,
        }

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        captured["request"] = request
        return {
            "analysis": {
                "recommended_intent": "character_led",
                "effective_intent": "character_led",
                "effective_strategy": "character_first",
                "execution_mode": "delta",
                "execution_mode_reason": "人物缺口适合单轮协同。",
                "effective_target_chapter_count": 12,
                "effective_target_character_count": 10,
                "estimated_rounds": 1,
                "analysis_summary": "推荐采用人物主导；执行模式为单轮增量；预计 1 轮",
                "model_plan": {
                    "outline_expansion_model": "qwen3-max",
                    "character_expansion_model": "deepseek-reasoner",
                },
                "warnings": [],
            }
        }

    monkeypatch.setattr(workflow, "_build_story_written_chapter_preview", fake_preview)
    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)

    result = workflow._build_legacy_character_story_analysis(
        request=workflow.ExpandCharactersRequest(
            project_id=1,
            main_characters="### 【姓名】：林舟\n【角色定位】：主角",
            world_setting="蒸汽仙侠世界",
            plot_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
            current_character_count=0,
            target_total_characters=10,
        ),
        db=fake_db,
        target_total_characters=10,
    )

    assert captured["request"].intent == "character_led"
    assert captured["request"].strategy == "character_first"
    assert captured["request"].expansion_mode == "total"
    assert captured["request"].current_character_count == 1
    assert captured["request"].target_total_chapters is None
    assert result["available"] is True
    assert result["requested_entry"] == "expand-characters"
    assert result["effective_target_chapter_count"] == 12


def test_build_project_world_setting_context_appends_settings_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "build_project_settings_summary",
        lambda *args, **kwargs: "【设定摘要】门派体系稳定。",
    )

    result = workflow._build_project_world_setting_context(
        project_id=1,
        world_setting="蒸汽仙侠世界",
        db=_FakeDBSession(),
    )

    assert result == "蒸汽仙侠世界\n\n【设定摘要】门派体系稳定。"


def test_build_legacy_outline_story_analysis_from_task_maps_background_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}

    def fake_legacy_analysis(
        *,
        request: workflow.ExpandOutlineRequest,
        db: Any,
        target_total_chapters: int,
    ) -> dict[str, Any]:
        captured["request"] = request
        captured["db"] = db
        captured["target_total_chapters"] = target_total_chapters
        return {"available": True, "source": "legacy_outline"}

    monkeypatch.setattr(workflow, "_build_legacy_outline_story_analysis", fake_legacy_analysis)

    result = workflow._build_legacy_outline_story_analysis_from_task(
        db=fake_db,
        project_id=1,
        current_outline="第1章：雨夜入城",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=3,
        increment=2,
        target_total_chapters=18,
        expansion_mode="volume_detail",
        target_volumes=3,
        chapters_per_volume_min=12,
        chapters_per_volume_max=18,
        incremental_step=4,
        total_volumes=10,
        total_chapters_min=800,
        total_chapters_max=1200,
        framework_content="总卷数: 10",
        target_volume_index=2,
        volume_chapters_min=30,
        volume_chapters_max=40,
        preserve_written_mode="preserve_written",
    )

    assert result["source"] == "legacy_outline"
    assert captured["db"] is fake_db
    assert captured["target_total_chapters"] == 18
    assert captured["request"].project_id == 1
    assert captured["request"].current_chapter_count == 3
    assert captured["request"].increment == 2
    assert captured["request"].target_total_chapters == 18
    assert captured["request"].expansion_mode == "volume_detail"
    assert captured["request"].target_volumes == 3
    assert captured["request"].chapters_per_volume_min == 12
    assert captured["request"].chapters_per_volume_max == 18
    assert captured["request"].incremental_step == 4
    assert captured["request"].total_volumes == 10
    assert captured["request"].total_chapters_min == 800
    assert captured["request"].total_chapters_max == 1200
    assert captured["request"].framework_content == "总卷数: 10"
    assert captured["request"].target_volume_index == 2
    assert captured["request"].volume_chapters_min == 30
    assert captured["request"].volume_chapters_max == 40
    assert captured["request"].preserve_written_mode == "preserve_written"


def test_build_legacy_character_story_analysis_from_task_maps_background_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}

    def fake_legacy_analysis(
        *,
        request: workflow.ExpandCharactersRequest,
        db: Any,
        target_total_characters: int,
    ) -> dict[str, Any]:
        captured["request"] = request
        captured["db"] = db
        captured["target_total_characters"] = target_total_characters
        return {"available": True, "source": "legacy_characters"}

    monkeypatch.setattr(workflow, "_build_legacy_character_story_analysis", fake_legacy_analysis)

    result = workflow._build_legacy_character_story_analysis_from_task(
        db=fake_db,
        project_id=1,
        main_characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="蒸汽仙侠世界",
        plot_outline="第1章：雨夜入城",
        current_character_count=2,
        target_total_characters=10,
    )

    assert result["source"] == "legacy_characters"
    assert captured["db"] is fake_db
    assert captured["target_total_characters"] == 10
    assert captured["request"].project_id == 1
    assert captured["request"].main_characters.startswith("### 【姓名】：林舟")
    assert captured["request"].world_setting == "蒸汽仙侠世界"
    assert captured["request"].plot_outline == "第1章：雨夜入城"
    assert captured["request"].current_character_count == 2
    assert captured["request"].target_total_characters == 10


@pytest.mark.asyncio
async def test_execute_expand_characters_task_uses_shared_character_estimator_when_count_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.agents.outline_expander as outline_expander

    captured: dict[str, Any] = {}

    class _FetchOneResult:
        def __init__(self, row: Any) -> None:
            self._row = row

        def fetchone(self) -> Any:
            return self._row

    class _LegacyCharactersDBSession(_FakeDBSession):
        def execute(self, query: Any, params: Any = None) -> Any:
            self.execute_calls.append((query, params))
            if "SELECT genre, planned_chapters_max" in str(query):
                return _FetchOneResult(("修仙", 1200))
            return SimpleNamespace()

    class _FakeLegacyCharacterExpander:
        def expand_characters_incremental(self, **kwargs: Any) -> dict[str, Any]:
            captured["expand_kwargs"] = kwargs
            return {
                "all_characters": "### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友\n\n### 【姓名】：周朔\n【角色定位】：配角\n\n### 【姓名】：沈砚\n【角色定位】：配角\n\n### 【姓名】：苏禾\n【角色定位】：配角",
                "current_character_count": 5,
                "should_continue": False,
                "continue_reason": "已达到目标",
                "post_validation_score": 85,
            }

    def fake_create_outline_expander(**kwargs: Any) -> _FakeLegacyCharacterExpander:
        captured["expander_kwargs"] = kwargs
        return _FakeLegacyCharacterExpander()

    async def fake_send_task_progress(**kwargs: Any) -> None:
        return None

    async def fake_send_task_complete(**kwargs: Any) -> None:
        return None

    async def fake_send_task_error(**kwargs: Any) -> None:
        raise AssertionError(f"unexpected error event: {kwargs}")

    async def fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    fake_db = _LegacyCharactersDBSession()

    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(workflow, "build_project_settings_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr(workflow, "_estimate_character_count_from_text", lambda text: 3)
    monkeypatch.setattr(
        workflow,
        "_build_legacy_character_story_analysis",
        lambda **kwargs: {
            "available": True,
            "source": "legacy_characters",
            "analysis_summary": "推荐采用人物主导；执行模式为单轮增量；预计 1 轮",
        },
    )
    monkeypatch.setattr(outline_expander, "create_outline_expander", fake_create_outline_expander)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", lambda **kwargs: {"parsed": 0, "created": 0, "updated": 0, "skipped": 0})
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_characters_task(
        task_id="expand-characters-auto-detect",
        project_id=1,
        user_id=99,
        main_characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="山海修真世界",
        plot_outline="第1章：少年入山门。",
        current_character_count=0,
        target_total_characters=5,
    )

    assert fake_db.committed is True
    assert fake_db.closed is True
    assert captured["expander_kwargs"] == {
        "genre": "修仙",
        "planned_chapters_max": 1200,
        "project_id": 1,
    }
    assert captured["expand_kwargs"]["current_character_count"] == 3
    assert captured["expand_kwargs"]["target_total_characters"] == 5


@pytest.mark.asyncio
async def test_execute_expand_characters_task_reuses_provided_legacy_story_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.agents.outline_expander as outline_expander

    complete_events: list[dict[str, Any]] = []
    provided_analysis = {
        "available": True,
        "source": "legacy_characters",
        "analysis_summary": "直接复用的人物兼容分析",
    }

    class _FetchOneResult:
        def __init__(self, row: Any) -> None:
            self._row = row

        def fetchone(self) -> Any:
            return self._row

    class _LegacyCharactersDBSession(_FakeDBSession):
        def execute(self, query: Any, params: Any = None) -> Any:
            self.execute_calls.append((query, params))
            if "SELECT genre, planned_chapters_max" in str(query):
                return _FetchOneResult(("修仙", 1200))
            return SimpleNamespace()

    class _FakeLegacyCharacterExpander:
        def expand_characters_incremental(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "all_characters": "### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
                "current_character_count": 2,
                "should_continue": False,
                "continue_reason": "已达到目标",
                "post_validation_score": 82,
            }

    async def fake_send_task_progress(**kwargs: Any) -> None:
        return None

    async def fake_send_task_complete(**kwargs: Any) -> None:
        complete_events.append(kwargs)

    async def fake_send_task_error(**kwargs: Any) -> None:
        raise AssertionError(f"unexpected error event: {kwargs}")

    async def fake_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    fake_db = _LegacyCharactersDBSession()

    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(workflow, "build_project_settings_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        workflow,
        "_build_legacy_character_story_analysis_from_task",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not rebuild legacy character analysis")),
    )
    monkeypatch.setattr(outline_expander, "create_outline_expander", lambda **kwargs: _FakeLegacyCharacterExpander())
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", lambda **kwargs: {"parsed": 0, "created": 0, "updated": 0, "skipped": 0})
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_characters_task(
        task_id="expand-characters-reuse-analysis",
        project_id=1,
        user_id=99,
        main_characters="### 【姓名】：林舟\n【角色定位】：主角",
        world_setting="山海修真世界",
        plot_outline="第1章：少年入山门。",
        current_character_count=1,
        target_total_characters=2,
        legacy_story_analysis=provided_analysis,
    )

    assert fake_db.committed is True
    assert fake_db.closed is True
    assert len(complete_events) == 1
    assert complete_events[0]["result"]["story_expansion_analysis"] is provided_analysis


@pytest.mark.asyncio
async def test_expand_story_passes_reset_epic_framework_into_background_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FrameworkGuardDBSession()
    captured: dict[str, Any] = {}

    def fake_create_task(coro: Any) -> SimpleNamespace:
        captured["scheduled"] = True
        coro.close()
        return SimpleNamespace()

    def fake_execute_expand_story_task(**kwargs: Any) -> Any:
        captured["task_kwargs"] = kwargs

        async def _noop() -> None:
            return None

        return _noop()

    monkeypatch.setattr(workflow, "execute_expand_story_task", fake_execute_expand_story_task)
    monkeypatch.setattr(workflow.asyncio, "create_task", fake_create_task)

    result = await workflow.expand_story(
        request=workflow.ExpandStoryRequest(
            project_id=1,
            current_outline="第1卷：旧卷\n第2卷：新卷",
            world_setting="蒸汽仙侠世界",
            characters="### 【姓名】：林舟\n【角色定位】：主角",
            current_chapter_count=0,
            current_character_count=1,
            target_total_chapters=18,
            expansion_mode="total",
            reset_epic_framework=True,
        ),
        current_user=SimpleNamespace(id=99),
        db=fake_db,
    )

    assert captured["scheduled"] is True
    assert captured["task_kwargs"]["reset_epic_framework"] is True
    assert result["success"] is True


@pytest.mark.asyncio
async def test_expand_outline_returns_legacy_story_analysis_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}

    def fake_legacy_analysis(**kwargs: Any) -> dict[str, Any]:
        captured["legacy_kwargs"] = kwargs
        return {
            "available": True,
            "source": "legacy_outline",
            "analysis_summary": "推荐采用大纲主导；执行模式为分轮协同；预计 2 轮",
        }

    def fake_create_task(coro: Any) -> SimpleNamespace:
        captured["scheduled"] = True
        coro.close()
        return SimpleNamespace()

    def fake_execute_expand_outline_task(**kwargs: Any) -> Any:
        captured["task_kwargs"] = kwargs

        async def _noop() -> None:
            return None

        return _noop()

    monkeypatch.setattr(workflow, "_build_legacy_outline_story_analysis", fake_legacy_analysis)
    monkeypatch.setattr(workflow, "execute_expand_outline_task", fake_execute_expand_outline_task)
    monkeypatch.setattr(workflow.asyncio, "create_task", fake_create_task)

    result = await workflow.expand_outline(
        request=workflow.ExpandOutlineRequest(
            project_id=1,
            current_outline="第1章：雨夜入城",
            world_setting="蒸汽仙侠世界",
            characters="### 【姓名】：林舟\n【角色定位】：主角",
            current_chapter_count=1,
            target_total_chapters=18,
        ),
        current_user=SimpleNamespace(id=99),
        db=fake_db,
    )

    assert captured["legacy_kwargs"]["target_total_chapters"] == 18
    assert captured["scheduled"] is True
    assert result["story_expansion_analysis"]["source"] == "legacy_outline"
    assert captured["task_kwargs"]["legacy_story_analysis"] == result["story_expansion_analysis"]


@pytest.mark.asyncio
async def test_expand_outline_passes_legacy_story_analysis_into_background_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}

    def fake_legacy_analysis(**kwargs: Any) -> dict[str, Any]:
        return {
            "available": True,
            "source": "legacy_outline",
            "analysis_summary": "推荐采用大纲主导；执行模式为分轮协同；预计 2 轮",
        }

    def fake_execute_expand_outline_task(**kwargs: Any) -> Any:
        captured["task_kwargs"] = kwargs

        async def _noop() -> None:
            return None

        return _noop()

    def fake_create_task(coro: Any) -> SimpleNamespace:
        captured["scheduled"] = True
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(workflow, "_build_legacy_outline_story_analysis", fake_legacy_analysis)
    monkeypatch.setattr(workflow, "execute_expand_outline_task", fake_execute_expand_outline_task)
    monkeypatch.setattr(workflow.asyncio, "create_task", fake_create_task)

    result = await workflow.expand_outline(
        request=workflow.ExpandOutlineRequest(
            project_id=1,
            current_outline="第1章：雨夜入城",
            world_setting="蒸汽仙侠世界",
            characters="### 【姓名】：林舟\n【角色定位】：主角",
            current_chapter_count=1,
            target_total_chapters=18,
        ),
        current_user=SimpleNamespace(id=99),
        db=fake_db,
    )

    assert captured["scheduled"] is True
    assert captured["task_kwargs"]["legacy_story_analysis"] == result["story_expansion_analysis"]


@pytest.mark.asyncio
async def test_expand_characters_returns_legacy_story_analysis_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}

    def fake_legacy_analysis(**kwargs: Any) -> dict[str, Any]:
        captured["legacy_kwargs"] = kwargs
        return {
            "available": True,
            "source": "legacy_characters",
            "analysis_summary": "推荐采用人物主导；执行模式为单轮增量；预计 1 轮",
        }

    def fake_create_task(coro: Any) -> SimpleNamespace:
        captured["scheduled"] = True
        coro.close()
        return SimpleNamespace()

    def fake_execute_expand_characters_task(**kwargs: Any) -> Any:
        captured["task_kwargs"] = kwargs

        async def _noop() -> None:
            return None

        return _noop()

    monkeypatch.setattr(workflow, "_build_legacy_character_story_analysis", fake_legacy_analysis)
    monkeypatch.setattr(workflow, "execute_expand_characters_task", fake_execute_expand_characters_task)
    monkeypatch.setattr(workflow.asyncio, "create_task", fake_create_task)

    result = await workflow.expand_characters(
        request=workflow.ExpandCharactersRequest(
            project_id=1,
            main_characters="### 【姓名】：林舟\n【角色定位】：主角",
            world_setting="蒸汽仙侠世界",
            plot_outline="第1章：雨夜入城",
            current_character_count=1,
            target_total_characters=10,
        ),
        current_user=SimpleNamespace(id=99),
        db=fake_db,
    )

    assert captured["legacy_kwargs"]["target_total_characters"] == 10
    assert captured["scheduled"] is True
    assert result["story_expansion_analysis"]["source"] == "legacy_characters"
    assert captured["task_kwargs"]["legacy_story_analysis"] == result["story_expansion_analysis"]


@pytest.mark.asyncio
async def test_expand_characters_passes_legacy_story_analysis_into_background_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}

    def fake_legacy_analysis(**kwargs: Any) -> dict[str, Any]:
        return {
            "available": True,
            "source": "legacy_characters",
            "analysis_summary": "推荐采用人物主导；执行模式为单轮增量；预计 1 轮",
        }

    def fake_execute_expand_characters_task(**kwargs: Any) -> Any:
        captured["task_kwargs"] = kwargs

        async def _noop() -> None:
            return None

        return _noop()

    def fake_create_task(coro: Any) -> SimpleNamespace:
        captured["scheduled"] = True
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(workflow, "_build_legacy_character_story_analysis", fake_legacy_analysis)
    monkeypatch.setattr(workflow, "execute_expand_characters_task", fake_execute_expand_characters_task)
    monkeypatch.setattr(workflow.asyncio, "create_task", fake_create_task)

    result = await workflow.expand_characters(
        request=workflow.ExpandCharactersRequest(
            project_id=1,
            main_characters="### 【姓名】：林舟\n【角色定位】：主角",
            world_setting="蒸汽仙侠世界",
            plot_outline="第1章：雨夜入城",
            current_character_count=1,
            target_total_characters=10,
        ),
        current_user=SimpleNamespace(id=99),
        db=fake_db,
    )

    assert captured["scheduled"] is True
    assert captured["task_kwargs"]["legacy_story_analysis"] == result["story_expansion_analysis"]
