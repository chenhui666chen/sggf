import asyncio
import hashlib
import json
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

from app.api.v1.audiobook_api import routes_segment_preview, routes_segment_regen
from app.api.v1.audiobook_api.dependencies import OwnedAudiobookProject
from app.api.v1.audiobook_api.routes_review import get_chapter_review_status
from app.api.v1.audiobook_api.routes_segment_preview import preview_script_segment_audio
from app.api.v1.audiobook_api.routes_segment_regen import (
    get_segment_regeneration_candidate_audio,
    regenerate_segment,
    review_segment,
)
from app.db.base import Base
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Chapter, Project
from app.models.user import User
from app.schemas.audiobook import ScriptSegmentPreviewRequest, SegmentRegenerateRequest, SegmentReviewRequest
from app.services.audiobook.temp_segment_store import TempSegmentStoreError


def _expected_candidate_revision():
    from app.services.audiobook.voice_identity_policy import (
        VOICE_IDENTITY_POLICY_VERSION,
    )

    return f"2:{VOICE_IDENTITY_POLICY_VERSION}"


def _compute_compiled_segment_fingerprint(segment):
    from app.services.audiobook.segment_synthesis_contract import (
        compute_compiled_segment_fingerprint,
    )

    return compute_compiled_segment_fingerprint(segment)


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


@pytest.fixture(autouse=True)
def cleanup_persistent_segment_dirs_after_each():
    """本文件测试使用 chapter_audio.id=1/2 真实落盘持久化片段，测试后清理避免污染其他测试文件。"""
    yield
    from types import SimpleNamespace

    from app.services.audiobook import chapter_segment_assets

    for chapter_id in (1, 2):
        try:
            chapter_segment_assets.delete_chapter_persistent_segment_assets(
                SimpleNamespace(id=chapter_id, script_json="[]")
            )
        except Exception:
            pass


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


def build_owned_context(db, context):
    return OwnedAudiobookProject(
        audiobook_project=context["audiobook_project"],
        project=context["project"],
        current_user=context["user"],
        db=db,
    )


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
                owned=build_owned_context(db, context),
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
                    owned=build_owned_context(db, context),
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
                    owned=build_owned_context(db, context),
                )
            )

        assert exc_info.value.status_code == 400
        assert context["chapter_audio"].segment_reviews_json is None


def test_review_segment_rejects_soft_deleted_chapter_audio():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)
        context["chapter_audio"].deleted_at = datetime.now(timezone.utc)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                review_segment(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=0,
                    request=SegmentReviewRequest(quality_score=4.0, notes="deleted", needs_regenerate=False),
                    owned=build_owned_context(db, context),
                )
            )

        assert exc_info.value.status_code == 404


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
                owned=build_owned_context(db, context),
            )
        )

        db.refresh(context["chapter_audio"])
        review_data = json.loads(context["chapter_audio"].segment_reviews_json)

        assert payload["success"] is True
        assert set(review_data) == {"0"}
        assert review_data["0"]["notes"] == "recovered"


def test_load_chapter_segments_logs_invalid_script_json(caplog):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)
        context["chapter_audio"].script_json = "{bad-json"
        db.commit()

        with caplog.at_level("WARNING", logger="app.api.v1.audiobook_api.routes_segment_regen"):
            with pytest.raises(HTTPException) as exc_info:
                routes_segment_regen._load_chapter_segments(context["chapter_audio"])

        assert exc_info.value.status_code == 500
        assert "章节剧本 JSON 损坏" in caplog.text
        assert f"chapter_audio_id={context['chapter_audio'].id}" in caplog.text


