"""add prompt_challenger_state_transitions audit table (五轮评审修复①)

Revision ID: add_prompt_challenger_state_transitions
Revises: add_champion_ai_score_to_experiments
Create Date: 2026-07-25

设计文档：docs/ONLINE_PROMPT_EVOLUTION_DESIGN_20260730.md §13 #12
人工开闸（eligible → returnable）等挑战者状态变更管理动作的持久化审计：
operator + reason 与状态变更同事务落库，普通应用日志不构成审计记录。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_prompt_challenger_state_transitions"
down_revision = "add_champion_ai_score_to_experiments"
branch_labels = None
depends_on = None

TABLE = "prompt_challenger_state_transitions"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("challenger_id", sa.String(120), nullable=False, index=True),
        sa.Column("genre", sa.String(50), nullable=False, index=True),
        sa.Column("from_mode", sa.String(20), nullable=False),
        sa.Column("to_mode", sa.String(20), nullable=False),
        sa.Column("operator", sa.String(80), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_prompt_challenger_transitions_lookup",
        TABLE,
        ["challenger_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(TABLE):
        op.drop_table(TABLE)
