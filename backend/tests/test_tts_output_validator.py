import io
import base64
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.audiobook.tts_engine_pkg import RetryConfig, TTSEngine
from app.services.audiobook.tts_output_validator import (
    TTSValidationResult,
    estimate_tts_duration_ms,
    validate_tts_audio,
)

try:
    from pydub import AudioSegment
    from pydub.generators import Sine
except ImportError:  # pragma: no cover - optional dependency guard
    AudioSegment = None
    Sine = None


def _export_wav(audio: AudioSegment) -> bytes:
    buffer = io.BytesIO()
    audio.export(buffer, format="wav")
    return buffer.getvalue()


def _tone_wav(duration_ms: int = 1500) -> bytes:
    audio = (
        Sine(440)
        .to_audio_segment(duration=duration_ms)
        .apply_gain(-14)
        .set_frame_rate(24000)
        .set_channels(1)
    )
    return _export_wav(audio)


def _silent_wav(duration_ms: int = 1500) -> bytes:
    return _export_wav(AudioSegment.silent(duration=duration_ms, frame_rate=24000))


def test_estimate_tts_duration_counts_cjk_and_words():
    chinese = estimate_tts_duration_ms("她推开门，低声说：你终于来了。")
    mixed = estimate_tts_duration_ms("She opened the door and whispered hello.")

    assert chinese >= 1500
    assert mixed >= 1800


@pytest.mark.skipif(AudioSegment is None or Sine is None, reason="pydub unavailable")
def test_validate_tts_audio_accepts_normal_segment():
    result = validate_tts_audio(_tone_wav(1600), "她推开门，低声说：你终于来了。")

    assert result.passed is True
    assert result.reason == "ok"
    assert result.decodable is True
    assert result.duration_ms >= 1500


@pytest.mark.skipif(AudioSegment is None or Sine is None, reason="pydub unavailable")
def test_validate_tts_audio_rejects_undecodable_bytes():
    result = validate_tts_audio(b"not an audio file", "这是一句正常文本。")

    assert result.passed is False
    assert result.reason == "undecodable_audio"
    assert result.decodable is False


@pytest.mark.skipif(AudioSegment is None or Sine is None, reason="pydub unavailable")
def test_validate_tts_audio_rejects_low_energy_silence():
    result = validate_tts_audio(_silent_wav(1800), "这是一句正常文本。")

    assert result.passed is False
    assert result.reason in {"low_energy_audio", "excessive_silence"}
    assert result.silence_ratio >= 0.9


@pytest.mark.skipif(AudioSegment is None or Sine is None, reason="pydub unavailable")
def test_validate_tts_audio_rejects_duration_outlier():
    result = validate_tts_audio(_tone_wav(9000), "短句。")

    assert result.passed is False
    assert result.reason == "duration_outlier"
    assert result.duration_ms > result.max_duration_ms


@pytest.mark.skipif(AudioSegment is None or Sine is None, reason="pydub unavailable")
@pytest.mark.asyncio
async def test_tts_engine_retries_when_provider_output_fails_validation(monkeypatch):
    monkeypatch.setenv("AUDIOBOOK_TTS_OUTPUT_VALIDATION", "1")
    invalid_audio = _silent_wav(1600)
    valid_audio = _tone_wav(1600)
    calls = []
    engine = TTSEngine(
        enable_cache=False,
        request_delay=0,
        retry_config=RetryConfig(max_retries=2, base_delay=0, jitter=False),
    )

    async def fake_synthesize_aliyun(text, voice_params):
        calls.append((text, dict(voice_params)))
        return invalid_audio if len(calls) == 1 else valid_audio

    monkeypatch.setattr(engine, "_synthesize_aliyun", fake_synthesize_aliyun)

    audio = await engine.synthesize(
        "她推开门，低声说：你终于来了。",
        {"speaker": "longwan"},
        emotion="neutral",
    )

    assert audio == valid_audio
    assert len(calls) == 2
    assert engine.get_last_synthesis_metadata()["output_validation"]["passed"] is True


@pytest.mark.asyncio
async def test_tts_engine_does_not_count_empty_audio_as_billable_segment(monkeypatch):
    engine = TTSEngine(
        enable_cache=False,
        request_delay=0,
        retry_config=RetryConfig(max_retries=1, base_delay=0, jitter=False),
    )

    async def fake_synthesize_aliyun(text, voice_params):
        return b""

    monkeypatch.setattr(engine, "_synthesize_aliyun", fake_synthesize_aliyun)

    audio = await engine.synthesize(
        "empty audio should not be counted as usable output",
        {"speaker": "longwan"},
        emotion="neutral",
    )

    stats = engine.get_cost_stats()
    assert audio == b""
    assert stats["total_segments"] == 0
    assert stats["api_calls"] == 0
    assert stats["api_calls_scope"] == "usable_audio_outputs_only"
    assert stats["failed_segments"] == 1
    assert stats["failed_characters"] > 0
    assert stats["estimated_cost"].endswith("0.00")
    assert stats["estimated_cost_scope"] == "usable_audio_estimate"
    assert "provider may still bill" in stats["provider_billing_note"]


