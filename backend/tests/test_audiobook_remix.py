import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


TEST_CHAPTER_AUDIO_ID = 98765401


@pytest.fixture()
def cleanup_test_assets():
    yield
    from app.services.audiobook import chapter_segment_assets

    chapter_audio = SimpleNamespace(id=TEST_CHAPTER_AUDIO_ID, script_json=None)
    chapter_segment_assets.delete_chapter_persistent_segment_assets(chapter_audio)


def _mark_voice_audio_signature_current(segment):
    from app.services.audiobook import chapter_segment_assets

    chunk_limit = 420
    segment["audio_cache_key"] = chapter_segment_assets.compute_segment_audio_cache_key(
        segment,
        render_chunk_max_chars=chunk_limit,
    )
    segment["audio_render_chunk_max_chars"] = chunk_limit


def _build_segments_with_audio():
    from app.services.audiobook import chapter_segment_assets

    segments = [
        {
            "type": "narration",
            "text": "第一段旁白，已有持久化音频。",
            "speaker": "旁白",
            "voice_params": {"speaker": "voice-a"},
        },
        {
            "type": "dialogue",
            "text": "第二段对白，已有持久化音频。",
            "speaker": "林深",
            "voice_params": {"speaker": "voice-b"},
        },
    ]
    refs = [
        chapter_segment_assets.save_persistent_segment_audio(
            chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
            segment_index=index,
            audio_bytes=b"ID3 segment audio",
        )
        for index in range(len(segments))
    ]
    for index, ref in enumerate(refs):
        segments[index]["audio_path"] = ref
        _mark_voice_audio_signature_current(segments[index])
    return segments


def _build_fake_engine():
    mixer_calls = {}

    class FakeMixer:
        def build_segment_timeline(self, audio_segments, **kwargs):
            mixer_calls["timeline"] = True
            return [
                {"index": idx, "start": 0.0, "end": 1.0, "duration": 1.0}
                for idx in range(len(audio_segments))
                if audio_segments[idx]
            ]

        def mix_chapter(self, audio_segments, **kwargs):
            mixer_calls["mix"] = True
            mixer_calls["segment_count"] = len(audio_segments)
            mixer_calls["audio_segments"] = list(audio_segments)
            return b"ID3 mixed chapter audio"

        def add_sound_effect(
            self,
            voice_audio,
            effect_audio,
            position_ms,
            **kwargs,
        ):
            mixer_calls.setdefault("segment_sfx", []).append(
                (voice_audio, effect_audio, position_ms, kwargs)
            )
            return voice_audio + b"|sfx|" + effect_audio

        def add_background_music(self, voice_audio, bgm_audio, **kwargs):
            mixer_calls.setdefault("segment_bgm", []).append(
                (voice_audio, bgm_audio, kwargs)
            )
            return voice_audio + b"|bgm|" + bgm_audio

        def transcode_audio(self, audio_data, output_format=None):
            return audio_data

        def get_audio_info(self, audio_data):
            return {"duration_seconds": 12.5}

    def apply_sound_effects(audio, timeline):
        mixer_calls["chapter_effect_timeline"] = timeline
        return audio

    def apply_background_music(audio, timeline):
        mixer_calls["chapter_music_timeline"] = timeline
        return audio

    engine = SimpleNamespace(
        audio_mixer=FakeMixer(),
        _build_mixer_segment_types=lambda segments: ["sentence"] * len(segments),
        _build_mixer_pause_after_ms=lambda segments: [None] * len(segments),
        _apply_sound_effects=apply_sound_effects,
        _apply_background_music=apply_background_music,
        apply_audio_fx_config=lambda config: None,
    )
    return engine, mixer_calls


def _load_remix_module():
    from app.services.audiobook import background_jobs_remix as remix

    return remix


