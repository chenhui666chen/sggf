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

from app.api.v1.audiobook_api import routes_segment_preview, routes_segment_regen
from app.api.v1.audiobook_api.routes_review import get_chapter_review_status
from app.api.v1.audiobook_api.routes_segment_preview import preview_script_segment_audio
from app.api.v1.audiobook_api.routes_segment_regen import regenerate_segment, review_segment
from app.db.base import Base
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Chapter, Project
from app.models.user import User
from app.schemas.audiobook import ScriptSegmentPreviewRequest, SegmentRegenerateRequest, SegmentReviewRequest


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


def seed_segment_context(db):
    user = User(
        username="segment_regen_user",
        email="segment_regen@example.com",
        password_hash="hash",
        is_active=True,
    )
    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        display_no=1,
        title="Segment Regen Project",
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
        script_json=json.dumps(
            [
                {"type": "narration", "speaker": "narrator", "text": "First segment.", "emotion": "neutral"},
                {"type": "dialogue", "speaker": "Alice", "text": "Second segment.", "emotion": "happy"},
            ],
            ensure_ascii=False,
        ),
        script_status="reviewed",
        segment_count=2,
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


def test_review_segment_persists_review_for_existing_segment():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)

        payload = asyncio.run(
            review_segment(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                segment_index=1,
                request=SegmentReviewRequest(quality_score=4.5, notes="ok", needs_regenerate=False),
                current_user=context["user"],
                db=db,
            )
        )

        db.refresh(context["chapter_audio"])
        review_data = json.loads(context["chapter_audio"].segment_reviews_json)

        assert payload["success"] is True
        assert payload["segment_index"] == 1
        assert set(review_data) == {"1"}
        assert review_data["1"]["quality_score"] == 4.5
        assert review_data["1"]["notes"] == "ok"
        assert review_data["1"]["needs_regenerate"] is False
        assert review_data["1"]["reviewed_by"] == context["user"].id
        assert review_data["1"]["reviewed_at"]


def test_review_segment_rejects_unknown_segment_index_without_writing_review():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                review_segment(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=9,
                    request=SegmentReviewRequest(quality_score=1.0, notes="bad", needs_regenerate=True),
                    current_user=context["user"],
                    db=db,
                )
            )

        assert exc_info.value.status_code == 404
        assert context["chapter_audio"].segment_reviews_json is None


def test_review_segment_rejects_body_path_segment_index_mismatch():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                review_segment(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=0,
                    request=SegmentReviewRequest(
                        segment_index=1,
                        quality_score=4.0,
                        notes="mismatch",
                        needs_regenerate=False,
                    ),
                    current_user=context["user"],
                    db=db,
                )
            )

        assert exc_info.value.status_code == 400
        assert context["chapter_audio"].segment_reviews_json is None


def test_review_segment_replaces_non_dict_review_payload():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)
        context["chapter_audio"].segment_reviews_json = "[]"
        db.commit()

        payload = asyncio.run(
            review_segment(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                segment_index=0,
                request=SegmentReviewRequest(quality_score=3.0, notes="recovered", needs_regenerate=False),
                current_user=context["user"],
                db=db,
            )
        )

        db.refresh(context["chapter_audio"])
        review_data = json.loads(context["chapter_audio"].segment_reviews_json)

        assert payload["success"] is True
        assert set(review_data) == {"0"}
        assert review_data["0"]["notes"] == "recovered"


def test_review_status_ignores_reviews_for_unknown_segments():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)
        context["chapter_audio"].segment_reviews_json = json.dumps(
            {
                "0": {"quality_score": 5.0, "needs_regenerate": True},
                "9": {"quality_score": 1.0, "needs_regenerate": True},
                "bad": {"quality_score": 2.0, "needs_regenerate": True},
            }
        )
        db.commit()

        payload = asyncio.run(
            get_chapter_review_status(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                current_user=context["user"],
                db=db,
            )
        )

        assert payload["total_segments"] == 2
        assert payload["reviewed_segments"] == 1
        assert payload["avg_quality_score"] == 5.0
        assert payload["flagged_segments"] == [0]


