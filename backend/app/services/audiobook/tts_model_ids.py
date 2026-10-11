from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

from app.services.audiobook.cosyvoice_clone_client import COSYVOICE_V35_PLUS_MODEL_ID
from core.model_resolution import normalize_model_id


QWEN_AUDIO_31_TTS_FLASH_MODEL: Final[str] = "qwen-audio-3.1-tts-flash"
DEFAULT_AUDIOBOOK_TTS_MODEL: Final[str] = QWEN_AUDIO_31_TTS_FLASH_MODEL
MINIMAX_SPEECH_28_HD_MODEL: Final[str] = "minimax-speech-2.8-hd"
MINIMAX_SPEECH_28_TURBO_MODEL: Final[str] = "minimax-speech-2.8-turbo"
MIMO_V25_TTS_MODEL: Final[str] = "mimo-v2.5-tts"
MIMO_V25_TTS_VOICE_DESIGN_MODEL: Final[str] = "mimo-v2.5-tts-voicedesign"
MIMO_V25_TTS_VOICE_CLONE_MODEL: Final[str] = "mimo-v2.5-tts-voiceclone"
STEPAUDIO_3_TTS_MODEL: Final[str] = "stepaudio-3-tts"
SEED_TTS_20_EXPRESSIVE_MODEL: Final[str] = "seed-tts-2.0-expressive"

SUPPORTED_AUDIOBOOK_TTS_MODELS: Final[set[str]] = {
    # DEFAULT_AUDIOBOOK_TTS_MODEL 与 QWEN_AUDIO_31_TTS_FLASH_MODEL 是同一个模型，
    # 注册表只保留一个条目，避免默认模型在列表里出现两次。
    QWEN_AUDIO_31_TTS_FLASH_MODEL,
    COSYVOICE_V35_PLUS_MODEL_ID,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    MIMO_V25_TTS_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    MIMO_V25_TTS_VOICE_CLONE_MODEL,
    STEPAUDIO_3_TTS_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
}

SUPPORTED_AUDIOBOOK_TTS_MODEL_ORDER: Final[tuple[str, ...]] = (
    QWEN_AUDIO_31_TTS_FLASH_MODEL,
    COSYVOICE_V35_PLUS_MODEL_ID,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    MIMO_V25_TTS_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    MIMO_V25_TTS_VOICE_CLONE_MODEL,
    STEPAUDIO_3_TTS_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
)

AUDIOBOOK_TTS_RUNTIME_MODEL_IDS: Final[dict[str, str]] = {
    QWEN_AUDIO_31_TTS_FLASH_MODEL: QWEN_AUDIO_31_TTS_FLASH_MODEL,
    COSYVOICE_V35_PLUS_MODEL_ID: COSYVOICE_V35_PLUS_MODEL_ID,
    MINIMAX_SPEECH_28_HD_MODEL: "MiniMax/speech-2.8-hd",
    MINIMAX_SPEECH_28_TURBO_MODEL: "MiniMax/speech-2.8-turbo",
    MIMO_V25_TTS_MODEL: MIMO_V25_TTS_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL: MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    MIMO_V25_TTS_VOICE_CLONE_MODEL: MIMO_V25_TTS_VOICE_CLONE_MODEL,
    STEPAUDIO_3_TTS_MODEL: STEPAUDIO_3_TTS_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL: SEED_TTS_20_EXPRESSIVE_MODEL,
}

GENERIC_AUDIOBOOK_TTS_STYLE_CAPABILITIES: Final[dict[str, Any]] = {
    "model_family": "generic",
    "style_control_modes": ["natural_language"],
    "preferred_style_control_mode": "natural_language",
    "supports_voice_description": True,
    "supports_director_mode": False,
    "supports_audio_tags": False,
    "supports_emotion_mixing": False,
    "supports_micro_tags": False,
    "supports_word_level_control": False,
    "supports_singing": False,
    "supports_streaming": False,
    "instruction_budget": None,
    "supported_emotions": [],
    "emotion_aliases": {},
    "control_message_roles": {},
}

_CORE_TTS_EMOTIONS: Final[list[str]] = [
    "neutral",
    "happy",
    "sad",
    "angry",
    "fearful",
    "surprised",
    "disgusted",
]

