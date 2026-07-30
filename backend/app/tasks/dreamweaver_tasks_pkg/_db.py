"""
数据库更新函数
"""
import logging
import random
import sqlite3
import time
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.base import SessionLocal


logger = logging.getLogger(__name__)


def _update_generation_history(task_id: str, **changes: Any) -> None:
    set_parts = []
    params: Dict[str, Any] = {"task_id": task_id}
    for key, value in changes.items():
        set_parts.append(f"{key} = :{key}")
        params[key] = value
    if not set_parts:
        return

    query = text(
        f"""
        UPDATE generation_history
        SET {", ".join(set_parts)}
        WHERE task_id = :task_id
        """
    )

    # SQLite under FastAPI + Celery concurrent writes may hit short lock contention.
    # Retry a few times on "database is locked" to avoid failing the whole task.
    max_retries = max(0, _env_int("SQLITE_WRITE_RETRIES", 8))
    base_sleep_s = max(0.05, _env_float("SQLITE_WRITE_RETRY_BASE_S", 0.15))
    max_sleep_s = max(0.2, _env_float("SQLITE_WRITE_RETRY_MAX_S", 2.0))
    status_busy_timeout_ms = int(max(0.0, _env_float("SQLITE_STATUS_BUSY_TIMEOUT_S", 2.0)) * 1000)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        session = SessionLocal()
        try:
            try:
                bind = session.get_bind()
                if getattr(getattr(bind, "dialect", None), "name", None) == "sqlite" and status_busy_timeout_ms > 0:
                    session.execute(text(f"PRAGMA busy_timeout={status_busy_timeout_ms};"))
            except Exception:  # noqa: BLE001
                pass
            session.execute(query, params)
            session.commit()
            return
        except OperationalError as exc:
            last_exc = exc
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
            if not _is_sqlite_locked_error(exc):
                raise
            if attempt < max_retries:
                sleep_s = min(max_sleep_s, base_sleep_s * (2**attempt))
                time.sleep(sleep_s + random.random() * 0.05)
                continue
            break
        finally:
            session.close()

    # 写入状态失败不应导致整条生成链路直接失败：记录日志，交由后续轮询覆盖。
    if last_exc is not None and _is_sqlite_locked_error(last_exc):
        logger.warning("update generation_history failed after retries (task_id=%s): %s", task_id, last_exc)
        return
    if last_exc is not None:
        raise last_exc
