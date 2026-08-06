from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
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
from app.services.audiobook.repository import ChapterAudioRunRepository


def test_sanitize_incoming_script_segments_drops_compiled_voice_fields():
    existing = [{
        "text": "原文",
        "audio_path": "chapter_segments_persistent_voice/1/segment.mp3",
        "audio_cache_key": "server-signature",
    }]
    incoming = [{
        "text": "原文",
        "instruct_scene": "水牢囚禁场景",
        "voice_params": {
            "speaker": "voice-a",
            "tts_model": "seed-tts-2.0-expressive",
            "speed": 0.8,
            "instruct_scene": "客户端旧场景",
            "delivery_plan": {"director_guidance": "stale"},
            "provider_prompt_snapshot": {"mode": "stale"},
            "resolved_tts_model": "stale-model",
        },
        "audio_path": "../../forged.mp3",
        "audio_cache_key": "forged-signature",
    }]

    sanitized = routes_script._sanitize_incoming_script_segments(incoming, existing)

    assert sanitized[0]["instruct_scene"] == "水牢囚禁场景"
    assert sanitized[0]["voice_params"] == {
        "speaker": "voice-a",
        "tts_model": "seed-tts-2.0-expressive",
        "speed": 0.8,
    }
    # 顶层场景语义变化会让旧片段音频失效，不能继续保留旧资产。
    assert "audio_path" not in sanitized[0]
    assert "audio_cache_key" not in sanitized[0]


def test_sanitize_incoming_script_segments_invalidates_only_changed_tracks():
    existing = [{
        "type": "narration",
        "text": "原文",
        "speaker": "旁白",
        "performance_notes": "平静",
        "sound_effects_simple": ["水滴声"],
        "music_cue_simple": "低沉弦乐",
        "audio_path": "chapter_segments_persistent_voice/1/segment.mp3",
        "sfx_audio_path": "chapter_segments_persistent_sfx/1/segment.mp3",
        "bgm_audio_path": "chapter_segments_persistent_bgm/1/segment.mp3",
        "mix_audio_path": "chapter_segments_persistent_mix/1/segment.mp3",
        "audio_cache_key": "voice-signature",
        "audio_render_chunk_max_chars": 420,
    }]

    incoming = [{
        "type": "narration",
        "text": "原文",
        "speaker": "旁白",
        "performance_notes": "痛苦压抑",
        "sound_effects_simple": ["风声"],
        "music_cue_simple": "低沉弦乐",
    }]
    sanitized = routes_script._sanitize_incoming_script_segments(incoming, existing)

    assert "audio_path" not in sanitized[0]
    assert "audio_cache_key" not in sanitized[0]
    assert "audio_render_chunk_max_chars" not in sanitized[0]
    assert "sfx_audio_path" not in sanitized[0]
    assert "mix_audio_path" not in sanitized[0]
    assert sanitized[0]["bgm_audio_path"] == existing[0]["bgm_audio_path"]


def test_sanitize_incoming_script_segments_clears_whole_render_mode_when_voice_changes():
    existing = [{
        "type": "narration",
        "text": "原文",
        "speaker": "旁白",
        "performance_notes": "平静",
        "audio_path": "chapter_segments_persistent_voice/1/segment.mp3",
        "audio_cache_key": "voice-signature",
        "audio_render_chunk_max_chars": 360,
        "audio_render_mode": "whole_segment",
    }]
    incoming = [{
        "type": "narration",
        "text": "原文",
        "speaker": "旁白",
        "performance_notes": "痛苦压抑",
        # 客户端不能伪造服务端整段渲染标记。
        "audio_render_mode": "whole_segment",
    }]

    sanitized = routes_script._sanitize_incoming_script_segments(incoming, existing)

    assert "audio_path" not in sanitized[0]
    assert "audio_cache_key" not in sanitized[0]
    assert "audio_render_chunk_max_chars" not in sanitized[0]
    assert "audio_render_mode" not in sanitized[0]


def test_sanitize_incoming_script_segments_follows_stable_keys_when_reordered():
    existing = [
        {
            "segment_key": "seg-a",
            "type": "narration",
            "text": "甲段",
            "speaker": "旁白",
            "audio_path": "chapter_segments_persistent_voice/1/a.mp3",
            "mix_audio_path": "chapter_segments_persistent_mix/1/a.mp3",
        },
        {
            "segment_key": "seg-b",
            "type": "dialogue",
            "text": "乙段",
            "speaker": "角色乙",
            "audio_path": "chapter_segments_persistent_voice/1/b.mp3",
            "mix_audio_path": "chapter_segments_persistent_mix/1/b.mp3",
        },
    ]
    incoming = [
        {"segment_key": "seg-b", "type": "dialogue", "text": "乙段", "speaker": "角色乙"},
        {"segment_key": "seg-a", "type": "narration", "text": "甲段", "speaker": "旁白"},
    ]

    sanitized = routes_script._sanitize_incoming_script_segments(incoming, existing)

    assert sanitized[0]["segment_key"] == "seg-b"
    assert sanitized[0]["audio_path"].endswith("/b.mp3")
    assert sanitized[0]["mix_audio_path"].endswith("/b.mp3")
    assert sanitized[1]["segment_key"] == "seg-a"
    assert sanitized[1]["audio_path"].endswith("/a.mp3")
    assert sanitized[1]["mix_audio_path"].endswith("/a.mp3")


