"""add voice reference assets table

Revision ID: add_voice_reference_assets
Revises: add_audio_library_asset_ratings
Create Date: 2026-07-22

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_voice_reference_assets"
down_revision = "add_audio_library_asset_ratings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("voice_reference_assets"):
        return

    op.create_table(
        "voice_reference_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.String(length=160), nullable=False),
        sa.Column("reference_kind", sa.String(length=30), nullable=False),
        sa.Column("reference_field", sa.String(length=20), nullable=False, server_default="speaker"),
        sa.Column("provider", sa.String(length=60), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_model", sa.String(length=120), nullable=True),
        sa.Column("source_voice_id", sa.String(length=255), nullable=True),
        sa.Column("speaker", sa.String(length=255), nullable=True),
        sa.Column("source_preview_cache_key", sa.String(length=255), nullable=True),
        sa.Column("storage_uri", sa.String(length=1000), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("sha256", sa.String(length=128), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("authorization_scope", sa.String(length=40), nullable=False, server_default="account"),
        sa.Column("authorization_version", sa.String(length=40), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("source_payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("asset_id", name="uq_voice_reference_assets_asset_id"),
    )
    op.create_index("ix_voice_reference_assets_asset_id", "voice_reference_assets", ["asset_id"])
    op.create_index("ix_voice_reference_assets_reference_kind", "voice_reference_assets", ["reference_kind"])
    op.create_index("ix_voice_reference_assets_provider", "voice_reference_assets", ["provider"])
    op.create_index("ix_voice_reference_assets_source_type", "voice_reference_assets", ["source_type"])
    op.create_index("ix_voice_reference_assets_source_model", "voice_reference_assets", ["source_model"])
    op.create_index("ix_voice_reference_assets_source_voice_id", "voice_reference_assets", ["source_voice_id"])
    op.create_index("ix_voice_reference_assets_sha256", "voice_reference_assets", ["sha256"])
    op.create_index("ix_voice_reference_assets_authorization_scope", "voice_reference_assets", ["authorization_scope"])
    op.create_index("ix_voice_reference_assets_revoked_at", "voice_reference_assets", ["revoked_at"])
    op.create_index(
        "ix_voice_reference_assets_source_voice",
        "voice_reference_assets",
        ["source_model", "source_voice_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("voice_reference_assets"):
        return
    op.drop_table("voice_reference_assets")
