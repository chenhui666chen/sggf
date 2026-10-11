"""片段音频签名验签的分块策略上下文一致性测试。

回归目标：管线按默认分块上限生成片段后，
重新混合整章不得把未修改片段误报为 stale_audio 缺失。
"""

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


TEST_CHAPTER_AUDIO_ID = 98765501
TEST_RUN_ID = f"signature_context_run_{TEST_CHAPTER_AUDIO_ID}"

# 400 字：默认上限 420 时为单 chunk，收紧到 200 时拆成多 chunk，
# 两种分块策略产生不同的片段级合并签名
_LONG_TEXT = "这是一个用于验证分块策略一致性的测试句子。" * 20


@pytest.fixture()
def cleanup_test_assets(monkeypatch):
    # 保证分块上限确定性：测试期间忽略环境变量覆盖
    monkeypatch.delenv("AUDIOBOOK_RENDER_CHUNK_MAX_CHARS", raising=False)
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


def _build_long_segment():
    return {
        "type": "narration",
        "text": _LONG_TEXT,
        "speaker": "旁白",
        "voice_params": {"speaker": "voice-a"},
    }


def _build_wav_bytes() -> bytes:
    """生成可被 pydub 解码的静音 WAV（多 chunk 拼接需要真实音频字节）。"""
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(b"\x00\x00" * 800)
    return buffer.getvalue()


def test_remix_does_not_report_legacy_non_qwen_segment_as_stale(cleanup_test_assets):
    """历史数据：按默认分块策略生成的签名不得被误判过期。"""
    from app.services.audiobook import background_jobs_remix as remix
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.render_plan import build_render_plan

    segment = _build_long_segment()
    # 模拟默认分块上限的 run 固化：分块上限为 None（默认 420），单 chunk 签名
    runtime_chunks = build_render_plan(
        [SimpleNamespace(**segment)], max_chunk_chars=None
    )
    assert len(runtime_chunks) == 1
    segment["audio_cache_key"] = runtime_chunks[0].cache_key

    asset_ref = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 legacy non-qwen audio",
    )
    segment["audio_path"] = asset_ref
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps([segment], ensure_ascii=False),
    )

    missing = remix.collect_chapter_remix_missing_segments(chapter_audio)

    assert missing == []


def test_persist_records_chunk_context_for_non_qwen_run(cleanup_test_assets):
    """persist 固化 run 音频时必须记录生成分块上下文，供验签精确复现。"""
    from app.services.audiobook import background_jobs_remix as remix
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.render_plan import (
        build_render_plan,
        render_plan_to_payload,
    )
    from app.services.audiobook.temp_segment_store import save_segment_audio_map
    from app.services.audiobook.tts_model_ids import MINIMAX_SPEECH_28_HD_MODEL

    segments = [_build_long_segment()]
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )

    # 运行时 render_plan：分块上限 None（默认 420）
    runtime_chunks = build_render_plan(
        [SimpleNamespace(**segment) for segment in segments], max_chunk_chars=None
    )
    assert len(runtime_chunks) == 1
    temp_cache = save_segment_audio_map(
        run_id=TEST_RUN_ID,
        chapter_id=2,
        audio_map={chunk.index: b"ID3 chunk audio" for chunk in runtime_chunks},
        format="mp3",
    )
    temp_cache["render_plan"] = render_plan_to_payload(runtime_chunks)

    persisted = chapter_segment_assets.persist_generated_chapter_segment_audio(
        chapter_audio=chapter_audio,
        result={"temp_segment_cache": temp_cache},
        tts_model=MINIMAX_SPEECH_28_HD_MODEL,
    )

    updated_segments = json.loads(chapter_audio.script_json)
    assert set(persisted.keys()) == {0}
    assert updated_segments[0]["audio_cache_key"] == runtime_chunks[0].cache_key
    # 记录生效的分块上限（默认 420），验签可精确复现签名
    assert updated_segments[0]["audio_render_chunk_max_chars"] == 420

    chapter_audio.script_json = json.dumps(updated_segments, ensure_ascii=False)
    assert remix.collect_chapter_remix_missing_segments(chapter_audio) == []


