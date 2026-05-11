from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.repository import AudiobookTaskRepository


class _FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.committed = False
        self.refreshed = []

    def add(self, item) -> None:
        self.added.append(item)

    def commit(self) -> None:
        self.committed = True

    def refresh(self, item) -> None:
        self.refreshed.append(item)


def test_create_task_sets_client_side_timestamps() -> None:
    db = _FakeSession()

    task = AudiobookTaskRepository.create_task(
        db,
        audiobook_project_id=1,
        chapter_id=2,
        task_type="full",
        total_units=3,
    )

    assert task.created_at is not None
    assert task.updated_at is not None
    assert task.created_at == task.updated_at
    assert task.status == "pending"
    assert task.total_units == 3
    assert db.added == [task]
    assert db.committed is True
    assert db.refreshed == [task]
