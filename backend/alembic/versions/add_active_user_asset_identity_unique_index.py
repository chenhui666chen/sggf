"""add active user asset identity unique index

Revision ID: add_active_user_asset_identity_unique_index
Revises: align_chapter_audios_with_runtime_model
Create Date: 2026-04-24

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_active_user_asset_identity_unique_index"
down_revision = "align_chapter_audios_with_runtime_model"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_user_asset_records_active_identity"
TABLE_NAME = "user_asset_records"


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in inspector.get_indexes(table_name)}


def _assert_no_active_duplicates(bind) -> None:
    duplicate_rows = bind.execute(
        sa.text(
            """
            SELECT user_id, source_module, asset_kind, asset_uuid, COUNT(*) AS duplicate_count
            FROM user_asset_records
            WHERE archived_at IS NULL
            GROUP BY user_id, source_module, asset_kind, asset_uuid
            HAVING COUNT(*) > 1
            ORDER BY duplicate_count DESC, user_id, source_module, asset_kind, asset_uuid
            LIMIT 10
            """
        )
    ).fetchall()
    if not duplicate_rows:
        return

    preview = "; ".join(
        (
            f"user_id={row.user_id}, source_module={row.source_module}, "
            f"asset_kind={row.asset_kind}, asset_uuid={row.asset_uuid}, count={row.duplicate_count}"
        )
        for row in duplicate_rows
    )
    raise RuntimeError(
        "检测到未归档 user_asset_records 重复数据，无法创建唯一索引："
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
        ["user_id", "source_module", "asset_kind", "asset_uuid"],
        unique=True,
        sqlite_where=sa.text("archived_at IS NULL"),
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table(TABLE_NAME):
        return
    if not _has_index(inspector, TABLE_NAME, INDEX_NAME):
        return

    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
