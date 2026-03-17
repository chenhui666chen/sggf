"""
日期时间工具。
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """返回当前 UTC 感知时间。"""
    return datetime.now(timezone.utc)


def ensure_utc_datetime(value: datetime | None) -> datetime | None:
    """将 datetime 统一为 UTC 感知时间。"""
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def parse_datetime_utc(
    value: str | datetime | None,
    *,
    default: datetime | None = None,
) -> datetime | None:
    """解析字符串或 datetime，并统一为 UTC 感知时间。"""
    if value is None:
        return default

    if isinstance(value, datetime):
        return ensure_utc_datetime(value)

    raw = str(value).strip()
    if not raw:
        return default

    try:
        return ensure_utc_datetime(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return default
