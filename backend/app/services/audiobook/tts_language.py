from __future__ import annotations

import re
from typing import Any, Dict


QWEN_LANGUAGE_AUTO = "Auto"
QWEN_SUPPORTED_LANGUAGE_TYPES = frozenset(
    {
        "Auto",
        "Chinese",
        "English",
        "Japanese",
        "Korean",
        "German",
        "French",
        "Russian",
        "Portuguese",
        "Spanish",
        "Italian",
    }
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_HIRAGANA_KATAKANA_RE = re.compile(r"[\u3040-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
_LATIN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")

_LATIN_LANGUAGE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("French", (" le ", " la ", " les ", " des ", " une ", " est ", " avec ", " pour ", " très ")),
    ("Spanish", (" el ", " la ", " los ", " una ", " que ", " con ", " para ", " está ", "ción")),
    ("Portuguese", (" que ", " com ", " para ", " uma ", "ção", "ões", " não ", " está ")),
    ("Italian", (" il ", " lo ", " gli ", " una ", " che ", " con ", " per ", "zione", "sono ")),
    ("German", (" der ", " die ", " das ", " und ", " ist ", " nicht ", " eine ", "sch", "ung")),
)


def normalize_qwen_language_type(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return QWEN_LANGUAGE_AUTO
    aliases = {
        "auto": "Auto",
        "zh": "Chinese",
        "zh-cn": "Chinese",
        "zh-tw": "Chinese",
        "cn": "Chinese",
        "chinese": "Chinese",
        "en": "English",
        "english": "English",
        "ja": "Japanese",
        "jp": "Japanese",
        "japanese": "Japanese",
        "ko": "Korean",
        "kr": "Korean",
        "korean": "Korean",
        "de": "German",
        "german": "German",
        "fr": "French",
        "french": "French",
        "ru": "Russian",
        "russian": "Russian",
        "pt": "Portuguese",
        "portuguese": "Portuguese",
        "es": "Spanish",
        "spanish": "Spanish",
        "it": "Italian",
        "italian": "Italian",
    }
    normalized = aliases.get(candidate.lower(), candidate)
    return normalized if normalized in QWEN_SUPPORTED_LANGUAGE_TYPES else QWEN_LANGUAGE_AUTO


def detect_qwen_language_type(text: Any) -> str:
    value = str(text or "").strip()
    if not value:
        return QWEN_LANGUAGE_AUTO

    sample = value[:4000]
    kana_count = len(_HIRAGANA_KATAKANA_RE.findall(sample))
    hangul_count = len(_HANGUL_RE.findall(sample))
    cyrillic_count = len(_CYRILLIC_RE.findall(sample))
    cjk_count = len(_CJK_RE.findall(sample))
    latin_count = len(_LATIN_RE.findall(sample))
    signal_count = kana_count + hangul_count + cyrillic_count + cjk_count + latin_count
    if signal_count <= 0:
        return QWEN_LANGUAGE_AUTO

    if hangul_count / signal_count >= 0.20:
        return "Korean"
    if kana_count / signal_count >= 0.08:
        return "Japanese"
    if cyrillic_count / signal_count >= 0.30:
        return "Russian"
    if cjk_count / signal_count >= 0.30:
        return "Chinese"
    if latin_count / signal_count >= 0.70:
        return _detect_latin_language(sample)
    return QWEN_LANGUAGE_AUTO


def apply_detected_language_type(
    voice_params: Dict[str, Any],
    text: Any,
) -> Dict[str, Any]:
    params = dict(voice_params or {})
    explicit_language = normalize_qwen_language_type(params.get("language_type"))
    if explicit_language != QWEN_LANGUAGE_AUTO or str(params.get("language_type") or "").strip():
        params["language_type"] = explicit_language
        return params

    detected = detect_qwen_language_type(text)
    if detected != QWEN_LANGUAGE_AUTO:
        params["language_type"] = detected
        params["language_type_auto_detected"] = True
    return params


def _detect_latin_language(text: str) -> str:
    padded = f" {text.lower()} "
    marker_scores: Dict[str, int] = {}
    for language, markers in _LATIN_LANGUAGE_MARKERS:
        score = sum(1 for marker in markers if marker in padded)
        if score:
            marker_scores[language] = score
    if marker_scores:
        return max(marker_scores.items(), key=lambda item: item[1])[0]
    return "English"


__all__ = [
    "QWEN_LANGUAGE_AUTO",
    "QWEN_SUPPORTED_LANGUAGE_TYPES",
    "apply_detected_language_type",
    "detect_qwen_language_type",
    "normalize_qwen_language_type",
]
