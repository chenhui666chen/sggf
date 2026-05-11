"""add shared audio library assets table

Revision ID: add_audio_library_assets
Revises: add_active_user_asset_identity_unique_index
Create Date: 2026-05-07

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_audio_library_assets"
down_revision = "add_active_user_asset_identity_unique_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("audio_library_assets"):
        return

    op.create_table(
        "audio_library_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("library_type", sa.String(length=20), nullable=False),
        sa.Column("asset_scope", sa.String(length=30), nullable=False, server_default="shared_library"),
        sa.Column("asset_key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("style", sa.String(length=120), nullable=True),
        sa.Column("mood", sa.String(length=80), nullable=True),
        sa.Column("tempo", sa.String(length=80), nullable=True),
        sa.Column("bucket", sa.String(length=120), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("variant", sa.Integer(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("storage_mode", sa.String(length=30), nullable=False, server_default="local_cache"),
        sa.Column("storage_driver", sa.String(length=60), nullable=False, server_default="local_fs"),
        sa.Column("cloud_uri", sa.String(length=1000), nullable=True),
        sa.Column("public_url", sa.String(length=1000), nullable=True),
        sa.Column("object_key", sa.String(length=1000), nullable=True),
        sa.Column("local_cache_path", sa.String(length=1000), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("source_id", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("author_url", sa.String(length=1000), nullable=True),
        sa.Column("license", sa.String(length=160), nullable=True),
        sa.Column("license_url", sa.String(length=1000), nullable=True),
        sa.Column("license_version", sa.String(length=40), nullable=True),
        sa.Column("license_commercial", sa.Boolean(), nullable=True),
        sa.Column("attribution_required", sa.Boolean(), nullable=True),
        sa.Column("attribution_text", sa.Text(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("quality_grade", sa.String(length=10), nullable=True),
        sa.Column("quality_status", sa.String(length=30), nullable=True),
        sa.Column("sha256", sa.String(length=128), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("scenes", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("source_payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("retrieved_at", sa.String(length=80), nullable=True),
        sa.Column("license_checked_at", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("library_type", "asset_key", name="uq_audio_library_assets_type_key"),
    )
    op.create_index("ix_audio_library_assets_library_type", "audio_library_assets", ["library_type"])
    op.create_index("ix_audio_library_assets_asset_scope", "audio_library_assets", ["asset_scope"])
    op.create_index("ix_audio_library_assets_asset_key", "audio_library_assets", ["asset_key"])
    op.create_index("ix_audio_library_assets_category", "audio_library_assets", ["category"])
    op.create_index("ix_audio_library_assets_style", "audio_library_assets", ["style"])
    op.create_index("ix_audio_library_assets_mood", "audio_library_assets", ["mood"])
    op.create_index("ix_audio_library_assets_bucket", "audio_library_assets", ["bucket"])
    op.create_index("ix_audio_library_assets_storage_mode", "audio_library_assets", ["storage_mode"])
    op.create_index("ix_audio_library_assets_storage_driver", "audio_library_assets", ["storage_driver"])
    op.create_index("ix_audio_library_assets_quality_status", "audio_library_assets", ["quality_status"])
    op.create_index("ix_audio_library_assets_source", "audio_library_assets", ["source"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("audio_library_assets"):
        return
    op.drop_table("audio_library_assets")
