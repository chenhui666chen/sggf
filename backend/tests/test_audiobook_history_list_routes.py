"""历史生成记录列表（GET /projects/by-project/{id}）字段测试。

覆盖：
- 列表返回 ``engine_mode``，供前端区分场景生成/分轨合成模式；
- 列表返回 ``audio_completed_chapters``（有 audio_path 的章节数），
  供前端区分"剧本完成、音频未生成"与"全部完成"，避免剧本-only
  批次被误读为整体完成。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
from app.core.security import get_current_user
from app.db.base import Base, get_db
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Chapter, Project
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

    def get(self, url: str, **kwargs) -> Response:
        import asyncio

        return asyncio.run(self._request_async("GET", url, **kwargs))


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
            ChapterAudio.__table__,
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


def seed_history_context(session_factory):
    """同一本小说下两个批次：场景模式剧本-only + 分轨模式音频已完成。"""
    db = session_factory()
    try:
        user = User(
            username="history_list_user",
            email="history_list@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add(user)
        db.flush()
        project = Project(
            user_id=user.id,
            display_no=1,
            title="History List Project",
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

        # 批次一：seed_scene 剧本阶段完成、音频未生成（无 audio_path）
        script_only_batch = AudiobookProject(
            project_id=project.id,
            status="completed",
            total_chapters=1,
            completed_chapters=1,
            engine_mode="seed_scene",
        )
        db.add(script_only_batch)
        db.flush()
        db.add(
            ChapterAudio(
                audiobook_project_id=script_only_batch.id,
                chapter_id=chapter.id,
                script_status="approved",
            )
        )

        # 批次二：legacy_stems 音频已生成（audio_path 落盘）
        audio_batch = AudiobookProject(
            project_id=project.id,
            status="completed",
            total_chapters=1,
            completed_chapters=1,
            total_duration=534.0,
            engine_mode="legacy_stems",
        )
        db.add(audio_batch)
        db.flush()
        db.add(
            ChapterAudio(
                audiobook_project_id=audio_batch.id,
                chapter_id=chapter.id,
                script_status="approved",
                audio_path="audiobooks/p1/chapter_1.mp3",
                duration=534.0,
            )
        )

        db.commit()
        return {
            "user_id": user.id,
            "project_id": project.id,
            "script_only_batch_id": script_only_batch.id,
            "audio_batch_id": audio_batch.id,
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


def test_history_list_exposes_engine_mode_and_audio_completion_stage():
    client, session_factory, app = build_test_client()
    context = seed_history_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(
        context["user_id"]
    )

    response = client.get(f"/api/v1/audiobook/projects/by-project/{context['project_id']}")

    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()}

    script_only = items[context["script_only_batch_id"]]
    assert script_only["engine_mode"] == "seed_scene"
    assert script_only["status"] == "completed"
    # 剧本完成但音频未生成：音频完成章节数必须为 0，前端据此区分阶段
    assert script_only["audio_completed_chapters"] == 0

    audio_done = items[context["audio_batch_id"]]
    assert audio_done["engine_mode"] == "legacy_stems"
    assert audio_done["audio_completed_chapters"] == 1