_CORE_TTS_EMOTION_ALIASES: Final[dict[str, str]] = {
    "calm": "neutral",
    "tender": "neutral",
    "gentle": "neutral",
    "focused": "neutral",
    "serious": "neutral",
    "whisper": "neutral",
    "solemn": "sad",
    "tense": "fearful",
    "nervous": "fearful",
    "fear": "fearful",
    "scared": "fearful",
    "excited": "happy",
    "joyful": "happy",
    "shout": "angry",
}

MIMO_V25_STYLE_CAPABILITIES: Final[dict[str, Any]] = {
    "model_family": "mimo",
    "style_control_modes": ["director", "audio_tags", "natural_language"],
    "preferred_style_control_mode": "director",
    "supports_voice_description": True,
    "supports_director_mode": True,
    "supports_audio_tags": True,
    "supports_emotion_mixing": True,
    "supports_micro_tags": True,
    "supports_word_level_control": True,
    "instruction_budget": None,
    "control_message_roles": {
        "director": "user",
        "audio_tags": "assistant",
        "natural_language": "user",
    },
}

AUDIOBOOK_TTS_STYLE_CAPABILITIES: Final[dict[str, dict[str, Any]]] = {
    QWEN_AUDIO_31_TTS_FLASH_MODEL: {
        "model_family": "qwen",
        "style_control_modes": ["natural_language"],
        "preferred_style_control_mode": "natural_language",
        "supports_voice_description": True,
        # 服务商侧 instruction 实测 4000 字仍返回 200，取 1200 留出安全余量。
        "instruction_budget": 1200,
        # 不声明 supported_emotions：3.1 没有服务端情绪枚举，情绪标签只进入自然语言指令，
        # 强行折叠到枚举会丢表现力（承接自 Qwen3 的历史降级行为不再需要）。
        "control_message_roles": {"natural_language": "input.instruction"},
    },
    COSYVOICE_V35_PLUS_MODEL_ID: {
        "model_family": "cosyvoice",
        "style_control_modes": ["natural_language"],
        "preferred_style_control_mode": "natural_language",
        "supports_voice_description": True,
        "instruction_budget": 100,
        "supported_emotions": _CORE_TTS_EMOTIONS,
        "emotion_aliases": _CORE_TTS_EMOTION_ALIASES,
        "control_message_roles": {"natural_language": "parameters.instruction"},
    },
    MINIMAX_SPEECH_28_HD_MODEL: {
        "model_family": "minimax",
        "style_control_modes": ["basic"],
        "preferred_style_control_mode": "basic",
        "supports_voice_description": False,
        "has_system_voices": True,
        "requires_custom_voice": False,
        "supports_voice_clone": True,
        "supports_voice_design": False,
        "supports_voice_tuning": False,
        "control_message_roles": {},
    },
    MINIMAX_SPEECH_28_TURBO_MODEL: {
        "model_family": "minimax",
        "style_control_modes": ["basic"],
        "preferred_style_control_mode": "basic",
        "supports_voice_description": False,
        "has_system_voices": True,
        "requires_custom_voice": False,
        "supports_voice_clone": True,
        "supports_voice_design": False,
        "supports_voice_tuning": False,
        "control_message_roles": {},
    },
    MIMO_V25_TTS_MODEL: {
        **MIMO_V25_STYLE_CAPABILITIES,
        "has_system_voices": True,
        "requires_custom_voice": False,
        "supports_voice_clone": False,
        "supports_voice_design": False,
        "supports_voice_tuning": True,
        "supports_singing": True,
        "supports_streaming": True,
        "control_message_roles": {
            "director": "user",
            "audio_tags": "assistant",
            "natural_language": "user",
        },
    },
    MIMO_V25_TTS_VOICE_DESIGN_MODEL: {
        **MIMO_V25_STYLE_CAPABILITIES,
        "style_control_modes": ["voice_design", "natural_language"],
        "preferred_style_control_mode": "voice_design",
        "has_system_voices": False,
        "requires_custom_voice": True,
        "supports_voice_clone": False,
        "supports_voice_design": True,
        "supports_voice_tuning": True,
        "supports_director_mode": False,
        "supports_audio_tags": False,
        "supports_micro_tags": False,
        "supports_word_level_control": False,
        "supports_singing": False,
        "supports_streaming": False,
        "style_instruction_scope": "merged_into_voice_design_prompt",
        "control_message_roles": {
            "voice_design": "user",
            "natural_language": "user",
        },
    },
    MIMO_V25_TTS_VOICE_CLONE_MODEL: {
        **MIMO_V25_STYLE_CAPABILITIES,
        "has_system_voices": False,
        "requires_custom_voice": True,
        "supports_voice_clone": True,
        "supports_voice_design": False,
        "supports_voice_tuning": True,
        "supports_singing": False,
        "supports_streaming": False,
        "control_message_roles": {
            "director": "user",
            "audio_tags": "assistant",
            "natural_language": "user",
            "voice_clone": "audio.voice",
        },
    },
    STEPAUDIO_3_TTS_MODEL: {
        "model_family": "stepaudio",
        "style_control_modes": ["global_context", "inline_context", "natural_language"],
        "preferred_style_control_mode": "global_context",
        "supports_voice_description": True,
        "supports_director_mode": False,
        "supports_audio_tags": False,
        "supports_emotion_mixing": True,
        "supports_micro_tags": True,
        "supports_word_level_control": True,
        "supports_singing": False,
        # 上游流式能力未取证，且我方消费面是缓冲式 HTTP（无 stream 布尔、无 SSE 解析），按未支持声明。
        "supports_streaming": False,
        "has_system_voices": True,
        "requires_custom_voice": False,
        "supports_voice_clone": True,
        "supports_voice_design": False,
        "supports_voice_tuning": True,
        "instruction_budget": 500,
        "max_input_chars": 1000,
        "control_message_roles": {
            "global_context": "parameters.instruction",
            "inline_context": "input.parentheses",
            "natural_language": "parameters.instruction",
        },
    },
    SEED_TTS_20_EXPRESSIVE_MODEL: {
        "model_family": "doubao",
        "style_control_modes": ["query_response", "audio_tags", "natural_language"],
        "preferred_style_control_mode": "query_response",
        "supports_voice_description": True,
        "supports_director_mode": False,
        "supports_audio_tags": True,
        "supports_emotion_mixing": True,
        "supports_micro_tags": True,
        "supports_word_level_control": True,
        "supports_singing": False,
        "supports_streaming": True,
        "has_system_voices": True,
        "requires_custom_voice": False,
        # 官方支持声音复刻 2.0（seed-icl-2.0），但项目无复刻创建与资产链路，且首次正式使用有 138 元槽位费，按未实现声明。
        "supports_voice_clone": False,
        "supports_voice_design": False,
        "supports_voice_tuning": True,
        "instruction_budget": None,
        "control_message_roles": {
            "query_response": "additions.context_texts",
            "audio_tags": "req_params.text + req_params.use_tag_parser",
            "natural_language": "additions.context_texts",
        },
    },
}

