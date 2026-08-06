import asyncio
import base64
import json
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

from app.services.audiobook.tts_engine import TTSEngine
from app.services.audiobook.engine_pkg._tts_mixin import QWEN_RENDER_CHUNK_MAX_CHARS, TTSMixin
from app.services.audiobook.tts_engine_pkg._base import redact_tts_voice_params_for_log
from app.services.audiobook.tts_engine_pkg._aliyun_mixin import (
    QWEN_TTS_COMPACT_IDENTITY_INSTRUCTION,
    QWEN_TTS_INPUT_SAFETY_CHARS,
    QWEN_TTS_MAX_INPUT_CHARS,
    SEED_TTS_API_KEY_ENV_NAMES,
)
from app.services.audiobook.tts_model_ids import (
    MIMO_V25_TTS_MODEL,
    MIMO_V25_TTS_VOICE_CLONE_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_25_TTS_MODEL,
)
from app.services.audiobook.narration_styles import apply_narration_style_to_tts_params
from app.services.audiobook.tts_style_control import (
    build_model_style_control,
    prepare_text_for_style_control,
)
from app.services.audiobook.voice_identity_policy import VOICE_IDENTITY_POLICY_VERSION


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
    assert "情绪目标：fearful" in instructions
    assert "演绎要求：压低声音，停顿更长" in instructions


def test_tts_voice_params_log_redacts_clone_data_urls() -> None:
    redacted = redact_tts_voice_params_for_log(
        {
            "speaker": "mimo_clone:mimo_clone_saved",
            "voice_clone_data_url": "data:audio/webm;base64," + ("a" * 120),
            "nested": {"voice_sample_data_url": "data:audio/wav;base64," + ("b" * 80)},
        }
    )

    assert redacted["speaker"] == "mimo_clone:mimo_clone_saved"
    assert redacted["voice_clone_data_url"] == "<audio data URL: audio/webm, base64 chars=120>"
    assert redacted["nested"]["voice_sample_data_url"] == "<audio data URL: audio/wav, base64 chars=80>"


def test_qwen_explicit_instructions_merge_with_structured_prompt() -> None:
    engine = TTSEngine(model="qwen3-tts-instruct-flash", enable_cache=False, request_delay=0)

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text="旁白文本",
        voice_id="Cherry",
        voice_params={
            "instructions": "慢速、温柔、带一点回忆感",
            "optimize_instructions": False,
            "segment_speaker": "林晚",
            "segment_type": "dialogue",
            "instruct_scene": "雨夜逃亡",
            "instruct_role": "克制但紧张的调查员",
            "instruct_emotion": "fearful",
            "performance_notes": "句尾短暂停顿。",
        },
    )

    assert payload["input"]["language_type"] == "Auto"
    assert payload["parameters"]["optimize_instructions"] is False
    instructions = payload["parameters"]["instructions"]
    assert instructions.startswith("音色约束：保持已选音色")
    assert instructions.index("音色约束：") < instructions.index("慢速、温柔、带一点回忆感")
    assert "说话角色：林晚" in instructions
    assert "片段类型：dialogue" in instructions
    assert "角色设定：克制但紧张的调查员" in instructions
    assert "场景氛围：雨夜逃亡" in instructions
    assert "情绪目标：fearful" in instructions
    assert "演绎要求：句尾短暂停顿" in instructions


def test_qwen_payload_ignores_legacy_narration_style_runtime_overrides() -> None:
    engine = TTSEngine(model="qwen3-tts-instruct-flash", enable_cache=False, request_delay=0)
    voice_params = apply_narration_style_to_tts_params(
        "relaxing",
        {
            "speaker": "Neil",
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "emotion": "neutral",
        },
    )

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text="夜色慢慢落下来。",
        voice_id="Neil",
        voice_params=voice_params,
    )

    instructions = payload["parameters"]["instructions"]
    assert instructions.startswith("音色约束：保持已选音色")
    assert "声音描述：" not in instructions
    assert "片段类型：narration" in instructions
    assert "温和、舒缓、放松" not in instructions
    assert "语速：缓慢" not in instructions


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
    instruction_budget = QWEN_TTS_MAX_INPUT_CHARS - QWEN_TTS_INPUT_SAFETY_CHARS - len(text)
    assert len(text) + len(instructions) <= QWEN_TTS_MAX_INPUT_CHARS - QWEN_TTS_INPUT_SAFETY_CHARS
    assert len(instructions) == instruction_budget
    assert instructions.startswith(f"{QWEN_TTS_COMPACT_IDENTITY_INSTRUCTION}；")
    assert "y" in instructions
    assert instructions.endswith("…")
    assert payload["parameters"]["optimize_instructions"] is False


def test_qwen_http_payload_refits_structured_instruction_by_field_priority() -> None:
    engine = TTSEngine(model="qwen3-tts-instruct-flash", enable_cache=False, request_delay=0)
    text = "x" * 500

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text=text,
        voice_id="Cherry",
        voice_params={
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "voice_description": "性别：女性，年龄感：青年，音调：中低音，语速：中等，特点：吐字清晰、气息稳定，用途：有声书旁白。" * 4,
            "instruct_role": "全知叙述者",
            "instruct_scene": "密室揭示关键证据，所有人都屏住呼吸。",
            "instruct_emotion": "surprised",
            "performance_notes": "压低声音，新鲜的指纹前短停，结尾加重但不要喊。",
            "delivery_plan": {
                "pause_profile": "dramatic",
                "pause_strategy": "新鲜的指纹前短停",
                "stress_words": ["新鲜的指纹"],
                "director_guidance": "新鲜的指纹前短停，结尾保持克制。",
            },
        },
    )

    instructions = payload["parameters"]["instructions"]

    assert len(text) + len(instructions) <= QWEN_TTS_MAX_INPUT_CHARS - QWEN_TTS_INPUT_SAFETY_CHARS
    assert "surprised" in instructions
    assert "演绎要求：压低声音" in instructions
    assert "停顿策略：新鲜的指纹前短停" in instructions
    assert "重读词：新鲜的指纹" in instructions
    assert "声音描述：" not in instructions
    assert "旁白模板：" not in instructions


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


def test_qwen_http_payload_treats_provider_prompt_snapshot_as_audit_only() -> None:
    engine = TTSEngine(model="qwen3-tts-instruct-flash", enable_cache=False, request_delay=0)

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text="她终于停下。",
        voice_id="Neil",
        voice_params={
            "speaker": "Neil",
            "instructions": "语速缓慢，保持克制",
            "provider_prompt_snapshot": {
                "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION,
                "model": "qwen3-tts-instruct-flash",
                "voice_id": "Neil",
                "provider_prompt": {
                    "instructions": "Use an elderly male voice and permanent HUSKY VOICE",
                }
            },
        },
    )

    instructions = payload["parameters"]["instructions"]
    assert instructions.startswith("音色约束：保持已选音色")
    assert "语速缓慢，保持克制" in instructions
    assert "elderly male voice" not in instructions.lower()
    assert "husky voice" not in instructions.lower()


def test_qwen_http_payload_rebuilds_stale_provider_prompt_snapshot_instruction() -> None:
    engine = TTSEngine(model="qwen3-tts-instruct-flash", enable_cache=False, request_delay=0)

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text="她终于停下。",
        voice_id="Neil",
        voice_params={
            "instructions": "按当前合同重新构建",
            "provider_prompt_snapshot": {
                "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION - 1,
                "provider_prompt": {
                    "instructions": "旧策略快照",
                },
            },
        },
    )

    instructions = payload["parameters"]["instructions"]
    assert instructions.startswith("音色约束：保持已选音色")
    assert "按当前合同重新构建" in instructions
    assert "旧策略快照" not in instructions


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
    assert parameters["rate"] == 1.0
    assert "pitch" not in parameters
    assert parameters["enable_ssml"] is True
    assert parameters["word_timestamp_enabled"] is True
    assert parameters["phoneme_timestamp_enabled"] is True
    assert parameters["seed"] == 42
    assert parameters["language_hints"] == ["zh", "en", "ja", "ko", "fr"]
    assert parameters["instruction"].startswith("原音色不变;仅表演；")
    assert "温柔但坚定" in parameters["instruction"]
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


def test_cosyvoice_websocket_parameters_include_explicit_pause_controls() -> None:
    engine = TTSEngine(model="cosyvoice-v3.5-plus", enable_cache=False, request_delay=0)

    parameters = engine._build_cosyvoice_websocket_parameters(
        text="她停在门前，没有立刻回答。",
        voice="cosyvoice-v3.5-plus-demo",
        voice_params={
            "pause_before": 0.25,
            "pause_after": 0.75,
        },
    )

    assert parameters["pause_before"] == 0.25
    assert parameters["pause_after"] == 0.75


