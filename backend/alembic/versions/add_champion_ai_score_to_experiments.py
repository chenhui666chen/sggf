"""add champion_ai_score to prompt_experiments (online prompt evolution 信号 3a)

Revision ID: add_champion_ai_score_to_experiments
Revises: add_prompt_experiment_tables
Create Date: 2026-07-25

设计文档：docs/ONLINE_PROMPT_EVOLUTION_DESIGN_20260730.md §11.2 champion_ai_score_rise
向 prompt_experiments 新增只写列 champion_ai_score（冠军原始 AI 检测分），
结算落库供休眠期在线退化唤醒判定。仅新增可空列，不改既有语义，向后兼容。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_champion_ai_score_to_experiments"
down_revision = "add_prompt_experiment_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("prompt_experiments"):
        return
    columns = {c["name"] for c in inspector.get_columns("prompt_experiments")}
    if "champion_ai_score" not in columns:
        op.add_column(
            "prompt_experiments",
            sa.Column("champion_ai_score", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("prompt_experiments"):
        return
    columns = {c["name"] for c in inspector.get_columns("prompt_experiments")}
    if "champion_ai_score" in columns:
        op.drop_column("prompt_experiments", "champion_ai_score")
