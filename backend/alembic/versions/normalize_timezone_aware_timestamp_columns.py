"""normalize timezone-aware timestamp columns

Revision ID: normalize_timezone_aware_timestamps
Revises: add_cascade_delete_constraints, add_structured_memory_to_project_settings
Create Date: 2026-03-18

"""

from __future__ import annotations

from collections.abc import Iterable

from alembic import op
import sqlalchemy as sa


revision = "normalize_timezone_aware_timestamps"
down_revision = (
    "add_cascade_delete_constraints",
    "add_structured_memory_to_project_settings",
)
branch_labels = None
depends_on = None


# ORM 中声明为 timezone=True 的列，以及直接由服务层写入 aware datetime 的补充列。
TARGET_COLUMNS: tuple[tuple[str, str], ...] = (
    ("admin_login_logs", "created_at"),
    ("admin_operation_logs", "created_at"),
    ("book_analyses", "created_at"),
    ("book_analyses", "updated_at"),
    ("book_chapters", "created_at"),
    ("book_sources", "created_at"),
    ("book_sources", "updated_at"),
    ("book_sources", "parsed_at"),
    ("chapter_revisions", "created_at"),
    ("chapters", "created_at"),
    ("chapters", "updated_at"),
    ("chapters", "deleted_at"),
    ("character_techniques", "created_at"),
    ("character_techniques", "updated_at"),
    ("characters", "created_at"),
    ("characters", "updated_at"),
    ("dreamweaver_assets", "created_at"),
    ("dreamweaver_assets", "updated_at"),
    ("dreamweaver_episodes", "created_at"),
    ("dreamweaver_episodes", "updated_at"),
    ("dreamweaver_projects", "created_at"),
    ("dreamweaver_projects", "updated_at"),
    ("dreamweaver_run_events", "created_at"),
    ("dreamweaver_shots", "created_at"),
    ("dreamweaver_shots", "updated_at"),
    ("knowledge_graph_edges", "created_at"),
    ("memories", "created_at"),
    ("memories", "updated_at"),
    ("permissions", "created_at"),
    ("project_settings", "structured_memory_updated_at"),
    ("projects", "created_at"),
    ("projects", "updated_at"),
    ("reviews", "created_at"),
    ("reviews", "updated_at"),
    ("role_permissions", "created_at"),
    ("roles", "created_at"),
    ("roles", "updated_at"),
    ("setting_collections", "created_at"),
    ("setting_collections", "updated_at"),
    ("setting_items", "last_referenced_at"),
    ("setting_items", "created_at"),
    ("setting_items", "updated_at"),
    ("user_roles", "created_at"),
    ("users", "created_at"),
    ("users", "updated_at"),
)


def _get_column_types(inspector: sa.Inspector, table_name: str) -> dict[str, sa.types.TypeEngine]:
    return {
        column["name"]: column["type"]
        for column in inspector.get_columns(table_name)
    }


def _is_timezone_aware(column_type: sa.types.TypeEngine | None) -> bool:
    return bool(getattr(column_type, "timezone", False))


def _alter_columns(target_columns: Iterable[tuple[str, str]], *, to_timezone_aware: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("normalize_timezone_aware_timestamps only supports PostgreSQL")

    inspector = sa.inspect(bind)
    table_columns_cache: dict[str, dict[str, sa.types.TypeEngine]] = {}
    target_sql_type = "TIMESTAMP WITH TIME ZONE" if to_timezone_aware else "TIMESTAMP WITHOUT TIME ZONE"

    for table_name, column_name in target_columns:
        if table_name not in table_columns_cache:
            table_columns_cache[table_name] = _get_column_types(inspector, table_name)

        column_type = table_columns_cache[table_name].get(column_name)
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
    _alter_columns(TARGET_COLUMNS, to_timezone_aware=True)


def downgrade() -> None:
    _alter_columns(reversed(TARGET_COLUMNS), to_timezone_aware=False)