def test_cosyvoice_websocket_parameters_map_dramatic_delivery_plan_to_pause_after() -> None:
    engine = TTSEngine(model="cosyvoice-v3.5-plus", enable_cache=False, request_delay=0)

    parameters = engine._build_cosyvoice_websocket_parameters(
        text="她终于明白，那扇门后什么都没有。",
        voice="cosyvoice-v3.5-plus-demo",
        voice_params={
            "delivery_plan": {
                "pause_profile": "dramatic",
                "pause_strategy": "句尾留白",
            },
        },
    )

    assert parameters["pause_after"] == 0.8
    assert "pause_before" not in parameters


def test_cosyvoice_uses_mixer_for_chapter_boundary_pause_without_duplicate_provider_pause() -> None:
    engine = TTSEngine(model="cosyvoice-v3.5-plus", enable_cache=False, request_delay=0)

    parameters = engine._build_cosyvoice_websocket_parameters(
        text="她终于明白，那扇门后什么都没有。",
        voice="cosyvoice-v3.5-plus-demo",
        voice_params={
            "timeline_boundary_managed": True,
            "pause_before": 0.25,
            "pause_after": 0.75,
            "delivery_plan": {"pause_profile": "dramatic"},
        },
    )

    assert "pause_before" not in parameters
    assert "pause_after" not in parameters


def test_cosyvoice_instruction_prioritizes_performance_cues_within_provider_limit() -> None:
    engine = TTSEngine(model="cosyvoice-v3.5-plus", enable_cache=False, request_delay=0)

    parameters = engine._build_cosyvoice_websocket_parameters(
        text="盒盖打开的一瞬间，所有人的呼吸都停住了。里面没有钥匙，只有一枚新鲜的指纹。",
        voice="cosyvoice-v3.5-plus-demo",
        voice_params={
            "voice_description": (
                "性别：女性，年龄感：青年，音调：中低音，语速：中等，"
                "情绪：冷静克制，特点：吐字清晰、气息稳定，用途：有声书旁白"
            ),
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "instruct_role": "全知叙述者",
            "instruct_scene": "密室揭示关键证据",
            "instruct_emotion": "surprised",
            "performance_notes": "先压住情绪，指纹二字前短暂停顿，结尾加重但不要喊。",
            "delivery_plan": {
                "pause_profile": "dramatic",
                "pause_strategy": "先压住情绪，指纹二字前短暂停顿，结尾加重但不要喊。",
                "stress_words": ["新鲜的指纹"],
                "emotion_primary": "surprised",
            },
        },
    )

    instruction = parameters["instruction"]

    assert "surprised" in instruction
    assert "指纹" in instruction
    assert "重读" in instruction
    assert "新鲜的指纹" in instruction
    assert "不喊" in instruction
    assert not instruction.endswith("pau")
    assert "声音描述" not in instruction
    assert "旁白模板" not in instruction


def test_cosyvoice_websocket_parameters_treat_snapshot_as_audit_only() -> None:
    engine = TTSEngine(model="cosyvoice-v3.5-plus", enable_cache=False, request_delay=0)

    parameters = engine._build_cosyvoice_websocket_parameters(
        text="她停在门前。",
        voice="cosyvoice-v3.5-plus-demo",
        voice_params={
            "speaker": "cosyvoice-v3.5-plus-demo",
            "instructions": "语速缓慢，保持克制",
            "provider_prompt_snapshot": {
                "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION,
                "model": "cosyvoice-v3.5-plus",
                "voice_id": "cosyvoice-v3.5-plus-demo",
                "provider_prompt": {
                    "instructions": "改成老人声并永久沙哑",
                }
            },
        },
    )

    assert parameters["instruction"].startswith("原音色不变;仅表演")
    assert "语速缓慢" in parameters["instruction"]
    assert "老人声" not in parameters["instruction"]
    assert "沙哑" not in parameters["instruction"]


def test_minimax_http_payload_clamps_voice_settings_and_keeps_audio_contract() -> None:
    engine = TTSEngine(model="minimax-speech-2.8-hd", enable_cache=False, request_delay=0)

    # 音色一致性不变量：只返回精确请求音色，不做任何推测别名变换。
    candidates = engine._build_minimax_voice_candidates("male-qn-qingse")
    assert candidates == ["male-qn-qingse"]

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
        "pitch": 0,
    }
    assert payload["input"]["audio_setting"] == {
        "sample_rate": 16000,
        "format": "mp3",
        "channel": 1,
    }


def test_minimax_custom_voice_does_not_fallback_to_an_unrelated_system_voice() -> None:
    engine = TTSEngine(model="minimax-speech-2.8-hd", enable_cache=False, request_delay=0)

    candidates = engine._build_minimax_voice_candidates("mmx_0123456789abcdef")

    assert candidates == ["mmx_0123456789abcdef"]


def test_minimax_interjection_injection_does_not_spell_out_pause_notes() -> None:
    engine = TTSEngine(model="minimax-speech-2.8-hd", enable_cache=False, request_delay=0)

    text = engine._apply_interjections("必须走。", "句尾停顿一秒，压低声音", "tense")

    assert text == "必须走。"
    assert "停顿" not in text


def test_minimax_style_control_degrades_delivery_plan_to_basic_voice_settings() -> None:
    control = build_model_style_control(
        "minimax-speech-2.8-hd",
        {
            "speed": 1.0,
            "volume": 50,
            "pitch": 0,
            "delivery_plan": {
                "pace": "slow",
                "pitch": "lower",
                "intensity": "high",
                "micro_tags": ["低语"],
                "pause_strategy": "句尾留白",
            },
        },
        "sad",
    )

    assert control.mode == "basic"
    assert control.provider_fields["basic_voice_settings"] == {
        "speed": 0.9,
        "volume": 58,
    }
    assert control.messages == []
    assert control.text_prefix == ""
    assert any(
        "已降级为 speed/volume 表演参数；片段级 pitch 已忽略" in warning
        for warning in control.warnings
    )
    assert any("micro_tags" in warning and "pause_strategy" in warning for warning in control.warnings)


def test_minimax_http_payload_applies_basic_delivery_plan_settings() -> None:
    engine = TTSEngine(model="minimax-speech-2.8-hd", enable_cache=False, request_delay=0)

    payload = engine._build_minimax_http_payload(
        model="MiniMax/speech-2.8-hd",
        text="别回头，继续往前走。",
        voice="male-qn-qingse",
        voice_params={
            "speed": 1.0,
            "volume": 50,
            "pitch": 0,
            "delivery_plan": {
                "pace": "slow",
                "pitch": "lower",
                "intensity": "high",
                "micro_tags": ["低语"],
                "pause_strategy": "句尾留白",
            },
        },
    )

    assert payload["input"]["text"] == "别回头，继续往前走。"
    assert payload["input"]["voice_setting"] == {
        "voice_id": "male-qn-qingse",
        "speed": 0.9,
        "vol": 0.58,
        "pitch": 0,
    }


def test_minimax_style_control_uses_basic_mode_without_natural_language_fields() -> None:
    control = build_model_style_control(
        "minimax-speech-2.8-hd",
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_role": "长期压抑情绪的继承人",
            "performance_notes": "压低声音，语速偏慢，句尾留白。",
            "style_control_method": "audio_tags",
        },
        "sad",
    )

    assert control.mode == "basic"
    assert control.provider_fields == {}
    assert control.messages == []
    assert control.text_prefix == ""
    assert prepare_text_for_style_control("我撑不住了。", control) == "我撑不住了。"


def test_model_style_control_adapts_same_context_for_qwen_and_mimo() -> None:
    voice_params = {
        "segment_speaker": "岑霜",
        "segment_type": "dialogue",
        "instruct_role": "百年门阀岑家的现任大当家",
        "instruct_scene": "祠堂阴影里，她要用冷硬阶级壁垒逼退对方。",
        "instruct_emotion": "压抑的愤怒",
        "performance_notes": "语速极慢，句间留长停顿，在“真心”尾音加入轻微气音。",
    }

    qwen_control = build_model_style_control("qwen3-tts-instruct-flash", voice_params, "neutral")
    mimo_control = build_model_style_control("mimo-v2.5-tts", voice_params, "neutral")

    assert qwen_control.mode == "natural_language"
    qwen_instruction = qwen_control.provider_fields["instructions"]
    assert qwen_instruction.startswith("音色约束：保持已选音色")
    assert qwen_instruction.index("音色约束：") < qwen_instruction.index("说话角色：岑霜")
    assert "角色设定：百年门阀岑家的现任大当家" in qwen_instruction
    assert "指导：" not in qwen_instruction
    assert qwen_control.text_prefix == ""

    assert mimo_control.mode == "mimo_director"
    assert len(mimo_control.messages) == 1
    assert mimo_control.messages[0]["role"] == "user"
    mimo_prompt = mimo_control.messages[0]["content"]
    assert mimo_prompt.startswith("角色：百年门阀岑家的现任大当家\n")
    assert "场景：祠堂阴影里，她要用冷硬阶级壁垒逼退对方" in mimo_prompt
    assert "指导：音色约束：保持已选音色" in mimo_prompt
    assert "压抑的愤怒" in mimo_prompt
    assert "语速极慢，句间留长停顿，在“真心”尾音加入轻微气音" in mimo_prompt
    assert "声音描述：" not in mimo_prompt
    assert mimo_control.provider_fields == {"style_control_mode": "natural_language"}
    assert mimo_control.text_prefix == ""


