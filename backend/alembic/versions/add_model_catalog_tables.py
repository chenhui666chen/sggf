"""add model catalog tables

Revision ID: add_model_catalog_tables
Revises: align_remaining_timestamp_columns
Create Date: 2026-03-20

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_model_catalog_tables"
down_revision = "align_remaining_timestamp_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建模型档案中心主表与来源校验表。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("model_catalog_entries"):
        op.create_table(
            "model_catalog_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("model_key", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("provider", sa.String(length=80), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False),
            sa.Column("subcategory", sa.String(length=80), nullable=True),
            sa.Column("model_family", sa.String(length=120), nullable=True),
            sa.Column("config_source", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("recommended_scenarios", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("limitations", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("integration_notes", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("documentation_url", sa.String(length=1000), nullable=True),
            sa.Column("source_urls", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("modalities", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("capabilities_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("constraints_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("performance_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("routing_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("default_params_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("raw_config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("verification_status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("verification_scope", sa.String(length=120), nullable=True),
            sa.Column("verification_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("total_source_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reachable_source_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("verified_source_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("verification_notes", sa.Text(), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("model_key", name="uq_model_catalog_entries_model_key"),
        )
        op.create_index("ix_model_catalog_entries_model_key", "model_catalog_entries", ["model_key"], unique=False)
        op.create_index("ix_model_catalog_entries_provider", "model_catalog_entries", ["provider"], unique=False)
        op.create_index("ix_model_catalog_entries_category", "model_catalog_entries", ["category"], unique=False)
        op.create_index(
            "ix_model_catalog_entries_verification_status",
            "model_catalog_entries",
            ["verification_status"],
            unique=False,
        )

    if not inspector.has_table("model_catalog_sources"):
        op.create_table(
            "model_catalog_sources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entry_id", sa.Integer(), nullable=False),
            sa.Column("url", sa.String(length=1000), nullable=False),
            sa.Column("source_type", sa.String(length=50), nullable=False),
            sa.Column("source_domain", sa.String(length=255), nullable=True),
            sa.Column("http_status", sa.Integer(), nullable=True),
            sa.Column("reachable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("page_title", sa.String(length=500), nullable=True),
            sa.Column("page_excerpt", sa.Text(), nullable=True),
            sa.Column("matched_keywords", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("verification_note", sa.Text(), nullable=True),
            sa.Column("raw_metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["entry_id"], ["model_catalog_entries.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("entry_id", "url", name="uq_model_catalog_sources_entry_url"),
        )
        op.create_index("ix_model_catalog_sources_entry_id", "model_catalog_sources", ["entry_id"], unique=False)


def downgrade() -> None:
    """删除模型档案中心相关表。"""

    op.drop_index("ix_model_catalog_sources_entry_id", table_name="model_catalog_sources")
    op.drop_table("model_catalog_sources")

    op.drop_index("ix_model_catalog_entries_verification_status", table_name="model_catalog_entries")
    op.drop_index("ix_model_catalog_entries_category", table_name="model_catalog_entries")
    op.drop_index("ix_model_catalog_entries_provider", table_name="model_catalog_entries")
    op.drop_index("ix_model_catalog_entries_model_key", table_name="model_catalog_entries")
    op.drop_table("model_catalog_entries")
