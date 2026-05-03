"""
拆书文本统计工具。

中文等 CJK 文本按字符计数，拉丁/西里尔文本与数字按词元计数。
"""
from __future__ import annotations

import re


_CJK_LIKE_CHAR_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]"
)
_WORD_TOKEN_RE = re.compile(
    r"[A-Za-z]+(?:['-][A-Za-z]+)*|[\u0400-\u04ff]+(?:['-][\u0400-\u04ff]+)*|\d+(?:[.,]\d+)?"
)


def count_readable_units(text: str) -> int:
    """统计可朗读文本单位，用于拆书字数、章节长度和进度估算。"""
    raw_text = str(text or "")
    cjk_like_count = len(_CJK_LIKE_CHAR_RE.findall(raw_text))
    word_count = len(_WORD_TOKEN_RE.findall(raw_text))
    return cjk_like_count + word_count


__all__ = ["count_readable_units"]
