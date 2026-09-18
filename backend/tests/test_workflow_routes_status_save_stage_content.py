import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

import app.api.v1.workflow.routes_status as routes_status


class FakeQuery:
    def __init__(self, project):
        self.project = project

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.project

    def all(self):
        return []

    def update(self, *args, **kwargs):
        return 0


class FakeResult:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._one


class FakeDB:
    def __init__(self, project, chapters=None):
        self.project = project
        self.chapters = list(chapters or [])
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):
        return FakeQuery(self.project)

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        if "FROM chapters" in sql and "ORDER BY chapter_number DESC" in sql:
            ordered = sorted(self.chapters, key=lambda row: row[1], reverse=True)
            return FakeResult(rows=ordered)
        if "FROM chapters" in sql and "chapter_number = :chapter_number" in sql:
            target = (params or {}).get("chapter_number")
            for row in self.chapters:
                if row[1] == target:
                    return FakeResult(one=row)
            return FakeResult(one=None)
        return FakeResult()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class DummyWorkflowContextBuilder:
    writes = []

    def __init__(self, db):
        self.db = db

    def get_stage_field_name(self, stage: str):
        return {
            "concept": "concept",
            "structure": "plot_outline",
            "content": "chapter_draft",
            "review": "review_report",
            "iteration": "final_version",
        }.get(stage)

    def write_stage_content(self, project_id: int, stage: str, content: str):
        type(self).writes.append(
            {
                "project_id": project_id,
                "stage": stage,
                "content": content,
            }
        )