def test_rescale_timeline_reanchors_cues_to_their_segment_instead_of_global_ratio():
    remix = _load_remix_module()
    timeline = {
        "timeline": [
            {
                "scene_id": "scene_0",
                "timestamp": 0.5,
                "duration": 0.2,
                "description": "first segment cue",
            },
            {
                "scene_id": "scene_1",
                "timestamp": 1.25,
                "duration": 0.4,
                "description": "second segment cue",
            },
        ]
    }
    old_timings = [
        {"index": 0, "start": 0.0, "end": 1.0, "duration": 1.0},
        {"index": 1, "start": 1.0, "end": 2.0, "duration": 1.0},
    ]
    new_timings = [
        {"index": 0, "start": 0.0, "end": 2.0, "duration": 2.0},
        {"index": 1, "start": 2.0, "end": 3.0, "duration": 1.0},
    ]

    rescaled = remix._rescale_timeline_for_new_duration(
        timeline,
        old_timings=old_timings,
        new_timings=new_timings,
    )

    assert rescaled["timeline"][0]["timestamp"] == 0.5
    assert rescaled["timeline"][0]["duration"] == 0.2
    assert rescaled["timeline"][1]["timestamp"] == 2.25
    assert rescaled["timeline"][1]["duration"] == 0.4


def test_collect_missing_segments_reports_unavailable_audio(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets

    remix = _load_remix_module()

    segments = [
        {
            "type": "narration",
            "text": "第一段已有持久化音频。",
            "speaker": "旁白",
        },
        {
            "type": "dialogue",
            "text": "第二段没有音频路径。",
            "speaker": "林深",
        },
        {
            "type": "dialogue",
            "text": "第三段引用临时 run 音频。",
            "speaker": "林深",
            "audio_path": "audio_from_scripts_9/segment-2.mp3",
        },
        {
            "type": "narration",
            "text": "第四段引用已删除的持久化音频。",
            "speaker": "旁白",
            "audio_path": "chapter_segments_persistent_voice/999999/segment-3.mp3",
        },
    ]
    asset_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 available",
    )
    segments[0]["audio_path"] = asset_ref
    _mark_voice_audio_signature_current(segments[0])
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )

    missing = remix.collect_chapter_remix_missing_segments(chapter_audio)

    assert [item["index"] for item in missing] == [1, 2, 3]
    assert missing[0]["speaker"] == "林深"
    assert missing[0]["text_preview"]
    assert all(item["reason"] for item in missing)


def test_collect_missing_segments_accepts_saved_mix_without_voice(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets

    remix = _load_remix_module()
    mix_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 complete saved mix",
        preview_type="mix",
    )
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(
            [{"type": "narration", "text": "完整混音片段", "mix_audio_path": mix_ref}],
            ensure_ascii=False,
        ),
    )

    assert remix.collect_chapter_remix_missing_segments(chapter_audio) == []


def test_collect_missing_segments_reports_registered_non_voice_files_that_are_missing(
    cleanup_test_assets,
):
    from app.services.audiobook import chapter_segment_assets

    remix = _load_remix_module()
    segments = _build_segments_with_audio()
    existing_sfx_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 temporary source for missing ref",
        preview_type="sfx",
    )
    segments[0]["sfx_audio_path"] = existing_sfx_ref.replace(".mp3", "-missing.mp3")
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
        audio_path="old_chapter.mp3",
    )

    missing = remix.collect_chapter_remix_missing_segments(chapter_audio)

    assert missing == [
        {
            "index": 0,
            "speaker": "旁白",
            "text_preview": "第一段旁白，已有持久化音频。",
            "reason": "file_missing",
            "asset_type": "sfx",
        }
    ]


def test_load_segment_remix_sources_never_promotes_temporary_mix_ref(monkeypatch):
    remix = _load_remix_module()
    temporary_mix_ref = "segment_regen_candidate_mix_12/chapter-9/segment-0.mp3"
    persistent_voice_ref = (
        "chapter_segments_persistent_voice/chapter-9/segment-0.mp3"
    )
    loaded_refs = []

    def fake_load(asset_ref):
        loaded_refs.append(asset_ref)
        return b"ID3 temporary mix" if asset_ref == temporary_mix_ref else b"ID3 voice"

    monkeypatch.setattr(remix, "load_persistent_segment_audio", fake_load)

    sources = remix._load_segment_remix_sources(
        {
            "audio_path": persistent_voice_ref,
            "mix_audio_path": temporary_mix_ref,
        }
    )

    assert sources["base_audio"] == b"ID3 voice"
    assert sources["uses_mix"] is False
    assert temporary_mix_ref not in loaded_refs


