from __future__ import annotations

import os
from typing import Any, Dict, Optional


def _read_str(value: Any, default: str) -> str:
    raw = value if value is not None else default
    return str(raw).strip()


def _read_flag(value: Any) -> Optional[bool]:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    return raw not in {"0", "false", "no", "off"}


def _read_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return int(default)


def resolve_image_edit_adapter_name(
    image_cfg: Dict[str, Any],
    *,
    purpose: str,
    default_adapter: str = "wan_image_edit",
) -> str:
    base_adapter = _read_str(
        image_cfg.get("image_edit_adapter"),
        os.getenv("DREAMWEAVER_IMAGE_EDIT_ADAPTER", default_adapter),
    )
    high_adapter = _read_str(
        image_cfg.get("image_edit_high_adapter"),
        os.getenv("DREAMWEAVER_IMAGE_EDIT_HIGH_ADAPTER", ""),
    )
    high_policy = _read_str(
        image_cfg.get("image_edit_high_policy"),
        os.getenv("DREAMWEAVER_IMAGE_EDIT_HIGH_POLICY", "auto"),
    ).lower()

    if not high_adapter:
        return base_adapter
    if high_policy in {"never", "off", "false", "0"}:
        return base_adapter
    if high_policy in {"always", "on", "true", "1"}:
        return high_adapter
    if purpose in {"library_character_view", "keyframe_head"}:
        return high_adapter
    return base_adapter


def resolve_image_edit_multi_ref(*, image_cfg: Dict[str, Any], adapter_name: str) -> bool:
    raw = _read_flag(image_cfg.get("image_edit_multi_ref"))
    if raw is None:
        raw = _read_flag(os.getenv("DREAMWEAVER_IMAGE_EDIT_MULTI_REF"))
    if raw is None:
        return str(adapter_name or "").strip().lower().startswith("qwen_image_edit")
    return bool(raw)


def resolve_image_edit_ref_max_images(*, image_cfg: Dict[str, Any], default_max: int = 3) -> int:
    raw = image_cfg.get("image_edit_ref_max_images")
    if raw is None:
        raw = os.getenv("DREAMWEAVER_IMAGE_EDIT_REF_MAX_IMAGES", str(default_max))
    value = _read_int(raw, default_max)
    return max(0, min(int(value), 8))
