"""add prompt experiment tables (online prompt evolution persistence)

Revision ID: add_prompt_experiment_tables
Revises: add_user_voice_public_pool
Create Date: 2026-07-30

设计文档：docs/ONLINE_PROMPT_EVOLUTION_DESIGN_20260730.md §6
四张表：prompt_challengers / prompt_experiments / prompt_experiment_budgets / prompt_champion_assignments
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_prompt_experiment_tables"
down_revision = "add_user_voice_public_pool"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("prompt_challengers"):
        op.create_table(
            "prompt_challengers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("challenger_id", sa.String(length=120), nullable=False),
            sa.Column("genre", sa.String(length=50), nullable=False),
            sa.Column("prompt_text", sa.Text(), nullable=False),
            sa.Column("prompt_hash", sa.String(length=80), nullable=False),
            sa.Column("strategy_desc", sa.Text(), nullable=False),
            sa.Column("strategy_family", sa.String(length=50), nullable=False),
            sa.Column("source_batch", sa.String(length=80), nullable=False),
            sa.Column("offline_gate_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("offline_scores", sa.JSON(), nullable=False),
            sa.Column("serving_mode", sa.String(length=20), nullable=False, server_default="shadow"),
            sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("challenger_id", name="uq_prompt_challengers_challenger_id"),
        )
        op.create_index("ix_prompt_challengers_challenger_id", "prompt_challengers", ["challenger_id"])
        op.create_index("ix_prompt_challengers_genre", "prompt_challengers", ["genre"])
        op.create_index("ix_prompt_challengers_strategy_family", "prompt_challengers", ["strategy_family"])
        op.create_index("ix_prompt_challengers_source_batch", "prompt_challengers", ["source_batch"])
        op.create_index("ix_prompt_challengers_serving_mode", "prompt_challengers", ["serving_mode"])
        op.create_index("ix_prompt_challengers_genre_mode", "prompt_challengers", ["genre", "serving_mode"])

    if not inspector.has_table("prompt_experiments"):
        op.create_table(
            "prompt_experiments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("experiment_id", sa.String(length=80), nullable=False),
            sa.Column("request_id", sa.String(length=80), nullable=False),
            sa.Column("challenger_id", sa.String(length=120), nullable=False),
            sa.Column("genre", sa.String(length=50), nullable=False),
            # 任务字段（§5.2）
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payload_ref", sa.String(length=80), nullable=True),
            sa.Column("payload_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_code", sa.String(length=80), nullable=True),
            # 冻结实验契约（§4）
            sa.Column("champion_id", sa.String(length=120), nullable=False),
            sa.Column("assignment_bucket", sa.Integer(), nullable=False),
            sa.Column("serving_mode", sa.String(length=20), nullable=False),
            sa.Column("resolved_model_id", sa.String(length=120), nullable=False),
            sa.Column("model_selection_source", sa.String(length=40), nullable=False),
            sa.Column("model_config_version", sa.String(length=80), nullable=True),
            sa.Column("prompt_version_id", sa.String(length=80), nullable=False),
            sa.Column("provider_parameters_hash", sa.String(length=40), nullable=False),
            # 版本字段（§7.2）
            sa.Column("light_judge_version", sa.String(length=40), nullable=False),
            sa.Column("evaluation_policy_version", sa.String(length=60), nullable=False),
            sa.Column("async_review_prompt_version", sa.String(length=40), nullable=True),
            sa.Column("async_review_model_id", sa.String(length=120), nullable=True),
            sa.Column("detector_provider", sa.String(length=60), nullable=True),
            sa.Column("detector_version", sa.String(length=60), nullable=True),
            sa.Column("champion_prompt_hash", sa.String(length=80), nullable=False),
            sa.Column("challenger_prompt_hash", sa.String(length=80), nullable=False),
            sa.Column("model_catalog_version", sa.String(length=80), nullable=True),
            # 结果字段（§7.1）
            sa.Column("light_judge_result", sa.JSON(), nullable=False),
            sa.Column("returned_variant", sa.String(length=20), nullable=True),
            sa.Column("async_review_result", sa.JSON(), nullable=False),
            sa.Column("outcome", sa.String(length=30), nullable=True),
            sa.Column("latency_ms", sa.JSON(), nullable=False),
            sa.Column("cost", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("experiment_id", name="uq_prompt_experiments_experiment_id"),
            sa.UniqueConstraint(
                "request_id",
                "challenger_id",
                "evaluation_policy_version",
                name="uq_prompt_experiments_settlement",
            ),
        )
        op.create_index("ix_prompt_experiments_request_id", "prompt_experiments", ["request_id"])
        op.create_index("ix_prompt_experiments_challenger_id", "prompt_experiments", ["challenger_id"])
        op.create_index("ix_prompt_experiments_genre", "prompt_experiments", ["genre"])
        op.create_index("ix_prompt_experiments_status", "prompt_experiments", ["status"])
        op.create_index("ix_prompt_experiments_claim", "prompt_experiments", ["status", "lease_until"])
        op.create_index("ix_prompt_experiments_stats", "prompt_experiments", ["challenger_id", "outcome"])

    if not inspector.has_table("prompt_experiment_budgets"):
        op.create_table(
            "prompt_experiment_budgets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("budget_date", sa.String(length=10), nullable=False),
            sa.Column("scope", sa.String(length=20), nullable=False),
            sa.Column("scope_key", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("calls_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_used", sa.Float(), nullable=False, server_default="0"),
            sa.Column("reserved_cost", sa.Float(), nullable=False, server_default="0"),
            sa.Column("calls_limit", sa.Integer(), nullable=True),
            sa.Column("cost_limit", sa.Float(), nullable=True),
            sa.Column("circuit_open", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("budget_date", "scope", "scope_key", name="uq_prompt_experiment_budgets_scope"),
        )
        op.create_index("ix_prompt_experiment_budgets_budget_date", "prompt_experiment_budgets", ["budget_date"])

    if not inspector.has_table("prompt_champion_assignments"):
        op.create_table(
            "prompt_champion_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("genre", sa.String(length=50), nullable=False),
            sa.Column("prompt_version_id", sa.String(length=80), nullable=False),
            sa.Column("prompt_hash", sa.String(length=80), nullable=False),
            sa.Column("previous_version_id", sa.String(length=80), nullable=True),
            sa.Column("operator", sa.String(length=80), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("gate_overridden", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("override_reason", sa.Text(), nullable=True),
            sa.Column("effective_from", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_prompt_champion_assignments_genre", "prompt_champion_assignments", ["genre"])
        op.create_index(
            "ix_prompt_champion_assignments_current",
            "prompt_champion_assignments",
            ["genre", "effective_until"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name in (
        "prompt_champion_assignments",
        "prompt_experiment_budgets",
        "prompt_experiments",
        "prompt_challengers",
    ):
        if inspector.has_table(table_name):
            op.drop_table(table_name)
