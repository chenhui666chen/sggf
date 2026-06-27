from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import app.db.base as db_base
import app.services.character_parser as character_parser
import app.services.vector_sync as vector_sync
import app.services.agents.written_chapters_handler as written_chapters_handler
import backend.app.api.v1.workflow as workflow
import backend.app.api.v1.workflow.routes_status as workflow_status
import backend.app.api.v1.workflow.story_resolve as workflow_story_resolve
import backend.app.services.outline_merger as outline_merger
from app.schemas.story_expansion import StoryExpansionAnalysisPayload


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
        query_text = str(query)
        if "SELECT epic_framework, epic_framework_generated_at, plot_outline, epic_volumes_detail" in query_text:
            return SimpleNamespace(fetchone=lambda: (None, None, None, None))
        return SimpleNamespace(fetchone=lambda: None)

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
        if "SELECT epic_framework, epic_framework_generated_at, plot_outline, epic_volumes_detail" in query_text:
            return SimpleNamespace(fetchone=lambda: (self.epic_framework, self.framework_generated_at, None, ""))
        return SimpleNamespace(fetchone=lambda: None)


class _TaskStatusDBSession(_FakeDBSession):
    def __init__(self, task_row: Any) -> None:
        super().__init__()
        self.task_row = task_row
        self.updated_rows: list[dict[str, Any]] = []

    def execute(self, query: Any, params: Any = None) -> Any:
        self.execute_calls.append((query, params))
        query_text = str(query)
        if "FROM generation_history gh" in query_text and "WHERE gh.task_id = :task_id AND p.user_id = :user_id" in query_text:
            return SimpleNamespace(fetchone=lambda: self.task_row)
        if "UPDATE generation_history" in query_text:
            self.updated_rows.append(dict(params or {}))
            return SimpleNamespace()
        return SimpleNamespace(fetchone=lambda: None)


class _VolumeDetailConfigDBSession(_FakeDBSession):
    def __init__(self, *, epic_framework: str, epic_volumes_detail: str) -> None:
        super().__init__()
        self.epic_framework = epic_framework
        self.epic_volumes_detail = epic_volumes_detail

    def execute(self, query: Any, params: Any = None) -> Any:
        self.execute_calls.append((query, params))
        query_text = str(query)
        if "SELECT epic_framework, epic_framework_generated_at, plot_outline, epic_volumes_detail" in query_text:
            return SimpleNamespace(fetchone=lambda: (self.epic_framework, None, None, self.epic_volumes_detail))
        return SimpleNamespace()


class _StageContentDBSession(_FakeDBSession):
    def __init__(
        self,
        *,
        plot_outline: str,
        epic_volumes_detail: str,
        concept: str = "故事概念",
        world_setting: str = "世界设定",
        characters: str = "### 【姓名】：顾长庚\n【角色定位】：主角",
        chapter_draft: str = "章节初稿",
        review_report: str = "评审报告",
        final_version: str = "终稿",
    ) -> None:
        super().__init__()
        self.stage_row = (
            concept,
            world_setting,
            characters,
            plot_outline,
            epic_volumes_detail,
            chapter_draft,
            review_report,
            final_version,
        )
        self.plot_outline = plot_outline
        self.epic_volumes_detail = epic_volumes_detail

    def execute(self, query: Any, params: Any = None) -> Any:
        self.execute_calls.append((query, params))
        query_text = str(query)
        if "SELECT concept, world_setting, characters, plot_outline," in query_text:
            return SimpleNamespace(fetchone=lambda: self.stage_row)
        if "SELECT plot_outline, epic_volumes_detail" in query_text:
            return SimpleNamespace(fetchone=lambda: (self.plot_outline, self.epic_volumes_detail))
        if "SELECT epic_framework, epic_framework_generated_at, plot_outline, epic_volumes_detail" in query_text:
            return SimpleNamespace(fetchone=lambda: (None, None, self.plot_outline, self.epic_volumes_detail))
        return SimpleNamespace(fetchone=lambda: None)


class _UpdateProjectSettingsDBSession(_FakeDBSession):
    def __init__(
        self,
        *,
        plot_outline: str = "",
        epic_volumes_detail: str = "",
        characters: str = "### 【姓名】：顾长庚\n【角色定位】：主角",
    ) -> None:
        super().__init__()
        self.plot_outline = plot_outline
        self.epic_volumes_detail = epic_volumes_detail
        self.characters = characters
        self.updated_rows: list[dict[str, Any]] = []

    def execute(self, query: Any, params: Any = None) -> Any:
        self.execute_calls.append((query, params))
        query_text = str(query)
        if "SELECT id FROM project_settings WHERE project_id = :project_id" in query_text:
            return SimpleNamespace(fetchone=lambda: (1,))
        if "SELECT characters" in query_text:
            return SimpleNamespace(fetchone=lambda: (self.characters,))
        if "SELECT plot_outline" in query_text and "FROM project_settings" in query_text:
            return SimpleNamespace(fetchone=lambda: (self.plot_outline,))
        if "UPDATE project_settings" in query_text:
            payload = dict(params or {})
            self.updated_rows.append(payload)
            if "plot_outline" in payload:
                self.plot_outline = payload["plot_outline"]
            if "epic_volumes_detail" in payload:
                self.epic_volumes_detail = payload["epic_volumes_detail"]
            if "characters" in payload:
                self.characters = payload["characters"]
            return SimpleNamespace()
        return SimpleNamespace(fetchone=lambda: None)


def _build_volume_detail_text(*, volume_index: int, start: int, end: int) -> str:
    chapter_blocks = "\n\n".join(
        (
            f"### 第{chapter_number}章：《卷{volume_index}章节{chapter_number - start + 1}》\n"
            f"- 场景目标：承接第{chapter_number - 1}章并推进本章矛盾。\n"
            f"- 关键事件：第{chapter_number}章发生关键转折。"
        )
        for chapter_number in range(start, end + 1)
    )
    return (
        "## 一、故事概述\n"
        f"- 承接第{start - 1}章的尾声冲突，展开本卷主线。\n\n"
        f"## 二、第{volume_index}卷详细规划（预计{end - start + 1}章，从第{start}章开始）\n\n"
        f"{chapter_blocks}\n\n"
        "## 三、伏笔埋设检查\n"
        f"- 第{start}-{min(start + 4, end)}章：完成第一轮伏笔铺垫。"
    )


def _build_volume_detail_without_tail(*, volume_index: int, start: int, end: int) -> str:
    chapter_blocks = "\n\n".join(
        (
            f"### 第{chapter_number}章：《卷{volume_index}章节{chapter_number - start + 1}》\n"
            f"- 场景目标：承接第{chapter_number - 1}章并推进本章矛盾。\n"
            f"- 关键事件：第{chapter_number}章发生关键转折。\n"
            f"- 情节作用：完成第{chapter_number}章的阶段推进。\n"
            f"- 结尾钩子：第{chapter_number}章留下下一步行动线索。\n"
            f"- 伏笔事项：第{chapter_number}章埋下后续回收线索。"
        )
        for chapter_number in range(start, end + 1)
    )
    return (
        "## 一、故事概述\n"
        f"- 承接第{start - 1}章的尾声冲突，展开本卷主线。\n\n"
        f"## 二、第{volume_index}卷详细规划（预计{end - start + 1}章，从第{start}章开始）\n\n"
        f"{chapter_blocks}"
    )


def test_legacy_expand_routes_are_removed_from_schema() -> None:
    route_schema_flags = {
        getattr(route, "path", ""): getattr(route, "include_in_schema", None)
        for route in workflow.router.routes
    }

    assert "/api/v1/workflow/expand-outline" not in route_schema_flags
    assert "/api/v1/workflow/expand-characters" not in route_schema_flags
    assert route_schema_flags["/api/v1/workflow/expand-story"] is True
    assert route_schema_flags["/api/v1/workflow/expand-story/analysis"] is True


