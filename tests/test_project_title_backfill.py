from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

import backend.app.api.v1.projects as projects_api


class _FakeDBSession:
    def __init__(self, concept_text: str | None) -> None:
        self._concept_text = concept_text
        self.added_projects: list[object] = []

    def execute(self, _query: object, _params: object = None) -> SimpleNamespace:
        concept_text = self._concept_text
        return SimpleNamespace(fetchone=lambda: ((concept_text,) if concept_text is not None else None))

    def add(self, project: object) -> None:
        self.added_projects.append(project)


def test_sync_project_title_from_saved_concept_backfills_untitled_project() -> None:
    db = _FakeDBSession(
        json.dumps("**2. 日志标题（短标题）**：  \n道骸纪\n\n**3. 概念摘要（80–150字）**：  \n守墓人逆命而行。", ensure_ascii=False)
    )
    project = SimpleNamespace(id=28, title="未命名项目")

    changed = projects_api._sync_project_title_from_saved_concept(db, project)

    assert changed is True
    assert project.title == "道骸纪"
    assert db.added_projects == [project]


def test_sync_project_title_from_saved_concept_skips_named_project() -> None:
    db = _FakeDBSession(
        json.dumps("**2. 日志标题（短标题）**：  \n道骸纪", ensure_ascii=False)
    )
    project = SimpleNamespace(id=28, title="已有标题")

    changed = projects_api._sync_project_title_from_saved_concept(db, project)

    assert changed is False
    assert project.title == "已有标题"
    assert db.added_projects == []
