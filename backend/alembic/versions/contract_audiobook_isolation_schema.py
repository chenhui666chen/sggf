"""Phase 1.1 Contract：门禁化约束收窄（GUIDE §1.1 Contract 发布单元）。

Revision ID: contract_audiobook_isolation_schema
Revises: expand_audiobook_isolation_schema
Create Date: 2026-08-15

发布单元合同（GUIDE §5 阶段 1.1）：
- 前置条件：Migrate 历史回填与 canonical 去重完成、迁移报告门禁通过、
  全表无重复 active 组（本迁移 upgrade 内 fail-closed 复核）；
- 收窄项：engine_mode NOT NULL+默认+CHECK、snapshot 三态与一致性 CHECK、
  dispatch_status NOT NULL+默认+CHECK、run status 值域 CHECK、
  chapter_audios 部分唯一索引（CONCURRENTLY，autocommit 块）；
- 回滚方式：downgrade 以 DROP CONSTRAINT/DROP INDEX 恢复宽态（Expand 态兼容读写仍可用）。

暂缓项（门禁依赖新写路径代码，另行排期）：snapshot_status NOT NULL、
chapter_audio_runs.chapter_audio_id NOT NULL、celery_task_id NOT NULL+UNIQUE、
audiobook_tasks CHECK 二阶段收窄。
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import op

# 包导入会触发 app.services.audiobook.__init__ 的重量依赖链（依赖仓库根 core 包）：先自举 sys.path
_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 服务模块本体仅依赖 sqlalchemy（无重量依赖链）
from app.services.audiobook.contract_constraints import (
    ACTIVE_UNIQUE_INDEX_NAME,
    apply_project_contract,
    apply_run_contract,
    create_chapter_audio_active_unique_index,
    verify_no_duplicate_active,
)

revision = "contract_audiobook_isolation_schema"
down_revision = "expand_audiobook_isolation_schema"
branch_labels = None
depends_on = None

_PROJECT_CHECKS = (
    "ck_audiobook_projects_engine_mode",
    "ck_audiobook_projects_snapshot_status",
    "ck_audiobook_projects_snapshot_consistency",
)
_RUN_CHECKS = (
    "ck_chapter_audio_runs_dispatch_status",
    "ck_chapter_audio_runs_status",
)


def upgrade() -> None:
    conn = op.get_bind()

    # 门禁（fail-closed）：全表无重复 active 组——部分唯一索引的准入条件（GUIDE §1.1 Contract）
    duplicates = verify_no_duplicate_active(conn, schema="public")
    if duplicates:
        raise RuntimeError(
            f"Contract 门禁未通过：存在 {len(duplicates)} 个重复 active 组"
            f"（示例：{duplicates[:5]}），先完成 canonical 去重迁移"
        )

    # 事务性 DDL：NOT NULL / server_default / CHECK / 普通索引（各步骤内含数据门禁）
    apply_project_contract(conn, schema="public")
    apply_run_contract(conn, schema="public")

    # 部分唯一索引：CONCURRENTLY 不能在事务块内执行（R20/P1-2 执行载体约束）
    with op.get_context().autocommit_block():
        create_chapter_audio_active_unique_index(conn, schema="public", concurrent=True)


def downgrade() -> None:
    conn = op.get_bind()
    with op.get_context().autocommit_block():
        conn.exec_driver_sql(f"DROP INDEX CONCURRENTLY IF EXISTS public.{ACTIVE_UNIQUE_INDEX_NAME}")

    for name in _RUN_CHECKS:
        op.execute(f"ALTER TABLE public.chapter_audio_runs DROP CONSTRAINT IF EXISTS {name}")
    op.execute("ALTER TABLE public.chapter_audio_runs ALTER COLUMN dispatch_status DROP NOT NULL")
    op.execute("ALTER TABLE public.chapter_audio_runs ALTER COLUMN dispatch_status DROP DEFAULT")

    for name in _PROJECT_CHECKS:
        op.execute(f"ALTER TABLE public.audiobook_projects DROP CONSTRAINT IF EXISTS {name}")
    op.execute("ALTER TABLE public.audiobook_projects ALTER COLUMN engine_mode DROP NOT NULL")
    op.execute("ALTER TABLE public.audiobook_projects ALTER COLUMN engine_mode DROP DEFAULT")
    op.execute("DROP INDEX IF EXISTS public.ix_audiobook_projects_engine_mode_deleted")
