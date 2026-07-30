"""Normalize provider subtitle payloads into a stable timed contract."""

from __future__ import annotations

import math
from typing import Any, Mapping


_CONTAINER_KEYS = (
    "subtitles",
    "subtitle",
    "subtitle_payload",
    "utterances",
    "sentences",
    "segments",
    "data",
    "result",
    "output",
    "results",
)


def subtitle_items(payload: Any) -> list[Mapping[str, Any]]:
    """Return the most specific subtitle items without descending into words."""
    if isinstance(payload, (list, tuple)):
        items: list[Mapping[str, Any]] = []
        for value in payload:
            items.extend(subtitle_items(value))
        return items
    if not isinstance(payload, Mapping):
        return []

    # Official Seed responses may expose a whole transcript next to sentences.
    # Prefer the timed sentence container over that untimed parent text.
    for key in _CONTAINER_KEYS:
        if key not in payload:
            continue
        items = subtitle_items(payload[key])
        if items:
            return items

    if payload.get("text") is not None or payload.get("transcript") is not None:
        return [payload]
    return []


def subtitle_time_seconds(
    item: Mapping[str, Any],
    prefix: str,
) -> float | None:
    """Read canonical seconds or provider millisecond timestamp fields."""
    if prefix not in {"start", "end"}:
        raise ValueError(f"unsupported subtitle time prefix: {prefix}")

    millisecond_keys = (
        ("start_ms", "startMs", "start_time", "startTime", "begin_time", "beginTime")
        if prefix == "start"
        else ("end_ms", "endMs", "end_time", "endTime")
    )
    for key in millisecond_keys:
        value = _finite_number(item.get(key))
        if value is not None:
            return value / 1000

    value = _finite_number(item.get(prefix))
    return value


def normalize_timed_subtitle_payload(payload: Any) -> dict[str, Any] | None:
    """Convert nested provider subtitles to canonical ``start_ms/end_ms`` items."""
    segments: list[dict[str, Any]] = []
    for item in subtitle_items(payload):
        text = str(item.get("text") or item.get("transcript") or "").strip()
        if not text:
            continue
        start_s = subtitle_time_seconds(item, "start")
        end_s = subtitle_time_seconds(item, "end")
        if start_s is None or end_s is None or start_s < 0 or end_s <= start_s:
            continue

        segment: dict[str, Any] = {
            "text": text,
            "start_ms": int(round(start_s * 1000)),
            "end_ms": int(round(end_s * 1000)),
        }
        speaker = str(item.get("speaker") or item.get("character") or "").strip()
        emotion = str(item.get("emotion") or "").strip()
        if speaker:
            segment["speaker"] = speaker
        if emotion:
            segment["emotion"] = emotion
        segments.append(segment)

    if not segments:
        return None
    segments.sort(key=lambda value: (value["start_ms"], value["end_ms"]))
    return {"segments": segments}


def has_timed_subtitle_payload(payload: Any) -> bool:
    return normalize_timed_subtitle_payload(payload) is not None


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


__all__ = [
    "has_timed_subtitle_payload",
    "normalize_timed_subtitle_payload",
    "subtitle_items",
    "subtitle_time_seconds",
]
