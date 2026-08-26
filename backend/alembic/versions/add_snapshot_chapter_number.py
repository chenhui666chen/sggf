"""add chapter_number to character_state_snapshots

Revision ID: add_snapshot_chapter_number
Revises: add_char_speech_style
Create Date: 2026-08-20

背景：人物状态快照闭环收尾。快照表原仅有 chapter_id（chapters.id 外键），
无法按章节号排序或做"恢复第 N 章前状态"查询。
新增 chapter_number 冗余列（Integer 可空，带索引）：
- 提取落库时由章节后处理写入；
- 生成第 N 章时按 chapter_number < N 取每个角色最新快照注入上下文。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_snapshot_chapter_number"
down_revision = "add_char_speech_style"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("character_state_snapshots"):
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("character_state_snapshots")
    }
    if "chapter_number" not in existing_columns:
        op.add_column(
            "character_state_snapshots",
            sa.Column(
                "chapter_number",
                sa.Integer(),
                nullable=True,
                comment="章节号（用于按章节排序/恢复）",
            ),
        )

    existing_indexes = {
        index["name"] for index in inspector.get_indexes("character_state_snapshots")
    }
    if "ix_character_state_snapshots_chapter_number" not in existing_indexes:
        op.create_index(
            "ix_character_state_snapshots_chapter_number",
            "character_state_snapshots",
            ["chapter_number"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("character_state_snapshots"):
        return

    existing_indexes = {
        index["name"] for index in inspector.get_indexes("character_state_snapshots")
    }
    if "ix_character_state_snapshots_chapter_number" in existing_indexes:
        op.drop_index(
            "ix_character_state_snapshots_chapter_number",
            table_name="character_state_snapshots",
        )

    existing_columns = {
        column["name"] for column in inspector.get_columns("character_state_snapshots")
    }
    if "chapter_number" in existing_columns:
        op.drop_column("character_state_snapshots", "chapter_number")
