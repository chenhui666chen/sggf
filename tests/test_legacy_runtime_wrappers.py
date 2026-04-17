from __future__ import annotations

import pytest

from adapters.registry import registry


def test_legacy_factory_qwen3_vl_plus_chat_uses_registry_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import legacy_runtime_wrappers
    from adapters.base import GenerationResult as RegistryGenerationResult
    from adapters.model_adapters import ModelAdapterFactory

    captured: dict[str, object] = {}

    class FakeAdapter:
        def chat(self, **kwargs):
            captured["kwargs"] = kwargs
            return RegistryGenerationResult(
                success=True,
                task_id="legacy",
                model_id="qwen3-vl-plus",
                metadata={
                    "source": "registry",
                    "result_data": {"content": '{"ok": true}'},
                },
            )

    def fake_get_adapter(model_id: str, config=None):
        captured["model_id"] = model_id
        captured["config"] = config
        return FakeAdapter()

    monkeypatch.setattr(registry, "get_adapter", fake_get_adapter)

    adapter = ModelAdapterFactory().get_adapter("qwen3_vl_plus")
    result = adapter.chat(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.3,
        max_tokens=128,
    )

    assert captured["model_id"] == "qwen3-vl-plus"
    assert result.success is True
    assert result.data == {"content": '{"ok": true}'}
    assert result.metadata == {"source": "registry"}
    assert captured["kwargs"] == {
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.3,
        "max_tokens": 128,
        "response_format": None,
    }


def test_legacy_factory_qwen_image_edit_plus_generate_routes_to_registry_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import legacy_runtime_wrappers
    from adapters.base import GenerationResult as RegistryGenerationResult
    from adapters.model_adapters import ModelAdapterFactory

    captured: dict[str, object] = {}

    class FakeAdapter:
        def generate(self, task):
            captured["task"] = task
            return RegistryGenerationResult(
                success=True,
                task_id=task.task_id,
                model_id="qwen-image-edit-plus",
                outputs=["https://example.com/edited.png"],
                metadata={"source": "registry"},
            )

    def fake_get_adapter(model_id: str, config=None):
        captured["model_id"] = model_id
        captured["config"] = config
        return FakeAdapter()

    monkeypatch.setattr(registry, "get_adapter", fake_get_adapter)

    adapter = ModelAdapterFactory().get_adapter("qwen_image_edit_plus")
    result = adapter.generate(
        image_path="base.png",
        edit_prompt="add moonlight",
        strength=0.65,
        guidance_scale=7.5,
        seed=123,
        image_paths=["ref-1.png", "ref-2.png"],
    )

    task = captured["task"]
    assert captured["model_id"] == "qwen-image-edit-plus"
    assert task.modality.value == "image_to_image_edit"
    assert task.prompt == "add moonlight"
    assert task.reference.images == ["base.png", "ref-1.png", "ref-2.png"]
    assert task.seed == 123
    assert task.extra["strength"] == 0.65
    assert task.extra["guidance_scale"] == 7.5
    assert result.success is True
    assert result.data["image_url"] == "https://example.com/edited.png"
    assert result.metadata == {"source": "registry"}