AUDIOBOOK_TTS_MODEL_CATALOG: Final[dict[str, dict[str, Any]]] = {
    QWEN_AUDIO_31_TTS_FLASH_MODEL: {
        "name": "Qwen-Audio 3.1 TTS Flash",
        "description": "默认模型，{voice_count} 个官方系统音色，支持自然语言 instructions 与长文本输入",
        "catalog_note": "覆盖普通话、英文、方言、儿童与角色扮演音色；正文与 instruction 上限均高于已退役的 Qwen3-TTS。",
        "price_per_10k": 0.4,
        "pricing_status": "public_postpaid",
        # 服务商按 token 计费（输入 1.5 / 输出 12 元每百万 tokens），此处折算为等效万字价。
        "pricing_basis": "derived_from_token_price",
        "pricing_source": "alibaba_model_studio_token_price_probe_2026-10-10",
        "custom_voice_pricing": {"creation_yuan": 0.0},
        "cost_level": "low",
        "quality_level": "high",
        "priority": 3,
        "features": ("默认模型", "{voice_count} 音色", "自然语言指令", "长文本输入", "英文与方言音色"),
        "capabilities": {
            "has_system_voices": True,
            "requires_custom_voice": False,
            "supports_voice_clone": False,
            "supports_voice_design": False,
            "supports_voice_tuning": False,
        },
    },
    COSYVOICE_V35_PLUS_MODEL_ID: {
        "name": "CosyVoice v3.5 Plus",
        "description": "高表现力模型，支持 instruction 与音色复刻/设计，但无系统音色",
        "catalog_note": "官方无系统音色，需要先准备复刻或设计音色，适合精品章节。",
        "price_per_10k": 1.5,
        "pricing_status": "public_postpaid",
        "pricing_basis": "public_list_price",
        "pricing_source": "alibaba_model_studio_public_price_2026-07-22",
        "custom_voice_pricing": {"creation_yuan": 0.0},
        "cost_level": "high",
        "quality_level": "premium",
        "priority": 1,
        "features": ("高表现力", "instruction", "复刻/设计音色", "无系统音色"),
        "capabilities": {
            "has_system_voices": False,
            "requires_custom_voice": True,
            "supports_voice_clone": True,
            "supports_voice_design": True,
            "supports_voice_tuning": True,
        },
    },
    MINIMAX_SPEECH_28_HD_MODEL: {
        "name": "MiniMax Speech 2.8 HD",
        "description": "高音质模型，{voice_count} 个可用音色，支持语气词标签",
        "catalog_note": "适合角色对白、旁白和高质量章节生成。",
        "price_per_10k": 3.5,
        "pricing_status": "public_postpaid",
        "pricing_basis": "public_list_price",
        "pricing_source": "alibaba_model_studio_public_price_2026-07-22",
        "custom_voice_pricing": {
            "clone_request_yuan": 0.0,
            "preview_price_per_10k": 3.5,
            "first_formal_use_yuan": 9.9,
        },
        "cost_level": "medium",
        "quality_level": "high",
        "priority": 4,
        "features": ("高音质", "语气词标签", "音色复刻", "{voice_count} 音色"),
        "capabilities": {
            "has_system_voices": True,
            "requires_custom_voice": False,
            "supports_voice_clone": True,
            "supports_voice_design": False,
            "supports_voice_tuning": False,
        },
    },
    MINIMAX_SPEECH_28_TURBO_MODEL: {
        "name": "MiniMax Speech 2.8 Turbo",
        "description": "低延迟模型，{voice_count} 个可用音色，适合高并发生成",
        "catalog_note": "适合高并发批量生成和成本优先场景。",
        "price_per_10k": 2.0,
        "pricing_status": "public_postpaid",
        "pricing_basis": "public_list_price",
        "pricing_source": "alibaba_model_studio_public_price_2026-07-22",
        "custom_voice_pricing": {
            "clone_request_yuan": 0.0,
            "preview_price_per_10k": 2.0,
            "first_formal_use_yuan": 9.9,
        },
        "cost_level": "low",
        "quality_level": "medium",
        "priority": 5,
        "features": ("低延迟", "高并发", "音色复刻", "{voice_count} 音色"),
        "capabilities": {
            "has_system_voices": True,
            "requires_custom_voice": False,
            "supports_voice_clone": True,
            "supports_voice_design": False,
            "supports_voice_tuning": False,
        },
    },
    MIMO_V25_TTS_MODEL: {
        "name": "MiMo V2.5 TTS",
        "description": "小米 MiMo 预置音色语音合成模型，{voice_count} 个官方精品音色，支持导演模式、音频标签和唱歌模式",
        "catalog_note": "仅使用官方预置音色；支持自然语言风格指令、导演模式、音频标签与唱歌模式。",
        "price_per_10k": 0.0,
        "pricing_status": "limited_time_free",
        "pricing_basis": "public_list_price",
        "pricing_source": "xiaomi_mimo_limited_time_free_2026-07-22",
        "custom_voice_pricing": {},
        "cost_level": "free",
        "quality_level": "high",
        "priority": 2,
        "features": ("{voice_count} 音色", "导演模式", "音频标签", "唱歌模式"),
        "capabilities": {
            "has_system_voices": True,
            "requires_custom_voice": False,
            "supports_voice_clone": False,
            "supports_voice_design": False,
            "supports_voice_tuning": True,
            "supports_singing": True,
            "supports_streaming": True,
        },
    },
    MIMO_V25_TTS_VOICE_DESIGN_MODEL: {
        "name": "MiMo V2.5 TTS Voice Design",
        "description": "小米 MiMo 文本音色设计模型，通过 user 消息中的声音描述生成定制音色",
        "catalog_note": "不提供预置音色；需要传入高质量 voice_description 作为 user 消息，适合为有声小说角色临时设计声线。",
        "price_per_10k": 0.0,
        "pricing_status": "limited_time_free",
        "pricing_basis": "public_list_price",
        "pricing_source": "xiaomi_mimo_limited_time_free_2026-07-22",
        "custom_voice_pricing": {},
        "cost_level": "free",
        "quality_level": "high",
        "priority": 2,
        "features": ("文本音色设计", "自然语言风格融合", "复合情绪", "无预置音色"),
        "capabilities": {
            "has_system_voices": False,
            "requires_custom_voice": True,
            "supports_voice_clone": False,
            "supports_voice_design": True,
            "supports_voice_tuning": True,
            "supports_singing": False,
            "supports_streaming": False,
        },
    },
    MIMO_V25_TTS_VOICE_CLONE_MODEL: {
        "name": "MiMo V2.5 TTS Voice Clone",
        "description": "小米 MiMo 音频样本复刻模型，通过 audio.voice 传入 base64 音频样本",
        "catalog_note": "不提供预置音色；audio.voice 必须是 data:{MIME_TYPE};base64,$BASE64_AUDIO，样本 base64 不超过 10 MB。",
        "price_per_10k": 0.0,
        "pricing_status": "limited_time_free",
        "pricing_basis": "public_list_price",
        "pricing_source": "xiaomi_mimo_limited_time_free_2026-07-22",
        "custom_voice_pricing": {},
        "cost_level": "free",
        "quality_level": "medium_high",
        "priority": 4,
        "features": ("音色复刻", "导演模式", "音频标签", "样本不超过 10 MB"),
        "capabilities": {
            "has_system_voices": False,
            "requires_custom_voice": True,
            "supports_voice_clone": True,
            "supports_voice_design": False,
            "supports_voice_tuning": True,
            "supports_singing": False,
            "supports_streaming": False,
        },
    },
    STEPAUDIO_3_TTS_MODEL: {
        "name": "StepAudio 3 TTS",
        "description": "新一代 Contextual TTS，{voice_count} 个可用音色，支持全局语境 instruction、文中语境括号控制与 Zero-shot 音色复刻，真人级口语表现",
        "catalog_note": "Global Context 定调整段基调，Inline Context 用圆括号逐句控制情绪、停顿和气息；单次输入 1000 字符，instruction 500 字符。",
        "price_per_10k": 2.5,
        "pricing_status": "public_postpaid",
        "pricing_basis": "public_list_price",
        "pricing_source": "stepfun_public_price_2026-10-09",
        "custom_voice_pricing": {
            "preview_price_per_10k": 2.5,
            "formal_clone_success_yuan": 9.9,
        },
        "cost_level": "medium",
        "quality_level": "premium",
        "priority": 2,
        "features": ("Contextual TTS", "全局语境", "文中语境", "Zero-shot 音色复刻", "真人级口语"),
        "capabilities": {
            "has_system_voices": True,
            "requires_custom_voice": False,
            "supports_voice_clone": True,
            "supports_voice_design": False,
            "supports_voice_tuning": True,
            # 与风格能力表同步降级：上游流式未取证，我方合成链路只发非流式 /audio/speech。
            "supports_streaming": False,
        },
    },
    SEED_TTS_20_EXPRESSIVE_MODEL: {
        "name": "Doubao Seed-TTS 2.0 Expressive",
        "description": "豆包语音合成 2.0 高表现力版，{voice_count} 个可用音色，支持 Query-Response 对话式TTS和文本指令控制",
        "catalog_note": "适合有声小说、AI 交互、内容生产和企业客服，可通过上下文指令控制语速、情绪、声线和风格。",
        "price_per_10k": 3.0,
        "pricing_status": "public_postpaid",
        "pricing_basis": "public_list_price",
        "pricing_source": "volcengine_public_postpaid_2026-07-22",
        # 仅作开通门槛台账：复刻链路未实现，代码不消费这些键。
        "custom_voice_pricing": {
            "postpaid_slot_first_formal_use_yuan": 138.0,
            "preview_price_per_10k": 3.0,
            "unused_preview_retention_days": 7,
        },
        "cost_level": "medium",
        "quality_level": "premium",
        "priority": 2,
        "features": ("对话式TTS", "情感演绎", "文本指令控制", "{voice_count} 音色"),
        "capabilities": {
            "has_system_voices": True,
            "requires_custom_voice": False,
            "supports_voice_clone": False,
            "supports_voice_design": False,
            "supports_voice_tuning": True,
            "supports_streaming": True,
        },
    },
}

