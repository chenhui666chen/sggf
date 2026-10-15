# -*- coding: utf-8 -*-
"""W1 数据库初始化：一条命令建齐 router_gateway 全部表。

- 入口：python -m router_gateway.db.init_db
- Base.metadata.create_all 幂等：表已存在则跳过，不删数据；
- 数据库本身需预先存在（docker novel_postgres 中的 router_gateway 库）；
- 当前无历史包袱，不引入 Alembic，表结构首次变更时再上迁移工具。
"""
from __future__ import annotations

import os

from sqlalchemy import inspect, text

from . import DEFAULT_DATABASE_URL, Base, get_engine


def resolve_database_url(env=None) -> str:
    """数据库地址取 ROUTER_GATEWAY_DATABASE_URL，缺省回退本机 docker 默认库。"""
    env = os.environ if env is None else env
    return (env.get("ROUTER_GATEWAY_DATABASE_URL") or "").strip() \
        or DEFAULT_DATABASE_URL


def init_schema(engine) -> None:
    """对给定引擎幂等建齐全部表（checkfirst，重复执行不报错不丢数据）。"""
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    migrations = {
        "clients": {
            "api_key_hash": "VARCHAR(64)",
            "rate_limit_per_second": "INTEGER NOT NULL DEFAULT 1",
            "burst_capacity": "INTEGER NOT NULL DEFAULT 5",
            "max_active_jobs": "INTEGER NOT NULL DEFAULT 5",
            "max_parallel_attempts": "INTEGER NOT NULL DEFAULT 2",
            "lifetime_task_limit": "INTEGER NOT NULL DEFAULT 100",
            "daily_task_limit": "INTEGER",
            "monthly_task_limit": "INTEGER",
            "daily_budget": "NUMERIC(12, 4)",
            "monthly_budget": "NUMERIC(12, 4)",
        },
        "jobs": {
            "claimed_by": "VARCHAR(128)",
            "claim_until": "TIMESTAMP WITH TIME ZONE",
            "next_poll_at": "TIMESTAMP WITH TIME ZONE",
        },
        "attempts": {
            "delivery_url": "VARCHAR(512)",
        },
    }
    with engine.begin() as connection:
        for table, columns in migrations.items():
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_clients_api_key_hash "
            "ON clients (api_key_hash)"))
        # jobs 幂等唯一约束与多实例认领索引（create_all 不会改存量表）
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_client_idempotency "
            "ON jobs (client_key, idempotency_key)"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_jobs_claimed_by "
            "ON jobs (claimed_by)"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_jobs_claim_until "
            "ON jobs (claim_until)"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_jobs_next_poll_at "
            "ON jobs (next_poll_at)"))


def main() -> None:
    """进程入口：python -m router_gateway.db.init_db"""
    engine = get_engine(resolve_database_url())
    try:
        init_schema(engine)
        names = ", ".join(sorted(Base.metadata.tables))
        print(f"初始化完成：{len(Base.metadata.tables)} 张表（{names}）")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
