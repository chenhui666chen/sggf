import asyncio
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

from app.api.v1.script_review import get_script_review_report, get_script_segments
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


def seed_script_review_context(db):
    user = User(
        username="script_review_user",
        email="script_review@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        display_no=1,
        title="Script Review Project",
        audio_config="{}",
        status="draft",
    )
    db.add(project)
    db.flush()

    chapter = Chapter(
        project_id=project.id,
        chapter_number=1,
        title="Chapter 1",
        content="Chapter content",
        summary="summary",
    )
    db.add(chapter)
    db.flush()

    audiobook_project = AudiobookProject(
        project_id=project.id,
        status="processing",
        total_chapters=1,
    )
    db.add(audiobook_project)
    db.flush()

    chapter_audio = ChapterAudio(
        audiobook_project_id=audiobook_project.id,
        chapter_id=chapter.id,
        script_json='[{"type":"narration","text":"第一段","speaker":"旁白","emotion":"neutral"}]',
        script_review_json='{"overall_grade":"A","overall_score":95,"issues":[],"revision_suggestions":[]}',
        script_status="reviewed",
        segment_count=1,
        audio_path="audiobooks/project_1/chapter_001.mp3",
        duration=0.0,
        file_size=0,
    )
    db.add(chapter_audio)
    db.commit()

    return {
        "user": user,
        "project": project,
        "chapter": chapter,
        "audiobook_project": audiobook_project,
        "chapter_audio": chapter_audio,
    }


def test_get_script_review_report_reads_persisted_review_without_task_id():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_script_review_context(db)

        payload = asyncio.run(
            get_script_review_report(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                current_user=context["user"],
                db=db,
            )
        )

        assert payload["success"] is True
        assert payload["script_status"] == "reviewed"
        assert payload["quality_report"]["overall_grade"] == "A"
        assert "task_id" not in payload


def test_get_script_segments_reads_persisted_script_without_task_id():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_script_review_context(db)

        payload = asyncio.run(
            get_script_segments(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                current_user=context["user"],
                db=db,
            )
        )

        assert payload["success"] is True
        assert payload["script_status"] == "reviewed"
        assert payload["segment_count"] == 1
        assert payload["script_segments"][0]["text"] == "第一段"
        assert "task_id" not in payload
