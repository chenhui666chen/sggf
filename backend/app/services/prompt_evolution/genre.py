"""题材规范化工具。"""
from __future__ import annotations

from typing import Optional


SUPPORTED_GENRES = ("通用", "玄幻", "都市", "言情", "悬疑", "科幻", "历史", "武侠")

_GENRE_ALIASES = {
    "通用": "通用",
    "general": "通用",
    "玄幻": "玄幻",
    "玄幻小说": "玄幻",
    "fantasy": "玄幻",
    "都市": "都市",
    "都市小说": "都市",
    "urban": "都市",
    "言情": "言情",
    "言情小说": "言情",
    "romance": "言情",
    "悬疑": "悬疑",
    "悬疑小说": "悬疑",
    "mystery": "悬疑",
    "suspense": "悬疑",
    "科幻": "科幻",
    "科幻小说": "科幻",
    "science fiction": "科幻",
    "sci-fi": "科幻",
    "scifi": "科幻",
    "历史": "历史",
    "历史小说": "历史",
    "history": "历史",
    "historical": "历史",
    "武侠": "武侠",
    "武侠小说": "武侠",
    "wuxia": "武侠",
}


def normalize_genre(genre: Optional[str]) -> str:
    """将项目题材或用户输入转换为稳定的存储键。"""
    if not genre:
        return "通用"
    value = genre.strip()
    if not value:
        return "通用"
    return _GENRE_ALIASES.get(value.lower(), "通用")
