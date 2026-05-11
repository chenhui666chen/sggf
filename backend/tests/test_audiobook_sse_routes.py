from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import router as audiobook_router
from app.api.v1.audiobook_api import routes_misc
from app.core.security import get_current_user
from app.db.base import Base, get_db
from app.models.audiobook import AudiobookProject
from app.models.audiobook_task import AudiobookTask
from app.models.project import Project
from app.models.user import User


class CompatTestClient:
    def __init__(self, app: FastAPI):
        self._app = app
        self._base_url = "http://testserver"

    async def _request_async(self, method: str, url: str, **kwargs) -> Response:
        transport = ASGITransport(app=self._app)
        async with AsyncClient(
            transport=transport,
            base_url=self._base_url,
            follow_redirects=True,
        ) as client:
            return await client.request(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async(method, url, **kwargs))

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)


def build_test_client() -> tuple[CompatTestClient, sessionmaker, FastAPI]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Project.__table__,
            AudiobookProject.__table__,
            AudiobookTask.__table__,
        ],
    )

    app = FastAPI()
    app.include_router(audiobook_router)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return CompatTestClient(app), session_factory, app


def seed_sse_context(session_factory) -> dict[str, int | str]:
    db = session_factory()
    try:
        owner = User(
            username="sse_owner",
            email="sse_owner@example.com",
            password_hash="hash",
            is_active=True,
        )
        other_user = User(
            username="sse_other",
            email="sse_other@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add_all([owner, other_user])
        db.flush()

        owner_project = Project(
            user_id=owner.id,
            display_no=1,
            title="SSE Owner Project",
            audio_config="{}",
            status="draft",
        )
        other_project = Project(
            user_id=other_user.id,
            display_no=2,
            title="SSE Other Project",
            audio_config="{}",
            status="draft",
        )
        db.add_all([owner_project, other_project])
        db.flush()

        owner_audiobook_project = AudiobookProject(
            project_id=owner_project.id,
            status="processing",
            total_chapters=1,
        )
        other_audiobook_project = AudiobookProject(
            project_id=other_project.id,
            status="processing",
            total_chapters=1,
        )
        db.add_all([owner_audiobook_project, other_audiobook_project])
        db.flush()

        owner_task = AudiobookTask(
            celery_task_id="sse-owner-task",
            audiobook_project_id=owner_audiobook_project.id,
            task_type="full",
            status="running",
            current_stage="tts_synthesis",
            progress=0.25,
            total_units=1,
        )
        other_task = AudiobookTask(
            celery_task_id="sse-other-task",
            audiobook_project_id=other_audiobook_project.id,
            task_type="full",
            status="running",
            current_stage="tts_synthesis",
            progress=0.5,
            total_units=1,
        )
        db.add_all([owner_task, other_task])
        db.commit()

        return {
            "owner_id": owner.id,
            "other_user_id": other_user.id,
            "owner_task_id": owner_task.celery_task_id,
            "other_task_id": other_task.celery_task_id,
            "owner_audiobook_project_id": owner_audiobook_project.id,
        }
    finally:
        db.close()


def _auth_user(user_id: int) -> User:
    return User(
        id=user_id,
        username=f"sse_auth_user_{user_id}",
        email=f"sse_auth_user_{user_id}@example.com",
        password_hash="hash",
        is_active=True,
    )


def test_sse_stream_route_allows_owner_task_and_returns_event(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_sse_context(session_factory)
    requested_task_ids: list[str] = []

    class FakeSseTracker:
        async def stream_events(self, task_id: str):
            requested_task_ids.append(task_id)
            yield "data: {\"event\":\"connected\",\"data\":{\"task_id\":\"sse-owner-task\"}}\n\n"

    monkeypatch.setattr(routes_misc, "sse_tracker", FakeSseTracker())
    app.dependency_overrides[get_current_user] = lambda: _auth_user(int(context["owner_id"]))

    response = client.get(f"/api/v1/audiobook/tasks/{context['owner_task_id']}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert "connected" in response.text
    assert requested_task_ids == [context["owner_task_id"]]


def test_sse_stream_route_does_not_subscribe_when_auth_fails(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_sse_context(session_factory)

    class FakeSseTracker:
        async def stream_events(self, task_id: str):
            raise AssertionError(f"不应订阅未鉴权任务: {task_id}")
            yield ""

    monkeypatch.setattr(routes_misc, "sse_tracker", FakeSseTracker())

    def reject_user():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")

    app.dependency_overrides[get_current_user] = reject_user

    response = client.get(f"/api/v1/audiobook/tasks/{context['owner_task_id']}/stream")

    assert response.status_code == 401
    assert response.json()["detail"] == "auth required"


def test_sse_stream_route_returns_controlled_error_event_when_tracker_fails(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_sse_context(session_factory)

    class FakeSseTracker:
        async def stream_events(self, task_id: str):
            raise RuntimeError("redis subscriber unavailable")
            yield ""

    monkeypatch.setattr(routes_misc, "sse_tracker", FakeSseTracker())
    app.dependency_overrides[get_current_user] = lambda: _auth_user(int(context["owner_id"]))

    response = client.get(f"/api/v1/audiobook/tasks/{context['owner_task_id']}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "progress_stream_unavailable" in response.text
    assert '"retryable": true' in response.text


def test_sse_stream_route_passes_heartbeat_event(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_sse_context(session_factory)

    class FakeSseTracker:
        async def stream_events(self, task_id: str):
            yield "data: {\"event\":\"connected\",\"data\":{\"task_id\":\"sse-owner-task\"}}\n\n"
            yield "data: {\"event\":\"heartbeat\",\"data\":{\"timestamp\":\"now\"}}\n\n"

    monkeypatch.setattr(routes_misc, "sse_tracker", FakeSseTracker())
    app.dependency_overrides[get_current_user] = lambda: _auth_user(int(context["owner_id"]))

    response = client.get(f"/api/v1/audiobook/tasks/{context['owner_task_id']}/stream")

    assert response.status_code == 200
    assert "connected" in response.text
    assert "heartbeat" in response.text


def test_sse_stream_route_hides_foreign_task(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_sse_context(session_factory)

    class FakeSseTracker:
        async def stream_events(self, task_id: str):
            raise AssertionError(f"不应订阅无权限任务: {task_id}")
            yield ""

    monkeypatch.setattr(routes_misc, "sse_tracker", FakeSseTracker())
    app.dependency_overrides[get_current_user] = lambda: _auth_user(int(context["owner_id"]))

    response = client.get(f"/api/v1/audiobook/tasks/{context['other_task_id']}/stream")

    assert response.status_code == 404
    assert response.json()["detail"] == f"任务不存在: {context['other_task_id']}"


def test_sse_stream_route_hides_task_for_deleted_audiobook_project(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_sse_context(session_factory)

    with session_factory() as db:
        audiobook_project = db.get(AudiobookProject, context["owner_audiobook_project_id"])
        audiobook_project.deleted_at = datetime.now(timezone.utc)
        db.commit()

    class FakeSseTracker:
        async def stream_events(self, task_id: str):
            raise AssertionError(f"不应订阅已删除项目任务: {task_id}")
            yield ""

    monkeypatch.setattr(routes_misc, "sse_tracker", FakeSseTracker())
    app.dependency_overrides[get_current_user] = lambda: _auth_user(int(context["owner_id"]))

    response = client.get(f"/api/v1/audiobook/tasks/{context['owner_task_id']}/stream")

    assert response.status_code == 404
    assert response.json()["detail"] == f"任务不存在: {context['owner_task_id']}"


def test_sse_stream_route_hides_missing_task(monkeypatch):
    client, _session_factory, app = build_test_client()

    class FakeSseTracker:
        async def stream_events(self, task_id: str):
            raise AssertionError(f"不应订阅不存在任务: {task_id}")
            yield ""

    monkeypatch.setattr(routes_misc, "sse_tracker", FakeSseTracker())
    app.dependency_overrides[get_current_user] = lambda: _auth_user(1)

    response = client.get("/api/v1/audiobook/tasks/missing-task/stream")

    assert response.status_code == 404
    assert response.json()["detail"] == "任务不存在: missing-task"
