from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook import prompt_audio_asr_provider as provider_module


def test_normalize_asr_subtitle_payload_uses_provider_millisecond_timestamps() -> None:
    from app.services.audiobook.prompt_audio_asr_provider import (
        normalize_asr_subtitle_payload,
    )

    normalized = normalize_asr_subtitle_payload(
        {
            "result": {
                "text": "first line second line",
                "utterances": [
                    {
                        "text": "first line",
                        "start_time": 120,
                        "end_time": 880,
                    },
                    {
                        "text": "second line",
                        "begin_time": 920,
                        "end_time": 1600,
                    },
                ],
            }
        }
    )

    assert normalized == {
        "segments": [
            {"text": "first line", "start_ms": 120, "end_ms": 880},
            {"text": "second line", "start_ms": 920, "end_ms": 1600},
        ]
    }


def test_provider_error_detail_only_keeps_code_and_message() -> None:
    from app.services.audiobook import prompt_audio_asr_provider as provider_module

    class FakeResponse:
        text = '{"code": "InvalidParameter", "message": "audio field is required", "secret": "must-not-leak"}'

        def json(self):
            return {
                "code": "InvalidParameter",
                "message": "audio field is required",
                "secret": "must-not-leak",
            }

    detail = provider_module._provider_error_detail(FakeResponse())

    assert detail == "code=InvalidParameter message=audio field is required"
    assert "secret" not in detail


def test_provider_error_detail_reads_openspeech_diagnostic_headers() -> None:
    from app.services.audiobook import prompt_audio_asr_provider as provider_module

    class FakeResponse:
        headers = {
            "X-Api-Status-Code": "45000000",
            "X-Api-Message": "invalid request payload",
            "X-Tt-Logid": "log-1",
            "Authorization": "must-not-leak",
        }

        def json(self):
            raise ValueError("empty response")

    detail = provider_module._provider_error_detail(FakeResponse())

    assert detail == (
        "code=45000000 message=invalid request payload log_id=log-1"
    )
    assert "Authorization" not in detail
    assert "must-not-leak" not in detail


def test_mimo_asr_provider_sends_audio_only_content(monkeypatch, tmp_path) -> None:
    from app.services.audiobook.prompt_audio_asr_provider import MiMoPromptAudioAsrProvider

    audio_file = tmp_path / "sample.mp3"
    audio_file.write_bytes(b"fake mp3 bytes")
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"text": "转写文本"}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)

    provider = MiMoPromptAudioAsrProvider(
        api_key="unit-key",
        base_url="https://example.test/v1",
        model="mimo-v2.5-asr",
    )

    result = provider.transcribe(str(audio_file))

    assert result.transcript == "转写文本"
    assert provider.supports_timestamps is False
    assert captured["url"] == "https://example.test/v1/chat/completions"
    payload = captured["json"]
    content = payload["messages"][0]["content"]
    assert [part["type"] for part in content] == ["input_audio"]
    assert content[0]["input_audio"]["format"] == "mp3"
    assert content[0]["input_audio"]["mime_type"] == "audio/mpeg"


def test_mimo_asr_provider_parses_chat_completion_message_content(monkeypatch, tmp_path) -> None:
    from app.services.audiobook.prompt_audio_asr_provider import MiMoPromptAudioAsrProvider

    audio_file = tmp_path / "sample.mp3"
    audio_file.write_bytes(b"fake mp3 bytes")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "id": "chatcmpl-unit",
                "choices": [
                    {"message": {"role": "assistant", "content": "天气很好。"}}
                ],
                "usage": {"total_tokens": 12},
            }

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: FakeResponse())

    provider = MiMoPromptAudioAsrProvider(api_key="unit-key")

    result = provider.transcribe(str(audio_file))

    assert result.provider == "mimo"
    assert result.model == "mimo-v2.5-asr"
    assert result.transcript == "天气很好。"
    assert result.metadata["response_id"] == "chatcmpl-unit"
    assert result.metadata["usage"] == {"total_tokens": 12}


