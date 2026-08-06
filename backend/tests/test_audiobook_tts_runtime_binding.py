import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for import_root in (PROJECT_ROOT, ROOT_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

import core.unified_media_runtime as runtime_module
from core.unified_media_runtime import UnifiedMediaRuntime


def test_explicit_tts_model_does_not_use_generic_model_routing(monkeypatch) -> None:
    runtime = UnifiedMediaRuntime()

    def fail_if_routed(**_kwargs):
        raise AssertionError("显式 TTS 模型不应进入通用候选排序")

    monkeypatch.setattr(runtime, "select_model", fail_if_routed)

    engine = runtime.create_tts_engine(
        model_id="cosyvoice-v3.5-plus",
        enable_cache=False,
        request_delay=0,
    )

    assert engine.model == "cosyvoice-v3.5-plus"


def test_explicit_tts_model_fails_instead_of_switching_when_runtime_blocks_it(
    monkeypatch,
) -> None:
    runtime = UnifiedMediaRuntime()

    class BlockedRuntimeIndex:
        @staticmethod
        def get_signal(_model_id):
            return SimpleNamespace(blocked=True, reason="unit_blocked")

    monkeypatch.setattr(
        runtime_module,
        "get_model_catalog_runtime_index",
        lambda: BlockedRuntimeIndex(),
    )

    with pytest.raises(ValueError, match="blocked"):
        runtime.create_tts_engine(
            model_id="cosyvoice-v3.5-plus",
            enable_cache=False,
            request_delay=0,
        )


def test_runtime_uses_voice_params_model_when_model_id_is_omitted(monkeypatch) -> None:
    runtime = UnifiedMediaRuntime()
    captured: dict[str, object] = {}

    class FakeEngine:
        async def synthesize(self, text, voice_params, emotion):
            captured["synthesize"] = (text, dict(voice_params), emotion)
            return b"unit-audio"

    def fake_create_tts_engine(**kwargs):
        captured["model_id"] = kwargs.get("model_id")
        return FakeEngine()

    monkeypatch.setattr(runtime, "create_tts_engine", fake_create_tts_engine)

    audio = asyncio.run(
        runtime.synthesize_speech(
            text="测试。",
            voice_params={
                "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
                "resolved_tts_model": "seed-tts-2.0-expressive",
            },
            enable_cache=False,
        )
    )

    assert audio == b"unit-audio"
    assert captured["model_id"] == "seed-tts-2.0-expressive"


def test_runtime_rejects_explicit_model_conflicting_with_voice_profile() -> None:
    runtime = UnifiedMediaRuntime()

    with pytest.raises(ValueError, match="conflicts with the model-scoped voice profile"):
        asyncio.run(
            runtime.synthesize_speech(
                text="测试。",
                voice_params={
                    "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
                    "tts_model": "seed-tts-2.0-expressive",
                },
                model_id="qwen3-tts-instruct-flash",
                enable_cache=False,
            )
        )


def test_runtime_batch_uses_the_single_model_bound_to_segment_voices(monkeypatch) -> None:
    runtime = UnifiedMediaRuntime()
    captured: dict[str, object] = {}

    class FakeEngine:
        async def synthesize_batch(self, segments, **kwargs):
            captured["segments"] = list(segments)
            captured["kwargs"] = dict(kwargs)
            return [b"first", b"second"]

    def fake_create_tts_engine(**kwargs):
        captured["model_id"] = kwargs.get("model_id")
        return FakeEngine()

    monkeypatch.setattr(runtime, "create_tts_engine", fake_create_tts_engine)
    segments = [
        {
            "text": "第一段。",
            "voice_params": {
                "speaker": "voice-a",
                "tts_model": "seed-tts-2.0-expressive",
            },
        },
        {
            "text": "第二段。",
            "voice_params": {
                "speaker": "voice-b",
                "resolved_tts_model": "seed-tts-2.0-expressive",
            },
        },
    ]

    result = asyncio.run(runtime.synthesize_speech_batch(segments=segments))

    assert result == [b"first", b"second"]
    assert captured["model_id"] == "seed-tts-2.0-expressive"


def test_runtime_batch_rejects_model_scoped_voices_from_multiple_models() -> None:
    runtime = UnifiedMediaRuntime()
    segments = [
        {
            "text": "第一段。",
            "voice_params": {
                "speaker": "voice-a",
                "tts_model": "seed-tts-2.0-expressive",
            },
        },
        {
            "text": "第二段。",
            "voice_params": {
                "speaker": "voice-b",
                "tts_model": "qwen3-tts-instruct-flash",
            },
        },
    ]

    with pytest.raises(ValueError, match="multiple TTS models"):
        asyncio.run(runtime.synthesize_speech_batch(segments=segments))


def test_runtime_batch_rejects_explicit_model_conflicting_with_any_segment() -> None:
    runtime = UnifiedMediaRuntime()
    segments = [
        {
            "text": "测试。",
            "voice_params": {
                "speaker": "voice-a",
                "tts_model": "seed-tts-2.0-expressive",
            },
        }
    ]

    with pytest.raises(ValueError, match="conflicts with the model-scoped voice profile"):
        asyncio.run(
            runtime.synthesize_speech_batch(
                segments=segments,
                model_id="qwen3-tts-instruct-flash",
            )
        )