def test_persist_records_chunk_context_for_multi_chunk_run(cleanup_test_assets, monkeypatch):
    """多 chunk 的 run 固化音频时，记录的上下文必须与运行时分块一致。

    旧 Qwen-TTS 有 360 字的独立上限，退役后所有在架模型统一按默认策略取上限；
    这里用 AUDIOBOOK_RENDER_CHUNK_MAX_CHARS 收紧上限来复现"一段拆多块"，
    验证记录口径跟着运行时解析出的分块上限，而不是跟着模型。
    """
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.render_plan import (
        build_render_plan,
        render_plan_to_payload,
    )
    from app.services.audiobook.temp_segment_store import save_segment_audio_map

    multi_chunk_limit = 200
    monkeypatch.setenv("AUDIOBOOK_RENDER_CHUNK_MAX_CHARS", str(multi_chunk_limit))
    segments = [_build_long_segment()]
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps(segments, ensure_ascii=False),
    )

    runtime_chunks = build_render_plan(
        [SimpleNamespace(**segment) for segment in segments],
        max_chunk_chars=None,
    )
    assert len(runtime_chunks) > 1
    chunk_audio = _build_wav_bytes()
    temp_cache = save_segment_audio_map(
        run_id=TEST_RUN_ID,
        chapter_id=2,
        audio_map={chunk.index: chunk_audio for chunk in runtime_chunks},
        format="wav",
    )
    temp_cache["render_plan"] = render_plan_to_payload(runtime_chunks)

    persisted = chapter_segment_assets.persist_generated_chapter_segment_audio(
        chapter_audio=chapter_audio,
        result={"temp_segment_cache": temp_cache},
        tts_model="qwen-audio-3.1-tts-flash",
    )

    updated_segments = json.loads(chapter_audio.script_json)
    assert set(persisted.keys()) == {0}
    assert (
        updated_segments[0]["audio_render_chunk_max_chars"]
        == multi_chunk_limit
    )
    assert chapter_segment_assets.segment_audio_cache_key_is_current(
        updated_segments[0]
    )


def test_recorded_context_still_detects_modified_text(cleanup_test_assets):
    """记录分块上下文后，片段文本被修改仍必须判定为过期。"""
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.render_plan import build_render_plan

    segment = _build_long_segment()
    runtime_chunks = build_render_plan(
        [SimpleNamespace(**segment)], max_chunk_chars=None
    )
    segment["audio_cache_key"] = runtime_chunks[0].cache_key
    segment["audio_render_chunk_max_chars"] = 420

    assert chapter_segment_assets.segment_audio_cache_key_is_current(segment)

    segment["text"] = _LONG_TEXT + "文本已被修改。"
    assert not chapter_segment_assets.segment_audio_cache_key_is_current(segment)


def _build_pre_semantic_sync_segment():
    return {
        "type": "narration",
        "text": "陆衍是在一阵令人作呕的腥甜气味中醒来的。",
        "speaker": "旁白",
        "emotion": "neutral",
        "instruct_emotion": "neutral",
        "performance_notes": "语速中等偏慢，声音沙哑。",
        "instruct_scene": "水牢囚禁场景",
        "instruct_role": "低沉压抑的有声书旁白",
        "instruct_identity": "故事讲述者",
        "voice_params": {
            "speaker": "voice-a",
            "tts_model": "seed-tts-2.0-expressive",
            "instruct_emotion": "neutral",
            "performance_notes": "语速中等偏慢，声音沙哑。",
            "instruct_scene": "水牢囚禁场景",
            "instruct_role": "低沉压抑的有声书旁白",
            "instruct_identity": "故事讲述者",
            "segment_speaker": "旁白",
            "segment_type": "narration",
        },
    }


def _compute_pre_semantic_sync_key(monkeypatch, segment):
    from app.services.audiobook import render_plan

    with monkeypatch.context() as context:
        context.setattr(
            render_plan,
            "_synchronize_segment_semantics",
            lambda _segment, voice_params: dict(voice_params or {}),
        )
        chunks = render_plan.build_render_plan(
            [SimpleNamespace(**segment)],
            max_chunk_chars=420,
        )
    assert len(chunks) == 1
    return chunks[0].cache_key


def test_remix_accepts_pre_semantic_sync_signature_with_recorded_context(
    cleanup_test_assets,
    monkeypatch,
):
    """签名投影升级前生成的有效持久音频不得被误报为 stale_audio。"""
    from app.services.audiobook import background_jobs_remix as remix
    from app.services.audiobook import chapter_segment_assets

    segment = _build_pre_semantic_sync_segment()
    segment["audio_cache_key"] = _compute_pre_semantic_sync_key(monkeypatch, segment)
    segment["audio_render_chunk_max_chars"] = 420
    segment["audio_path"] = chapter_segment_assets.save_persistent_segment_audio(
        chapter_audio_id=TEST_CHAPTER_AUDIO_ID,
        segment_index=0,
        audio_bytes=b"ID3 pre semantic sync audio",
    )
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps([segment], ensure_ascii=False),
    )

    assert remix.collect_chapter_remix_missing_segments(chapter_audio) == []


