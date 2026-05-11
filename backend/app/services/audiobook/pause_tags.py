from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Pattern


DEFAULT_PAUSE_MS = 1000
DEFAULT_BREAK_MS = 500
DEFAULT_PARAGRAPH_PAUSE_MS = 1200
MAX_PAUSE_MS = 10_000

_NATURAL_PAUSE_BODY_PATTERN = r"""
(?:
    (?:
        (?:旁白|叙述者|讲述者|播讲者|朗读者|此处|这里|这儿|句尾|句首|本句|请|需要|建议|应该|可以|先|再|要)
        \s*
        (?:短暂|稍作|稍微|轻微|明显|长|短|自然)?
        \s*
        (?:停顿|暂停|停一下|停一停|稍停|留白|空拍|静默|沉默)
    )
    |
    (?:
        (?:短暂|稍作|稍微|轻微|明显|长|短|自然)?
        \s*
        (?:停顿|暂停|停一下|停一停|稍停|留白|空拍)
    )
    |
    (?:
        (?:留出|插入|加入|加上)
        \s*
        (?:一个|一点|些许|短暂|明显)?
        \s*
        (?:停顿|暂停|留白|空拍)
    )
)
(?:\s*(?:约|大约|大概)?\s*(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十半]+)\s*(?:ms|毫秒|s|sec|secs|second|seconds|秒)?)?
(?:\s*(?:一下|一会儿|一会|片刻|一拍|半拍|更长|更久|更短|略长|略短))?
(?:\s*(?:后|之后)?\s*(?:再|继续)?\s*(?:讲述|朗读|播讲|叙述|往下读|进入下一句|下一句|继续|说下去)?)?
"""
_NATURAL_PAUSE_DIRECTIVE_PATTERN = rf"""
(?P<natural_bracket_pause>
    [\[【（(]\s*(?P<natural_bracket_body>{_NATURAL_PAUSE_BODY_PATTERN})\s*[\]】）)]
)
|
(?P<natural_inline_pause>
    (?<![A-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff])
    (?P<natural_inline_body>{_NATURAL_PAUSE_BODY_PATTERN})
    (?=\s*(?:[。！？!?；;，,、]|$|[^A-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff]))
    \s*[。！？!?；;，,、]?
)
"""
_NATURAL_PAUSE_DIRECTIVE_RE = re.compile(
    _NATURAL_PAUSE_DIRECTIVE_PATTERN,
    re.IGNORECASE | re.VERBOSE,
)
_NATURAL_DURATION_RE = re.compile(
    r"""
    (?P<value>\d+(?:\.\d+)?|[零〇一二两三四五六七八九十半]+)
    \s*
    (?P<unit>ms|毫秒|s|sec|secs|second|seconds|秒)?
    """,
    re.IGNORECASE | re.VERBOSE,
)
_CHINESE_NUMERAL_VALUES = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_PAUSE_TAG_RE = re.compile(
    rf"""
    \[
        (?P<bracket_name>pause|break)
        (?:\s*[:=]\s*(?P<bracket_value>[^\]]+))?
    \]
    |
    <break\b(?P<break_attrs>[^>]*)/?\s*>(?:\s*</break>)?
    |
    (?P<paragraph_pause>%P%)
    |
    {_NATURAL_PAUSE_DIRECTIVE_PATTERN}
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
    return _strip_pause_matches(text, _PAUSE_TAG_RE)


def strip_spoken_pause_directives(text: str) -> PauseTagResult:
    """只清理会被误读的自然语言停顿指令，保留 [pause] / <break> 标签。"""
    return _strip_pause_matches(text, _NATURAL_PAUSE_DIRECTIVE_RE)


def _strip_pause_matches(text: str, pattern: Pattern[str]) -> PauseTagResult:
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

    cleaned = pattern.sub(replace_tag, raw_text)
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
    groups = match.groupdict()
    if groups.get("paragraph_pause"):
        return DEFAULT_PARAGRAPH_PAUSE_MS

    natural_body = groups.get("natural_bracket_body") or groups.get("natural_inline_body")
    if natural_body:
        parsed_natural = _parse_natural_pause_ms(natural_body)
        return parsed_natural if parsed_natural is not None else DEFAULT_PAUSE_MS

    bracket_name = (groups.get("bracket_name") or "").strip().lower()
    if bracket_name:
        bracket_value = groups.get("bracket_value")
        if bracket_value is None or not str(bracket_value).strip():
            return DEFAULT_BREAK_MS if bracket_name == "break" else DEFAULT_PAUSE_MS
        parsed = _parse_duration_ms(bracket_value)
        return parsed if parsed is not None else DEFAULT_PAUSE_MS

    attrs = groups.get("break_attrs") or ""
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
        return _parse_natural_pause_ms(duration)

    raw_number = float(match.group("value"))
    unit = (match.group("unit") or "s").lower()
    if unit in {"ms", "millisecond", "milliseconds"}:
        return _clamp_pause_ms(round(raw_number))
    return _clamp_pause_ms(round(raw_number * 1000))


def _parse_natural_pause_ms(value: str) -> Optional[int]:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    match = _NATURAL_DURATION_RE.search(normalized)
    if not match:
        if "半秒" in normalized or "半拍" in normalized:
            return 500
        return None

    raw_value = match.group("value")
    try:
        number = float(raw_value)
    except ValueError:
        parsed = _parse_chinese_number(raw_value)
        if parsed is None:
            return None
        number = parsed

    if "秒半" in normalized:
        number += 0.5

    unit = (match.group("unit") or "秒").lower()
    if unit in {"ms", "毫秒"}:
        return _clamp_pause_ms(round(number))
    return _clamp_pause_ms(round(number * 1000))


def _parse_chinese_number(value: str) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    if text == "半":
        return 0.5
    if "十" in text:
        left, _, right = text.partition("十")
        tens = 1 if not left else _CHINESE_NUMERAL_VALUES.get(left)
        ones = 0 if not right else _CHINESE_NUMERAL_VALUES.get(right)
        if tens is None or ones is None:
            return None
        return float(tens * 10 + ones)
    if len(text) == 1:
        value = _CHINESE_NUMERAL_VALUES.get(text)
        return float(value) if value is not None else None
    return None


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
    "strip_spoken_pause_directives",
]