def test_expand_story_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        workflow.ExpandStoryRequest(
            project_id=1,
            current_outline="第1章：雨夜入城",
            world_setting="蒸汽仙侠世界",
            characters="### 【姓名】：林舟\n【角色定位】：主角",
            target_total_chapters=18,
            unknown_field="deprecated",
        )


def test_story_expansion_analysis_payload_accepts_runtime_model_timeout_fields() -> None:
    payload = StoryExpansionAnalysisPayload.model_validate(
        {
            "execution_mode": "delta",
            "model_plan": {
                "coordinator_planner_model": "qwen3.7-plus",
                "coordinator_writer_model": "deepseek-v4-pro",
                "coordinator_planner_max_tokens": 9879,
                "coordinator_writer_max_tokens": 26857,
                "coordinator_planner_timeout_seconds": 572,
                "coordinator_writer_timeout_seconds": 1701,
                "coordinator_planner_estimated_output_tokens": 8820,
                "coordinator_writer_estimated_output_tokens": 22760,
            },
        }
    )

    assert payload.model_plan is not None
    assert payload.model_plan.coordinator_planner_timeout_seconds == 572
    assert payload.model_plan.coordinator_writer_timeout_seconds == 1701


def test_build_story_execution_task_kwargs_maps_story_request_fields() -> None:
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="第1卷：雨夜入城",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=8,
        current_character_count=3,
        target_total_chapters=120,
        target_total_characters=12,
        strategy="balanced",
        intent="balanced",
        enable_auto_supplement=False,
        expansion_mode="volume_detail",
        target_volume_index=2,
        volume_chapters_min=10,
        volume_chapters_max=12,
        volume_character_increment=2,
        preserve_written_mode="preserve_written",
        reset_epic_framework=True,
    )

    result = workflow._build_story_execution_task_kwargs(
        task_id="expand-story-123",
        request=request,
        user_id=99,
    )

    assert result["task_id"] == "expand-story-123"
    assert result["project_id"] == 1
    assert result["user_id"] == 99
    assert result["strategy"] == "balanced"
    assert result["intent"] == "balanced"
    assert result["expansion_mode"] == "volume_detail"
    assert result["target_volume_index"] == 2
    assert result["volume_chapters_min"] == 10
    assert result["volume_chapters_max"] == 12
    assert result["volume_character_increment"] == 2
    assert result["preserve_written_mode"] == "preserve_written"
    assert result["reset_epic_framework"] is True


@pytest.mark.asyncio
async def test_get_task_status_parses_json_result_payload() -> None:
    fake_db = _TaskStatusDBSession(
        (
            "expand-story-task-1",
            "expand_story",
            "completed",
            json.dumps({"message": "完成", "current_chapter_count": 22}, ensure_ascii=False),
            None,
            "2026-04-25T00:00:00+00:00",
            "2026-04-25T00:05:00+00:00",
        )
    )

    result = await workflow_status.get_task_status(
        "expand-story-task-1",
        current_user=SimpleNamespace(id=1),
        db=fake_db,
    )

    assert result["task_id"] == "expand-story-task-1"
    assert result["status"] == "completed"
    assert result["progress"] == 100
    assert result["result"] == {
        "message": "完成",
        "current_chapter_count": 22,
    }


@pytest.mark.asyncio
async def test_get_task_status_keeps_plain_text_result_when_payload_is_not_json() -> None:
    fake_db = _TaskStatusDBSession(
        (
            "workflow-task-plain",
            "workflow_stage_content",
            "failed",
            "任务执行中断：上游服务无响应",
            "上游超时",
            "2026-04-25T00:00:00+00:00",
            "2026-04-25T00:03:00+00:00",
        )
    )

    result = await workflow_status.get_task_status(
        "workflow-task-plain",
        current_user=SimpleNamespace(id=1),
        db=fake_db,
    )

    assert result["task_id"] == "workflow-task-plain"
    assert result["status"] == "failed"
    assert result["progress"] == 0
    assert result["result"] == "任务执行中断：上游服务无响应"
    assert result["error"] == "上游超时"


@pytest.mark.asyncio
async def test_get_task_status_marks_stale_expand_story_task_as_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _TaskStatusDBSession(
        (
            "expand-story-timeout",
            "expand_story",
            "running",
            None,
            None,
            "2026-04-24T00:00:00+00:00",
            None,
        )
    )
    timeout_now = datetime(2026, 4, 24, 4, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(workflow_status, "utc_now", lambda: timeout_now)
    monkeypatch.setattr(
        workflow_status,
        "WORKFLOW_STATUS_PROCESS_STARTED_AT",
        datetime(2026, 4, 23, 23, 50, tzinfo=timezone.utc),
    )

    result = await workflow_status.get_task_status(
        "expand-story-timeout",
        current_user=SimpleNamespace(id=1),
        db=fake_db,
    )

    assert result["task_id"] == "expand-story-timeout"
    assert result["status"] == "timeout"
    assert result["progress"] == 0
    assert result["error"] == "协同扩展任务超时（运行超过180分钟）"
    assert result["completed_at"] == timeout_now.isoformat()
    assert fake_db.committed is True
    assert fake_db.updated_rows == [
        {
            "task_id": "expand-story-timeout",
            "error": "协同扩展任务超时（运行超过180分钟）",
            "completed_at": timeout_now.isoformat(),
        }
    ]


@pytest.mark.asyncio
async def test_get_task_status_marks_orphaned_expand_story_task_as_failed_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _TaskStatusDBSession(
        (
            "expand-story-orphan",
            "expand_story",
            "running",
            None,
            None,
            "2026-04-27T01:17:36+00:00",
            None,
        )
    )
    interrupted_now = datetime(2026, 4, 27, 3, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(workflow_status, "utc_now", lambda: interrupted_now)
    monkeypatch.setattr(
        workflow_status,
        "WORKFLOW_STATUS_PROCESS_STARTED_AT",
        datetime(2026, 4, 27, 2, 48, 58, tzinfo=timezone.utc),
    )

    result = await workflow_status.get_task_status(
        "expand-story-orphan",
        current_user=SimpleNamespace(id=1),
        db=fake_db,
    )

    assert result["task_id"] == "expand-story-orphan"
    assert result["status"] == "failed"
    assert result["progress"] == 0
    assert result["error"] == "协同扩展任务因服务重启或热重载中断，请重新发起"
    assert result["completed_at"] == interrupted_now.isoformat()
    assert fake_db.committed is True
    assert fake_db.updated_rows == [
        {
            "task_id": "expand-story-orphan",
            "error": "协同扩展任务因服务重启或热重载中断，请重新发起",
            "completed_at": interrupted_now.isoformat(),
        }
    ]


def test_resolve_story_volume_detail_config_estimates_start_chapter_from_framework_summary() -> None:
    fake_db = _VolumeDetailConfigDBSession(
        epic_framework="## 五、分卷规划（共3卷）\n【第1卷】守陵血祭\n- 章节规模：60章\n【第2卷】纸人替死\n- 章节规模：65章",
        epic_volumes_detail=json.dumps(
            {
                "total_volumes": 3,
                "framework_header": "## 故事总纲",
                "framework_footer": "## 关键伏笔",
                "volumes": {
                    "1": {
                        "type": "framework",
                        "title": "守陵血祭",
                        "summary": "- 章节规模：60章\n- 卷定位：开篇起点",
                        "detail": None,
                        "chapters_range": [0, 0],
                        "expanded_at": None,
                    },
                    "2": {
                        "type": "framework",
                        "title": "纸人替死",
                        "summary": "- 章节规模：65章\n- 卷定位：势力展开",
                        "detail": None,
                        "chapters_range": [0, 0],
                        "expanded_at": None,
                    },
                    "3": {
                        "type": "framework",
                        "title": "叛宗道葬",
                        "summary": "- 章节规模：70章\n- 卷定位：首次高潮",
                        "detail": None,
                        "chapters_range": [0, 0],
                        "expanded_at": None,
                    },
                },
            },
            ensure_ascii=False,
        ),
    )
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="## 五、分卷规划（共3卷）",
        world_setting="修仙世界",
        characters="### 【姓名】：苏离\n【角色定位】：主角",
        expansion_mode="volume_detail",
        target_volume_index=2,
        volume_chapters_min=30,
        volume_chapters_max=40,
    )

    config = workflow._resolve_story_volume_detail_config(request, fake_db)

    assert config is not None
    assert config["start_chapter_num"] == 61
    assert config["expected_chapter_range"] == (61, 100)
    assert config["expected_total_chapter_count"] == 100


def test_resolve_story_volume_detail_config_keeps_continuous_numbering_from_existing_volume_detail_text() -> None:
    first_volume_detail = "\n\n".join(
        f"### 第{index}章：卷一章节{index}\n- 场景目标：推进卷一第{index}章。"
        for index in range(1, 61)
    )
    fake_db = _VolumeDetailConfigDBSession(
        epic_framework="## 五、分卷规划（共2卷）\n【第1卷】枯荣复苏\n- 卷定位：宗门重建\n【第2卷】山雨欲来\n- 卷定位：外患压境",
        epic_volumes_detail=json.dumps(
            {
                "total_volumes": 2,
                "framework_header": "## 故事总纲",
                "framework_footer": "## 关键伏笔",
                "volumes": {
                    "1": {
                        "type": "detail",
                        "title": "枯荣复苏",
                        "summary": "- 卷定位：宗门重建",
                        "detail": first_volume_detail,
                        "chapters_range": [0, 0],
                        "expanded_at": None,
                    },
                    "2": {
                        "type": "framework",
                        "title": "山雨欲来",
                        "summary": "- 卷定位：外患压境",
                        "detail": None,
                        "chapters_range": [0, 0],
                        "expanded_at": None,
                    },
                },
            },
            ensure_ascii=False,
        ),
    )
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="## 五、分卷规划（共2卷）",
        world_setting="修仙世界",
        characters="### 【姓名】：顾长歌\n【角色定位】：主角",
        expansion_mode="volume_detail",
        target_volume_index=2,
        volume_chapters_min=40,
        volume_chapters_max=40,
    )

    config = workflow._resolve_story_volume_detail_config(request, fake_db)

    assert config is not None
    assert config["start_chapter_num"] == 61
    assert config["expected_chapter_range"] == (61, 100)
    assert config["current_total_chapter_count"] == 60
    assert config["expected_total_chapter_count"] == 100