def test_pre_semantic_sync_signature_still_detects_modified_text(monkeypatch):
    """旧投影兼容只能接受原语义，文本变更后仍必须判定为 stale。"""
    from app.services.audiobook import chapter_segment_assets

    segment = _build_pre_semantic_sync_segment()
    segment["audio_cache_key"] = _compute_pre_semantic_sync_key(monkeypatch, segment)
    segment["audio_render_chunk_max_chars"] = 420
    segment["text"] = "片段文本已经被用户修改。"

    assert chapter_segment_assets.segment_audio_signature_status(segment) == "stale"


def test_pre_semantic_sync_signature_rejects_changed_top_level_direction(monkeypatch):
    """顶层导演语义与旧 voice_params 副本不一致时不得接受旧投影签名。"""
    from app.services.audiobook import chapter_segment_assets

    segment = _build_pre_semantic_sync_segment()
    segment["audio_cache_key"] = _compute_pre_semantic_sync_key(monkeypatch, segment)
    segment["audio_render_chunk_max_chars"] = 420
    segment["instruct_scene"] = "开阔山谷场景"

    assert chapter_segment_assets.segment_audio_signature_status(segment) == "stale"


def test_repair_migrates_recorded_pre_semantic_sync_signature(monkeypatch):
    """精确命中旧投影的持久音频应迁移到当前签名，且迁移保持幂等。"""
    from app.services.audiobook import chapter_segment_assets

    segment = _build_pre_semantic_sync_segment()
    legacy_key = _compute_pre_semantic_sync_key(monkeypatch, segment)
    segment["audio_cache_key"] = legacy_key
    segment["audio_render_chunk_max_chars"] = 420
    segment["audio_path"] = "chapter_segments_persistent_legacy.mp3"
    chapter_audio = SimpleNamespace(
        id=TEST_CHAPTER_AUDIO_ID,
        script_json=json.dumps([segment], ensure_ascii=False),
    )

    assert chapter_segment_assets.repair_legacy_segment_signatures(chapter_audio) is True
    updated = json.loads(chapter_audio.script_json)[0]
    assert updated["audio_cache_key"] != legacy_key
    assert chapter_segment_assets.segment_audio_signature_status(updated) == "current"
    assert chapter_segment_assets.repair_legacy_segment_signatures(chapter_audio) is False


def test_compute_cache_key_accepts_explicit_chunk_limit():
    """显式分块上限参数必须与 build_render_plan 同策略签名一致。"""
    from app.services.audiobook import chapter_segment_assets
    from app.services.audiobook.render_plan import build_render_plan

    segment = _build_long_segment()
    chunks_420 = build_render_plan([SimpleNamespace(**segment)], max_chunk_chars=420)
    assert len(chunks_420) == 1
    assert (
        chapter_segment_assets.compute_segment_audio_cache_key(
            segment, render_chunk_max_chars=420
        )
        == chunks_420[0].cache_key
    )


def test_workbench_whole_segment_marker_uses_one_render_chunk_for_long_text():
    """工作台固化的长片段必须按整段缓存签名复用，而不是重新拆 chunk。"""
    from app.services.audiobook.render_plan import (
        DEFAULT_RENDER_CHUNK_MAX_CHARS,
        build_render_plan,
    )

    segment = SimpleNamespace(
        type="narration",
        speaker="旁白",
        text="长片段。" * (DEFAULT_RENDER_CHUNK_MAX_CHARS + 20),
        voice_params={"speaker": "voice-a", "tts_model": "qwen-audio-3.1-tts-flash"},
        audio_render_mode="whole_segment",
    )

    chunks = build_render_plan(
        [segment],
        max_chunk_chars=DEFAULT_RENDER_CHUNK_MAX_CHARS,
    )

    assert len(chunks) == 1
    assert chunks[0].text == segment.text


def test_cache_key_uses_top_level_direction_and_ignores_stale_compiled_copy():
    from app.services.audiobook import chapter_segment_assets

    segment = {
        "type": "narration",
        "text": "痛。",
        "speaker": "旁白",
        "emotion": "neutral",
        "performance_notes": "语速缓慢",
        "instruct_scene": "水牢囚禁场景",
        "instruct_role": "低沉压抑的旁白",
        "instruct_identity": "故事讲述者",
        "voice_params": {
            "speaker": "voice-a",
            "tts_model": "seed-tts-2.0-expressive",
            "performance_notes": "客户端旧提示",
            "instruct_scene": "客户端旧场景",
            "instruct_role": "客户端旧角色",
            "instruct_identity": "客户端旧身份",
        },
    }
    clean = {
        **segment,
        "voice_params": {
            "speaker": "voice-a",
            "tts_model": "seed-tts-2.0-expressive",
        },
    }

    original_key = chapter_segment_assets.compute_segment_audio_cache_key(segment)
    assert original_key == chapter_segment_assets.compute_segment_audio_cache_key(clean)

    changed = {**clean, "instruct_scene": "开阔山谷场景"}
    assert chapter_segment_assets.compute_segment_audio_cache_key(changed) != original_key
