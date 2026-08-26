import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
for item in (str(BACKEND_DIR), str(REPO_ROOT)):
    if item not in sys.path:
        sys.path.insert(0, item)

os.environ.setdefault("DEBUG", "false")

from app.api.v1.workflow import routes_chapter


def setup_function() -> None:
    routes_chapter._active_generate_next_chapter_task_ids.clear()
    routes_chapter._active_generate_next_chapter_tasks.clear()


def test_live_asyncio_task_is_treated_as_active() -> None:
    async def run() -> None:
        async def linger() -> None:
            await asyncio.sleep(60)

        aio_task = asyncio.create_task(linger())
        routes_chapter.mark_generate_next_chapter_task_active("t-live", 3, aio_task=aio_task)
        assert routes_chapter.has_active_generate_next_chapter_for_project(3) is True
        aio_task.cancel()
        try:
            await aio_task
        except asyncio.CancelledError:
            pass
        assert routes_chapter.has_active_generate_next_chapter_for_project(3) is False

    asyncio.run(run())


def test_finished_task_is_not_active() -> None:
    async def run() -> None:
        aio_task = asyncio.create_task(asyncio.sleep(0))
        await aio_task
        routes_chapter.mark_generate_next_chapter_task_active("t-done", 7, aio_task=aio_task)
        assert routes_chapter.has_active_generate_next_chapter_for_project(7) is False

    asyncio.run(run())