def test_aliyun_asr_provider_downloads_transcription_result(monkeypatch) -> None:
    from dashscope.audio.asr import Transcription

    from app.services.audiobook.prompt_audio_asr_provider import (
        AliyunPromptAudioAsrProvider,
    )

    class AttrDict(dict):
        __getattr__ = dict.get

    monkeypatch.setattr(
        Transcription,
        "async_call",
        lambda **_kwargs: SimpleNamespace(output=AttrDict(task_id="task-1")),
    )
    monkeypatch.setattr(
        Transcription,
        "fetch",
        lambda **_kwargs: SimpleNamespace(
            output=AttrDict(
                task_id="task-1",
                task_status="SUCCEEDED",
                results=[
                    {
                        "subtask_status": "SUCCEEDED",
                        "transcription_url": "https://result.example.test/task-1.json",
                    }
                ],
            )
        ),
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "properties": {"original_duration_in_milliseconds": 4500},
                "transcripts": [
                    {
                        "text": "山河远阔，人间烟火。",
                        "sentences": [
                            {
                                "text": "山河远阔，",
                                "begin_time": 100,
                                "end_time": 1800,
                            },
                            {
                                "text": "人间烟火。",
                                "begin_time": 1900,
                                "end_time": 4200,
                            },
                        ],
                    }
                ],
            }

    def fake_get(url, *, timeout, follow_redirects):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["follow_redirects"] = follow_redirects
        return FakeResponse()

    monkeypatch.setattr("httpx.get", fake_get)
    provider = AliyunPromptAudioAsrProvider(api_key="unit-key", timeout_seconds=30)

    result = provider.transcribe(
        "unused.wav",
        audio_url="https://audio.example.test/system-voice.wav",
    )

    assert result.transcript == "山河远阔，人间烟火。"
    assert result.subtitle_payload == {
        "segments": [
            {"text": "山河远阔，", "start_ms": 100, "end_ms": 1800},
            {"text": "人间烟火。", "start_ms": 1900, "end_ms": 4200},
        ]
    }
    assert result.metadata == {
        "task_id": "task-1",
        "usage": {"duration": 4.5},
    }
    assert captured["url"] == "https://result.example.test/task-1.json"
    assert 0 < float(captured["timeout"]) <= 30.0
    assert captured["follow_redirects"] is True


# fun-asr-flash 返回结构非标准：结果嵌套在 output.output.sentence，逐字时间戳带标点。
# 下面用真实响应形态作 fixture，离线验证 SSE 解析与按标点重切分段逻辑。
_FUNASR_SENTENCE = {
    "sentence_id": 1,
    "sentence_end": True,
    "begin_time": 160,
    "end_time": 2360,
    "text": "雨停以后，钟声传来。",
    "words": [
        {"begin_time": 160, "end_time": 400, "punctuation": "", "text": "雨"},
        {"begin_time": 400, "end_time": 640, "punctuation": "", "text": "停"},
        {"begin_time": 640, "end_time": 1000, "punctuation": "，", "text": "以后"},
        {"begin_time": 1200, "end_time": 1600, "punctuation": "", "text": "钟声"},
        {"begin_time": 1600, "end_time": 2360, "punctuation": "。", "text": "传来"},
    ],
}


def _funasr_sse_line() -> str:
    import json

    event = {
        "output": {
            "output": {"sentence": _FUNASR_SENTENCE, "text": _FUNASR_SENTENCE["text"]},
            "sentence": _FUNASR_SENTENCE,
            "text": _FUNASR_SENTENCE["text"],
            "request_id": "req-unit",
            "usage": {"duration": 3},
        },
        "usage": {"duration": 3},
        "request_id": "req-unit",
    }
    return "data:" + json.dumps(event, ensure_ascii=False)


def test_funasr_collect_sentences_reads_nested_output() -> None:
    from app.services.audiobook.prompt_audio_asr_provider import (
        _funasr_collect_sentences,
    )

    lines = ["id:1", "event:result", ":HTTP_STATUS/200", _funasr_sse_line(), ""]
    sentences, meta = _funasr_collect_sentences(lines)

    assert len(sentences) == 1
    assert sentences[0]["text"] == "雨停以后，钟声传来。"
    assert meta["request_id"] == "req-unit"
    assert meta["usage"] == {"duration": 3}


def test_funasr_subtitle_payload_splits_words_on_punctuation() -> None:
    from app.services.audiobook.prompt_audio_asr_provider import (
        _funasr_subtitle_payload,
        normalize_asr_subtitle_payload,
    )

    payload = _funasr_subtitle_payload([_FUNASR_SENTENCE])
    normalized = normalize_asr_subtitle_payload(payload)

    assert normalized == {
        "segments": [
            {"text": "雨停以后，", "start_ms": 160, "end_ms": 1000},
            {"text": "钟声传来。", "start_ms": 1200, "end_ms": 2360},
        ]
    }