def test_perform_remix_without_force_aborts_on_missing(cleanup_test_assets, monkeypatch):
    remix = _load_remix_module()

    segments = _build_segments_with_audio()
    segments.append(
        {
            "type": "narration",
            "text": "第三段缺失音频。",
            "speaker": "旁白",
        }
    )
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )
    engine, mixer_calls = _build_fake_engine()
    run_updates = []

    result = remix.perform_chapter_remix(
        chapter_audio=chapter_audio,
        chapter_number=1,
        audiobook_project=SimpleNamespace(project_id=5),
        force=False,
        engine=engine,
        checkpoint={},
        run_state_updater=lambda **kwargs: run_updates.append(kwargs),
        write_output=lambda path, data: None,
        generate_subtitle_artifacts=lambda **kwargs: {"generated": False},
    )

    assert result["success"] is False
    assert len(result["missing_segments"]) == 1
    assert "mix" not in mixer_calls
    assert run_updates and run_updates[0]["status"] == "failed"


def test_perform_remix_mixes_and_writes_output(cleanup_test_assets, monkeypatch):
    remix = _load_remix_module()

    segments = _build_segments_with_audio()
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )
    engine, mixer_calls = _build_fake_engine()
    run_updates = []
    written = {}

    def fake_write_output(path, data):
        written["path"] = path
        written["data"] = data

    effect_timeline = {"timeline": [{"start": 0.0, "track": "sfx"}]}
    music_timeline = {"timeline": [{"start": 0.0, "track": "suspense"}]}

    result = remix.perform_chapter_remix(
        chapter_audio=chapter_audio,
        chapter_number=3,
        audiobook_project=SimpleNamespace(project_id=5),
        force=False,
        engine=engine,
        checkpoint={"effect_timeline": effect_timeline, "music_timeline": music_timeline},
        run_state_updater=lambda **kwargs: run_updates.append(kwargs),
        write_output=fake_write_output,
        generate_subtitle_artifacts=lambda **kwargs: {"generated": True},
    )

    assert result["success"] is True
    assert mixer_calls["mix"] is True
    assert mixer_calls["segment_count"] == 2
    assert written["path"].endswith("chapter_003.mp3")
    assert chapter_audio.audio_path == written["path"]
    assert chapter_audio.duration == 12.5
    assert result["duration"] == 12.5
    assert run_updates[-1]["status"] == "completed"
    assert run_updates[-1]["run_type"] == "chapter_remix"
    assert run_updates[-1]["checkpoint_patch"]["segment_timings"]


def test_perform_remix_does_not_write_after_output_guard_rejects(cleanup_test_assets):
    """章节产物删除后，重混音不得再写出孤儿整章文件。"""
    remix = _load_remix_module()

    segments = _build_segments_with_audio()
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )
    engine, _ = _build_fake_engine()
    run_updates = []
    writes = []

    result = remix.perform_chapter_remix(
        chapter_audio=chapter_audio,
        chapter_number=3,
        audiobook_project=SimpleNamespace(project_id=5),
        force=False,
        engine=engine,
        checkpoint={},
        run_state_updater=lambda **kwargs: run_updates.append(kwargs),
        write_output=lambda path, data: writes.append((path, data)),
        generate_subtitle_artifacts=lambda **kwargs: {"generated": False},
        before_write_output=lambda path, data: False,
    )

    assert result == {
        "success": False,
        "error": "chapter_audio_not_found",
        "missing_segments": [],
    }
    assert writes == []
    assert run_updates[-1]["status"] == "cancelled"


def test_perform_remix_cleans_output_when_deleted_after_write(
    cleanup_test_assets,
    monkeypatch,
):
    """删除恰好发生在写盘前后检查之间时，回收新文件且不更新章节记录。"""
    remix = _load_remix_module()

    segments = _build_segments_with_audio()
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
        audio_path="old_chapter.mp3",
    )
    engine, _ = _build_fake_engine()
    run_updates = []
    writes = []
    cleanups = []
    active_results = iter((True, True, False))

    monkeypatch.setattr(
        remix,
        "_cleanup_previous_chapter_artifacts",
        lambda path, **kwargs: cleanups.append((path, kwargs)),
    )

    result = remix.perform_chapter_remix(
        chapter_audio=chapter_audio,
        chapter_number=3,
        audiobook_project=SimpleNamespace(project_id=5),
        force=False,
        engine=engine,
        checkpoint={},
        run_state_updater=lambda **kwargs: run_updates.append(kwargs),
        write_output=lambda path, data: writes.append((path, data)),
        generate_subtitle_artifacts=lambda **kwargs: {
            "generated": True,
            "subtitle_path": "chapter_003.srt",
        },
        before_write_output=lambda path, data: next(active_results),
    )

    assert result["success"] is False
    assert result["error"] == "chapter_audio_not_found"
    assert len(writes) == 1
    output_cleanup = next(
        (item for item in cleanups if item[1].get("extra_paths")),
        None,
    )
    assert output_cleanup is not None
    assert output_cleanup[0] == writes[0][0]
    assert output_cleanup[1]["extra_paths"] == ["chapter_003.srt"]
    assert chapter_audio.audio_path == "old_chapter.mp3"
    assert run_updates[-1]["status"] == "cancelled"