def test_review_segment_logs_invalid_review_payload_and_resets(caplog):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)
        context["chapter_audio"].segment_reviews_json = "{bad-json"
        db.commit()

        with caplog.at_level("WARNING", logger="app.api.v1.audiobook_api.routes_segment_regen"):
            payload = asyncio.run(
                review_segment(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=0,
                    request=SegmentReviewRequest(quality_score=3.0, notes="recovered", needs_regenerate=False),
                    owned=build_owned_context(db, context),
                )
            )

        db.refresh(context["chapter_audio"])
        review_data = json.loads(context["chapter_audio"].segment_reviews_json)

        assert payload["success"] is True
        assert set(review_data) == {"0"}
        assert review_data["0"]["notes"] == "recovered"
        assert "片段审查 JSON 损坏，已重置" in caplog.text
        assert f"chapter_audio_id={context['chapter_audio'].id}" in caplog.text


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
                owned=build_owned_context(db, context),
            )
        )

        assert payload["total_segments"] == 2
        assert payload["reviewed_segments"] == 1
        assert payload["avg_quality_score"] == 5.0
        assert payload["flagged_segments"] == [0]


def test_review_status_logs_invalid_script_and_review_payload(caplog):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)
        context["chapter_audio"].script_json = "{bad-json"
        context["chapter_audio"].segment_reviews_json = "{bad-json"
        db.commit()

        with caplog.at_level("WARNING", logger="app.api.v1.audiobook_api.routes_review"):
            payload = asyncio.run(
                get_chapter_review_status(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    owned=build_owned_context(db, context),
                )
            )

        assert payload["total_segments"] == 0
        assert payload["reviewed_segments"] == 0
        assert payload["avg_quality_score"] is None
        assert payload["flagged_segments"] == []
        assert "章节审查状态忽略损坏剧本 JSON" in caplog.text
        assert "章节审查状态忽略损坏审查 JSON" in caplog.text


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
                owned=build_owned_context(db, context),
            )
        )

        db.refresh(context["chapter_audio"])
        segments = json.loads(context["chapter_audio"].script_json)

        assert payload["success"] is True
        assert synthesize_call["model_id"] == "qwen3-tts-instruct-flash"
        assert synthesize_call["voice_params"]["speaker"] == "Neil"
        assert synthesize_call["voice_params"]["segment_speaker"] == "旁白"
        assert segments[0]["regenerated"] is True
        assert "chapter_segments_persistent_voice" in segments[0]["audio_path"]
        assert segments[0]["audio_path"].endswith(".mp3")


def test_candidate_payload_uses_project_voice_mapping_before_model_default():
    request = SegmentRegenerateRequest(tts_model="qwen3-tts-instruct-flash")

    payload = routes_segment_regen._build_segment_synthesis_payload(
        request,
        {
            "type": "narration",
            "speaker": "narrator",
            "text": "Mapped narrator.",
            "emotion": "neutral",
        },
        voice_mapping={"narrator": {"voice_id": "project-narrator-voice"}},
    )

    assert payload["voice_params"]["speaker"] == "project-narrator-voice"


def test_candidate_payload_restores_owned_mimo_design_asset_recipe(monkeypatch):
    merge_call = {}

    def fake_merge(config, *, owner_user_id=None):
        merge_call["config"] = dict(config)
        merge_call["owner_user_id"] = owner_user_id
        return {
            **config,
            "mimo_voice_asset_id": "asset-1",
            "voice_design_prompt": "资产库中的权威青年女性音色配方",
            "voice_description": "不应进入候选合同的冗余音色描述",
        }

    monkeypatch.setattr(
        routes_segment_regen,
        "merge_mimo_voice_asset_tts_params",
        fake_merge,
        raising=False,
    )

    payload = routes_segment_regen._build_segment_synthesis_payload(
        SegmentRegenerateRequest(
            tts_model="mimo-v2.5-tts-voice-design",
            voice_id="mimo_design:asset-1",
        ),
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "别回头。",
            "performance_notes": "语速缓慢，句尾拖长。",
            "voice_params": {
                "speaker": "mimo_design:asset-1",
                "mimo_voice_asset_id": "asset-2-client-forged",
                "pitch": 0.7,
                "voice_description": "客户端伪造的老人音色",
                "voice_design_prompt": "客户端伪造的老人设计配方",
            },
        },
        owner_user_id=42,
    )

    assert merge_call["owner_user_id"] == 42
    assert merge_call["config"]["mimo_voice_asset_id"] == "asset-1"
    assert "pitch" not in merge_call["config"]
    assert "voice_description" not in merge_call["config"]
    assert "voice_design_prompt" not in merge_call["config"]
    params = payload["voice_params"]
    assert params["mimo_voice_asset_id"] == "asset-1"
    assert params["voice_design_prompt"] == "资产库中的权威青年女性音色配方"
    assert "voice_description" not in params
    assert "客户端伪造" not in json.dumps(payload, ensure_ascii=False)
    assert payload["voice_identity_binding"] == {
        "asset_type": "design",
        "mimo_voice_asset_id": "asset-1",
        "voice_design_prompt_sha1": hashlib.sha1(
            "资产库中的权威青年女性音色配方".encode("utf-8")
        ).hexdigest(),
    }


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
                owned=build_owned_context(db, context),
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
                    owned=build_owned_context(db, context),
                )
            )

        assert exc_info.value.status_code == 400


