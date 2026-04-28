from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from core.model_resolution import normalize_model_id

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODELS_CONFIG_PATH = PROJECT_ROOT / "config" / "models.yaml"

_GROUP_MODEL_IDS: dict[str, tuple[str, ...]] = {
    "image_generation": (
        "wan2.6-t2i",
        "qwen-image-2.0",
        "qwen-image-2.0-pro",
        "wan2.7-image",
        "doubao-seedream-4-5",
        "doubao-seedream-5-0",
        "kling-v3-image-generation",
        "kling-v3-omni-image-generation",
    ),
    "image_edit": (
        "qwen-image-edit-plus",
        "qwen-image-edit-max",
    ),
    "video_generation": (
        "wan2.7-t2v",
        "wan2.6-t2v-fast",
        "wan2.7-i2v",
        "doubao-seedance-2-0",
        "doubao-seedance-2-0-fast",
        "doubao-seedance-1-5-pro",
        "kling-v3-video-generation",
        "kling-v3-omni-video-generation",
        "pixverse-v6-t2v",
        "vidu-q3-pro-text2video",
        "vidu-q3-pro-img2video",
        "vidu-q3-pro-start-end2video",
    ),
    "video_edit": (
        "wan2.7-videoedit",
        "doubao-seedance-2-0",
        "kling-v3-video-generation",
    ),
    "motion": (
        "wan2.7-i2v",
        "wan2.7-r2v",
        "doubao-seedance-2-0",
        "kling-v3-video-generation",
        "kling-v3-omni-video-generation",
        "pixverse-v6-t2v",
    ),
    "audio_music": (
        "mureka-o1-instrumental",
    ),
    "audio_sound_effect": (
        "vidu-timing2audio",
    ),
    "audio_speech": (
        "qwen3-tts-instruct-flash",
        "cosyvoice-v3.5-plus",
        "minimax-speech-2.8-hd",
        "minimax-speech-2.8-turbo",
    ),
    "vision_review": (
        "qwen3-vl-plus",
        "qwen3.5-omni-plus",
    ),
    "dreamweaver_image": (
        "wan2.6-t2i",
        "qwen-image-2.0",
        "qwen-image-2.0-pro",
        "wan2.7-image",
        "doubao-seedream-4-5",
        "doubao-seedream-5-0",
        "kling-v3-image-generation",
        "kling-v3-omni-image-generation",
        "qwen-image-edit-plus",
    ),
    "dreamweaver_video": (
        "wan2.7-t2v",
        "wan2.6-t2v-fast",
        "wan2.7-i2v",
        "doubao-seedance-2-0",
        "doubao-seedance-2-0-fast",
        "doubao-seedance-1-5-pro",
        "kling-v3-video-generation",
        "kling-v3-omni-video-generation",
        "pixverse-v6-t2v",
        "vidu-q3-pro-text2video",
        "vidu-q3-pro-img2video",
        "vidu-q3-pro-start-end2video",
    ),
    "dreamweaver_video_edit": (
        "wan2.7-videoedit",
        "doubao-seedance-2-0",
        "kling-v3-video-generation",
    ),
    "dreamweaver_vision": (
        "qwen3-vl-plus",
        "qwen3.5-omni-plus",
    ),
}

_DEFAULT_MODEL_IDS: dict[str, str] = {
    "asset_studio_image_generation": "wan2.7-image",
    "asset_studio_image_edit": "qwen-image-edit-plus",
    "asset_studio_video_generation": "wan2.7-t2v",
    "asset_studio_video_edit": "wan2.7-videoedit",
    "asset_studio_motion": "wan2.7-i2v",
    "asset_studio_audio_music": "mureka-o1-instrumental",
    "asset_studio_audio_sound_effect": "vidu-timing2audio",
    "asset_studio_audio_speech": "qwen3-tts-instruct-flash",
    "asset_studio_vision_review": "qwen3-vl-plus",
    "dreamweaver_image": "qwen-image-2.0-pro",
    "dreamweaver_video": "wan2.7-t2v",
    "dreamweaver_video_edit": "wan2.7-videoedit",
    "dreamweaver_vision": "qwen3-vl-plus",
}

_AUDIO_DURATION_OPTIONS: dict[str, tuple[int, ...]] = {
    "music": (15, 30, 45, 60),
    "sound-effect": (3, 5, 8, 10),
}


def _normalize_public_model_id(model_id: str) -> str:
    normalized = normalize_model_id(model_id)
    return str(normalized or model_id).strip()