def test_factory_wan2_6_t2i_uses_registry_image_generation_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import legacy_runtime_wrappers
    from adapters.base import GenerationResult as RegistryGenerationResult
    from adapters.model_adapters import ModelAdapterFactory

    captured: dict[str, object] = {}

    class FakeAdapter:
        def generate(self, task):
            captured["task"] = task
            return RegistryGenerationResult(
                success=True,
                task_id=task.task_id,
                model_id="wan2.6-t2i",
                outputs=["https://example.com/generated.png"],
                metadata={"source": "registry"},
            )

    def fake_get_adapter(model_id: str, config=None):
        captured["model_id"] = model_id
        captured["config"] = config
        return FakeAdapter()

    monkeypatch.setattr(registry, "get_adapter", fake_get_adapter)

    adapter = ModelAdapterFactory().get_adapter("wan2.6-t2i")
    result = adapter.generate(
        prompt="hero portrait",
        negative_prompt="blurry",
        width=768,
        height=1024,
        num_inference_steps=40,
        guidance_scale=6.5,
        seed=11,
    )

    task = captured["task"]
    assert captured["model_id"] == "wan2.6-t2i"
    assert task.modality.value == "text_to_image"
    assert task.prompt == "hero portrait"
    assert task.negative_prompt == "blurry"
    assert task.width == 768
    assert task.height == 1024
    assert task.seed == 11
    assert task.extra["num_inference_steps"] == 40
    assert task.extra["guidance_scale"] == 6.5
    assert result.success is True
    assert result.data["image_url"] == "https://example.com/generated.png"
    assert result.metadata == {"source": "registry"}


def test_legacy_factory_wan_image_edit_preserves_old_adapter_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import legacy_runtime_wrappers
    from adapters.base import GenerationResult as RegistryGenerationResult
    from adapters.model_adapters import ModelAdapterFactory

    captured: dict[str, object] = {}

    class FakeAdapter:
        def generate(self, task):
            captured["task"] = task
            return RegistryGenerationResult(
                success=True,
                task_id=task.task_id,
                model_id="qwen-image-edit-plus",
                outputs=["https://example.com/wan-edit.png"],
            )

    def fake_get_adapter(model_id: str, config=None):
        captured["model_id"] = model_id
        return FakeAdapter()

    monkeypatch.setattr(registry, "get_adapter", fake_get_adapter)

    adapter = ModelAdapterFactory().get_adapter("wan_image_edit")
    result = adapter.generate(
        image_path="base.png",
        edit_prompt="clean background",
        image_paths=["ignored-ref.png"],
    )

    task = captured["task"]
    assert adapter.supports_multi_image is False
    assert adapter.__class__.__name__ == "WanImageEditRuntimeWrapper"
    assert captured["model_id"] == "qwen-image-edit-plus"
    assert task.reference.images == ["base.png"]
    assert result.data["image_url"] == "https://example.com/wan-edit.png"


def test_factory_wan2_7_i2v_routes_to_unified_generate_video_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers
    from adapters.model_adapters import ModelAdapterFactory

    captured: dict[str, object] = {}

    def fake_generate_video(**kwargs):
        captured.update(kwargs)
        return type(
            "Result",
            (),
            {
                "success": True,
                "data": {"video_url": "https://example.com/clip.mp4"},
                "error": None,
                "metadata": {"source": "runtime"},
                "cost": 0.0,
            },
        )()

    monkeypatch.setattr(adapter_helpers, "generate_video", fake_generate_video)

    adapter = ModelAdapterFactory().get_adapter("wan2.7-i2v")
    result = adapter.generate(
        image_path="head.png",
        prompt="animate the portrait",
        duration=5,
        fps=24,
        motion_bucket_id=96,
        seed=7,
        character_references=[{"name": "hero"}],
    )

    assert captured == {
        "prompt": "animate the portrait",
        "duration": 5.0,
        "image_path": "head.png",
        "model_id": "wan2.7-i2v",
        "use_fallback": False,
        "fps": 24,
        "motion_bucket_id": 96,
        "seed": 7,
        "character_references": [{"name": "hero"}],
    }
    assert result.success is True
    assert result.data["video_url"] == "https://example.com/clip.mp4"
    assert result.metadata == {"source": "runtime"}