def test_stepaudio_style_control_uses_global_context_instruction() -> None:
    control = build_model_style_control(
        STEPAUDIO_25_TTS_MODEL,
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_role": "百年门阀岑家的现任大当家",
            "instruct_scene": "祠堂阴影里，她要用冷硬阶级壁垒逼退对方。",
            "instruct_emotion": "克制的悲伤，不哭腔，轻轻发颤",
            "performance_notes": "语速极慢，句间留长停顿，在“真心”尾音加轻微气音。",
        },
        "neutral",
    )

    assert control.mode == "stepaudio_global_context"
    assert control.messages == []
    assert control.text_prefix == ""
    assert control.provider_fields["style_control_mode"] == "global_context"
    assert "说话角色：岑霜" in control.provider_fields["instruction"]
    assert "角色设定：百年门阀岑家的现任大当家" in control.provider_fields["instruction"]
    assert "情绪目标：克制的悲伤，不哭腔，轻轻发颤" in control.provider_fields["instruction"]


def test_stepaudio_style_control_renders_pause_and_micro_tags_as_inline_parentheses() -> None:
    control = build_model_style_control(
        STEPAUDIO_25_TTS_MODEL,
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_emotion": "紧张",
            "delivery_plan": {
                "pause_profile": "dramatic",
                "pause_strategy": "句尾留白",
                "micro_tags": ["低语"],
                "emotion_mix": ["紧张"],
            },
        },
        "neutral",
    )

    assert control.mode == "stepaudio_global_context"
    assert control.text_prefix == "（停顿0.8秒）（低语）（紧张）"
    assert prepare_text_for_style_control("别回头。", control) == "（停顿0.8秒）（低语）（紧张）别回头。"


def test_stepaudio_style_control_preserves_key_cues_within_instruction_budget() -> None:
    control = build_model_style_control(
        STEPAUDIO_25_TTS_MODEL,
        {
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "voice_description": "性别：女性，年龄感：青年，音调：中低音，语速：中等，情绪：冷静克制，特点：吐字清晰、气息稳定，用途：有声书旁白。" * 6,
            "instruct_role": "全知叙述者",
            "instruct_scene": "密室揭示关键证据，所有人都屏住呼吸。",
            "instruct_emotion": "surprised",
            "performance_notes": "压低声音，新鲜的指纹前短停，结尾加重但不要喊。",
            "delivery_plan": {
                "pause_profile": "dramatic",
                "pause_strategy": "新鲜的指纹前短停",
                "micro_tags": ["低语"],
                "emotion_mix": ["压抑"],
                "stress_words": ["新鲜的指纹"],
                "director_guidance": "新鲜的指纹前短停，结尾保持克制。",
            },
        },
        "neutral",
    )

    instruction = control.provider_fields["instruction"]

    assert len(instruction) <= 200
    assert "surprised" in instruction
    assert "演绎要求：压低声音" in instruction
    assert "停顿策略：新鲜的指纹前短停" in instruction
    assert "重读词：新鲜的指纹" in instruction
    assert "声音描述：" not in instruction
    assert control.text_prefix == "（停顿0.8秒）（低语）（压抑）"


def test_seed_tts_style_control_uses_query_response_context_texts() -> None:
    control = build_model_style_control(
        SEED_TTS_20_EXPRESSIVE_MODEL,
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_role": "长期压抑情绪的继承人",
            "instruct_scene": "雨夜，她终于说出真相。",
            "instruct_emotion": "带着哽咽的笑意",
            "performance_notes": "语速偏慢，句尾轻微气声。",
        },
        "sad",
    )

    assert control.mode == "doubao_query_response"
    assert control.messages == []
    assert control.text_prefix == ""
    assert control.provider_fields["style_control_mode"] == "query_response"
    assert "context_texts" in control.provider_fields
    assert "说话角色：岑霜" in control.provider_fields["context_texts"][0]
    assert "情绪目标：带着哽咽的笑意" in control.provider_fields["context_texts"][0]
    context_text = control.provider_fields["context_texts"][0]
    assert context_text.startswith("音色约束：保持已选音色")
    assert "演绎要求：语速偏慢，句尾轻微气声" in context_text
    assert "声音描述：" not in context_text


@pytest.mark.parametrize(
    ("model", "prompt_field"),
    [
        ("qwen3-tts-instruct-flash", "instructions"),
        ("cosyvoice-v3.5-plus", "instructions"),
        (STEPAUDIO_25_TTS_MODEL, "instruction"),
        (SEED_TTS_20_EXPRESSIVE_MODEL, "context_texts"),
    ],
)
def test_fixed_voice_provider_prompts_preserve_identity_during_temporary_texture(
    model: str,
    prompt_field: str,
) -> None:
    control = build_model_style_control(
        model,
        {
            "speaker": "selected-voice",
            "segment_speaker": "陆衍",
            "segment_type": "dialogue",
            "performance_notes": "生病后声音明显沙哑、虚弱，句尾带气声。",
        },
        "sad",
    )

    raw_prompt = control.provider_fields[prompt_field]
    prompt = raw_prompt[0] if isinstance(raw_prompt, list) else raw_prompt

    if model == "cosyvoice-v3.5-plus":
        assert prompt.startswith("原音色不变;仅表演")
    else:
        assert "已选音色" in prompt
        assert "身份" in prompt
        assert "年龄" in prompt
        assert "声线" in prompt
        assert "辨识度" in prompt
    assert "表演" in prompt
    assert "沙哑" in prompt
    assert "气声" in prompt
    assert "轻度" in prompt
    assert "原音色" in prompt or "原声" in prompt


def test_fixed_voice_identity_constraint_survives_long_explicit_instruction_budget() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Neil",
            "instructions": "用户表演要求" * 120,
        },
        "neutral",
    )

    instruction = control.provider_fields["instructions"]

    assert instruction.startswith("音色约束：保持已选音色")
    assert len(instruction) <= 600


def test_mimo_director_locks_selected_voice_but_voice_design_remains_unrestricted() -> None:
    fixed_voice_control = build_model_style_control(
        MIMO_V25_TTS_MODEL,
        {
            "speaker": "Chloe",
            "segment_speaker": "陆衍",
            "segment_type": "dialogue",
            "performance_notes": "重伤后声音沙哑、虚弱，句尾带气声。",
        },
        "sad",
    )
    voice_design_control = build_model_style_control(
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        {
            "voice_description": "设计为苍老沙哑的男性声线，气息虚弱。",
            "performance_notes": "语速缓慢。",
        },
        "sad",
    )

    director_prompt = fixed_voice_control.messages[0]["content"]
    design_prompt = voice_design_control.messages[0]["content"]

    assert "保持已选音色" in director_prompt
    assert "说话人身份" in director_prompt
    assert "年龄感" in director_prompt
    assert "基础声线" in director_prompt
    assert "辨识度" in director_prompt
    assert "只在原音色基础上调整当前片段表演" in director_prompt
    assert "沙哑、气声" in director_prompt
    assert "因重伤，仅在原音色基础上轻微、短暂表现沙哑" in director_prompt
    assert "轻度" in director_prompt
    assert "保持已选音色" not in design_prompt
    assert "苍老沙哑的男性声线" in design_prompt


def test_mimo_label_control_prefixes_text_without_polluting_other_models() -> None:
    voice_params = {
        "style_control_method": "audio_tags",
        "style_tags": ["紧张", "深呼吸"],
        "inline_audio_tags": ["小声"],
    }

    mimo_control = build_model_style_control("mimo-v2.5-tts", voice_params, "fearful")
    qwen_control = build_model_style_control("qwen3-tts-instruct-flash", voice_params, "fearful")

    assert mimo_control.mode == "mimo_audio_tags"
    assert len(mimo_control.messages) == 1
    assert mimo_control.messages[0]["role"] == "user"
    assert mimo_control.messages[0]["content"].startswith("音色约束：保持已选音色")
    assert mimo_control.text_prefix == "（紧张，深呼吸）[小声]"
    assert prepare_text_for_style_control("别停下。", mimo_control) == "（紧张，深呼吸）[小声]别停下。"
    assert qwen_control.text_prefix == ""
    assert prepare_text_for_style_control("别停下。", qwen_control) == "别停下。"


