import sys
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


TEST_CHAPTER_AUDIO_ID = 98765001


@pytest.fixture()
def cleanup_test_assets():
    yield
    from app.services.audiobook import chapter_segment_assets

    chapter_audio = SimpleNamespace(id=TEST_CHAPTER_AUDIO_ID, script_json=None)
    chapter_segment_assets.delete_chapter_persistent_segment_assets(chapter_audio)


def test_save_and_load_persistent_segment_audio(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets

    asset_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=3,
        audio_bytes=b"ID3 persistent segment audio",
    )

    assert asset_ref
    assert chapter_segment_assets.persistent_segment_audio_exists(asset_ref) is True
    assert (
        chapter_segment_assets.load_persistent_segment_audio(asset_ref)
        == b"ID3 persistent segment audio"
    )


def test_save_persistent_segment_audio_replaces_previous_file(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets

    old_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=5,
        audio_bytes=b"ID3 old version",
    )
    new_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=5,
        audio_bytes=b"ID3 new version",
    )

    # 重新保存后旧版本文件必须被清除，只保留最新版本
    assert new_ref != old_ref
    assert chapter_segment_assets.persistent_segment_audio_exists(old_ref) is False
    assert chapter_segment_assets.persistent_segment_audio_exists(new_ref) is True
    assert (
        chapter_segment_assets.load_persistent_segment_audio(new_ref)
        == b"ID3 new version"
    )


def test_resolve_segment_asset_storage_index_is_stable_across_reorder():
    from app.services.audiobook import chapter_segment_assets

    original_slot = chapter_segment_assets.resolve_segment_asset_storage_index(
        {"segment_key": "segment-a"},
        0,
    )
    reordered_slot = chapter_segment_assets.resolve_segment_asset_storage_index(
        {"segment_key": "segment-a"},
        7,
    )

    assert original_slot == reordered_slot
    assert original_slot >= 1_000_000_000
    assert chapter_segment_assets.resolve_segment_asset_storage_index({}, 7) == 7


def test_reordered_segment_save_does_not_delete_other_legacy_index_asset(
    cleanup_test_assets,
):
    from app.services.audiobook import chapter_segment_assets

    other_legacy_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=1,
        audio_bytes=b"ID3 segment-b legacy index audio",
    )
    original_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        segment_key="segment-a",
        audio_bytes=b"ID3 segment-a original audio",
    )
    reordered_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=1,
        segment_key="segment-a",
        audio_bytes=b"ID3 segment-a reordered audio",
    )

    assert chapter_segment_assets.persistent_segment_audio_exists(other_legacy_ref) is True
    assert chapter_segment_assets.persistent_segment_audio_exists(original_ref) is False
    assert chapter_segment_assets.persistent_segment_audio_exists(reordered_ref) is True


def test_delete_chapter_persistent_segment_assets_removes_all_preview_types(cleanup_test_assets):
    from app.services.audiobook import chapter_segment_assets

    voice_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 voice",
    )
    mix_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 mix",
        preview_type="mix",
    )

    chapter_audio = SimpleNamespace(id=TEST_CHAPTER_AUDIO_ID, script_json=None)
    chapter_segment_assets.delete_chapter_persistent_segment_assets(chapter_audio)

    assert chapter_segment_assets.persistent_segment_audio_exists(voice_ref) is False
    assert chapter_segment_assets.persistent_segment_audio_exists(mix_ref) is False


def test_collect_chapter_segment_asset_refs_includes_chunk_cache_paths():
    from app.services.audiobook import chapter_segment_assets

    chapter_audio = SimpleNamespace(
        script_json=json.dumps(
            [
                {
                    "audio_path": "persistent/voice.mp3",
                    "sfx_audio_path": "persistent/sfx.mp3",
                    "audio_chunk_cache_paths": {
                        "chunk-a": "persistent/chunk-a.mp3",
                        "chunk-b": "persistent/chunk-b.mp3",
                    },
                }
            ]
        )
    )

    assert chapter_segment_assets.collect_chapter_segment_asset_refs(chapter_audio) == {
        "persistent/voice.mp3",
        "persistent/sfx.mp3",
        "persistent/chunk-a.mp3",
        "persistent/chunk-b.mp3",
    }