_AUDIOBOOK_TTS_MODEL_ALIASES: Final[dict[str, str]] = {
    # Qwen3-TTS 一族的写法不在这里逐条列举，统一由 normalize_audiobook_tts_model
    # 的前缀分支折叠到 3.1，避免出现第二个事实源。
    "qwen-audio-3.1-tts": QWEN_AUDIO_31_TTS_FLASH_MODEL,
    "qwen-audio-3.1-tts-flash": QWEN_AUDIO_31_TTS_FLASH_MODEL,
    "qwen_audio_3_1_tts_flash": QWEN_AUDIO_31_TTS_FLASH_MODEL,
    "qwen-audio/3.1-tts-flash": QWEN_AUDIO_31_TTS_FLASH_MODEL,
    "cosyvoice-v3-plus": COSYVOICE_V35_PLUS_MODEL_ID,
    "cosyvoice_v3_plus": COSYVOICE_V35_PLUS_MODEL_ID,
    "cosyvoice-v3.5-plus": COSYVOICE_V35_PLUS_MODEL_ID,
    "minimax-speech-2.8": MINIMAX_SPEECH_28_HD_MODEL,
    "minimax-speech-2.8-hd": MINIMAX_SPEECH_28_HD_MODEL,
    "minimax-speech-2.8-turbo": MINIMAX_SPEECH_28_TURBO_MODEL,
    "minimax/speech-2.8-hd": MINIMAX_SPEECH_28_HD_MODEL,
    "minimax/speech-2.8-turbo": MINIMAX_SPEECH_28_TURBO_MODEL,
    "minimax/speech-2.8": MINIMAX_SPEECH_28_HD_MODEL,
    "mimo-v2.5-tts": MIMO_V25_TTS_MODEL,
    "mimo-v2.5-tts-voicedesign": MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    "mimo-v2.5-tts-voice-design": MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    "mimo/v2.5-tts-voicedesign": MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    "mimo/v2.5-tts-voice-design": MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    "mimo-v2.5-tts-voiceclone": MIMO_V25_TTS_VOICE_CLONE_MODEL,
    "mimo-v2.5-tts-voice-clone": MIMO_V25_TTS_VOICE_CLONE_MODEL,
    "mimo/v2.5-tts-voiceclone": MIMO_V25_TTS_VOICE_CLONE_MODEL,
    "mimo/v2.5-tts-voice-clone": MIMO_V25_TTS_VOICE_CLONE_MODEL,
    "mimo/v2.5-tts": MIMO_V25_TTS_MODEL,
    "stepaudio-3-tts": STEPAUDIO_3_TTS_MODEL,
    "stepaudio_3_tts": STEPAUDIO_3_TTS_MODEL,
    "stepaudio3tts": STEPAUDIO_3_TTS_MODEL,
    "stepfun/stepaudio-3-tts": STEPAUDIO_3_TTS_MODEL,
    "stepfun/stepaudio_3_tts": STEPAUDIO_3_TTS_MODEL,
    "seed-tts-2.0-expressive": SEED_TTS_20_EXPRESSIVE_MODEL,
    "seed_tts_2_0_expressive": SEED_TTS_20_EXPRESSIVE_MODEL,
    "doubao/seed-tts-2.0-expressive": SEED_TTS_20_EXPRESSIVE_MODEL,
    "doubao/seed_tts_2_0_expressive": SEED_TTS_20_EXPRESSIVE_MODEL,
    "doubao-tts-2.0-expressive": SEED_TTS_20_EXPRESSIVE_MODEL,
    "doubao-语音合成-2.0": SEED_TTS_20_EXPRESSIVE_MODEL,
}


