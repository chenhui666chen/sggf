from __future__ import annotations

import pytest


def test_media_runtime_balanced_tts_prefers_qwen3_tts_flash() -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime

    runtime = UnifiedMediaRuntime()

    spec = runtime.select_model(
        operation="synthesize_speech",
        modality="text_to_speech",
        strategy="balanced",
    )

    assert spec.id == "qwen3-tts-flash"


def test_media_runtime_quality_edit_prefers_max_variant() -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime

    runtime = UnifiedMediaRuntime()

    spec = runtime.select_model(
        operation="edit_image",
        modality="image_to_image_edit",
        strategy="quality",
    )

    assert spec.id == "qwen-image-edit-max"


def test_media_runtime_generate_image_respects_explicit_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.unified_media_runtime import UnifiedMediaResult, UnifiedMediaRuntime

    runtime = UnifiedMediaRuntime()
    captured: dict[str, object] = {}

    def fake_execute(self: UnifiedMediaRuntime, model_id: str, task: object) -> UnifiedMediaResult:
        captured["model_id"] = model_id
        captured["task"] = task
        return UnifiedMediaResult(
            success=True,
            model_id=model_id,
            outputs=["https://example.com/image.png"],
        )

    monkeypatch.setattr(UnifiedMediaRuntime, "_execute_adapter_task", fake_execute)

    result = runtime.generate_image(
        prompt="hero portrait",
        model_id="wanx-v1-turbo",
        use_fallback=False,
    )

    assert result.success is True
    assert captured["model_id"] == "wanx-v1-turbo"


def test_media_runtime_analyze_image_uses_registry_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime

    runtime = UnifiedMediaRuntime()
    captured: dict[str, object] = {}

    class FakeAdapter:
        def analyze_image(self, **kwargs):
            captured["kwargs"] = kwargs
            return type(
                "Result",
                (),
                {
                    "success": True,
                    "metadata": {"source": "fake", "result_data": {"score": 0.91}},
                    "error": None,
                    "error_code": None,
                    "cost": 0.0,
                },
            )()

    monkeypatch.setattr(runtime._registry, "get_adapter", lambda model_id: FakeAdapter())

    result = runtime.analyze_image(
        image_path="sample.png",
        model_id="qwen3-vl-plus",
    )

    assert result.success is True
    assert result.data == {"score": 0.91}
    assert result.metadata == {"source": "fake"}
    assert captured["kwargs"] == {
        "image_path": "sample.png",
        "analysis_type": "quality",
        "criteria": None,
    }


def test_media_runtime_edit_image_uses_registry_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.unified_media_runtime import UnifiedMediaResult, UnifiedMediaRuntime

    runtime = UnifiedMediaRuntime()
    captured: dict[str, object] = {}

    def fake_execute(self: UnifiedMediaRuntime, model_id: str, task: object) -> UnifiedMediaResult:
        captured["model_id"] = model_id
        captured["task"] = task
        return UnifiedMediaResult(
            success=True,
            model_id=model_id,
            outputs=["https://example.com/edited.png"],
        )

    monkeypatch.setattr(UnifiedMediaRuntime, "_execute_adapter_task", fake_execute)

    result = runtime.edit_image(
        image_path="base.png",
        edit_prompt="add moonlight",
        model_id="qwen-image-edit-plus",
        use_fallback=False,
    )

    assert result.success is True
    assert captured["model_id"] == "qwen-image-edit-plus"


def test_multimodal_registry_auto_loads_new_adapters() -> None:
    from adapters.registry import ModelRegistry

    registry = ModelRegistry()
    registry.clear()

    assert registry.get_adapter("qwen3-vl-plus") is not None
    assert registry.get_adapter("qwen-image-edit-plus") is not None
    assert registry.get_adapter("qwen-image-edit-max") is not None
    assert registry.get_adapter("wan2.6-i2v") is not None
    assert registry.get_adapter("wan2.6-r2v") is not None


def test_create_tts_engine_accepts_legacy_model_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime

    runtime = UnifiedMediaRuntime()

    class FakeEngine:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.model = kwargs["model"]

    monkeypatch.setattr(
        "core.unified_media_runtime._import_tts_components",
        lambda: (FakeEngine, type("RetryConfig", (), {})),
    )

    engine = runtime.create_tts_engine(
        model="cosyvoice-v3-plus",
        enable_cache=False,
        max_concurrent=1,
    )

    assert engine.model == "cosyvoice-v3-plus"
    assert engine.kwargs["enable_cache"] is False
    assert engine.kwargs["max_concurrent"] == 1


def test_create_tts_engine_accepts_legacy_qwen3_tts_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime

    runtime = UnifiedMediaRuntime()

    class FakeEngine:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.model = kwargs["model"]

    monkeypatch.setattr(
        "core.unified_media_runtime._import_tts_components",
        lambda: (FakeEngine, type("RetryConfig", (), {})),
    )

    engine = runtime.create_tts_engine(
        model="qwen3_tts",
        enable_cache=True,
        max_concurrent=2,
    )

    assert engine.model == "qwen3-tts-flash"


@pytest.mark.asyncio
async def test_adapter_helper_synthesize_speech_returns_binary_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers
    from core.unified_media_runtime import UnifiedMediaResult

    class FakeRuntime:
        async def synthesize_speech_result(self, **kwargs):
            return UnifiedMediaResult(
                success=True,
                model_id="qwen3-tts-flash",
                binary=b"RIFF-demo",
                data={"audio_bytes": b"RIFF-demo", "format": "wav"},
            )

    monkeypatch.setattr(adapter_helpers, "_get_media_runtime", lambda: FakeRuntime())

    result = await adapter_helpers.synthesize_speech(
        text="hello",
        voice_params={"speaker": "longxiaochun"},
        model_id="qwen3-tts-flash",
    )

    assert result.success is True
    assert result.model_id == "qwen3-tts-flash"
    assert result.binary == b"RIFF-demo"
    assert result.data["format"] == "wav"


@pytest.mark.asyncio
async def test_synthesize_speech_result_preserves_engine_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime

    runtime = UnifiedMediaRuntime()

    class FakeEngine:
        model = "qwen3-tts-flash"

        async def synthesize_with_metadata(self, text, voice_params, emotion):
            assert text == "hello"
            assert voice_params == {"speaker": "Ryan"}
            assert emotion == "neutral"
            return {
                "audio_bytes": b"RIFF-demo",
                "format": "wav",
                "tts_timestamps": [{"text": "hello", "start": 0, "end": 120}],
            }

    monkeypatch.setattr(UnifiedMediaRuntime, "create_tts_engine", lambda self, **kwargs: FakeEngine())

    result = await runtime.synthesize_speech_result(
        text="hello",
        voice_params={"speaker": "Ryan"},
        emotion="neutral",
        model_id="qwen3_tts",
    )

    assert result.success is True
    assert result.model_id == "qwen3-tts-flash"
    assert result.binary == b"RIFF-demo"
    assert result.data["format"] == "wav"
    assert result.data["tts_timestamps"] == [{"text": "hello", "start": 0, "end": 120}]