def _load_models_payload() -> list[dict[str, Any]]:
    payload = yaml.safe_load(MODELS_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    models = payload.get("models")
    if not isinstance(models, list):
        raise ValueError(f"models.yaml 格式无效: {MODELS_CONFIG_PATH}")
    return [item for item in models if isinstance(item, dict)]


@lru_cache(maxsize=1)
def get_models_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in _load_models_payload():
        model_id = str(item.get("id") or "").strip()
        if model_id:
            index[model_id] = item
    return index


def _resolve_model_record(public_model_id: str) -> tuple[str, dict[str, Any]]:
    models_index = get_models_index()
    normalized_model_id = _normalize_public_model_id(public_model_id)
    record = models_index.get(normalized_model_id)
    if record is not None:
        return normalized_model_id, record
    direct_record = models_index.get(public_model_id)
    if direct_record is not None:
        return public_model_id, direct_record
    raise KeyError(f"未找到模型配置: {public_model_id}")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clip_helper_text(value: str, limit: int = 84) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _extract_duration_values(record: dict[str, Any]) -> tuple[float, ...]:
    constraints = record.get("constraints") if isinstance(record.get("constraints"), dict) else {}
    raw_duration = constraints.get("duration")
    values: list[float] = []

    if isinstance(raw_duration, list):
        for value in raw_duration:
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
    elif isinstance(raw_duration, dict):
        for key in ("values", "options", "supported_values", "allowed_values"):
            candidate = raw_duration.get(key)
            if not isinstance(candidate, list):
                continue
            for value in candidate:
                try:
                    values.append(float(value))
                except (TypeError, ValueError):
                    continue
        if not values:
            for key in ("min", "default", "max"):
                try:
                    candidate = float(raw_duration.get(key))
                except (TypeError, ValueError):
                    continue
                values.append(candidate)

    unique_sorted = sorted({round(value, 4) for value in values})
    return tuple(unique_sorted)


def _build_option(public_model_id: str) -> dict[str, Any]:
    catalog_model_key, record = _resolve_model_record(public_model_id)
    summary = _clean_text(record.get("summary"))
    recommended = record.get("recommended_scenarios") if isinstance(record.get("recommended_scenarios"), list) else []
    helper_source = summary or _clean_text(recommended[0] if recommended else "")

    return {
        "model_id": public_model_id,
        "catalog_model_key": catalog_model_key,
        "label": _clean_text(record.get("name")) or public_model_id,
        "helper": _clip_helper_text(helper_source or public_model_id),
        "provider": _clean_text(record.get("provider")),
        "category": _clean_text(record.get("category")) or _clean_text(record.get("provider")),
        "status": _clean_text(record.get("status")) or "active",
        "modalities": [str(value).strip() for value in (record.get("modality") or []) if str(value).strip()],
        "tags": [str(value).strip() for value in (record.get("tags") or []) if str(value).strip()],
        "duration_options": list(_extract_duration_values(record)),
    }


@lru_cache(maxsize=1)
def get_asset_studio_model_manifest() -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for group_key, model_ids in _GROUP_MODEL_IDS.items():
        groups[group_key] = [_build_option(model_id) for model_id in model_ids]

    return {
        "catalog_version": "2026-04-28",
        "defaults": dict(_DEFAULT_MODEL_IDS),
        "groups": groups,
    }


@lru_cache(maxsize=1)
def get_asset_studio_model_sets() -> dict[str, set[str]]:
    manifest = get_asset_studio_model_manifest()
    result: dict[str, set[str]] = {}
    for group_key, options in manifest["groups"].items():
        result[group_key] = {
            str(option.get("model_id")).strip()
            for option in options
            if str(option.get("model_id")).strip()
        }
    return result


@lru_cache(maxsize=1)
def get_asset_studio_video_duration_options() -> dict[str, tuple[float, ...]]:
    model_sets = get_asset_studio_model_sets()
    relevant_model_ids = (
        model_sets["video_generation"]
        | model_sets["video_edit"]
        | model_sets["motion"]
    )
    result: dict[str, tuple[float, ...]] = {}
    for model_id in sorted(relevant_model_ids):
        _, record = _resolve_model_record(model_id)
        duration_values = _extract_duration_values(record)
        if duration_values:
            result[model_id] = duration_values
    return result


def get_asset_studio_audio_duration_options() -> dict[str, tuple[int, ...]]:
    return dict(_AUDIO_DURATION_OPTIONS)


def get_asset_studio_default_model_id(key: str, fallback: str) -> str:
    return str(_DEFAULT_MODEL_IDS.get(key) or fallback).strip() or fallback
