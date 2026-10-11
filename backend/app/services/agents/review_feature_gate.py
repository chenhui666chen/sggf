"""Feature gate helpers for multi-model chapter review."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.core.config import settings


VALID_REVIEW_PRESETS = {"balanced_3", "key_chapter_5", "deep_7"}
DEFAULT_AUTO_STRATEGY = {
    "regular": None,
    "opening": "key_chapter_5",
    "key": "key_chapter_5",
    "finale": "deep_7",
}


def get_multi_model_review_config(project_context: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return normalized multi-model review config when the project toggle is enabled."""

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
    if "auto_strategy" in mmr:
        mmr["auto_strategy"] = _normalize_auto_strategy(mmr.get("auto_strategy"))
    mmr["chief_model"] = (
        mmr.get("chief_model")
        or getattr(settings, "MULTI_MODEL_REVIEW_CHIEF_MODEL", "deepseek-pro")
    )
    return mmr


def should_trigger_multi_model_review(
    project_context: dict[str, Any],
    chapter_number: int,
    is_manual: bool = False,
    chapter_plan: str = "",
) -> tuple[bool, Optional[str]]:
    """Return whether this review should use the multi-model path and which preset."""

    cfg = get_multi_model_review_config(project_context)
    if cfg is None:
        return False, None

    if is_manual:
        manual_preset = _normalize_preset(
            project_context.get("manual_multi_model_review_preset"),
            cfg["manual_depth"],
        )
        return True, manual_preset

    if cfg.get("auto_strategy"):
        tier = resolve_chapter_review_tier(project_context, chapter_number, chapter_plan)
        preset = cfg["auto_strategy"].get(tier)
        return (True, preset) if preset else (False, None)

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


def _normalize_auto_strategy(value: Any) -> dict[str, Optional[str]]:
    if not isinstance(value, dict):
        return dict(DEFAULT_AUTO_STRATEGY)

    strategy: dict[str, Optional[str]] = {}
    for tier, default in DEFAULT_AUTO_STRATEGY.items():
        raw = value.get(tier, default)
        if raw in (None, "", False):
            strategy[tier] = None
        else:
            strategy[tier] = _normalize_preset(raw, default or "balanced_3")
    return strategy


def resolve_chapter_review_tier(
    project_context: dict[str, Any],
    chapter_number: int,
    chapter_plan: str = "",
) -> str:
    """Resolve chapter importance from chapter plan first, with chapter number as fallback."""

    text = str(chapter_plan or "")
    explicit_position = _extract_chapter_position(text)
    if explicit_position:
        tier = _tier_from_position(explicit_position)
        if tier:
            return tier

    inferred_tier = _infer_tier_from_text(text)
    if inferred_tier:
        return inferred_tier

    if _is_final_chapter(project_context, chapter_number):
        return "finale"
    if _is_key_chapter(project_context, chapter_number):
        return "opening" if chapter_number == 1 else "key"
    return "regular"


def _extract_chapter_position(text: str) -> str:
    match = re.search(r"(?:章节定位|本章定位)\s*[：:]\s*([^\n\r]+)", text)
    return match.group(1).strip() if match else ""


def _tier_from_position(position: str) -> Optional[str]:
    normalized = position.strip()
    if any(keyword in normalized for keyword in ("完结", "终局", "结局", "收官")):
        return "finale"
    if any(keyword in normalized for keyword in ("卷末", "大高潮", "最终战")):
        return "finale"
    if any(keyword in normalized for keyword in ("关键转折", "伏笔回收", "人物突破", "世界观揭示", "小高潮", "高潮")):
        return "key"
    if any(keyword in normalized for keyword in ("开篇", "第一章", "定调")):
        return "opening"
    if any(keyword in normalized for keyword in ("普通", "日常", "承接", "过渡")):
        return "regular"
    return None


def _infer_tier_from_text(text: str) -> Optional[str]:
    if not text.strip():
        return None
    if any(keyword in text for keyword in ("完结收束", "终局", "最终战", "收束全书", "结局")):
        return "finale"
    if any(keyword in text for keyword in ("大高潮", "卷末收束", "关键转折", "伏笔回收", "人物突破", "世界观揭示")):
        return "key"
    if any(keyword in text for keyword in ("开篇定调", "第一章", "开局")):
        return "opening"
    return None


def _is_key_chapter(project_context: dict[str, Any], chapter_number: int) -> bool:
    return chapter_number == 1 or chapter_number % 10 == 0


def _is_final_chapter(project_context: dict[str, Any], chapter_number: int) -> bool:
    try:
        planned_max = int(project_context.get("planned_chapters_max") or 0)
    except (TypeError, ValueError):
        return False
    return planned_max > 0 and chapter_number >= planned_max
