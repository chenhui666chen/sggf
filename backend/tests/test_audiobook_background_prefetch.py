import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.background_jobs_prefetch import (
    normalize_chapter_ids,
    prefetch_chapter_generation_records,
)
from app.services.audiobook.repository import ChapterAudioRepository, ChapterRepository


def test_normalize_chapter_ids_preserves_order_and_removes_duplicates():
    assert normalize_chapter_ids([3, 1, 3, None, 2, 1]) == [3, 1, 2]


def test_prefetch_chapter_generation_records_uses_batch_repositories(monkeypatch):
    calls = {}

    def fake_list_active_by_ids(db, chapter_ids):
        calls["chapter_ids"] = list(chapter_ids)
        return [
            SimpleNamespace(id=1, title="第一章"),
            SimpleNamespace(id=2, title="第二章"),
        ]

    def fake_list_active_by_project_chapter_ids(db, audiobook_project_id, chapter_ids):
        calls["audiobook_project_id"] = audiobook_project_id
        calls["audio_chapter_ids"] = list(chapter_ids)
        return [
            SimpleNamespace(id=10, chapter_id=2),
            SimpleNamespace(id=11, chapter_id=1),
        ]

    monkeypatch.setattr(ChapterRepository, "list_active_by_ids", fake_list_active_by_ids)
    monkeypatch.setattr(
        ChapterAudioRepository,
        "list_active_by_project_chapter_ids",
        fake_list_active_by_project_chapter_ids,
    )

    records = prefetch_chapter_generation_records(
        object(),
        audiobook_project_id=9,
        chapter_ids=[2, 1, 2, None],
    )

    assert calls == {
        "chapter_ids": [2, 1],
        "audiobook_project_id": 9,
        "audio_chapter_ids": [2, 1],
    }
    assert set(records.chapter_by_id) == {1, 2}
    assert records.chapter_audio_by_chapter_id[1].id == 11
    assert records.chapter_audio_by_chapter_id[2].id == 10