def test_mimo_audio_tags_filter_identity_changes_and_prefix_identity_constraint() -> None:
    control = build_model_style_control(
        MIMO_V25_TTS_MODEL,
        {
            "speaker": "Chloe",
            "style_control_method": "audio_tags",
            "style_tags": ["紧张", "少女音", "沙哑"],
            "inline_audio_tags": ["小声", "变声"],
            "performance_notes": "生病后轻微沙哑，但保持原本身份。",
        },
        "fearful",
    )

    assert control.mode == "mimo_audio_tags"
    assert control.messages[0]["role"] == "user"
    assert control.messages[0]["content"].startswith("音色约束：保持已选音色")
    assert "（紧张）" in control.text_prefix
    assert "[小声]" in control.text_prefix
    assert "少女音" not in control.text_prefix
    assert "变声" not in control.text_prefix
    assert "[沙哑]" not in control.text_prefix
    assert any(
        "少女音" in warning and "沙哑" in warning and "变声" in warning
        for warning in control.warnings
    )


def test_mimo_audio_tags_payload_places_identity_constraint_before_safe_tags() -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_mimo_chat_payload(
        model=MIMO_V25_TTS_MODEL,
        text="别停下。",
        voice="Chloe",
        voice_params={
            "style_control_method": "audio_tags",
            "style_tags": ["紧张", "童声"],
            "inline_audio_tags": ["低语"],
        },
    )

    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][0]["content"].startswith("音色约束：保持已选音色")
    assert payload["messages"][1] == {
        "role": "assistant",
        "content": "（紧张）[低语]别停下。",
    }
    assert "童声" not in json.dumps(payload["messages"], ensure_ascii=False)


def test_inline_tag_strategy_audits_mimo_and_doubao_tag_placement() -> None:
    voice_params = {
        "style_control_method": "audio_tags",
        "style_tags": ["紧张", "紧张"],
        "inline_audio_tags": ["低语"],
        "delivery_plan": {
            "emotion_primary": "fearful",
            "emotion_mix": ["压抑"],
            "micro_tags": ["吸气", "低语"],
        },
    }

    mimo_control = build_model_style_control("mimo-v2.5-tts", voice_params, "fearful")
    doubao_control = build_model_style_control(SEED_TTS_20_EXPRESSIVE_MODEL, voice_params, "fearful")

    assert mimo_control.text_prefix == "（紧张）[低语][吸气]"
    assert mimo_control.provider_fields["inline_tag_strategy"] == {
        "model_family": "mimo",
        "placement": "assistant_prefix",
        "style_tags": ["紧张"],
        "inline_tags": ["低语", "吸气"],
        "use_tag_parser": False,
    }

    assert doubao_control.text_prefix == "[低语，吸气]"
    assert doubao_control.provider_fields["inline_tag_strategy"] == {
        "model_family": "doubao",
        "placement": "text_prefix",
        "style_tags": ["紧张"],
        "inline_tags": ["低语", "吸气"],
        "use_tag_parser": True,
    }


def test_doubao_inline_tag_strategy_preserves_style_fallback_with_delivery_plan_tags() -> None:
    control = build_model_style_control(
        SEED_TTS_20_EXPRESSIVE_MODEL,
        {
            "style_control_method": "labels",
            "style_tags": ["旁白"],
            "delivery_plan": {
                "emotion_primary": "fearful",
                "emotion_mix": ["压抑"],
            },
        },
        "fearful",
    )

    assert control.text_prefix == "[旁白，fearful，压抑]"
    assert control.provider_fields["inline_tag_strategy"] == {
        "model_family": "doubao",
        "placement": "text_prefix",
        "style_tags": ["旁白", "fearful", "压抑"],
        "inline_tags": [],
        "use_tag_parser": True,
    }


def test_mimo_style_control_recognizes_registered_model_aliases() -> None:
    control = build_model_style_control(
        "MiMo/V2.5-TTS-VoiceDesign",
        {
            "segment_speaker": "岑霜",
            "instruct_role": "冷静克制的继承人",
            "performance_notes": "语速偏慢，句尾轻微气声。",
        },
        "calm",
    )

    assert control.mode == "mimo_voice_design"
    assert control.provider_fields == {"style_control_mode": "voice_design"}
    assert control.messages[0]["role"] == "user"
    assert "冷静克制的继承人" in control.messages[0]["content"]
    assert "语速偏慢，句尾轻微气声。" in control.messages[0]["content"]
    assert control.text_prefix == ""


def test_mimo_voice_design_ignores_audio_tags_as_standalone_control() -> None:
    control = build_model_style_control(
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        {
            "style_control_method": "audio_tags",
            "style_tags": ["紧张"],
            "inline_audio_tags": ["小声"],
            "voice_description": "青年女性，中音偏低，语速偏慢，声线清晰。",
            "instructions": "句尾轻微气声，整体克制。",
        },
        "fearful",
    )

    assert control.mode == "mimo_voice_design"
    assert control.provider_fields == {"style_control_mode": "voice_design"}
    assert control.messages[0]["role"] == "user"
    assert "青年女性，中音偏低，语速偏慢，声线清晰。" in control.messages[0]["content"]
    assert "句尾轻微气声，整体克制。" in control.messages[0]["content"]
    assert control.text_prefix == ""
    assert "[小声]" not in control.messages[0]["content"]


def test_mimo_chat_payload_places_natural_language_control_in_user_message() -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_mimo_chat_payload(
        model=MIMO_V25_TTS_MODEL,
        text="你所谓的真心，太廉价了。",
        voice="Chloe",
        voice_params={
            "segment_speaker": "岑霜",
            "instruct_role": "冷硬疏离的世家掌权人",
            "instruct_scene": "祠堂里，对方试图带她逃离家族。",
            "instruct_emotion": "温柔但疲惫",
            "performance_notes": "语速极慢，实音偏重，句末轻微气音。",
        },
    )

    assert payload["model"] == MIMO_V25_TTS_MODEL
    assert payload["messages"][0]["role"] == "user"
    director_prompt = payload["messages"][0]["content"]
    assert director_prompt.startswith("角色：冷硬疏离的世家掌权人\n")
    assert "场景：祠堂里，对方试图带她逃离家族" in director_prompt
    assert "指导：音色约束：保持已选音色" in director_prompt
    assert "温柔但疲惫" in director_prompt
    assert "语速极慢，实音偏重，句末轻微气音" in director_prompt
    assert payload["messages"][1] == {"role": "assistant", "content": "你所谓的真心，太廉价了。"}
    assert payload["audio"] == {"voice": "Chloe", "format": "wav"}


def test_stepaudio_http_payload_uses_instruction_and_keeps_inline_context() -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)
    text = "她停下脚步。（压低声音，克制但发颤）你真的想清楚了吗？"

    payload = engine._build_stepaudio_http_payload(
        model=STEPAUDIO_25_TTS_MODEL,
        text=text,
        voice="cixingnansheng",
        voice_params={
            "segment_speaker": "岑霜",
            "instruct_emotion": "克制的悲伤，不哭腔，轻轻发颤",
            "performance_notes": "语速偏慢，停顿更长。",
            "voice_label": "不能传给 StepAudio 2.5 TTS",
        },
    )

    assert payload["model"] == STEPAUDIO_25_TTS_MODEL
    assert payload["voice"] == "cixingnansheng"
    assert payload["input"] == text
    assert "instruction" in payload
    assert "voice_label" not in payload
    assert "克制的悲伤" in payload["instruction"]
    assert "语速偏慢" in payload["instruction"]


def test_stepaudio_http_payload_prefixes_delivery_plan_inline_context() -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_stepaudio_http_payload(
        model=STEPAUDIO_25_TTS_MODEL,
        text="别回头。",
        voice="cixingnansheng",
        voice_params={
            "delivery_plan": {
                "pause_profile": "dramatic",
                "micro_tags": ["低语"],
                "emotion_mix": ["紧张"],
            },
        },
    )

    assert payload["input"] == "（停顿0.8秒）（低语）（紧张）别回头。"


