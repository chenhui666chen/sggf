from __future__ import annotations

import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.routing import Match


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"

for candidate in (str(ROOT_DIR), str(BACKEND_DIR)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from app.api.v1.audiobook import list_deleted_projects, router as audiobook_router
from app.api.v1.chapters import get_deleted_chapters, router as chapters_router
from app.models.audiobook_delete_audit import AudiobookDeleteAudit
from app.models.project import Chapter, Project


def _find_full_match_path(app: FastAPI, path: str, method: str) -> str | None:
    scope = {
        "type": "http",
        "path": path,
        "method": method,
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    for route in app.router.routes:
        match, _child_scope = route.matches(scope)
        if match == Match.FULL:
            return getattr(route, "path", None)

    return None


class _FakeQuery:
    def __init__(self, *, result_all=None, result_first=None):
        self._result_all = result_all if result_all is not None else []
        self._result_first = result_first

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._result_all

    def first(self):
        return self._result_first


class _FakeDeletedChapterDb:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *entities):
        if entities == (Chapter, Project.title):
            return _FakeQuery(result_all=self._rows)
        raise AssertionError(f"unexpected query entities: {entities!r}")


class _FakeDeletedAudiobookDb:
    def __init__(self, audit_logs, project_title_rows):
        self._audit_logs = audit_logs
        self._project_title_rows = project_title_rows

    def query(self, *entities):
        if len(entities) == 1 and entities[0] is AudiobookDeleteAudit:
            return _FakeQuery(result_all=self._audit_logs)
        if len(entities) == 2 and entities[0] is Project.id and entities[1] is Project.title:
            return _FakeQuery(result_all=self._project_title_rows)
        raise AssertionError(f"unexpected query entities: {entities!r}")


def test_chapters_deleted_route_prefers_static_match() -> None:
    app = FastAPI()
    app.include_router(chapters_router)

    matched_path = _find_full_match_path(app, "/api/v1/chapters/deleted", "GET")

    assert matched_path == "/api/v1/chapters/deleted"


def test_audiobook_deleted_route_prefers_static_match() -> None:
    app = FastAPI()
    app.include_router(audiobook_router)

    matched_path = _find_full_match_path(app, "/api/v1/audiobook/projects/deleted", "GET")

    assert matched_path == "/api/v1/audiobook/projects/deleted"


def test_get_deleted_chapters_supports_all_projects_query() -> None:
    now = datetime.now(timezone.utc)
    chapter = SimpleNamespace(
        id=101,
        project_id=7,
        chapter_number=3,
        title="已删除章节",
        content="章节内容",
        word_count=1280,
        created_at=now,
        updated_at=now,
        deleted_at=now,
        status="draft",
    )
    db = _FakeDeletedChapterDb([(chapter, "项目A")])
    current_user = SimpleNamespace(id=42)

    response = asyncio.run(get_deleted_chapters(project_id=0, current_user=current_user, db=db))

    assert response["project_id"] is None
    assert response["count"] == 1
    assert response["deleted_chapters"][0]["project_name"] == "项目A"
    assert response["deleted_chapters"][0]["project_id"] == 7


def test_list_deleted_projects_returns_audit_enriched_items(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    deleted_project = SimpleNamespace(
        id=301,
        project_id=17,
        status="deleted",
        total_chapters=12,
        completed_chapters=8,
        total_duration=456.7,
        deleted_at=now,
        created_at=now,
    )
    audit_log = SimpleNamespace(
        id=901,
        target_id=301,
        delete_reason="手动删除",
        affected_chapters=12,
        affected_tasks=3,
        total_size=2048,
        restored_at=None,
    )
    db = _FakeDeletedAudiobookDb(
        audit_logs=[audit_log],
        project_title_rows=[(17, "项目A")],
    )
    current_user = SimpleNamespace(id=42)

    monkeypatch.setattr(
        "app.api.v1.audiobook.AudiobookProjectRepository.list_deleted",
        lambda db, user_id, limit: [deleted_project],
    )

    response = asyncio.run(list_deleted_projects(current_user=current_user, db=db, limit=50))

    assert response["success"] is True
    assert response["count"] == 1
    assert response["projects"][0]["project_title"] == "项目A"
    assert response["projects"][0]["audit_id"] == 901
    assert response["projects"][0]["delete_reason"] == "手动删除"
