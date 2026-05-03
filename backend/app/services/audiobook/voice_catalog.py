"""Shared voice catalog for TTS models (loaded from JSON in /shared)."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import QWEN3_TTS_INSTRUCT_SUPPORTED_VOICES
from .tts_model_ids import DEFAULT_AUDIOBOOK_TTS_MODEL, normalize_audiobook_tts_model

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


class VoiceCatalogError(RuntimeError):
    """Raised when the voice catalog cannot be loaded."""


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
    filename = _filename_for_model(normalized_model)
    library_path = _resolve_voice_library_path(filename)
    if not library_path.exists():
        raise VoiceCatalogError(f"Voice catalog not found at {library_path}")

    try:
        raw = json.loads(library_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive guardrail
        raise VoiceCatalogError(f"Failed to parse {library_path}: {exc}") from exc

    raw_voices: List[Dict[str, Any]] = raw.get("voices") or []
    voices = _filter_voices_for_model(model, raw_voices)
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