def test_segment_regen_route_does_not_keep_broad_save_exception_handler():
    source = Path(routes_segment_regen.__file__).read_text(encoding="utf-8")

    assert "except Exception as e" not in source
    assert "except (OSError, TempSegmentStoreError) as e" in source


def test_regenerate_segment_converts_temp_store_failures_to_http_error(monkeypatch):
    session_factory = build_session_factory()

    async def fake_synthesize_speech(**kwargs):
        return b"ID3fake-audio"

    def fail_save_persistent_segment_audio(**kwargs):
        raise TempSegmentStoreError("temp store unavailable")

    monkeypatch.setattr(routes_segment_regen, "runtime_synthesize_speech", fake_synthesize_speech)
    monkeypatch.setattr(
        routes_segment_regen,
        "save_persistent_segment_audio",
        fail_save_persistent_segment_audio,
    )

    with session_factory() as db:
        context = seed_segment_context(db)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                regenerate_segment(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=0,
                    request=SegmentRegenerateRequest(),
                    owned=build_owned_context(db, context),
                )
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "保存音频失败: temp store unavailable"


def test_regenerate_segment_does_not_swallow_unexpected_script_serialization_errors(monkeypatch):
    session_factory = build_session_factory()

    async def fake_synthesize_speech(**kwargs):
        return b"ID3fake-audio"

    def fake_save_segment_audio_map(**kwargs):
        return {
            "storage_driver": "local_fs",
            "cached_audio_paths": {0: "data/audiobook/temp-segments/test/chapter_1/segment.mp3"},
            "segments": {},
        }

    def fail_json_dumps(*args, **kwargs):
        raise RuntimeError("unexpected serializer failure")

    monkeypatch.setattr(routes_segment_regen, "runtime_synthesize_speech", fake_synthesize_speech)
    monkeypatch.setattr(routes_segment_regen, "save_segment_audio_map", fake_save_segment_audio_map)

    with session_factory() as db:
        context = seed_segment_context(db)
        monkeypatch.setattr(routes_segment_regen.json, "dumps", fail_json_dumps)

        with pytest.raises(RuntimeError, match="unexpected serializer failure"):
            asyncio.run(
                regenerate_segment(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=0,
                    request=SegmentRegenerateRequest(),
                    owned=build_owned_context(db, context),
                )
            )


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
                owned=build_owned_context(db, context),
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
                owned=build_owned_context(db, context),
            )
        )

        assert response.body == b"ID3minimax-preview"
        assert synthesize_call["model_id"] == "minimax-speech-2.8-hd"
        assert synthesize_call["voice_params"]["speaker"] == "male-qn-qingse"


