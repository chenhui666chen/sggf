"""add project settings review meta

Revision ID: add_project_settings_review_meta
Revises: add_project_review_config
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa


revision = "add_project_settings_review_meta"
down_revision = "add_project_review_config"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if _has_column("project_settings", "review_meta"):
        return
    op.add_column("project_settings", sa.Column("review_meta", sa.Text(), nullable=True))


def downgrade() -> None:
    if not _has_column("project_settings", "review_meta"):
        return
    op.drop_column("project_settings", "review_meta")
