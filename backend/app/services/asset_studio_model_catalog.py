from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from core.model_resolution import normalize_model_id, pick_resolution_label

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODELS_CONFIG_PATH = PROJECT_ROOT / "config" / "models.yaml"

# Asset Studio 视频页可选档位（= DreamWeaver 视频宇宙）。motion / video_edit 从这里派生，
# 未进入该清单的档案条目（如 pixverse-c1-r2v）不会自动获得 UI 入口。
_VIDEO_UNIVERSE_MODEL_IDS: tuple[str, ...] = (
    "wan3.0-video",
    "doubao-seedance-2-5",
    "doubao-seedance-2-0",
    "doubao-seedance-2-0-fast",
    "kling/kling-v3-video-generation",
    "kling/kling-v3-omni-video-generation",
    "pixverse-v6-t2v",
    "vidu-q3-pro-text2video",
    "vidu-q3-pro-img2video",
    "vidu-q3-pro-start-end2video",
)

_GROUP_MODEL_IDS: dict[str, tuple[str, ...]] = {
    "image_generation": (
        "qwen-image-3.0",
        "qwen-image-3.0-pro",
        "wan2.7-image-pro",
        "doubao-seedream-5-0",
        "doubao-seedream-5-0-pro",
        "kling/kling-v3-image-generation",
        "kling/kling-v3-omni-image-generation",
    ),
    "image_edit": (
        "qwen-image-edit-plus",
        "qwen-image-edit-max",
    ),
    "video_generation": _VIDEO_UNIVERSE_MODEL_IDS,
    "audio_music": (
        "mureka-o1-instrumental",
    ),
    "audio_sound_effect": (
        "seed-audio-1.0",
        "qwen-audio-3.1-tts-next",
    ),
    "audio_scene": (
        "seed-audio-1.0",
    ),
    "audio_speech": (
        "qwen-audio-3.1-tts-flash",
        "cosyvoice-v3.5-plus",
        "minimax-speech-2.8-hd",
        "minimax-speech-2.8-turbo",
    ),
    "vision_review": (
        "qwen3-vl-plus",
        "qwen3.5-omni-plus",
    ),
    "dreamweaver_image": (
        "qwen-image-3.0-pro",
        "qwen-image-3.0",
        "wan2.7-image-pro",
        "doubao-seedream-5-0",
        "doubao-seedream-5-0-pro",
        "kling/kling-v3-image-generation",
        "kling/kling-v3-omni-image-generation",
        "qwen-image-edit-plus",
    ),
    "dreamweaver_video": _VIDEO_UNIVERSE_MODEL_IDS,
    "dreamweaver_vision": (
        "qwen3-vl-plus",
        "qwen3.5-omni-plus",
    ),
}

