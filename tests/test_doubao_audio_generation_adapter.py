import base64
from pathlib import Path
import uuid

import pytest
import requests
import yaml
from unittest.mock import Mock

from adapters.volcengine.audio_generation import DoubaoSeedAudio10Adapter


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


def test_seed_audio_supports_multilingual_model_and_subtitle_defaults():
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())

    request = adapter._map_task_to_request(
        {
            "model": "seed-audio-1.0-multilingual",
            "text_prompt": "男子用台湾口音通过电话说话。",
        }
    )

    assert request["model"] == "seed-audio-1.0-multilingual"
    assert request["audio_config"] == {
        "format": "mp3",
        "sample_rate": 48000,
        "pitch_rate": 0,
        "speech_rate": 0,
        "loudness_rate": 0,
        "enable_subtitle": True,
    }


@pytest.mark.parametrize(
    ("references", "message"),
    [
        ([{"speaker": f"speaker-{index}"} for index in range(4)], "at most 3"),
        ([{"speaker": "speaker-1", "audio_url": "https://example.com/ref.mp3"}], "exactly one"),
        ([{"role": "俘虏"}], "exactly one"),
    ],
)
def test_seed_audio_rejects_invalid_references(references, message):
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())

    with pytest.raises(ValueError, match=message):
        adapter._map_task_to_request({"text_prompt": "测试场景", "references": references})


def test_seed_audio_parses_url_base64_subtitles_and_request_metadata():
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    encoded_audio = base64.b64encode(b"ID3-test-audio").decode("ascii")

    result = adapter._parse_response(
        {
            "request_id": "request-123",
            "data": {
                "audio_url": "https://cdn.example/scene.mp3",
                "audio_data": encoded_audio,
                "duration": 12.5,
                "original_duration": 13.0,
                "subtitles": [{"text": "不要啊！", "start_time": 0, "end_time": 900}],
            },
        },
        None,
    )

    assert result.success is True
    assert result.task_id == "request-123"
    assert result.outputs == [
        "https://cdn.example/scene.mp3",
        f"data:audio/mpeg;base64,{encoded_audio}",
    ]
    assert result.metadata["request_id"] == "request-123"
    assert result.metadata["duration"] == 12.5
    assert result.metadata["original_duration"] == 13.0
    assert result.metadata["subtitles"][0]["text"] == "不要啊！"


def test_seed_audio_parses_official_audio_and_subtitle_fields():
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    encoded_audio = base64.b64encode(b"RIFF-test-audio").decode("ascii")

    result = adapter._parse_response(
        {
            "code": 0,
            "message": "success",
            "audio": encoded_audio,
            "duration": 8.0,
            "original_duration": 8.5,
            "subtitle": {
                "text": "试药。",
                "sentences": [
                    {
                        "text": "试药。",
                        "start_time": 0,
                        "end_time": 600,
                        "words": [],
                    }
                ],
            },
        },
        None,
    )

    assert result.success is True
    assert result.outputs == [f"data:audio/wav;base64,{encoded_audio}"]
    assert result.metadata["format"] == "wav"
    assert result.metadata["subtitles"]["text"] == "试药。"


def test_seed_audio_sniffs_wav_format_when_response_omits_format():
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    encoded_audio = base64.b64encode(b"RIFF\x00\x00\x00\x00WAVEfmt ").decode("ascii")

    result = adapter._parse_response({"audio": encoded_audio, "duration": 5.5}, None)

    assert result.success is True
    assert result.outputs == [f"data:audio/wav;base64,{encoded_audio}"]
    assert result.metadata["format"] == "wav"


def test_seed_audio_sniffs_mp3_frame_sync_without_id3():
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    encoded_audio = base64.b64encode(b"\xff\xfb\x90\x00mp3-frame").decode("ascii")

    result = adapter._parse_response({"audio": encoded_audio}, None)

    assert result.outputs == [f"data:audio/mpeg;base64,{encoded_audio}"]
    assert result.metadata["format"] == "mp3"


def test_seed_audio_falls_back_to_explicit_format_when_bytes_unsniffable():
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    encoded_audio = base64.b64encode(b"\x01\x02\x03\x04raw-pcm-bytes").decode("ascii")

    result = adapter._parse_response(
        {"audio": encoded_audio, "format": "pcm"}, None
    )

    assert result.outputs == [f"data:application/octet-stream;base64,{encoded_audio}"]
    assert result.metadata["format"] == "pcm"


def test_seed_audio_call_sends_trace_id_and_preserves_provider_log_id(monkeypatch):
    monkeypatch.setenv("DOUBAO_API_KEY", "configured-ark-key")
    response = Mock()
    response.json.return_value = {"url": "https://cdn.example/audio.mp3"}
    response.headers = {"X-Tt-Logid": "provider-log-123"}
    response.raise_for_status.return_value = None
    post = Mock(return_value=response)
    monkeypatch.setattr("adapters.volcengine.audio_generation.requests.post", post)
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())

    payload = adapter._call_api({"model": "seed-audio-1.0", "text_prompt": "rain"})

    trace_id = post.call_args.kwargs["headers"]["X-Api-Request-Id"]
    assert str(uuid.UUID(trace_id)) == trace_id
    assert payload["_request_id"] == "provider-log-123"


