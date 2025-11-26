"""add setting models

Revision ID: add_setting_models
Revises: add_chapter_summary_fields_to_existing_table
Create Date: 2025-11-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_setting_models"
down_revision = "add_chapter_summary_fields_to_existing_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 setting_collections 和 setting_items 表"""
    op.create_table(
        "setting_collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False, index=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_setting_collections_project_id",
        "setting_collections",
        ["project_id"],
    )

    op.create_table(
        "setting_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("collection_id", sa.Integer(), nullable=False, index=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("relations", sa.Text(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["setting_collections.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_setting_items_collection_id",
        "setting_items",
        ["collection_id"],
    )


def downgrade() -> None:
    """删除 setting_collections 和 setting_items 表"""
    op.drop_index("ix_setting_items_collection_id", table_name="setting_items")
    op.drop_table("setting_items")
    op.drop_index("ix_setting_collections_project_id", table_name="setting_collections")
    op.drop_table("setting_collections")

