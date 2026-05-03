from __future__ import annotations

import re
from typing import Optional, Set

from .word_substitutor import WordSubstitutor

_ZERO_WIDTH_CHARS = "\u200b\u200c\u200d\ufeff"
_PUNCT_ONLY_ALLOWED = {"...", "……", "…", "-", "—", "——"}
_PERCENT_RE = re.compile(r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*%")
_THOUSANDS_NUMBER_RE = re.compile(r"\b\d{1,3}(?:,\d{3})+\b")
_URL_RE = re.compile(
    r"\bhttps?://(?P<domain>[^/\s?#，。！？!?；;：:]+)(?:[^\s，。！？；;]*)?",
    re.IGNORECASE,
)
_WWW_URL_RE = re.compile(
    r"(?<!@)\bwww\.(?P<domain>[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?:/[^\s，。！？；;]*)?",
    re.IGNORECASE,
)
_ALL_CAPS_LATIN_WORD_RE = re.compile(r"\b[A-Z]{2,}\b")
_COMMON_LATIN_ACRONYMS = {
    "AI",
    "API",
    "CPU",
    "CSS",
    "DNA",
    "EPUB",
    "EU",
    "FBI",
    "GPU",
    "GPS",
    "HTML",
    "HTTP",
    "HTTPS",
    "ISBN",
    "NASA",
    "PDF",
    "RNA",
    "SQL",
    "UK",
    "UN",
    "URL",
    "USA",
    "UX",
}
_COMMON_LATIN_ABBREVIATIONS = (
    (re.compile(r"\bMr\.", re.IGNORECASE), "Mister"),
    (re.compile(r"\bMrs\.", re.IGNORECASE), "Misses"),
    (re.compile(r"\bMs\.", re.IGNORECASE), "Miss"),
    (re.compile(r"\bDr\.", re.IGNORECASE), "Doctor"),
    (re.compile(r"\bProf\.", re.IGNORECASE), "Professor"),
    (re.compile(r"\bJr\.", re.IGNORECASE), "Junior"),
    (re.compile(r"\bSr\.", re.IGNORECASE), "Senior"),
    (re.compile(r"\bvs\.", re.IGNORECASE), "versus"),
    (re.compile(r"\betc\.", re.IGNORECASE), "etcetera"),
)
_DEFAULT_SUBSTITUTOR: Optional[WordSubstitutor] = None


def normalize_tts_prompt(
    text: str,
    *,
    substitutions: Optional[dict[str, str]] = None,
    protected_words: Optional[Set[str]] = None,
    enable_word_substitution: bool = True,
) -> str:
    processed = str(text or "")
    if not processed:
        return ""

    processed = processed.translate({ord(ch): None for ch in _ZERO_WIDTH_CHARS})
    processed = processed.replace("\u3000", " ")
    processed = re.sub(r"\s+", " ", processed).strip()

    processed = re.sub(r"\s*\.\s*\.\s*\.\s*", "……", processed)
    processed = re.sub(r"…{2,}|……+", "……", processed)
    processed = re.sub(r"\.{3,}", "……", processed)
    processed = re.sub(r"([。！？!?]){3,}", r"\1\1", processed)
    processed = _normalize_all_caps_latin_text(processed)
    processed = _normalize_urls(processed)
    processed = _normalize_common_latin_abbreviations(processed)
    processed = _normalize_thousands_separators(processed)
    processed = _normalize_percent_expressions(processed)

    tokens = processed.split(" ")
    if len(tokens) > 1:
        tokens = [
            token
            for token in tokens
            if token.strip()
            and (not _is_punctuation_only(token) or token.strip() in _PUNCT_ONLY_ALLOWED)
        ]
        processed = " ".join(tokens).strip()

    if enable_word_substitution and processed:
        if substitutions is None and protected_words is None:
            substitutor = _get_default_substitutor()
        else:
            substitutor = WordSubstitutor(
                rules=substitutions,
                protected_words=protected_words,
                enable_default_rules=True,
            )
        processed = substitutor.substitute(processed).processed_text.strip()

    return processed


def _normalize_percent_expressions(text: str) -> str:
    return _PERCENT_RE.sub(r"百分之\1", text)


def _normalize_thousands_separators(text: str) -> str:
    return _THOUSANDS_NUMBER_RE.sub(lambda match: match.group(0).replace(",", ""), text)


def _normalize_urls(text: str) -> str:
    processed = _URL_RE.sub(lambda match: _clean_url_domain(match.group("domain")), text)
    return _WWW_URL_RE.sub(lambda match: _clean_url_domain(match.group("domain")), processed)


def _clean_url_domain(domain: str) -> str:
    value = str(domain or "").strip()
    if value.lower().startswith("www."):
        return value[4:]
    return value


def _normalize_all_caps_latin_text(text: str) -> str:
    value = str(text or "")
    if not value or re.search(r"[a-z]", value):
        return value

    words = _ALL_CAPS_LATIN_WORD_RE.findall(value)
    if len(words) < 3:
        return value
    if any(word in _COMMON_LATIN_ACRONYMS for word in words):
        return value
    if not any(len(word) >= 5 for word in words):
        return value

    return _latin_sentence_case(value)


def _latin_sentence_case(text: str) -> str:
    lowered = str(text or "").lower()
    chars = list(lowered)
    capitalize_next = True
    for index, char in enumerate(chars):
        if char in ".!?":
            capitalize_next = True
            continue
        if not char.isalpha() or not char.isascii():
            continue
        if capitalize_next:
            chars[index] = char.upper()
            capitalize_next = False
    return "".join(chars)


def _normalize_common_latin_abbreviations(text: str) -> str:
    processed = str(text or "")
    for pattern, replacement in _COMMON_LATIN_ABBREVIATIONS:
        processed = pattern.sub(replacement, processed)
    return processed


def _is_punctuation_only(text: str) -> bool:
    value = text.strip()
    return bool(value) and not re.search(r"[\w\u3400-\u4dbf\u4e00-\u9fff]", value)


def _get_default_substitutor() -> WordSubstitutor:
    global _DEFAULT_SUBSTITUTOR
    if _DEFAULT_SUBSTITUTOR is None:
        _DEFAULT_SUBSTITUTOR = WordSubstitutor(enable_default_rules=True)
    return _DEFAULT_SUBSTITUTOR
