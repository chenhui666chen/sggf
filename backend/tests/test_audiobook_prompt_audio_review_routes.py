from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import router as audiobook_router
from app.core.security import get_current_user
from app.db.base import Base, get_db
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.audiobook_task import AudiobookTask
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.audiobook.prompt_audio_asr_provider import PromptAudioAsrResult
from app.services.audiobook.prompt_audio_transcript_runner import (
    execute_prompt_audio_transcript,
)
from app.services.audiobook.voice_identity_policy import (
    VOICE_IDENTITY_POLICY_VERSION,
)


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

    def patch(self, url: str, **kwargs) -> Response:
        return self.request("PATCH", url, **kwargs)

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
            ChapterAudio.__table__,
            AudiobookTask.__table__,
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


def _prompt_audio_quality_payload() -> dict:
    return {
        "overall_score": 91,
        "prompt_audio_quality": {
            "available": True,
            "coverage": {
                "segments_count": 2,
                "audio_segments_count": 2,
                "missing_audio_count": 0,
                "provider_prompt_snapshot_count": 2,
                "inline_tag_strategy_count": 2,
                "manual_review_pending_count": 2,
            },
            "by_model": {
                "minimax-speech-2.8-hd": {
                    "model_family": "minimax",
                    "segments_count": 1,
                    "audio_segments_count": 1,
                    "missing_audio_count": 0,
                    "provider_prompt_snapshot_count": 1,
                    "inline_tag_strategy_count": 1,
                    "use_tag_parser_count": 1,
                    "tag_count": 2,
                    "manual_review_segment_indices": [0],
                    "manual_review_fields": {
                        "tag_parse_success": None,
                        "text_contamination": None,
                        "score": None,
                    },
                },
                "doubao-tts": {
                    "model_family": "doubao",
                    "segments_count": 1,
                    "audio_segments_count": 1,
                    "missing_audio_count": 0,
                    "provider_prompt_snapshot_count": 1,
                    "inline_tag_strategy_count": 1,
                    "use_tag_parser_count": 1,
                    "tag_count": 1,
                    "manual_review_segment_indices": [1],
                    "manual_review_fields": {
                        "tag_parse_success": False,
                        "text_contamination": True,
                        "score": 2.0,
                    },
                },
            },
        },
    }


