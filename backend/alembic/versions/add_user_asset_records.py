"""add user asset records

Revision ID: add_user_asset_records
Revises: merge_effective_heads_after_model_catalog
Create Date: 2026-03-21

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_user_asset_records"
down_revision = "merge_effective_heads_after_model_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建用户资产记录表。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("user_asset_records"):
        return

    op.create_table(
        "user_asset_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("source_module", sa.String(length=50), nullable=False),
        sa.Column("asset_kind", sa.String(length=30), nullable=False),
        sa.Column("asset_class", sa.String(length=30), nullable=False, server_default="reusable"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_url", sa.String(length=1000), nullable=True),
        sa.Column("preview_url", sa.String(length=1000), nullable=True),
        sa.Column("model_id", sa.String(length=120), nullable=True),
        sa.Column("generation_mode", sa.String(length=80), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("source_payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_user_asset_records_user_id", "user_asset_records", ["user_id"], unique=False)
    op.create_index("ix_user_asset_records_project_id", "user_asset_records", ["project_id"], unique=False)
    op.create_index("ix_user_asset_records_source_module", "user_asset_records", ["source_module"], unique=False)
    op.create_index("ix_user_asset_records_asset_kind", "user_asset_records", ["asset_kind"], unique=False)
    op.create_index("ix_user_asset_records_asset_class", "user_asset_records", ["asset_class"], unique=False)
    op.create_index("ix_user_asset_records_is_favorite", "user_asset_records", ["is_favorite"], unique=False)
    op.create_index("ix_user_asset_records_archived_at", "user_asset_records", ["archived_at"], unique=False)


def downgrade() -> None:
    """删除用户资产记录表。"""

    op.drop_index("ix_user_asset_records_archived_at", table_name="user_asset_records")
    op.drop_index("ix_user_asset_records_is_favorite", table_name="user_asset_records")
    op.drop_index("ix_user_asset_records_asset_class", table_name="user_asset_records")
    op.drop_index("ix_user_asset_records_asset_kind", table_name="user_asset_records")
    op.drop_index("ix_user_asset_records_source_module", table_name="user_asset_records")
    op.drop_index("ix_user_asset_records_project_id", table_name="user_asset_records")
    op.drop_index("ix_user_asset_records_user_id", table_name="user_asset_records")
    op.drop_table("user_asset_records")
