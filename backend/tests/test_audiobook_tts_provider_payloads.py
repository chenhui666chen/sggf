import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.tts_engine import TTSEngine
from app.services.audiobook.engine_pkg._tts_mixin import QWEN_RENDER_CHUNK_MAX_CHARS, TTSMixin
from app.services.audiobook.tts_engine_pkg._aliyun_mixin import (
    QWEN_TTS_INPUT_SAFETY_CHARS,
    QWEN_TTS_MAX_INPUT_CHARS,
)


def test_qwen_http_payload_preserves_voice_language_and_instructions() -> None:
    engine = TTSEngine(model="qwen3-tts-instruct-flash", enable_cache=False, request_delay=0)

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text="她压低声音说。",
        voice_id="Neil",
        voice_params={
            "language_type": "Chinese",
            "segment_speaker": "林晚",
            "segment_type": "dialogue",
            "instruct_role": "冷静的调查员",
            "emotion": "tense",
            "performance_notes": "压低声音，停顿更长",
        },
    )

    assert payload["model"] == "qwen3-tts-instruct-flash"
    assert payload["input"] == {
        "text": "她压低声音说。",
        "voice": "Neil",
        "language_type": "Chinese",
    }
    assert "parameters" in payload
    assert payload["parameters"]["optimize_instructions"] is True
    instructions = payload["parameters"]["instructions"]
    assert "说话角色：林晚" in instructions
    assert "角色设定：冷静的调查员" in instructions
    assert "情绪目标：tense" in instructions
    assert "演绎要求：压低声音，停顿更长" in instructions


def test_qwen_explicit_instructions_override_derived_prompt() -> None:
    engine = TTSEngine(model="qwen3-tts-instruct-flash", enable_cache=False, request_delay=0)

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text="旁白文本",
        voice_id="Cherry",
        voice_params={
            "instructions": "慢速、温柔、带一点回忆感",
            "optimize_instructions": False,
            "segment_speaker": "不应进入",
        },
    )

    assert payload["input"]["language_type"] == "Auto"
    assert payload["parameters"] == {
        "instructions": "慢速、温柔、带一点回忆感",
        "optimize_instructions": False,
    }


def test_qwen_http_payload_truncates_instructions_to_provider_input_limit() -> None:
    engine = TTSEngine(model="qwen3-tts-instruct-flash", enable_cache=False, request_delay=0)
    text = "x" * 520

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text=text,
        voice_id="Neil",
        voice_params={
            "instructions": "y" * 300,
            "optimize_instructions": False,
        },
    )

    assert payload["input"]["text"] == text
    assert "parameters" in payload
    instructions = payload["parameters"]["instructions"]
    assert len(text) + len(instructions) <= QWEN_TTS_MAX_INPUT_CHARS - QWEN_TTS_INPUT_SAFETY_CHARS
    assert instructions == "y" * (QWEN_TTS_MAX_INPUT_CHARS - QWEN_TTS_INPUT_SAFETY_CHARS - len(text))
    assert payload["parameters"]["optimize_instructions"] is False


def test_qwen_http_payload_drops_instructions_when_text_uses_budget() -> None:
    engine = TTSEngine(model="qwen3-tts-instruct-flash", enable_cache=False, request_delay=0)

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text="x" * 590,
        voice_id="Neil",
        voice_params={"instructions": "y" * 40},
    )

    assert payload["input"]["text"] == "x" * 590
    assert "parameters" not in payload


def test_qwen_render_chunks_use_conservative_limit() -> None:
    class DummyEngine(TTSMixin):
        tts_model = "minimax-speech-2.8-hd"

    segment = SimpleNamespace(
        text="x" * (QWEN_RENDER_CHUNK_MAX_CHARS + 80),
        voice_params={"tts_model": "qwen3-tts-instruct-flash"},
    )

    chunks = DummyEngine()._build_render_chunks([segment])

    assert len(chunks) == 2
    assert all(len(chunk.text) <= QWEN_RENDER_CHUNK_MAX_CHARS for chunk in chunks)


