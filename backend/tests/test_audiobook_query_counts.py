from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api.dependencies import OwnedAudiobookProject
from app.api.v1.audiobook_api.routes_projects import list_user_audiobook_projects
from app.api.v1.audiobook_api.routes_subtitle import (
    _parse_browser_player_segments,
    get_browser_player_data,
)
from app.db.base import Base
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Chapter, Project
from app.models.user import User


def build_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
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
    return session_factory


@contextmanager
def count_select_statements(db):
    engine = db.get_bind()
    counter = {"selects": 0}

    def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            counter["selects"] += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def seed_user_audiobook_projects(db, *, project_count: int = 25):
    user = User(
        username="query_count_user",
        email="query_count@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    for display_no in range(1, project_count + 1):
        project = Project(
            user_id=user.id,
            display_no=display_no,
            title=f"Project {display_no}",
            description=f"Description {display_no}",
            status="draft",
        )
        db.add(project)
        db.flush()
        db.add(
            AudiobookProject(
                project_id=project.id,
                status="completed",
                total_chapters=1,
                completed_chapters=1,
                total_duration=display_no * 10,
            )
        )

    db.commit()
    return user


def seed_browser_player_project(db, *, chapter_count: int = 50):
    user = User(
        username="browser_query_count_user",
        email="browser_query_count@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        display_no=1,
        title="Browser Query Count Project",
        status="draft",
    )
    db.add(project)
    db.flush()

    audiobook_project = AudiobookProject(
        project_id=project.id,
        status="completed",
        total_chapters=chapter_count,
        completed_chapters=chapter_count,
        total_duration=chapter_count * 60,
    )
    db.add(audiobook_project)
    db.flush()

    for chapter_number in range(1, chapter_count + 1):
        chapter = Chapter(
            project_id=project.id,
            chapter_number=chapter_number,
            title=f"Chapter {chapter_number}",
            content="content",
        )
        db.add(chapter)
        db.flush()
        db.add(
            ChapterAudio(
                audiobook_project_id=audiobook_project.id,
                chapter_id=chapter.id,
                audio_path=f"audiobooks/project_1/chapter_{chapter_number:03d}.mp3",
                duration=60.0,
                file_size=1024,
            )
        )

    db.commit()
    return user, project, audiobook_project


def test_list_user_audiobook_projects_query_count_is_not_per_project():
    session_factory = build_session_factory()

    with session_factory() as db:
        user = seed_user_audiobook_projects(db, project_count=25)

        with count_select_statements(db) as counter:
            payload = asyncio.run(
                list_user_audiobook_projects(
                    current_user=user,
                    db=db,
                )
            )

        assert len(payload) == 25
        assert counter["selects"] <= 2


def test_browser_player_query_count_is_not_per_chapter():
    session_factory = build_session_factory()

    with session_factory() as db:
        user, project, audiobook_project = seed_browser_player_project(db, chapter_count=50)
        owned = OwnedAudiobookProject(
            audiobook_project=audiobook_project,
            project=project,
            current_user=user,
            db=db,
        )

        with count_select_statements(db) as counter:
            payload = asyncio.run(
                get_browser_player_data(
                    audiobook_project_id=audiobook_project.id,
                    owned=owned,
                )
            )

        assert payload["audiobook_project_id"] == audiobook_project.id
        assert len(payload["chapters"]) == 50
        assert counter["selects"] <= 2


def test_browser_player_segment_parser_logs_invalid_script_json(caplog):
    with caplog.at_level("WARNING", logger="app.api.v1.audiobook_api.routes_subtitle"):
        segments = _parse_browser_player_segments(
            "{bad-json",
            audiobook_project_id=12,
            chapter_id=34,
        )

    assert segments == []
    assert "浏览器播放器忽略无效章节剧本 JSON" in caplog.text
    assert "audiobook_project_id=12" in caplog.text
    assert "chapter_id=34" in caplog.text


def test_browser_player_segment_parser_rejects_non_array_script_json(caplog):
    with caplog.at_level("WARNING", logger="app.api.v1.audiobook_api.routes_subtitle"):
        segments = _parse_browser_player_segments(
            '{"segments": []}',
            audiobook_project_id=12,
            chapter_id=34,
        )

    assert segments == []
    assert "浏览器播放器忽略非数组章节剧本 JSON" in caplog.text
    assert "payload_type=dict" in caplog.text
