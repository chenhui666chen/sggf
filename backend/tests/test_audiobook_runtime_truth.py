import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base
from app.api.v1.audiobook_api.routes_download import (
    _create_stream_access_token,
    _resolve_stream_token_user,
)
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from app.models.project import Chapter, Project
from app.models.user import User
from app.services.audiobook import background_jobs_shared
from app.services.audiobook.background_jobs_shared import (
    apply_chapter_audio_generation_result,
    generate_and_apply_subtitle_artifacts,
    mark_chapter_generation_failed,
    parse_estimated_cost,
    prepare_chapter_generation_output_context,
    release_audiobook_project_billing,
    settle_audiobook_project_billing,
)
from app.services.audiobook.task_support import build_generation_checkpoint_payload


def test_parse_estimated_cost_accepts_supported_currency_symbols():
    assert parse_estimated_cost("¥2.08") == 2.08
    assert parse_estimated_cost("￥2.08") == 2.08
    assert parse_estimated_cost("$2.08") == 2.08
    assert parse_estimated_cost("not-a-cost") is None


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


class FakeNarrationStyleEngine:
    def __init__(self):
        self.applied_style = None

    def apply_narration_style_config(self, style, prompt):
        self.applied_style = (style, prompt)


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append((message, args))


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


def test_audiobook_stream_token_resolves_active_owner():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        token, expires_at = _create_stream_access_token(
            user_id=context["user"].id,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
        )

        resolved_user = _resolve_stream_token_user(
            db=db,
            token=token,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
        )

        assert token
        assert expires_at.tzinfo is not None
        assert resolved_user.id == context["user"].id


def test_audiobook_stream_token_rejects_chapter_mismatch():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        token, _ = _create_stream_access_token(
            user_id=context["user"].id,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
        )

        try:
            _resolve_stream_token_user(
                db=db,
                token=token,
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id + 1,
            )
        except HTTPException as exc:
            assert exc.status_code == 401
        else:
            raise AssertionError("chapter mismatch should reject stream token")


def test_prepare_chapter_generation_output_context_uses_run_checkpoint_and_persists_progress():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        run = ChapterAudioRun(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="full",
            celery_task_id="celery-full-1",
            status="running",
            current_stage="tts_synthesis",
            progress=0.0,
            checkpoint_json={
                "output_format": "m4a",
                "generate_subtitle": False,
                "narration_style": "dramatic",
                "narration_style_prompt": "压低声线，保留停顿",
            },
        )
        db.add(run)
        db.commit()

        engine = FakeNarrationStyleEngine()
        output_context = prepare_chapter_generation_output_context(
            db,
            engine=engine,
            audiobook_project=context["audiobook_project"],
            chapter_id=context["chapter"].id,
            chapter_number=context["chapter"].chapter_number,
            run_type="full",
        )

        assert output_context.output_format == "m4b"
        assert output_context.generate_subtitle is False
        assert output_context.output_path == "audiobooks/project_1/chapter_001.m4b"
        assert output_context.resume_checkpoint["narration_style"] == "dramatic"
        assert engine.applied_style == ("dramatic", "压低声线，保留停顿")

        output_context.tts_progress_callback(
            {
                "task_id": "engine-task-1",
                "total_segments": 4,
                "completed_segment_indices": [0, "2"],
                "temp_segment_cache": {
                    "cached_audio_paths": {"0": "tmp/segment_0.wav", "2": "tmp/segment_2.wav"},
                },
            }
        )
        db.refresh(run)

        assert run.status == "running"
        assert run.current_stage == "tts_synthesis"
        assert run.total_segment_count == 4
        assert run.completed_segment_count == 2
        assert run.progress == 0.5
        assert run.checkpoint_json["completed_segment_indices"] == [0, 2]
        assert run.checkpoint_json["cached_audio_paths"]["2"] == "tmp/segment_2.wav"


