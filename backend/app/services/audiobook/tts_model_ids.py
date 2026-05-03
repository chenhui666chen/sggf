from __future__ import annotations

from typing import Any, Final

from app.services.audiobook.cosyvoice_clone_client import COSYVOICE_V35_PLUS_MODEL_ID
from core.model_resolution import normalize_model_id


DEFAULT_AUDIOBOOK_TTS_MODEL: Final[str] = "qwen3-tts-instruct-flash"
MINIMAX_SPEECH_28_HD_MODEL: Final[str] = "minimax-speech-2.8-hd"
MINIMAX_SPEECH_28_TURBO_MODEL: Final[str] = "minimax-speech-2.8-turbo"

SUPPORTED_AUDIOBOOK_TTS_MODELS: Final[set[str]] = {
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    COSYVOICE_V35_PLUS_MODEL_ID,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
}

SUPPORTED_AUDIOBOOK_TTS_MODEL_ORDER: Final[tuple[str, ...]] = (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    COSYVOICE_V35_PLUS_MODEL_ID,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
)

AUDIOBOOK_TTS_RUNTIME_MODEL_IDS: Final[dict[str, str]] = {
    DEFAULT_AUDIOBOOK_TTS_MODEL: DEFAULT_AUDIOBOOK_TTS_MODEL,
    COSYVOICE_V35_PLUS_MODEL_ID: COSYVOICE_V35_PLUS_MODEL_ID,
    MINIMAX_SPEECH_28_HD_MODEL: "MiniMax/speech-2.8-hd",
    MINIMAX_SPEECH_28_TURBO_MODEL: "MiniMax/speech-2.8-turbo",
}

AUDIOBOOK_TTS_MODEL_CATALOG: Final[dict[str, dict[str, Any]]] = {
    DEFAULT_AUDIOBOOK_TTS_MODEL: {
        "name": "Qwen3-TTS Instruct Flash",
        "description": "默认模型，{voice_count} 个可用音色，支持自然语言 instructions",
        "catalog_note": "覆盖普通话、多语种和方言，适合整本批量生成。",
        "price_per_10k": 1.0,
        "cost_level": "low",
        "quality_level": "medium_high",
        "priority": 3,
        "features": ("默认模型", "{voice_count} 音色", "自然语言指令"),
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
        "price_per_10k": 2.0,
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
        "price_per_10k": 6.0,
        "cost_level": "medium",
        "quality_level": "high",
        "priority": 4,
        "features": ("高音质", "语气词标签", "{voice_count} 音色"),
        "capabilities": {
            "has_system_voices": True,
            "requires_custom_voice": False,
            "supports_voice_clone": False,
            "supports_voice_design": False,
            "supports_voice_tuning": False,
        },
    },
    MINIMAX_SPEECH_28_TURBO_MODEL: {
        "name": "MiniMax Speech 2.8 Turbo",
        "description": "低延迟模型，{voice_count} 个可用音色，适合高并发生成",
        "catalog_note": "适合高并发批量生成和成本优先场景。",
        "price_per_10k": 3.0,
        "cost_level": "low",
        "quality_level": "medium",
        "priority": 5,
        "features": ("低延迟", "高并发", "{voice_count} 音色"),
        "capabilities": {
            "has_system_voices": True,
            "requires_custom_voice": False,
            "supports_voice_clone": False,
            "supports_voice_design": False,
            "supports_voice_tuning": False,
        },
    },
}

_AUDIOBOOK_TTS_MODEL_ALIASES: Final[dict[str, str]] = {
    "qwen3_tts": DEFAULT_AUDIOBOOK_TTS_MODEL,
    "qwen3-tts": DEFAULT_AUDIOBOOK_TTS_MODEL,
    "qwen3-tts-flash": DEFAULT_AUDIOBOOK_TTS_MODEL,
    "qwen3-tts-instruct": DEFAULT_AUDIOBOOK_TTS_MODEL,
    "qwen3-tts-instruct-flash": DEFAULT_AUDIOBOOK_TTS_MODEL,
    # qwen3-tts-plus is not currently registered for audiobook synthesis.
    "qwen3-tts-plus": DEFAULT_AUDIOBOOK_TTS_MODEL,
    "cosyvoice-v3-plus": COSYVOICE_V35_PLUS_MODEL_ID,
    "cosyvoice_v3_plus": COSYVOICE_V35_PLUS_MODEL_ID,
    "cosyvoice-v3.5-plus": COSYVOICE_V35_PLUS_MODEL_ID,
    "minimax-speech-2.8": MINIMAX_SPEECH_28_HD_MODEL,
    "minimax-speech-2.8-hd": MINIMAX_SPEECH_28_HD_MODEL,
    "minimax-speech-2.8-turbo": MINIMAX_SPEECH_28_TURBO_MODEL,
    "minimax/speech-2.8-hd": MINIMAX_SPEECH_28_HD_MODEL,
    "minimax/speech-2.8-turbo": MINIMAX_SPEECH_28_TURBO_MODEL,
    "minimax/speech-2.8": MINIMAX_SPEECH_28_HD_MODEL,
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
    if lowered.startswith("qwen3-tts"):
        return DEFAULT_AUDIOBOOK_TTS_MODEL

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


def get_audiobook_tts_model_metadata(model: Any) -> dict[str, Any]:
    normalized = normalize_audiobook_tts_model(model, default="")
    if normalized not in AUDIOBOOK_TTS_MODEL_CATALOG:
        return {}
    metadata = dict(AUDIOBOOK_TTS_MODEL_CATALOG[normalized])
    metadata["id"] = normalized
    metadata["features"] = list(metadata.get("features") or [])
    return metadata


def get_audiobook_tts_model_price_per_10k(model: Any, *, default: float | None = None) -> float | None:
    metadata = get_audiobook_tts_model_metadata(model)
    if not metadata:
        return default
    try:
        return float(metadata.get("price_per_10k"))
    except (TypeError, ValueError):
        return default
