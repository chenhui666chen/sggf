from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_string = str(path)
    if path_string not in sys.path:
        sys.path.insert(0, path_string)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.scripts import probe_prompt_audio_asr as probe_module


def test_probe_uses_public_url_and_sanitizes_provider_metadata(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeProvider:
        timeout_seconds = 300.0

        def transcribe(self, audio_path: str, *, audio_url: str):
            calls.append((audio_path, audio_url))
            return SimpleNamespace(
                provider="fake",
                model="fake-v1",
                transcript="测试转写",
                subtitle_payload={
                    "segments": [{"text": "测试转写", "start_ms": 0, "end_ms": 800}]
                },
                metadata={
                    "request_id": "request-1",
                    "usage": {"duration": 1},
                    "raw_output": {"must_not_persist": True},
                },
            )

    provider = FakeProvider()
    monkeypatch.setattr(
        probe_module,
        "create_prompt_audio_asr_provider",
        lambda _name: provider,
    )

    result = probe_module.probe_prompt_audio_asr(
        provider_name="aliyun",
        audio_url="https://audio.example.test/probe.wav",
        timeout_seconds=15.0,
    )

    assert calls == [
        ("remote-contract-probe", "https://audio.example.test/probe.wav")
    ]
    assert provider.timeout_seconds == 15.0
    assert result["metadata"] == {
        "request_id": "request-1",
        "usage": {"duration": 1},
    }
    assert "raw_output" not in str(result)


def test_probe_rejects_non_https_audio_url(monkeypatch) -> None:
    monkeypatch.setattr(
        probe_module,
        "create_prompt_audio_asr_provider",
        lambda _name: SimpleNamespace(),
    )

    try:
        probe_module.probe_prompt_audio_asr(
            provider_name="aliyun",
            audio_url="file:///private/user.wav",
        )
    except ValueError as exc:
        assert "public HTTPS URL" in str(exc)
    else:
        raise AssertionError("non-HTTPS audio URL must be rejected")


def test_probe_main_persists_sanitized_failure_with_elapsed_time(
    monkeypatch, tmp_path
) -> None:
    output_path = tmp_path / "probe.json"

    def fail_probe(**_kwargs):
        raise probe_module.PromptAudioAsrProviderError(
            "asr_provider_timeout", "provider timed out"
        )

    monkeypatch.setattr(probe_module, "probe_prompt_audio_asr", fail_probe)
    result = probe_module.main(
        [
            "--provider",
            "aliyun",
            "--audio-url",
            "https://audio.example.test/probe.wav",
            "--timeout",
            "45",
            "--output",
            str(output_path),
        ]
    )

    assert result == 1
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["error_code"] == "asr_provider_timeout"
    assert payload["timeout_s"] == 45.0
    assert payload["elapsed_s"] >= 0
    assert "audio-url" not in str(payload)