def test_tts_progress_callback_merges_incremental_scene_checkpoints():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        run = ChapterAudioRun(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="full",
            celery_task_id="celery-scene-1",
            status="running",
            current_stage="tts_synthesis",
            progress=0.0,
            checkpoint_json={},
        )
        db.add(run)
        db.commit()

        output_context = prepare_chapter_generation_output_context(
            db,
            engine=FakeNarrationStyleEngine(),
            audiobook_project=context["audiobook_project"],
            chapter_id=context["chapter"].id,
            chapter_number=context["chapter"].chapter_number,
            run_type="full",
        )

        output_context.tts_progress_callback(
            {
                "task_id": "engine-scene-1",
                "total_segments": 4,
                "scene_checkpoints": {
                    "scene_0001": {"status": "passed", "audio_path": "scene-1.wav"},
                },
            }
        )
        output_context.tts_progress_callback(
            {
                "task_id": "engine-scene-1",
                "total_segments": 4,
                "scene_checkpoints": {
                    "scene_0002": {"status": "passed", "audio_path": "scene-2.wav"},
                },
            }
        )
        db.refresh(run)

        assert run.current_stage == "scene_rendering"
        assert run.checkpoint_json["scene_checkpoints"] == {
            "scene_0001": {"status": "passed", "audio_path": "scene-1.wav"},
            "scene_0002": {"status": "passed", "audio_path": "scene-2.wav"},
        }


def test_generate_and_apply_subtitle_artifacts_updates_chapter_audio(tmp_path):
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        result = {
            "segment_timings": [
                {"index": 0, "start": 0.0, "end": 1.0, "duration": 1.0},
            ],
        }

        subtitle_artifacts = generate_and_apply_subtitle_artifacts(
            chapter_audio=context["chapter_audio"],
            result=result,
            fallback_script_segments=[
                {"text": "星河在窗外流动。", "speaker": "旁白", "emotion": "calm"},
            ],
            output_path=str(tmp_path / "chapter_001.mp3"),
            title="第一章",
            generate_subtitle=True,
        )

        assert subtitle_artifacts["generated"] is True
        assert result["subtitle_artifacts"]["subtitle_format"] == "srt"
        assert context["chapter_audio"].subtitle_format == "srt"
        assert context["chapter_audio"].subtitle_path.endswith("chapter_001.srt")


def test_generate_and_apply_subtitle_artifacts_respects_disabled_flag():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        result = {"segment_timings": [{"index": 0, "start": 0.0, "end": 1.0}]}

        subtitle_artifacts = generate_and_apply_subtitle_artifacts(
            chapter_audio=context["chapter_audio"],
            result=result,
            fallback_script_segments=[
                {"text": "不应生成字幕。", "speaker": "旁白"},
            ],
            output_path="chapter_001.mp3",
            title="第一章",
            generate_subtitle=False,
        )

        assert subtitle_artifacts == {"generated": False, "reason": "disabled_by_request"}
        assert result["subtitle_artifacts"] == subtitle_artifacts
        assert context["chapter_audio"].subtitle_path is None


def test_apply_chapter_audio_generation_result_updates_shared_metadata():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        chapter_audio = context["chapter_audio"]
        chapter_audio.segment_count = 9
        chapter_audio.dialogue_count = 4
        chapter_audio.narration_count = 5
        result = {
            "duration": 12.5,
            "file_size": 2048,
            "stats": {
                "generation_time": "3.5秒",
                "parse_stats": {
                    "total_segments": 2,
                    "dialogue_count": 1,
                    "narration_count": 1,
                },
                "tts_stats": {"estimated_cost": "¥0.12"},
                "final_audio_review": {"score": 0.91},
            },
        }

        metadata = apply_chapter_audio_generation_result(
            chapter_audio=chapter_audio,
            result=result,
            output_path="audiobooks/project_1/chapter_001.wav",
            require_audio_metrics=True,
        )

        assert metadata["parse_stats"]["total_segments"] == 2
        assert chapter_audio.audio_path == "audiobooks/project_1/chapter_001.wav"
        assert chapter_audio.duration == 12.5
        assert chapter_audio.file_size == 2048
        assert chapter_audio.segment_count == 2
        assert chapter_audio.dialogue_count == 1
        assert chapter_audio.narration_count == 1
        assert chapter_audio.generation_time == 3.5
        assert chapter_audio.tts_cost == 0.12
        assert json.loads(chapter_audio.final_audio_review_json) == {"score": 0.91}


