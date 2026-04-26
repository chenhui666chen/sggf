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
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.audiobook.task_support import build_generation_checkpoint_payload


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
            ChapterAudioRun.__table__,
        ],
    )
    return session_factory


def seed_runtime_context(db):
    user = User(
        username="runtime_truth_user",
        email="runtime_truth@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        display_no=1,
        title="Runtime Truth Project",
        audio_config="{}",
        status="draft",
    )
    db.add(project)
    db.flush()

    chapter = Chapter(
        project_id=project.id,
        chapter_number=1,
        title="Chapter 1",
        content="Test chapter content",
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
        segment_count=4,
        audio_path="audiobooks/project_1/chapter_001.mp3",
        duration=0.0,
        file_size=0,
        script_status="pending",
    )
    db.add(chapter_audio)
    db.commit()
    db.refresh(chapter_audio)

    return {
        "user": user,
        "project": project,
        "chapter": chapter,
        "audiobook_project": audiobook_project,
        "chapter_audio": chapter_audio,
    }


def test_checkpoint_payload_without_run_has_no_resume_material():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)

        payload = build_generation_checkpoint_payload(
            chapter_id=context["chapter"].id,
            chapter_audio=context["chapter_audio"],
            run_type="full",
            db=db,
            audiobook_project_id=context["audiobook_project"].id,
        )

        assert payload["checkpoint_source"] == "none"
        assert payload["can_resume"] is False
        assert payload["completed_segments"] == 0
        assert payload["completed_segment_indices"] == []
        assert payload["cached_audio_paths"] == {}
        assert "no_checkpoint_material" in payload["resume_blockers"]


def test_checkpoint_payload_prefers_chapter_run_checkpoint_json():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)

        run = ChapterAudioRun(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="full",
            celery_task_id="celery-run-1",
            status="failed",
            current_stage="tts_synthesis",
            progress=0.5,
            completed_segment_count=1,
            total_segment_count=4,
            tts_model="qwen3-tts-instruct-flash",
            output_format="mp3",
            narration_style="professional",
            narration_style_prompt=None,
            resumable=True,
            checkpoint_json={
                "schema_version": 1,
                "status": "failed",
                "current_stage": "tts_synthesis",
                "total_segments": 4,
                "completed_segment_count": 1,
                "completed_segment_indices": [0],
                "cached_audio_paths": {},
                "segments": {},
                "tts_model": "qwen3-tts-instruct-flash",
                "output_format": "mp3",
            },
        )
        db.add(run)
        db.commit()

        payload = build_generation_checkpoint_payload(
            chapter_id=context["chapter"].id,
            chapter_audio=context["chapter_audio"],
            run_type="full",
            db=db,
            audiobook_project_id=context["audiobook_project"].id,
        )

        assert payload["checkpoint_source"] == "chapter_audio_run"
        assert payload["run_id"] == run.id
        assert payload["completed_segments"] == 1
        assert payload["completed_segment_indices"] == [0]
        assert payload["resume_validation_mode"] == "strict"
