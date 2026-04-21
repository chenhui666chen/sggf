from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.model_resolution import normalize_model_id


_LEGACY_MODEL_KEYS = {
    "cosyvoice-v3.5-plus": ("cosyvoice-v3-plus",),
}


def parse_project_audio_config(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_audio_fx(config: Dict[str, Any]) -> Optional[dict]:
    audio_fx = config.get("audio_fx")
    return audio_fx if isinstance(audio_fx, dict) else None


def get_characters_for_model(config: Dict[str, Any], tts_model: str) -> List[dict]:
    requested_model = (normalize_model_id(tts_model) or "").strip() or "qwen3-tts-instruct-flash"
    tts_models = config.get("tts_models")
    if isinstance(tts_models, dict):
        candidate_keys = (requested_model, *_LEGACY_MODEL_KEYS.get(requested_model, ()))
        for candidate_key in candidate_keys:
            model_cfg = tts_models.get(candidate_key)
            if isinstance(model_cfg, dict):
                chars = model_cfg.get("characters") or []
                return list(chars) if isinstance(chars, list) else []

    # legacy: single shared character config
    chars = config.get("characters") or []
    return list(chars) if isinstance(chars, list) else []


def set_characters_for_model(config: Dict[str, Any], tts_model: str, characters: List[dict]) -> Dict[str, Any]:
    tts_model = (normalize_model_id(tts_model) or "").strip() or "qwen3-tts-instruct-flash"
    tts_models = config.get("tts_models")
    if not isinstance(tts_models, dict):
        tts_models = {}
        config["tts_models"] = tts_models

    model_cfg = tts_models.get(tts_model)
    if not isinstance(model_cfg, dict):
        model_cfg = {}
        tts_models[tts_model] = model_cfg

    model_cfg["characters"] = list(characters or [])

    # backward-compat: keep the default model mirrored at top-level
    if tts_model in {"qwen3-tts-instruct-flash", "qwen3-tts-flash"}:
        config["characters"] = list(characters or [])

    return config


def set_audio_fx(config: Dict[str, Any], audio_fx: Optional[dict]) -> Dict[str, Any]:
    if audio_fx is None:
        config.pop("audio_fx", None)
        return config
    config["audio_fx"] = audio_fx
    return config