def test_candidate_audio_preview_rejects_registry_fingerprint_mismatch(monkeypatch):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)
        monkeypatch.setattr(
            routes_segment_regen,
            "verify_segment_candidate_token",
            lambda *args, **kwargs: {
                "run": "candidate-run",
                "chi": context["chapter"].id,
                "sha1": "a" * 40,
                "ext": "mp3",
                "pt": "voice",
                "fp": "base-fingerprint",
                "efp": "effective-fingerprint",
                "sfp": "synthesis-fingerprint",
                "rev": _expected_candidate_revision(),
            },
        )
        monkeypatch.setattr(
            routes_segment_regen,
            "build_segment_asset_ref",
            lambda **kwargs: "candidate-ref",
        )
        monkeypatch.setattr(
            routes_segment_regen,
            "load_segment_candidate_contract",
            lambda *args, **kwargs: {
                "revision": _expected_candidate_revision(),
                "preview_type": "voice",
                "base_segment_fingerprint": "different-base",
                "effective_segment_fingerprint": "effective-fingerprint",
                "synthesis_fingerprint": "synthesis-fingerprint",
            },
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                get_segment_regeneration_candidate_audio(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=0,
                    candidate_id="candidate-token",
                    owned=build_owned_context(db, context),
                )
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "候选登记与凭证不一致，请重新生成候选"


def test_candidate_audio_preview_rejects_stale_registry_contract_revision(monkeypatch):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)
        effective_segment = {
            "type": "narration",
            "speaker": "narrator",
            "text": "candidate text",
            "voice_params": {"speaker": "voice-a"},
        }
        effective_fingerprint = _compute_compiled_segment_fingerprint(
            effective_segment
        )
        candidate_payload = {
            "run": "candidate-run",
            "chi": context["chapter"].id,
            "sha1": "a" * 40,
            "ext": "mp3",
            "pt": "voice",
            "fp": "base-fingerprint",
            "efp": effective_fingerprint,
            "sfp": "synthesis-fingerprint",
            "rev": _expected_candidate_revision(),
        }
        monkeypatch.setattr(
            routes_segment_regen,
            "verify_segment_candidate_token",
            lambda *args, **kwargs: candidate_payload,
        )
        monkeypatch.setattr(
            routes_segment_regen,
            "build_segment_asset_ref",
            lambda **kwargs: "candidate-ref",
        )
        monkeypatch.setattr(
            routes_segment_regen,
            "load_segment_candidate_contract",
            lambda *args, **kwargs: {
                "revision": "1:4",
                "preview_type": "voice",
                "base_segment_fingerprint": "base-fingerprint",
                "effective_segment": effective_segment,
                "effective_segment_fingerprint": effective_fingerprint,
                "synthesis_fingerprint": "synthesis-fingerprint",
            },
        )
        monkeypatch.setattr(
            routes_segment_regen,
            "load_cached_segment_audio",
            lambda *args, **kwargs: {0: b"ID3 stale candidate"},
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                get_segment_regeneration_candidate_audio(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=0,
                    candidate_id="candidate-token",
                    owned=build_owned_context(db, context),
                )
            )

        assert exc_info.value.status_code == 400


def test_preview_segment_compiles_server_owned_delivery_contract(monkeypatch):
    session_factory = build_session_factory()
    captured = {}

    class FakePreviewService:
        def __init__(self, **kwargs):
            captured["service_model"] = kwargs["tts_model"]

        def resolve_voice_params(self, segment):
            return "painful", {"speaker": "voice-selected"}

        async def generate_preview(self, segment, *, preview_type):
            captured["segment"] = segment
            captured["preview_type"] = preview_type
            return type("Preview", (), {"audio": b"ID3 compiled-preview", "media_type": "audio/mpeg"})()

    monkeypatch.setattr(routes_segment_preview, "SegmentPreviewService", FakePreviewService)

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
                        "text": "Preview with a fresh direction.",
                        "performance_notes": "slow and painful",
                        "voice_params": {
                            "tts_model": "seed-tts-2.0-expressive",
                            "delivery_plan": {"director_guidance": "STALE_CLIENT_PLAN"},
                            "provider_prompt_snapshot": {"mode": "STALE_CLIENT_SNAPSHOT"},
                        },
                    },
                    tts_model="qwen3-tts-instruct-flash",
                    preview_type="voice",
                ),
                owned=build_owned_context(db, context),
            )
        )

        assert response.body == b"ID3 compiled-preview"
        assert captured["service_model"] == "seed-tts-2.0-expressive"
        assert captured["preview_type"] == "voice"
        compiled_params = captured["segment"]["voice_params"]
        assert compiled_params["speaker"] == "voice-selected"
        assert "director_guidance" not in compiled_params["delivery_plan"]
        assert compiled_params["delivery_plan"]["style_instruction"] == "slow and painful"
        assert compiled_params["provider_prompt_snapshot"]["mode"] != "STALE_CLIENT_SNAPSHOT"


