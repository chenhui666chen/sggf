"""GUIDE 验收 17/§3.2：场景重渲染入口（revision_set_hash 校验与透传）。

覆盖：
- 携带正确 revision_set_hash → 200，`_enqueue_audiobook_task` 收到
  revision_heads_by_chapter（含三条链 head + projection），且入队发生在
  校验通过之后；
- 携带过期 revision_set_hash → 409（detail 含 current_revision_set_hash），
  不触发入队；
- 不携带 revision_set_hash → 200（向后兼容，revision_heads_by_chapter=None）；
- 无已审批剧本章节 → 400（回归既有行为）。

计费预检/冻结与任务派发均以替身隔离（本文件只验证重渲染入口合同）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for _path in (ROOT_DIR, PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import router as audiobook_router
from app.api.v1.audiobook_api import routes_projects
from app.core.security import get_current_user
from app.db.base import Base, get_db
from app.models.audiobook import (
    AudiobookProject,
    ChapterAudio,
    ChapterAudioRun,
    ChapterAudioOutput,
    SceneAudioArtifact,
    SceneEditRevision,
    SceneEditRevisionHead,
)
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.audiobook.scene_edit_revision_service import (
    compute_revision_set_hash,
    get_revision_heads_projection,
)

SEGMENTS = [
    {
        "segment_key": "seg_a",
        "type": "dialogue",
        "text": "第一段台词原文",
        "speaker": "角色甲",
    },
    {
        "segment_key": "seg_b",
        "type": "dialogue",
        "text": "第二段台词原文",
        "speaker": "角色乙",
    },
]


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
        import asyncio

        return asyncio.run(self._request_async(method, url, **kwargs))

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


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
            Chapter.__table__,
            AudiobookProject.__table__,
            ChapterAudioRun.__table__,
            ChapterAudio.__table__,
            ChapterAudioOutput.__table__,
            SceneAudioArtifact.__table__,
            SceneEditRevision.__table__,
            SceneEditRevisionHead.__table__,
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


def seed_rerender_context(session_factory, *, script_status: str = "approved"):
    db = session_factory()
    try:
        user = User(
            username="rerender_user",
            email="rerender@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add(user)
        db.flush()
        project = Project(
            user_id=user.id,
            display_no=1,
            title="Rerender Project",
            audio_config="{}",
            status="draft",
        )
        db.add(project)
        db.flush()
        chapter = Chapter(
            project_id=project.id,
            chapter_number=1,
            title="Chapter 1",
            content="Test content",
            summary="summary",
        )
        db.add(chapter)
        db.flush()
        audiobook_project = AudiobookProject(
            project_id=project.id,
            status="processing",
            total_chapters=1,
            engine_mode="seed_scene",
        )
        db.add(audiobook_project)
        db.flush()
        chapter_audio = ChapterAudio(
            audiobook_project_id=audiobook_project.id,
            chapter_id=chapter.id,
            script_status=script_status,
            script_json=json.dumps(SEGMENTS, ensure_ascii=False),
        )
        db.add(chapter_audio)
        db.commit()
        return {
            "user_id": user.id,
            "project_id": project.id,
            "chapter_id": chapter.id,
            "audiobook_project_id": audiobook_project.id,
            "chapter_audio_id": chapter_audio.id,
        }
    finally:
        db.close()


def _auth_user(user_id: int) -> User:
    return User(
        id=user_id,
        username=f"auth_user_{user_id}",
        email=f"auth_user_{user_id}@example.com",
        password_hash="hash",
        is_active=True,
    )


def patch_heavy_dependencies(monkeypatch) -> dict[str, Any]:
    """隔离计费预检/冻结与任务派发，只留重渲染入口校验与透传链路。"""
    captured: dict[str, Any] = {}

    def fake_precheck(**kwargs):
        return SimpleNamespace(estimated_yuan=1.0, cost_precheck_id="pre-1")

    def fake_ensure(payload):
        return None

    def fake_enqueue(db, **kwargs):
        captured["enqueue_kwargs"] = kwargs
        return SimpleNamespace(id=1), SimpleNamespace(id="fake-celery-task-1")

    def fake_freeze(**kwargs):
        return None

    monkeypatch.setattr(
        routes_projects, "build_audiobook_task_points_precheck", fake_precheck
    )
    monkeypatch.setattr(
        routes_projects, "_ensure_audiobook_points_precheck_passed", fake_ensure
    )
    monkeypatch.setattr(routes_projects, "_enqueue_audiobook_task", fake_enqueue)
    monkeypatch.setattr(routes_projects, "_safe_record_audiobook_billing_freeze", fake_freeze)
    return captured


def _current_set_hash(session_factory, audiobook_project_id: int, chapter_id: int) -> str:
    db = session_factory()
    try:
        heads = get_revision_heads_projection(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        )
        return compute_revision_set_hash(heads)
    finally:
        db.close()


def _post_generate(client, audiobook_project_id: int, payload: dict) -> Response:
    return client.post(
        f"/api/v1/audiobook/projects/{audiobook_project_id}/generate-audio-from-scripts",
        json=payload,
    )


def test_rerender_with_matching_revision_set_hash_passes_heads(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_rerender_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )
    captured = patch_heavy_dependencies(monkeypatch)

    current_hash = _current_set_hash(
        session_factory, context["audiobook_project_id"], context["chapter_id"]
    )
    response = _post_generate(
        client,
        context["audiobook_project_id"],
        {
            "chapter_ids": [context["chapter_id"]],
            "revision_set_hash": current_hash,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["job_id"] == "fake-celery-task-1"

    enqueue_kwargs = captured["enqueue_kwargs"]
    heads_by_chapter = enqueue_kwargs["revision_heads_by_chapter"]
    assert heads_by_chapter is not None
    chapter_heads = heads_by_chapter[context["chapter_id"]]
    assert chapter_heads["revision_set_hash"] == current_hash
    # 三条链 head 投影与完整 projection 一并透传
    for chain in ("dialogue", "director_override", "voice_binding"):
        assert chain in chapter_heads
    assert isinstance(chapter_heads["projection"], dict)
    assert enqueue_kwargs["job_type"] == "audio_from_scripts"
    assert enqueue_kwargs["chapter_ids"] == [context["chapter_id"]]


def test_rerender_with_stale_revision_set_hash_conflicts_409(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_rerender_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )
    captured = patch_heavy_dependencies(monkeypatch)

    response = _post_generate(
        client,
        context["audiobook_project_id"],
        {
            "chapter_ids": [context["chapter_id"]],
            "revision_set_hash": "stale-set-hash",
        },
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "基线已变化" in detail["message"]
    current_hash = _current_set_hash(
        session_factory, context["audiobook_project_id"], context["chapter_id"]
    )
    assert detail["current_revision_set_hash"] == current_hash
    assert "enqueue_kwargs" not in captured


def test_generate_without_revision_set_hash_stays_compatible(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_rerender_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )
    captured = patch_heavy_dependencies(monkeypatch)

    response = _post_generate(
        client,
        context["audiobook_project_id"],
        {"chapter_ids": [context["chapter_id"]]},
    )
    assert response.status_code == 200, response.text
    assert captured["enqueue_kwargs"]["revision_heads_by_chapter"] is None


def test_generate_without_approved_script_rejected_400():
    client, session_factory, app = build_test_client()
    context = seed_rerender_context(session_factory, script_status="pending")
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = _post_generate(
        client,
        context["audiobook_project_id"],
        {"chapter_ids": [context["chapter_id"]]},
    )
    assert response.status_code == 400, response.text
    assert "缺少已审批剧本" in response.json()["detail"]
