from __future__ import annotations

import json
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
import backend.app.api.v1.workflow as workflow


class _FakeExecuteResult:
    def __init__(self, fetchone_result: Any = None, rowcount: int = 1) -> None:
        self._fetchone_result = fetchone_result
        self.rowcount = rowcount

    def fetchone(self) -> Any:
        return self._fetchone_result


class _FakeQuery:
    def __init__(self, first_result: Any = None) -> None:
        self._first_result = first_result

    def filter(self, *args: Any, **kwargs: Any) -> "_FakeQuery":
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> "_FakeQuery":
        return self

    def first(self) -> Any:
        return self._first_result


class _FakeDBSession:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, Any]] = []
        self.closed = False
        self.commits = 0
        self.rollbacks = 0
        self.added: list[Any] = []
        self.memory_record = SimpleNamespace(messages=[], current_scene=None)

    def execute(self, query: Any, params: Any = None) -> _FakeExecuteResult:
        query_text = str(query)
        self.execute_calls.append((query_text, params))

        if "SELECT title, genre, sub_genre" in query_text:
            return _FakeExecuteResult(("测试项目", "玄幻", "", "", 0, 50, ""))

        if "SELECT id FROM project_settings" in query_text:
            return _FakeExecuteResult((1,))

        if "SELECT concept, world_setting, characters, plot_outline, chapter_draft, review_report" in query_text:
            return _FakeExecuteResult(
                (
                    '"测试概念"',
                    '"测试世界观"',
                    '"测试人物"',
                    "",
                    "",
                    "",
                )
            )

        return _FakeExecuteResult()

    def query(self, model: Any) -> _FakeQuery:
        model_name = getattr(model, "__name__", "")
        if model_name == "Memory":
            return _FakeQuery(self.memory_record)
        if model_name == "Project":
            return _FakeQuery(SimpleNamespace(user_id=99))
        return _FakeQuery()

    def add(self, item: Any) -> None:
        self.added.append(item)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True

    def get_bind(self) -> None:
        return None


class _FakeStreamingService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_chapter_streaming(
        self,
        *,
        prompt: str,
        system_prompt: str,
        on_chunk: Any,
        **kwargs: Any,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                **kwargs,
            }
        )
        content = "第1章：结构测试大纲\n- 主要内容：结构阶段专项流式输出。"
        await on_chunk(content, 0)
        return content


class _FakeWSManager:
    def __init__(self) -> None:
        self.task_complete_calls: list[dict[str, Any]] = []
        self.task_error_calls: list[dict[str, Any]] = []

    async def send_stage_update(self, **kwargs: Any) -> None:
        return None

    async def send_model_used(self, **kwargs: Any) -> None:
        return None

    async def send_stream_start(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def send_agent_status(self, **kwargs: Any) -> None:
        return None

    async def send_stream_chunk(self, **kwargs: Any) -> None:
        return None

    async def send_stream_end(self, **kwargs: Any) -> None:
        return None

    async def send_task_complete(self, **kwargs: Any) -> None:
        self.task_complete_calls.append(kwargs)

    async def send_task_error(self, **kwargs: Any) -> None:
        self.task_error_calls.append(kwargs)


class _FakeCoordinator:
    def __init__(self) -> None:
        self._coordinator_initialized = True
        self.real_coordinator = SimpleNamespace(project_context={})

    async def initialize_agents(self) -> None:
        return None

    def set_project_context(self, project_id: int) -> None:
        self.real_coordinator.project_context["project_id"] = project_id

    def get_real_coordinator(self, project_id: int | None = None) -> Any:
        return self.real_coordinator

    async def execute_stage(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("结构阶段流式成功时不应回退到 coordinator.execute_stage")


@pytest.mark.asyncio
async def test_execute_stage_with_streaming_structure_uses_single_specialized_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDBSession()
    fake_streaming_service = _FakeStreamingService()
    fake_ws_manager = _FakeWSManager()
    fake_coordinator = _FakeCoordinator()

    monkeypatch.setattr(db_base, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(workflow, "STREAMING_AVAILABLE", True)
    monkeypatch.setattr(workflow, "get_streaming_service", lambda: fake_streaming_service)
    monkeypatch.setattr(workflow, "ws_manager", fake_ws_manager)
    monkeypatch.setattr(workflow, "coordinator", fake_coordinator)

    await workflow.execute_stage_with_streaming(
        task_id="structure-streaming-regression",
        project_id=20,
        stage_enum=workflow.StageType.STRUCTURE,
        user_id=99,
        db=fake_db,
    )

    assert len(fake_streaming_service.calls) == 1
    assert fake_streaming_service.calls[0]["task_type"] == "structure_plot"
    assert fake_ws_manager.task_error_calls == []
    assert fake_ws_manager.task_complete_calls[0]["result"]["output"].startswith("第1章：结构测试大纲")
    assert fake_db.closed is True

    structure_save_calls = [
        params
        for query_text, params in fake_db.execute_calls
        if "UPDATE project_settings" in query_text and isinstance(params, dict) and "plot_outline" in params
    ]
    assert structure_save_calls
    assert "结构测试大纲" in json.loads(structure_save_calls[0]["plot_outline"])