def test_funasr_flash_provider_transcribes_via_stream(monkeypatch, tmp_path) -> None:
    from app.services.audiobook.prompt_audio_asr_provider import (
        FunAsrFlashPromptAudioAsrProvider,
    )

    audio_file = tmp_path / "chapter.mp3"
    audio_file.write_bytes(b"fake mp3 bytes")
    captured: dict[str, object] = {}

    class FakeStream:
        status_code = 200

        def __init__(self, lines):
            self._lines = lines

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def iter_lines(self):
            return iter(self._lines)

        def read(self):
            return b""

    def fake_stream(method, url, *, headers, json, timeout):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeStream(["id:1", "event:result", _funasr_sse_line()])

    monkeypatch.setattr("httpx.stream", fake_stream)

    provider = FunAsrFlashPromptAudioAsrProvider(api_key="unit-key")
    result = provider.transcribe(str(audio_file))

    assert result.provider == "funasr_flash"
    assert result.model == "fun-asr-flash-2026-06-15"
    assert result.transcript == "雨停以后，钟声传来。"
    assert result.metadata["request_id"] == "req-unit"
    assert result.metadata["usage"] == {"duration": 3}
    assert result.subtitle_payload == {
        "segments": [
            {"text": "雨停以后，", "start_ms": 160, "end_ms": 1000},
            {"text": "钟声传来。", "start_ms": 1200, "end_ms": 2360},
        ]
    }
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/multimodal-generation/generation")
    assert captured["headers"]["X-DashScope-SSE"] == "enable"
    content = captured["json"]["input"]["messages"][0]["content"]
    assert content[0]["input_audio"]["data"].startswith("data:audio/mpeg;base64,")
    assert captured["json"]["parameters"]["format"] == "mp3"


def test_create_prompt_audio_asr_provider_returns_funasr_flash(monkeypatch) -> None:
    from app.services.audiobook.prompt_audio_asr_provider import (
        FunAsrFlashPromptAudioAsrProvider,
        create_prompt_audio_asr_provider,
    )

    monkeypatch.delenv("DASHSCOPE_ASR_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-key")

    provider = create_prompt_audio_asr_provider("fun-asr-flash")

    assert isinstance(provider, FunAsrFlashPromptAudioAsrProvider)
    assert provider.supports_timestamps is True