def test_factory_wan2_7_t2v_uses_registry_video_generation_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import legacy_runtime_wrappers
    from adapters.base import GenerationResult as RegistryGenerationResult
    from adapters.model_adapters import ModelAdapterFactory

    captured: dict[str, object] = {}

    class FakeAdapter:
        def generate(self, task):
            captured["task"] = task
            return RegistryGenerationResult(
                success=True,
                task_id=task.task_id,
                model_id="wan2.7-t2v",
                outputs=["https://example.com/generated.mp4"],
                metadata={"source": "registry"},
            )

    def fake_get_adapter(model_id: str, config=None):
        captured["model_id"] = model_id
        captured["config"] = config
        return FakeAdapter()

    monkeypatch.setattr(registry, "get_adapter", fake_get_adapter)

    adapter = ModelAdapterFactory().get_adapter("wan2.7-t2v")
    result = adapter.generate(
        prompt="storm over the sea",
        negative_prompt="low quality",
        width=1280,
        height=720,
        duration=5,
        fps=24,
        num_inference_steps=28,
        guidance_scale=7.0,
        seed=17,
    )

    task = captured["task"]
    assert captured["model_id"] == "wan2.7-t2v"
    assert task.modality.value == "text_to_video"
    assert task.prompt == "storm over the sea"
    assert task.negative_prompt == "low quality"
    assert task.width == 1280
    assert task.height == 720
    assert task.duration == 5.0
    assert task.seed == 17
    assert task.extra["fps"] == 24
    assert task.extra["num_inference_steps"] == 28
    assert task.extra["guidance_scale"] == 7.0
    assert result.success is True
    assert result.data["video_url"] == "https://example.com/generated.mp4"
    assert result.metadata == {"source": "registry"}


def test_legacy_factory_qwen_multiperson_fusion_match_scene_uses_registry_edit_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import legacy_runtime_wrappers
    from adapters.base import GenerationResult as RegistryGenerationResult
    from adapters.model_adapters import ModelAdapterFactory

    captured: dict[str, object] = {}

    class FakeAdapter:
        def generate(self, task):
            captured["task"] = task
            return RegistryGenerationResult(
                success=True,
                task_id=task.task_id,
                model_id="qwen-image-edit-plus",
                outputs=["https://example.com/fused.png"],
            )

    def fake_get_adapter(model_id: str, config=None):
        captured["model_id"] = model_id
        return FakeAdapter()

    monkeypatch.setattr(registry, "get_adapter", fake_get_adapter)

    adapter = ModelAdapterFactory().get_adapter("qwen_multiperson_fusion")
    result = adapter.match_scene(
        person_image_path="person.png",
        target_scene_path="scene.png",
        scene_prompt="place the character into the scene",
    )

    task = captured["task"]
    assert captured["model_id"] == "qwen-image-edit-plus"
    assert task.modality.value == "image_to_image_edit"
    assert task.prompt == "place the character into the scene"
    assert task.reference.images == ["scene.png", "person.png"]
    assert result.success is True
    assert result.data["image_url"] == "https://example.com/fused.png"


def test_factory_wan2_7_r2v_routes_to_unified_generate_video_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers
    from adapters.model_adapters import ModelAdapterFactory

    captured: dict[str, object] = {}

    def fake_generate_video(**kwargs):
        captured.update(kwargs)
        return type(
            "Result",
            (),
            {
                "success": True,
                "data": {"video_url": "https://example.com/r2v.mp4"},
                "error": None,
                "metadata": {"source": "runtime"},
                "cost": 0.0,
            },
        )()

    monkeypatch.setattr(adapter_helpers, "generate_video", fake_generate_video)

    adapter = ModelAdapterFactory().get_adapter("wan2.7-r2v")
    result = adapter.generate(
        reference_video_path="scene.mp4",
        prompt="keep the motion style",
        duration=4,
        fps=24,
        seed=9,
    )

    assert captured == {
        "prompt": "keep the motion style",
        "duration": 4.0,
        "video_path": "scene.mp4",
        "model_id": "wan2.7-r2v",
        "use_fallback": False,
        "fps": 24,
        "seed": 9,
    }
    assert result.success is True
    assert result.data["video_url"] == "https://example.com/r2v.mp4"
    assert result.metadata == {"source": "runtime"}