def test_delete_segment_asset_refs_uses_explicit_asset_manifest(monkeypatch):
    from app.services.audiobook import chapter_segment_assets

    calls = []
    monkeypatch.setattr(
        chapter_segment_assets,
        "delete_temp_segment_prefix",
        lambda prefix, checkpoint_json=None: calls.append((prefix, checkpoint_json)) or 2,
    )

    removed = chapter_segment_assets.delete_segment_asset_refs(
        {"persistent/chunk-b.mp3", "persistent/chunk-a.mp3"}
    )

    assert removed == 2
    assert calls == [
        (
            None,
            {
                "cached_audio_paths": {
                    "0": "persistent/chunk-a.mp3",
                    "1": "persistent/chunk-b.mp3",
                }
            },
        )
    ]


def test_delete_replaced_segment_asset_refs_only_removes_unreferenced_persistent_refs(
    monkeypatch,
):
    from app.services.audiobook import chapter_segment_assets

    captured = []
    monkeypatch.setattr(
        chapter_segment_assets,
        "delete_segment_asset_refs",
        lambda refs: captured.extend(sorted(refs)) or len(captured),
    )

    removed = chapter_segment_assets.delete_replaced_segment_asset_refs(
        {
            "persistent/chapter_segments_persistent_voice/old.mp3",
            "persistent/chapter_segments_persistent_voice/shared.mp3",
            "C:/legacy/non-managed.mp3",
        },
        {"persistent/chapter_segments_persistent_voice/shared.mp3"},
    )

    assert removed == 1
    assert captured == ["persistent/chapter_segments_persistent_voice/old.mp3"]


def test_compute_segment_audio_cache_key_changes_with_text():
    from app.services.audiobook import chapter_segment_assets

    segment = {
        "type": "narration",
        "text": "片段原始文本",
        "speaker": "旁白",
        "voice_params": {"speaker": "voice-a"},
    }
    modified = dict(segment)
    modified["text"] = "片段修改后的文本"

    original_key = chapter_segment_assets.compute_segment_audio_cache_key(segment)
    assert original_key
    assert chapter_segment_assets.compute_segment_audio_cache_key(segment) == original_key
    assert (
        chapter_segment_assets.compute_segment_audio_cache_key(modified) != original_key
    )


def test_compute_segment_audio_cache_key_changes_with_voice_identity_policy(monkeypatch):
    from app.services.audiobook import chapter_segment_assets, render_plan

    segment = {
        "type": "narration",
        "text": "痛意沿着肩胛骨炸开。",
        "speaker": "旁白",
        "performance_notes": "音调低沉，语速缓慢，重读痛字。",
        "voice_params": {
            "speaker": "voice-a",
            "tts_model": "seed-tts-2.0-expressive",
        },
    }

    original_key = chapter_segment_assets.compute_segment_audio_cache_key(segment)
    monkeypatch.setattr(
        render_plan,
        "VOICE_IDENTITY_POLICY_VERSION",
        render_plan.VOICE_IDENTITY_POLICY_VERSION + 1,
    )

    assert chapter_segment_assets.compute_segment_audio_cache_key(segment) != original_key


def test_compute_segment_audio_cache_key_matches_single_render_chunk_signature():
    """签名必须与 build_render_plan 单 chunk 的 cache_key 一致，保证管线按签名复用。"""
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.render_plan import build_render_plan

    segment = {
        "type": "dialogue",
        "text": "你好，世界。",
        "speaker": "林晚",
        "emotion": "sad",
        "voice_params": {"speaker": "voice-b", "tts_model": "seed-tts-2.0-expressive"},
    }

    chunks = build_render_plan([SimpleNamespace(**segment)])
    assert len(chunks) == 1
    assert chapter_segment_assets.compute_segment_audio_cache_key(segment) == chunks[0].cache_key
