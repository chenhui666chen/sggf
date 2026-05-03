from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


DEFAULT_PAUSE_MS = 1000
DEFAULT_BREAK_MS = 500
DEFAULT_PARAGRAPH_PAUSE_MS = 1200
MAX_PAUSE_MS = 10_000

_PAUSE_TAG_RE = re.compile(
    r"""
    \[
        (?P<bracket_name>pause|break)
        (?:\s*[:=]\s*(?P<bracket_value>[^\]]+))?
    \]
    |
    <break\b(?P<break_attrs>[^>]*)/?\s*>(?:\s*</break>)?
    |
    (?P<paragraph_pause>%P%)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_BREAK_TIME_RE = re.compile(
    r"""\btime\s*=\s*(?P<quote>["'])(?P<value>.*?)(?P=quote)""",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"""
    ^\s*
    (?P<value>\d+(?:\.\d+)?)
    \s*
    (?P<unit>ms|millisecond|milliseconds|s|sec|secs|second|seconds)?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class PauseTagResult:
    text: str
    pause_after_ms: Optional[int]
    applied: bool = False


@dataclass(frozen=True)
class PauseTextPart:
    text: str
    pause_after_ms: Optional[int]
    applied: bool = False


def strip_pause_tags(text: str) -> PauseTagResult:
    """清理文本内停顿标签，并返回需要由混音层插入的停顿时长。"""
    raw_text = str(text or "")
    if not raw_text:
        return PauseTagResult(text="", pause_after_ms=None, applied=False)

    pause_after_ms: Optional[int] = None
    applied = False

    def replace_tag(match: re.Match[str]) -> str:
        nonlocal pause_after_ms, applied
        applied = True
        tag_pause_ms = _pause_ms_from_match(match)
        if tag_pause_ms is not None:
            pause_after_ms = (
                tag_pause_ms
                if pause_after_ms is None
                else max(pause_after_ms, tag_pause_ms)
            )
        return " "

    cleaned = _PAUSE_TAG_RE.sub(replace_tag, raw_text)
    cleaned = _cleanup_text_after_tag_removal(cleaned)
    return PauseTagResult(
        text=cleaned,
        pause_after_ms=pause_after_ms,
        applied=applied,
    )


def split_pause_tag_text(text: str) -> List[PauseTextPart]:
    """按停顿标签切分文本，让内部停顿可以落在对应音频块之后。"""
    raw_text = str(text or "")
    if not raw_text:
        return []

    parts: List[PauseTextPart] = []
    cursor = 0
    applied = False

    for match in _PAUSE_TAG_RE.finditer(raw_text):
        applied = True
        before = raw_text[cursor:match.start()]
        pause_after_ms = _pause_ms_from_match(match)
        cleaned_before = _cleanup_text_after_tag_removal(before)
        if cleaned_before:
            parts.append(
                PauseTextPart(
                    text=cleaned_before,
                    pause_after_ms=pause_after_ms,
                    applied=True,
                )
            )
        elif parts and pause_after_ms is not None:
            previous = parts[-1]
            parts[-1] = PauseTextPart(
                text=previous.text,
                pause_after_ms=(
                    pause_after_ms
                    if previous.pause_after_ms is None
                    else max(previous.pause_after_ms, pause_after_ms)
                ),
                applied=True,
            )
        cursor = match.end()

    trailing = _cleanup_text_after_tag_removal(raw_text[cursor:])
    if trailing:
        parts.append(
            PauseTextPart(
                text=trailing,
                pause_after_ms=None,
                applied=applied,
            )
        )

    if parts:
        return parts

    cleaned = _cleanup_text_after_tag_removal(raw_text)
    return [PauseTextPart(text=cleaned, pause_after_ms=None, applied=applied)] if cleaned else []


def coerce_pause_ms(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _clamp_pause_ms(round(float(value)))
    parsed = _parse_duration_ms(str(value))
    if parsed is None:
        return None
    return _clamp_pause_ms(parsed)


def _pause_ms_from_match(match: re.Match[str]) -> Optional[int]:
    if match.group("paragraph_pause"):
        return DEFAULT_PARAGRAPH_PAUSE_MS

    bracket_name = (match.group("bracket_name") or "").strip().lower()
    if bracket_name:
        bracket_value = match.group("bracket_value")
        if bracket_value is None or not str(bracket_value).strip():
            return DEFAULT_BREAK_MS if bracket_name == "break" else DEFAULT_PAUSE_MS
        parsed = _parse_duration_ms(bracket_value)
        return parsed if parsed is not None else DEFAULT_PAUSE_MS

    attrs = match.group("break_attrs") or ""
    attr_match = _BREAK_TIME_RE.search(attrs)
    if not attr_match:
        return DEFAULT_BREAK_MS
    parsed = _parse_duration_ms(attr_match.group("value"))
    return parsed if parsed is not None else DEFAULT_BREAK_MS


def _parse_duration_ms(value: str) -> Optional[int]:
    duration = str(value or "").strip().strip('"').strip("'")
    if not duration:
        return None
    match = _DURATION_RE.match(duration)
    if not match:
        return None

    raw_number = float(match.group("value"))
    unit = (match.group("unit") or "s").lower()
    if unit in {"ms", "millisecond", "milliseconds"}:
        return _clamp_pause_ms(round(raw_number))
    return _clamp_pause_ms(round(raw_number * 1000))


def _clamp_pause_ms(value: int) -> int:
    return max(0, min(MAX_PAUSE_MS, int(value)))


def _cleanup_text_after_tag_removal(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    cjk = r"\u3400-\u4dbf\u4e00-\u9fff"
    cn_punctuation = r"。！？；：，、"
    cleaned = re.sub(rf"(?<=[{cjk}{cn_punctuation}])\s+(?=[{cjk}])", "", cleaned)
    cleaned = re.sub(rf"(?<=[{cjk}])\s+(?=[{cn_punctuation}])", "", cleaned)
    return cleaned


__all__ = [
    "DEFAULT_BREAK_MS",
    "DEFAULT_PARAGRAPH_PAUSE_MS",
    "DEFAULT_PAUSE_MS",
    "MAX_PAUSE_MS",
    "PauseTagResult",
    "PauseTextPart",
    "coerce_pause_ms",
    "split_pause_tag_text",
    "strip_pause_tags",
]
