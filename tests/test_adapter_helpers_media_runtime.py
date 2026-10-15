from __future__ import annotations

import pytest


def test_generate_video_helper_forwards_model_id_and_extra_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers
    from core.unified_media_runtime import UnifiedMediaResult

    captured: dict[str, object] = {}

    class FakeRuntime:
        def generate_video(self, **kwargs):
            captured.update(kwargs)
            return UnifiedMediaResult(
                success=True,
                model_id="wan3.0-video",
                outputs=["https://example.com/clip.mp4"],
                metadata={"source": "runtime"},
            )

    monkeypatch.setattr(adapter_helpers, "_get_media_runtime", lambda: FakeRuntime())

    result = adapter_helpers.generate_video(
        prompt="camera push-in",
        duration=5.0,
        width=1280,
        height=720,
        image_path="head.png",
        model_id="wan3.0-video",
        use_fallback=False,
        fps=24,
        motion_bucket_id=127,
    )

    assert result.success is True
    assert result.model_id == "wan3.0-video"
    assert result.data["video_url"] == "https://example.com/clip.mp4"
    assert captured == {
        "prompt": "camera push-in",
        "duration": 5.0,
        "width": 1280,
        "height": 720,
        "negative_prompt": "",
        "seed": None,
        "style": None,
        "image_path": "head.png",
        "video_path": None,
        "model_id": "wan3.0-video",
        "use_fallback": False,
        "fps": 24,
        "motion_bucket_id": 127,
    }


def test_model_supports_capability_normalizes_format_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers

    captured: dict[str, object] = {}

    class FakeRuntime:
        def get_model_info(self, model_id: str):
            captured["model_id"] = model_id
            return {
                "id": model_id,
                "capabilities": [
                    {"name": "image_edit", "support_level": "native"},
                    {"name": "multi_image", "support_level": "native"},
                ],
            }

    monkeypatch.setattr(adapter_helpers, "_get_media_runtime", lambda: FakeRuntime())

    assert adapter_helpers.model_supports_capability("qwen_image_edit_plus", "multi_image") is True
    assert adapter_helpers.model_supports_capability("qwen_image_edit_plus", "video_understanding") is False
    assert captured["model_id"] == "qwen-image-edit-plus"


def test_chat_messages_calls_registry_adapter_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers
    from adapters.base import GenerationResult as RegistryGenerationResult
    from adapters.registry import registry

    captured: dict[str, object] = {}

    class FakeAdapter:
        def chat(self, **kwargs):
            captured["kwargs"] = kwargs
            return RegistryGenerationResult(
                success=True,
                task_id="chat-test",
                model_id="qwen-plus",
                metadata={"result_data": {"content": '{"ok": true}'}, "source": "registry"},
            )

    monkeypatch.setattr(registry, "get_adapter", lambda model_id, config=None: FakeAdapter())

    result = adapter_helpers.chat_messages(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.1,
        max_tokens=256,
        response_format={"type": "json_object"},
        model_id="qwen-plus",
    )

    assert result.success is True
    assert result.model_id == "qwen-plus"
    assert result.metadata["source"] == "registry"
    assert captured["kwargs"] == {
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.1,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
    }


def test_create_runtime_client_delegates_to_runtime_wrapper_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers

    sentinel = object()
    captured: dict[str, object] = {}

    def fake_create(name):
        captured["name"] = name
        return sentinel

    monkeypatch.setattr(adapter_helpers, "_create_legacy_wrapper", fake_create)

    client = adapter_helpers.create_runtime_client("qwen-image-3.0")

    assert client is sentinel
    assert captured["name"] == "qwen-image-3.0"


def test_match_scene_helper_routes_to_unified_edit_image_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers
    from core.unified_media_runtime import UnifiedMediaResult

    captured: dict[str, object] = {}

    class FakeRuntime:
        def edit_image(self, **kwargs):
            captured.update(kwargs)
            return UnifiedMediaResult(
                success=True,
                model_id="qwen-image-edit-plus",
                outputs=["https://example.com/fused.png"],
                metadata={"source": "runtime"},
            )

    monkeypatch.setattr(adapter_helpers, "_get_media_runtime", lambda: FakeRuntime())

    result = adapter_helpers.match_scene(
        person_image_path="person.png",
        target_scene_path="scene.png",
        scene_prompt="place the character into the scene",
        model_id="qwen_multiperson_fusion",
        use_fallback=False,
    )

    assert result.success is True
    assert result.model_id == "qwen-image-edit-plus"
    assert result.data["image_url"] == "https://example.com/fused.png"
    assert captured == {
        "image_path": "scene.png",
        "edit_prompt": "place the character into the scene",
        "strength": 0.8,
        "width": None,
        "height": None,
        "reference_images": ["person.png"],
        "model_id": "qwen_multiperson_fusion",
        "use_fallback": False,
        "guidance_scale": 7.5,
        "seed": None,
    }
