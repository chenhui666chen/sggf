"""align remaining timestamp columns

Revision ID: align_remaining_timestamp_columns
Revises: normalize_project_settings_row_timestamps
Create Date: 2026-03-18

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "align_remaining_timestamp_columns"
down_revision = "normalize_project_settings_row_timestamps"
branch_labels = None
depends_on = None


TARGET_COLUMNS: dict[str, tuple[str, ...]] = {
    "audiobook_delete_audits": ("deleted_at", "restored_at"),
    "audiobook_projects": ("created_at", "updated_at", "completed_at", "deleted_at"),
    "audiobook_tasks": ("created_at", "updated_at", "started_at", "finished_at"),
    "chapter_audios": ("created_at", "updated_at", "deleted_at"),
    "chapter_plans": ("created_at", "updated_at"),
    "generation_history": ("created_at", "completed_at", "updated_at"),
    "knowledge_base": ("created_at", "updated_at"),
    "project_settings": ("epic_framework_generated_at",),
    "review_results": ("created_at",),
    "workflow_sessions": ("started_at", "completed_at"),
}


def _is_timezone_aware(column_type: sa.types.TypeEngine | None) -> bool:
    return bool(getattr(column_type, "timezone", False))


def _alter_timestamp_columns(*, to_timezone_aware: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("align_remaining_timestamp_columns only supports PostgreSQL")

    inspector = sa.inspect(bind)
    target_sql_type = "TIMESTAMP WITH TIME ZONE" if to_timezone_aware else "TIMESTAMP WITHOUT TIME ZONE"

    for table_name, column_names in TARGET_COLUMNS.items():
        if not inspector.has_table(table_name):
            continue

        column_map = {
            column["name"]: column["type"]
            for column in inspector.get_columns(table_name)
        }

        for column_name in column_names:
            column_type = column_map.get(column_name)
            if column_type is None:
                continue
            if _is_timezone_aware(column_type) == to_timezone_aware:
                continue

            op.execute(
                sa.text(
                    f'''
                    ALTER TABLE "{table_name}"
                    ALTER COLUMN "{column_name}"
                    TYPE {target_sql_type}
                    USING "{column_name}" AT TIME ZONE 'UTC'
                    '''
                )
            )


def upgrade() -> None:
    _alter_timestamp_columns(to_timezone_aware=True)


def downgrade() -> None:
    _alter_timestamp_columns(to_timezone_aware=False)
