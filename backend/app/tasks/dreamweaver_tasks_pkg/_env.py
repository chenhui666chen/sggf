"""
环境变量和类型转换辅助函数
"""
import os
from typing import Any, List


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    text = str(raw).strip()
    if not text:
        return bool(default)
    return text.lower() not in {"0", "false", "no", "off"}


def _safe_int_list(value: Any) -> List[int]:
    if not isinstance(value, list):
        return []
    out: List[int] = []
    for item in value:
        try:
            out.append(int(item))
        except Exception:
            continue
    return out


def _safe_str_list(value: Any, *, limit: int = 200) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, (str, int)):
            continue
        s = str(item).strip()
        if not s or s in out:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out