def test_seed_tts_http_payload_uses_context_texts_and_audio_params() -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_seed_tts_http_payload(
        model=SEED_TTS_20_EXPRESSIVE_MODEL,
        text="你真的想清楚了吗？",
        voice="zh_female_vv_uranus_bigtts",
        voice_params={
            "speed": 1.2,
            "volume": 50,
            "pitch": 50,
            "sample_rate": 24000,
            "format": "mp3",
            "segment_speaker": "岑霜",
            "instruct_emotion": "温柔但疲惫",
            "performance_notes": "语速偏慢，停顿更长。",
        },
    )

    assert payload["user"]["uid"] == "audiobook"
    assert "audio_params" not in payload
    assert payload["req_params"]["speaker"] == "zh_female_vv_uranus_bigtts"
    assert payload["req_params"]["audio_params"] == {
        "format": "mp3",
        "sample_rate": 24000,
        "speech_rate": 0,
        "loudness_rate": 0,
    }
    assert payload["req_params"]["model"] == SEED_TTS_20_EXPRESSIVE_MODEL
    assert payload["req_params"]["text"] == "你真的想清楚了吗？"
    assert payload["req_params"]["text_type"] == "plain"
    assert payload["req_params"]["with_timestamp"] == 0
    additions = json.loads(payload["req_params"]["additions"])
    context_text = additions["context_texts"][0]
    assert context_text.startswith("音色约束：保持已选音色")
    assert "温柔但疲惫" in context_text
    assert "语速偏慢，停顿更长" in context_text
    assert "声音描述：" not in context_text


@pytest.mark.parametrize(
    "voice_params",
    [
        {"pitch": 0.9},
        {"pitch": 1.0},
        {"pitch": 50},
        {"pitch_semitones": -3, "pitch": 0.9},
        {"pitch_ratio": 2.0, "pitch": 50},
    ],
)
def test_seed_tts_http_payload_ignores_all_segment_pitch_controls(
    voice_params: dict[str, float],
) -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_seed_tts_http_payload(
        model=SEED_TTS_20_EXPRESSIVE_MODEL,
        text="保持原音色。",
        voice="zh_male_yuanboxiaoshu_uranus_bigtts",
        voice_params=voice_params,
    )

    additions = json.loads(payload["req_params"].get("additions", "{}"))
    assert "post_process" not in additions


def test_tts_cache_key_ignores_segment_pitch_contract_fields() -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)

    neutral_key = engine._generate_cache_key(
        "保持原音色。",
        {"speaker": "voice-a", "pitch_semitones": 0},
        "neutral",
    )
    lowered_key = engine._generate_cache_key(
        "保持原音色。",
        {"speaker": "voice-a", "pitch_semitones": -2},
        "neutral",
    )
    ratio_key = engine._generate_cache_key(
        "保持原音色。",
        {"speaker": "voice-a", "pitch_ratio": 0.9},
        "neutral",
    )

    assert neutral_key == lowered_key == ratio_key


def test_tts_cache_key_includes_voice_identity_policy_version(monkeypatch) -> None:
    from app.services.audiobook.tts_engine_pkg import _minimax_mixin

    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)
    base_key = engine._generate_cache_key(
        "保持原音色。",
        {"speaker": "voice-a", "performance_notes": "语速缓慢"},
        "neutral",
    )

    monkeypatch.setattr(
        _minimax_mixin,
        "VOICE_IDENTITY_POLICY_VERSION",
        _minimax_mixin.VOICE_IDENTITY_POLICY_VERSION + 1,
    )
    upgraded_key = engine._generate_cache_key(
        "保持原音色。",
        {"speaker": "voice-a", "performance_notes": "语速缓慢"},
        "neutral",
    )

    assert upgraded_key != base_key


def test_tts_cache_key_includes_structured_performance_contract() -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)
    slow_key = engine._generate_cache_key(
        "痛。",
        {
            "speaker": "voice-a",
            "delivery_plan": {
                "pace": "slow",
                "stress_words": ["痛"],
            },
        },
        "sad",
    )
    fast_key = engine._generate_cache_key(
        "痛。",
        {
            "speaker": "voice-a",
            "delivery_plan": {
                "pace": "fast",
                "stress_words": [],
            },
        },
        "sad",
    )

    assert slow_key != fast_key


def test_seed_tts_http_payload_supports_official_inline_voice_labels() -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_seed_tts_http_payload(
        model=SEED_TTS_20_EXPRESSIVE_MODEL,
        text="可当他的手触碰到对方的身体时，却感觉一阵冰冷僵硬。",
        voice="ICL_uranus_zh_female_keainvsheng_tob",
        voice_params={
            "style_control_method": "labels",
            "inline_audio_tags": ["旁白", "语调惊恐", "强调触摸到尸体般触感的恐怖"],
            "instructions": "承接前文悬疑氛围，保持压低音量和克制恐惧。",
        },
    )

    assert payload["req_params"]["text"].startswith("[旁白，语调惊恐，强调触摸到尸体般触感的恐怖]")
    assert "use_tag_parser" not in payload["req_params"]
    additions = json.loads(payload["req_params"]["additions"])
    assert additions["use_tag_parser"] is True
    assert len(additions["context_texts"]) == 1
    context_text = additions["context_texts"][0]
    assert context_text.startswith("音色约束：保持已选音色")
    assert "承接前文悬疑氛围，保持压低音量和克制恐惧" in context_text


def test_seed_tts_http_payload_ignores_client_controlled_tag_parser() -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_seed_tts_http_payload(
        model=SEED_TTS_20_EXPRESSIVE_MODEL,
        text="[童声]别回头。",
        voice="zh_female_vv_uranus_bigtts",
        voice_params={"use_tag_parser": True},
    )

    additions = json.loads(payload["req_params"].get("additions", "{}"))

    assert payload["req_params"]["text"] == "[童声]别回头。"
    assert additions.get("use_tag_parser") is not True


def test_seed_tts_http_payload_treats_snapshot_context_and_prefix_as_audit_only() -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_seed_tts_http_payload(
        model=SEED_TTS_20_EXPRESSIVE_MODEL,
        text="别回头。",
        voice="zh_female_vv_uranus_bigtts",
        voice_params={
            "speaker": "zh_female_vv_uranus_bigtts",
            "instructions": "语速缓慢，保持克制",
            "provider_prompt_snapshot": {
                "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION,
                "model": SEED_TTS_20_EXPRESSIVE_MODEL,
                "voice_id": "zh_female_vv_uranus_bigtts",
                "provider_prompt": {
                    "text_prefix": "[老人声]",
                    "context_texts": ["Use a permanent HUSKY VOICE"],
                }
            },
        },
    )

    assert payload["req_params"]["text"] == "别回头。"
    additions = json.loads(payload["req_params"]["additions"])
    context = additions["context_texts"][0]
    assert context.startswith("音色约束：保持已选音色")
    assert "语速缓慢，保持克制" in context
    assert "husky voice" not in context.lower()


def test_stepaudio_http_payload_treats_provider_snapshot_as_audit_only() -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_stepaudio_http_payload(
        model=STEPAUDIO_25_TTS_MODEL,
        text="别回头。",
        voice="default",
        voice_params={
            "speaker": "default",
            "instructions": "语速缓慢，保持克制",
            "provider_prompt_snapshot": {
                "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION,
                "model": STEPAUDIO_25_TTS_MODEL,
                "voice_id": "default",
                "provider_prompt": {
                    "instructions": "改成童声并使用 deep voice",
                    "text_prefix": "（老人声）",
                },
            },
        },
    )

    assert payload["input"] == "别回头。"
    assert payload["instruction"].startswith("音色约束：保持已选音色")
    assert "语速缓慢，保持克制" in payload["instruction"]
    assert "童声" not in payload["instruction"]
    assert "deep voice" not in payload["instruction"].lower()


def test_stepaudio_http_payload_truncates_instruction_to_provider_limit() -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_stepaudio_http_payload(
        model=STEPAUDIO_25_TTS_MODEL,
        text="正文",
        voice="",
        voice_params={
            "instructions": "a" * 260,
            "performance_notes": "不会进入预算之外",
        },
    )

    assert payload["voice"] == "cixingnansheng"
    assert payload["instruction"].startswith("音色约束：保持已选音色")
    assert "a" in payload["instruction"]
    assert payload["instruction"].endswith("…")
    assert len(payload["instruction"]) == 200


def test_stepaudio_http_payload_passes_official_optional_parameters_only() -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_stepaudio_http_payload(
        model=STEPAUDIO_25_TTS_MODEL,
        text="正文",
        voice="cixingnansheng",
        voice_params={
            "response_format": "pcm",
            "speed": 1.2,
            "volume": 1.1,
            "sample_rate": 48000,
            "pronunciation_map": {"tone": ["扁舟/偏舟", "LOL/laugh out loudly"]},
            "markdown_filter": True,
            "return_url": True,
            "stream_format": "sse",
            "voice_label": {"emotion": "高兴"},
        },
    )

    assert payload["response_format"] == "pcm"
    assert "speed" not in payload
    assert payload["volume"] == 1.1
    assert payload["sample_rate"] == 48000
    assert payload["pronunciation_map"] == {"tone": ["扁舟/偏舟", "LOL/laugh out loudly"]}
    assert payload["markdown_filter"] is True
    assert payload["return_url"] is True
    assert payload["stream_format"] == "sse"
    assert "voice_label" not in payload