def test_preview_segment_rehydrates_owned_mimo_design_asset_baseline(monkeypatch):
    from app.services.audiobook import mimo_voice_assets

    session_factory = build_session_factory()
    captured = {}
    asset_calls = []

    class FakePreviewService:
        def __init__(self, **kwargs):
            pass

        async def generate_preview(self, segment, *, preview_type):
            captured["segment"] = segment
            return type(
                "Preview",
                (),
                {"audio": b"ID3 mimo-design-preview", "media_type": "audio/mpeg"},
            )()

    def fake_resolve_asset(asset_id, *, owner_user_id=None):
        asset_calls.append((asset_id, owner_user_id))
        return {
            "mimo_voice_asset_id": "asset-1",
            "voice_design_prompt": "服务端固定青年女性声线",
            "voice_description": "服务端固定青年女性声线",
        }

    monkeypatch.setattr(routes_segment_preview, "SegmentPreviewService", FakePreviewService)
    monkeypatch.setattr(
        mimo_voice_assets,
        "resolve_mimo_voice_asset_tts_params",
        fake_resolve_asset,
    )

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
                        "text": "Preview fixed MiMo design voice.",
                        "performance_notes": "改成老人声，语速缓慢，句尾拖长。",
                        "voice_params": {
                            "speaker": "mimo_design:asset-1",
                            "tts_model": "mimo-v2.5-tts-voicedesign",
                            "voice_design_prompt": "客户端伪造的老人声",
                        },
                    },
                    tts_model="mimo-v2.5-tts-voicedesign",
                    preview_type="voice",
                ),
                owned=build_owned_context(db, context),
            )
        )

        assert response.body == b"ID3 mimo-design-preview"
        assert asset_calls == [("asset-1", context["user"].id)]
        compiled_params = captured["segment"]["voice_params"]
        assert compiled_params["voice_design_prompt"] == "服务端固定青年女性声线"
        serialized = json.dumps(compiled_params, ensure_ascii=False)
        assert "客户端伪造的老人声" not in serialized
        assert "固定声音设定保持不变" in serialized


def test_preview_segment_keeps_explicit_bound_voice_in_compiled_contract(monkeypatch):
    """工作台试听必须使用片段绑定的 speaker，而不是按角色名重新分配默认音色。"""
    session_factory = build_session_factory()
    synthesize_call = {}

    class FakeVoiceProfile:
        def get_tts_params(self, emotion):
            return {
                "speaker": "manager-default-voice",
                "emotion": emotion,
                "voice_description": "项目默认旁白音色",
            }

    class FakeVoiceManager:
        def apply_project_voice_mapping(self, mapping):
            return None

        def get_narrator_voice(self):
            return FakeVoiceProfile()

        def get_voice(self, speaker):
            return None

        def assign_voice(self, speaker):
            return FakeVoiceProfile()

    async def fake_synthesize_speech(**kwargs):
        synthesize_call.update(kwargs)
        return b"ID3 bound-voice-preview"

    from app.services.audiobook import segment_preview_service

    monkeypatch.setattr(
        segment_preview_service,
        "create_voice_manager",
        lambda **kwargs: FakeVoiceManager(),
    )
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
                        "text": "Preview bound voice.",
                        "performance_notes": "slow and restrained",
                        "voice_params": {
                            "speaker": "bound-voice-id",
                            "tts_model": "seed-tts-2.0-expressive",
                        },
                    },
                    tts_model="qwen3-tts-instruct-flash",
                    preview_type="voice",
                ),
                owned=build_owned_context(db, context),
            )
        )

        assert response.body == b"ID3 bound-voice-preview"
        assert synthesize_call["model_id"] == "seed-tts-2.0-expressive"
        assert synthesize_call["voice_params"]["speaker"] == "bound-voice-id"
        delivery_plan = synthesize_call["voice_params"]["delivery_plan"]
        assert "director_guidance" not in delivery_plan
        assert delivery_plan["style_instruction"] == "slow and restrained"
        snapshot = synthesize_call["voice_params"]["provider_prompt_snapshot"]
        assert snapshot["voice_id"] == "bound-voice-id"
        assert snapshot["delivery_plan"]["style_instruction"] == "slow and restrained"