def test_sanitize_incoming_script_segments_migrates_legacy_reorder_by_unique_identity():
    existing = [
        {
            "type": "narration",
            "text": "第一段",
            "speaker": "旁白",
            "audio_path": "chapter_segments_persistent_voice/1/first.mp3",
        },
        {
            "type": "narration",
            "text": "第二段",
            "speaker": "旁白",
            "audio_path": "chapter_segments_persistent_voice/1/second.mp3",
        },
    ]
    incoming = [
        {"type": "narration", "text": "第二段", "speaker": "旁白"},
        {"type": "narration", "text": "第一段", "speaker": "旁白"},
    ]

    sanitized = routes_script._sanitize_incoming_script_segments(incoming, existing)

    assert sanitized[0]["audio_path"].endswith("/second.mp3")
    assert sanitized[1]["audio_path"].endswith("/first.mp3")
    assert sanitized[0]["segment_key"] != sanitized[1]["segment_key"]


def test_sanitize_incoming_script_segments_does_not_carry_assets_to_unmatched_inserted_segment():
    existing = [{
        "segment_key": "seg-existing",
        "type": "narration",
        "text": "旧段",
        "speaker": "旁白",
        "audio_path": "chapter_segments_persistent_voice/1/old.mp3",
        "mix_audio_path": "chapter_segments_persistent_mix/1/old.mp3",
    }]
    incoming = [
        {"type": "narration", "text": "新插入", "speaker": "旁白"},
        {"segment_key": "seg-existing", "type": "narration", "text": "旧段", "speaker": "旁白"},
    ]

    sanitized = routes_script._sanitize_incoming_script_segments(incoming, existing)

    assert "audio_path" not in sanitized[0]
    assert "mix_audio_path" not in sanitized[0]
    assert sanitized[1]["segment_key"] == "seg-existing"
    assert sanitized[1]["audio_path"].endswith("/old.mp3")


def test_sanitize_incoming_script_segments_rejects_unknown_key_asset_inheritance():
    existing = [{
        "segment_key": "seg-server",
        "type": "narration",
        "text": "相同文本",
        "speaker": "旁白",
        "audio_path": "chapter_segments_persistent_voice/1/server.mp3",
    }]
    incoming = [{
        "segment_key": "seg-from-another-chapter",
        "type": "narration",
        "text": "相同文本",
        "speaker": "旁白",
    }]

    sanitized = routes_script._sanitize_incoming_script_segments(incoming, existing)

    assert sanitized[0]["segment_key"] not in {
        "seg-server",
        "seg-from-another-chapter",
    }
    assert "audio_path" not in sanitized[0]


def test_sanitize_incoming_script_segments_keeps_omitted_semantic_fields_for_partial_patch():
    existing = [{
        "segment_key": "seg-partial",
        "type": "dialogue",
        "text": "原台词",
        "speaker": "林晚",
        "emotion": "sad",
        "performance_notes": "压低声音",
    }]

    sanitized = routes_script._sanitize_incoming_script_segments(
        [{"segment_key": "seg-partial", "text": "修改后的台词"}],
        existing,
    )

    assert sanitized[0]["text"] == "修改后的台词"
    assert sanitized[0]["type"] == "dialogue"
    assert sanitized[0]["speaker"] == "林晚"
    assert sanitized[0]["emotion"] == "sad"
    assert sanitized[0]["performance_notes"] == "压低声音"


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


def test_completed_chapter_runs_are_ordered_by_finish_time():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_script_context(db)
        base_time = datetime(2026, 1, 1, 12, 0, 0)
        created_later_but_finished_first = ChapterAudioRun(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="audio_from_scripts",
            status="completed",
            current_stage="completed",
            resumable=False,
            created_at=base_time + timedelta(minutes=10),
            finished_at=base_time + timedelta(minutes=20),
        )
        created_first_but_finished_last = ChapterAudioRun(
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            run_type="chapter_remix",
            status="completed",
            current_stage="completed",
            resumable=False,
            created_at=base_time,
            finished_at=base_time + timedelta(minutes=30),
        )
        db.add_all([created_later_but_finished_first, created_first_but_finished_last])
        db.commit()

        runs = ChapterAudioRunRepository.list_completed_runs_for_chapter(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
            limit=2,
        )
        latest = ChapterAudioRunRepository.get_latest_completed_run(
            db,
            audiobook_project_id=context["audiobook_project"].id,
            chapter_id=context["chapter"].id,
        )

        assert [run.id for run in runs] == [
            created_first_but_finished_last.id,
            created_later_but_finished_first.id,
        ]
        assert latest.id == created_first_but_finished_last.id


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


def test_update_chapter_script_key_migration_does_not_mark_audio_stale():
    session_factory = build_session_factory()

    with session_factory() as db:
        context = seed_script_context(db)
        chapter_audio = context["chapter_audio"]
        chapter_audio.final_audio_review_json = '{"quality":"passed"}'
        db.commit()
        db.refresh(chapter_audio)
        previous_updated_at = chapter_audio.updated_at

        owned = OwnedAudiobookProject(
            audiobook_project=context["audiobook_project"],
            project=context["project"],
            current_user=context["user"],
            db=db,
        )
        request = ChapterScriptUpdateRequest(
            script_segments=[{
                "type": "narration",
                "text": "第一段",
                "speaker": "旁白",
                "emotion": "neutral",
            }],
            script_status="approved",
        )

        payload = asyncio.run(
            routes_script.update_chapter_script(
                audiobook_project_id=context["audiobook_project"].id,
                chapter_id=context["chapter"].id,
                request=request,
                owned=owned,
            )
        )

        db.refresh(chapter_audio)
        saved_segment = json.loads(chapter_audio.script_json)[0]
        assert saved_segment["segment_key"].startswith("seg_")
        assert chapter_audio.updated_at == previous_updated_at
        assert chapter_audio.final_audio_review_json == '{"quality":"passed"}'
        assert payload["chapter_audio_stale"] is False