def test_resolve_story_volume_detail_config_renumbers_existing_detail_after_previous_volume_changes() -> None:
    first_volume_detail = _build_volume_detail_text(volume_index=1, start=1, end=70)
    second_volume_detail = _build_volume_detail_text(volume_index=2, start=61, end=120)
    fake_db = _VolumeDetailConfigDBSession(
        epic_framework="## 五、分卷规划（共2卷）\n【第1卷】枯荣复苏\n- 卷定位：宗门重建\n【第2卷】山雨欲来\n- 卷定位：外患压境",
        epic_volumes_detail=json.dumps(
            {
                "total_volumes": 2,
                "framework_header": "## 故事总纲",
                "framework_footer": "## 关键伏笔",
                "volumes": {
                    "1": {
                        "type": "detail",
                        "title": "枯荣复苏",
                        "summary": "- 卷定位：宗门重建",
                        "detail": first_volume_detail,
                        "chapters_range": [1, 70],
                        "chapter_count": 70,
                        "expanded_at": None,
                    },
                    "2": {
                        "type": "detail",
                        "title": "山雨欲来",
                        "summary": "- 卷定位：外患压境",
                        "detail": second_volume_detail,
                        "chapters_range": [61, 120],
                        "chapter_count": 60,
                        "expanded_at": None,
                    },
                },
            },
            ensure_ascii=False,
        ),
    )
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="## 五、分卷规划（共2卷）",
        world_setting="修仙世界",
        characters="### 【姓名】：顾长歌\n【角色定位】：主角",
        expansion_mode="volume_detail",
        target_volume_index=2,
        volume_chapters_min=60,
        volume_chapters_max=60,
    )

    config = workflow._resolve_story_volume_detail_config(request, fake_db)

    assert config is not None
    assert config["start_chapter_num"] == 71
    assert config["expected_chapter_range"] == (71, 130)
    assert "### 第71章" in config["existing_volume_detail"]
    assert "### 第61章" not in config["existing_volume_detail"]
    assert "承接第70章" in config["existing_volume_detail"]


def test_merge_volumes_to_outline_recalculates_following_detail_ranges_and_headings() -> None:
    volumes_data = {
        "total_volumes": 2,
        "framework_generated_at": "2026-04-15T00:00:00",
        "framework_header": "## 故事总纲",
        "framework_footer": "## 关键伏笔",
        "volumes": {
            "1": {
                "type": "detail",
                "title": "枯荣复苏",
                "summary": "- 卷定位：宗门重建",
                "detail": _build_volume_detail_text(volume_index=1, start=1, end=70),
                "chapters_range": [1, 70],
                "chapter_count": 70,
                "expanded_at": None,
            },
            "2": {
                "type": "detail",
                "title": "山雨欲来",
                "summary": "- 卷定位：外患压境",
                "detail": _build_volume_detail_text(volume_index=2, start=61, end=120),
                "chapters_range": [61, 120],
                "chapter_count": 60,
                "expanded_at": None,
            },
        },
    }

    merged = outline_merger.merge_volumes_to_outline(volumes_data)

    assert "📖 第2卷详细章节（第71-130章" in merged
    assert "## 二、第2卷详细规划（预计60章，从第71章开始）" in merged
    assert "### 第71章：《卷2章节1》" in merged
    assert "### 第130章：《卷2章节60》" in merged
    assert "### 第61章：《卷2章节1》" not in merged
    assert "承接第70章" in merged


