import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for import_root in (PROJECT_ROOT, ROOT_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from adapters import adapter_helpers
from app.services.audiobook.agent_dispatch_client import (
    AgentSmartDispatchClient,
    _sanitize_dispatch_kwargs,
)
from app.services.audiobook.tts_model_ids import MIMO_V25_TTS_VOICE_DESIGN_MODEL


def test_agent_dispatch_reaches_tts_engine_boundary_with_fixed_voice(monkeypatch) -> None:
    captured = {}

    def fake_synthesize_speech_sync(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            success=True,
            outputs=[],
            error=None,
            error_code=None,
            cost=0.0,
            latency=0.01,
            metadata={},
            model_id=kwargs["model_id"],
            binary=b"unit-audio",
            data={"audio_bytes": b"unit-audio", "format": "mp3"},
        )

    monkeypatch.setattr(adapter_helpers, "synthesize_speech_sync", fake_synthesize_speech_sync)

    client = AgentSmartDispatchClient()
    result = client.synthesize(
        text="Keep walking.",
        voice_id="Cherry",
        tts_model="qwen-audio-3.1-tts-flash",
        instructions="Speak slowly and stress walking.",
        pitch=0.7,
        pitch_ratio=0.8,
        speed=1.1,
        rate=1.1,
        character_base_speed=1.0,
        voice_description="Replace the selected voice with an elderly deep voice.",
        provider_prompt_snapshot={"delivery_plan": {"pitch": "lower"}},
    )

    assert result.success is True
    assert result.audio_data == b"unit-audio"
    assert captured["text"] == "Keep walking."
    assert captured["model_id"] == "qwen-audio-3.1-tts-flash"

    voice_params = captured["voice_params"]
    assert voice_params["speaker"] == "Cherry"
    assert voice_params["tts_model"] == "qwen-audio-3.1-tts-flash"
    assert "pitch" not in voice_params
    assert "pitch_ratio" not in voice_params
    assert "speed" not in voice_params
    assert "rate" not in voice_params
    assert "character_base_speed" not in voice_params
    assert "voice_description" not in voice_params
    assert "provider_prompt_snapshot" not in voice_params
    assert "Speak slowly" in voice_params["instructions"]


def test_agent_dispatch_voice_design_creation_drops_numeric_speed_only() -> None:
    params = _sanitize_dispatch_kwargs(
        {
            "voice_design_prompt": "设计一位年长女性的声音",
            "pitch": 38,
            "speed": 1.1,
            "rate": 1.1,
            "character_base_speed": 1.0,
        },
        tts_model=MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    )

    assert params["voice_design_prompt"] == "设计一位年长女性的声音"
    assert params["pitch"] == 38
    assert "speed" not in params
    assert "rate" not in params
    assert "character_base_speed" not in params
