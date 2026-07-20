"""add audio library asset ratings

Revision ID: add_audio_library_asset_ratings
Revises: add_project_settings_review_meta
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_audio_library_asset_ratings"
down_revision = "add_project_settings_review_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("audio_library_asset_ratings"):
        return

    op.create_table(
        "audio_library_asset_ratings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Integer(),
            sa.ForeignKey("audio_library_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "score >= 1 AND score <= 5",
            name="ck_audio_library_asset_ratings_score",
        ),
        sa.UniqueConstraint(
            "asset_id",
            "user_id",
            name="uq_audio_library_asset_ratings_asset_user",
        ),
    )
    op.create_index(
        "ix_audio_library_asset_ratings_asset_id",
        "audio_library_asset_ratings",
        ["asset_id"],
    )
    op.create_index(
        "ix_audio_library_asset_ratings_user_id",
        "audio_library_asset_ratings",
        ["user_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("audio_library_asset_ratings"):
        return
    op.drop_table("audio_library_asset_ratings")