def test_stepaudio_http_payload_rejects_unsupported_response_format_and_ui_volume() -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_stepaudio_http_payload(
        model=STEPAUDIO_25_TTS_MODEL,
        text="正文",
        voice="cixingnansheng",
        voice_params={
            "response_format": "aac",
            "volume": 50,
            "sample_rate": 44100,
            "stream_format": "chunked",
        },
    )

    assert "response_format" not in payload
    assert "volume" not in payload
    assert "sample_rate" not in payload
    assert "stream_format" not in payload


def test_stepaudio_http_call_uses_stepfun_speech_endpoint(monkeypatch) -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)
    expected_audio = b"fake-mp3"
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        content = expected_audio
        text = ""
        headers = {"content-type": "audio/mpeg"}

        def json(self):
            raise AssertionError("binary audio response should not be parsed as JSON")

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        engine._call_stepaudio_speech_http(
            model=STEPAUDIO_25_TTS_MODEL,
            api_key="unit-step-key",
            text="她停下脚步。（压低声音）你真的想清楚了吗？",
            voice="cixingnansheng",
            voice_params={"instructions": "语气克制，语速偏慢"},
        )
    )

    assert result == expected_audio
    assert captured["url"] == "https://api.stepfun.com/v1/audio/speech"
    assert captured["headers"] == {
        "Authorization": "Bearer unit-step-key",
        "Content-Type": "application/json",
    }
    assert captured["json"]["model"] == STEPAUDIO_25_TTS_MODEL
    assert captured["json"]["voice"] == "cixingnansheng"
    assert captured["json"]["input"] == "她停下脚步。（压低声音）你真的想清楚了吗？"
    instruction = captured["json"]["instruction"]
    assert instruction.startswith("音色约束：保持已选音色")
    assert instruction.endswith("语气克制，语速偏慢")
    assert captured["json"] == {
        "model": STEPAUDIO_25_TTS_MODEL,
        "voice": "cixingnansheng",
        "input": "她停下脚步。（压低声音）你真的想清楚了吗？",
        "instruction": instruction,
    }
    metadata = engine.get_last_synthesis_metadata()
    assert metadata["provider"] == "stepfun"
    assert metadata["endpoint"] == "/audio/speech"
    assert metadata["instruction"] == instruction


def test_seed_tts_http_call_uses_volcengine_v3_endpoint(monkeypatch) -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)
    expected_audio = b"fake-seed-mp3"
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        content = b""
        text = ""
        headers = {"content-type": "application/json"}

        def json(self):
            return {"audio": base64.b64encode(expected_audio).decode("ascii")}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        engine._call_seed_tts_http(
            model=SEED_TTS_20_EXPRESSIVE_MODEL,
            api_key="unit-seed-key",
            text="她终于笑了。",
            voice="zh_female_cancan_uranus_bigtts",
            voice_params={
                "instructions": "带着哽咽的笑意，语速偏慢。",
                "response_format": "mp3",
            },
            resource_id="seed-tts-2.0",
        )
    )

    assert result == expected_audio
    assert captured["url"] == "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
    assert captured["headers"] == {
        "X-Api-App-Key": "unit-seed-key",
        "X-Api-Key": "unit-seed-key",
        "X-Api-Resource-Id": "seed-tts-2.0",
        "Content-Type": "application/json",
    }
    assert "audio_params" not in captured["json"]
    assert captured["json"]["req_params"]["speaker"] == "zh_female_cancan_uranus_bigtts"
    assert captured["json"]["req_params"]["audio_params"]["format"] == "mp3"
    assert captured["json"]["req_params"]["model"] == SEED_TTS_20_EXPRESSIVE_MODEL
    assert captured["json"]["req_params"]["text"] == "她终于笑了。"
    context_texts = json.loads(captured["json"]["req_params"]["additions"])["context_texts"]
    assert len(context_texts) == 1
    assert context_texts[0].startswith("音色约束：保持已选音色")
    assert "带着哽咽的笑意，语速偏慢" in context_texts[0]
    metadata = engine.get_last_synthesis_metadata()
    assert metadata["provider"] == "volcengine"
    assert metadata["endpoint"] == "/api/v3/tts/unidirectional"
    assert metadata["resource_id"] == "seed-tts-2.0"
    assert metadata["style_control"] == "query_response"


def test_seed_tts_synthesis_falls_back_to_http_when_websocket_returns_no_audio(monkeypatch) -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)
    calls: list[str] = []

    async def fake_websocket(**_kwargs):
        calls.append("websocket")
        raise RuntimeError("Seed-TTS WebSocket returned no audio data")

    async def fake_http(**kwargs):
        calls.append("http")
        assert kwargs["model"] == SEED_TTS_20_EXPRESSIVE_MODEL
        assert kwargs["text"] == "她终于笑了。"
        assert kwargs["voice"] == "zh_female_vv_uranus_bigtts"
        assert kwargs["resource_id"] == "seed-tts-2.0"
        return b"seed-http-audio"

    monkeypatch.setattr(engine, "_call_seed_tts_websocket", fake_websocket)
    monkeypatch.setattr(engine, "_call_seed_tts_http", fake_http)

    result = asyncio.run(
        engine._synthesize_seed_tts(
            text="她终于笑了。",
            voice_params={"speaker": "zh_female_vv_uranus_bigtts"},
            provider_model=SEED_TTS_20_EXPRESSIVE_MODEL,
            api_key="unit-seed-key",
            resource_id="seed-tts-2.0",
            raw_speaker_id="zh_female_vv_uranus_bigtts",
        )
    )

    assert result == b"seed-http-audio"
    assert calls == ["websocket", "http"]


def test_seed_tts_websocket_sends_finish_session_before_awaiting_session_finished(monkeypatch) -> None:
    """按双向流协议时序，FinishSession 必须在收流前发送：服务端收到 FinishSession
    后才会返回 SessionFinished。若等接收循环超时后才发，每段合成都会白等超时，
    且超时后到达的尾部音频会被丢弃（尾音截断）。"""
    scripts_dir = ROOT_DIR.parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import protocols
    import websockets

    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)
    monkeypatch.setenv("SEED_TTS_WS_RECEIVE_TIMEOUT", "0.5")

    E = protocols.EventType
    M = protocols.MsgType
    F = protocols.MsgTypeFlagBits

    class FakeSeedServer:
        """模拟真实服务端：收到 FinishSession 前不发 SessionFinished，
        且最后一块音频在 FinishSession 之后才推送。"""

        def __init__(self) -> None:
            self.response = SimpleNamespace(headers={})
            self.events: list[int] = []
            self.task_request_payload = None
            self._queue: asyncio.Queue = asyncio.Queue()

        def _reply(self, msg) -> None:
            self._queue.put_nowait(msg.marshal())

        async def send(self, data) -> None:
            msg = protocols.Message.from_bytes(data)
            self.events.append(int(msg.event))
            if msg.event == E.StartConnection:
                self._reply(protocols.Message(type=M.FullServerResponse, flag=F.WithEvent, event=E.ConnectionStarted))
            elif msg.event == E.StartSession:
                self._reply(
                    protocols.Message(
                        type=M.FullServerResponse, flag=F.WithEvent, event=E.SessionStarted, session_id=msg.session_id
                    )
                )
            elif msg.event == E.TaskRequest:
                self.task_request_payload = json.loads(msg.payload.decode("utf-8"))
                self._reply(protocols.Message(type=M.AudioOnlyServer, payload=b"seed-head"))
            elif msg.event == E.FinishSession:
                self._reply(protocols.Message(type=M.AudioOnlyServer, payload=b"-tail"))
                self._reply(
                    protocols.Message(
                        type=M.FullServerResponse, flag=F.WithEvent, event=E.SessionFinished, session_id=msg.session_id
                    )
                )
            elif msg.event == E.FinishConnection:
                self._reply(protocols.Message(type=M.FullServerResponse, flag=F.WithEvent, event=E.ConnectionFinished))

        async def recv(self):
            return await self._queue.get()

        async def close(self) -> None:
            return None

    fake_ws = FakeSeedServer()

    async def fake_connect(*_args, **_kwargs):
        return fake_ws

    monkeypatch.setattr(websockets, "connect", fake_connect)

    result = asyncio.run(
        engine._call_seed_tts_websocket(
            model=SEED_TTS_20_EXPRESSIVE_MODEL,
            api_key="unit-seed-key",
            text="[童声]她终于笑了。",
            voice="zh_female_vv_uranus_bigtts",
            voice_params={
                "use_tag_parser": True,
                "pitch": 0.8,
                "pitch_ratio": 0.8,
                "pitch_semitones": -4,
            },
            resource_id="seed-tts-2.0",
        )
    )

    assert result == b"seed-head-tail", "FinishSession 后到达的尾部音频不应被丢弃"
    task_req_params = fake_ws.task_request_payload["req_params"]
    task_additions = json.loads(task_req_params.get("additions", "{}"))
    assert task_req_params["text"] == "[童声]她终于笑了。"
    assert task_additions.get("use_tag_parser") is not True
    assert "post_process" not in task_additions
    finish_idx = fake_ws.events.index(int(E.FinishSession))
    # FinishSession 应紧随 TaskRequest 发送，而不是等接收循环超时后才补发
    assert fake_ws.events[finish_idx - 1] == int(E.TaskRequest)


