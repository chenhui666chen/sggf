"""remove legacy chapter audio runtime fields

Revision ID: remove_legacy_chapter_audio_runtime_fields
Revises: add_chapter_audio_runs
Create Date: 2026-04-23

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "remove_legacy_chapter_audio_runtime_fields"
down_revision = "add_chapter_audio_runs"
branch_labels = None
depends_on = None


def _get_column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _get_index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    """Drop legacy runtime fields from chapter_audios."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("chapter_audios"):
        return

    column_names = _get_column_names(inspector, "chapter_audios")
    index_names = _get_index_names(inspector, "chapter_audios")

    with op.batch_alter_table("chapter_audios") as batch_op:
        if "ix_chapter_audios_task_id" in index_names:
            batch_op.drop_index("ix_chapter_audios_task_id")
        if "task_id" in column_names:
            batch_op.drop_column("task_id")
        if "generation_progress_json" in column_names:
            batch_op.drop_column("generation_progress_json")


def downgrade() -> None:
    """Restore legacy runtime fields on chapter_audios."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("chapter_audios"):
        return

    column_names = _get_column_names(inspector, "chapter_audios")
    index_names = _get_index_names(inspector, "chapter_audios")

    with op.batch_alter_table("chapter_audios") as batch_op:
        if "generation_progress_json" not in column_names:
            batch_op.add_column(sa.Column("generation_progress_json", sa.Text(), nullable=True))
        if "task_id" not in column_names:
            batch_op.add_column(sa.Column("task_id", sa.String(length=100), nullable=True))

    if "task_id" not in column_names and "ix_chapter_audios_task_id" not in index_names:
        op.create_index("ix_chapter_audios_task_id", "chapter_audios", ["task_id"], unique=False)