def normalize_audiobook_tts_model(model: Any, *, default: str = DEFAULT_AUDIOBOOK_TTS_MODEL) -> str:
    raw = str(model or "").strip()
    if not raw:
        return default

    normalized = normalize_model_id(raw) or raw
    for candidate in (raw, normalized):
        value = str(candidate or "").strip()
        if value in SUPPORTED_AUDIOBOOK_TTS_MODELS:
            return value

        alias = _AUDIOBOOK_TTS_MODEL_ALIASES.get(value.lower())
        if alias:
            return alias

    lowered = str(normalized or raw).strip().lower()
    if lowered.startswith("minimax/speech-2.8-turbo"):
        return MINIMAX_SPEECH_28_TURBO_MODEL
    if lowered.startswith("minimax/speech-2.8-hd") or lowered.startswith("minimax/speech-2.8"):
        return MINIMAX_SPEECH_28_HD_MODEL
    if lowered.startswith("minimax-speech-2.8-turbo"):
        return MINIMAX_SPEECH_28_TURBO_MODEL
    if lowered.startswith("minimax-speech-2.8"):
        return MINIMAX_SPEECH_28_HD_MODEL
    if lowered.startswith("qwen-audio-3.1-tts-flash") or lowered.startswith("qwen-audio/3.1-tts-flash"):
        return QWEN_AUDIO_31_TTS_FLASH_MODEL
    if lowered.startswith("qwen-audio-3.1-tts") or lowered.startswith("qwen-audio/3.1-tts"):
        return default
    if lowered.startswith("qwen3-tts") or lowered.startswith("qwen3_tts"):
        # Qwen3-TTS 一族已物理退役：历史配置里的任何拼写（含 -flash/-plus/-instruct
        # 变体与下划线写法）统一折叠到 3.1，不保留注册表里已不存在的模型 ID。
        return QWEN_AUDIO_31_TTS_FLASH_MODEL
    if lowered.startswith("stepfun/stepaudio-3-tts") or lowered.startswith("stepaudio-3-tts"):
        return STEPAUDIO_3_TTS_MODEL
    if lowered.startswith("stepfun/stepaudio_3_tts") or lowered.startswith("stepaudio_3_tts"):
        return STEPAUDIO_3_TTS_MODEL
    if (
        lowered.startswith("doubao/seed-tts-2.0-expressive")
        or lowered.startswith("doubao/seed_tts_2_0_expressive")
        or lowered.startswith("doubao-tts-2.0-expressive")
        or lowered.startswith("seed-tts-2.0-expressive")
        or lowered.startswith("seed_tts_2_0_expressive")
    ):
        return SEED_TTS_20_EXPRESSIVE_MODEL
    if lowered.startswith("mimo-v2.5-tts-voicedesign") or lowered.startswith("mimo/v2.5-tts-voicedesign"):
        return MIMO_V25_TTS_VOICE_DESIGN_MODEL
    if lowered.startswith("mimo-v2.5-tts-voice-design") or lowered.startswith("mimo/v2.5-tts-voice-design"):
        return MIMO_V25_TTS_VOICE_DESIGN_MODEL
    if lowered.startswith("mimo-v2.5-tts-voiceclone") or lowered.startswith("mimo/v2.5-tts-voiceclone"):
        return MIMO_V25_TTS_VOICE_CLONE_MODEL
    if lowered.startswith("mimo-v2.5-tts-voice-clone") or lowered.startswith("mimo/v2.5-tts-voice-clone"):
        return MIMO_V25_TTS_VOICE_CLONE_MODEL
    if lowered.startswith("mimo-v2.5-tts-") or lowered.startswith("mimo/v2.5-tts-"):
        return default
    if lowered.startswith("mimo-v2.5-tts") or lowered.startswith("mimo/v2.5-tts"):
        return MIMO_V25_TTS_MODEL

    return default