def test_preview_segment_drops_server_managed_audio_fields(monkeypatch):
    session_factory = build_session_factory()
    captured = {}

    class FakePreviewService:
        def __init__(self, **kwargs):
            pass

        def resolve_voice_params(self, segment):
            return "neutral", {"speaker": "preview-voice"}

        async def generate_preview(self, segment, *, preview_type):
            captured["segment"] = segment
            return type("Preview", (), {"audio": b"ID3 sanitized-preview", "media_type": "audio/mpeg"})()

    monkeypatch.setattr(routes_segment_preview, "SegmentPreviewService", FakePreviewService)

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
                        "text": "Preview sanitized fields.",
                        "audio_path": "../../outside.mp3",
                        "mix_audio_path": "C:/outside/mix.mp3",
                        "voice_params": {
                            "speaker": "preview-voice",
                            "provider_prompt_snapshot": {"stale": True},
                        },
                    },
                    preview_type="voice",
                ),
                owned=build_owned_context(db, context),
            )
        )

    assert response.body == b"ID3 sanitized-preview"
    assert "audio_path" not in captured["segment"]
    assert "mix_audio_path" not in captured["segment"]
    assert captured["segment"]["voice_params"]["provider_prompt_snapshot"] != {"stale": True}


def test_saved_segment_sfx_preview_renders_timeline_when_no_persisted_stem(monkeypatch):
    """管线生成的音效无持久化分轨时，试听回退到 checkpoint 时间线实时渲染。"""
    session_factory = build_session_factory()
    captured = {}

    def fake_render(**kwargs):
        captured.update(kwargs)
        return b"ID3timeline-preview"

    monkeypatch.setattr(
        routes_segment_regen,
        "get_latest_run_checkpoint_json",
        lambda *args, **kwargs: {
            "segment_timings": [{"index": 0, "start": 0.0, "end": 10.0}],
            "effect_timeline": {"timeline": [{"timestamp": 1.0, "file": "e.mp3"}]},
        },
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "render_segment_timeline_preview",
        fake_render,
    )

    with session_factory() as db:
        context = seed_segment_context(db)
        response = asyncio.run(
            get_segment_regeneration_candidate_audio(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                segment_index=0,
                candidate_id=None,
                preview_type="sfx",
                owned=build_owned_context(db, context),
            )
        )

    assert response.body == b"ID3timeline-preview"
    assert response.media_type == "audio/mpeg"
    assert captured["preview_type"] == "sfx"
    assert captured["segment_index"] == 0
    assert captured["checkpoint"]["effect_timeline"]["timeline"]


def test_saved_segment_bgm_preview_404_when_timeline_missing(monkeypatch):
    session_factory = build_session_factory()

    monkeypatch.setattr(
        routes_segment_regen,
        "get_latest_run_checkpoint_json",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        routes_segment_regen,
        "render_segment_timeline_preview",
        lambda **kwargs: None,
    )

    with session_factory() as db:
        context = seed_segment_context(db)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                get_segment_regeneration_candidate_audio(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=0,
                    candidate_id=None,
                    preview_type="bgm",
                    owned=build_owned_context(db, context),
                )
            )

    assert exc_info.value.status_code == 404
    assert "配乐" in exc_info.value.detail


def test_saved_segment_voice_preview_still_rejects_missing_audio_path():
    """人声试听保持原校验：未登记持久化音频时不得回退。"""
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_segment_context(db)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                get_segment_regeneration_candidate_audio(
                    audiobook_project_id=context["audiobook_project"].id,
                    chapter_id=context["chapter"].id,
                    segment_index=0,
                    candidate_id=None,
                    audio_path="candidate-voice.mp3",
                    preview_type="voice",
                    owned=build_owned_context(db, context),
                )
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "片段音频路径无效"