@pytest.mark.asyncio
async def test_tts_engine_records_failed_segment_when_provider_raises(monkeypatch):
    engine = TTSEngine(
        enable_cache=False,
        request_delay=0,
        retry_config=RetryConfig(max_retries=1, base_delay=0, jitter=False),
    )

    async def fake_synthesize_aliyun(text, voice_params):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(engine, "_synthesize_aliyun", fake_synthesize_aliyun)

    audio = await engine.synthesize(
        "provider exception should be visible but not billable",
        {"speaker": "longwan"},
        emotion="neutral",
    )

    stats = engine.get_cost_stats()
    assert audio == b""
    assert stats["total_segments"] == 0
    assert stats["api_calls"] == 0
    assert stats["api_calls_scope"] == "usable_audio_outputs_only"
    assert stats["failed_segments"] == 1
    assert stats["failed_characters"] > 0
    assert stats["estimated_cost"].endswith("0.00")
    assert stats["estimated_cost_scope"] == "usable_audio_estimate"
    assert "provider may still bill" in stats["provider_billing_note"]


def test_tts_cost_reset_preserves_model_price():
    engine = TTSEngine(
        enable_cache=False,
        request_delay=0,
        model="minimax-speech-2.8-hd",
    )

    engine.reset_cost_tracker()
    engine.cost_tracker.add_segment(10000, is_cached=False)

    stats = engine.get_cost_stats()
    assert stats["estimated_cost"] == "¥3.50"
    assert stats["estimated_cost_scope"] == "usable_audio_estimate"


@pytest.mark.asyncio
async def test_tts_engine_uses_validated_memory_cache(monkeypatch):
    monkeypatch.setenv("AUDIOBOOK_TTS_OUTPUT_VALIDATION", "0")
    engine = TTSEngine(
        enable_cache=True,
        request_delay=0,
        retry_config=RetryConfig(max_retries=1, base_delay=0, jitter=False),
    )
    await engine.cache.clear_all()
    calls = []

    async def fake_synthesize_aliyun(text, voice_params):
        calls.append((text, dict(voice_params)))
        return b"provider-audio"

    monkeypatch.setattr(engine, "_synthesize_aliyun", fake_synthesize_aliyun)

    first_audio = await engine.synthesize(
        "cacheable tts segment",
        {"speaker": "longwan"},
        emotion="neutral",
    )
    second_audio = await engine.synthesize(
        "cacheable tts segment",
        {"speaker": "longwan"},
        emotion="neutral",
    )

    stats = engine.get_cost_stats()
    assert first_audio == b"provider-audio"
    assert second_audio == b"provider-audio"
    assert len(calls) == 1
    assert stats["total_segments"] == 2
    assert stats["api_calls"] == 1
    assert stats["cache_hits"] == 1


@pytest.mark.asyncio
async def test_tts_engine_discards_invalid_cached_audio(monkeypatch):
    monkeypatch.setenv("AUDIOBOOK_TTS_OUTPUT_VALIDATION", "1")
    engine = TTSEngine(
        enable_cache=True,
        request_delay=0,
        retry_config=RetryConfig(max_retries=1, base_delay=0, jitter=False),
    )
    await engine.cache.clear_all()
    text = "cached invalid tts segment"
    voice_params = {"speaker": "longwan"}
    cache_key = engine._generate_cache_key(
        text,
        {**voice_params, "emotion": "neutral"},
        "neutral",
    )
    await engine.cache.set(
        cache_key,
        base64.b64encode(b"stale").decode("utf-8"),
        ttl=60,
    )
    calls = []

    def fake_validate(audio_bytes, _text):
        passed = audio_bytes == b"fresh"
        return TTSValidationResult(
            passed=passed,
            reason="ok" if passed else "stale_cache",
            decodable=passed,
        )

    async def fake_synthesize_aliyun(text, voice_params):
        calls.append((text, dict(voice_params)))
        return b"fresh"

    monkeypatch.setattr(engine, "_validate_tts_output", fake_validate)
    monkeypatch.setattr(engine, "_synthesize_aliyun", fake_synthesize_aliyun)

    first_audio = await engine.synthesize(text, voice_params, emotion="neutral")
    second_audio = await engine.synthesize(text, voice_params, emotion="neutral")

    stats = engine.get_cost_stats()
    assert first_audio == b"fresh"
    assert second_audio == b"fresh"
    assert len(calls) == 1
    assert stats["api_calls"] == 1
    assert stats["cache_hits"] == 1