def test_default_prompt_audio_asr_provider_is_funasr_flash(monkeypatch) -> None:
    from app.services.audiobook.prompt_audio_asr_provider import (
        FunAsrFlashPromptAudioAsrProvider,
        create_prompt_audio_asr_provider,
    )

    monkeypatch.delenv("PROMPT_AUDIO_ASR_PROVIDER", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-key")

    provider = create_prompt_audio_asr_provider()

    assert isinstance(provider, FunAsrFlashPromptAudioAsrProvider)
    assert provider.supports_timestamps is True


def test_doubao_asr_provider_accepts_configured_openspeech_key(monkeypatch) -> None:
    from app.services.audiobook.prompt_audio_asr_provider import (
        DoubaoPromptAudioAsrProvider,
        create_prompt_audio_asr_provider,
    )

    monkeypatch.delenv("VOLCENGINE_ASR_API_KEY", raising=False)
    monkeypatch.delenv("DOUBAO_ASR_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_SPEECH_API_KEY", raising=False)
    monkeypatch.delenv("DOUBAO_SPEECH_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_OPEN_SPEECH_API_KEY", "unit-openspeech-key")

    provider = create_prompt_audio_asr_provider("doubao")

    assert isinstance(provider, DoubaoPromptAudioAsrProvider)
    assert provider.api_key == "unit-openspeech-key"


def test_prompt_audio_asr_factory_applies_shared_timeout(monkeypatch) -> None:
    from app.services.audiobook.prompt_audio_asr_provider import (
        DoubaoPromptAudioAsrProvider,
        create_prompt_audio_asr_provider,
    )

    monkeypatch.setenv("VOLCENGINE_OPEN_SPEECH_API_KEY", "unit-openspeech-key")
    monkeypatch.setenv("PROMPT_AUDIO_ASR_TIMEOUT_SECONDS", "45")

    provider = create_prompt_audio_asr_provider("doubao")

    assert isinstance(provider, DoubaoPromptAudioAsrProvider)
    assert provider.timeout_seconds == 45.0


def test_doubao_asr_provider_uses_official_recording_file_contract(monkeypatch) -> None:
    from app.services.audiobook import prompt_audio_asr_provider as provider_module

    calls: list[dict[str, object]] = []

    class FakeResponse:
        status_code = 200

        def __init__(self, *, status_code: str, payload=None):
            self.headers = {
                "X-Api-Status-Code": status_code,
                "X-Api-Message": "OK",
                "X-Tt-Logid": f"log-{status_code}",
            }
            self._payload = payload

        def json(self):
            if self._payload is None:
                raise ValueError("official submit and pending responses have an empty body")
            return self._payload

    responses = iter(
        [
            FakeResponse(status_code="20000000"),
            FakeResponse(status_code="20000001"),
            FakeResponse(
                status_code="20000000",
                payload={
                    "audio_info": {"duration": 3696},
                    "result": {
                        "text": "这是字节跳动，今日头条母公司。",
                        "utterances": [
                            {
                                "text": "这是字节跳动，",
                                "start_time": 0,
                                "end_time": 1705,
                            },
                            {
                                "text": "今日头条母公司。",
                                "start_time": 2110,
                                "end_time": 3696,
                            },
                        ],
                    },
                },
            ),
        ]
    )

    class FakeClient:
        def __init__(self, *, timeout):
            assert 0 < timeout <= 30.0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def post(self, url, *, headers, json, timeout=None):
            calls.append({"url": url, "headers": dict(headers), "json": json})
            return next(responses)

    monkeypatch.setattr("httpx.Client", FakeClient)
    monkeypatch.setattr(provider_module.time, "sleep", lambda _seconds: None)
    provider = provider_module.DoubaoPromptAudioAsrProvider(
        api_key="unit-key",
        resource_id="volc.seedasr.auc",
        endpoint="https://openspeech.example.test/api/v3/auc/bigmodel",
        timeout_seconds=30,
    )

    result = provider.transcribe(
        "unused.wav",
        audio_url="https://audio.example.test/system-voice.wav",
    )

    assert len(calls) == 3
    submit_call, pending_query_call, success_query_call = calls
    request_id = submit_call["headers"]["X-Api-Request-Id"]
    assert submit_call == {
        "url": "https://openspeech.example.test/api/v3/auc/bigmodel/submit",
        "headers": {
            "X-Api-Key": "unit-key",
            "X-Api-Resource-Id": "volc.seedasr.auc",
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
            "Content-Type": "application/json",
        },
        "json": {
            "audio": {
                "format": "wav",
                "url": "https://audio.example.test/system-voice.wav",
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True,
            },
        },
    }
    expected_query_call = {
        "url": "https://openspeech.example.test/api/v3/auc/bigmodel/query",
        "headers": {
            "X-Api-Key": "unit-key",
            "X-Api-Resource-Id": "volc.seedasr.auc",
            "X-Api-Request-Id": request_id,
            "Content-Type": "application/json",
        },
        "json": {},
    }
    assert pending_query_call == expected_query_call
    assert success_query_call == expected_query_call
    assert result.transcript == "这是字节跳动，今日头条母公司。"
    assert result.subtitle_payload == {
        "segments": [
            {"text": "这是字节跳动，", "start_ms": 0, "end_ms": 1705},
            {"text": "今日头条母公司。", "start_ms": 2110, "end_ms": 3696},
        ]
    }
    assert result.metadata == {
        "request_id": request_id,
        "usage": {"duration": 3.696},
    }
def test_asr_remaining_timeout_uses_one_absolute_deadline(monkeypatch) -> None:
    ticks = iter((100.0, 103.5, 109.9, 110.0))
    monkeypatch.setattr(provider_module.time, "monotonic", lambda: next(ticks))
    deadline = provider_module._new_asr_deadline(10.0)

    assert provider_module._remaining_asr_timeout(deadline, cap=30.0) == 6.5
    assert provider_module._remaining_asr_timeout(deadline, cap=30.0) == pytest.approx(0.1)
    with pytest.raises(
        provider_module.PromptAudioAsrProviderError,
        match="ASR.*超时|ASR.*timeout",
    ) as error:
        provider_module._remaining_asr_timeout(deadline, cap=30.0)
    assert error.value.code == "asr_provider_timeout"