def test_save_stage_content_can_schedule_next_stage_for_content(monkeypatch) -> None:
    fake_db = FakeDB(project=SimpleNamespace(id=17, user_id=3))
    scheduled = []

    async def fake_run_execute_stage_with_streaming_serialized(*args, **kwargs):
        return None

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr(routes_status, "WorkflowContextBuilder", DummyWorkflowContextBuilder)
    monkeypatch.setattr(
        routes_status,
        "_run_execute_stage_with_streaming_serialized",
        fake_run_execute_stage_with_streaming_serialized,
    )
    monkeypatch.setattr(routes_status.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(routes_status.uuid, "uuid4", lambda: "fixed-task-id")

    DummyWorkflowContextBuilder.writes = []

    response = asyncio.run(
        routes_status.save_stage_content(
            project_id=17,
            stage="content",
            request=routes_status.SaveStageContentRequest(
                content="新的章节正文",
                continue_workflow=True,
            ),
            current_user=SimpleNamespace(id=3),
            db=fake_db,
        )
    )

    assert response["success"] is True
    assert response["stage"] == "content"
    assert response["task_id"] == "fixed-task-id"
    assert response["continue_workflow"] is True
    assert len(scheduled) == 1
    assert DummyWorkflowContextBuilder.writes == [
        {
            "project_id": 17,
            "stage": "content",
            "content": "新的章节正文",
        }
    ]


def test_save_stage_content_review_continue_does_not_delete_or_update_chapters(monkeypatch) -> None:
    chapters = [(11, 1, "第一章", 1200), (12, 2, "第二章", 1300)]
    fake_db = FakeDB(project=SimpleNamespace(id=17, user_id=3), chapters=chapters)
    scheduled = []

    async def fake_run_execute_stage_with_streaming_serialized(*args, **kwargs):
        return None

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return SimpleNamespace(done=lambda: True)

    class DummyKB:
        def delete_chapter(self, chapter_number, project_id):
            return 0

    monkeypatch.setattr(routes_status, "WorkflowContextBuilder", DummyWorkflowContextBuilder)
    monkeypatch.setattr(
        routes_status,
        "_run_execute_stage_with_streaming_serialized",
        fake_run_execute_stage_with_streaming_serialized,
    )
    monkeypatch.setattr(routes_status.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(routes_status.uuid, "uuid4", lambda: "review-task-id")
    monkeypatch.setitem(__import__("sys").modules, "app.services.agents.knowledge_base", SimpleNamespace(NovelKnowledgeBase=DummyKB))

    DummyWorkflowContextBuilder.writes = []

    response = asyncio.run(
        routes_status.save_stage_content(
            project_id=17,
            stage="review",
            request=routes_status.SaveStageContentRequest(
                content="评审报告正文",
                continue_workflow=True,
            ),
            current_user=SimpleNamespace(id=3),
            db=fake_db,
        )
    )

    assert response["success"] is True
    assert response["stage"] == "review"
    assert response["task_id"] == "review-task-id"
    assert response.get("deleted_chapters_count") in (None, 0)
    assert "deleted_chapter" not in response
    assert "updated_chapter" not in response
    assert not any("DELETE FROM chapters" in sql for sql, _params in fake_db.executed)
    assert not any("UPDATE chapters" in sql for sql, _params in fake_db.executed)
    assert len(scheduled) == 1

def test_save_stage_content_content_updates_latest_chapter_in_place(monkeypatch) -> None:
    chapters = [(11, 1, "第一章", 1200), (12, 2, "第二章", 1300)]
    fake_db = FakeDB(project=SimpleNamespace(id=17, user_id=3), chapters=chapters)
    scheduled = []

    async def fake_run_execute_stage_with_streaming_serialized(*args, **kwargs):
        return None

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr(routes_status, "WorkflowContextBuilder", DummyWorkflowContextBuilder)
    monkeypatch.setattr(
        routes_status,
        "_run_execute_stage_with_streaming_serialized",
        fake_run_execute_stage_with_streaming_serialized,
    )
    monkeypatch.setattr(routes_status.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(routes_status.uuid, "uuid4", lambda: "content-task-id")

    DummyWorkflowContextBuilder.writes = []

    response = asyncio.run(
        routes_status.save_stage_content(
            project_id=17,
            stage="content",
            request=routes_status.SaveStageContentRequest(
                content="改写后的第二章",
                continue_workflow=True,
            ),
            current_user=SimpleNamespace(id=3),
            db=fake_db,
        )
    )

    assert response["success"] is True
    assert response["updated_chapter"]["id"] == 12
    assert response["updated_chapter"]["chapter_number"] == 2
    assert not any("DELETE FROM chapters" in sql for sql, _params in fake_db.executed)
    updates = [params for sql, params in fake_db.executed if "UPDATE chapters" in sql]
    assert updates == [{"content": "改写后的第二章", "word_count": len("改写后的第二章"), "chapter_id": 12}]
    assert len(scheduled) == 1


class DummyStageContentBuilder:
    def __init__(self, db, *, content="终稿", review_meta=None):
        self.db = db
        self.content = content
        self.review_meta = review_meta or {}

    def get_stage_field_name(self, stage: str):
        return {"concept": "concept", "iteration": "final_version"}.get(stage)

    def read_stage_content(self, project_id, stage, pretty_json=True):
        return self.content

    def load_review_meta(self, project_id):
        return self.review_meta


@pytest.mark.parametrize(
    ("review_meta", "expected_degraded", "expected_score"),
    [
        ({"first_chapter_iteration": {"degraded": True, "best_score": 8.0}}, True, 8.0),
        ({"first_chapter_iteration": {"degraded": False}}, False, None),
        ({}, False, None),
    ],
)
def test_get_stage_content_reports_iteration_degraded(
    monkeypatch, review_meta, expected_degraded, expected_score
):
    db = FakeDB(project=SimpleNamespace(id=17, user_id=3))
    builder = DummyStageContentBuilder(db, review_meta=review_meta)
    monkeypatch.setattr(routes_status, "WorkflowContextBuilder", lambda db: builder)

    result = asyncio.run(
        routes_status.get_stage_content(17, "iteration", SimpleNamespace(id=3), db)
    )

    assert result == {
        "content": "终稿",
        "stage": "iteration",
        "degraded": expected_degraded,
        "best_score": expected_score,
    }


@pytest.fixture
def stage_execution_env(monkeypatch):
    import importlib
    import app.db.base as db_base
    import app.services.chapter_post_save as chapter_post_save_module
    from app.services.agent_coordinator import AgentCoordinator
    from app.services.agents.agent_coordinator import CreativeDirectorCoordinator

    streaming = importlib.import_module("app.api.v1.workflow.execute_streaming")
    background = importlib.import_module("app.api.v1.workflow.execute_background")
    events = []
    db = FakeDB(project=SimpleNamespace(id=17, user_id=3))
    db.close = Mock()
    db.add = Mock()

    class FakeChapterQuery:
        """模拟 ORM 查询链：filter/order_by 透传，first 返回当前假章节。"""

        def __init__(self, holder):
            self._holder = holder

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return self._holder.chapter

    db.chapter = None
    db.query = lambda model: (
        FakeQuery(None) if model.__name__ == "Memory"
        else FakeChapterQuery(db) if model.__name__ == "Chapter"
        else FakeQuery(db.project)
    )
    original_execute = db.execute

    def execute(sql, params=None):
        if params and params.get("status"):
            events.append(params["status"])
        return original_execute(sql, params)

    db.execute = execute
    state = SimpleNamespace(concept="概念", world_setting="世界", characters="人物", plot_outline="第一章 追逐", chapter_draft="初稿", review_report="综合评分：7/10分", final_version="")
    builder = Mock()
    builder.get_project_profile.return_value = SimpleNamespace(genre="玄幻")
    builder.ensure_project_settings_record.return_value = False
    builder.load_stage_text_context.return_value = state
    builder.build_world_setting_context.return_value = SimpleNamespace(combined_world_setting="世界")
    builder.build_typed_rag_context.return_value = SimpleNamespace(rag_character_context="人物召回", rag_world_context="世界召回")
    builder.update_project_settings_fields.side_effect = lambda *a, **kw: events.append("saved")
    real = CreativeDirectorCoordinator.__new__(CreativeDirectorCoordinator)
    real.project_context = {**vars(state), "content": state.chapter_draft, "review": state.review_report}
    real.finalize_structure = Mock(return_value={"plot_outline": "验证后大纲", "event_validation": "结果：通过"})
    real.finalize_content = Mock(return_value={"content": "润色稿"})
    real._stage_three_content_creation = Mock(return_value={"content": "润色稿"})
    real._stage_four_quality_review = Mock(return_value={"review": "综合评分：9.5/10分", "review_meta": {"multi_model": True}})
    real._stage_five_iteration_optimization = Mock(return_value={"revised_content": "终稿", "final_review": "综合评分：9.5/10分\n结论：通过", "iteration_plan": "计划"})
    real.set_project_context = Mock()
    wrapper = AgentCoordinator()
    wrapper._coordinator_initialized = True
    wrapper.get_real_coordinator = lambda project_id=None: real
    wrapper.set_project_context = Mock()
    wrapper._load_project_context_from_db = AsyncMock()
    ws = SimpleNamespace(**{name: AsyncMock() for name in (
        "send_stage_update", "send_model_used", "send_stream_start", "send_stream_chunk", "send_stream_end",
        "send_agent_status", "send_task_complete", "send_task_error", "send_task_progress",
    )})

    async def generate(**kwargs):
        await kwargs["on_chunk"]("流式初稿", 0)
        return "流式初稿"

    service = SimpleNamespace(generate_chapter_streaming=AsyncMock(side_effect=generate))
    monkeypatch.setattr(db_base, "SessionLocal", lambda: db)
    for module in (streaming, background):
        monkeypatch.setattr(module, "coordinator", wrapper)
        monkeypatch.setattr(module, "WorkflowContextBuilder", lambda db: builder)
        monkeypatch.setattr(module, "ws_manager", ws)
        monkeypatch.setattr(module, "_sync_real_coordinator_project_context", lambda *args: (builder.get_project_profile.return_value, real))
        monkeypatch.setattr(module, "_resolve_workflow_requirement", lambda *args: ("要求", "test"))
    monkeypatch.setattr(streaming, "STREAMING_AVAILABLE", True)
    monkeypatch.setattr(streaming, "get_streaming_service", lambda: service)
    monkeypatch.setattr(
        chapter_post_save_module,
        "start_chapter_post_save_task",
        lambda **kwargs: events.append("chapter_post_save"),
    )
    monkeypatch.setattr(streaming, "_build_project_world_setting_context", lambda *args: "世界")
    return SimpleNamespace(streaming=streaming, background=background, db=db, state=state, builder=builder, real=real, wrapper=wrapper, ws=ws, service=service, events=events)


@pytest.mark.parametrize("stage", ["structure", "content", "review", "iteration"])
def test_streaming_entry_runs_shared_quality_steps(stage_execution_env, stage):
    from app.services.agent_coordinator import StageType
    env = stage_execution_env
    asyncio.run(env.streaming.execute_stage_with_streaming("task", 17, StageType(stage), 3, env.db, manual_multi_model_review=True, manual_multi_model_review_preset="deep_7"))
    env.ws.send_task_error.assert_not_called()
    method = {"structure": env.real.finalize_structure, "content": env.real.finalize_content, "review": env.real._stage_four_quality_review, "iteration": env.real._stage_five_iteration_optimization}[stage]
    method.assert_called_once()
    assert env.events.index("saved") < env.events.index("completed")
    if stage in {"review", "iteration"}:
        env.service.generate_chapter_streaming.assert_not_called()
    if stage == "review":
        assert env.real.project_context["manual_multi_model_review"] is True
        assert env.real.project_context["manual_multi_model_review_preset"] == "deep_7"
    if stage == "iteration":
        assert env.builder.update_project_settings_fields.call_args.kwargs["review_meta"]["first_chapter_iteration"]["final_review"].endswith("结论：通过")


@pytest.mark.parametrize("streaming", [True, False])
def test_stage_storage_failure_never_completes(stage_execution_env, streaming):
    from app.services.agent_coordinator import StageType
    env = stage_execution_env
    env.builder.update_project_settings_fields.side_effect = RuntimeError("存储不可用")
    entry = env.streaming.execute_stage_with_streaming if streaming else env.background.execute_stage_background
    asyncio.run(entry("task", 17, StageType.CONTENT, 3, env.db))
    env.ws.send_task_complete.assert_not_called()
    env.ws.send_task_error.assert_awaited_once()
    assert "completed" not in env.events
    assert "failed" in env.events
    assert not any(call.kwargs.get("status") == "completed" for call in env.ws.send_agent_status.call_args_list)


@pytest.mark.parametrize("streaming", [True, False])
def test_database_outage_still_notifies_failure(stage_execution_env, streaming):
    from app.services.agent_coordinator import StageType
    env = stage_execution_env
    env.builder.update_project_settings_fields.side_effect = RuntimeError("数据库不可用")
    env.db.execute = Mock(side_effect=RuntimeError("数据库不可用"))
    entry = env.streaming.execute_stage_with_streaming if streaming else env.background.execute_stage_background
    asyncio.run(entry("task", 17, StageType.CONTENT, 3, env.db))
    env.ws.send_task_complete.assert_not_called()
    env.ws.send_task_error.assert_awaited_once()


@pytest.mark.parametrize("streaming", [True, False])
def test_missing_revised_content_cannot_save_review_as_final(stage_execution_env, streaming):
    from app.services.agent_coordinator import StageType
    env = stage_execution_env
    env.real._stage_five_iteration_optimization.return_value = {"final_review": "综合评分：9.5/10分\n结论：通过"}
    entry = env.streaming.execute_stage_with_streaming if streaming else env.background.execute_stage_background
    asyncio.run(entry("task", 17, StageType.ITERATION, 3, env.db))
    env.builder.update_project_settings_fields.assert_not_called()
    env.ws.send_task_complete.assert_not_called()
    env.ws.send_task_error.assert_awaited_once()


@pytest.mark.parametrize("streaming", [True, False])
def test_iteration_result_overwrites_latest_chapter(stage_execution_env, streaming):
    """评审「保存并继续」的迭代终稿必须覆盖最新一章，否则用户看到的仍是旧稿。"""
    from app.services.agent_coordinator import StageType
    env = stage_execution_env
    chapter = SimpleNamespace(
        id=88, chapter_number=2, title="第2章", content="上一版旧稿", word_count=6, deleted_at=None
    )
    env.db.chapter = chapter
    entry = env.streaming.execute_stage_with_streaming if streaming else env.background.execute_stage_background

    asyncio.run(entry("task", 17, StageType.ITERATION, 3, env.db))

    env.ws.send_task_error.assert_not_called()
    assert chapter.content == "终稿"
    assert chapter.word_count == len("终稿")
    assert "chapter_post_save" in env.events
    # 旧正文留档，保证可回溯
    archived = [
        call.args[0].content
        for call in env.db.add.call_args_list
        if hasattr(call.args[0], "chapter_id")
    ]
    assert archived == ["上一版旧稿"]


@pytest.mark.parametrize("streaming", [True, False])
def test_stage_execution_injects_real_chapter_number(stage_execution_env, streaming):
    """改稿/复评提示词的章节号必须来自项目最新章，不能永远是第 1 章。"""
    from app.services.agent_coordinator import StageType
    env = stage_execution_env
    env.db.chapter = SimpleNamespace(
        id=7, chapter_number=4, title="第4章", content="旧稿", word_count=2, deleted_at=None
    )
    entry = env.streaming.execute_stage_with_streaming if streaming else env.background.execute_stage_background

    asyncio.run(entry("task", 17, StageType.ITERATION, 3, env.db))

    assert env.real.project_context["chapter_number"] == 4


def test_streaming_quality_failure_does_not_restart_generation(stage_execution_env):
    from app.services.agent_coordinator import StageType
    env = stage_execution_env
    env.real.finalize_structure.side_effect = RuntimeError("验证不通过")
    env.wrapper.execute_stage = AsyncMock()
    asyncio.run(env.streaming.execute_stage_with_streaming("task", 17, StageType.STRUCTURE, 3, env.db))
    env.wrapper.execute_stage.assert_not_called()
    env.ws.send_task_complete.assert_not_called()
    env.ws.send_task_error.assert_awaited_once()
    env.builder.update_project_settings_fields.assert_not_called()


def test_streaming_missing_chapter_fails_before_model_call(stage_execution_env):
    from app.services.agent_coordinator import StageType
    env = stage_execution_env
    env.state.chapter_draft = ""
    asyncio.run(env.streaming.execute_stage_with_streaming("task", 17, StageType.REVIEW, 3, env.db))
    env.service.generate_chapter_streaming.assert_not_called()
    env.real._stage_four_quality_review.assert_not_called()
    env.ws.send_task_error.assert_awaited_once()


def test_agent_observer_runs_in_worker_and_is_cleared_before_storage(stage_execution_env):
    import threading
    from app.services.agent_coordinator import StageType
    from app.services.agents.agents import agent_stream_observer
    env = stage_execution_env
    main_thread = threading.get_ident()
    seen = []

    def finalize(draft, **kwargs):
        assert threading.get_ident() != main_thread
        observer = agent_stream_observer.get()
        assert observer is not None
        observer("style_optimizer", "")
        observer("style_optimizer", "润色增量")
        return {"content": "润色增量"}

    def save(*args, **kwargs):
        seen.append(agent_stream_observer.get())
        env.events.append("saved")

    env.real.finalize_content.side_effect = finalize
    env.builder.update_project_settings_fields.side_effect = save
    asyncio.run(env.streaming.execute_stage_with_streaming("task", 17, StageType.CONTENT, 3, env.db))
    env.ws.send_task_error.assert_not_called()
    assert seen == [None]
    assert agent_stream_observer.get() is None
    assert any(call.kwargs["chunk"] == "润色增量" for call in env.ws.send_stream_chunk.call_args_list)


def test_fallback_content_keeps_incremental_preview(stage_execution_env, monkeypatch):
    from app.services.agent_coordinator import StageType
    from app.services.agents.agents import agent_stream_observer
    env = stage_execution_env
    monkeypatch.setattr(env.streaming, "STREAMING_AVAILABLE", False)

    def create(context):
        observer = agent_stream_observer.get()
        observer("content_creator", "")
        observer("content_creator", "回退路径正文增量")
        return {"content": "正文"}

    env.real._stage_three_content_creation.side_effect = create
    asyncio.run(env.streaming.execute_stage_with_streaming("task", 17, StageType.CONTENT, 3, env.db))
    env.ws.send_task_error.assert_not_called()
    assert any(call.kwargs["chunk"] == "回退路径正文增量" for call in env.ws.send_stream_chunk.call_args_list)


def test_fallback_concept_stream_routes_parts_to_separate_targets(stage_execution_env, monkeypatch):
    from app.services.agent_coordinator import StageType
    from app.services.agents.agents import agent_stream_observer
    env = stage_execution_env
    monkeypatch.setattr(env.streaming, "STREAMING_AVAILABLE", False)
    monkeypatch.setattr(env.streaming, "_inject_recent_project_novelty_context", Mock())
    monkeypatch.setattr(env.streaming, "_normalize_concept_stage_characters_for_storage", lambda pid, text, **kw: text)
    monkeypatch.setattr(env.streaming, "_sync_project_title_from_concept", Mock())

    def create(requirement):
        observer = agent_stream_observer.get()
        for role, chunk in (("creative_director", "概念增量"), ("world_architect", "世界增量"), ("character_designer", "人物增量")):
            observer(role, "")
            observer(role, chunk)
        return {"concept": "概念", "world_setting": "世界", "characters": "人物"}

    env.real._stage_one_concept_development = create
    asyncio.run(env.streaming.execute_stage_with_streaming("task", 17, StageType.CONCEPT, 3, env.db))
    env.ws.send_task_error.assert_not_called()
    actual = [(call.kwargs["chunk"], call.kwargs.get("extra", {}).get("target")) for call in env.ws.send_stream_chunk.call_args_list]
    assert actual == [("概念增量", "concept"), ("世界增量", "world"), ("人物增量", "character")]


def test_wrapper_preserves_skipped_concept_agents(stage_execution_env):
    from app.services.agent_coordinator import StageType, AgentStatus
    env = stage_execution_env
    env.wrapper.agents = {
        name: {"stage": StageType.CONCEPT, "status": AgentStatus.IDLE, "progress": 0}
        for name in ("creative_director", "world_architect", "character_designer")
    }
    env.real._stage_one_concept_development = Mock(return_value={
        "concept": "概念", "world_setting": "世界", "characters": "新人物",
        "skipped_agents": ["creative_director", "world_architect"],
    })
    result = asyncio.run(env.wrapper.execute_stage(StageType.CONCEPT, {}))
    assert result.agents_involved == ["character_designer"]
    assert env.wrapper.agents["creative_director"]["status"] == AgentStatus.IDLE


def test_character_regeneration_saves_new_card_and_reports_only_executed_agents(stage_execution_env, monkeypatch):
    import json
    import app.services.character_parser as parser
    import app.services.vector_sync as vector_sync
    from app.services.agent_coordinator import StageType
    env = stage_execution_env
    env.builder.load_concept_storage_state.return_value = SimpleNamespace(concept_value="旧概念", world_setting_value="旧世界", characters_value="旧人物")
    env.real._stage_one_concept_development = Mock(return_value={
        "concept": "旧概念", "world_setting": "旧世界", "characters": "新人物卡",
        "skipped_agents": ["creative_director", "world_architect"],
    })
    monkeypatch.setattr(env.background, "_inject_recent_project_novelty_context", Mock())
    monkeypatch.setattr(env.background, "_normalize_concept_stage_characters_for_storage", lambda pid, text, **kw: text)
    monkeypatch.setattr(env.background, "_sync_project_title_from_concept", Mock())
    monkeypatch.setattr(parser, "parse_and_sync_characters", Mock(return_value={"parsed": 0, "created": 0, "updated": 0}))
    monkeypatch.setattr(vector_sync, "sync_to_vector_db", Mock())
    asyncio.run(env.background.execute_stage_background("task", 17, StageType.CONCEPT, 3, env.db, regenerate=True, targets=["characters"]))
    env.ws.send_task_error.assert_not_called()
    saved = env.builder.update_project_settings_fields.call_args.kwargs
    assert json.loads(saved["characters"]) == "新人物卡"
    assert json.loads(saved["concept"]) == "旧概念"
    completed = [call.kwargs["agent_id"] for call in env.ws.send_agent_status.call_args_list if call.kwargs["status"] == "completed"]
    assert completed == ["character_designer"]