def test_parse_framework_to_volumes_restores_merged_outline_without_losing_following_summaries() -> None:
    volumes_data = {
        "total_volumes": 3,
        "framework_generated_at": "2026-04-15T00:00:00",
        "framework_header": "## 故事总纲\n- 主线：推翻天庄",
        "framework_footer": "## 关键伏笔\n- 倒悬之塔中继站将在后续卷回收",
        "volumes": {
            "1": {
                "type": "framework",
                "title": "锈镇求生",
                "summary": "- 章节规模：1-30章\n- 卷定位：开篇立足\n- 核心目标：活下来",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "2": {
                "type": "detail",
                "title": "黑狱逃生",
                "summary": "- 章节规模：31-60章\n- 卷定位：突破黑狱\n- 核心目标：逃出生天",
                "detail": _build_volume_detail_text(volume_index=2, start=31, end=60),
                "chapters_range": [31, 60],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "3": {
                "type": "framework",
                "title": "万法潜行",
                "summary": "- 章节规模：61-90章\n- 卷定位：潜入万法城\n- 核心目标：夺取节点",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
        },
    }

    merged = outline_merger.merge_volumes_to_outline(volumes_data)
    reparsed = outline_merger.parse_framework_to_volumes(merged, 3)

    assert reparsed["framework_header"] == "## 故事总纲\n- 主线：推翻天庄"
    assert reparsed["framework_footer"] == "## 关键伏笔\n- 倒悬之塔中继站将在后续卷回收"
    assert reparsed["volumes"]["1"]["summary"] == "- 章节规模：1-30章\n- 卷定位：开篇立足\n- 核心目标：活下来"
    assert reparsed["volumes"]["2"]["type"] == "detail"
    assert reparsed["volumes"]["2"]["chapters_range"] == [31, 60]
    assert "## 二、第2卷详细规划（预计30章，从第31章开始）" in reparsed["volumes"]["2"]["detail"]
    assert reparsed["volumes"]["3"]["summary"] == "- 章节规模：61-90章\n- 卷定位：潜入万法城\n- 核心目标：夺取节点"


def test_merge_volumes_to_outline_repairs_legacy_detail_tail_sections_and_collapses_details() -> None:
    volumes_data = {
        "total_volumes": 3,
        "framework_generated_at": "2026-04-27T00:00:00",
        "framework_header": "## 故事总纲",
        "framework_footer": "## 关键伏笔",
        "volumes": {
            "1": {
                "type": "detail",
                "title": "锈镇求生",
                "summary": "- 章节规模：1-30章\n- 卷定位：开篇立足",
                "detail": _build_volume_detail_without_tail(volume_index=1, start=1, end=30),
                "chapters_range": [1, 30],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "2": {
                "type": "framework",
                "title": "黑狱突围",
                "summary": "- 章节规模：31-60章\n- 卷定位：突破黑狱",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "3": {
                "type": "framework",
                "title": "万法潜行",
                "summary": "- 章节规模：61-90章\n- 卷定位：潜入万法城",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
        },
    }

    merged = outline_merger.merge_volumes_to_outline(volumes_data)

    assert "<details>" in merged
    assert "<details open>" not in merged
    assert "## 三、伏笔埋设检查" in merged
    assert "## 四、卷尾衔接检查" in merged
    assert "✅ 下卷开局场景：" in merged
    assert "### 【第2卷】《黑狱突围》" in merged
    assert "### 【第3卷】《万法潜行》" in merged


def test_load_epic_framework_state_rebuilds_plot_outline_from_epic_volumes_detail() -> None:
    from app.services.workflow_context_builder import WorkflowContextBuilder

    volumes_data = {
        "total_volumes": 3,
        "framework_generated_at": "2026-04-27T00:00:00",
        "framework_header": "## 故事总纲\n- 主线：推翻天庄",
        "framework_footer": "## 关键伏笔\n- 倒悬之塔将在后续卷回收",
        "volumes": {
            "1": {
                "type": "detail",
                "title": "锈镇求生",
                "summary": "- 章节规模：1-30章\n- 卷定位：开篇立足",
                "detail": _build_volume_detail_without_tail(volume_index=1, start=1, end=30),
                "chapters_range": [1, 30],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "2": {
                "type": "framework",
                "title": "黑狱突围",
                "summary": "- 章节规模：31-60章\n- 卷定位：突破黑狱",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "3": {
                "type": "framework",
                "title": "万法潜行",
                "summary": "- 章节规模：61-90章\n- 卷定位：潜入万法城",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
        },
    }
    fake_db = _VolumeDetailConfigDBSession(
        epic_framework="## 五、分卷规划（共3卷）\n### 【第1卷】《旧文本》",
        epic_volumes_detail=json.dumps(volumes_data, ensure_ascii=False),
    )

    state = WorkflowContextBuilder(fake_db).load_epic_framework_state(1)

    assert "### 【第2卷】《黑狱突围》" in state.plot_outline
    assert "### 【第3卷】《万法潜行》" in state.plot_outline
    assert "## 三、伏笔埋设检查" in state.plot_outline
    assert "## 四、卷尾衔接检查" in state.plot_outline
    assert "<details open>" not in state.plot_outline


def test_load_stage_contents_snapshot_rebuilds_plot_outline_from_epic_volumes_detail() -> None:
    from app.services.workflow_context_builder import WorkflowContextBuilder

    volumes_data = {
        "total_volumes": 3,
        "framework_generated_at": "2026-04-27T00:00:00",
        "framework_header": "## 故事总纲\n- 主线：推翻天庄",
        "framework_footer": "## 关键伏笔\n- 倒悬之塔将在后续卷回收",
        "volumes": {
            "1": {
                "type": "detail",
                "title": "锈镇求生",
                "summary": "- 章节规模：1-30章\n- 卷定位：开篇立足",
                "detail": _build_volume_detail_without_tail(volume_index=1, start=1, end=30),
                "chapters_range": [1, 30],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "2": {
                "type": "framework",
                "title": "黑狱突围",
                "summary": "- 章节规模：31-60章\n- 卷定位：突破黑狱",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "3": {
                "type": "framework",
                "title": "万法潜行",
                "summary": "- 章节规模：61-90章\n- 卷定位：潜入万法城",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
        },
    }
    fake_db = _StageContentDBSession(
        plot_outline="### 【第1卷】《旧文本》\n<details open>",
        epic_volumes_detail=json.dumps(volumes_data, ensure_ascii=False),
    )

    snapshot = WorkflowContextBuilder(fake_db).load_stage_contents_snapshot(1, pretty_json=True)

    assert "### 【第2卷】《黑狱突围》" in snapshot["plot_outline"]
    assert "### 【第3卷】《万法潜行》" in snapshot["plot_outline"]
    assert "## 三、伏笔埋设检查" in snapshot["plot_outline"]
    assert "## 四、卷尾衔接检查" in snapshot["plot_outline"]
    assert "<details open>" not in snapshot["plot_outline"]


def test_read_stage_content_returns_rebuilt_plot_outline_for_structure_stage() -> None:
    from app.services.workflow_context_builder import WorkflowContextBuilder

    volumes_data = {
        "total_volumes": 2,
        "framework_generated_at": "2026-04-27T00:00:00",
        "framework_header": "## 故事总纲",
        "framework_footer": "## 关键伏笔",
        "volumes": {
            "1": {
                "type": "detail",
                "title": "锈镇求生",
                "summary": "- 章节规模：1-30章\n- 卷定位：开篇立足",
                "detail": _build_volume_detail_without_tail(volume_index=1, start=1, end=30),
                "chapters_range": [1, 30],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "2": {
                "type": "framework",
                "title": "黑狱突围",
                "summary": "- 章节规模：31-60章\n- 卷定位：突破黑狱",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
        },
    }
    fake_db = _StageContentDBSession(
        plot_outline="### 【第1卷】《旧文本》\n<details open>",
        epic_volumes_detail=json.dumps(volumes_data, ensure_ascii=False),
    )

    content = WorkflowContextBuilder(fake_db).read_stage_content(1, "structure", pretty_json=True)

    assert "### 【第2卷】《黑狱突围》" in content
    assert "## 三、伏笔埋设检查" in content
    assert "## 四、卷尾衔接检查" in content
    assert "<details open>" not in content


def test_update_project_settings_fields_preserves_merged_plot_outline_when_only_plot_outline_is_written() -> None:
    from app.services.workflow_context_builder import WorkflowContextBuilder

    volumes_data = {
        "total_volumes": 2,
        "framework_generated_at": "2026-04-27T00:00:00",
        "framework_header": "## 故事总纲",
        "framework_footer": "## 关键伏笔",
        "volumes": {
            "1": {
                "type": "detail",
                "title": "锈镇求生",
                "summary": "- 章节规模：1-30章\n- 卷定位：开篇立足",
                "detail": _build_volume_detail_without_tail(volume_index=1, start=1, end=30),
                "chapters_range": [1, 30],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "2": {
                "type": "framework",
                "title": "黑狱突围",
                "summary": "- 章节规模：31-60章\n- 卷定位：突破黑狱",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
        },
    }
    merged_outline = outline_merger.merge_volumes_to_outline(volumes_data)
    fake_db = _UpdateProjectSettingsDBSession()

    WorkflowContextBuilder(fake_db).update_project_settings_fields(
        1,
        plot_outline=merged_outline,
    )

    assert fake_db.committed is True
    assert len(fake_db.updated_rows) == 1
    persisted_plot_outline = fake_db.updated_rows[0]["plot_outline"]
    assert persisted_plot_outline == merged_outline
    assert "<details>" in persisted_plot_outline
    assert "<details open>" not in persisted_plot_outline
    assert "### 【第2卷】《黑狱突围》" in persisted_plot_outline


def test_update_project_settings_fields_rebuilds_plot_outline_from_epic_volumes_detail_on_write() -> None:
    from app.services.workflow_context_builder import WorkflowContextBuilder

    volumes_data = {
        "total_volumes": 3,
        "framework_generated_at": "2026-04-27T00:00:00",
        "framework_header": "## 故事总纲\n- 主线：推翻天庄",
        "framework_footer": "## 关键伏笔\n- 倒悬之塔将在后续卷回收",
        "volumes": {
            "1": {
                "type": "detail",
                "title": "锈镇求生",
                "summary": "- 章节规模：1-30章\n- 卷定位：开篇立足",
                "detail": _build_volume_detail_without_tail(volume_index=1, start=1, end=30),
                "chapters_range": [1, 30],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "2": {
                "type": "framework",
                "title": "黑狱突围",
                "summary": "- 章节规模：31-60章\n- 卷定位：突破黑狱",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
            "3": {
                "type": "framework",
                "title": "万法潜行",
                "summary": "- 章节规模：61-90章\n- 卷定位：潜入万法城",
                "detail": None,
                "chapters_range": [0, 0],
                "chapter_count": 30,
                "expanded_at": None,
            },
        },
    }
    fake_db = _UpdateProjectSettingsDBSession(
        plot_outline="### 【第1卷】《旧文本》\n<details open>",
    )

    WorkflowContextBuilder(fake_db).update_project_settings_fields(
        1,
        plot_outline="### 【第1卷】《旧文本》\n<details open>",
        epic_volumes_detail=json.dumps(volumes_data, ensure_ascii=False),
    )

    assert fake_db.committed is True
    assert len(fake_db.updated_rows) == 1
    persisted_plot_outline = fake_db.updated_rows[0]["plot_outline"]
    persisted_epic_volumes_detail = fake_db.updated_rows[0]["epic_volumes_detail"]
    assert "### 【第2卷】《黑狱突围》" in persisted_plot_outline
    assert "### 【第3卷】《万法潜行》" in persisted_plot_outline
    assert "## 三、伏笔埋设检查" in persisted_plot_outline
    assert "## 四、卷尾衔接检查" in persisted_plot_outline
    assert "<details open>" not in persisted_plot_outline
    persisted_volumes = json.loads(persisted_epic_volumes_detail)
    persisted_detail = persisted_volumes["volumes"]["1"]["detail"]
    assert "## 三、伏笔埋设检查" in persisted_detail
    assert "## 四、卷尾衔接检查" in persisted_detail


def test_validate_expand_story_request_accepts_layered_epic_framework_thresholds() -> None:
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="第1章：雨夜入城",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=12,
        current_character_count=3,
        expansion_mode="epic_framework",
        total_volumes=3,
        total_chapters_min=300,
        total_chapters_max=900,
    )

    workflow._validate_expand_story_request(request)


def test_validate_expand_story_request_rejects_total_mode_beyond_conventional_total_ceiling() -> None:
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="第1章：雨夜入城",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=20,
        current_character_count=3,
        target_total_chapters=601,
        expansion_mode="total",
    )

    with pytest.raises(workflow.HTTPException) as exc_info:
        workflow._validate_expand_story_request(request)

    assert exc_info.value.detail == "常规协同仅支持总规模不超过 600 个细化章节；451 章起建议优先改用长篇框架协同，超过 600 章后必须切换。"


def test_validate_expand_story_request_rejects_total_mode_when_current_scale_already_exceeds_ceiling() -> None:
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="第1章：雨夜入城",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=620,
        current_character_count=12,
        target_total_characters=15,
        expansion_mode="total",
    )

    with pytest.raises(workflow.HTTPException) as exc_info:
        workflow._validate_expand_story_request(request)

    assert exc_info.value.detail == "常规协同仅支持总规模不超过 600 个细化章节；451 章起建议优先改用长篇框架协同，超过 600 章后必须切换。"


def test_validate_expand_story_request_accepts_20_chapter_volume_detail_lower_bound() -> None:
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="## 分卷概要",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=60,
        current_character_count=8,
        expansion_mode="volume_detail",
        target_volume_index=2,
        volume_chapters_min=20,
        volume_chapters_max=40,
    )

    workflow._validate_expand_story_request(request)


def test_validate_expand_story_request_accepts_120_chapter_volume_detail_upper_bound() -> None:
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="## 分卷概要",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=180,
        current_character_count=12,
        expansion_mode="volume_detail",
        target_volume_index=4,
        volume_chapters_min=60,
        volume_chapters_max=120,
    )

    workflow._validate_expand_story_request(request)


def test_validate_expand_story_request_rejects_volume_detail_above_120_chapters() -> None:
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="## 分卷概要",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=180,
        current_character_count=12,
        expansion_mode="volume_detail",
        target_volume_index=4,
        volume_chapters_min=60,
        volume_chapters_max=121,
    )

    with pytest.raises(workflow.HTTPException) as exc_info:
        workflow._validate_expand_story_request(request)

    assert exc_info.value.detail == "单卷细化协同需要有效的本卷章节范围 (20-120)"


def test_select_text_model_by_input_tokens_uses_dynamic_model_budget() -> None:
    safe_budget = workflow._get_safe_input_token_budget("qwen3.7-plus")

    assert safe_budget > 10000
    assert workflow._select_text_model_by_input_tokens(safe_budget - 1)[0] == "qwen3.7-plus"
    assert workflow._select_text_model_by_input_tokens(safe_budget + 1)[0] == "qwen3.7-plus"


@pytest.mark.parametrize(
    ("concept_text", "expected_title"),
    [
        (
            "2. **日志标题（短标题）**：《长夜引星》\n3. **一句话卖点**：命星重燃。",
            "长夜引星",
        ),
        (
            "**2. 日志标题（短标题）**：  \n道骸纪\n\n**3. 概念摘要（80–150字）**：  \n守墓人逆命而行。",
            "道骸纪",
        ),
        (
            "2. **日志标题（短标题）**：\n《万火归墟》\n3. **一句话卖点**：旧神复苏。",
            "万火归墟",
        ),
        (
            "项目标题：云海铸剑录\n一句话卖点：少年登天。",
            "云海铸剑录",
        ),
    ],
)
def test_extract_project_title_from_concept_supports_inline_and_multiline_formats(
    concept_text: str,
    expected_title: str,
) -> None:
    assert workflow._extract_project_title_from_concept(concept_text) == expected_title


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


def test_build_story_written_chapter_preview_merges_existing_outline_with_written_context() -> None:
    class _PreviewResult:
        def __init__(self, rows: list[tuple[Any, ...]]) -> None:
            self._rows = list(rows)

        def fetchall(self) -> list[tuple[Any, ...]]:
            return list(self._rows)

    class _PreviewDB:
        def __init__(self, rows: list[tuple[Any, ...]]) -> None:
            self._rows = list(rows)

        def execute(self, query: Any, params: Any = None) -> _PreviewResult:
            return _PreviewResult(self._rows)

    preview = workflow._build_story_written_chapter_preview(
        workflow.ExpandStoryRequest(
            project_id=1,
            current_outline="旧大纲\n第1章：雨夜入城\n第22章：风雪夜归",
            world_setting="蒸汽仙侠世界",
            characters="### 【姓名】：林舟\n【角色定位】：主角",
            current_chapter_count=22,
            target_total_chapters=60,
            preserve_written_mode="extract_extend",
        ),
        _PreviewDB(
            [
                (
                    1,
                    "雨夜入城",
                    "正文片段不应直接覆盖原始大纲",
                    "",
                    json.dumps(
                        {
                            "scene_goal": "主角入城并观察局势",
                            "key_events": ["抵达青石城", "察觉有人跟踪"],
                            "ending_hook": {"content": "巷口出现陌生纸灯"},
                        },
                        ensure_ascii=False,
                    ),
                )
            ]
        ),
    )

    assert preview["applied"] is True
    assert preview["effective_current_chapter_count"] == 22
    assert "旧大纲" in preview["effective_outline"]
    assert "已写章节摘要预览" in preview["effective_outline"]
    assert "主角入城并观察局势" in preview["effective_outline"]


@pytest.mark.asyncio
async def test_prepare_story_execution_request_keeps_larger_outline_chapter_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = workflow.ExpandStoryRequest(
        project_id=1,
        current_outline="旧大纲\n第1章：雨夜入城\n第22章：风雪夜归",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=22,
        current_character_count=3,
        target_total_chapters=60,
        preserve_written_mode="extract_extend",
    )

    def fake_preview(_: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        return {
            "effective_outline": "旧大纲\n\n【已写章节摘要预览（用于连续性约束）】\n第1章：已写开场",
            "effective_current_chapter_count": 22,
            "written_chapter_count": 1,
            "written_outline_context": "第1章：已写开场\n- 已写摘要：主角入城。",
            "warnings": ["检测到已写正文，预检阶段先按摘要预览。"],
            "applied": True,
        }

    async def fake_process_written_chapters(**kwargs: Any) -> tuple[int, str]:
        return 1, "### 第1章：已写开场\n- 场景目标：主角入城并观察局势。"

    monkeypatch.setattr(workflow_story_resolve, "_build_story_written_chapter_preview", fake_preview)
    monkeypatch.setattr(workflow_story_resolve, "_build_project_world_setting_context", lambda *args, **kwargs: "蒸汽仙侠世界")
    monkeypatch.setattr(
        workflow_story_resolve,
        "_create_project_outline_expander",
        lambda *args, **kwargs: {"expander": SimpleNamespace(llm=object()), "genre": "修仙"},
    )
    monkeypatch.setattr(written_chapters_handler, "process_written_chapters", fake_process_written_chapters)

    result = await workflow_story_resolve._prepare_story_execution_request(request, _FakeDBSession())

    prepared_request = result["request"]
    assert prepared_request.current_chapter_count == 22
    assert "旧大纲" in prepared_request.current_outline
    assert "已写章节提炼细纲" in prepared_request.current_outline
    assert "### 已写章节 1：已写开场" in prepared_request.current_outline


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
        "auto_supplement": {
            "character_delta": 3,
            "character_plan": {
                "stage_target_characters": 5,
                "task_target_characters": 8,
                "task_target_increment": 6,
            },
        },
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
                "outline_delta": "第2章：旧案浮现\n- 主要内容：顾晚加入调查。",
                "character_delta": "### 【姓名】：顾晚\n【角色定位】：盟友",
                "character_relationships": "- 林舟 ↔ 顾晚：盟友（共同调查旧案）",
                "outline_ops": [{"round": 1, "mode": "iterative"}],
                "execution_mode": "iterative",
                "execution_mode_reason": "超出单轮阈值，改为分轮协同。",
                "execution_rounds": [{"round": 1, "mode": "iterative"}],
                "new_characters": ["顾晚"],
                "strategy": "plot_first",
                "coordination_summary": "已按分轮协同完成本轮扩展。",
                "plan": {
                    "target_chapter_count": 20,
                    "target_character_count": 8,
                },
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
    assert captured["execute_kwargs"]["auto_supplement_plan"]["character_delta"] == analysis["auto_supplement"]["character_delta"]
    assert captured["execute_kwargs"]["auto_supplement_plan"]["character_plan"] == analysis["auto_supplement"]["character_plan"]
    assert len(complete_events) == 1
    history_updates = [
        params
        for query, params in fake_db.execute_calls
        if "UPDATE generation_history" in str(query)
    ]
    assert any(
        params["status"] == "completed" and "顾晚" in (params["result"] or "")
        for params in history_updates
    )

    result = complete_events[0]["result"]
    assert result["story_intent"] == "outline_led"
    assert result["story_expansion_mode"] == "total"
    assert result["story_strategy"] == "plot_first"
    assert result["target_chapter_count"] == 20
    assert result["target_character_count"] == 8
    assert result["execution_mode"] == "iterative"
    assert result["expansion_analysis"]["effective_target_character_count"] == analysis["effective_target_character_count"]
    assert result["expansion_analysis"]["auto_supplement"]["character_plan"] == analysis["auto_supplement"]["character_plan"]
    assert result["character_sync"]["relationships"]["saved"] == 1
    assert result["completion_status"] == "partial"
    assert result["goal_reached"] is False
    assert result["message"].startswith("⚠️ 协同拓展已阶段性完成")
    project_settings_updates = [
        params
        for query, params in fake_db.execute_calls
        if "UPDATE project_settings" in str(query)
    ]
    assert any(params["project_id"] == 1 for params in project_settings_updates)


@pytest.mark.asyncio
async def test_execute_expand_story_task_reconciles_final_counts_from_result_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    complete_events: list[dict[str, Any]] = []

    analysis = {
        "effective_target_chapter_count": 100,
        "effective_target_character_count": 20,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "total",
        "execution_mode": "iterative",
        "execution_mode_reason": "分轮协同。",
        "warnings": [],
    }

    loose_characters = """### 顾晚
角色定位：情报盟友
背景故事：长期潜伏于青石城情报网。

姓名：沈砚
故事立场：对手阵营
角色定位：审讯官
关键关系：与顾晚互相试探。"""

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "plot_outline": "\n\n".join(
                    f"第{index}章：章节{index}\n- 主要内容：推进第{index}章剧情。"
                    for index in range(1, 17)
                ),
                "characters": loose_characters,
                "execution_mode": "iterative",
                "execution_mode_reason": "分轮协同。",
                "execution_rounds": [],
                "strategy": "plot_first",
                "coordination_summary": "分轮协同已执行完当前可安全推进的部分。",
                "current_chapter_count": 0,
                "current_character_count": 0,
                "validation_before": {"chapter_count": 0, "character_count": 0},
                "validation_after": {"chapter_count": 0, "character_count": 0},
                "stop_reasons": ["人物扩展未产生新增内容，为避免空转已提前停止。"],
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

    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", lambda **kwargs: {"parsed": 2, "created": 2, "updated": 0, "skipped": 0})
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-count-reconcile",
        project_id=1,
        user_id=99,
        current_outline="",
        world_setting="蒸汽仙侠世界",
        characters="",
        current_chapter_count=0,
        current_character_count=0,
        target_total_chapters=100,
        target_total_characters=20,
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

    result = complete_events[0]["result"]
    assert result["current_chapter_count"] == 16
    assert result["current_character_count"] == 2
    assert result["message"].startswith("⚠️ 协同拓展已阶段性完成")
    assert "人物 0 → 2" in result["message"]


@pytest.mark.asyncio
async def test_execute_expand_story_task_marks_partial_completion_when_goal_not_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    complete_events: list[dict[str, Any]] = []

    analysis = {
        "effective_target_chapter_count": 20,
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
            return {
                "plot_outline": "\n\n".join(
                    f"第{index}章：章节{index}\n- 主要内容：推进第{index}章剧情。"
                    for index in range(1, 13)
                ),
                "characters": "### 【姓名】：林舟\n【角色定位】：主角",
                "execution_mode": "delta",
                "execution_mode_reason": "单轮协同。",
                "execution_rounds": [],
                "strategy": "plot_first",
                "coordination_summary": "已完成单轮扩展。",
                "current_chapter_count": 12,
                "current_character_count": 1,
                "validation_before": {"chapter_count": 8, "character_count": 1},
                "validation_after": {"chapter_count": 12, "character_count": 1},
                "stop_reasons": [],
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
        task_id="expand-story-partial",
        project_id=1,
        user_id=99,
        current_outline="\n\n".join(
            f"第{index}章：旧章节{index}\n- 主要内容：旧剧情。"
            for index in range(1, 9)
        ),
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=8,
        current_character_count=1,
        target_total_chapters=20,
        target_total_characters=4,
        strategy="auto",
        intent="auto",
        enable_auto_supplement=False,
        expansion_mode="total",
        total_volumes=None,
        total_chapters_min=None,
        total_chapters_max=None,
        target_volume_index=None,
        volume_chapters_min=None,
        volume_chapters_max=None,
        preserve_written_mode="extract_extend",
    )

    result = complete_events[0]["result"]
    assert result["completion_status"] == "partial"
    assert result["goal_reached"] is False
    assert result["stop_reasons"] == [
        "章节尚差 8 章，需继续发起下一次协同。",
        "人物尚差 3 人，需继续发起下一次协同。",
    ]
    assert "本次协同已完成当前可确认增量" in result["coordination_summary"]
    assert result["message"].startswith("⚠️ 协同拓展已阶段性完成")


@pytest.mark.asyncio
async def test_execute_expand_story_task_reconciles_initial_counts_for_completion_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    complete_events: list[dict[str, Any]] = []

    analysis = {
        "effective_target_chapter_count": 22,
        "effective_target_character_count": 19,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "total",
        "execution_mode": "delta",
        "execution_mode_reason": "单轮协同。",
        "warnings": [],
    }

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "plot_outline": "\n\n".join(
                    f"第{index}章：章节{index}\n- 主要内容：推进第{index}章剧情。"
                    for index in range(1, 23)
                ),
                "characters": "### 【姓名】：林舟\n【角色定位】：主角",
                "execution_mode": "delta",
                "execution_mode_reason": "单轮协同。",
                "execution_rounds": [],
                "strategy": "plot_first",
                "coordination_summary": "已完成单轮扩展。",
                "current_chapter_count": 22,
                "current_character_count": 19,
                "validation_before": {"chapter_count": 1, "character_count": 1},
                "validation_after": {"chapter_count": 22, "character_count": 19},
                "stop_reasons": [],
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
        task_id="expand-story-initial-count-message",
        project_id=1,
        user_id=99,
        current_outline="第1章：旧开场\n- 主要内容：旧剧情。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=20,
        current_character_count=18,
        target_total_chapters=22,
        target_total_characters=19,
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

    result = complete_events[0]["result"]
    assert result["message"] == "✅ 协同拓展完成！章节 20 → 22，人物 18 → 19"


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
                "outline_ops": [{"round": 1, "mode": "delta"}],
                "execution_mode": "delta",
                "execution_mode_reason": "单轮协同。",
                "execution_rounds": [{"round": 1, "mode": "delta"}],
                "strategy": "plot_first",
                "coordination_summary": "已完成扩展。",
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
                "outline_ops": [{"stage": "epic_framework"}],
                "execution_mode": "epic",
                "execution_mode_reason": "已显式选择长篇框架协同。",
                "execution_rounds": [{"stage": "epic_framework"}],
                "strategy": "plot_first",
                "coordination_summary": "已生成长篇框架。",
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
                "outline_delta": "第21章：新卷开场",
                "outline_ops": [{"stage": "volume_detail"}],
                "execution_mode": "volume_detail",
                "execution_mode_reason": "已显式选择单卷细化协同。",
                "execution_rounds": [{"stage": "volume_detail"}],
                "strategy": "plot_first",
                "coordination_summary": "已细化第2卷。",
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
                "outline_delta": "第1章：重建主线\n- 主要内容：以常规章节结构重建故事。",
                "character_delta": "### 【姓名】：顾晚\n【角色定位】：盟友",
                "character_relationships": "- 林舟 -> 顾晚：盟友（共同推进新主线）",
                "outline_ops": [{"round": 1, "mode": "iterative"}],
                "execution_mode": "iterative",
                "execution_mode_reason": "常规协同执行",
                "execution_rounds": [{"round": 1, "mode": "iterative"}],
                "new_characters": ["顾晚"],
                "strategy": "plot_first",
                "coordination_summary": "已切回常规协同并完成本轮补强。",
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


def test_build_project_world_setting_context_appends_settings_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow.WorkflowContextBuilder,
        "build_world_setting_context",
        lambda self, project_id, world_setting: SimpleNamespace(
            combined_world_setting=f"{world_setting}\n\n【设定摘要】门派体系稳定。"
        ),
    )

    result = workflow._build_project_world_setting_context(
        project_id=1,
        world_setting="蒸汽仙侠世界",
        db=_FakeDBSession(),
    )

    assert result == "蒸汽仙侠世界\n\n【设定摘要】门派体系稳定。"


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
    history_inserts = [
        params
        for query, params in fake_db.execute_calls
        if "INSERT INTO generation_history" in str(query)
    ]
    assert len(history_inserts) == 1
    assert history_inserts[0]["project_id"] == 1
    assert history_inserts[0]["task_type"] == "expand_story"
    assert history_inserts[0]["status"] == "running"


@pytest.mark.asyncio
async def test_execute_expand_story_task_updates_generation_history_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    error_events: list[dict[str, Any]] = []

    async def fake_prepare_story_execution_request(
        request: workflow.ExpandStoryRequest,
        db: Any,
    ) -> dict[str, Any]:
        return {
            "request": request,
            "warnings": [],
            "applied": False,
            "written_chapter_count": 0,
        }

    def fake_build_story_expansion_analysis(*, request: workflow.ExpandStoryRequest, db: Any) -> dict[str, Any]:
        raise RuntimeError("analysis exploded")

    async def fake_send_task_progress(**kwargs: Any) -> None:
        return None

    async def fake_send_task_complete(**kwargs: Any) -> None:
        raise AssertionError("should not send completion event on failure")

    async def fake_send_task_error(**kwargs: Any) -> None:
        error_events.append(kwargs)

    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(workflow, "_prepare_story_execution_request", fake_prepare_story_execution_request)
    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-test-failed",
        project_id=1,
        user_id=99,
        current_outline="第1章：雨夜入城",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=1,
        current_character_count=1,
        target_total_chapters=8,
        target_total_characters=2,
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

    assert len(error_events) == 1
    history_updates = [
        params
        for query, params in fake_db.execute_calls
        if "UPDATE generation_history" in str(query)
    ]
    assert any(
        params["status"] == "failed" and params["error"] == "analysis exploded"
        for params in history_updates
    )
    assert fake_db.closed is True


def test_vector_sync_sync_to_vector_db_uses_module_logger_without_name_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str, str, dict[str, Any]]] = []

    class _FakeKB:
        def add_world_setting(self, name: str, content: str, metadata: dict[str, Any]) -> None:
            captured.append(("world", name, content, metadata))

    monkeypatch.setattr(vector_sync, "get_vector_kb", lambda: _FakeKB())

    vector_sync.sync_to_vector_db(
        kb_type="world",
        name="蒸汽仙侠世界",
        content="旧神遗迹与三大宗门并存。",
        metadata={"project_id": "22"},
    )

    assert captured == [
        ("world", "蒸汽仙侠世界", "旧神遗迹与三大宗门并存。", {"project_id": "22"}),
    ]


def test_normalize_story_character_sync_result_strips_extra_fields_and_promotes_total_to_parsed() -> None:
    normalized, warnings = workflow._normalize_story_character_sync_result(
        {
            "parsed": None,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": ["未能解析出任何人物卡"],
            "total": 0,
        }
    )

    assert normalized == {
        "parsed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
    }
    assert warnings == ["未能解析出任何人物卡"]


@pytest.mark.asyncio
async def test_execute_expand_story_task_prefers_character_delta_for_character_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}
    complete_events: list[dict[str, Any]] = []

    analysis = {
        "effective_target_chapter_count": 12,
        "effective_target_character_count": 2,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "total",
        "execution_mode": "delta",
        "execution_mode_reason": "单轮协同。",
        "warnings": [],
    }

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "plot_outline": "第1章：雨夜入城\n- 主要内容：主角抵达青石城。\n\n第2章：旧案浮现\n- 主要内容：顾晚加入调查。",
                "characters": "### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
                "character_delta": "### 【姓名】：顾晚\n【角色定位】：盟友",
                "execution_mode": "delta",
                "execution_mode_reason": "单轮协同。",
                "execution_rounds": [],
                "strategy": "plot_first",
                "coordination_summary": "已完成单轮扩展。",
                "current_chapter_count": 12,
                "current_character_count": 2,
                "validation_before": {"chapter_count": 8, "character_count": 1},
                "validation_after": {"chapter_count": 12, "character_count": 2},
                "stop_reasons": ["达到当前目标"],
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

    def fake_parse_and_sync_characters(**kwargs: Any) -> dict[str, Any]:
        captured["characters_text"] = kwargs["characters_text"]
        return {"parsed": 1, "created": 1, "updated": 0, "skipped": 0}

    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", fake_parse_and_sync_characters)
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-character-sync-extra",
        project_id=1,
        user_id=99,
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=8,
        current_character_count=1,
        target_total_chapters=12,
        target_total_characters=2,
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

    result = complete_events[0]["result"]
    assert captured["characters_text"] == "### 【姓名】：顾晚\n【角色定位】：盟友"
    assert result["character_sync"] == {
        "parsed": 1,
        "created": 1,
        "updated": 0,
        "skipped": 0,
    }
    assert "未能解析出任何人物卡" not in result["alignment_warnings"]


@pytest.mark.asyncio
async def test_execute_expand_story_task_prefers_loose_character_delta_for_character_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}
    complete_events: list[dict[str, Any]] = []

    analysis = {
        "effective_target_chapter_count": 12,
        "effective_target_character_count": 2,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "total",
        "execution_mode": "delta",
        "execution_mode_reason": "单轮协同。",
        "warnings": [],
    }

    loose_delta = "### 顾晚\n角色定位：情报盟友\n背景故事：长期潜伏于青石城情报网。"

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "plot_outline": "第1章：雨夜入城\n- 主要内容：主角抵达青石城。\n\n第2章：旧案浮现\n- 主要内容：顾晚加入调查。",
                "characters": "### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友",
                "character_delta": loose_delta,
                "execution_mode": "delta",
                "execution_mode_reason": "单轮协同。",
                "execution_rounds": [],
                "strategy": "plot_first",
                "coordination_summary": "已完成单轮扩展。",
                "current_chapter_count": 12,
                "current_character_count": 2,
                "validation_before": {"chapter_count": 8, "character_count": 1},
                "validation_after": {"chapter_count": 12, "character_count": 2},
                "stop_reasons": ["达到当前目标"],
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

    def fake_parse_and_sync_characters(**kwargs: Any) -> dict[str, Any]:
        captured["characters_text"] = kwargs["characters_text"]
        return {"parsed": 1, "created": 1, "updated": 0, "skipped": 0}

    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", fake_parse_and_sync_characters)
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-character-sync-loose-delta",
        project_id=1,
        user_id=99,
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=8,
        current_character_count=1,
        target_total_chapters=12,
        target_total_characters=2,
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

    result = complete_events[0]["result"]
    assert captured["characters_text"] == loose_delta
    assert result["character_sync"] == {
        "parsed": 1,
        "created": 1,
        "updated": 0,
        "skipped": 0,
    }


@pytest.mark.asyncio
async def test_execute_expand_story_task_falls_back_to_full_characters_when_delta_not_parseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    captured: dict[str, Any] = {}
    complete_events: list[dict[str, Any]] = []

    analysis = {
        "effective_target_chapter_count": 12,
        "effective_target_character_count": 2,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "total",
        "execution_mode": "delta",
        "execution_mode_reason": "单轮协同。",
        "warnings": [],
    }

    full_characters = "### 【姓名】：林舟\n【角色定位】：主角\n\n### 【姓名】：顾晚\n【角色定位】：盟友"

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "plot_outline": "第1章：雨夜入城\n- 主要内容：主角抵达青石城。\n\n第2章：旧案浮现\n- 主要内容：顾晚加入调查。",
                "characters": full_characters,
                "character_delta": "本轮未新增结构化人物卡",
                "execution_mode": "delta",
                "execution_mode_reason": "单轮协同。",
                "execution_rounds": [],
                "strategy": "plot_first",
                "coordination_summary": "已完成单轮扩展。",
                "current_chapter_count": 12,
                "current_character_count": 2,
                "validation_before": {"chapter_count": 8, "character_count": 1},
                "validation_after": {"chapter_count": 12, "character_count": 2},
                "stop_reasons": ["达到当前目标"],
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

    def fake_parse_and_sync_characters(**kwargs: Any) -> dict[str, Any]:
        captured["characters_text"] = kwargs["characters_text"]
        return {"parsed": 2, "created": 1, "updated": 1, "skipped": 0}

    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", fake_parse_and_sync_characters)
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-character-sync-fallback",
        project_id=1,
        user_id=99,
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=8,
        current_character_count=1,
        target_total_chapters=12,
        target_total_characters=2,
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

    assert captured["characters_text"] == full_characters
    assert complete_events[0]["result"]["character_sync"] == {
        "parsed": 2,
        "created": 1,
        "updated": 1,
        "skipped": 0,
    }


@pytest.mark.asyncio
async def test_execute_expand_story_task_skips_character_sync_without_parseable_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    parse_calls: list[dict[str, Any]] = []
    complete_events: list[dict[str, Any]] = []

    analysis = {
        "effective_target_chapter_count": 12,
        "effective_target_character_count": 1,
        "effective_strategy": "plot_first",
        "effective_intent": "outline_led",
        "effective_expansion_mode": "total",
        "execution_mode": "delta",
        "execution_mode_reason": "单轮协同。",
        "warnings": [],
    }

    class _FakeCoordinator:
        def execute(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "plot_outline": "第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
                "characters": "暂无可解析人物卡",
                "character_delta": "本轮未新增人物",
                "execution_mode": "delta",
                "execution_mode_reason": "单轮协同。",
                "execution_rounds": [],
                "strategy": "plot_first",
                "coordination_summary": "已完成单轮扩展。",
                "current_chapter_count": 12,
                "current_character_count": 1,
                "validation_before": {"chapter_count": 8, "character_count": 1},
                "validation_after": {"chapter_count": 12, "character_count": 1},
                "alignment_warnings": ["原始协同警告"],
                "stop_reasons": ["达到当前目标"],
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

    def fake_parse_and_sync_characters(**kwargs: Any) -> dict[str, Any]:
        parse_calls.append(kwargs)
        raise AssertionError("没有结构化人物卡时不应触发解析")

    monkeypatch.setattr(workflow, "_build_story_expansion_analysis", fake_build_story_expansion_analysis)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(character_parser, "parse_and_sync_characters", fake_parse_and_sync_characters)
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(vector_sync, "upsert_character_to_vector_db", lambda **kwargs: None)
    monkeypatch.setattr(workflow.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(workflow.ws_manager, "send_task_progress", fake_send_task_progress)
    monkeypatch.setattr(workflow.ws_manager, "send_task_complete", fake_send_task_complete)
    monkeypatch.setattr(workflow.ws_manager, "send_task_error", fake_send_task_error)

    await workflow.execute_expand_story_task(
        task_id="expand-story-character-sync-skip",
        project_id=1,
        user_id=99,
        current_outline="第1章：雨夜入城\n- 主要内容：主角抵达青石城。",
        world_setting="蒸汽仙侠世界",
        characters="### 【姓名】：林舟\n【角色定位】：主角",
        current_chapter_count=8,
        current_character_count=1,
        target_total_chapters=12,
        target_total_characters=1,
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

    result = complete_events[0]["result"]
    assert parse_calls == []
    assert result["character_sync"] == {
        "parsed": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
    }
    assert "未能解析出任何人物卡" not in result["alignment_warnings"]
    assert "原始协同警告" in result["alignment_warnings"]

