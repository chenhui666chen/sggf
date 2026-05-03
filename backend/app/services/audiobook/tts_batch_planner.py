from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_TTS_BATCH_MAX_ITEMS = 10
DEFAULT_TTS_BATCH_MAX_CHARS = 1200


@dataclass(frozen=True)
class TTSBatchPlan:
    batch_index: int
    start_index: int
    end_index: int
    segment_indices: List[int]
    total_chars: int
    voice_key: str


def plan_tts_batches(
    segments: Iterable[Dict[str, Any]],
    *,
    max_items: Optional[int] = None,
    max_chars: Optional[int] = None,
    split_on_voice_change: bool = True,
) -> List[TTSBatchPlan]:
    items = list(segments or [])
    if not items:
        return []

    item_limit = _coerce_positive_int(max_items, _env_int("AUDIOBOOK_TTS_BATCH_MAX_ITEMS"), DEFAULT_TTS_BATCH_MAX_ITEMS)
    char_limit = _coerce_positive_int(max_chars, _env_int("AUDIOBOOK_TTS_BATCH_MAX_CHARS"), DEFAULT_TTS_BATCH_MAX_CHARS)

    batches: List[TTSBatchPlan] = []
    current_indices: List[int] = []
    current_chars = 0
    current_voice = ""

    def flush() -> None:
        nonlocal current_indices, current_chars, current_voice
        if not current_indices:
            return
        batches.append(
            TTSBatchPlan(
                batch_index=len(batches),
                start_index=current_indices[0],
                end_index=current_indices[-1] + 1,
                segment_indices=list(current_indices),
                total_chars=current_chars,
                voice_key=current_voice,
            )
        )
        current_indices = []
        current_chars = 0
        current_voice = ""

    for index, segment in enumerate(items):
        text_length = len(str(segment.get("text") or ""))
        voice_key = _voice_key(segment)
        would_exceed_items = len(current_indices) >= item_limit
        would_exceed_chars = bool(current_indices) and current_chars + text_length > char_limit
        voice_changed = bool(current_indices) and split_on_voice_change and voice_key != current_voice

        if would_exceed_items or would_exceed_chars or voice_changed:
            flush()

        current_indices.append(index)
        current_chars += text_length
        current_voice = voice_key

    flush()
    return batches


def _voice_key(segment: Dict[str, Any]) -> str:
    voice_params = segment.get("voice_params") if isinstance(segment, dict) else {}
    if not isinstance(voice_params, dict):
        voice_params = {}
    return str(
        voice_params.get("speaker")
        or voice_params.get("voice")
        or voice_params.get("voice_id")
        or ""
    ).strip()


def _env_int(name: str) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _coerce_positive_int(*values: Optional[int]) -> int:
    for value in values:
        try:
            candidate = int(value) if value is not None else 0
        except (TypeError, ValueError):
            candidate = 0
        if candidate > 0:
            return candidate
    return 1


__all__ = [
    "DEFAULT_TTS_BATCH_MAX_CHARS",
    "DEFAULT_TTS_BATCH_MAX_ITEMS",
    "TTSBatchPlan",
    "plan_tts_batches",
]
