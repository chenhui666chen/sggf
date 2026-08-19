"""canonical 去重合并迁移进度合同服务（GUIDE R21/P1-1、R22/P1-2、R22/P1-3）。

本模块只承载进度表与全局会话锁的合同级原语：
- record_group_failure：事务 B 的 fail-closed 条件更新——绝不覆盖已提交 completed；
- migration_session_lock：全局单实例会话锁的专用非池化连接合同；
- sanitize_failure_detail：failure_detail 脱敏（禁止完整堆栈/DSN/密钥/用户正文）。
迁移组处理（事务 A）与 canonical 选择算法由迁移执行器负责，不在此模块。
"""

from __future__ import annotations

import os
import socket
import uuid
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.pool import NullPool

from app.models.canonical_migration_progress import AudiobookCanonicalMigrationProgress

# 全局单实例会话锁固定键（按 migration_version 固定，GUIDE §1.1 并发认领合同）
MIGRATION_VERSION_LOCK_KEY = 816202601

_FAILURE_DETAIL_MAX_LENGTH = 1000


class MigrationLockBusy(RuntimeError):
    """全局迁移锁已被其他实例持有——按合同立即退出（不排队、不降级为并行，KISS）。"""


def sanitize_failure_detail(detail: object, max_length: int = _FAILURE_DETAIL_MAX_LENGTH) -> str:
    """脱敏异常摘要：仅保留首行并截断。

    禁止包含完整堆栈、数据库 DSN、供应商密钥或用户正文（R21/P1-1）。
    """
    raw = str(detail) if detail is not None else ""
    first_line = raw.splitlines()[0] if raw else ""
    return first_line[:max_length]


def record_group_failure(
    bind,
    *,
    migration_version: str,
    audiobook_project_id: int,
    chapter_id: int,
    error_code: str,
    failure_detail: str,
) -> None:
    """事务 B：fail-closed 条件更新写入失败组（R22/P1-2）。

    `ON CONFLICT ... DO UPDATE ... WHERE status <> 'completed'`——
    绝不把已提交的 completed 覆盖为 failed；attempts 仅在本语句生效时递增。
    调用前提：调用方已确认事务 A 未提交或 progress 仍非 completed
    （提交结果不确定时先用新连接重读 progress，见 GUIDE R22/P1-2）。
    """
    table = AudiobookCanonicalMigrationProgress
    stmt = pg_insert(table).values(
        migration_version=migration_version,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        status="failed",
        attempts=1,
        last_failed_at=func.now(),
        last_error_code=error_code,
        failure_detail=sanitize_failure_detail(failure_detail),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["migration_version", "audiobook_project_id", "chapter_id"],
        set_={
            "status": "failed",
            "attempts": table.attempts + 1,
            "last_failed_at": func.now(),
            "last_error_code": stmt.excluded.last_error_code,
            "failure_detail": stmt.excluded.failure_detail,
        },
        where=table.status != "completed",
    )
    with bind.begin() as conn:
        conn.execute(stmt)


@contextmanager
def migration_session_lock(database_url: str, lock_key: int = MIGRATION_VERSION_LOCK_KEY) -> Iterator[dict]:
    """会话锁连接合同（R22/P1-3）：

    - 专用、非池化连接持有（NullPool）——不借用应用连接池，持锁连接不归还任何池；
    - 获取失败立即关闭连接并抛 MigrationLockBusy（不排队、不降级为并行）；
    - 正常完成/异常退出均在 finally 执行 pg_advisory_unlock 后关闭连接；
    - 进程崩溃依赖数据库断连自动释放，启动时记录 run_id/host/pid 供运维诊断。
    """
    lock_engine = create_engine(database_url, poolclass=NullPool)
    conn = lock_engine.connect()
    run_id = uuid.uuid4().hex
    acquired = False
    try:
        acquired = bool(
            conn.execute(text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": lock_key}).scalar()
        )
        if not acquired:
            raise MigrationLockBusy(
                "migration session lock held by another instance; "
                f"run_id={run_id} host={socket.gethostname()} pid={os.getpid()}"
            )
        yield {"run_id": run_id, "host": socket.gethostname(), "pid": os.getpid()}
    finally:
        try:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key})
            conn.rollback()
        except Exception:  # noqa: BLE001 —— 解锁失败不掩盖原始异常，连接关闭即释放会话锁
            pass
        finally:
            conn.close()
            lock_engine.dispose()
