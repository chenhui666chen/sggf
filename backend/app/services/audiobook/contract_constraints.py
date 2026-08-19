"""Phase 1.1 Contract：门禁化约束收窄（GUIDE §1.1，R19/R20/R21/R22）。

本模块只提供可复用的 DDL 收窄步骤，由 Alembic Contract 迁移编排调用；
每一步都是 fail-closed：前置数据门禁不通过时抛错中止，绝不带病收窄。

已实现的收窄项（门禁可在当前代码库验证）：
- ``audiobook_projects.engine_mode``：NOT NULL + ``server_default='legacy_stems'`` + CHECK
  （模型已声明 server_default，ORM 省略列由 DB 默认兜底，旧写路径兼容）
- ``audiobook_projects.snapshot_status``：三态 CHECK + 快照一致性 CHECK
  （NOT NULL 无 server_default 且存在多处构造点，待构造点全部显式写入后由后续步骤施加，R19/P2-1）
- ``chapter_audio_runs.dispatch_status``：NOT NULL + ``server_default='pending'`` + CHECK
- ``chapter_audio_runs.status``：值域 CHECK（含 ``expired``，R15/P0-1）
- ``chapter_audios``：部分唯一索引 ``UNIQUE (audiobook_project_id, chapter_id) WHERE deleted_at IS NULL``
  （含 INVALID 索引身份校验流程，R21/P2-2）

暂缓项（门禁依赖新写路径代码，待后续单元满足后再收窄）：
- ``snapshot_status`` NOT NULL、``chapter_audio_runs.chapter_audio_id`` NOT NULL、
  ``celery_task_id`` NOT NULL+UNIQUE、``audiobook_tasks`` CHECK 二阶段收窄
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

ACTIVE_UNIQUE_INDEX_NAME = "uq_chapter_audio_active_unique"

RUN_STATUS_DOMAIN = (
    "pending",
    "queued",
    "running",
    "paused",
    "pause_requested",
    "completed",
    "failed",
    "canceled",
    "cancelled",
    "expired",
)


def verify_no_duplicate_active(conn: sa.engine.Connection, *, schema: str = "public") -> list:
    """Contract 门禁：全表无重复 active 组（GUIDE §1.1 Contract 前置验证 SQL）。

    返回重复组列表 ``[(audiobook_project_id, chapter_id), ...]``；空列表表示门禁通过。
    """
    rows = conn.execute(text(
        f"SELECT audiobook_project_id, chapter_id FROM {schema}.chapter_audios "
        "WHERE deleted_at IS NULL GROUP BY 1, 2 HAVING COUNT(*) > 1"
    )).all()
    return [(r[0], r[1]) for r in rows]


def _constraint_names(conn, table_fqn: str) -> set[str]:
    rows = conn.execute(
        text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:tbl AS regclass)"),
        {"tbl": table_fqn},
    )
    return {r[0] for r in rows}


def _index_names(conn, table_fqn: str) -> set[str]:
    schema, _, table = table_fqn.rpartition(".")
    rows = conn.execute(
        text("SELECT indexname FROM pg_indexes WHERE schemaname = :s AND tablename = :tbl"),
        {"s": schema or "public", "tbl": table},
    )
    return {r[0] for r in rows}


def apply_project_contract(conn: sa.engine.Connection, *, schema: str = "public") -> None:
    """audiobook_projects 收窄：engine_mode NOT NULL+默认+CHECK、snapshot 三态与一致性 CHECK。"""
    table = f"{schema}.audiobook_projects"

    # fail-closed 门禁：engine_mode 必须已回填；快照非法组合必须先清洗
    null_engine = conn.execute(
        text(f"SELECT count(*) FROM {table} WHERE engine_mode IS NULL")
    ).scalar()
    if null_engine:
        raise RuntimeError(f"Contract 门禁未通过：{null_engine} 行 engine_mode 仍为 NULL，先执行历史回填")
    bad_combo = conn.execute(text(
        f"SELECT count(*) FROM {table} WHERE "
        "(snapshot_status = 'frozen' AND engine_config_snapshot IS NULL) OR "
        "(snapshot_status = 'legacy_unfrozen' AND engine_config_snapshot IS NOT NULL)"
    )).scalar()
    if bad_combo:
        raise RuntimeError(f"Contract 门禁未通过：{bad_combo} 行快照状态组合非法，先清洗")

    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN engine_mode SET DEFAULT 'legacy_stems'"))
    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN engine_mode SET NOT NULL"))

    existing = _constraint_names(conn, table)
    checks = [
        (
            "ck_audiobook_projects_engine_mode",
            "engine_mode IN ('legacy_stems', 'seed_scene')",
        ),
        (
            "ck_audiobook_projects_snapshot_status",
            "snapshot_status IN ('frozen', 'legacy_unfrozen', 'legacy_unverified')",
        ),
        (
            "ck_audiobook_projects_snapshot_consistency",
            "NOT (snapshot_status = 'frozen' AND engine_config_snapshot IS NULL) AND "
            "NOT (snapshot_status = 'legacy_unfrozen' AND engine_config_snapshot IS NOT NULL)",
        ),
    ]
    for name, clause in checks:
        if name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({clause})"))

    if "ix_audiobook_projects_engine_mode_deleted" not in _index_names(conn, table):
        conn.execute(text(
            f"CREATE INDEX ix_audiobook_projects_engine_mode_deleted ON {table} "
            "(id, engine_mode, deleted_at)"
        ))


def apply_run_contract(conn: sa.engine.Connection, *, schema: str = "public") -> None:
    """chapter_audio_runs 收窄：dispatch_status NOT NULL+默认+CHECK、status 值域 CHECK。"""
    table = f"{schema}.chapter_audio_runs"

    null_dispatch = conn.execute(
        text(f"SELECT count(*) FROM {table} WHERE dispatch_status IS NULL")
    ).scalar()
    if null_dispatch:
        raise RuntimeError(f"Contract 门禁未通过：{null_dispatch} 行 dispatch_status 仍为 NULL，先执行历史回填")
    placeholders = ", ".join(f"'{v}'" for v in RUN_STATUS_DOMAIN)
    bad_status = conn.execute(text(
        f"SELECT count(*) FROM {table} WHERE status NOT IN ({placeholders})"
    )).scalar()
    if bad_status:
        raise RuntimeError(f"Contract 门禁未通过：{bad_status} 行 run status 在值域外，先按父聚合规则清洗")

    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN dispatch_status SET DEFAULT 'pending'"))
    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN dispatch_status SET NOT NULL"))

    existing = _constraint_names(conn, table)
    checks = [
        (
            "ck_chapter_audio_runs_dispatch_status",
            "dispatch_status IN ('pending', 'dispatched', 'cancelled', 'unknown')",
        ),
        (
            "ck_chapter_audio_runs_status",
            f"status IN ({placeholders})",
        ),
    ]
    for name, clause in checks:
        if name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({clause})"))


def _inspect_active_unique_index(conn, *, schema: str):
    """读取同名索引的身份事实：列序、谓词、有效性（R21/P2-2 身份校验输入）。"""
    row = conn.execute(text(
        "SELECT ("
        "  SELECT array_agg(a.attname ORDER BY k.ord) "
        "  FROM unnest(string_to_array(i.indkey::text, ' ')::int[]) WITH ORDINALITY AS k(attnum, ord)"
        "  JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum"
        ") AS cols, "
        "pg_get_expr(i.indpred, i.indrelid) AS pred, "
        "i.indisvalid AS valid, i.indisready AS ready, "
        "(SELECT relname FROM pg_class WHERE oid = i.indrelid) AS table_name "
        "FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = :name"
    ), {"schema": schema, "name": ACTIVE_UNIQUE_INDEX_NAME}).first()
    return row


def create_chapter_audio_active_unique_index(
    conn: sa.engine.Connection, *, schema: str = "public", concurrent: bool = True
) -> None:
    """创建 chapter_audios 部分唯一索引（唯一 active 合同，R10/P0-4）。

    ``concurrent=True`` 使用 ``CREATE/DROP INDEX CONCURRENTLY``——调用方连接必须处于
    autocommit（Alembic ``autocommit_block`` 或 ``isolation_level='AUTOCOMMIT'``）；
    ``concurrent=False`` 为阻塞式（测试/维护窗口可写入阻塞场景）。

    同名索引身份校验（R21/P2-2）：
    - 定义一致且有效 → 幂等返回；
    - 定义一致的 INVALID → 校验 schema/表/列/谓词后 DROP 重建；
    - 同名不同定义的有效索引 → 抛错停止 Contract，转人工处置。
    """
    drop_sql = (
        f"DROP INDEX CONCURRENTLY IF EXISTS {schema}.{ACTIVE_UNIQUE_INDEX_NAME}"
        if concurrent
        else f"DROP INDEX IF EXISTS {schema}.{ACTIVE_UNIQUE_INDEX_NAME}"
    )
    create_sql = (
        f"CREATE UNIQUE INDEX {'CONCURRENTLY ' if concurrent else ''}"
        f"IF NOT EXISTS {ACTIVE_UNIQUE_INDEX_NAME} "
        f"ON {schema}.chapter_audios (audiobook_project_id, chapter_id) "
        "WHERE deleted_at IS NULL"
    )

    existing = _inspect_active_unique_index(conn, schema=schema)
    if existing is not None:
        expected_cols = ["audiobook_project_id", "chapter_id"]
        expected_pred = "deleted_at IS NULL"
        identity_ok = (
            existing.table_name == "chapter_audios"
            and list(existing.cols or []) == expected_cols
            and (existing.pred or "").strip("( )") == expected_pred
        )
        if not identity_ok:
            raise RuntimeError(
                f"停止 Contract：发现同名但定义不同的索引 {schema}.{ACTIVE_UNIQUE_INDEX_NAME}"
                f"（cols={existing.cols}, pred={existing.pred}, valid={existing.valid}），转人工处置"
            )
        if existing.valid:
            return  # 定义一致且有效：幂等完成
        # 定义一致的 INVALID 索引：身份已校验，DROP 后重建
        conn.execute(text(drop_sql))
    conn.execute(text(create_sql))
