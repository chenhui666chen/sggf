from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")


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