def test_apply_chapter_audio_generation_result_prefers_structured_cost_yuan():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        chapter_audio = context["chapter_audio"]

        apply_chapter_audio_generation_result(
            chapter_audio=chapter_audio,
            result={
                "duration": 1.0,
                "file_size": 128,
                "stats": {
                    "parse_stats": {},
                    "tts_stats": {
                        "estimated_cost_yuan": 0.123456,
                        "estimated_cost": "¥0.12",
                    },
                },
            },
            output_path="audiobooks/project_1/chapter_001.wav",
        )

        assert chapter_audio.tts_cost == 0.123456


def test_apply_chapter_audio_generation_result_can_preserve_existing_counts():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        chapter_audio = context["chapter_audio"]
        chapter_audio.segment_count = 9
        chapter_audio.dialogue_count = 4
        chapter_audio.narration_count = 5

        apply_chapter_audio_generation_result(
            chapter_audio=chapter_audio,
            result={
                "duration": None,
                "file_size": None,
                "stats": {
                    "parse_stats": {},
                    "tts_stats": {"estimated_cost": "$0.05"},
                },
            },
            output_path="audiobooks/project_1/chapter_001.mp3",
            preserve_existing_counts=True,
        )

        assert chapter_audio.duration == 0.0
        assert chapter_audio.file_size == 0
        assert chapter_audio.segment_count == 9
        assert chapter_audio.dialogue_count == 4
        assert chapter_audio.narration_count == 5
        assert chapter_audio.tts_cost == 0.05


def test_settle_audiobook_project_billing_delegates_to_points_event(monkeypatch):
    calls = []

    def fake_settle(*, db, audiobook_project_id):
        calls.append((db, audiobook_project_id))

    monkeypatch.setattr(
        background_jobs_shared,
        "record_audiobook_billing_settle",
        fake_settle,
    )

    db = object()
    logger = FakeLogger()
    settle_audiobook_project_billing(
        logger,
        db,
        audiobook_project_id=123,
    )

    assert calls == [(db, 123)]
    assert logger.warnings == []


def test_release_audiobook_project_billing_logs_event_failure(monkeypatch):
    def fake_release(*, db, audiobook_project_id, reason):
        raise RuntimeError(f"release failed:{audiobook_project_id}:{reason}")

    monkeypatch.setattr(
        background_jobs_shared,
        "record_audiobook_billing_release",
        fake_release,
    )

    logger = FakeLogger()
    release_audiobook_project_billing(
        logger,
        object(),
        audiobook_project_id=456,
        reason="failed",
    )

    assert len(logger.warnings) == 1
    assert "释放有声书冻结积分失败" in logger.warnings[0][0]
    assert logger.warnings[0][1][0] == 456


def test_mark_chapter_generation_failed_records_result_diagnostic():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        run = ChapterAudioRun(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="full",
            celery_task_id="celery-full-failed",
            status="running",
            current_stage="tts_synthesis",
            progress=0.25,
            checkpoint_json={"output_format": "mp3"},
        )
        db.add(run)
        db.commit()

        result = {
            "success": False,
            "task_id": "engine-task-failed",
            "error": "provider_empty_audio",
            "stats": {"parse_stats": {"total_segments": 3}},
            "temp_segment_cache": {
                "cached_audio_paths": {"0": "tmp/segment_0.wav"},
                "render_chunk_count": 3,
                "render_plan": [
                    {"index": 0, "source_segment_indices": [0]},
                    {"index": 1, "source_segment_indices": [1]},
                    {"index": 2, "source_segment_indices": [2]},
                ],
            },
        }

        summary = mark_chapter_generation_failed(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="full",
            stage="full",
            chapter=context["chapter"],
            script_segments=[
                {"text": "segment zero", "speaker": "Narrator"},
                {"text": "segment one", "speaker": "Narrator"},
                {"text": "segment two", "speaker": "Narrator"},
            ],
            result=result,
            resume_checkpoint={},
            task_id="engine-task-failed",
            default_error_message="full_generation_failed",
        )
        db.refresh(run)

        diagnostic = run.checkpoint_json["failure_diagnostic"]
        assert run.status == "failed"
        assert run.current_stage == "failed"
        assert run.error_message == "provider_empty_audio"
        assert run.total_segment_count == 3
        assert summary["total_segment_count"] == 3
        assert diagnostic["stage"] == "full"
        assert diagnostic["error_message"] == "provider_empty_audio"
        assert diagnostic["failed_render_chunk_index"] == 1
        assert diagnostic["failed_segment_index"] == 1
        assert diagnostic["completed_segment_indices"] == [0]
        assert run.checkpoint_json["failed_segment_indices"] == [1]
        assert run.checkpoint_json["engine_task_id"] == "engine-task-failed"


