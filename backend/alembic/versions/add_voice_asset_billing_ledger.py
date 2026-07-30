"""add voice asset billing ledger table

Revision ID: add_voice_asset_billing_ledger
Revises: add_voice_reference_assets
Create Date: 2026-07-22

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_voice_asset_billing_ledger"
down_revision = "add_voice_reference_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("voice_asset_billing_ledger"):
        return

    op.create_table(
        "voice_asset_billing_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("account_scope", sa.String(length=40), nullable=False, server_default="user"),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("voice_id", sa.String(length=255), nullable=True),
        sa.Column("voice_asset_id", sa.String(length=160), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("billable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fixed_fee_yuan", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="CNY"),
        sa.Column("charge_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("provider_charge_id", sa.String(length=255), nullable=True),
        sa.Column("provider_charge_receipt", sa.String(length=1000), nullable=True),
        sa.Column("charged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("event_payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_voice_asset_billing_ledger_idem"),
    )
    op.create_index("ix_voice_asset_billing_ledger_idempotency_key", "voice_asset_billing_ledger", ["idempotency_key"])
    op.create_index("ix_voice_asset_billing_ledger_owner_user_id", "voice_asset_billing_ledger", ["owner_user_id"])
    op.create_index("ix_voice_asset_billing_ledger_provider", "voice_asset_billing_ledger", ["provider"])
    op.create_index("ix_voice_asset_billing_ledger_model", "voice_asset_billing_ledger", ["model"])
    op.create_index("ix_voice_asset_billing_ledger_voice_id", "voice_asset_billing_ledger", ["voice_id"])
    op.create_index("ix_voice_asset_billing_ledger_voice_asset_id", "voice_asset_billing_ledger", ["voice_asset_id"])
    op.create_index("ix_voice_asset_billing_ledger_event_type", "voice_asset_billing_ledger", ["event_type"])
    op.create_index("ix_voice_asset_billing_ledger_charge_status", "voice_asset_billing_ledger", ["charge_status"])
    op.create_index(
        "ix_voice_asset_billing_ledger_voice",
        "voice_asset_billing_ledger",
        ["provider", "model", "voice_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("voice_asset_billing_ledger"):
        return
    op.drop_table("voice_asset_billing_ledger")
