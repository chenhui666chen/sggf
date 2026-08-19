"""add character source and archived_at for epic rebuild orphan archive

Revision ID: add_character_source_archived
Revises: contract_audiobook_isolation_finalize, add_prompt_challenger_state_transitions
Create Date: 2026-08-18

背景：epic 框架重建时旧框架的人物卡（新框架不再引用）永久残留累积。
新增 source（卡片来源标记）与 archived_at（软归档时间）两列，
重建后由扩展管线将 source='expansion' 且不再被引用的卡片归档。
本迁移同时收敛既有的双 head 分叉。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_character_source_archived"
down_revision = (
    "contract_audiobook_isolation_finalize",
    "add_prompt_challenger_state_transitions",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("characters"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("characters")}
    if "source" not in existing_columns:
        op.add_column(
            "characters",
            sa.Column(
                "source",
                sa.String(length=30),
                nullable=True,
                comment="卡片来源：expansion=协同扩展管线",
            ),
        )
    if "archived_at" not in existing_columns:
        op.add_column(
            "characters",
            sa.Column(
                "archived_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="归档时间；非空=已随框架重建归档",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("characters"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("characters")}
    if "archived_at" in existing_columns:
        op.drop_column("characters", "archived_at")
    if "source" in existing_columns:
        op.drop_column("characters", "source")
