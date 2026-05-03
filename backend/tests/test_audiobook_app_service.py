from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Chapter, Project
from app.models.user import User
from app.schemas.audiobook import AudiobookProjectCreate
from app.services.audiobook.app_service import (
    AudiobookAppService,
    PreparedAudiobookProjectCreation,
)


def build_session_factory():
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
    return session_factory


def seed_project_with_existing_script(db):
    user = User(
        username="app_service_user",
        email="app_service@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        display_no=1,
        title="App Service Project",
        audio_config="{}",
        status="draft",
    )
    db.add(project)
    db.flush()

    chapter = Chapter(
        project_id=project.id,
        chapter_number=1,
        title="Chapter 1",
        content="chapter content",
        summary="summary",
    )
    db.add(chapter)
    db.flush()

    old_audiobook_project = AudiobookProject(
        project_id=project.id,
        status="completed",
        total_chapters=1,
    )
    db.add(old_audiobook_project)
    db.flush()

    old_script = [
        {"type": "narration", "speaker": "narrator", "text": "旧剧本"},
    ]
    db.add(
        ChapterAudio(
            audiobook_project_id=old_audiobook_project.id,
            chapter_id=chapter.id,
            script_json=json.dumps(old_script, ensure_ascii=False),
            script_review_json=json.dumps({"overall_score": 8}, ensure_ascii=False),
            script_status="approved",
            segment_count=1,
            narration_count=1,
            dialogue_count=0,
            character_count=0,
        )
    )
    db.commit()

    return user, project, chapter, old_script


def build_create_request(project_id: int, chapter_id: int, *, force_regenerate_script: bool) -> AudiobookProjectCreate:
    return AudiobookProjectCreate(
        project_id=project_id,
        chapter_ids=[chapter_id],
        generation_mode="script_only",
        force_regenerate_script=force_regenerate_script,
    )


def create_audiobook_project_with_request(db, user, project, chapter, request):
    service = AudiobookAppService(db=db, current_user=user)
    service._auto_assign_voices = lambda *args, **kwargs: None
    return service.create_audiobook_project(
        request,
        prepared=PreparedAudiobookProjectCreation(
            project=project,
            chapters=[chapter],
        ),
    )


def test_create_audiobook_project_reuses_existing_script_by_default():
    session_factory = build_session_factory()

    with session_factory() as db:
        user, project, chapter, old_script = seed_project_with_existing_script(db)
        audiobook_project = create_audiobook_project_with_request(
            db,
            user,
            project,
            chapter,
            build_create_request(project.id, chapter.id, force_regenerate_script=False),
        )

        cloned_audio = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project.id,
            ChapterAudio.chapter_id == chapter.id,
        ).first()

        assert cloned_audio is not None
        assert json.loads(cloned_audio.script_json) == old_script
        assert cloned_audio.script_status == "approved"


def test_create_audiobook_project_skips_script_reuse_when_force_regenerate_requested():
    session_factory = build_session_factory()

    with session_factory() as db:
        user, project, chapter, _old_script = seed_project_with_existing_script(db)
        audiobook_project = create_audiobook_project_with_request(
            db,
            user,
            project,
            chapter,
            build_create_request(project.id, chapter.id, force_regenerate_script=True),
        )

        cloned_audio = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project.id,
            ChapterAudio.chapter_id == chapter.id,
        ).first()

        assert cloned_audio is None
