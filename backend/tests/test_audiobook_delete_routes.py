from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import routes_delete
from app.api.v1.audiobook_api.routes_delete import (
    delete_audiobook_project,
    delete_chapter_audio,
    list_deleted_chapter_audios,
    restore_audiobook_project,
    restore_chapter_audio,
)
from app.db.base import Base
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.audiobook_delete_audit import AudiobookDeleteAudit
from app.models.audiobook_task import AudiobookTask
from app.models.project import Chapter, Project
from app.schemas.audiobook import AudiobookDeleteRequest, ChapterAudioDeleteRequest
from app.models.user import User
from app.services.audiobook import repository as audiobook_repository


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
            AudiobookTask.__table__,
            AudiobookDeleteAudit.__table__,
        ],
    )
    return session_factory


def seed_delete_context(
    db,
    *,
    username: str = "audiobook_delete_user",
    email: str = "audiobook_delete@example.com",
):
    user = User(
        username=username,
        email=email,
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        display_no=1,
        title="Delete Route Project",
        status="draft",
    )
    db.add(project)
    db.flush()

    chapter = Chapter(
        project_id=project.id,
        chapter_number=1,
        title="Chapter 1",
        content="chapter content",
    )
    db.add(chapter)
    db.flush()

    audiobook_project = AudiobookProject(
        project_id=project.id,
        status="completed",
        total_chapters=1,
        completed_chapters=1,
    )
    db.add(audiobook_project)
    db.flush()

    chapter_audio = ChapterAudio(
        audiobook_project_id=audiobook_project.id,
        chapter_id=chapter.id,
        audio_path="audiobooks/project_1/chapter_001.mp3",
        duration=10.0,
        file_size=1024,
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


def test_repository_snapshot_serializers_preserve_delete_audit_contract():
    created_at = datetime(2026, 5, 5, 1, 30, tzinfo=timezone.utc)
    updated_at = datetime(2026, 5, 5, 1, 45, tzinfo=timezone.utc)
    finished_at = datetime(2026, 5, 5, 2, 0, tzinfo=timezone.utc)
    audiobook_project = AudiobookProject(
        id=12,
        project_id=34,
        status="completed",
        tts_provider="cosyvoice-v3.5-plus",
        voice_mapping={"旁白": {"voice_id": "voice-1"}},
        enable_cache=True,
        total_chapters=3,
        completed_chapters=2,
        failed_chapters=1,
        total_duration=123.5,
        total_size=4096,
        total_cost=1.25,
        created_at=created_at,
        updated_at=updated_at,
        completed_at=None,
        deleted_at=None,
    )
    chapter_audio = ChapterAudio(
        id=56,
        audiobook_project_id=12,
        chapter_id=78,
        audio_path="audiobooks/project/chapter.mp3",
        duration=45.5,
        file_size=1024,
        segment_count=9,
        dialogue_count=4,
        narration_count=5,
        generation_time=12.3,
        tts_cost=0.33,
        cache_hit_rate=0.5,
        script_status="approved",
        created_at=created_at,
        updated_at=None,
        deleted_at=None,
    )
    task = AudiobookTask(
        id=90,
        celery_task_id="celery-90",
        audiobook_project_id=12,
        chapter_id=78,
        task_type="audio_from_scripts",
        status="completed",
        current_stage="done",
        progress=1.0,
        completed_units=9,
        total_units=9,
        detail_json={"stage": "done"},
        error_message=None,
        created_at=created_at,
        updated_at=updated_at,
        started_at=None,
        finished_at=finished_at,
    )

    assert audiobook_repository._serialize_audiobook_project_snapshot(audiobook_project) == {
        "id": 12,
        "project_id": 34,
        "status": "completed",
        "tts_provider": "cosyvoice-v3.5-plus",
        "voice_mapping": {"旁白": {"voice_id": "voice-1"}},
        "enable_cache": True,
        "total_chapters": 3,
        "completed_chapters": 2,
        "failed_chapters": 1,
        "total_duration": 123.5,
        "total_size": 4096,
        "total_cost": 1.25,
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "completed_at": None,
        "deleted_at": None,
    }
    assert audiobook_repository._serialize_chapter_audio_snapshot(chapter_audio) == {
        "id": 56,
        "audiobook_project_id": 12,
        "chapter_id": 78,
        "audio_path": "audiobooks/project/chapter.mp3",
        "duration": 45.5,
        "file_size": 1024,
        "segment_count": 9,
        "dialogue_count": 4,
        "narration_count": 5,
        "generation_time": 12.3,
        "tts_cost": 0.33,
        "cache_hit_rate": 0.5,
        "script_status": "approved",
        "created_at": created_at.isoformat(),
        "updated_at": None,
        "deleted_at": None,
    }
    assert audiobook_repository._serialize_task_snapshot(task) == {
        "id": 90,
        "celery_task_id": "celery-90",
        "audiobook_project_id": 12,
        "chapter_id": 78,
        "task_type": "audio_from_scripts",
        "status": "completed",
        "current_stage": "done",
        "progress": 1.0,
        "completed_units": 9,
        "total_units": 9,
        "detail_json": {"stage": "done"},
        "error_message": None,
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "started_at": None,
        "finished_at": finished_at.isoformat(),
    }


def test_delete_project_rejects_already_soft_deleted_project():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_delete_context(db)
        context["audiobook_project"].deleted_at = datetime.now(timezone.utc)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                delete_audiobook_project(
                    audiobook_project_id=context["audiobook_project"].id,
                    current_user=context["user"],
                    db=db,
                )
            )

        assert exc_info.value.status_code == 404
        assert db.query(AudiobookDeleteAudit).count() == 0