def test_regenerate_segment_uses_current_qwen_default_voice_when_missing_voice(monkeypatch):
    session_factory = build_session_factory()
    synthesize_call = {}

    async def fake_synthesize_speech(**kwargs):
        synthesize_call.update(kwargs)
        return b"ID3fake-audio"

    def fake_save_segment_audio_map(**kwargs):
        assert kwargs["audio_map"] == {0: b"ID3fake-audio"}
        return {
            "storage_driver": "local_fs",
            "cached_audio_paths": {0: "data/audiobook/temp-segments/test/chapter_1/segment.mp3"},
            "segments": {},
        }

    monkeypatch.setattr(routes_segment_regen, "runtime_synthesize_speech", fake_synthesize_speech)
    monkeypatch.setattr(routes_segment_regen, "save_segment_audio_map", fake_save_segment_audio_map)

    with session_factory() as db:
        context = seed_segment_context(db)

        payload = asyncio.run(
            regenerate_segment(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                segment_index=0,
                request=SegmentRegenerateRequest(),
                current_user=context["user"],
                db=db,
            )
        )

        db.refresh(context["chapter_audio"])
        segments = json.loads(context["chapter_audio"].script_json)

        assert payload["success"] is True
        assert synthesize_call["model_id"] == "qwen3-tts-instruct-flash"
        assert synthesize_call["voice_params"]["speaker"] == "Neil"
        assert synthesize_call["voice_params"]["segment_speaker"] == "narrator"
        assert segments[0]["regenerated"] is True
        assert segments[0]["audio_path"].endswith("segment.mp3")


def test_regenerate_segment_uses_minimax_default_voice_when_missing_voice(monkeypatch):
    session_factory = build_session_factory()
    synthesize_call = {}

    async def fake_synthesize_speech(**kwargs):
        synthesize_call.update(kwargs)
        return b"ID3minimax-audio"

    def fake_save_segment_audio_map(**kwargs):
        return {
            "storage_driver": "local_fs",
            "cached_audio_paths": {0: "data/audiobook/temp-segments/test/chapter_1/minimax.mp3"},
            "segments": {},
        }

    monkeypatch.setattr(routes_segment_regen, "runtime_synthesize_speech", fake_synthesize_speech)
    monkeypatch.setattr(routes_segment_regen, "save_segment_audio_map", fake_save_segment_audio_map)

    with session_factory() as db:
        context = seed_segment_context(db)

        payload = asyncio.run(
            regenerate_segment(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                segment_index=0,
                request=SegmentRegenerateRequest(tts_model="MiniMax/speech-2.8-hd"),
                current_user=context["user"],
                db=db,
            )
        )

        assert payload["success"] is True
        assert synthesize_call["model_id"] == "minimax-speech-2.8-hd"
        assert synthesize_call["voice_params"]["speaker"] == "male-qn-qingse"


def test_regenerate_segment_requires_explicit_cosyvoice_voice_when_missing_voice():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                regenerate_segment(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=0,
                    request=SegmentRegenerateRequest(tts_model="cosyvoice-v3.5-plus"),
                    current_user=context["user"],
                    db=db,
                )
            )

        assert exc_info.value.status_code == 400


def test_preview_segment_uses_tts_retry_config(monkeypatch):
    session_factory = build_session_factory()
    synthesize_call = {}

    async def fake_synthesize_speech(**kwargs):
        synthesize_call.update(kwargs)
        return b"ID3preview-audio"

    monkeypatch.setattr(routes_segment_preview, "runtime_synthesize_speech", fake_synthesize_speech)

    with session_factory() as db:
        context = seed_segment_context(db)

        response = asyncio.run(
            preview_script_segment_audio(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                request=ScriptSegmentPreviewRequest(
                    segment={
                        "type": "narration",
                        "speaker": "narrator",
                        "text": "Preview segment.",
                        "emotion": "neutral",
                    },
                    tts_model="qwen3-tts-instruct-flash",
                    preview_type="voice",
                ),
                current_user=context["user"],
                db=db,
            )
        )

        retry_config = synthesize_call["retry_config"]

        assert response.media_type == "audio/mpeg"
        assert response.body == b"ID3preview-audio"
        assert retry_config.base_delay == 1.0
        assert retry_config.max_delay == 8.0


def test_preview_segment_preserves_minimax_model_selection(monkeypatch):
    session_factory = build_session_factory()
    synthesize_call = {}

    async def fake_synthesize_speech(**kwargs):
        synthesize_call.update(kwargs)
        return b"ID3minimax-preview"

    monkeypatch.setattr(routes_segment_preview, "runtime_synthesize_speech", fake_synthesize_speech)

    with session_factory() as db:
        context = seed_segment_context(db)

        response = asyncio.run(
            preview_script_segment_audio(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                request=ScriptSegmentPreviewRequest(
                    segment={
                        "type": "narration",
                        "speaker": "narrator",
                        "text": "Preview segment.",
                        "emotion": "neutral",
                    },
                    tts_model="MiniMax/speech-2.8-hd",
                    preview_type="voice",
                ),
                current_user=context["user"],
                db=db,
            )
        )

        assert response.body == b"ID3minimax-preview"
        assert synthesize_call["model_id"] == "minimax-speech-2.8-hd"
        assert synthesize_call["voice_params"]["speaker"] == "male-qn-qingse"
