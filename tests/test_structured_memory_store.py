import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app.services.agents.structured_memory_store import StructuredMemoryStore


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _RecordingSession:
    def __init__(self, load_value=None, fail=False):
        self.load_value = load_value
        self.fail = fail
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        if self.fail:
            raise RuntimeError("db unavailable")
        return _ScalarResult(self.load_value)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_structured_memory_store_prefers_database_payload_over_file_cache(tmp_path):
    db_payload = {
        "structured_memory": {"character_states": ["数据库角色状态"]},
        "memory_text": "数据库摘要",
        "metadata": {"source": "db"},
        "updated_at": "2026-03-17T00:00:00+00:00",
    }
    session = _RecordingSession(load_value=json.dumps(db_payload, ensure_ascii=False))
    store = StructuredMemoryStore(
        persist_directory=str(tmp_path),
        session_factory=lambda: session,
    )

    store._save_context(
        7,
        {
            store.STORAGE_KEY: {
                "structured_memory": {"character_states": ["文件角色状态"]},
                "memory_text": "文件摘要",
                "metadata": {"source": "file"},
                "updated_at": "2026-03-16T00:00:00+00:00",
            }
        },
    )

    payload = store.load(7)

    assert payload["memory_text"] == "数据库摘要"
    assert payload["structured_memory"]["character_states"] == ["数据库角色状态"]
    assert payload["metadata"]["source"] == "db"
    assert session.closed is True


def test_structured_memory_store_falls_back_to_file_when_database_load_fails(tmp_path):
    session = _RecordingSession(fail=True)
    store = StructuredMemoryStore(
        persist_directory=str(tmp_path),
        session_factory=lambda: session,
    )

    store._save_context(
        8,
        {
            store.STORAGE_KEY: {
                "structured_memory": {"pending_foreshadowings": ["文件伏笔"]},
                "memory_text": "文件记忆",
                "metadata": {"source": "file"},
                "updated_at": "2026-03-16T00:00:00+00:00",
            }
        },
    )

    payload = store.load(8)

    assert payload["memory_text"] == "文件记忆"
    assert payload["structured_memory"]["pending_foreshadowings"] == ["文件伏笔"]
    assert payload["metadata"]["source"] == "file"
    assert session.closed is True


def test_structured_memory_store_save_writes_database_and_file_cache(tmp_path):
    session = _RecordingSession()
    store = StructuredMemoryStore(
        persist_directory=str(tmp_path),
        session_factory=lambda: session,
    )

    saved = store.save(
        project_id=9,
        structured_memory={"world_rules_hard_constraints": ["夜禁期间城门不可无故开启"]},
        memory_text="结构化记忆摘要",
        metadata={"scenario": "outline_expand"},
    )

    assert saved is True
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True
    assert len(session.executed) == 1

    _, params = session.executed[0]
    assert params["project_id"] == 9
    assert isinstance(params["structured_memory_updated_at"], datetime)

    db_payload = json.loads(params["structured_memory"])
    assert db_payload["memory_text"] == "结构化记忆摘要"
    assert db_payload["metadata"]["scenario"] == "outline_expand"
    assert db_payload["structured_memory"]["world_rules_hard_constraints"] == ["夜禁期间城门不可无故开启"]

    file_payload = store._load_from_file(9)
    assert file_payload["memory_text"] == "结构化记忆摘要"
    assert file_payload["metadata"]["scenario"] == "outline_expand"
