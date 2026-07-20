from adapters.volcengine.audio_generation import DoubaoSeedAudio10Adapter
from pathlib import Path

import yaml
from unittest.mock import Mock


def test_seed_audio_maps_prompt_references_and_audio_config(monkeypatch):
    monkeypatch.setenv("VOLCENGINE_OPEN_SPEECH_API_KEY", "test-key")
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    request = adapter._map_task_to_request(
        {
            "text_prompt": "rain and footsteps",
            "references": [{"speaker": "spk_1"}],
            "audio_config": {"format": "wav", "sample_rate": 16000},
        }
    )
    assert request["model"] == "seed-audio-1.0"
    assert request["text_prompt"] == "rain and footsteps"
    assert request["references"] == [{"speaker": "spk_1"}]
    assert request["audio_config"]["format"] == "wav"


def test_seed_audio_parses_url_response():
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    result = adapter._parse_response({"url": "https://cdn.example/audio.mp3", "duration": 2.5}, None)
    assert result.success is True
    assert result.outputs == ["https://cdn.example/audio.mp3"]
    assert result.metadata["duration"] == 2.5


def test_seed_audio_reuses_configured_doubao_ark_api_key(monkeypatch):
    monkeypatch.delenv("VOLCENGINE_OPEN_SPEECH_API_KEY", raising=False)
    monkeypatch.setenv("DOUBAO_API_KEY", "configured-ark-key")
    response = Mock()
    response.json.return_value = {"url": "https://cdn.example/audio.mp3"}
    response.raise_for_status.return_value = None
    post = Mock(return_value=response)
    monkeypatch.setattr("adapters.volcengine.audio_generation.requests.post", post)

    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    adapter._call_api({"model": "seed-audio-1.0", "text_prompt": "rain"})

    assert post.call_args.kwargs["headers"]["X-Api-Key"] == "configured-ark-key"


def test_seed_audio_model_catalog_card_exposes_official_contract():
    config_path = Path(__file__).parent.parent / "config" / "models.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    models = {model["id"]: model for model in data["models"]}

    model = models["seed-audio-1.0"]
    assert model["provider"] == "volcengine"
    assert model["modality"] == ["text_to_audio"]
    assert model["api_config"]["base_url"] == "https://openspeech.bytedance.com"
    assert model["api_config"]["endpoint"] == "/api/v3/tts/create"
    assert model["api_config"]["api_key_env"] == "DOUBAO_API_KEY"
    assert model["constraints"]["verified_formats"] == ["mp3"]
    assert model["constraints"]["verified_sample_rates"] == [48000]
    assert {capability["name"] for capability in model["capabilities"]} >= {
        "text_to_audio",
        "multi_speaker_dialogue",
        "sound_effect_generation",
        "music_generation",
        "speaker_reference",
    }
    assert model["documentation_url"] == "https://docs.volcengine.com/docs/6561/2550782?lang=zh"
