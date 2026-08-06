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


TEST_CHAPTER_AUDIO_ID = 98765301
TEST_RUN_ID = f"writeback_test_run_{TEST_CHAPTER_AUDIO_ID}"


@pytest.fixture()
def cleanup_test_assets():
    yield
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.temp_segment_store import (
        build_temp_segment_prefix,
        delete_temp_segment_prefix,
    )

    chapter_audio = SimpleNamespace(id=TEST_CHAPTER_AUDIO_ID, script_json=None)
    chapter_segment_assets.delete_chapter_persistent_segment_assets(chapter_audio)
    try:
        delete_temp_segment_prefix(
            build_temp_segment_prefix(run_id=TEST_RUN_ID, chapter_id=2), None
        )
    except Exception:
        pass


def _build_script_segments():
    return [
        {
            "type": "narration",
            "text": "第一段旁白文本。",
            "speaker": "旁白",
            "voice_params": {"speaker": "voice-a"},
        },
        {
            "type": "dialogue",
            "text": "第二段对白文本。",
            "speaker": "林深",
            "voice_params": {"speaker": "voice-b"},
        },
    ]


def test_persist_generated_segment_audio_writes_back_paths(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.temp_segment_store import save_segment_audio_map

    segments = _build_script_segments()
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )

    temp_cache = save_segment_audio_map(
        run_id=TEST_RUN_ID,
        chapter_id=2,
        audio_map={0: b"ID3 segment zero", 1: b"ID3 segment one"},
        format="mp3",
    )
    temp_cache["render_plan"] = [
        {"index": 0, "cache_key": "sig-0", "source_segment_indices": [0]},
        {"index": 1, "cache_key": "sig-1", "source_segment_indices": [1]},
    ]
    result = {"temp_segment_cache": temp_cache}

    persisted = chapter_segment_assets.persist_generated_chapter_segment_audio(
        chapter_audio=chapter_audio,
        result=result,
    )

    updated_segments = json.loads(chapter_audio.script_json)

    # run 临时片段音频必须固化到持久化前缀并写回 script_json
    assert set(persisted.keys()) == {0, 1}
    for index in (0, 1):
        assert updated_segments[index]["audio_path"] == persisted[index]
        assert chapter_segment_assets.is_persistent_segment_asset_ref(persisted[index])
        assert (
            chapter_segment_assets.load_persistent_segment_audio(persisted[index])
            is not None
        )
    assert updated_segments[0]["audio_cache_key"] == "sig-0"
    assert updated_segments[1]["audio_cache_key"] == "sig-1"


def test_persist_generated_segment_audio_skips_current_workbench_segments(
    cleanup_test_assets, monkeypatch
):
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.temp_segment_store import save_segment_audio_map

    segments = _build_script_segments()
    workbench_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 workbench audio",
    )
    segments[0]["audio_path"] = workbench_ref
    segments[0]["audio_cache_key"] = "sig-0"
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )

    # 片段 0 的工作台签名仍然有效：不得被管线音频覆盖
    monkeypatch.setattr(
        chapter_segment_assets,
        "segment_audio_cache_key_is_current",
        lambda segment, **_: str(segment.get("audio_cache_key") or "") == "sig-0",
    )

    temp_cache = save_segment_audio_map(
        run_id=TEST_RUN_ID,
        chapter_id=2,
        audio_map={0: b"ID3 pipeline zero", 1: b"ID3 pipeline one"},
        format="mp3",
    )
    temp_cache["render_plan"] = [
        {"index": 0, "cache_key": "sig-0", "source_segment_indices": [0]},
        {"index": 1, "cache_key": "sig-1", "source_segment_indices": [1]},
    ]

    persisted = chapter_segment_assets.persist_generated_chapter_segment_audio(
        chapter_audio=chapter_audio,
        result={"temp_segment_cache": temp_cache},
    )

    updated_segments = json.loads(chapter_audio.script_json)

    assert set(persisted.keys()) == {1}
    assert updated_segments[0]["audio_path"] == workbench_ref
    assert chapter_segment_assets.is_persistent_segment_asset_ref(persisted[1])


def test_persist_generated_segment_audio_ignores_multi_source_chunks(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.temp_segment_store import save_segment_audio_map

    segments = _build_script_segments()
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )

    temp_cache = save_segment_audio_map(
        run_id=TEST_RUN_ID,
        chapter_id=2,
        audio_map={0: b"ID3 merged chunk"},
        format="mp3",
    )
    # chunk 覆盖多个片段：无法安全归属到单个片段，跳过写回
    temp_cache["render_plan"] = [
        {"index": 0, "cache_key": "sig-merged", "source_segment_indices": [0, 1]},
    ]

    persisted = chapter_segment_assets.persist_generated_chapter_segment_audio(
        chapter_audio=chapter_audio,
        result={"temp_segment_cache": temp_cache},
    )

    updated_segments = json.loads(chapter_audio.script_json)

    assert persisted == {}
    assert "audio_path" not in updated_segments[0]


def test_checkpoint_patch_includes_music_timeline():
    from app.services.audiobook.background_jobs_shared import (
        build_checkpoint_patch_from_generation_result,
    )

    music_timeline = {"timeline": [{"start": 0.0, "track": "suspense"}]}
    patch = build_checkpoint_patch_from_generation_result(
        result={"music_timeline": music_timeline},
        task_id="task-1",
    )

    assert patch["music_timeline"] == music_timeline

    invalid_patch = build_checkpoint_patch_from_generation_result(
        result={"music_timeline": {"timeline": "not-a-list"}},
        task_id="task-2",
    )
    assert "music_timeline" not in invalid_patch