def test_perform_remix_prefers_saved_mix_and_suppresses_old_segment_timelines(
    cleanup_test_assets,
):
    from app.services.audiobook import chapter_segment_assets

    remix = _load_remix_module()
    segments = _build_segments_with_audio()
    segments[0]["mix_audio_path"] = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 latest saved mix",
        preview_type="mix",
    )
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )
    engine, mixer_calls = _build_fake_engine()
    checkpoint = {
        "effect_timeline": {
            "timeline": [
                {"scene_id": "scene_0", "description": "old segment effect"},
                {"scene_id": "scene_1", "description": "other segment effect"},
            ]
        },
        "music_timeline": {
            "timeline": [
                {"scene_id": "scene_0", "description": "old segment music"},
                {"scene_id": "scene_1", "description": "other segment music"},
            ]
        },
    }

    result = remix.perform_chapter_remix(
        chapter_audio=chapter_audio,
        chapter_number=1,
        audiobook_project=SimpleNamespace(project_id=5),
        force=False,
        engine=engine,
        checkpoint=checkpoint,
        run_state_updater=lambda **kwargs: None,
        write_output=lambda path, data: None,
        generate_subtitle_artifacts=lambda **kwargs: {"generated": False},
    )

    assert result["success"] is True
    assert mixer_calls["audio_segments"][0] == b"ID3 latest saved mix"
    assert mixer_calls["chapter_effect_timeline"]["timeline"] == [
        {"scene_id": "scene_1", "description": "other segment effect"}
    ]
    assert mixer_calls["chapter_music_timeline"]["timeline"] == [
        {"scene_id": "scene_1", "description": "other segment music"}
    ]


def test_perform_remix_composes_saved_stems_and_keeps_other_segment_timelines(
    cleanup_test_assets,
):
    from app.services.audiobook import chapter_segment_assets

    remix = _load_remix_module()
    segments = _build_segments_with_audio()
    segments[0]["sfx_audio_path"] = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 latest saved sfx stem",
        preview_type="sfx",
    )
    segments[0]["bgm_audio_path"] = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 latest saved bgm stem",
        preview_type="bgm",
    )
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )
    engine, mixer_calls = _build_fake_engine()
    checkpoint = {
        "effect_timeline": {
            "timeline": [
                {"scene_id": "scene_0", "description": "old segment effect"},
                {"scene_id": "scene_1", "description": "other segment effect"},
            ]
        },
        "music_timeline": {
            "timeline": [
                {"scene_id": "scene_0", "description": "old segment music"},
                {"scene_id": "scene_1", "description": "other segment music"},
            ]
        },
    }

    result = remix.perform_chapter_remix(
        chapter_audio=chapter_audio,
        chapter_number=1,
        audiobook_project=SimpleNamespace(project_id=5),
        force=False,
        engine=engine,
        checkpoint=checkpoint,
        run_state_updater=lambda **kwargs: None,
        write_output=lambda path, data: None,
        generate_subtitle_artifacts=lambda **kwargs: {"generated": False},
    )

    assert result["success"] is True
    assert mixer_calls["audio_segments"][0] == (
        b"ID3 segment audio"
        b"|sfx|ID3 latest saved sfx stem"
        b"|bgm|ID3 latest saved bgm stem"
    )
    assert len(mixer_calls["segment_sfx"]) == 1
    assert len(mixer_calls["segment_bgm"]) == 1
    assert mixer_calls["chapter_effect_timeline"]["timeline"] == [
        {"scene_id": "scene_1", "description": "other segment effect"}
    ]
    assert mixer_calls["chapter_music_timeline"]["timeline"] == [
        {"scene_id": "scene_1", "description": "other segment music"}
    ]