def seed_prompt_audio_review_context(session_factory) -> dict[str, int]:
    db = session_factory()
    try:
        owner = User(
            username="prompt_audio_owner",
            email="prompt-audio-owner@example.com",
            password_hash="hash",
            is_active=True,
        )
        other_user = User(
            username="prompt_audio_other",
            email="prompt-audio-other@example.com",
            password_hash="hash",
            is_active=True,
        )
        db.add_all([owner, other_user])
        db.flush()

        owner_project = Project(
            user_id=owner.id,
            display_no=1,
            title="Prompt Audio Owner Project",
            audio_config="{}",
            status="draft",
        )
        other_project = Project(
            user_id=other_user.id,
            display_no=2,
            title="Prompt Audio Other Project",
            audio_config="{}",
            status="draft",
        )
        db.add_all([owner_project, other_project])
        db.flush()

        chapter = Chapter(
            project_id=owner_project.id,
            chapter_number=1,
            title="Chapter 1",
            content="chapter content",
            summary="summary",
        )
        db.add(chapter)
        db.flush()

        audiobook_project = AudiobookProject(
            project_id=owner_project.id,
            status="completed",
            total_chapters=1,
        )
        db.add(audiobook_project)
        db.flush()

        chapter_audio = ChapterAudio(
            audiobook_project_id=audiobook_project.id,
            chapter_id=chapter.id,
            audio_path="audiobooks/project_1/chapter_001.mp3",
            duration=1.0,
            file_size=123,
            script_json=json.dumps(
                [
                    {
                        "text": "The door opened slowly.",
                        "voice_params": {
                            "provider_prompt_snapshot": {
                                "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION,
                                "model": "minimax-speech-2.8-hd",
                                "provider_prompt": {
                                    "inline_tag_strategy": {
                                        "model_family": "minimax",
                                        "style_tags": ["tense"],
                                        "inline_tags": ["whisper"],
                                        "use_tag_parser": True,
                                    }
                                },
                            },
                        },
                    },
                    {
                        "text": "She whispered from the hallway.",
                        "voice_params": {
                            "provider_prompt_snapshot": {
                                "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION,
                                "model": "doubao-tts",
                                "provider_prompt": {
                                    "inline_tag_strategy": {
                                        "model_family": "doubao",
                                        "style_tags": ["narration"],
                                        "inline_tags": ["whisper"],
                                        "use_tag_parser": True,
                                    }
                                },
                            },
                        },
                    },
                ],
                ensure_ascii=False,
            ),
            script_status="approved",
            final_audio_review_json=json.dumps(
                _prompt_audio_quality_payload(),
                ensure_ascii=False,
            ),
        )
        db.add(chapter_audio)
        db.commit()

        return {
            "owner_id": owner.id,
            "other_user_id": other_user.id,
            "audiobook_project_id": audiobook_project.id,
            "chapter_id": chapter.id,
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


def test_prompt_audio_manual_review_persists_for_owned_chapter_audio():
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["owner_id"])

    response = client.patch(
        f"/api/v1/audiobook/chapter-audios/{context['chapter_audio_id']}/prompt-audio-review",
        json={
            "model": "minimax-speech-2.8-hd",
            "tag_parse_success": True,
            "text_contamination": False,
            "score": 4.5,
            "notes": "标签未被朗读，正文无污染",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["model"] == "minimax-speech-2.8-hd"
    assert payload["manual_review_fields"]["tag_parse_success"] is True
    assert payload["manual_review_fields"]["text_contamination"] is False
    assert payload["manual_review_fields"]["score"] == 4.5
    assert payload["manual_review_fields"]["notes"] == "标签未被朗读，正文无污染"
    assert payload["manual_review_fields"]["reviewed_by"] == context["owner_id"]
    assert payload["manual_review_fields"]["reviewed_at"]

    db = session_factory()
    try:
        chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        saved_review = json.loads(chapter_audio.final_audio_review_json)
    finally:
        db.close()

    prompt_audio_quality = saved_review["prompt_audio_quality"]
    by_model = prompt_audio_quality["by_model"]
    minimax_fields = by_model["minimax-speech-2.8-hd"]["manual_review_fields"]
    doubao_fields = by_model["doubao-tts"]["manual_review_fields"]

    assert prompt_audio_quality["coverage"]["segments_count"] == 2
    assert by_model["minimax-speech-2.8-hd"]["tag_count"] == 2
    assert minimax_fields["tag_parse_success"] is True
    assert minimax_fields["text_contamination"] is False
    assert minimax_fields["score"] == 4.5
    assert minimax_fields["notes"] == "标签未被朗读，正文无污染"
    assert doubao_fields == {
        "tag_parse_success": False,
        "text_contamination": True,
        "score": 2.0,
    }


def test_prompt_audio_manual_review_persists_asr_assist_signal():
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["owner_id"])

    response = client.patch(
        f"/api/v1/audiobook/chapter-audios/{context['chapter_audio_id']}/prompt-audio-review",
        json={
            "model": "minimax-speech-2.8-hd",
            "asr_transcript": "tense whisper the door opened slowly",
        },
    )

    assert response.status_code == 200
    manual_review_fields = response.json()["manual_review_fields"]
    asr_assist = manual_review_fields["asr_assist"]

    assert manual_review_fields["asr_transcript"] == "tense whisper the door opened slowly"
    assert asr_assist["available"] is True
    assert asr_assist["source"] == "manual_transcript"
    assert asr_assist["segment_indices"] == [0]
    assert asr_assist["detected_tag_residue"] is True
    assert asr_assist["suggested_text_contamination"] is True
    assert asr_assist["suggested_tag_parse_success"] is False
    assert asr_assist["matched_tags"] == ["tense", "whisper"]
    assert asr_assist["similarity_score"] < 1.0
    assert asr_assist["word_error_rate"] > 0.0

    db = session_factory()
    try:
        chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        saved_review = json.loads(chapter_audio.final_audio_review_json)
    finally:
        db.close()

    saved_fields = (
        saved_review["prompt_audio_quality"]["by_model"]["minimax-speech-2.8-hd"]["manual_review_fields"]
    )
    assert saved_fields["asr_assist"]["detected_tag_residue"] is True
    assert saved_fields["asr_assist"]["matched_tags"] == ["tense", "whisper"]


def test_prompt_audio_transcript_runner_applies_provider_transcript_to_selected_model(tmp_path):
    _client, session_factory, _app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    audio_file = tmp_path / "chapter_001.mp3"
    audio_file.write_bytes(b"fake audio bytes")

    captured: dict[str, object] = {}

    class FakeAsrProvider:
        name = "mimo"
        model = "mimo-v2.5-asr"

        def transcribe(self, audio_path: str, **kwargs):
            captured["audio_path"] = audio_path
            captured["kwargs"] = kwargs
            return PromptAudioAsrResult(
                provider=self.name,
                model=self.model,
                transcript="tense whisper the door opened slowly",
                metadata={"usage": {"seconds": 1}},
            )

    db = session_factory()
    try:
        chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        chapter_audio.audio_path = str(audio_file)
        db.commit()
        db.refresh(chapter_audio)

        result = execute_prompt_audio_transcript(
            db,
            chapter_audio=chapter_audio,
            provider=FakeAsrProvider(),
            target_model="minimax-speech-2.8-hd",
            provider_call_allowed=True,
        )

        db.refresh(chapter_audio)
        saved_review = json.loads(chapter_audio.final_audio_review_json)
    finally:
        db.close()

    assert result["transcript_status"] == "completed"
    assert result["provider"] == "mimo"
    assert result["model"] == "minimax-speech-2.8-hd"
    assert result["transcript_length"] == len("tense whisper the door opened slowly")
    assert captured["audio_path"] == str(audio_file)
    assert captured["kwargs"]["target_model"] == "minimax-speech-2.8-hd"

    saved_fields = (
        saved_review["prompt_audio_quality"]["by_model"]["minimax-speech-2.8-hd"]["manual_review_fields"]
    )
    assert saved_fields["asr_transcript"] == "tense whisper the door opened slowly"
    assert saved_fields["asr_provider"] == "mimo"
    assert saved_fields["asr_provider_model"] == "mimo-v2.5-asr"
    assert saved_fields["asr_assist"]["source"] == "mimo_asr"
    assert saved_fields["asr_assist"]["detected_tag_residue"] is True
    assert saved_fields["asr_assist"]["matched_tags"] == ["tense", "whisper"]


def test_prompt_audio_transcript_runner_skips_provider_call_without_cost_confirmation(tmp_path):
    _client, session_factory, _app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    audio_file = tmp_path / "chapter_001.mp3"
    audio_file.write_bytes(b"fake audio bytes")

    class FakeAsrProvider:
        name = "mimo"
        model = "mimo-v2.5-asr"

        def transcribe(self, *_args, **_kwargs):
            raise AssertionError("ASR provider must not be called before cost confirmation")

    db = session_factory()
    try:
        chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        chapter_audio.audio_path = str(audio_file)
        db.commit()
        db.refresh(chapter_audio)

        result = execute_prompt_audio_transcript(
            db,
            chapter_audio=chapter_audio,
            provider=FakeAsrProvider(),
            target_model="minimax-speech-2.8-hd",
            provider_call_allowed=False,
        )

        db.refresh(chapter_audio)
        saved_review = json.loads(chapter_audio.final_audio_review_json)
    finally:
        db.close()

    assert result["transcript_status"] == "skipped"
    assert result["reason"] == "asr_cost_not_confirmed"
    saved_fields = (
        saved_review["prompt_audio_quality"]["by_model"]["minimax-speech-2.8-hd"]["manual_review_fields"]
    )
    assert "asr_transcript" not in saved_fields
    assert "asr_assist" not in saved_fields


def test_prompt_audio_transcript_queue_creates_manual_asr_task(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["owner_id"])

    dispatched: list[dict] = []

    class FakeSignature:
        def apply_async(self, *, task_id: str):
            dispatched.append({"task_id": task_id})

            class Result:
                id = task_id

            return Result()

    def fake_signature(name: str, args: list):
        dispatched.append({"name": name, "args": args})
        return FakeSignature()

    from app.services.audiobook import prompt_audio_transcript_queue

    monkeypatch.setattr(prompt_audio_transcript_queue.celery_app, "signature", fake_signature)

    response = client.post(
        f"/api/v1/audiobook/chapter-audios/{context['chapter_audio_id']}/prompt-audio-transcript/queue",
        json={
            "model": "minimax-speech-2.8-hd",
            "provider": "mimo",
            "confirm_cost": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["audiobook_project_id"] == context["audiobook_project_id"]
    assert payload["chapter_audio_id"] == context["chapter_audio_id"]
    assert payload["job_id"] == payload["task_id"]
    assert payload["task_db_id"] > 0
    assert payload["task_type"] == "prompt_audio_asr_transcript"
    assert payload["status"] == "queued"
    assert payload["message"] == "ASR 转写任务已进入队列"

    assert dispatched[0]["name"] == "audiobook.prompt_audio_asr_transcript"
    assert dispatched[0]["args"] == [
        payload["task_db_id"],
        context["audiobook_project_id"],
        context["chapter_audio_id"],
        "mimo",
        "minimax-speech-2.8-hd",
        True,
    ]
    assert dispatched[1]["task_id"] == payload["job_id"]

    db = session_factory()
    try:
        task = db.get(AudiobookTask, payload["task_db_id"])
    finally:
        db.close()

    assert task is not None
    assert task.celery_task_id == payload["job_id"]
    assert task.audiobook_project_id == context["audiobook_project_id"]
    assert task.chapter_id == context["chapter_id"]
    assert task.task_type == "prompt_audio_asr_transcript"
    assert task.status == "queued"
    assert task.current_stage == "asr_transcript_queued"
    assert task.total_units == 1
    assert task.detail_json["manual_triggered"] is True
    assert task.detail_json["chapter_audio_id"] == context["chapter_audio_id"]
    assert task.detail_json["status"] == "queued"
    assert task.detail_json["stage"] == "asr_transcript_queued"
    assert task.detail_json["cost_control"]["manual_trigger_required"] is True
    assert task.detail_json["cost_control"]["auto_asr_in_generation"] is False
    assert task.detail_json["cost_control"]["provider_call_allowed"] is True
    assert task.detail_json["provider"] == "mimo"
    assert task.detail_json["model"] == "minimax-speech-2.8-hd"


def test_prompt_audio_transcript_queue_rejects_other_user_without_dispatch(monkeypatch):
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["other_user_id"])

    from app.services.audiobook import prompt_audio_transcript_queue

    def fail_signature(*_args, **_kwargs):
        raise AssertionError("ASR transcript task must not dispatch for unauthorized users")

    monkeypatch.setattr(prompt_audio_transcript_queue.celery_app, "signature", fail_signature)

    response = client.post(
        f"/api/v1/audiobook/chapter-audios/{context['chapter_audio_id']}/prompt-audio-transcript/queue"
    )

    assert response.status_code == 403


def test_prompt_audio_manual_review_rejects_other_user():
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["other_user_id"])

    response = client.patch(
        f"/api/v1/audiobook/chapter-audios/{context['chapter_audio_id']}/prompt-audio-review",
        json={
            "model": "minimax-speech-2.8-hd",
            "score": 5.0,
        },
    )

    assert response.status_code == 403


def test_prompt_audio_manual_review_rejects_unknown_model_without_writing():
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["owner_id"])

    response = client.patch(
        f"/api/v1/audiobook/chapter-audios/{context['chapter_audio_id']}/prompt-audio-review",
        json={
            "model": "unknown-model",
            "score": 1.0,
        },
    )

    assert response.status_code == 404

    db = session_factory()
    try:
        chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        saved_review = json.loads(chapter_audio.final_audio_review_json)
    finally:
        db.close()

    assert "unknown-model" not in saved_review["prompt_audio_quality"]["by_model"]


