from __future__ import annotations

import json
import pytest


def test_media_runtime_balanced_tts_prefers_qwen3_tts_instruct_flash() -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime

    runtime = UnifiedMediaRuntime()

    spec = runtime.select_model(
        operation="synthesize_speech",
        modality="text_to_speech",
        strategy="balanced",
    )

    assert spec.id == "qwen3-tts-instruct-flash"


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
        model_id="wan2.6-t2i",
        use_fallback=False,
    )

    assert result.success is True
    assert captured["model_id"] == "wan2.6-t2i"


def test_media_runtime_select_model_reroutes_incompatible_preferred_video_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime
    from schemas.task_spec import TaskSpecBuilder

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-t2v": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                    },
                    "wan2.6-t2v-fast": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    runtime = UnifiedMediaRuntime()
    task = (
        TaskSpecBuilder()
        .with_modality("text_to_video")
        .with_prompt("角色从暗处走向镜头")
        .with_dimensions(1920, 1080)
        .with_duration(10.0)
        .build()
    )

    spec = runtime.select_model(
        operation="generate_video",
        modality="text_to_video",
        preferred_model="wan2.6-t2v-fast",
        strategy="speed",
        task=task,
    )

    assert spec.id == "wan2.7-t2v"


def test_media_runtime_select_model_keeps_canonical_wan_image_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.6-t2i": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-21T00:00:00+00:00",
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    runtime = UnifiedMediaRuntime()
    spec = runtime.select_model(
        operation="generate_image",
        modality="text_to_image",
        preferred_model="wan2.6-t2i",
        strategy="balanced",
    )

    assert spec.id == "wan2.6-t2i"