def is_supported_audiobook_tts_model(model: Any) -> bool:
    return normalize_audiobook_tts_model(model, default="") in SUPPORTED_AUDIOBOOK_TTS_MODELS


def list_supported_audiobook_tts_models() -> list[str]:
    return list(SUPPORTED_AUDIOBOOK_TTS_MODEL_ORDER)


def get_audiobook_tts_runtime_model_id(model: Any) -> str:
    normalized = normalize_audiobook_tts_model(model, default="")
    if not normalized:
        return ""
    return AUDIOBOOK_TTS_RUNTIME_MODEL_IDS.get(normalized, normalize_model_id(normalized) or normalized)


def get_audiobook_tts_style_capabilities(model: Any) -> dict[str, Any]:
    normalized = normalize_audiobook_tts_model(model, default="")
    capabilities = deepcopy(GENERIC_AUDIOBOOK_TTS_STYLE_CAPABILITIES)
    capabilities.update(deepcopy(AUDIOBOOK_TTS_STYLE_CAPABILITIES.get(normalized, {})))
    return capabilities


# 可用自然语言/标签等表演指令控制韵律的风格控制模式；
# 命中其一的模型，语速等韵律应由表演指令表达，而非片段级数值参数。
INSTRUCT_STYLE_CONTROL_MODES: Final[frozenset[str]] = frozenset(
    {
        "audio_tags",
        "director",
        "global_context",
        "inline_context",
        "natural_language",
        "query_response",
        "voice_design",
    }
)

