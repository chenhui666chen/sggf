import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace


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

    def first(self):
        return self.project


class FakeResult:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._one


class FakeDB:
    def __init__(self, project):
        self.project = project
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):
        return FakeQuery(self.project)

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        if "FROM chapters" in sql and "ORDER BY chapter_number DESC" in sql:
            return FakeResult(rows=[])
        if "FROM chapters" in sql and "chapter_number = :chapter_number" in sql:
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
