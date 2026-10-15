from __future__ import annotations

import pytest

from adapters.registry import registry


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


def test_legacy_factory_qwen_audio_31_tts_generate_uses_sync_helper(
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

    adapter = ModelAdapterFactory().get_adapter("qwen_audio_3_1_tts")
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
    assert captured["model_id"] == "qwen-audio-3.1-tts-flash"
    assert captured["voice_params"]["speaker"] == "longxiaochun"
    assert captured["voice_params"]["rate"] == 1.2
    assert captured["voice_params"]["pitch"] == 1.1
    assert captured["voice_params"]["volume"] == 40


def test_qwen_audio_31_tts_runtime_wrapper_normalizes_legacy_tts_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers
    from adapters.legacy_runtime_wrappers import QwenAudio31TTSRuntimeWrapper
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

    wrapper = QwenAudio31TTSRuntimeWrapper(
        ModelConfig(
            api_key="",
            base_url="",
            model_name="qwen_audio_3_1_tts",
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
    assert captured["model_id"] == "qwen-audio-3.1-tts-flash"
    assert captured["voice_params"]["speaker"] == "longxiaochun"
    assert captured["voice_params"]["rate"] == 1.2
    assert captured["voice_params"]["pitch"] == 1.1
    assert captured["voice_params"]["volume"] == 40


def test_normalize_model_id_returns_current_multimodal_ids() -> None:
    from core.model_resolution import normalize_model_id

    from adapters.legacy_runtime_wrappers import has_runtime_wrapper

    # Qwen3-TTS 已物理退役：core 层不再折叠旧 ID，旧写法必须原样返回并暴露成注册失败，
    # 而不是被静默改写成后继模型（与 test_model_retirement_registry 的同名约束一致）。
    assert normalize_model_id("qwen3_tts") == "qwen3_tts"
    assert normalize_model_id("kling-v3-image-generation") == "kling/kling-v3-image-generation"
    assert normalize_model_id("qwen_multiperson_fusion") == "qwen-image-edit-plus"
    assert normalize_model_id("wan_image_edit") == "qwen-image-edit-plus"
    assert normalize_model_id("minimax-m") == "minimax-m"
    assert has_runtime_wrapper("qwen_image_edit_plus") is True
    assert has_runtime_wrapper("qwen_audio_3_1_tts") is True
    assert has_runtime_wrapper("qwen3_tts") is False
