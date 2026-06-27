"""add project review config

Revision ID: add_project_review_config
Revises: add_audio_library_assets
Create Date: 2026-06-28

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_project_review_config"
down_revision = "add_audio_library_assets"
branch_labels = None
depends_on = None

TABLE_NAME = "projects"
COLUMN_NAME = "review_config"


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME) or _has_column(inspector, TABLE_NAME, COLUMN_NAME):
        return

    with op.batch_alter_table(TABLE_NAME, schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                COLUMN_NAME,
                sa.Text(),
                nullable=True,
                comment="评审高级功能配置(JSON)",
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME) or not _has_column(inspector, TABLE_NAME, COLUMN_NAME):
        return

    with op.batch_alter_table(TABLE_NAME, schema=None) as batch_op:
        batch_op.drop_column(COLUMN_NAME)