_DEFAULT_MODEL_IDS: dict[str, str] = {
    "asset_studio_image_generation": "qwen-image-3.0",
    "asset_studio_image_edit": "qwen-image-edit-plus",
    "asset_studio_video_generation": "wan3.0-video",
    "asset_studio_video_edit": "wan3.0-video",
    "asset_studio_motion": "wan3.0-video",
    "asset_studio_audio_music": "mureka-o1-instrumental",
    "asset_studio_audio_sound_effect": "seed-audio-1.0",
    "asset_studio_audio_scene": "seed-audio-1.0",
    "asset_studio_audio_speech": "qwen-audio-3.1-tts-flash",
    "asset_studio_vision_review": "qwen3-vl-plus",
    "dreamweaver_image": "qwen-image-3.0-pro",
    "dreamweaver_video": "wan3.0-video",
    "dreamweaver_video_edit": "wan3.0-video",
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


def _derive_video_group(modality: str) -> tuple[str, ...]:
    """按 config/models.yaml 的 modality 声明在视频宇宙上派生分组。

    motion / video_edit 原来各有一份手写名单，代价是档案与 UI 长期脱钩：官方支持图生视频的
    kling-v3、vidu 两档进不了动作组，而 pixverse-v6-t2v 靠批量模板挂上的 motion_control 能力
    混进了组里（它档案只有 text_to_video）。派生后档案是唯一事实源；条目能否真正执行仍由
    backend/tests/test_asset_studio_model_catalog_image_line.py 校验 adapter 与运行时白名单。
    """
    models_index = get_models_index()
    return tuple(
        model_id
        for model_id in _VIDEO_UNIVERSE_MODEL_IDS
        if modality in (models_index.get(model_id, {}).get("modality") or [])
    )


_VIDEO_EDIT_MODEL_IDS = _derive_video_group("video_edit")
_GROUP_MODEL_IDS["motion"] = _derive_video_group("image_to_video")
_GROUP_MODEL_IDS["video_edit"] = _VIDEO_EDIT_MODEL_IDS
_GROUP_MODEL_IDS["dreamweaver_video_edit"] = _VIDEO_EDIT_MODEL_IDS


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


def _coerce_float_value(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _build_integer_ladder(duration_min: float, duration_max: float) -> tuple[float, ...]:
    if not duration_min.is_integer() or not duration_max.is_integer() or duration_max < duration_min:
        return ()
    return tuple(float(value) for value in range(int(duration_min), int(duration_max) + 1))


def _extract_duration_spec(record: dict[str, Any]) -> dict[str, Any]:
    """把 models.yaml 的两种 duration 写法归一成前端控件需要的形态。

    档位列表（[4,5,10,15]）只能渲染下拉；{min,max,default,supports_auto} 区间要交回
    min/max/step=1/default/supports_auto 让前端渲染滑块 + 数字输入 + 智能时长，同时把区间
    展开成逐秒阶梯——只认 duration_options 的旧调用方（含后端 VIDEO_DURATION_OPTIONS 兜底表）
    才不会退化成 min/default/max 三个点。
    """
    values = _extract_duration_values(record)
    constraints = record.get("constraints") if isinstance(record.get("constraints"), dict) else {}
    raw_duration = constraints.get("duration")
    if isinstance(raw_duration, dict):
        duration_min = _coerce_float_value(raw_duration.get("min"))
        duration_max = _coerce_float_value(raw_duration.get("max"))
        if duration_min is not None and duration_max is not None:
            duration_default = _coerce_float_value(raw_duration.get("default"))
            if duration_default is None:
                duration_default = duration_min
            ladder = _build_integer_ladder(duration_min, duration_max)
            return {
                "values": ladder or values,
                "min": duration_min,
                "max": duration_max,
                "step": 1.0,
                "default": duration_default,
                "supports_auto": bool(raw_duration.get("supports_auto")),
            }

    return {
        "values": values,
        "min": None,
        "max": None,
        "step": None,
        "default": None,
        "supports_auto": False,
    }


def _build_option(public_model_id: str) -> dict[str, Any]:
    catalog_model_key, record = _resolve_model_record(public_model_id)
    summary = _clean_text(record.get("summary"))
    recommended = record.get("recommended_scenarios") if isinstance(record.get("recommended_scenarios"), list) else []
    helper_source = summary or _clean_text(recommended[0] if recommended else "")
    duration_spec = _extract_duration_spec(record)

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
        "duration_options": list(duration_spec["values"]),
        "duration_min": duration_spec["min"],
        "duration_max": duration_spec["max"],
        "duration_step": duration_spec["step"],
        "duration_default": duration_spec["default"],
        "duration_supports_auto": duration_spec["supports_auto"],
    }


@lru_cache(maxsize=1)
def get_asset_studio_model_manifest() -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for group_key, model_ids in _GROUP_MODEL_IDS.items():
        groups[group_key] = [_build_option(model_id) for model_id in model_ids]

    return {
        "catalog_version": "2026-10-08",
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
        duration_values = _extract_duration_spec(record)["values"]
        if duration_values:
            result[model_id] = duration_values
    return result


def get_asset_studio_audio_duration_options() -> dict[str, tuple[int, ...]]:
    return dict(_AUDIO_DURATION_OPTIONS)


def get_asset_studio_default_model_id(key: str, fallback: str) -> str:
    return str(_DEFAULT_MODEL_IDS.get(key) or fallback).strip() or fallback


_PER_SECOND_UNIT = "每秒"

# pricing_info.unit 决定「每秒单价阶梯」放在哪个键：按秒计费的条目直接就是 tiers，
# 按 token 计费的条目（seedance 三档）只能放 per_second_estimate.tiers，两者不可混读。
_TOKEN_BASED_ESTIMATE_KEY = "per_second_estimate"


def _per_second_tiers(pricing_info: dict[str, Any]) -> list[dict[str, Any]]:
    if str(pricing_info.get("unit") or "").strip() == _PER_SECOND_UNIT:
        raw_tiers = pricing_info.get("tiers")
    else:
        estimate = pricing_info.get(_TOKEN_BASED_ESTIMATE_KEY)
        raw_tiers = estimate.get("tiers") if isinstance(estimate, dict) else None
    return [tier for tier in (raw_tiers or []) if isinstance(tier, dict)]


def resolve_video_price_per_second(
    *,
    model_id: str | None,
    width: int | None,
    height: int | None,
    audio_output: bool = True,
) -> float | None:
    """按「模型 × 短边分辨率档」取官方每秒价；取不到返回 None，由调用方拒单。

    档名与运行时下发给上游的 parameters["resolution"] 共用 pick_resolution_label，
    避免「按 720P 收钱、按 1080P 下单」这类错档。无声价只在显式 audio_output=False 时取，
    上游未单独公布无声价的条目回落含声档（档案里含声价恒不低于无声价，宁可多冻不欠收）。
    """
    normalized_width = int(width or 0)
    normalized_height = int(height or 0)
    if normalized_width <= 0 or normalized_height <= 0:
        return None

    record = get_models_index().get(_normalize_public_model_id(str(model_id or "")))
    if record is None:
        return None
    pricing_info = record.get("pricing_info")
    if not isinstance(pricing_info, dict):
        return None

    target_label = pick_resolution_label(normalized_width, normalized_height)
    for tier in _per_second_tiers(pricing_info):
        if str(tier.get("resolution") or "").strip().upper() != target_label:
            continue
        if not audio_output:
            silent_price = _coerce_float_value(tier.get("no_audio_price_per_second"))
            if silent_price is not None:
                return silent_price
        return _coerce_float_value(tier.get("price_per_second"))
    return None