def test_delete_chapter_audio_rejects_soft_deleted_parent_project():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_delete_context(db)
        context["audiobook_project"].deleted_at = datetime.now(timezone.utc)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                delete_chapter_audio(
                    chapter_audio_id=context["chapter_audio"].id,
                    current_user=context["user"],
                    db=db,
                )
            )

        db.refresh(context["chapter_audio"])
        assert exc_info.value.status_code == 404
        assert context["chapter_audio"].deleted_at is None
        assert db.query(AudiobookDeleteAudit).count() == 0


def test_delete_project_uses_delete_request_schema():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_delete_context(db)

        payload = asyncio.run(
            delete_audiobook_project(
                audiobook_project_id=context["audiobook_project"].id,
                request=AudiobookDeleteRequest(
                    delete_reason="  cleanup project  ",
                    delete_files=False,
                ),
                current_user=context["user"],
                db=db,
            )
        )

        audit = db.query(AudiobookDeleteAudit).one()
        assert payload["success"] is True
        assert audit.delete_reason == "cleanup project"
        assert payload["deleted_files"] == 0


def test_delete_chapter_audio_accepts_deprecated_delete_file_field(monkeypatch):
    session_factory = build_session_factory()
    delete_call = {}

    def fake_delete_physical_files(paths):
        delete_call["called"] = True
        delete_call["path_count"] = len(paths)
        return 0, []

    monkeypatch.setattr(routes_delete, "_delete_physical_files", fake_delete_physical_files)

    with session_factory() as db:
        context = seed_delete_context(db)

        payload = asyncio.run(
            delete_chapter_audio(
                chapter_audio_id=context["chapter_audio"].id,
                request=ChapterAudioDeleteRequest(
                    delete_reason="  cleanup audio  ",
                    delete_file=True,
                ),
                current_user=context["user"],
                db=db,
            )
        )

        audit = db.query(AudiobookDeleteAudit).one()
        assert payload["success"] is True
        assert audit.delete_reason == "cleanup audio"
        assert payload["deleted_files"] == 0
        assert delete_call["called"] is True


