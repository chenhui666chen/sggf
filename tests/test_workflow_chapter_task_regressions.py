from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


import backend.app.api.v1.workflow as workflow
from app.services.agents.chapter_summarizer import ChapterSummarizer


class _FakeExecuteResult:
    def __init__(self, fetchone_result: Any = None) -> None:
        self._fetchone_result = fetchone_result

    def fetchone(self) -> Any:
        return self._fetchone_result


class _FakeDB:
    def __init__(self, fetchone_result: Any = None) -> None:
        self._fetchone_result = fetchone_result
        self.execute_calls: list[tuple[str, Any]] = []
        self.rollbacks = 0

    def execute(self, query: Any, params: Any = None) -> _FakeExecuteResult:
        query_text = str(query)
        self.execute_calls.append((query_text, params))

        if "SELECT title, genre, sub_genre" in query_text:
            return _FakeExecuteResult(("测试项目", "玄幻", "", "", 0, 0, "用户大纲"))

        if "SELECT concept, world_setting, characters, plot_outline" in query_text:
            return _FakeExecuteResult(("", "世界观设定", "人物设定", "结构大纲", "", "", ""))

        return _FakeExecuteResult(self._fetchone_result)

    def rollback(self) -> None:
        self.rollbacks += 1


class _RollbackFailsDB:
    def rollback(self) -> None:
        raise RuntimeError("boom")


def test_chapter_summarizer_module_importable() -> None:
    assert ChapterSummarizer is not None


def test_load_latest_chapter_plan_uses_current_schema() -> None:
    fake_db = _FakeDB(("当前章节规划",))

    result = workflow._load_latest_chapter_plan(
        fake_db,
        project_id=21,
        chapter_id=361,
    )

    assert result == "当前章节规划"
    query_text, params = fake_db.execute_calls[0]
    assert "SELECT content" in query_text
    assert "chapter_id = :chapter_id" in query_text
    assert "chapter_number" not in query_text
    assert params == {"project_id": 21, "chapter_id": 361}


def test_load_project_chapter_context_prefers_plot_outline() -> None:
    fake_db = _FakeDB()

    result = workflow._load_project_chapter_context(fake_db, project_id=9)

    assert result == {
        "genre": "玄幻",
        "outline": "结构大纲",
        "world_setting": "世界观设定",
        "characters": "人物设定",
    }


def test_safe_db_rollback_swallows_rollback_errors() -> None:
    workflow._safe_db_rollback(_RollbackFailsDB(), "回归测试")
