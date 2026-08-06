import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


TEST_CHAPTER_AUDIO_ID = 98765201


@pytest.fixture()
def cleanup_test_assets():
    yield
    from app.services.audiobook import chapter_segment_assets

    chapter_audio = SimpleNamespace(id=TEST_CHAPTER_AUDIO_ID, script_json=None)
    chapter_segment_assets.delete_chapter_persistent_segment_assets(chapter_audio)


def _build_segments():
    return [
        {
            "type": "narration",
            "text": "第一段旁白文本，用于工作台复用测试。",
            "speaker": "旁白",
            "voice_params": {"speaker": "voice-a"},
        },
        {
            "type": "dialogue",
            "text": "第二段对白文本，未在工作台生成。",
            "speaker": "林深",
            "voice_params": {"speaker": "voice-b"},
        },
    ]


def test_merge_injects_matching_workbench_segment_into_checkpoint(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.background_jobs_shared import (
        merge_workbench_segment_audio_into_checkpoint,
    )
    from app.services.audiobook.render_plan import extract_render_signatures
    from app.services.audiobook.temp_segment_store import extract_cached_segment_paths

    segments = _build_segments()
    asset_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 workbench segment audio",
    )
    segments[0]["audio_path"] = asset_ref
    segments[0]["audio_cache_key"] = chapter_segment_assets.compute_segment_audio_cache_key(
        segments[0]
    )

    old_checkpoint = {
        "narration_style": "warm",
        "cached_audio_paths": {1: "runs/old/segment-1.mp3"},
        "render_plan": [{"index": 1, "cache_key": "old-signature-1"}],
    }

    merged = merge_workbench_segment_audio_into_checkpoint(
        script_segments=segments,
        resume_checkpoint=old_checkpoint,
    )

    # 工作台片段必须进入当前 checkpoint 的 cached_audio_paths，且签名可被引擎 remap
    assert merged["cached_audio_paths"][0] == asset_ref
    assert extract_render_signatures(merged)[0] == segments[0]["audio_cache_key"]
    assert extract_cached_segment_paths(merged)[0] == asset_ref
    # 原 run checkpoint 挂到 source_checkpoint 供断点继续复用，其余配置字段保留
    assert merged["source_checkpoint"] == old_checkpoint
    assert merged["narration_style"] == "warm"


def test_merge_skips_segment_with_stale_cache_key(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.background_jobs_shared import (
        merge_workbench_segment_audio_into_checkpoint,
    )

    segments = _build_segments()
    asset_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 stale workbench audio",
    )
    segments[0]["audio_path"] = asset_ref
    # 文本已修改但未重新生成：签名与当前片段不一致，不能复用
    segments[0]["audio_cache_key"] = "stale-signature"

    old_checkpoint = {"cached_audio_paths": {1: "runs/old/segment-1.mp3"}}

    merged = merge_workbench_segment_audio_into_checkpoint(
        script_segments=segments,
        resume_checkpoint=old_checkpoint,
    )

    assert merged == old_checkpoint


def test_merge_skips_segment_when_persistent_file_missing(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.background_jobs_shared import (
        merge_workbench_segment_audio_into_checkpoint,
    )

    segments = _build_segments()
    segments[0]["audio_path"] = "chapter_segments_persistent_voice/999999/segment-0.mp3"
    segments[0]["audio_cache_key"] = chapter_segment_assets.compute_segment_audio_cache_key(
        segments[0]
    )

    merged = merge_workbench_segment_audio_into_checkpoint(
        script_segments=segments,
        resume_checkpoint=None,
    )

    assert merged == {}


def test_merge_ignores_non_persistent_audio_refs(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.background_jobs_shared import (
        merge_workbench_segment_audio_into_checkpoint,
    )

    segments = _build_segments()
    # 普通 run 临时前缀的旧音频会被过期清理，不能作为种子注入
    segments[0]["audio_path"] = "audio_from_scripts_123/segment-0.mp3"
    segments[0]["audio_cache_key"] = chapter_segment_assets.compute_segment_audio_cache_key(
        segments[0]
    )

    merged = merge_workbench_segment_audio_into_checkpoint(
        script_segments=segments,
        resume_checkpoint=None,
    )

    assert merged == {}


def test_merge_reuses_long_workbench_segment_as_whole_render_chunk(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.background_jobs_shared import (
        merge_workbench_segment_audio_into_checkpoint,
    )
    from app.services.audiobook.engine_pkg._tts_mixin import QWEN_RENDER_CHUNK_MAX_CHARS
    from app.services.audiobook.render_plan import build_render_plan

    segment = {
        "type": "narration",
        "text": "长片段。" * (QWEN_RENDER_CHUNK_MAX_CHARS + 20),
        "speaker": "旁白",
        "voice_params": {
            "speaker": "voice-a",
            "tts_model": "qwen3-tts-instruct-flash",
        },
        "audio_render_mode": "whole_segment",
    }
    asset_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 long workbench segment",
    )
    segment["audio_path"] = asset_ref
    segment["audio_cache_key"] = chapter_segment_assets.compute_segment_audio_cache_key(
        segment,
        render_chunk_max_chars=QWEN_RENDER_CHUNK_MAX_CHARS,
    )
    assert segment["audio_cache_key"] == build_render_plan(
        [SimpleNamespace(**segment)],
        max_chunk_chars=QWEN_RENDER_CHUNK_MAX_CHARS,
    )[0].cache_key

    merged = merge_workbench_segment_audio_into_checkpoint(
        script_segments=[segment],
        resume_checkpoint=None,
        default_tts_model="qwen3-tts-instruct-flash",
    )

    assert merged["cached_audio_paths"][0] == asset_ref
    assert merged["total_segments"] == 1
