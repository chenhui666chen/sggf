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