def test_legacy_factory_qwen3_tts_generate_uses_sync_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers
    from adapters.model_adapters import ModelAdapterFactory

    captured: dict[str, object] = {}

    def fake_synthesize_speech_sync(**kwargs):
        captured.update(kwargs)
        return type(
            "Result",
            (),
            {
                "success": True,
                "data": {"audio_data": "ZmFrZQ==", "format": "mp3"},
                "error": None,
                "metadata": {"source": "runtime"},
                "cost": 0.0,
            },
        )()

    monkeypatch.setattr(adapter_helpers, "synthesize_speech_sync", fake_synthesize_speech_sync)

    adapter = ModelAdapterFactory().get_adapter("qwen3_tts")
    result = adapter.generate(
        text="hello",
        voice_style="natural",
        character_id="char-1",
        voice_id="longxiaochun",
        speed=1.2,
        pitch=1.1,
        volume=0.8,
    )

    assert result.success is True
    assert result.data["audio_data"] == "ZmFrZQ=="
    assert result.metadata == {"source": "runtime"}
    assert captured["text"] == "hello"
    assert captured["emotion"] == "neutral"
    assert captured["model_id"] == "qwen3-tts-flash"
    assert captured["voice_params"]["speaker"] == "longxiaochun"
    assert captured["voice_params"]["rate"] == 1.2
    assert captured["voice_params"]["pitch"] == 1.1
    assert captured["voice_params"]["volume"] == 40


def test_qwen3_tts_runtime_wrapper_normalizes_legacy_tts_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers
    from adapters.legacy_runtime_wrappers import Qwen3TTSRuntimeWrapper
    from adapters.model_adapters import ModelConfig

    captured: dict[str, object] = {}

    def fake_synthesize_speech_sync(**kwargs):
        captured.update(kwargs)
        return type(
            "Result",
            (),
            {
                "success": True,
                "data": {"audio_data": "ZmFrZQ==", "format": "mp3"},
                "error": None,
                "metadata": {"source": "runtime"},
                "cost": 0.0,
            },
        )()

    monkeypatch.setattr(adapter_helpers, "synthesize_speech_sync", fake_synthesize_speech_sync)

    wrapper = Qwen3TTSRuntimeWrapper(
        ModelConfig(
            api_key="",
            base_url="",
            model_name="qwen3_tts",
        )
    )
    result = wrapper.generate(
        text="hello",
        voice_style="humorous",
        character_id="char-1",
        voice_id="longxiaochun",
        speed=1.2,
        pitch=1.1,
        volume=0.8,
    )

    assert result.success is True
    assert result.data["audio_data"] == "ZmFrZQ=="
    assert captured["text"] == "hello"
    assert captured["emotion"] == "happy"
    assert captured["model_id"] == "qwen3-tts-flash"
    assert captured["voice_params"]["speaker"] == "longxiaochun"
    assert captured["voice_params"]["rate"] == 1.2
    assert captured["voice_params"]["pitch"] == 1.1
    assert captured["voice_params"]["volume"] == 40


def test_normalize_model_id_returns_current_multimodal_ids() -> None:
    from core.model_resolution import normalize_model_id

    from adapters.legacy_runtime_wrappers import has_runtime_wrapper

    assert normalize_model_id("qwen3_vl_plus") == "qwen3-vl-plus"
    assert normalize_model_id("qwen3_tts") == "qwen3-tts-flash"
    assert normalize_model_id("wan2.6-t2i") == "wan2.6-t2i"
    assert normalize_model_id("wan2.7-t2v") == "wan2.7-t2v"
    assert normalize_model_id("wan2.7-i2v") == "wan2.7-i2v"
    assert normalize_model_id("qwen_multiperson_fusion") == "qwen-image-edit-plus"
    assert normalize_model_id("wan_image_edit") == "qwen-image-edit-plus"
    assert has_runtime_wrapper("wan2.6-t2i") is True
    assert has_runtime_wrapper("wan2.7-t2v") is True
