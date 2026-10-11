"""add chapter project number unique index

Revision ID: add_chapter_project_number_unique_index
Revises: add_consent_records_and_user_rights
Create Date: 2026-10-07

阶段 B WP2：为活跃章节 (project_id, chapter_number) 增加部分唯一索引，
软删除行（deleted_at IS NOT NULL）不参与约束，允许删章后同号复用。
建索引前自检存量重复，若存在活跃重复则 raise（不静默改数据）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_chapter_project_number_unique_index"
down_revision = "add_consent_records_and_user_rights"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_chapters_project_number_active"
TABLE_NAME = "chapters"


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def _assert_no_active_duplicates(bind) -> None:
    duplicate_rows = bind.execute(
        sa.text(
            """
            SELECT project_id, chapter_number, COUNT(*) AS duplicate_count
            FROM chapters
            WHERE deleted_at IS NULL
            GROUP BY project_id, chapter_number
            HAVING COUNT(*) > 1
            ORDER BY duplicate_count DESC, project_id, chapter_number
            LIMIT 10
            """
        )
    ).fetchall()
    if not duplicate_rows:
        return

    preview = "; ".join(
        (
            f"project_id={row.project_id}, "
            f"chapter_number={row.chapter_number}, count={row.duplicate_count}"
        )
        for row in duplicate_rows
    )
    raise RuntimeError(
        "检测到未软删除的 chapters 重复 (project_id, chapter_number)，无法创建唯一索引："
        f"{preview}"
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table(TABLE_NAME):
        return
    if _has_index(inspector, TABLE_NAME, INDEX_NAME):
        return

    _assert_no_active_duplicates(bind)
    op.create_index(
        INDEX_NAME,
        TABLE_NAME,
        ["project_id", "chapter_number"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table(TABLE_NAME):
        return
    if not _has_index(inspector, TABLE_NAME, INDEX_NAME):
        return

    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
