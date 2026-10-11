# -*- coding: utf-8 -*-
"""Qwen-Audio 3.1 TTS Next（Audiogen）适配器契约测试。

断言的合法值区间与错误码全部来自 2026-10-10 真实调用（见 config/models.yaml 同 ID 档案的
constraints.verified_parameters），不是照抄文档：文档只说“不支持 Opus”，实测是
400 InvalidParameter / "Unsupported format: opus"；文档没写的 voice 字段实测被忽略。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import yaml

from adapters.dashscope.audio_generation import (
    QWEN_AUDIO_31_TTS_NEXT_MODEL,
    QwenAudio31TtsNextAdapter,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _adapter() -> QwenAudio31TtsNextAdapter:
    return QwenAudio31TtsNextAdapter(QwenAudio31TtsNextAdapter.get_model_spec())


def test_next_maps_prompt_and_keeps_only_supported_audio_params():
    request = _adapter()._map_task_to_request(
        {
            "text_prompt": "雨夜走廊，远处传来三声缓慢的木门吱呀。",
            # 路由层复用豆包 Seed Audio 的 audio_config，未知字段必须被丢弃而不是发给上游。
            "audio_config": {
                "format": "mp3",
                "sample_rate": 48000,
                "pitch_rate": 0,
                "speech_rate": 0,
                "loudness_rate": 0,
                "enable_subtitle": True,
            },
        }
    )

    assert request["model"] == QWEN_AUDIO_31_TTS_NEXT_MODEL
    assert request["input"]["text_prompt"] == "雨夜走廊，远处传来三声缓慢的木门吱呀。"
    assert request["input"]["format"] == "mp3"
    assert request["input"]["sample_rate"] == 48000
    assert "pitch_rate" not in request["input"]
    assert "enable_subtitle" not in request["input"]
    assert set(request["_dropped_params"]) == {"pitch_rate", "speech_rate", "loudness_rate", "enable_subtitle"}


def test_next_applies_official_defaults_when_audio_config_absent():
    request = _adapter()._map_task_to_request({"prompt": "一声清脆的玻璃碎裂。"})

    assert request["input"] == {
        "text_prompt": "一声清脆的玻璃碎裂。",
        "format": "wav",
        "sample_rate": 48000,
        "channels": 2,
    }


def test_next_audio_config_cannot_override_prompt_or_references():
    request = _adapter()._map_task_to_request(
        {
            "text_prompt": "真实提示词",
            "audio_config": {"text_prompt": "越权提示词", "references": [{"audio_url": "https://x/a.wav"}]},
        }
    )

    assert request["input"]["text_prompt"] == "真实提示词"
    assert "references" not in request["input"]
    assert set(request["_dropped_params"]) == {"text_prompt", "references"}


@pytest.mark.parametrize(
    ("audio_config", "message"),
    [
        ({"format": "opus"}, "unsupported format"),
        ({"sample_rate": 22050}, "unsupported sample_rate"),
        ({"channels": 3}, "channels must be either 1 or 2"),
        ({"rate": 2.5}, r"rate must be within \[0.5, 2.0\]"),
        ({"volume": 101}, r"volume must be within \[0, 100\]"),
    ],
)
def test_next_rejects_params_the_server_would_reject(audio_config, message):
    with pytest.raises(ValueError, match=message):
        _adapter()._map_task_to_request({"text_prompt": "短音效", "audio_config": audio_config})


def test_next_rejects_prompt_over_3000_chars():
    with pytest.raises(ValueError, match="must not exceed 3000 characters"):
        _adapter()._map_task_to_request({"text_prompt": "呀" * 3001})


def test_next_requires_prompt():
    with pytest.raises(ValueError, match="text_prompt is required"):
        _adapter()._map_task_to_request({"audio_config": {"format": "wav"}})


def test_next_accepts_url_and_base64_references():
    references = [
        {"audio_url": "https://example.com/voice1.wav"},
        {"audio_data": "data:audio/wav;base64,AAAA"},
    ]
    request = _adapter()._map_task_to_request(
        {"text_prompt": "@voice1 与 @voice2 对话", "references": references}
    )

    assert request["input"]["references"] == references


def test_next_rejects_speaker_voice_ids():
    """豆包用 speaker 音色 ID，本模型只认参考音频；混用必须报错，不能静默丢参。"""
    with pytest.raises(ValueError, match="does not accept speaker"):
        _adapter()._map_task_to_request(
            {"text_prompt": "双人对话", "references": [{"speaker": "spk_1"}]}
        )


@pytest.mark.parametrize(
    ("references", "message"),
    [
        ([{"audio_url": f"https://example.com/{index}.wav"} for index in range(4)], "must not exceed 3 items"),
        ([{"audio_url": "https://example.com/a.wav", "audio_data": "data:audio/wav;base64,AAAA"}], "exactly one"),
        ([{"role": "旁白"}], "exactly one"),
        ([{"audio_url": "file:///local/a.wav"}], r"must be an HTTP\(S\) URL"),
    ],
)
def test_next_rejects_invalid_references(references, message):
    with pytest.raises(ValueError, match=message):
        _adapter()._map_task_to_request({"text_prompt": "测试", "references": references})


def test_next_parses_audio_url_duration_and_token_usage():
    result = _adapter()._parse_response(
        {
            "request_id": "63c3083e-1d44-9f24-89ec-0c205fab222b",
            "output": {
                "finish_reason": "stop",
                "audio": {
                    "data": "",
                    "url": "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/prod/a.wav",
                    "id": "audio_63c3083e",
                    "expires_at": 1791658382,
                    "duration": 4.0,
                },
            },
            "usage": {"duration": 4, "input_tokens": 231, "output_tokens": 800, "total_tokens": 1031},
        },
        None,
    )

    assert result.success is True
    assert result.task_id == "63c3083e-1d44-9f24-89ec-0c205fab222b"
    assert result.outputs == ["https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/prod/a.wav"]
    # 结算链路按 metadata.duration 取实际时长，必须转成 float 而不是原样透传
    assert result.metadata["duration"] == 4.0
    assert result.metadata["usage"]["output_tokens"] == 800
    assert result.metadata["audio_id"] == "audio_63c3083e"
    assert result.metadata["finish_reason"] == "stop"


def test_next_wraps_inline_audio_data_as_data_uri():
    result = _adapter()._parse_response(
        {"output": {"audio": {"data": "UklGRiQ=", "format": "wav", "duration": 1.25}}},
        None,
    )

    assert result.success is True
    assert result.outputs == ["data:audio/wav;base64,UklGRiQ="]
    assert result.metadata["duration"] == 1.25


def test_next_flags_missing_audio_as_invalid_response():
    result = _adapter()._parse_response({"request_id": "r-1", "output": {"finish_reason": "stop"}}, None)

    assert result.success is False
    assert result.error_code == "invalid_response"
    assert result.task_id == "r-1"


def test_next_call_uses_bearer_auth_and_never_sends_internal_keys(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    response = Mock()
    response.json.return_value = {"output": {"audio": {"url": "https://cdn.example/a.wav", "duration": 3.0}}}
    response.raise_for_status.return_value = None
    post = Mock(return_value=response)
    monkeypatch.setattr("adapters.dashscope.audio_generation.requests.post", post)

    _adapter()._call_api(
        {"model": QWEN_AUDIO_31_TTS_NEXT_MODEL, "input": {"text_prompt": "a"}, "_dropped_params": ["pitch_rate"]}
    )

    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"
    sent_payload = post.call_args.kwargs["json"]
    assert "_dropped_params" not in sent_payload
    assert "text_prompt" in sent_payload["input"]


def test_next_generate_records_dropped_params_on_success(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    response = Mock()
    response.json.return_value = {"output": {"audio": {"url": "https://cdn.example/a.wav", "duration": 2.0}}}
    response.raise_for_status.return_value = None
    monkeypatch.setattr("adapters.dashscope.audio_generation.requests.post", Mock(return_value=response))

    result = _adapter().generate(
        prompt="两声敲门。",
        audio_config={"format": "mp3", "enable_subtitle": True},
        watermark={"enabled": True},
    )

    assert result.success is True
    assert set(result.metadata["dropped_params"]) == {"enable_subtitle", "watermark"}


def test_next_maps_provider_400_to_non_retryable_invalid_request(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    response = Mock()
    response.status_code = 400
    response.json.return_value = {
        "request_id": "req-400",
        "code": "InvalidParameter",
        "message": "channels must be either 1 or 2.",
    }
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    monkeypatch.setattr(
        "adapters.dashscope.audio_generation.requests.post", Mock(return_value=response)
    )

    # 本地校验放行的请求仍可能被服务端打回（例如 channels 之外的档位限制），
    # 这里用完全合法的入参模拟上游 400，验证错误码归类。
    result = _adapter().generate(prompt="测试", audio_config={"channels": 2})

    assert result.success is False
    assert result.error_code == "invalid_request"
    assert result.trace["retryable"] is False
    assert result.trace["provider_code"] == "InvalidParameter"
    assert result.trace["status_code"] == 400
    assert "channels must be either 1 or 2" in result.error


def test_next_maps_429_to_retryable_rate_limit(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    response = Mock()
    response.status_code = 429
    response.json.return_value = {"code": "Throttling.RateQuota", "message": "Too many requests."}
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    monkeypatch.setattr(
        "adapters.dashscope.audio_generation.requests.post", Mock(return_value=response)
    )

    result = _adapter().generate(prompt="测试")

    assert result.error_code == "rate_limited"
    assert result.trace["retryable"] is True


def test_next_missing_api_key_fails_before_network(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    post = Mock()
    monkeypatch.setattr("adapters.dashscope.audio_generation.requests.post", post)

    result = _adapter().generate(prompt="测试")

    assert result.success is False
    assert "DASHSCOPE_API_KEY" in result.error
    post.assert_not_called()


def test_next_archive_constraints_match_adapter_limits():
    """档案与适配器是两份事实源，必须逐条对齐，否则 UI 放开的值上游会打回。"""
    payload = yaml.safe_load((PROJECT_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    record = next(item for item in payload["models"] if item.get("id") == QWEN_AUDIO_31_TTS_NEXT_MODEL)
    constraints = record["constraints"]

    from adapters.dashscope import audio_generation as module

    assert constraints["max_prompt_chars"] == module.QWEN_AUDIO_NEXT_MAX_PROMPT_CHARS
    assert constraints["max_audio_references"] == module.QWEN_AUDIO_NEXT_MAX_REFERENCES
    assert set(constraints["supported_formats"]) == set(module.QWEN_AUDIO_NEXT_SUPPORTED_FORMATS)
    assert set(constraints["supported_sample_rates"]) == set(module.QWEN_AUDIO_NEXT_SUPPORTED_SAMPLE_RATES)
    assert set(constraints["supported_channels"]) == set(module.QWEN_AUDIO_NEXT_SUPPORTED_CHANNELS)
    assert [float(value) for value in constraints["rate_range"]] == [
        module.QWEN_AUDIO_NEXT_MIN_RATE,
        module.QWEN_AUDIO_NEXT_MAX_RATE,
    ]
    assert [int(value) for value in constraints["volume_range"]] == [
        module.QWEN_AUDIO_NEXT_MIN_VOLUME,
        module.QWEN_AUDIO_NEXT_MAX_VOLUME,
    ]
    assert record["api_config"]["endpoint"] == module.QWEN_AUDIO_31_TTS_NEXT_ENDPOINT
