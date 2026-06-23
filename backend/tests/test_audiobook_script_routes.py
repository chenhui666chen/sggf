from __future__ import annotations

import asyncio
import json
import os
import sys
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

from app.api.v1.audiobook_api import routes_script
from app.api.v1.audiobook_api.dependencies import OwnedAudiobookProject
from app.db.base import Base
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from app.models.project import Chapter, Project
from app.models.user import User
from app.schemas.audiobook import ChapterScriptUpdateRequest


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


def seed_script_context(db):
    user = User(
        username="script_route_user",
        email="script_route@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        display_no=1,
        title="Script Route Project",
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


def test_script_routes_do_not_keep_broad_json_exception_handlers():
    source = Path(routes_script.__file__).read_text(encoding="utf-8")

    assert "except Exception as e" not in source
    assert "except json.JSONDecodeError" in source
    assert "except (TypeError, ValueError)" in source


def test_get_chapter_script_does_not_swallow_unexpected_json_errors(monkeypatch):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_script_context(db)
        owned = OwnedAudiobookProject(
            audiobook_project=context["audiobook_project"],
            project=context["project"],
            current_user=context["user"],
            db=db,
        )

        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(routes_script.json, "loads", boom)

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(
                routes_script.get_chapter_script(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    owned=owned,
                )
            )


def test_get_chapter_script_does_not_reuse_history_when_current_project_has_no_script():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_script_context(db)
        old_script = json.loads(context["chapter_audio"].script_json)
        old_project = context["audiobook_project"]
        new_project = AudiobookProject(
            project_id=context["project"].id,
            status="processing",
            total_chapters=1,
        )
        db.add(new_project)
        db.commit()

        owned = OwnedAudiobookProject(
            audiobook_project=new_project,
            project=context["project"],
            current_user=context["user"],
            db=db,
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                routes_script.get_chapter_script(
                    audiobook_project_id=new_project.id,
                    chapter_id=context["chapter"].id,
                    owned=owned,
                )
            )

        assert exc_info.value.status_code == 404
        assert "请先生成剧本" in exc_info.value.detail
        assert db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == new_project.id,
            ChapterAudio.chapter_id == context["chapter"].id,
        ).first() is None
        assert json.loads(context["chapter_audio"].script_json) == old_script
        assert old_project.id != new_project.id


def test_get_chapter_script_returns_chapter_audio_timeline_for_editor_playback():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_script_context(db)
        segment_timings = [
            {"index": 0, "start": 1.25, "end": 3.75, "duration": 2.5},
        ]
        db.add(
            ChapterAudioRun(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                run_type="audio_from_scripts",
                status="completed",
                current_stage="completed",
                progress=1.0,
                checkpoint_json={
                    "segment_timings": segment_timings,
                    "cached_audio_paths": {},
                },
                resumable=False,
            )
        )
        db.commit()

        owned = OwnedAudiobookProject(
            audiobook_project=context["audiobook_project"],
            project=context["project"],
            current_user=context["user"],
            db=db,
        )

        payload = asyncio.run(
            routes_script.get_chapter_script(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                owned=owned,
            )
        )

        assert payload["chapter_audio_available"] is True
        assert payload["chapter_audio_url"] == (
            f"/api/v1/audiobook/download/{context['audiobook_project'].id}/{context['chapter'].id}"
        )
        assert payload["segment_timings"] == segment_timings


def test_get_chapter_script_keeps_completed_timeline_when_newer_run_is_running():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_script_context(db)
        completed_timings = [
            {"index": 0, "start": 0.0, "end": 2.0, "duration": 2.0},
        ]
        db.add(
            ChapterAudioRun(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                run_type="audio_from_scripts",
                status="completed",
                current_stage="completed",
                progress=1.0,
                checkpoint_json={"segment_timings": completed_timings},
                resumable=False,
            )
        )
        db.flush()
        db.add(
            ChapterAudioRun(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                run_type="audio_from_scripts",
                status="running",
                current_stage="tts_synthesis",
                progress=0.25,
                checkpoint_json={"segment_timings": []},
                resumable=True,
            )
        )
        db.commit()

        owned = OwnedAudiobookProject(
            audiobook_project=context["audiobook_project"],
            project=context["project"],
            current_user=context["user"],
            db=db,
        )

        payload = asyncio.run(
            routes_script.get_chapter_script(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                owned=owned,
            )
        )

        assert payload["segment_timings"] == completed_timings


def test_get_chapter_script_uses_full_generation_timeline_for_completed_chapter_audio():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_script_context(db)
        full_generation_timings = [
            {"index": 0, "start": 4.0, "end": 6.5, "duration": 2.5},
        ]
        db.add(
            ChapterAudioRun(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                run_type="full",
                status="completed",
                current_stage="completed",
                progress=1.0,
                checkpoint_json={"segment_timings": full_generation_timings},
                resumable=False,
            )
        )
        db.commit()

        owned = OwnedAudiobookProject(
            audiobook_project=context["audiobook_project"],
            project=context["project"],
            current_user=context["user"],
            db=db,
        )

        payload = asyncio.run(
            routes_script.get_chapter_script(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                owned=owned,
            )
        )

        assert payload["chapter_audio_available"] is True
        assert payload["segment_timings"] == full_generation_timings


def test_update_chapter_script_does_not_swallow_unexpected_json_errors(monkeypatch):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_script_context(db)
        owned = OwnedAudiobookProject(
            audiobook_project=context["audiobook_project"],
            project=context["project"],
            current_user=context["user"],
            db=db,
        )
        request = ChapterScriptUpdateRequest(
            script_segments=[{"text": "第一段"}],
            script_status="reviewed",
        )

        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(routes_script.json, "dumps", boom)

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(
                routes_script.update_chapter_script(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    request=request,
                    owned=owned,
                )
            )
