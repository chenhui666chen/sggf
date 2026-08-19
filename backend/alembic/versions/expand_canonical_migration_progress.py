"""expand audiobook canonical migration progress table

Expand 发布单元（GUIDE R19/P1-2）：仅新建可空/宽态结构，不收紧任何约束；
幂等可重复执行；允许旧版本实例继续运行；无需维护窗口。

Revision ID: expand_canonical_migration_progress
Revises: add_user_voice_public_pool
Create Date: 2026-08-15

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "expand_canonical_migration_progress"
down_revision = "add_user_voice_public_pool"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("audiobook_canonical_migration_progress"):
        op.create_table(
            "audiobook_canonical_migration_progress",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("migration_version", sa.String(length=64), nullable=False),
            sa.Column("audiobook_project_id", sa.Integer(), nullable=False),
            sa.Column("chapter_id", sa.Integer(), nullable=False),
            sa.Column("canonical_chapter_audio_id", sa.Integer(), nullable=True),
            sa.Column("source_row_ids", sa.JSON(), nullable=True),
            # 本版仅三态（R22/P1-1 方案 A）：多实例升级需同步扩展 CHECK 值域
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_code", sa.String(length=64), nullable=True),
            sa.Column("failure_detail", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "status IN ('pending','completed','failed')",
                name="ck_audiobook_canonical_migration_progress_status",
            ),
            sa.UniqueConstraint(
                "migration_version",
                "audiobook_project_id",
                "chapter_id",
                name="uq_canonical_migration_progress_group",
            ),
        )
        op.create_index(
            "ix_acmp_audiobook_project_id",
            "audiobook_canonical_migration_progress",
            ["audiobook_project_id"],
        )
        op.create_index(
            "ix_acmp_chapter_id",
            "audiobook_canonical_migration_progress",
            ["chapter_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("audiobook_canonical_migration_progress"):
        return
    for index_name in ("ix_acmp_chapter_id", "ix_acmp_audiobook_project_id"):
        if index_name in {str(index["name"]) for index in inspector.get_indexes("audiobook_canonical_migration_progress")}:
            op.drop_index(index_name, table_name="audiobook_canonical_migration_progress")
        inspector = sa.inspect(bind)
    op.drop_table("audiobook_canonical_migration_progress")
