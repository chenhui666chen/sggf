"""Utilities for cross-platform safe download and archive filenames."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional, Set


_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename_component(
    value: Any,
    *,
    fallback: str = "file",
    max_bytes: int = 120,
) -> str:
    """Return a safe filename stem without path separators or extension."""
    original = str(value or "")
    text = unicodedata.normalize("NFKC", original).strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", "_", text).strip("._ ")
    text = re.sub(r"_+", "_", text).strip("._ ")
    if not text:
        text = fallback

    if text.upper() in _RESERVED_WINDOWS_NAMES:
        text = f"{text}_file"

    return _truncate_utf8_stem(text, max_bytes=max_bytes, hash_source=original or text)


def build_safe_filename(
    stem: Any,
    extension: str,
    *,
    fallback: str = "file",
    prefix: str = "",
    max_bytes: int = 180,
) -> str:
    """Build a full safe filename that respects UTF-8 byte length limits."""
    ext = str(extension or "").strip()
    if not ext:
        raise ValueError("extension must be non-empty")
    if not ext.startswith("."):
        ext = "." + ext
    ext = re.sub(r"[^A-Za-z0-9.]+", "", ext) or ".bin"
    if ext == ".":
        ext = ".bin"

    safe_prefix = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', "_", str(prefix or "")).strip("._ ")
    if safe_prefix:
        safe_prefix = f"{safe_prefix}_"

    prefix_bytes = len(safe_prefix.encode("utf-8"))
    ext_bytes = len(ext.encode("utf-8"))
    available = max(16, int(max_bytes) - prefix_bytes - ext_bytes)
    safe_stem = sanitize_filename_component(stem, fallback=fallback, max_bytes=available)
    candidate = f"{safe_prefix}{safe_stem}{ext}"

    if len(candidate.encode("utf-8")) <= max_bytes:
        return candidate

    digest = hashlib.sha1(str(stem or fallback).encode("utf-8")).hexdigest()[:8]
    minimal = f"{safe_prefix}{digest}{ext}"
    if len(minimal.encode("utf-8")) <= max_bytes:
        return minimal
    return f"{digest}{ext}"


def ensure_unique_filename(filename: str, used_filenames: Set[str]) -> str:
    """Return filename or add a numeric suffix when it already exists."""
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = filename
    counter = 2
    while candidate.lower() in used_filenames:
        candidate = build_safe_filename(
            f"{stem}_{counter}",
            suffix or ".bin",
            fallback="file",
        )
        counter += 1
    used_filenames.add(candidate.lower())
    return candidate


def _truncate_utf8_stem(text: str, *, max_bytes: int, hash_source: str) -> str:
    limit = max(8, int(max_bytes))
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text

    digest = hashlib.sha1(str(hash_source).encode("utf-8")).hexdigest()[:8]
    reserve = len(digest.encode("utf-8")) + 1
    keep = max(1, limit - reserve)
    truncated = encoded[:keep]
    while truncated and (truncated[-1] & 0b11000000) == 0b10000000:
        truncated = truncated[:-1]

    stem = truncated.decode("utf-8", errors="ignore").rstrip("._- ")
    if not stem:
        stem = "file"
    return f"{stem}_{digest}"