def test_seed_tts_parser_decodes_text_plain_json_lines() -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)
    first = base64.b64encode(b"ID3-first").decode("ascii")
    second = base64.b64encode(b"-second").decode("ascii")

    class FakeResponse:
        headers = {"content-type": "text/plain; charset=utf-8"}
        content = (
            f'{{"code":0,"message":"","data":"{first}"}}\n'
            f'{{"code":0,"message":"","data":"{second}"}}\n'
            '{"code":0,"message":"","data":null,"sentence":{"text":"测试。"}}\n'
            '{"code":20000000,"message":"OK","data":null}\n'
        ).encode("utf-8")
        text = content.decode("utf-8")

        def json(self):
            raise json.JSONDecodeError("Extra data", self.text, len(self.text) // 2)

    parsed = asyncio.run(engine._parse_seed_tts_audio_response(FakeResponse(), client=None))

    assert parsed == b"ID3-first-second"


def test_seed_tts_synthesis_requires_dedicated_speech_api_key(monkeypatch) -> None:
    engine = TTSEngine(model=SEED_TTS_20_EXPRESSIVE_MODEL, enable_cache=False, request_delay=0)

    for env_name in SEED_TTS_API_KEY_ENV_NAMES:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("DOUBAO_API_KEY", "ark-api-key-is-not-speech-key")

    async def fail_if_called(**_kwargs):
        raise AssertionError("Seed-TTS should not use generic Doubao/Ark API keys")

    monkeypatch.setattr(engine, "_synthesize_seed_tts", fail_if_called)

    result = asyncio.run(
        engine._synthesize_aliyun(
            text="最小试听文本",
            voice_params={"speaker": "zh_female_vv_uranus_bigtts"},
            enable_cache=False,
        )
    )

    assert result is None


def test_stepaudio_http_call_allows_base_url_override(monkeypatch) -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)
    expected_audio = b"fake-mp3"
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        content = expected_audio
        text = ""
        headers = {"content-type": "audio/mpeg"}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setenv("STEPAUDIO_TTS_BASE_URL", "https://api.stepfun.example/v1")

    result = asyncio.run(
        engine._call_stepaudio_speech_http(
            model=STEPAUDIO_25_TTS_MODEL,
            api_key="unit-step-key",
            text="StepAudio endpoint override.",
            voice="cixingnansheng",
            voice_params={},
        )
    )

    assert result == expected_audio
    assert captured["url"] == "https://api.stepfun.example/v1/audio/speech"
    metadata = engine.get_last_synthesis_metadata()
    assert metadata["base_url"] == "https://api.stepfun.example/v1"
    assert metadata["endpoint"] == "/audio/speech"


def test_stepaudio_voice_preview_call_uses_official_preview_endpoint(monkeypatch) -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)
    expected_audio = b"fake-preview-mp3"
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        content = expected_audio
        text = ""
        headers = {"content-type": "audio/mpeg"}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        engine._call_stepaudio_voice_preview_http(
            model=STEPAUDIO_25_TTS_MODEL,
            api_key="unit-step-key",
            text="智能阶跃，十倍每一个人的可能",
            file_id="file-Ckyl3cV09A",
            sample_text="今天天气不错",
            instruction="语气温柔，语速偏慢",
        )
    )

    assert result == expected_audio
    assert captured["url"] == "https://api.stepfun.com/v1/audio/voices/preview"
    assert captured["headers"] == {
        "Authorization": "Bearer unit-step-key",
        "Content-Type": "application/json",
    }
    assert captured["json"] == {
        "model": STEPAUDIO_25_TTS_MODEL,
        "file_id": "file-Ckyl3cV09A",
        "text": "今天天气不错",
        "sample_text": "智能阶跃，十倍每一个人的可能",
        "instruction": "语气温柔，语速偏慢",
    }
    metadata = engine.get_last_synthesis_metadata()
    assert metadata["provider"] == "stepfun"
    assert metadata["endpoint"] == "/audio/voices/preview"
    assert metadata["file_id"] == "file-Ckyl3cV09A"


def test_stepaudio_voice_preview_accepts_sample_audio_json_response(monkeypatch) -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)

    class FakeResponse:
        status_code = 200
        content = b""
        text = ""
        headers = {"content-type": "application/json"}

        def json(self):
            return {
                "sample_text": "当你真的喜欢一个人的时候就容易说傻话办蠢事。",
                "sample_audio": "cHJldmlldy1hdWRpbw==",
            }

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        engine._call_stepaudio_voice_preview_http(
            model=STEPAUDIO_25_TTS_MODEL,
            api_key="unit-step-key",
            text="当你真的喜欢一个人的时候就容易说傻话办蠢事。",
            file_id="file-unit",
            sample_text="时间会缓和所有的悲伤。",
            instruction="",
        )
    )

    assert result == b"preview-audio"


def test_stepaudio_voice_preview_cer_error_is_user_actionable(monkeypatch) -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)

    class FakeResponse:
        status_code = 400
        content = b""
        headers = {"content-type": "application/json"}
        text = (
            '{"error":{"message":"validate result: CER_NOT_PASS, msg: cer is too high: 94.64%. '
            'asr_result is: real sample words, user_text is: wrong sample words","type":"input_invalid"}}'
        )

        def json(self):
            return {
                "error": {
                    "message": (
                        "validate result: CER_NOT_PASS, msg: cer is too high: 94.64%. "
                        "asr_result is: real sample words, user_text is: wrong sample words"
                    ),
                    "type": "input_invalid",
                }
            }

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(
            engine._call_stepaudio_voice_preview_http(
                model=STEPAUDIO_25_TTS_MODEL,
                api_key="unit-step-key",
                text="preview text",
                file_id="file-unit",
                sample_text="wrong sample words",
                instruction="",
            )
        )

    message = str(exc_info.value)
    assert "CER_NOT_PASS" in message
    assert "sample_text" in message
    assert "reference audio" in message
    assert "real sample words" in message
    assert "wrong sample words" in message


def test_stepaudio_clone_asset_synthesis_uses_voice_preview_when_file_id_exists(monkeypatch) -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)
    captured: dict[str, object] = {}

    async def fake_preview(**kwargs):
        captured["preview"] = kwargs
        return b"preview-audio"

    async def fake_speech(**kwargs):
        raise AssertionError("StepAudio clone assets must not use /audio/speech")

    monkeypatch.setattr(engine, "_call_stepaudio_voice_preview_http", fake_preview)
    monkeypatch.setattr(engine, "_call_stepaudio_speech_http", fake_speech)

    result = asyncio.run(
        engine._synthesize_stepaudio(
            text="Preview line.",
            voice_params={
                "speaker": "stepaudio_clone:stepaudio_clone_unit",
                "stepaudio_voice_asset_id": "stepaudio_clone_unit",
                "stepaudio_voice_file_id": "file-unit",
                "stepaudio_voice_sample_text": "Sample text.",
                "instructions": "Warm voice, slow pace.",
            },
            provider_model=STEPAUDIO_25_TTS_MODEL,
            api_key="unit-step-key",
            raw_speaker_id="stepaudio_clone:stepaudio_clone_unit",
        )
    )

    assert result == b"preview-audio"
    instruction = captured["preview"]["instruction"]
    assert instruction.startswith("音色约束：保持已选音色")
    assert instruction.endswith("Warm voice，slow pace.")
    assert captured["preview"] == {
        "model": STEPAUDIO_25_TTS_MODEL,
        "api_key": "unit-step-key",
        "text": "Preview line.",
        "file_id": "file-unit",
        "sample_text": "Sample text.",
        "instruction": instruction,
    }


def test_stepaudio_clone_asset_synthesis_requires_file_id(monkeypatch) -> None:
    engine = TTSEngine(model=STEPAUDIO_25_TTS_MODEL, enable_cache=False, request_delay=0)

    async def fake_preview(**kwargs):
        raise AssertionError("StepAudio clone assets without file_id must fail before preview")

    async def fake_speech(**kwargs):
        raise AssertionError("StepAudio clone assets without file_id must not use /audio/speech")

    monkeypatch.setattr(engine, "_call_stepaudio_voice_preview_http", fake_preview)
    monkeypatch.setattr(engine, "_call_stepaudio_speech_http", fake_speech)

    with pytest.raises(ValueError, match="StepAudio clone reference requires file_id"):
        asyncio.run(
            engine._synthesize_stepaudio(
                text="Preview line.",
                voice_params={
                    "speaker": "stepaudio_clone:stepaudio_clone_unit",
                    "stepaudio_voice_asset_id": "stepaudio_clone_unit",
                },
                provider_model=STEPAUDIO_25_TTS_MODEL,
                api_key="unit-step-key",
                raw_speaker_id="stepaudio_clone:stepaudio_clone_unit",
            )
        )