def test_mark_chapter_generation_failed_records_exception_diagnostic():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)
        run = ChapterAudioRun(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="audio_from_scripts",
            celery_task_id="celery-audio-exception",
            status="running",
            current_stage="tts_synthesis",
            progress=0.5,
            completed_segment_count=1,
            total_segment_count=2,
            checkpoint_json={
                "total_segments": 2,
                "completed_segment_indices": [0],
                "cached_audio_paths": {"0": "tmp/segment_0.wav"},
            },
        )
        db.add(run)
        db.commit()

        summary = mark_chapter_generation_failed(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="audio_from_scripts",
            stage="audio_from_scripts",
            chapter=context["chapter"],
            script_segments=[
                {"text": "segment zero", "speaker": "Narrator"},
                {"text": "segment one", "speaker": "Lead"},
            ],
            exception=RuntimeError("mixer failed"),
            resume_checkpoint={
                "total_segments": 2,
                "completed_segment_indices": [0],
                "cached_audio_paths": {"0": "tmp/segment_0.wav"},
            },
            task_id="engine-task-exception",
            default_error_message="audio_generation_failed",
        )
        db.refresh(run)

        diagnostic = run.checkpoint_json["failure_diagnostic"]
        assert run.status == "failed"
        assert run.error_message == "mixer failed"
        assert run.total_segment_count == 2
        assert summary["error_message"] == "mixer failed"
        assert diagnostic["stage"] == "audio_from_scripts"
        assert diagnostic["error_type"] == "RuntimeError"
        assert diagnostic["failed_render_chunk_index"] == 1
        assert diagnostic["completed_segment_indices"] == [0]
        assert run.checkpoint_json["failed_segment_indices"] == [1]


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


def test_checkpoint_payload_without_run_type_prefers_resumable_failed_run():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_runtime_context(db)

        failed_run = ChapterAudioRun(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="full",
            celery_task_id="celery-failed",
            status="failed",
            current_stage="tts_synthesis",
            progress=0.25,
            completed_segment_count=1,
            total_segment_count=4,
            tts_model="qwen3-tts-instruct-flash",
            output_format="mp3",
            narration_style="professional",
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
        completed_run = ChapterAudioRun(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="script_only",
            celery_task_id="celery-completed",
            status="completed",
            current_stage="completed",
            progress=1.0,
            completed_segment_count=4,
            total_segment_count=4,
            tts_model="qwen3-tts-instruct-flash",
            output_format="mp3",
            narration_style="professional",
            resumable=True,
            checkpoint_json={
                "schema_version": 1,
                "status": "completed",
                "current_stage": "completed",
                "total_segments": 4,
                "completed_segment_count": 4,
                "completed_segment_indices": [0, 1, 2, 3],
                "cached_audio_paths": {},
                "segments": {},
                "tts_model": "qwen3-tts-instruct-flash",
                "output_format": "mp3",
            },
        )
        db.add_all([failed_run, completed_run])
        db.commit()

        payload = build_generation_checkpoint_payload(
            chapter_id=context["chapter"].id,
            chapter_audio=context["chapter_audio"],
            run_type=None,
            db=db,
            audiobook_project_id=context["audiobook_project"].id,
        )

        assert payload["run_id"] == failed_run.id
        assert payload["run_status"] == "failed"
        assert payload["resume_task_type"] == "full"
        assert payload["can_resume"] is True
