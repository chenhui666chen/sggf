"""Phase 1.1 Contract 收尾：暂缓项门禁收窄（GUIDE §1.1/R14/P1-b 二阶段）。

Revision ID: contract_audiobook_isolation_finalize
Revises: contract_audiobook_isolation_schema
Create Date: 2026-08-15

前置条件（测试环境已满足；生产执行前必须确认旧实例为零/drain 完成）：
- 新写路径代码已部署（入队写 dispatch 意图 + chapter_audio_id + 独立 celery_task_id、
  终态关账/聚合/finalizer 已接入）；
- 历史回填完成（history_backfill：snapshot_status/chapter_audio_id/celery_task_id 无 NULL）；
- 父表无遗留暂停态（pause_requested/paused 已清洗并按 run 重新聚合）；
- celery_task_id 无重复值。

收窄项：
- audiobook_projects.snapshot_status NOT NULL（回填后施加）
- chapter_audio_runs.chapter_audio_id NOT NULL（回填后施加）
- chapter_audio_runs.celery_task_id NOT NULL + UNIQUE（回填后施加）
- audiobook_tasks CHECK 二阶段收窄：移除 pause_requested/paused，
  仅保留聚合值域 {pending, running, completed, failed, cancelled,
  completed_with_partial_failure}

回滚方式：downgrade 恢复宽态（NOT NULL → 可空、UNIQUE 删除、CHECK 回 stage1 宽值域）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import op

_REPO_ROOT = str(Path(__file__).resolve().parents[3])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import text  # noqa: E402

revision = "contract_audiobook_isolation_finalize"
down_revision = "contract_audiobook_isolation_schema"
branch_labels = None
depends_on = None

_TASKS_CHECK_STAGE1 = "ck_audiobook_tasks_status_stage1"
_TASKS_CHECK_STAGE2 = "ck_audiobook_tasks_status_stage2"
_CELERY_UNIQUE = "uq_chapter_audio_runs_celery_task_id"


def _verify_fail_closed(conn) -> None:
    """数据门禁（fail-closed）：任一残留即中止收窄。"""
    checks = (
        ("audiobook_projects.snapshot_status NULL", "SELECT count(*) FROM audiobook_projects WHERE snapshot_status IS NULL"),
        ("chapter_audio_runs.chapter_audio_id NULL", "SELECT count(*) FROM chapter_audio_runs WHERE chapter_audio_id IS NULL"),
        ("chapter_audio_runs.celery_task_id NULL", "SELECT count(*) FROM chapter_audio_runs WHERE celery_task_id IS NULL"),
        ("chapter_audio_runs.celery_task_id 重复", "SELECT count(*) FROM (SELECT celery_task_id FROM chapter_audio_runs WHERE celery_task_id IS NOT NULL GROUP BY celery_task_id HAVING count(*) > 1) t"),
        ("audiobook_tasks 遗留暂停态", "SELECT count(*) FROM audiobook_tasks WHERE status IN ('pause_requested','paused')"),
    )
    for label, sql in checks:
        count = conn.execute(text(sql)).scalar()
        if count:
            raise RuntimeError(f"Contract 收尾门禁未通过：{label} 残留 {count} 行")


def upgrade() -> None:
    conn = op.get_bind()
    _verify_fail_closed(conn)

    # 1. snapshot_status NOT NULL
    op.execute(
        "ALTER TABLE public.audiobook_projects ALTER COLUMN snapshot_status SET NOT NULL"
    )
    # 2. runs.chapter_audio_id NOT NULL
    op.execute(
        "ALTER TABLE public.chapter_audio_runs ALTER COLUMN chapter_audio_id SET NOT NULL"
    )
    # 3. runs.celery_task_id NOT NULL + UNIQUE
    op.execute(
        "ALTER TABLE public.chapter_audio_runs ALTER COLUMN celery_task_id SET NOT NULL"
    )
    op.execute(
        f"CREATE UNIQUE INDEX {_CELERY_UNIQUE} ON public.chapter_audio_runs (celery_task_id)"
    )
    # 4. tasks CHECK 二阶段收窄（R14/P1-b ④）
    op.execute(f"ALTER TABLE public.audiobook_tasks DROP CONSTRAINT IF EXISTS {_TASKS_CHECK_STAGE1}")
    op.execute(
        f"ALTER TABLE public.audiobook_tasks ADD CONSTRAINT {_TASKS_CHECK_STAGE2} "
        "CHECK (status IN ('pending','running','completed','failed','cancelled',"
        "'completed_with_partial_failure'))"
    )


def downgrade() -> None:
    # 回 stage1 宽 CHECK（含暂停态，Expand 态兼容读写）
    op.execute(f"ALTER TABLE public.audiobook_tasks DROP CONSTRAINT IF EXISTS {_TASKS_CHECK_STAGE2}")
    op.execute(
        f"ALTER TABLE public.audiobook_tasks ADD CONSTRAINT {_TASKS_CHECK_STAGE1} "
        "CHECK (status IN ('pending','running','completed','failed','cancelled',"
        "'completed_with_partial_failure','pause_requested','paused'))"
    )
    op.execute(f"DROP INDEX IF EXISTS public.{_CELERY_UNIQUE}")
    op.execute("ALTER TABLE public.chapter_audio_runs ALTER COLUMN celery_task_id DROP NOT NULL")
    op.execute("ALTER TABLE public.chapter_audio_runs ALTER COLUMN chapter_audio_id DROP NOT NULL")
    op.execute("ALTER TABLE public.audiobook_projects ALTER COLUMN snapshot_status DROP NOT NULL")