def test_mimo_chat_payload_uses_official_default_preset_voice() -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_mimo_chat_payload(
        model=MIMO_V25_TTS_MODEL,
        text="夜色慢慢落下来。",
        voice="",
        voice_params={},
    )

    assert payload["audio"] == {"voice": "mimo_default", "format": "wav"}


def test_mimo_director_prompt_omits_fixed_voice_description_from_guidance() -> None:
    control = build_model_style_control(
        "mimo-v2.5-tts",
        {
            "voice_description": "性别：女性，年龄感：青年，音调：偏低，语速：缓慢，情绪：温柔但疲惫，特点：气声、吐字清晰，用途：有声书角色对白",
            "segment_speaker": "岑霜",
            "instruct_role": "冷硬疏离的世家掌权人",
            "instruct_scene": "祠堂里，对方试图带她逃离家族。",
            "performance_notes": "句末轻微气音。",
        },
        "calm",
    )

    assert control.mode == "mimo_director"
    content = control.messages[0]["content"]
    assert content.startswith("角色：冷硬疏离的世家掌权人\n")
    assert "场景：祠堂里，对方试图带她逃离家族" in content
    assert "指导：音色约束：保持已选音色" in content
    assert "性别：女性" not in content
    assert "年龄感：青年" not in content
    assert "语速：缓慢" not in content
    assert "情绪：温柔但疲惫" not in content
    assert "句末轻微气音" in content


def test_mimo_director_prompt_keeps_explicit_performance_without_voice_description() -> None:
    control = build_model_style_control(
        "mimo-v2.5-tts",
        {
            "instructions": "整体保持冷静克制，重读关键转折。",
            "voice_description": "性别：女性，年龄感：青年，音调：中低音，语速：缓慢，情绪：压抑，特点：气声、清晰，用途：有声书角色对白",
            "instruct_role": "长期压抑情绪的继承人",
            "instruct_scene": "雨夜，她终于说出真相。",
        },
        "calm",
    )

    content = control.messages[0]["content"]

    assert content.startswith("角色：长期压抑情绪的继承人\n")
    assert "场景：雨夜，她终于说出真相" in content
    assert "指导：音色约束：保持已选音色" in content
    assert "性别：女性" not in content
    assert "年龄感：青年" not in content
    assert "整体保持冷静克制，重读关键转折" in content


def test_mimo_chat_payload_places_audio_tags_in_assistant_message() -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_mimo_chat_payload(
        model=MIMO_V25_TTS_MODEL,
        text="呼……冷静，冷静。",
        voice="冰糖",
        voice_params={
            "style_control_method": "audio_tags",
            "style_tags": ["紧张", "深呼吸"],
            "inline_audio_tags": ["小声"],
        },
    )

    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][0]["content"].startswith("音色约束：保持已选音色")
    assert payload["messages"][1] == {
        "role": "assistant",
        "content": "（紧张，深呼吸）[小声]呼……冷静，冷静。",
    }
    assert payload["audio"] == {"voice": "冰糖", "format": "wav"}


def test_mimo_voice_design_payload_uses_user_voice_description_without_preset_voice() -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_VOICE_DESIGN_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_mimo_chat_payload(
        model=MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        text="今晚的风很轻，我们慢慢说。",
        voice="Chloe",
        voice_params={
            "voice_description": "青年女性，中音偏低，语速缓慢，温柔但略带疲惫，气声轻，适合有声书独白。",
            "format": "wav",
            "optimize_text_preview": True,
        },
    )

    assert payload["model"] == MIMO_V25_TTS_VOICE_DESIGN_MODEL
    assert payload["messages"] == [
        {
            "role": "user",
            "content": "青年女性，中音偏低，语速缓慢，温柔但略带疲惫，气声轻，适合有声书独白。",
        },
        {"role": "assistant", "content": "今晚的风很轻，我们慢慢说。"},
    ]
    assert payload["audio"] == {"format": "wav", "optimize_text_preview": True}


def test_mimo_voice_design_payload_merges_style_into_user_prompt_without_audio_tags() -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_VOICE_DESIGN_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_mimo_chat_payload(
        model=MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        text="别回头，继续往前走。",
        voice="Chloe",
        voice_params={
            "style_control_method": "audio_tags",
            "style_tags": ["紧张"],
            "inline_audio_tags": ["小声"],
            "voice_description": "青年女性，中音偏低，语速偏慢，声线清晰。",
            "instructions": "句尾轻微气声，整体克制。",
        },
    )

    assert payload["model"] == MIMO_V25_TTS_VOICE_DESIGN_MODEL
    assert payload["messages"][0]["role"] == "user"
    assert "青年女性，中音偏低，语速偏慢，声线清晰。" in payload["messages"][0]["content"]
    assert "句尾轻微气声，整体克制。" in payload["messages"][0]["content"]
    assert payload["messages"][1] == {"role": "assistant", "content": "别回头，继续往前走。"}
    assert "[小声]" not in payload["messages"][1]["content"]
    assert payload["audio"] == {"format": "wav"}


def test_mimo_voice_clone_payload_uses_audio_data_url_as_voice() -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_VOICE_CLONE_MODEL, enable_cache=False, request_delay=0)
    sample_voice = "data:audio/mpeg;base64,dm9pY2U="

    payload = engine._build_mimo_chat_payload(
        model=MIMO_V25_TTS_VOICE_CLONE_MODEL,
        text="别怕，我就在这里。",
        voice=sample_voice,
        voice_params={
            "style_control_method": "audio_tags",
            "style_tags": ["温柔"],
            "inline_audio_tags": ["轻声"],
        },
    )

    assert payload["model"] == MIMO_V25_TTS_VOICE_CLONE_MODEL
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][0]["content"].startswith("音色约束：保持已选音色")
    assert payload["messages"][1] == {
        "role": "assistant",
        "content": "（温柔）[轻声]别怕，我就在这里。",
    }
    assert payload["audio"] == {"voice": sample_voice, "format": "wav"}


def test_mimo_voice_clone_payload_prefers_asset_data_url_over_asset_voice_id() -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_VOICE_CLONE_MODEL, enable_cache=False, request_delay=0)
    sample_voice = "data:audio/wav;base64,dm9pY2U="

    payload = engine._build_mimo_chat_payload(
        model=MIMO_V25_TTS_VOICE_CLONE_MODEL,
        text="别怕，我就在这里。",
        voice="mimo_clone:mimo_clone_saved",
        voice_params={
            "voice_clone_data_url": sample_voice,
            "mimo_voice_asset_id": "mimo_clone_saved",
        },
    )

    assert payload["audio"] == {"voice": sample_voice, "format": "wav"}


def test_mimo_synthesis_uses_mimo_api_key_without_dashscope(monkeypatch) -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_MODEL, enable_cache=False, request_delay=0)
    monkeypatch.setenv("MIMO_API_KEY", "unit-mimo-key")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("ALIYUN_API_KEY", raising=False)
    captured: dict[str, object] = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return b"ok"

    monkeypatch.setattr(engine, "_call_mimo_chat_completions_http", fake_call, raising=False)

    result = asyncio.run(
        engine._synthesize_aliyun(
            text="测试 MiMo。",
            voice_params={"speaker": "Chloe"},
            enable_cache=False,
        )
    )

    assert result == b"ok"
    assert captured["api_key"] == "unit-mimo-key"
    assert captured["model"] == MIMO_V25_TTS_MODEL
    assert captured["voice"] == "Chloe"


def test_mimo_http_call_uses_xiaomi_chat_completions_endpoint(monkeypatch) -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_MODEL, enable_cache=False, request_delay=0)
    expected_audio = b"fake-wav"
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "audio": {"data": base64.b64encode(expected_audio).decode("ascii")},
                        },
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        engine._call_mimo_chat_completions_http(
            model=MIMO_V25_TTS_MODEL,
            api_key="unit-mimo-key",
            text="测试小米 MiMo。",
            voice="Chloe",
            voice_params={},
        )
    )

    assert result == expected_audio
    assert captured["url"] == "https://api.xiaomimimo.com/v1/chat/completions"
    assert captured["headers"] == {
        "api-key": "unit-mimo-key",
        "Content-Type": "application/json",
    }
    assert captured["json"]["model"] == MIMO_V25_TTS_MODEL
    assert captured["json"]["audio"] == {"voice": "Chloe", "format": "wav"}
