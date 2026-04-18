"""rebuild user asset records for local-first assets

Revision ID: rebuild_user_asset_records_local_first
Revises: cleanup_redundant_indexes
Create Date: 2026-04-19

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "rebuild_user_asset_records_local_first"
down_revision = "cleanup_redundant_indexes"
branch_labels = None
depends_on = None


def _create_new_schema() -> None:
    op.create_table(
        "user_asset_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("source_module", sa.String(length=50), nullable=False),
        sa.Column("asset_kind", sa.String(length=30), nullable=False),
        sa.Column("asset_class", sa.String(length=30), nullable=False, server_default="reusable"),
        sa.Column("asset_uuid", sa.String(length=120), nullable=False),
        sa.Column("storage_mode", sa.String(length=30), nullable=False, server_default="temp_cloud"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_uri", sa.String(length=1000), nullable=True),
        sa.Column("preview_uri", sa.String(length=1000), nullable=True),
        sa.Column("download_uri", sa.String(length=1000), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_user_asset_records_asset_uuid", "user_asset_records", ["asset_uuid"], unique=False)
    op.create_index("ix_user_asset_records_storage_mode", "user_asset_records", ["storage_mode"], unique=False)
    op.create_index("ix_user_asset_records_is_favorite", "user_asset_records", ["is_favorite"], unique=False)
    op.create_index("ix_user_asset_records_archived_at", "user_asset_records", ["archived_at"], unique=False)
    op.create_index("ix_user_asset_records_expires_at", "user_asset_records", ["expires_at"], unique=False)


def _create_old_schema() -> None:
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


def upgrade() -> None:
    """开发阶段直接重建 user_asset_records 表，切换到 local-first 结构。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("user_asset_records"):
        op.drop_table("user_asset_records")

    _create_new_schema()


def downgrade() -> None:
    """回退到旧版 user_asset_records 结构。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("user_asset_records"):
        op.drop_table("user_asset_records")

    _create_old_schema()
