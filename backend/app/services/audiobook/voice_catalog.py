"""Shared voice catalog for TTS models (loaded from JSON in /shared)."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import QWEN3_TTS_INSTRUCT_SUPPORTED_VOICES
from .tts_model_ids import (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    get_audiobook_tts_model_metadata,
    normalize_audiobook_tts_model,
)

logger = logging.getLogger(__name__)

VOICE_FILENAMES_BY_MODEL = {
    "qwen3-tts-instruct-flash": "qwen3_tts_voices.json",
    "qwen3-tts-flash": "qwen3_tts_voices.json",
    "cosyvoice-v3.5-plus": "cosyvoice_v3_5_plus_voices.json",
    "cosyvoice-v3-plus": "cosyvoice_v3_5_plus_voices.json",
    "minimax-speech-2.8-hd": "minimax_speech_2_8_voices.json",
    "minimax-speech-2.8-turbo": "minimax_speech_2_8_voices.json",
    # 兼容别名
    "minimax-speech-2.8": "minimax_speech_2_8_voices.json",
    "mimo-v2.5-tts": "mimo_v2_5_tts_voices.json",
    "stepaudio-2.5-tts": "stepaudio_2_5_tts_voices.json",
    SEED_TTS_20_EXPRESSIVE_MODEL: "seed_tts_2_0_voices.json",
}

VOICE_PROFILE_FILENAMES_BY_MODEL = {
    "qwen3-tts-instruct-flash": "qwen3_tts_voice_profiles.json",
    "qwen3-tts-flash": "qwen3_tts_voice_profiles.json",
}


def _resolve_voice_library_path(filename: str) -> Path:
    """Locate the shared voice catalog anywhere in the repo tree."""
    current = Path(__file__).resolve()
    for ancestor in current.parents:
        candidate = ancestor / "shared" / filename
        if candidate.exists():
            return candidate
    # Fallback to previous default (relative to backend/app)
    return current.parents[3] / "shared" / filename


def _filename_for_model(model: str) -> str:
    model = normalize_audiobook_tts_model(model)
    if model in VOICE_FILENAMES_BY_MODEL:
        return VOICE_FILENAMES_BY_MODEL[model]
    # 兼容别名匹配
    if model.startswith("minimax-speech"):
        return VOICE_FILENAMES_BY_MODEL["minimax-speech-2.8-hd"]
    if model.startswith("qwen3-tts"):
        return VOICE_FILENAMES_BY_MODEL["qwen3-tts-instruct-flash"]
    return VOICE_FILENAMES_BY_MODEL["qwen3-tts-instruct-flash"]


def _profile_filename_for_model(model: str) -> Optional[str]:
    model = normalize_audiobook_tts_model(model)
    if model in VOICE_PROFILE_FILENAMES_BY_MODEL:
        return VOICE_PROFILE_FILENAMES_BY_MODEL[model]
    if model.startswith("qwen3-tts"):
        return VOICE_PROFILE_FILENAMES_BY_MODEL["qwen3-tts-instruct-flash"]
    return None


class VoiceCatalogError(RuntimeError):
    """Raised when the voice catalog cannot be loaded."""


def _read_voice_profiles_for_model(model: str) -> Dict[str, Dict[str, Any]]:
    filename = _profile_filename_for_model(model)
    if not filename:
        return {}

    profile_path = _resolve_voice_library_path(filename)
    if not profile_path.exists():
        return {}

    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive guardrail
        raise VoiceCatalogError(f"Failed to parse {profile_path}: {exc}") from exc

    profiles = raw.get("voice_profiles") or {}
    if not isinstance(profiles, dict):
        return {}
    return {
        str(voice_id): profile
        for voice_id, profile in profiles.items()
        if isinstance(profile, dict)
    }


def _merge_voice_profiles(model: str, voices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    profiles = _read_voice_profiles_for_model(model)
    if not profiles:
        return list(voices)

    enriched: List[Dict[str, Any]] = []
    for voice in voices:
        voice_id = str(voice.get("id") or voice.get("speaker") or "")
        profile = profiles.get(voice_id)
        if profile and not voice.get("voice_profile"):
            voice = dict(voice)
            voice["voice_profile"] = profile
        enriched.append(voice)
    return enriched


def _filter_voices_for_model(model: str, voices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_model = normalize_audiobook_tts_model(model)
    if normalized_model.startswith("qwen3-tts"):
        supported = QWEN3_TTS_INSTRUCT_SUPPORTED_VOICES
        return [
            voice
            for voice in voices
            if (voice.get("id") or voice.get("speaker")) in supported
            or voice.get("speaker") in supported
        ]
    return list(voices)


def _read_catalog_for_model(model: str) -> Dict[str, Any]:
    normalized_model = normalize_audiobook_tts_model(model)
    model_meta = get_audiobook_tts_model_metadata(normalized_model)
    capabilities = model_meta.get("capabilities") if isinstance(model_meta.get("capabilities"), dict) else {}
    if capabilities and not capabilities.get("has_system_voices", True):
        return {
            "meta": {
                "model": normalized_model,
                "updated_at": None,
                "source": "model-capabilities: no system voices",
                "voice_count": 0,
            },
            "voices": [],
            "voices_by_id": {},
        }

    filename = _filename_for_model(normalized_model)
    library_path = _resolve_voice_library_path(filename)
    if not library_path.exists():
        raise VoiceCatalogError(f"Voice catalog not found at {library_path}")

    try:
        raw = json.loads(library_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive guardrail
        raise VoiceCatalogError(f"Failed to parse {library_path}: {exc}") from exc

    raw_voices: List[Dict[str, Any]] = raw.get("voices") or []
    voices = _merge_voice_profiles(model, _filter_voices_for_model(model, raw_voices))
    voices_by_id: Dict[str, Dict[str, Any]] = {voice["id"]: voice for voice in voices if voice.get("id")}
    meta = {
        "model": normalized_model or raw.get("model", DEFAULT_AUDIOBOOK_TTS_MODEL),
        "updated_at": raw.get("updated_at"),
        "source": raw.get("source"),
        "voice_count": len(voices),
    }
    return {"meta": meta, "voices": voices, "voices_by_id": voices_by_id}


@lru_cache(maxsize=8)
def load_voice_catalog_for_model(model: str) -> Dict[str, Any]:
    """Load the voice catalog for a specific model and cache it."""
    catalog = _read_catalog_for_model(model)
    logger.info(
        "Loaded %s voices for %s (source=%s)",
        catalog["meta"]["voice_count"],
        catalog["meta"]["model"],
        catalog["meta"]["source"],
    )
    return catalog


def load_voice_catalog() -> Dict[str, Any]:
    """Backward-compatible default (Qwen3-TTS Instruct Flash)."""
    return load_voice_catalog_for_model("qwen3-tts-instruct-flash")


def list_supported_voices(model: str = "qwen3-tts-instruct-flash") -> List[Dict[str, Any]]:
    """Return the raw voice entries from the shared catalog."""
    return list(load_voice_catalog_for_model(model)["voices"])


def get_voice_entry(voice_id: str, model: str = "qwen3-tts-instruct-flash") -> Optional[Dict[str, Any]]:
    """Get a single voice entry by ID."""
    return load_voice_catalog_for_model(model)["voices_by_id"].get(voice_id)


def get_voice_catalog_meta(model: str = "qwen3-tts-instruct-flash") -> Dict[str, Any]:
    """Expose catalog metadata (model, updated_at, source, voice_count)."""
    return dict(load_voice_catalog_for_model(model)["meta"])


# ---------------------------------------------------------------------------
# TTS 试听名言列表
# ---------------------------------------------------------------------------

_PREVIEW_QUOTES_CACHE: Optional[List[str]] = None
_DEFAULT_PREVIEW_QUOTE = "当你真的喜欢一个人的时候就容易说傻话办蠢事。"
_DEFAULT_EN_PREVIEW_QUOTE = "When you really like someone, it's easy to say silly things and do foolish things."


def _load_preview_quotes() -> List[str]:
    """加载 shared/tts_preview_quotes.json 中的名言列表（带缓存）。"""
    global _PREVIEW_QUOTES_CACHE
    if _PREVIEW_QUOTES_CACHE is not None:
        return _PREVIEW_QUOTES_CACHE
    path = _resolve_voice_library_path("tts_preview_quotes.json")
    if not path.exists():
        _PREVIEW_QUOTES_CACHE = [_DEFAULT_PREVIEW_QUOTE]
        return _PREVIEW_QUOTES_CACHE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        quotes = [str(q).strip() for q in (data.get("quotes") or []) if str(q).strip()]
    except Exception:
        quotes = []
    if not quotes:
        quotes = [_DEFAULT_PREVIEW_QUOTE]
    _PREVIEW_QUOTES_CACHE = quotes
    return quotes


def get_preview_quote_for_voice(model: str, voice_id: str) -> str:
    """根据音色在 catalog 中的索引从名言列表选取试听文本。

    - 英文音色（voice_id 以 en_ 开头）返回英文文本
    - 找不到音色时返回第一条名言作为 fallback
    - 名言列表不足时按索引取模循环使用
    """
    voice_id = str(voice_id or "").strip()
    if voice_id.startswith("en_"):
        return _DEFAULT_EN_PREVIEW_QUOTE

    quotes = _load_preview_quotes()
    try:
        voices = list(load_voice_catalog_for_model(model).get("voices") or [])
        for i, v in enumerate(voices):
            vid = str(v.get("id") or v.get("speaker") or "")
            if vid == voice_id:
                preview_text = str(v.get("preview_text") or "").strip()
                if preview_text:
                    return preview_text
                return quotes[i % len(quotes)]
    except Exception:
        pass
    return quotes[0] if quotes else _DEFAULT_PREVIEW_QUOTE