def test_perform_remix_force_mode_mixes_with_missing_segments(cleanup_test_assets):
    remix = _load_remix_module()

    segments = _build_segments_with_audio()
    segments.append(
        {
            "type": "narration",
            "text": "第三段缺失音频（用户确认继续）。",
            "speaker": "旁白",
        }
    )
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )
    engine, mixer_calls = _build_fake_engine()
    run_updates = []

    result = remix.perform_chapter_remix(
        chapter_audio=chapter_audio,
        chapter_number=1,
        audiobook_project=SimpleNamespace(project_id=5),
        force=True,
        engine=engine,
        checkpoint={},
        run_state_updater=lambda **kwargs: run_updates.append(kwargs),
        write_output=lambda path, data: None,
        generate_subtitle_artifacts=lambda **kwargs: {"generated": False},
    )

    assert result["success"] is True
    assert mixer_calls["mix"] is True
    assert result["missing_segments"][0]["index"] == 2
    assert run_updates[-1]["status"] == "completed"


def test_remix_endpoint_requires_confirmation_when_segments_missing(monkeypatch):
    from app.api.v1.audiobook_api import routes_remix
    from app.schemas.audiobook import RemixChapterRequest

    missing_segments = [{"index": 1, "speaker": "林深", "text_preview": "缺失", "reason": "no_audio_path"}]

    class FakeBackgroundTasks:
        def __init__(self):
            self.added = []

        def add_task(self, func, *args, **kwargs):
            self.added.append((func, args, kwargs))

    monkeypatch.setattr(
        routes_remix,
        "get_active_chapter_audio_for_project",
        lambda **_: SimpleNamespace(id=TEST_CHAPTER_AUDIO_ID, script_json="[]"),
    )
    monkeypatch.setattr(
        routes_remix.ChapterAudioRunRepository,
        "get_latest_run",
        lambda db, **kwargs: None,
    )
    monkeypatch.setattr(
        routes_remix,
        "collect_chapter_remix_missing_segments",
        lambda chapter_audio: missing_segments,
    )
    background_tasks = FakeBackgroundTasks()

    response = asyncio_run(
        routes_remix.remix_chapter(
            audiobook_project_id=1,
            chapter_id=2,
            request=RemixChapterRequest(force=False),
            background_tasks=background_tasks,
            owned=SimpleNamespace(db=SimpleNamespace()),
        )
    )

    assert response["success"] is False
    assert response["requires_confirmation"] is True
    assert response["missing_segments"] == missing_segments
    assert background_tasks.added == []


def test_remix_endpoint_force_triggers_background_task(monkeypatch):
    from app.api.v1.audiobook_api import routes_remix
    from app.schemas.audiobook import RemixChapterRequest

    missing_segments = [{"index": 1, "speaker": "林深", "text_preview": "缺失", "reason": "no_audio_path"}]

    class FakeBackgroundTasks:
        def __init__(self):
            self.added = []

        def add_task(self, func, *args, **kwargs):
            self.added.append((func, args, kwargs))

    monkeypatch.setattr(
        routes_remix,
        "get_active_chapter_audio_for_project",
        lambda **_: SimpleNamespace(id=TEST_CHAPTER_AUDIO_ID, script_json="[]"),
    )
    monkeypatch.setattr(
        routes_remix.ChapterAudioRunRepository,
        "get_latest_run",
        lambda db, **kwargs: SimpleNamespace(id=55, status="completed"),
    )
    monkeypatch.setattr(
        routes_remix,
        "collect_chapter_remix_missing_segments",
        lambda chapter_audio: missing_segments,
    )
    monkeypatch.setattr(routes_remix, "_update_chapter_run_state", lambda db, **kwargs: None)
    background_tasks = FakeBackgroundTasks()

    response = asyncio_run(
        routes_remix.remix_chapter(
            audiobook_project_id=1,
            chapter_id=2,
            request=RemixChapterRequest(force=True),
            background_tasks=background_tasks,
            owned=SimpleNamespace(db=SimpleNamespace(commit=lambda: None)),
        )
    )

    assert response["success"] is True
    assert response["status"] == "remix_queued"
    assert response["run_id"] == 55
    assert len(background_tasks.added) == 1
    assert background_tasks.added[0][0].__name__ == "run_chapter_remix_background"
    assert background_tasks.added[0][2].get("run_id") == 55


def asyncio_run(awaitable):
    import asyncio

    return asyncio.run(awaitable)