def test_restore_chapter_audio_reads_deleted_chapter_audio_record():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_delete_context(db)
        context["chapter_audio"].deleted_at = datetime.now(timezone.utc)
        db.commit()

        payload = asyncio.run(
            restore_chapter_audio(
                chapter_audio_id=context["chapter_audio"].id,
                current_user=context["user"],
                db=db,
            )
        )

        db.refresh(context["chapter_audio"])
        assert payload["success"] is True
        assert payload["chapter_audio_id"] == context["chapter_audio"].id
        assert context["chapter_audio"].deleted_at is None


def test_restore_project_does_not_restore_previously_deleted_chapter_audio():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_delete_context(db)
        second_chapter = Chapter(
            project_id=context["project"].id,
            chapter_number=2,
            title="Chapter 2",
            content="chapter 2 content",
        )
        db.add(second_chapter)
        db.flush()

        previously_deleted_audio = ChapterAudio(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=second_chapter.id,
            audio_path="audiobooks/project_1/chapter_002.mp3",
            duration=20.0,
            file_size=2048,
            deleted_at=datetime.now(timezone.utc),
        )
        db.add(previously_deleted_audio)
        db.commit()

        delete_payload = asyncio.run(
            delete_audiobook_project(
                audiobook_project_id=context["audiobook_project"].id,
                request=AudiobookDeleteRequest(delete_files=False),
                current_user=context["user"],
                db=db,
            )
        )
        db.refresh(context["chapter_audio"])
        db.refresh(previously_deleted_audio)

        assert delete_payload["success"] is True
        assert delete_payload["affected_chapters"] == 1
        assert context["chapter_audio"].deleted_at is not None
        assert previously_deleted_audio.deleted_at is not None

        restore_payload = asyncio.run(
            restore_audiobook_project(
                audiobook_project_id=context["audiobook_project"].id,
                current_user=context["user"],
                db=db,
            )
        )
        db.refresh(context["audiobook_project"])
        db.refresh(context["chapter_audio"])
        db.refresh(previously_deleted_audio)

        assert restore_payload["success"] is True
        assert context["audiobook_project"].deleted_at is None
        assert context["chapter_audio"].deleted_at is None
        assert previously_deleted_audio.deleted_at is not None


def test_list_deleted_chapter_audios_returns_only_current_user_records():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_delete_context(db)
        other_context = seed_delete_context(
            db,
            username="other_audiobook_delete_user",
            email="other_audiobook_delete@example.com",
        )
        deleted_at = datetime.now(timezone.utc)

        context["chapter_audio"].deleted_at = deleted_at
        other_context["chapter_audio"].deleted_at = deleted_at
        db.add(
            AudiobookDeleteAudit(
                delete_type="chapter",
                target_id=context["chapter_audio"].id,
                user_id=context["user"].id,
                user_name=context["user"].username,
                delete_reason="cleanup take",
                file_count=1,
                total_size=1024,
                affected_chapters=1,
                affected_tasks=0,
                deleted_at=deleted_at,
            )
        )
        db.add(
            AudiobookDeleteAudit(
                delete_type="chapter",
                target_id=other_context["chapter_audio"].id,
                user_id=other_context["user"].id,
                user_name=other_context["user"].username,
                delete_reason="other cleanup",
                file_count=1,
                total_size=2048,
                affected_chapters=1,
                affected_tasks=0,
                deleted_at=deleted_at,
            )
        )
        db.commit()

        payload = asyncio.run(
            list_deleted_chapter_audios(
                current_user=context["user"],
                db=db,
            )
        )

        assert payload["success"] is True
        assert payload["count"] == 1
        assert len(payload["chapter_audios"]) == 1

        item = payload["chapter_audios"][0]
        assert item["chapter_audio_id"] == context["chapter_audio"].id
        assert item["audiobook_project_id"] == context["audiobook_project"].id
        assert item["project_id"] == context["project"].id
        assert item["project_title"] == "Delete Route Project"
        assert item["chapter_id"] == context["chapter"].id
        assert item["chapter_number"] == 1
        assert item["chapter_title"] == "Chapter 1"
        assert item["delete_reason"] == "cleanup take"
        assert item["file_size"] == 1024
        assert item["total_size"] == 1024
