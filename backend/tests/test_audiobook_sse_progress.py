from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.sse_progress import SSEProgressTracker  # noqa: E402
from app.services.audiobook import sse_progress as sse_progress_module  # noqa: E402


def test_sse_tracker_broadcasts_progress_to_local_clients():
    async def run_case():
        tracker = SSEProgressTracker()
        tracker._redis_checked = True
        tracker._redis_available = False
        tracker._redis_publish_client = None

        queue = tracker.register_client("task-1")
        try:
            await tracker.broadcast_progress(
                "task-1",
                {"stage": "tts_synthesis", "progress": 0.5},
            )
            message = await asyncio.wait_for(queue.get(), timeout=1)
        finally:
            tracker.unregister_client("task-1", queue)

        assert message.startswith("data: ")
        payload = json.loads(message.removeprefix("data: ").strip())
        assert payload["event"] == "progress"
        assert payload["data"] == {"stage": "tts_synthesis", "progress": 0.5}
        assert payload["origin"] == tracker._origin_id

    asyncio.run(run_case())


def test_create_progress_handler_delegates_to_tracker_emit(monkeypatch):
    calls = []

    class FakeTracker:
        def emit_progress(self, task_id, data):
            calls.append((task_id, data))

    monkeypatch.setattr(sse_progress_module, "sse_tracker", FakeTracker())

    handler = sse_progress_module.create_progress_handler("task-2")
    handler("tts_synthesis", 0.75, {"chapter_id": 3})

    assert calls == [
        (
            "task-2",
            {
                "stage": "tts_synthesis",
                "progress": 0.75,
                "detail": {"chapter_id": 3},
            },
        )
    ]