def test_media_runtime_multi_image_edit_prefers_verified_multi_image_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from core.unified_media_runtime import UnifiedMediaResult, UnifiedMediaRuntime

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "qwen-image-edit-plus": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                        "capability_hints": {
                            "supports_reference_images": True,
                            "max_reference_images": 4,
                            "supports_multi_image_edit": True,
                        },
                    },
                    "qwen-image-edit-max": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                        "capability_hints": {
                            "supports_reference_images": False,
                            "max_reference_images": None,
                            "supports_multi_image_edit": False,
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    runtime = UnifiedMediaRuntime()
    captured: dict[str, object] = {}

    def fake_execute(self: UnifiedMediaRuntime, model_id: str, task: object) -> UnifiedMediaResult:
        captured["model_id"] = model_id
        return UnifiedMediaResult(
            success=True,
            model_id=model_id,
            outputs=["https://example.com/edited.png"],
        )

    monkeypatch.setattr(UnifiedMediaRuntime, "_execute_adapter_task", fake_execute)

    result = runtime.edit_image(
        image_path="base.png",
        edit_prompt="融合三张图的角色与背景",
        reference_images=["style.png", "scene.png"],
        strategy="quality",
        use_fallback=False,
    )

    assert result.success is True
    assert captured["model_id"] == "qwen-image-edit-plus"


def test_media_runtime_image_to_video_with_last_frame_prefers_frame_control_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from core.unified_media_runtime import UnifiedMediaResult, UnifiedMediaRuntime

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-t2v": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                        "capability_hints": {
                            "supports_reference_images": True,
                            "supports_last_frame": False,
                        },
                    },
                    "wan2.7-i2v": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                        "capability_hints": {
                            "supports_reference_images": True,
                            "supports_last_frame": False,
                        },
                    },
                    "wan2.7-r2v": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                        "capability_hints": {
                            "supports_reference_images": True,
                            "supports_last_frame": True,
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    runtime = UnifiedMediaRuntime()
    captured: dict[str, object] = {}

    def fake_execute(self: UnifiedMediaRuntime, model_id: str, task: object) -> UnifiedMediaResult:
        captured["model_id"] = model_id
        return UnifiedMediaResult(
            success=True,
            model_id=model_id,
            outputs=["https://example.com/video.mp4"],
        )

    monkeypatch.setattr(UnifiedMediaRuntime, "_execute_adapter_task", fake_execute)

    result = runtime.generate_video(
        prompt="角色从站立平滑过渡到坐下",
        image_path="start.png",
        last_frame="end.png",
        use_fallback=False,
    )

    assert result.success is True
    assert captured["model_id"] == "wan2.7-r2v"


def test_media_runtime_image_to_video_reroutes_incompatible_duration_preferred_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from core.unified_media_runtime import UnifiedMediaResult, UnifiedMediaRuntime

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-t2v": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                        "capability_hints": {
                            "supports_reference_images": True,
                            "max_reference_images": 1,
                        },
                    },
                    "wan2.7-i2v": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                        "capability_hints": {
                            "supports_reference_images": True,
                            "max_reference_images": 1,
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    runtime = UnifiedMediaRuntime()
    captured: dict[str, object] = {}

    def fake_execute(self: UnifiedMediaRuntime, model_id: str, task: object) -> UnifiedMediaResult:
        captured["model_id"] = model_id
        captured["task"] = task
        return UnifiedMediaResult(
            success=True,
            model_id=model_id,
            outputs=["https://example.com/video.mp4"],
        )

    monkeypatch.setattr(UnifiedMediaRuntime, "_execute_adapter_task", fake_execute)

    result = runtime.generate_video(
        prompt="让角色保持主体一致并向前推进",
        image_path="start.png",
        duration=15.0,
        model_id="wan2.7-i2v",
        strategy="balanced",
        use_fallback=False,
    )

    assert result.success is True
    assert captured["model_id"] == "wan2.7-t2v"


def test_media_runtime_image_to_video_uses_runtime_snapshot_task_constraints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from core.unified_media_runtime import UnifiedMediaResult, UnifiedMediaRuntime

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.7-i2v": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                        "capability_hints": {
                            "supports_reference_images": True,
                            "max_reference_images": 1,
                        },
                        "task_constraints": {
                            "duration_values": [3.0, 5.0, 10.0, 15.0],
                            "ratio_values": ["16:9", "9:16", "1:1"],
                            "min_width": 480,
                            "max_width": 1920,
                            "min_height": 480,
                            "max_height": 1080,
                        },
                    },
                    "wan2.7-t2v": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-22T00:00:00+00:00",
                        "capability_hints": {
                            "supports_reference_images": True,
                            "max_reference_images": 1,
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    runtime = UnifiedMediaRuntime()
    captured: dict[str, object] = {}

    def fake_execute(self: UnifiedMediaRuntime, model_id: str, task: object) -> UnifiedMediaResult:
        captured["model_id"] = model_id
        return UnifiedMediaResult(
            success=True,
            model_id=model_id,
            outputs=["https://example.com/video.mp4"],
        )

    monkeypatch.setattr(UnifiedMediaRuntime, "_execute_adapter_task", fake_execute)

    result = runtime.generate_video(
        prompt="让角色保持主体一致并完成长镜头推进",
        image_path="start.png",
        duration=15.0,
        model_id="wan2.7-i2v",
        strategy="balanced",
        use_fallback=False,
    )

    assert result.success is True
    assert captured["model_id"] == "wan2.7-i2v"


def test_media_runtime_get_model_info_exposes_catalog_routing_signal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "wan2.6-t2i": {
                        "verification_status": "verified",
                        "last_verified_at": "2026-03-21T00:00:00+00:00",
                        "capability_hints": {
                            "supports_reference_images": True,
                            "max_reference_images": 1,
                        },
                        "task_constraints": {
                            "ratio_values": ["1:1", "16:9"],
                            "min_width": 256,
                            "max_width": 2048,
                            "min_height": 256,
                            "max_height": 2048,
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    runtime = UnifiedMediaRuntime()
    monkeypatch.setattr(
        runtime._registry,
        "get_model_info",
        lambda model_id: {"id": model_id, "name": "Wan 2.6 T2I", "provider": "alibaba"},
    )

    info = runtime.get_model_info("wan2.6-t2i")

    assert info is not None
    assert info["catalog_routing"]["verification_status"] == "verified"
    assert info["catalog_routing"]["blocked"] is False
    assert info["catalog_capability_hints"]["supports_reference_images"] is True
    assert info["catalog_task_constraints"]["ratio_values"] == ["1:1", "16:9"]


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
    assert registry.get_adapter("wan2.7-i2v") is not None
    assert registry.get_adapter("wan2.7-r2v") is not None


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

    assert engine.model == "qwen3-tts-instruct-flash"


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
                model_id="qwen3-tts-instruct-flash",
                binary=b"RIFF-demo",
                data={"audio_bytes": b"RIFF-demo", "format": "wav"},
            )

    monkeypatch.setattr(adapter_helpers, "_get_media_runtime", lambda: FakeRuntime())

    result = await adapter_helpers.synthesize_speech(
        text="hello",
        voice_params={"speaker": "longxiaochun"},
        model_id="qwen3-tts-instruct-flash",
    )

    assert result.success is True
    assert result.model_id == "qwen3-tts-instruct-flash"
    assert result.binary == b"RIFF-demo"
    assert result.data["format"] == "wav"


@pytest.mark.asyncio
async def test_synthesize_speech_result_preserves_engine_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.unified_media_runtime import UnifiedMediaRuntime

    runtime = UnifiedMediaRuntime()

    class FakeEngine:
        model = "qwen3-tts-instruct-flash"

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
    assert result.model_id == "qwen3-tts-instruct-flash"
    assert result.binary == b"RIFF-demo"
    assert result.data["format"] == "wav"
    assert result.data["tts_timestamps"] == [{"text": "hello", "start": 0, "end": 120}]
