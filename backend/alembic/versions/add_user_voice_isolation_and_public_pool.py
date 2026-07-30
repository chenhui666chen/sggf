"""add user voice isolation and public voice pool

Revision ID: add_user_voice_public_pool
Revises: add_voice_asset_billing_ledger
Create Date: 2026-07-23

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_user_voice_public_pool"
down_revision = "add_voice_asset_billing_ledger"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {str(index["name"]) for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("voice_reference_assets"):
        columns = _column_names(inspector, "voice_reference_assets")
        additions = (
            sa.Column(
                "owner_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("authorization_basis", sa.String(length=60), nullable=True),
            sa.Column(
                "authorized_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "revoked_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("revoke_reason", sa.Text(), nullable=True),
            sa.Column(
                "cleanup_status",
                sa.String(length=30),
                nullable=False,
                server_default="not_requested",
            ),
            sa.Column("cleanup_requested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cleanup_error", sa.Text(), nullable=True),
        )
        for column in additions:
            if column.name not in columns:
                op.add_column("voice_reference_assets", column)

        inspector = sa.inspect(bind)
        indexes = _index_names(inspector, "voice_reference_assets")
        simple_indexes = {
            "ix_voice_reference_assets_owner_user_id": ["owner_user_id"],
            "ix_voice_reference_assets_authorized_by_user_id": ["authorized_by_user_id"],
            "ix_voice_reference_assets_cleanup_status": ["cleanup_status"],
            "ix_voice_reference_assets_deleted_at": ["deleted_at"],
        }
        for name, columns in simple_indexes.items():
            if name not in indexes:
                op.create_index(name, "voice_reference_assets", columns)
        if "ix_voice_reference_assets_owner_active" not in indexes:
            op.create_index(
                "ix_voice_reference_assets_owner_active",
                "voice_reference_assets",
                ["owner_user_id", "revoked_at", "deleted_at"],
            )

    inspector = sa.inspect(bind)
    if not inspector.has_table("voice_pool_publications"):
        op.create_table(
            "voice_pool_publications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("publication_id", sa.String(length=80), nullable=False),
            sa.Column(
                "source_asset_id",
                sa.Integer(),
                sa.ForeignKey("voice_reference_assets.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "owner_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("display_name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("voice_origin", sa.String(length=30), nullable=False),
            sa.Column("source_model", sa.String(length=120), nullable=True),
            sa.Column("gender_presentation", sa.String(length=30), nullable=False),
            sa.Column("age_impression", sa.String(length=30), nullable=False),
            sa.Column("primary_style", sa.String(length=40), nullable=False),
            sa.Column("language", sa.String(length=30), nullable=False),
            sa.Column("accent", sa.String(length=60), nullable=True),
            sa.Column("timbre_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("scenario_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("emotion_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("rights_basis", sa.String(length=60), nullable=False),
            sa.Column("license_version", sa.String(length=40), nullable=False),
            sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("public_preview_uri", sa.String(length=1000), nullable=False),
            sa.Column("public_reference_uri", sa.String(length=1000), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending_review"),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column(
                "reviewed_by_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("publication_id", name="uq_voice_pool_publications_publication_id"),
            sa.UniqueConstraint("source_asset_id", name="uq_voice_pool_publications_source_asset"),
        )
        for column in (
            "publication_id",
            "source_asset_id",
            "owner_user_id",
            "voice_origin",
            "source_model",
            "gender_presentation",
            "age_impression",
            "primary_style",
            "language",
            "accent",
            "rights_basis",
            "status",
        ):
            op.create_index(
                f"ix_voice_pool_publications_{column}",
                "voice_pool_publications",
                [column],
            )
        op.create_index(
            "ix_voice_pool_publications_discovery",
            "voice_pool_publications",
            ["status", "gender_presentation", "age_impression", "primary_style"],
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table("voice_pool_ratings"):
        op.create_table(
            "voice_pool_ratings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "publication_id",
                sa.Integer(),
                sa.ForeignKey("voice_pool_publications.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_voice_pool_ratings_score"),
            sa.UniqueConstraint(
                "publication_id",
                "user_id",
                name="uq_voice_pool_ratings_publication_user",
            ),
        )
        op.create_index(
            "ix_voice_pool_ratings_publication_id",
            "voice_pool_ratings",
            ["publication_id"],
        )
        op.create_index("ix_voice_pool_ratings_user_id", "voice_pool_ratings", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("voice_pool_ratings"):
        op.drop_table("voice_pool_ratings")
    if inspector.has_table("voice_pool_publications"):
        op.drop_table("voice_pool_publications")
    if not inspector.has_table("voice_reference_assets"):
        return

    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, "voice_reference_assets")
    for index_name in (
        "ix_voice_reference_assets_owner_active",
        "ix_voice_reference_assets_deleted_at",
        "ix_voice_reference_assets_cleanup_status",
        "ix_voice_reference_assets_authorized_by_user_id",
        "ix_voice_reference_assets_owner_user_id",
    ):
        if index_name in indexes:
            op.drop_index(index_name, table_name="voice_reference_assets")
    columns = _column_names(sa.inspect(bind), "voice_reference_assets")
    for column_name in (
        "cleanup_error",
        "deleted_at",
        "cleanup_requested_at",
        "cleanup_status",
        "revoke_reason",
        "revoked_by_user_id",
        "authorized_by_user_id",
        "authorization_basis",
        "owner_user_id",
    ):
        if column_name in columns:
            op.drop_column("voice_reference_assets", column_name)
