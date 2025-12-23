"""Shared voice catalog for TTS models (loaded from JSON in /shared)."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

VOICE_FILENAMES_BY_MODEL = {
    "qwen3-tts-flash": "qwen3_tts_voices.json",
    "cosyvoice-v3-plus": "cosyvoice_v3_plus_voices.json",
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
    model = (model or "").strip()
    if model in VOICE_FILENAMES_BY_MODEL:
        return VOICE_FILENAMES_BY_MODEL[model]
    if model.startswith("qwen3-tts"):
        return VOICE_FILENAMES_BY_MODEL["qwen3-tts-flash"]
    return VOICE_FILENAMES_BY_MODEL["qwen3-tts-flash"]


class VoiceCatalogError(RuntimeError):
    """Raised when the voice catalog cannot be loaded."""


def _read_catalog_for_model(model: str) -> Dict[str, Any]:
    filename = _filename_for_model(model)
    library_path = _resolve_voice_library_path(filename)
    if not library_path.exists():
        raise VoiceCatalogError(f"Voice catalog not found at {library_path}")

    try:
        raw = json.loads(library_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive guardrail
        raise VoiceCatalogError(f"Failed to parse {library_path}: {exc}") from exc

    voices: List[Dict[str, Any]] = raw.get("voices") or []
    voices_by_id: Dict[str, Dict[str, Any]] = {voice["id"]: voice for voice in voices if voice.get("id")}
    meta = {
        "model": raw.get("model", model or "qwen3-tts-flash"),
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
    """Backward-compatible default (Qwen3-TTS Flash)."""
    return load_voice_catalog_for_model("qwen3-tts-flash")


def list_supported_voices(model: str = "qwen3-tts-flash") -> List[Dict[str, Any]]:
    """Return the raw voice entries from the shared catalog."""
    return list(load_voice_catalog_for_model(model)["voices"])


def get_voice_entry(voice_id: str, model: str = "qwen3-tts-flash") -> Optional[Dict[str, Any]]:
    """Get a single voice entry by ID."""
    return load_voice_catalog_for_model(model)["voices_by_id"].get(voice_id)


def get_voice_catalog_meta(model: str = "qwen3-tts-flash") -> Dict[str, Any]:
    """Expose catalog metadata (model, updated_at, source, voice_count)."""
    return dict(load_voice_catalog_for_model(model)["meta"])
