from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import router as audiobook_router
from app.api.v1.audiobook_api.routes_download import STREAM_TOKEN_PURPOSE
from app.core.config import settings
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


def seed_stream_context(session_factory, audio_file: Path) -> dict[str, int]:
    db = session_factory()
    try:
        owner = User(
            username="stream_owner",
            email="stream_owner@example.com",
            password_hash="hash",
            is_active=True,
        )
        other_user = User(
            username="stream_other",
            email="stream_other@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add_all([owner, other_user])
        db.flush()

        owner_project = Project(
            user_id=owner.id,
            display_no=1,
            title="Stream Owner Project",
            audio_config="{}",
            status="draft",
        )
        other_project = Project(
            user_id=other_user.id,
            display_no=2,
            title="Stream Other Project",
            audio_config="{}",
            status="draft",
        )
        db.add_all([owner_project, other_project])
        db.flush()

        owner_chapter = Chapter(
            project_id=owner_project.id,
            chapter_number=1,
            title="Owner Chapter",
            content="owner content",
            summary="summary",
        )
        other_chapter = Chapter(
            project_id=other_project.id,
            chapter_number=1,
            title="Other Chapter",
            content="other content",
            summary="summary",
        )
        db.add_all([owner_chapter, other_chapter])
        db.flush()

        owner_audiobook_project = AudiobookProject(
            project_id=owner_project.id,
            status="completed",
            total_chapters=1,
        )
        other_audiobook_project = AudiobookProject(
            project_id=other_project.id,
            status="completed",
            total_chapters=1,
        )
        db.add_all([owner_audiobook_project, other_audiobook_project])
        db.flush()

        db.add_all(
            [
                ChapterAudio(
                    audiobook_project_id=owner_audiobook_project.id,
                    chapter_id=owner_chapter.id,
                    audio_path=str(audio_file),
                    duration=1.0,
                    file_size=audio_file.stat().st_size,
                    script_status="approved",
                ),
                ChapterAudio(
                    audiobook_project_id=other_audiobook_project.id,
                    chapter_id=other_chapter.id,
                    audio_path=str(audio_file),
                    duration=1.0,
                    file_size=audio_file.stat().st_size,
                    script_status="approved",
                ),
            ]
        )
        db.commit()

        return {
            "owner_id": owner.id,
            "other_user_id": other_user.id,
            "owner_audiobook_project_id": owner_audiobook_project.id,
            "other_audiobook_project_id": other_audiobook_project.id,
            "owner_chapter_id": owner_chapter.id,
            "other_chapter_id": other_chapter.id,
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


def test_stream_url_route_creates_signed_url_and_stream_accepts_it(tmp_path):
    audio_file = tmp_path / "chapter.mp3"
    audio_file.write_bytes(b"ID3signed-stream-audio")
    client, session_factory, app = build_test_client()
    context = seed_stream_context(session_factory, audio_file)

    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["owner_id"])

    response = client.get(
        "/api/v1/audiobook/stream-url/"
        f"{context['owner_audiobook_project_id']}/{context['owner_chapter_id']}"
    )

    assert response.status_code == 200
    payload = response.json()
    stream_url = payload["stream_url"]
    parsed_stream_url = urlparse(stream_url)
    play_token = parse_qs(parsed_stream_url.query)["play_token"][0]
    token_payload = jwt.decode(
        play_token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )

    assert parsed_stream_url.path == (
        "/api/v1/audiobook/stream/"
        f"{context['owner_audiobook_project_id']}/{context['owner_chapter_id']}"
    )
    assert payload["expires_in_seconds"] == 7200
    assert token_payload["purpose"] == STREAM_TOKEN_PURPOSE
    assert int(token_payload["sub"]) == context["owner_id"]
    assert token_payload["audiobook_project_id"] == context["owner_audiobook_project_id"]
    assert token_payload["chapter_id"] == context["owner_chapter_id"]

    stream_response = client.get(stream_url)

    assert stream_response.status_code == 200
    assert stream_response.content == b"ID3signed-stream-audio"
    assert stream_response.headers["content-disposition"] == "inline"
    assert stream_response.headers["content-type"].startswith("audio/mpeg")


def test_stream_route_requires_bearer_or_signed_token(tmp_path):
    audio_file = tmp_path / "chapter.mp3"
    audio_file.write_bytes(b"ID3missing-credentials")
    client, session_factory, _app = build_test_client()
    context = seed_stream_context(session_factory, audio_file)

    response = client.get(
        "/api/v1/audiobook/stream/"
        f"{context['owner_audiobook_project_id']}/{context['owner_chapter_id']}"
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing stream credentials"


def test_stream_route_rejects_signed_token_for_non_owner_project(tmp_path):
    audio_file = tmp_path / "chapter.mp3"
    audio_file.write_bytes(b"ID3cross-user")
    client, session_factory, _app = build_test_client()
    context = seed_stream_context(session_factory, audio_file)
    token = jwt.encode(
        {
            "sub": str(context["owner_id"]),
            "purpose": STREAM_TOKEN_PURPOSE,
            "audiobook_project_id": context["other_audiobook_project_id"],
            "chapter_id": context["other_chapter_id"],
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )

    response = client.get(
        "/api/v1/audiobook/stream/"
        f"{context['other_audiobook_project_id']}/{context['other_chapter_id']}"
        f"?play_token={token}"
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限访问"


def test_stream_route_rejects_expired_signed_token(tmp_path):
    audio_file = tmp_path / "chapter.mp3"
    audio_file.write_bytes(b"ID3expired-token")
    client, session_factory, _app = build_test_client()
    context = seed_stream_context(session_factory, audio_file)
    token = jwt.encode(
        {
            "sub": str(context["owner_id"]),
            "purpose": STREAM_TOKEN_PURPOSE,
            "audiobook_project_id": context["owner_audiobook_project_id"],
            "chapter_id": context["owner_chapter_id"],
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )

    response = client.get(
        "/api/v1/audiobook/stream/"
        f"{context['owner_audiobook_project_id']}/{context['owner_chapter_id']}"
        f"?play_token={token}"
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid stream token"


def test_stream_route_rejects_malformed_signed_token_subject(tmp_path):
    audio_file = tmp_path / "chapter.mp3"
    audio_file.write_bytes(b"ID3malformed-sub")
    client, session_factory, _app = build_test_client()
    context = seed_stream_context(session_factory, audio_file)
    token = jwt.encode(
        {
            "sub": "not-a-user-id",
            "purpose": STREAM_TOKEN_PURPOSE,
            "audiobook_project_id": context["owner_audiobook_project_id"],
            "chapter_id": context["owner_chapter_id"],
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )

    response = client.get(
        "/api/v1/audiobook/stream/"
        f"{context['owner_audiobook_project_id']}/{context['owner_chapter_id']}"
        f"?play_token={token}"
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid stream token"
