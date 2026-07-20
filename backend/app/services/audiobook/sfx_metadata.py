"""音效素材的语义归一化与人工审核纠正。"""
from __future__ import annotations

import re
from typing import Any, Iterable


_TRANSPORT_KEYWORDS = (
    "train",
    "railway",
    "railcar",
    "locomotive",
    "station",
    "platform",
    "bus",
    "public transport",
    "火车",
    "铁路",
    "车站",
    "站台",
    "公交",
)

_AMBIENCE_CONTEXT_KEYWORDS = (
    "ambience",
    "ambient",
    "station",
    "platform",
    "arrival",
    "arrivals",
    "departure",
    "departing",
    "passenger",
    "passengers",
    "people",
    "talk",
    "talking",
    "announcement",
    "crowd",
    "railway yard",
    "industrial yard",
    "环境",
    "车站",
    "站台",
    "到站",
    "出发",
    "乘客",
    "人群",
    "交谈",
    "广播",
)

_TRANSPORT_CLASSIFICATION_TAGS = {"action", "intense", "battle", "general"}

_CURATED_OVERRIDES = {
    "wikimedia_airchime_k5la_train_horn_cc0": {
        "name": "火车站火车鸣笛与人群交谈声",
        "description": "火车站环境声，包含火车鸣笛、列车运行声和背景人群交谈。",
        "category": "environment/realistic",
        "style": "realistic",
        "tags": [
            "train",
            "station",
            "railway",
            "horn",
            "vehicle",
            "people",
            "talk",
            "ambience",
            "public_transport",
            "travel",
            "environment",
            "realistic",
        ],
        "scenes": ["travel"],
    },
}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values: Iterable[Any] = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = []

    normalized: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def metadata_keyword_matches(text: str, keyword: str) -> bool:
    normalized_text = re.sub(r"[_/\\-]+", " ", str(text or "").lower())
    normalized_keyword = re.sub(r"[_/\\-]+", " ", str(keyword or "").lower()).strip()
    if not normalized_keyword:
        return False
    if re.search(r"[\u4e00-\u9fff]", normalized_keyword):
        return normalized_keyword in normalized_text
    phrase = r"\s+".join(re.escape(part) for part in normalized_keyword.split())
    return re.search(rf"(?<![a-z0-9]){phrase}(?![a-z0-9])", normalized_text) is not None


def _record_text(record: dict[str, Any]) -> str:
    tags = " ".join(_string_list(record.get("tags")))
    return " ".join((
        str(record.get("name") or ""),
        str(record.get("description") or ""),
        tags,
    )).lower()


def _is_transport_ambience(record: dict[str, Any]) -> bool:
    text = _record_text(record)
    has_transport = any(metadata_keyword_matches(text, keyword) for keyword in _TRANSPORT_KEYWORDS)
    has_ambience_context = any(
        metadata_keyword_matches(text, keyword)
        for keyword in _AMBIENCE_CONTEXT_KEYWORDS
    )
    return has_transport and has_ambience_context


def normalize_sfx_semantics(record: dict[str, Any]) -> dict[str, Any]:
    """纠正高置信度语义冲突，并应用人工试听确认过的元数据。"""
    normalized = dict(record)
    tags = _string_list(normalized.get("tags"))
    scenes = _string_list(normalized.get("scenes"))
    semantics_changed = False

    if _is_transport_ambience(normalized):
        semantics_changed = True
        normalized["category"] = "environment/realistic"
        normalized["style"] = "realistic"
        tags = [tag for tag in tags if tag.lower() not in _TRANSPORT_CLASSIFICATION_TAGS]
        for tag in ("travel", "environment", "realistic"):
            if tag not in tags:
                tags.append(tag)
        scenes = [scene for scene in scenes if scene.lower() not in {"battle", "general"}]
        if "travel" not in scenes:
            scenes.append("travel")

    source_id = str(normalized.get("source_id") or "").strip().lower()
    override = _CURATED_OVERRIDES.get(source_id)
    if override:
        semantics_changed = True
        normalized.update(override)
        tags = list(override["tags"])
        scenes = list(override["scenes"])

    if "tags" in normalized or semantics_changed:
        normalized["tags"] = tags
    if "scenes" in normalized or semantics_changed:
        normalized["scenes"] = scenes
    return normalized


__all__ = ["metadata_keyword_matches", "normalize_sfx_semantics"]
