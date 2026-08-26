"""add character speech_style column

Revision ID: add_char_speech_style
Revises: add_char_baseline_snapshots
Create Date: 2026-08-20

背景：人物防扁平化改造 P3——说话风格持久化。
characters 表新增 speech_style（Text 可空）稳定基线列，
由 sync_parsed_characters_to_db 非空优先同步；
章节保存后的人物行为一致性检查（回避表达/对白同质化）从该列读取基线。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_char_speech_style"
down_revision = "add_char_baseline_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("characters"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("characters")}
    if "speech_style" not in existing_columns:
        op.add_column(
            "characters",
            sa.Column(
                "speech_style",
                sa.Text(),
                nullable=True,
                comment="稳定基线：说话风格（语气/称谓/回避表达等短摘要）",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("characters"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("characters")}
    if "speech_style" in existing_columns:
        op.drop_column("characters", "speech_style")