def test_cosyvoice_websocket_parameters_and_commands_are_stable() -> None:
    engine = TTSEngine(model="cosyvoice-v3.5-plus", enable_cache=False, request_delay=0)

    parameters = engine._build_cosyvoice_websocket_parameters(
        text="<speak>你好</speak>",
        voice="cosyvoice-v3.5-plus-demo",
        voice_params={
            "rate": 3.2,
            "pitch": 60,
            "volume": 120,
            "sample_rate": 12345,
            "format": "flac",
            "instructions": "温柔但坚定" * 20,
            "language_hints": ["zh", "", "en", "ja", "ko", "fr"],
            "word_timestamp_enabled": "true",
            "phoneme_timestamp_enabled": 1,
            "seed": "42",
        },
    )

    assert parameters["text_type"] == "PlainText"
    assert parameters["voice"] == "cosyvoice-v3.5-plus-demo"
    assert parameters["format"] == "mp3"
    assert parameters["sample_rate"] == 22050
    assert parameters["volume"] == 100
    assert parameters["rate"] == 2.0
    assert parameters["pitch"] == 1.2
    assert parameters["enable_ssml"] is True
    assert parameters["word_timestamp_enabled"] is True
    assert parameters["phoneme_timestamp_enabled"] is True
    assert parameters["seed"] == 42
    assert parameters["language_hints"] == ["zh", "en", "ja", "ko", "fr"]
    assert parameters["instruction"].startswith("温柔但坚定")
    assert len(parameters["instruction"].encode("utf-8")) > 0

    run_task = engine._build_cosyvoice_run_task_command(
        task_id="task-1",
        model="cosyvoice-v3.5-plus",
        parameters=parameters,
    )
    assert run_task["header"] == {
        "action": "run-task",
        "task_id": "task-1",
        "streaming": "duplex",
    }
    assert run_task["payload"]["task_group"] == "audio"
    assert run_task["payload"]["task"] == "tts"
    assert run_task["payload"]["function"] == "SpeechSynthesizer"
    assert run_task["payload"]["model"] == "cosyvoice-v3.5-plus"
    assert run_task["payload"]["parameters"] is parameters

    continue_task = engine._build_cosyvoice_continue_task_command(task_id="task-1", text="继续文本")
    finish_task = engine._build_cosyvoice_finish_task_command(task_id="task-1")
    assert continue_task["payload"] == {"input": {"text": "继续文本"}}
    assert finish_task["header"]["action"] == "finish-task"
    assert finish_task["payload"] == {"input": {}}


def test_minimax_http_payload_clamps_voice_settings_and_keeps_audio_contract() -> None:
    engine = TTSEngine(model="minimax-speech-2.8-hd", enable_cache=False, request_delay=0)

    candidates = engine._build_minimax_voice_candidates("male-qn-qingse")
    assert candidates[:3] == ["male-qn-qingse", "male-qingse", "qingse"]
    assert candidates.count("male-qn-qingse") == 1

    payload = engine._build_minimax_http_payload(
        model="MiniMax/speech-2.8-hd",
        text="这是一段 MiniMax 试听。",
        voice="male-qn-qingse",
        voice_params={
            "rate": 3.0,
            "volume": 150,
            "pitch": -150,
        },
    )

    assert payload["model"] == "MiniMax/speech-2.8-hd"
    assert payload["input"]["action"] == "tts"
    assert payload["input"]["text"] == "这是一段 MiniMax 试听。"
    assert payload["input"]["stream"] is False
    assert payload["input"]["voice_setting"] == {
        "voice_id": "male-qn-qingse",
        "speed": 2.0,
        "vol": 1.0,
        "pitch": -100,
    }
    assert payload["input"]["audio_setting"] == {
        "sample_rate": 16000,
        "format": "mp3",
        "channel": 1,
    }


def test_minimax_interjection_injection_does_not_spell_out_pause_notes() -> None:
    engine = TTSEngine(model="minimax-speech-2.8-hd", enable_cache=False, request_delay=0)

    text = engine._apply_interjections("必须走。", "句尾停顿一秒，压低声音", "tense")

    assert text == "必须走。"
    assert "停顿" not in text
