import asyncio
import threading
from pathlib import Path
import sys
import os


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

import pytest

from app.services import chapter_post_save as chapter_post_save_module
from app.websocket.manager import WorkflowWebSocketManager


class DummyWSManager:
    def __init__(self, result: bool = True):
        self.result = result
        self.calls = []

    async def broadcast_to_project(self, project_id: int, event: str, data: dict) -> bool:
        self.calls.append(
            {
                "project_id": project_id,
                "event": event,
                "data": data,
            }
        )
        return self.result


@pytest.mark.asyncio
async def test_broadcast_project_event_uses_main_loop_when_current_loop_differs(monkeypatch) -> None:
    main_loop = asyncio.new_event_loop()
    loop_ready = threading.Event()

    def _run_loop() -> None:
        asyncio.set_event_loop(main_loop)
        loop_ready.set()
        main_loop.run_forever()

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    loop_ready.wait(timeout=3)

    dummy_ws_manager = DummyWSManager(result=True)

    try:
        monkeypatch.setattr(chapter_post_save_module, "get_main_event_loop", lambda: main_loop)
        monkeypatch.setattr("app.websocket.manager.ws_manager", dummy_ws_manager)

        pushed = await chapter_post_save_module._broadcast_project_event(
            project_id=2,
            event="post_save_task_start",
            data={"chapter_id": 1, "status": "processing"},
        )

        assert pushed is True
        assert len(dummy_ws_manager.calls) == 1
        assert dummy_ws_manager.calls[0]["event"] == "post_save_task_start"
    finally:
        main_loop.call_soon_threadsafe(main_loop.stop)
        thread.join(timeout=3)
        main_loop.close()


@pytest.mark.asyncio
async def test_broadcast_project_event_returns_false_when_manager_reports_failure(monkeypatch) -> None:
    dummy_ws_manager = DummyWSManager(result=False)
    monkeypatch.setattr(chapter_post_save_module, "get_main_event_loop", lambda: None)
    monkeypatch.setattr("app.websocket.manager.ws_manager", dummy_ws_manager)

    pushed = await chapter_post_save_module._broadcast_project_event(
        project_id=3,
        event="post_save_task_complete",
        data={"chapter_id": 9, "status": "completed"},
    )

    assert pushed is False
    assert len(dummy_ws_manager.calls) == 1


@pytest.mark.asyncio
async def test_broadcast_to_project_returns_false_on_emit_error(monkeypatch) -> None:
    async def _broken_emit(*args, **kwargs):
        raise RuntimeError("emit failed")

    monkeypatch.setattr("app.websocket.manager.sio.emit", _broken_emit)

    result = await WorkflowWebSocketManager.broadcast_to_project(
        project_id=1,
        event="test_event",
        data={"ok": False},
    )

    assert result is False