BASIC_NUMERIC_SPEED_MODELS: Final[frozenset[str]] = frozenset(
    {
        MINIMAX_SPEECH_28_HD_MODEL,
        MINIMAX_SPEECH_28_TURBO_MODEL,
    }
)


def model_supports_instruct_style_control(model: Any) -> bool:
    """判断模型是否支持指令式风格控制（自然语言/音频标签等）。"""
    normalized = normalize_audiobook_tts_model(model, default="")
    if not normalized:
        return False
    modes = get_audiobook_tts_style_capabilities(normalized).get("style_control_modes") or []
    return bool(INSTRUCT_STYLE_CONTROL_MODES.intersection(modes))


def model_uses_basic_numeric_speed_control(model: Any) -> bool:
    """Return whether semantic pace must be degraded to provider numeric speed."""

    normalized = normalize_audiobook_tts_model(model, default="")
    return normalized in BASIC_NUMERIC_SPEED_MODELS


_EMOTION_KEYWORD_ALIASES: Final[tuple[tuple[str, str], ...]] = (
    ("\u7d27\u5f20", "fearful"),
    ("\u6050\u60e7", "fearful"),
    ("\u5bb3\u6015", "fearful"),
    ("\u53d1\u98a4", "fearful"),
    ("\u6124\u6012", "angry"),
    ("\u6012", "angry"),
    ("\u60b2", "sad"),
    ("\u54ed", "sad"),
    ("\u54fd\u54bd", "sad"),
    ("\u5f00\u5fc3", "happy"),
    ("\u559c", "happy"),
    ("\u60ca", "surprised"),
    ("\u538c\u6076", "disgusted"),
    ("\u5acc\u6076", "disgusted"),
)


