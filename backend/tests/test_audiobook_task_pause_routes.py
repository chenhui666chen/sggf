"""有声书任务暂停/继续路由的交互回归测试。"""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = ROOT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.v1.audiobook_api import routes_tasks


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.refreshed = []

    def commit(self) -> None:
        self.committed = True

    def refresh(self, item) -> None:
        self.refreshed.append(item)


def test_resume_revokes_pending_pause_without_enqueuing_another_task(monkeypatch) -> None:
    task = SimpleNamespace(
        id=1,
        status="pause_requested",
        detail_json={},
        audiobook_project_id=7,
        task_type="full",
    )
    db = _FakeSession()

    monkeypatch.setattr(
        routes_tasks.AudiobookTaskRepository,
        "get_task_for_user",
        lambda _db, _task_id, _user_id: task,
    )

    response = asyncio.run(routes_tasks.resume_task(
        task_id="task-1",
        raw_request=SimpleNamespace(),
        current_user=SimpleNamespace(id=3),
        db=db,
    ))

    assert task.status == "running"
    assert db.committed is True
    assert db.refreshed == [task]
    assert response == {
        "success": True,
        "audiobook_project_id": 7,
        "job_id": None,
        "task_type": "full",
        "message": "已继续当前生成任务",
    }