def test_seed_audio_prefers_verified_speech_api_key(monkeypatch):
    monkeypatch.setenv("VOLCENGINE_OPEN_SPEECH_API_KEY", "")
    monkeypatch.setenv("VOLCENGINE_TTS_API_KEY", "verified-speech-key")
    monkeypatch.setenv("DOUBAO_API_KEY", "ark-key")
    response = Mock()
    response.json.return_value = {"url": "https://cdn.example/audio.mp3"}
    response.headers = {}
    response.raise_for_status.return_value = None
    post = Mock(return_value=response)
    monkeypatch.setattr("adapters.volcengine.audio_generation.requests.post", post)

    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    adapter._call_api({"model": "seed-audio-1.0", "text_prompt": "rain"})

    assert post.call_args.kwargs["headers"]["X-Api-Key"] == "verified-speech-key"


def test_seed_audio_classifies_readable_text_validation_as_non_retryable(monkeypatch):
    monkeypatch.setenv("DOUBAO_API_KEY", "configured-key")
    response = Mock()
    response.status_code = 500
    response.headers = {"X-Tt-Logid": "provider-log-validation"}
    response.json.return_value = {
        "code": "40402002",
        "message": "TTSInvalidText:ReadableTextRatioTooLow",
    }
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    monkeypatch.setattr(
        "adapters.volcengine.audio_generation.requests.post",
        Mock(return_value=response),
    )

    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    result = adapter.generate(prompt="invalid provider text")

    assert result.success is False
    assert result.error_code == "invalid_request"
    assert result.trace["retryable"] is False
    assert result.trace["provider_code"] == "40402002"


def test_seed_audio_generate_marks_validation_errors_non_retryable():
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())

    result = adapter.generate(prompt="测试", references=[{"speaker": "a", "audio_data": "b"}])

    assert result.success is False
    assert result.error_code == "invalid_request"
    assert result.trace["retryable"] is False


def test_seed_audio_generate_marks_timeout_retryable(monkeypatch):
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())

    def raise_timeout(_request):
        raise requests.Timeout("provider timed out")

    monkeypatch.setattr(adapter, "_call_api", raise_timeout)
    result = adapter.generate(prompt="测试")

    assert result.success is False
    assert result.error_code == "provider_timeout"
    assert result.trace["retryable"] is True


def test_seed_audio_generate_preserves_retryable_http_error_metadata(monkeypatch):
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    response = Mock()
    response.status_code = 429
    response.headers = {"Retry-After": "7", "X-Request-Id": "request-429"}
    response.json.return_value = {"code": "TooManyRequests", "message": "rate limited"}

    def raise_rate_limit(_request):
        raise requests.HTTPError("429 Too Many Requests", response=response)

    monkeypatch.setattr(adapter, "_call_api", raise_rate_limit)
    result = adapter.generate(prompt="测试")

    assert result.success is False
    assert result.task_id == "request-429"
    assert result.error_code == "rate_limited"
    assert result.retry_after == 7
    assert result.trace == {
        "retryable": True,
        "status_code": 429,
        "provider_code": "TooManyRequests",
    }


def test_seed_audio_parses_url_response():
    adapter = DoubaoSeedAudio10Adapter(DoubaoSeedAudio10Adapter.get_model_spec())
    result = adapter._parse_response({"url": "https://cdn.example/audio.mp3", "duration": 2.5}, None)
    assert result.success is True
    assert result.outputs == ["https://cdn.example/audio.mp3"]
    assert result.metadata["duration"] == 2.5


def test_seed_audio_reuses_configured_doubao_ark_api_key(monkeypatch):
    for env_name in (
        "VOLCENGINE_OPEN_SPEECH_API_KEY",
        "VOLCENGINE_TTS_API_KEY",
        "DOUBAO_TTS_API_KEY",
        "SEED_TTS_API_KEY",
    ):
        monkeypatch.delenv(env_name, raising=False)
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
    assert model["constraints"]["max_duration_seconds"] == 120
    assert model["constraints"]["max_prompt_chars"] == 3000
    assert model["constraints"]["max_audio_references"] == 3
    assert model["constraints"]["max_reference_duration_seconds"] == 30
    assert model["constraints"]["max_reference_size_mb"] == 10
    assert model["constraints"]["supported_formats"] == ["wav", "mp3", "pcm", "ogg_opus"]
    assert model["constraints"]["supported_sample_rates"] == [8000, 16000, 24000, 32000, 44100, 48000]
    assert model["api_config"]["request_format"]["audio_config"]["enable_subtitle"] is True
    assert set(model["api_config"]["response_format"]) >= {
        "audio",
        "url",
        "duration",
        "original_duration",
        "subtitle",
    }
    assert model["api_config"]["response_headers"]["request_id"] == "X-Tt-Logid"
    assert {capability["name"] for capability in model["capabilities"]} >= {
        "text_to_audio",
        "multi_speaker_dialogue",
        "sound_effect_generation",
        "music_generation",
        "speaker_reference",
    }
    assert model["documentation_url"] == "https://docs.volcengine.com/docs/6561/2550782?lang=zh"
