import asyncio
import os
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.tts_engine import RetryConfig, TTSEngine


pytestmark = pytest.mark.skipif(
    os.getenv("AUDIOBOOK_TTS_PROVIDER_SMOKE") != "1",
    reason="set AUDIOBOOK_TTS_PROVIDER_SMOKE=1 to run paid/network TTS provider smoke tests",
)


def _require_dashscope_api_key() -> None:
    if not (os.getenv("DASHSCOPE_API_KEY") or "").strip():
        pytest.skip("DASHSCOPE_API_KEY is required for provider smoke tests")


async def _synthesize_smoke(
    *,
    model: str,
    text: str,
    voice_params: dict,
    emotion: str = "neutral",
) -> dict:
    engine = TTSEngine(
        model=model,
        enable_cache=False,
        max_concurrent=1,
        request_delay=0.0,
        retry_config=RetryConfig(max_retries=1, base_delay=0.1, max_delay=0.1, jitter=False),
    )
    payload = await engine.synthesize_with_metadata(text, voice_params, emotion)
    audio_bytes = payload.get("audio_bytes")
    assert isinstance(audio_bytes, bytes)
    assert len(audio_bytes) > 256
    assert payload.get("format") in {"mp3", "wav", "pcm"}
    return payload


def test_qwen_provider_smoke_returns_audio() -> None:
    _require_dashscope_api_key()

    payload = asyncio.run(
        _synthesize_smoke(
            model="qwen3-tts-instruct-flash",
            text="这是一段耳畔星河的真实语音合成烟测。",
            voice_params={
                "speaker": "Neil",
                "volume": 50,
                "instructions": "自然、清晰、适合有声书旁白。",
            },
        )
    )

    assert payload.get("provider") == "aliyun"
    assert payload.get("provider_model") == "qwen3-tts-instruct-flash"
    assert payload.get("speaker") == "Neil"
    assert payload.get("transport") == "http"


def test_minimax_provider_smoke_returns_audio() -> None:
    _require_dashscope_api_key()

    payload = asyncio.run(
        _synthesize_smoke(
            model="minimax-speech-2.8-turbo",
            text="这是一段耳畔星河的 MiniMax 语音合成烟测。",
            voice_params={
                "speaker": "male-qn-qingse",
                "rate": 1.0,
                "volume": 50,
                "pitch": 0,
            },
            emotion="calm",
        )
    )

    assert isinstance(payload.get("audio_bytes"), bytes)


def test_cosyvoice_provider_smoke_returns_audio_with_optional_timestamps() -> None:
    _require_dashscope_api_key()
    voice_id = (os.getenv("AUDIOBOOK_COSYVOICE_SMOKE_VOICE_ID") or "").strip()
    if not voice_id:
        pytest.skip("AUDIOBOOK_COSYVOICE_SMOKE_VOICE_ID is required for CosyVoice smoke test")

    payload = asyncio.run(
        _synthesize_smoke(
            model="cosyvoice-v3.5-plus",
            text="这是一段耳畔星河的 CosyVoice 语音合成烟测。",
            voice_params={
                "speaker": voice_id,
                "volume": 50,
                "rate": 1.0,
                "pitch": 1.0,
                "instruction": "自然、富有画面感。",
                "word_timestamp_enabled": True,
                "phoneme_timestamp_enabled": True,
            },
        )
    )

    assert payload.get("provider") == "aliyun"
    assert payload.get("provider_model") == "cosyvoice-v3.5-plus"
    assert payload.get("speaker") == voice_id
    assert payload.get("transport") == "websocket"
    assert payload.get("word_timestamp_enabled") is True
    assert payload.get("phoneme_timestamp_enabled") is True
    assert isinstance(payload.get("tts_timestamps"), list)
    assert isinstance(payload.get("tts_timestamp_sentences"), list)
    assert isinstance(payload.get("phoneme_timestamps"), list)
