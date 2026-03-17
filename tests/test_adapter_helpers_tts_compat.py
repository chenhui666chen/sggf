from __future__ import annotations

import base64

import pytest

from adapters.registry import registry


def test_synthesize_speech_sync_returns_base64_audio_and_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers

    captured: dict[str, object] = {}

    class FakeEngine:
        model = "qwen3-tts-flash"

        async def synthesize_with_metadata(self, text, voice_params, emotion):
            captured["text"] = text
            captured["voice_params"] = voice_params
            captured["emotion"] = emotion
            return {
                "audio_bytes": b"RIFF-demo",
                "format": "wav",
                "tts_timestamps": [{"text": "hello", "start": 0, "end": 120}],
                "phoneme_timestamps": [{"phoneme": "h", "start": 0, "end": 30}],
            }

    class FakeRuntime:
        def create_tts_engine(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return FakeEngine()

    monkeypatch.setattr(adapter_helpers, "_get_media_runtime", lambda: FakeRuntime())

    result = adapter_helpers.synthesize_speech_sync(
        text="hello",
        voice_params={"speaker": "longxiaochun"},
        emotion="happy",
        model_id="qwen3_tts",
    )

    assert result.success is True
    assert result.model_id == "qwen3-tts-flash"
    assert result.binary == b"RIFF-demo"
    assert result.data["audio_data"] == base64.b64encode(b"RIFF-demo").decode("utf-8")
    assert result.data["tts_timestamps"] == [{"text": "hello", "start": 0, "end": 120}]
    assert result.data["phoneme_timestamps"] == [{"phoneme": "h", "start": 0, "end": 30}]
    assert captured["text"] == "hello"
    assert captured["voice_params"] == {"speaker": "longxiaochun"}
    assert captured["emotion"] == "happy"
    assert captured["create_kwargs"] == {"model_id": "qwen3_tts"}


def test_simple_adapter_qwen3_tts_maps_legacy_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers

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
                "message": "",
            },
        )()

    monkeypatch.setattr(adapter_helpers, "synthesize_speech_sync", fake_synthesize_speech_sync)

    adapter = adapter_helpers.SimpleAdapterFactory().get_adapter("qwen3_tts")
    result = adapter.generate(
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
    assert captured["model_id"] == "qwen3_tts"
    assert captured["voice_params"]["speaker"] == "longxiaochun"
    assert captured["voice_params"]["character_id"] == "char-1"
    assert captured["voice_params"]["rate"] == 1.2
    assert captured["voice_params"]["speed"] == 1.2
    assert captured["voice_params"]["pitch"] == 1.1
    assert captured["voice_params"]["volume"] == 40


def test_qwen3_tts_adapter_delegates_to_sync_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers
    from adapters.model_adapters import ModelConfig, Qwen3TTSAdapter

    captured: dict[str, object] = {}

    def fake_synthesize_speech_sync(**kwargs):
        captured.update(kwargs)
        return type(
            "Result",
            (),
            {
                "success": True,
                "data": {
                    "audio_data": "ZmFrZQ==",
                    "format": "mp3",
                    "tts_timestamps": [{"text": "hi", "start": 0, "end": 80}],
                },
                "error": None,
                "metadata": {"source": "runtime"},
                "cost": 1.25,
                "message": "",
                "model_id": "qwen3-tts-flash",
            },
        )()

    monkeypatch.setattr(adapter_helpers, "synthesize_speech_sync", fake_synthesize_speech_sync)

    adapter = Qwen3TTSAdapter(
        ModelConfig(
            api_key="",
            base_url="",
            model_name="qwen3_tts",
        )
    )
    result = adapter.generate(
        text="hi",
        voice_style="humorous",
        character_id="char-1",
        voice_id="longxiaochun",
        speed=1.3,
        pitch=1.1,
        volume=0.8,
    )

    assert result.success is True
    assert result.data["audio_data"] == "ZmFrZQ=="
    assert result.data["tts_timestamps"] == [{"text": "hi", "start": 0, "end": 80}]
    assert result.cost == 1.25
    assert result.metadata["source"] == "runtime"
    assert result.metadata["model"] == "qwen3-tts-flash"
    assert captured["text"] == "hi"
    assert captured["emotion"] == "happy"
    assert captured["model_id"] == "qwen3_tts"
    assert captured["voice_params"]["speaker"] == "Jennifer"
    assert captured["voice_params"]["character_id"] == "char-1"
    assert captured["voice_params"]["rate"] == 1.3
    assert captured["voice_params"]["pitch"] == 1.1
    assert captured["voice_params"]["volume"] == 40


def test_simple_adapter_factory_delegates_qwen3_vl_plus_chat_to_runtime_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers, legacy_runtime_wrappers
    from adapters.base import GenerationResult as RegistryGenerationResult

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

    monkeypatch.setattr(
        registry,
        "get_adapter",
        lambda model_id, config=None: FakeAdapter(),
    )

    adapter = adapter_helpers.SimpleAdapterFactory().get_adapter("qwen3_vl_plus")
    result = adapter.chat(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.3,
        max_tokens=128,
    )

    assert result.success is True
    assert result.data == {"content": '{"ok": true}'}
    assert result.metadata == {"source": "registry"}
    assert captured["kwargs"] == {
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.3,
        "max_tokens": 128,
        "response_format": None,
    }


def test_simple_adapter_factory_delegates_qwen_multiperson_match_scene_to_runtime_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import adapter_helpers, legacy_runtime_wrappers
    from adapters.base import GenerationResult as RegistryGenerationResult

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

    monkeypatch.setattr(
        registry,
        "get_adapter",
        lambda model_id, config=None: FakeAdapter(),
    )

    adapter = adapter_helpers.SimpleAdapterFactory().get_adapter("qwen_multiperson_fusion")
    result = adapter.match_scene(
        person_image_path="person.png",
        target_scene_path="scene.png",
        scene_prompt="place the character into the scene",
    )

    task = captured["task"]
    assert task.modality.value == "image_to_image_edit"
    assert task.prompt == "place the character into the scene"
    assert task.reference.images == ["scene.png", "person.png"]
    assert result.success is True
    assert result.data["image_url"] == "https://example.com/fused.png"


def test_legacy_bridge_qwen3_tts_prefers_runtime_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from adapters import legacy_bridge

    class FakeWrapper:
        pass

    fake_wrapper = FakeWrapper()

    monkeypatch.setattr(legacy_bridge, "create_runtime_wrapper", lambda name, config: fake_wrapper)
    monkeypatch.setattr(legacy_bridge.ModelAdapterFactory, "_instances", {})

    wrapper = legacy_bridge.ModelAdapterFactory.create(
        "qwen3_tts",
        model_name="qwen3-tts-flash",
    )

    assert wrapper is fake_wrapper