def _coerce_capability_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def normalize_audiobook_tts_emotion(emotion: Any, model: Any) -> str:
    """Normalize an emotion label from the selected model capability matrix."""

    value = str(emotion or "").strip()
    if not value:
        return ""

    capabilities = get_audiobook_tts_style_capabilities(model)
    supported = _coerce_capability_string_list(capabilities.get("supported_emotions"))
    if not supported:
        return value

    lowered = value.lower()
    supported_lookup = {item.lower(): item for item in supported}
    if lowered in supported_lookup:
        return supported_lookup[lowered]

    aliases = {
        str(key).strip().lower(): str(mapped).strip()
        for key, mapped in dict(capabilities.get("emotion_aliases") or {}).items()
        if str(key).strip() and str(mapped).strip()
    }
    mapped = aliases.get(lowered)
    if mapped and mapped.lower() in supported_lookup:
        return supported_lookup[mapped.lower()]

    for keyword, candidate in _EMOTION_KEYWORD_ALIASES:
        if keyword in value and candidate.lower() in supported_lookup:
            return supported_lookup[candidate.lower()]

    return "neutral" if "neutral" in supported_lookup else supported[0]


def get_audiobook_tts_model_metadata(model: Any) -> dict[str, Any]:
    normalized = normalize_audiobook_tts_model(model, default="")
    if normalized not in AUDIOBOOK_TTS_MODEL_CATALOG:
        return {}
    metadata = deepcopy(AUDIOBOOK_TTS_MODEL_CATALOG[normalized])
    metadata["id"] = normalized
    metadata["features"] = list(metadata.get("features") or [])
    capabilities = dict(metadata.get("capabilities") or {})
    capabilities.update(get_audiobook_tts_style_capabilities(normalized))
    metadata["capabilities"] = capabilities
    return metadata


def get_audiobook_tts_model_price_per_10k(model: Any, *, default: float | None = None) -> float | None:
    metadata = get_audiobook_tts_model_metadata(model)
    if not metadata:
        return default
    try:
        return float(metadata.get("price_per_10k"))
    except (TypeError, ValueError):
        return default
