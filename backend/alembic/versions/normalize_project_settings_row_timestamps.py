"""normalize project_settings row timestamps

Revision ID: normalize_project_settings_row_timestamps
Revises: normalize_timezone_aware_timestamps
Create Date: 2026-03-18

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "normalize_project_settings_row_timestamps"
down_revision = "normalize_timezone_aware_timestamps"
branch_labels = None
depends_on = None


TARGET_COLUMNS: tuple[str, ...] = (
    "created_at",
    "updated_at",
)


def _is_timezone_aware(column_type: sa.types.TypeEngine | None) -> bool:
    return bool(getattr(column_type, "timezone", False))


def _alter_project_settings_columns(*, to_timezone_aware: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("normalize_project_settings_row_timestamps only supports PostgreSQL")

    inspector = sa.inspect(bind)
    column_map = {
        column["name"]: column["type"]
        for column in inspector.get_columns("project_settings")
    }
    target_sql_type = "TIMESTAMP WITH TIME ZONE" if to_timezone_aware else "TIMESTAMP WITHOUT TIME ZONE"

    for column_name in TARGET_COLUMNS:
        column_type = column_map.get(column_name)
        if column_type is None:
            continue
        if _is_timezone_aware(column_type) == to_timezone_aware:
            continue

        op.execute(
            sa.text(
                f'''
                ALTER TABLE "project_settings"
                ALTER COLUMN "{column_name}"
                TYPE {target_sql_type}
                USING "{column_name}" AT TIME ZONE 'UTC'
                '''
            )
        )


def upgrade() -> None:
    _alter_project_settings_columns(to_timezone_aware=True)


def downgrade() -> None:
    _alter_project_settings_columns(to_timezone_aware=False)