def test_prompt_audio_manual_review_rejects_soft_deleted_chapter_audio():
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["owner_id"])

    db = session_factory()
    try:
        chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        chapter_audio.deleted_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

    response = client.patch(
        f"/api/v1/audiobook/chapter-audios/{context['chapter_audio_id']}/prompt-audio-review",
        json={
            "model": "minimax-speech-2.8-hd",
            "score": 4.0,
        },
    )

    assert response.status_code == 404


def test_audiobook_project_detail_exposes_prompt_audio_quality_for_chapter_results():
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["owner_id"])

    response = client.get(f"/api/v1/audiobook/projects/{context['audiobook_project_id']}")

    assert response.status_code == 200
    payload = response.json()
    [chapter_audio] = payload["chapter_audios"]

    assert chapter_audio["id"] == context["chapter_audio_id"]
    assert chapter_audio["prompt_audio_quality"]["available"] is True
    assert set(chapter_audio["prompt_audio_quality"]["by_model"]) == {
        "minimax-speech-2.8-hd",
        "doubao-tts",
    }


def test_prompt_audio_review_summary_aggregates_manual_fields_by_model():
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["owner_id"])

    db = session_factory()
    try:
        audiobook_project = db.get(AudiobookProject, context["audiobook_project_id"])
        first_chapter_audio = db.get(ChapterAudio, context["chapter_audio_id"])
        first_payload = json.loads(first_chapter_audio.final_audio_review_json)
        first_payload["prompt_audio_quality"]["by_model"]["minimax-speech-2.8-hd"]["manual_review_fields"] = {
            "tag_parse_success": True,
            "text_contamination": False,
            "score": 4.5,
            "notes": "标签未污染正文",
            "asr_assist": {
                "available": True,
                "detected_tag_residue": False,
                "suggested_text_contamination": False,
                "suggested_tag_parse_success": True,
                "similarity_score": 1.0,
                "word_error_rate": 0.0,
                "matched_tags": [],
            },
        }
        first_chapter_audio.final_audio_review_json = json.dumps(
            first_payload,
            ensure_ascii=False,
        )

        chapter = Chapter(
            project_id=audiobook_project.project_id,
            chapter_number=2,
            title="Chapter 2",
            content="chapter content 2",
            summary="summary 2",
        )
        db.add(chapter)
        db.flush()

        payload = _prompt_audio_quality_payload()
        by_model = payload["prompt_audio_quality"]["by_model"]
        by_model["minimax-speech-2.8-hd"]["manual_review_fields"] = {
            "tag_parse_success": False,
            "text_contamination": True,
            "score": 3.5,
            "notes": "标签被读出",
            "asr_assist": {
                "available": True,
                "detected_tag_residue": True,
                "suggested_text_contamination": True,
                "suggested_tag_parse_success": False,
                "similarity_score": 0.82,
                "word_error_rate": 0.18,
                "matched_tags": ["tense"],
            },
        }
        by_model["doubao-tts"]["manual_review_fields"] = {
            "tag_parse_success": True,
            "text_contamination": False,
            "score": 4.0,
            "notes": "标签解析稳定",
        }
        db.add(
            ChapterAudio(
                audiobook_project_id=context["audiobook_project_id"],
                chapter_id=chapter.id,
                audio_path="audiobooks/project_1/chapter_002.mp3",
                duration=1.0,
                file_size=123,
                script_status="approved",
                final_audio_review_json=json.dumps(payload, ensure_ascii=False),
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}/prompt-audio-review-summary"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["audiobook_project_id"] == context["audiobook_project_id"]
    assert payload["coverage"]["chapter_audio_count"] == 2
    assert payload["coverage"]["reviewed_model_count"] == 4
    assert payload["coverage"]["tag_parse_reviewed_count"] == 4
    assert payload["coverage"]["text_contamination_reviewed_count"] == 4
    assert payload["coverage"]["score_reviewed_count"] == 4
    assert payload["coverage"]["asr_assist_count"] == 2
    assert payload["coverage"]["asr_tag_residue_count"] == 1

    by_model = {entry["model"]: entry for entry in payload["models"]}
    assert by_model["minimax-speech-2.8-hd"]["tag_parse_success_rate"] == 0.5
    assert by_model["minimax-speech-2.8-hd"]["text_contamination_rate"] == 0.5
    assert by_model["minimax-speech-2.8-hd"]["average_score"] == 4.0
    assert by_model["minimax-speech-2.8-hd"]["reviewed_model_count"] == 2
    assert by_model["minimax-speech-2.8-hd"]["asr_assist_count"] == 2
    assert by_model["minimax-speech-2.8-hd"]["asr_tag_residue_count"] == 1
    assert by_model["doubao-tts"]["tag_parse_success_rate"] == 0.5
    assert by_model["doubao-tts"]["text_contamination_rate"] == 0.5
    assert by_model["doubao-tts"]["average_score"] == 3.0


def test_prompt_audio_review_summary_rejects_other_user_project():
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["other_user_id"])

    response = client.get(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}/prompt-audio-review-summary"
    )

    assert response.status_code == 403


def test_prompt_audio_review_summary_csv_exports_model_rows():
    client, session_factory, app = build_test_client()
    context = seed_prompt_audio_review_context(session_factory)
    app.dependency_overrides[get_current_user] = lambda: _auth_user(context["owner_id"])

    response = client.get(
        f"/api/v1/audiobook/projects/{context['audiobook_project_id']}/prompt-audio-review-summary.csv"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]
    csv_text = response.text
    assert "model,model_family,chapter_audio_count,reviewed_model_count" in csv_text
    rows = {
        row["model"]: row
        for row in csv.DictReader(StringIO(csv_text))
    }

    assert rows["minimax-speech-2.8-hd"]["model_family"] == "minimax"
    assert rows["minimax-speech-2.8-hd"]["chapter_audio_count"] == "1"
    assert rows["minimax-speech-2.8-hd"]["reviewed_model_count"] == "0"
    assert rows["doubao-tts"]["model_family"] == "doubao"
    assert rows["doubao-tts"]["reviewed_model_count"] == "1"
    assert rows["doubao-tts"]["text_contamination_rate"] == "1.0"
