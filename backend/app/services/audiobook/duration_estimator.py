from __future__ import annotations


AUDIOBOOK_ESTIMATED_CHARS_PER_SECOND = 4.5
MIN_SEGMENT_DURATION_SECONDS = 0.2


def estimate_narration_duration_seconds(
    text: str,
    *,
    min_duration: float = MIN_SEGMENT_DURATION_SECONDS,
) -> float:
    """按中文有声书朗读语速估算文本时长。"""
    char_count = len(str(text or ""))
    duration = char_count / AUDIOBOOK_ESTIMATED_CHARS_PER_SECOND
    return max(float(min_duration), duration)


__all__ = [
    "AUDIOBOOK_ESTIMATED_CHARS_PER_SECOND",
    "MIN_SEGMENT_DURATION_SECONDS",
    "estimate_narration_duration_seconds",
]
