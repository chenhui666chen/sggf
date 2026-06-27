"""Feature gate helpers for multi-model chapter review."""

from __future__ import annotations

import json
from typing import Any, Optional

from app.core.config import settings


VALID_REVIEW_PRESETS = {"balanced_3", "key_chapter_5", "deep_7"}


def get_multi_model_review_config(project_context: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return normalized multi-model review config when both gates are enabled."""

    if not getattr(settings, "ENABLE_MULTI_MODEL_REVIEW", False):
        return None

    raw = project_context.get("review_config")
    if not raw:
        return None

    try:
        cfg = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(cfg, dict):
        return None

    mmr = cfg.get("multi_model_review") or {}
    if not isinstance(mmr, dict) or not mmr.get("enabled"):
        return None

    preset = _normalize_preset(
        mmr.get("preset"),
        getattr(settings, "MULTI_MODEL_REVIEW_DEFAULT_PRESET", "balanced_3"),
    )
    mmr = dict(mmr)
    mmr["preset"] = preset
    mmr["manual_depth"] = _normalize_preset(mmr.get("manual_depth"), preset)
    mmr["key_chapter_depth"] = _normalize_key_depth(mmr.get("key_chapter_depth"))
    mmr["chief_model"] = (
        mmr.get("chief_model")
        or getattr(settings, "MULTI_MODEL_REVIEW_CHIEF_MODEL", "deepseek-v4-pro")
    )
    return mmr


def should_trigger_multi_model_review(
    project_context: dict[str, Any],
    chapter_number: int,
    is_manual: bool = False,
) -> tuple[bool, Optional[str]]:
    """Return whether this review should use the multi-model path and which preset."""

    cfg = get_multi_model_review_config(project_context)
    if cfg is None:
        return False, None

    if is_manual:
        return True, cfg["manual_depth"]

    scenarios = cfg.get("auto_scenarios") or []
    if "first_chapter" in scenarios and chapter_number == 1:
        return True, cfg["key_chapter_depth"]
    if "key_chapter" in scenarios and _is_key_chapter(project_context, chapter_number):
        return True, cfg["key_chapter_depth"]
    if "final_chapter" in scenarios and _is_final_chapter(project_context, chapter_number):
        return True, cfg["key_chapter_depth"]

    return False, None


def _normalize_preset(value: Any, default: str) -> str:
    value_str = str(value or "").strip()
    return value_str if value_str in VALID_REVIEW_PRESETS else default


def _normalize_key_depth(value: Any) -> str:
    value_str = str(value or "").strip()
    return value_str if value_str in {"key_chapter_5", "deep_7"} else "key_chapter_5"


def _is_key_chapter(project_context: dict[str, Any], chapter_number: int) -> bool:
    return chapter_number == 1 or chapter_number % 10 == 0


def _is_final_chapter(project_context: dict[str, Any], chapter_number: int) -> bool:
    try:
        planned_max = int(project_context.get("planned_chapters_max") or 0)
    except (TypeError, ValueError):
        return False
    return planned_max > 0 and chapter_number >= planned_max

