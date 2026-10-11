"""Independent model-aware TTS prompt test cases."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.audiobook.tts_delivery_plan import build_delivery_plan
from app.services.audiobook.tts_model_ids import (
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    MIMO_V25_TTS_MODEL,
    MIMO_V25_TTS_VOICE_CLONE_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    QWEN_AUDIO_31_TTS_FLASH_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_3_TTS_MODEL,
    get_audiobook_tts_model_metadata,
    list_supported_audiobook_tts_models,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.cosyvoice_clone_client import COSYVOICE_V35_PLUS_MODEL_ID
from app.services.audiobook.tts_style_control import (
    build_model_style_control,
    build_provider_prompt_snapshot,
)


_COMMON_TEXT = "盒盖打开的一瞬间，所有人的呼吸都停住了。里面没有钥匙，只有一枚新鲜的指纹。"

# 注意：DEFAULT_AUDIOBOOK_TTS_MODEL 当前就是 QWEN_AUDIO_31_TTS_FLASH_MODEL，
# 两者若同时作为键会被 Python 字面量静默覆盖（后写赢），因此默认模型的用例并入同一条目。
_MODEL_TEST_CASES: dict[str, list[dict[str, Any]]] = {
    QWEN_AUDIO_31_TTS_FLASH_MODEL: [
        {
            "id": "emotion_pause_stress",
            "name": "情绪、停顿与重读",
            "purpose": "验证自然语言 instructions 能同时保留情绪、停顿与关键词重读。",
            "text": _COMMON_TEXT,
            "emotion": "surprised",
            "segment_type": "narration",
            "performance_notes": "先压住情绪，在“新鲜的指纹”前短暂停顿，结尾加重但不要喊。",
            "delivery_plan": {
                "delivery_mode": "narration",
                "pace": "slow",
                "intensity": "medium",
                "pause_profile": "dramatic",
                "pause_strategy": "在新鲜的指纹前短停，句尾留白",
                "stress_words": ["新鲜的指纹"],
            },
        },
        {
            "id": "wide_instruction_budget",
            "name": "宽预算自然语言指令",
            "purpose": "验证 instruction 预算放宽后，情绪、停顿与重读能同时保留而不被截断。",
            "text": _COMMON_TEXT,
            "emotion": "surprised",
            "segment_type": "narration",
            "performance_notes": "先压住情绪，在“新鲜的指纹”前短暂停顿，结尾加重但不要喊；保留旁白的克制感。",
            "delivery_plan": {
                "delivery_mode": "narration",
                "pace": "slow",
                "intensity": "medium",
                "pause_profile": "dramatic",
                "pause_strategy": "在新鲜的指纹前短停，句尾留白",
                "stress_words": ["新鲜的指纹"],
            },
        }
    ],
    COSYVOICE_V35_PLUS_MODEL_ID: [
        {
            "id": "compact_emotion_cues",
            "name": "短指令情绪变化",
            "purpose": "验证 100 单位预算内的 emotion/pause/重读/act 短 cue 是否真正改变表演。",
            "text": _COMMON_TEXT,
            "emotion": "surprised",
            "segment_type": "narration",
            "performance_notes": "先压住情绪，指纹二字前短暂停顿，结尾加重但不要喊。",
            "delivery_plan": {
                "delivery_mode": "narration",
                "pause_profile": "dramatic",
                "pause_strategy": "指纹前短停",
                "stress_words": ["新鲜的指纹"],
            },
        }
    ],
    MINIMAX_SPEECH_28_HD_MODEL: [
        {
            "id": "basic_prosody",
            "name": "基础韵律降级（HD）",
            "purpose": "验证高级提示被明确降级为较慢语速和受控音量，不改变固定音色。",
            "text": "雨声贴着窗沿落下，她沉默片刻，才轻声说出那个名字。",
            "emotion": "sad",
            "segment_type": "narration",
            "performance_notes": "语速放慢，语气收紧，情绪克制。",
            "delivery_plan": {
                "delivery_mode": "narration",
                "pace": "slow",
                "intensity": "low",
                "pause_strategy": "沉默片刻后继续",
            },
        }
    ],
    MINIMAX_SPEECH_28_TURBO_MODEL: [
        {
            "id": "basic_prosody_turbo",
            "name": "基础韵律降级（Turbo）",
            "purpose": "验证低延迟模型仅使用支持的 speed/volume 表演参数。",
            "text": "快走，门后的脚步已经追上来了。",
            "emotion": "fearful",
            "segment_type": "dialogue",
            "performance_notes": "语速略快，紧张但吐字清楚。",
            "delivery_plan": {
                "delivery_mode": "dialogue",
                "pace": "fast",
                "intensity": "high",
            },
        }
    ],
    MIMO_V25_TTS_MODEL: [
        {
            "id": "audio_tag_leak",
            "name": "音频标签与正文污染",
            "purpose": "验证 assistant 前缀标签能触发表演且不会被朗读进正文。",
            "text": "别出声，门外的脚步停在我们身后。",
            "emotion": "fearful",
            "segment_type": "dialogue",
            "performance_notes": "低语，气声更明显，紧张但不要尖叫。",
            "style_control_method": "audio_tags",
            "style_tags": ["紧张"],
            "inline_audio_tags": ["低语"],
            "delivery_plan": {
                "delivery_mode": "whisper",
                "pace": "slow",
                "intensity": "low",
                "emotion_mix": ["紧张"],
                "micro_tags": ["低语"],
            },
        }
    ],
    MIMO_V25_TTS_VOICE_DESIGN_MODEL: [
        {
            "id": "voice_design_emotion",
            "name": "音色设计与情绪合并",
            "purpose": "验证声音描述与表演提示合并进 voice-design user message。",
            "text": "天亮以前，她把这一夜的秘密，一并还给了雨声。",
            "emotion": "sad",
            "segment_type": "narration",
            "voice_design_prompt": "年轻女性，中低音，声音清晰克制，带轻微疲惫感。",
            "voice_description": "年轻女性，中低音，气息稳定，适合悬疑有声书旁白。",
            "performance_notes": "温柔收束，尾句留白，不要煽情。",
            "delivery_plan": {
                "delivery_mode": "narration",
                "pace": "slow",
                "intensity": "low",
                "pause_after": 0.6,
            },
        }
    ],
    MIMO_V25_TTS_VOICE_CLONE_MODEL: [
        {
            "id": "clone_director_control",
            "name": "复刻音色导演控制",
            "purpose": "验证复刻音色保持不变时，导演提示仍能改变情绪和节奏。",
            "text": "我不是不想回去，只是那里再也没有人在等我了。",
            "emotion": "sad",
            "segment_type": "dialogue",
            "performance_notes": "轻微哽咽，保持可懂度，不要拖成长哭。",
            "delivery_plan": {
                "delivery_mode": "sob",
                "pace": "slow",
                "intensity": "low",
                "emotion_mix": ["悲伤", "委屈"],
            },
        }
    ],
    STEPAUDIO_3_TTS_MODEL: [
        {
            "id": "global_and_inline_context",
            "name": "全局指令与文中提示",
            "purpose": "验证 instruction 保留停顿/重读，正文前缀承载低语等微表演。",
            "text": "别回头，灯影里站着的那个人，不一定还活着。",
            "emotion": "fearful",
            "segment_type": "dialogue",
            "performance_notes": "压低声音，近耳低语，紧张但克制，句尾不要上扬。",
            "inline_audio_tags": ["低语"],
            "delivery_plan": {
                "delivery_mode": "whisper",
                "pace": "slow",
                "intensity": "low",
                "pause_profile": "dramatic",
                "pause_strategy": "别回头后短停",
                "stress_words": ["不一定还活着"],
                "micro_tags": ["低语"],
            },
        }
    ],
    SEED_TTS_20_EXPRESSIVE_MODEL: [
        {
            "id": "query_response_tags",
            "name": "Query-response 与标签解析",
            "purpose": "验证 context_texts 和正文标签共同生效且标签不被读出。",
            "text": "停下！谁都不许再靠近那扇门。",
            "emotion": "angry",
            "segment_type": "dialogue",
            "performance_notes": "短促大喊，有制止感，后半句保持清晰。",
            "style_control_method": "audio_tags",
            "style_tags": ["愤怒"],
            "inline_audio_tags": ["大喊"],
            "delivery_plan": {
                "delivery_mode": "shout",
                "pace": "fast",
                "intensity": "high",
                "emotion_mix": ["愤怒"],
                "micro_tags": ["大喊"],
            },
        }
    ],
}


def _base_voice_params(model: str, case: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "tts_model": model,
        "text": case["text"],
        "segment_type": case.get("segment_type", "narration"),
        "segment_speaker": case.get("segment_speaker", "旁白"),
        "instruct_role": case.get("role", "有声书表演测试角色"),
        "instruct_scene": case.get("scene", "独立 TTS 提示词验收场景"),
        "instruct_emotion": case.get("emotion", "neutral"),
        "performance_notes": case.get("performance_notes", ""),
        "voice_description": case.get("voice_description", ""),
        "voice_design_prompt": case.get("voice_design_prompt", ""),
        "speed": 1.0,
        "rate": 1.0,
        "volume": 50,
    }
    for key in ("style_control_method", "style_tags", "inline_audio_tags"):
        if case.get(key):
            params[key] = deepcopy(case[key])
    if case.get("delivery_plan"):
        params["delivery_plan"] = deepcopy(case["delivery_plan"])
    return params


def _compile_case(model: str, raw_case: dict[str, Any]) -> dict[str, Any]:
    case = deepcopy(raw_case)
    params = _base_voice_params(model, case)
    emotion = str(case.get("emotion") or "neutral")
    delivery_plan = build_delivery_plan(voice_params=params, model=model, emotion=emotion)
    params["delivery_plan"] = delivery_plan
    style_control = build_model_style_control(model, params, emotion)
    params.update(style_control.provider_fields)
    if style_control.provider_fields.get("use_tag_parser"):
        params["use_tag_parser"] = True
    snapshot = build_provider_prompt_snapshot(
        model=model,
        style_control=style_control,
        delivery_plan=delivery_plan,
    )
    params["provider_prompt_snapshot"] = snapshot
    capabilities = get_audiobook_tts_model_metadata(model).get("capabilities") or {}
    return {
        **case,
        "model": model,
        "requires_custom_voice": bool(capabilities.get("requires_custom_voice")),
        "style_control_mode": style_control.mode,
        "text_prefix": style_control.text_prefix,
        "voice_params": params,
        "provider_prompt_snapshot": snapshot,
    }


def get_tts_test_case(model: Any, case_id: str) -> dict[str, Any]:
    normalized_model = normalize_audiobook_tts_model(model, default="")
    if normalized_model not in _MODEL_TEST_CASES:
        raise ValueError(f"unsupported TTS model: {model}")
    raw_case = next((item for item in _MODEL_TEST_CASES[normalized_model] if item["id"] == case_id), None)
    if raw_case is None:
        raise ValueError(f"unknown TTS test case: {normalized_model}/{case_id}")
    return _compile_case(normalized_model, raw_case)


def build_tts_test_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for model in list_supported_audiobook_tts_models():
        metadata = get_audiobook_tts_model_metadata(model)
        catalog.append(
            {
                "model": model,
                "name": metadata.get("name") or model,
                "description": metadata.get("description") or "",
                "capabilities": metadata.get("capabilities") or {},
                "cases": [_compile_case(model, case) for case in _MODEL_TEST_CASES[model]],
            }
        )
    return catalog
