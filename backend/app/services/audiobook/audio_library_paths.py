from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


AUDIO_LIBRARY_DIR_ENV = "AUDIOBOOK_AUDIO_LIBRARY_DIR"


def get_backend_dir() -> Path:
    """返回 backend 目录。"""
    return Path(__file__).resolve().parents[3]


def get_audio_library_dir() -> Path:
    """返回有声书音频素材库目录。"""
    override = os.getenv(AUDIO_LIBRARY_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return get_backend_dir() / "data" / "audio_library"


def resolve_audio_library_file_path(file_ref: object, base_dir: Path) -> Optional[Path]:
    """按素材库根目录解析文件引用，兼容旧绝对路径和新相对路径。"""
    raw = str(file_ref or "").strip()
    if not raw:
        return None
    path = Path(raw)
    candidate = path if path.is_absolute() else base_dir / path
    return candidate if candidate.exists() else None


__all__ = [
    "AUDIO_LIBRARY_DIR_ENV",
    "get_audio_library_dir",
    "get_backend_dir",
    "resolve_audio_library_file_path",
]
