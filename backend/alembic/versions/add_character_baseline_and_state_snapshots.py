"""add character baseline fields and chapter state snapshots

Revision ID: add_char_baseline_snapshots
Revises: add_character_source_archived
Create Date: 2026-08-20

背景：人物防扁平化改造 P2（基线与动态状态分离）。
- characters 表新增 5 个稳定基线列（personality/worldview/motivation/limitation/
  growth_direction，Text 可空），由 sync_parsed_characters_to_db 非空优先同步；
- 新建 character_state_snapshots 章节级动态状态快照表，
  同角色同章节唯一约束，动态状态不写回基线列。
迁移不删除、不重写既有 profile 数据。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_char_baseline_snapshots"
down_revision = "add_character_source_archived"
branch_labels = None
depends_on = None


BASELINE_COLUMNS = (
    ("personality", "稳定基线：性格锚点"),
    ("worldview", "稳定基线：世界观/价值倾向"),
    ("motivation", "稳定基线：原始核心动机"),
    ("limitation", "稳定基线：能力/弱点限制"),
    ("growth_direction", "稳定基线：成长方向"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. characters 基线列（幂等：已存在则跳过）
    if inspector.has_table("characters"):
        existing_columns = {column["name"] for column in inspector.get_columns("characters")}
        for column_name, comment in BASELINE_COLUMNS:
            if column_name not in existing_columns:
                op.add_column(
                    "characters",
                    sa.Column(column_name, sa.Text(), nullable=True, comment=comment),
                )

    # 2. character_state_snapshots 快照表
    if not inspector.has_table("character_state_snapshots"):
        op.create_table(
            "character_state_snapshots",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "character_id",
                sa.Integer(),
                sa.ForeignKey("characters.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "chapter_id",
                sa.Integer(),
                sa.ForeignKey("chapters.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("current_motivation", sa.Text(), nullable=True, comment="当前目标/动机"),
            sa.Column("current_belief", sa.Text(), nullable=True, comment="当前信念"),
            sa.Column("emotional_state", sa.Text(), nullable=True, comment="情绪状态"),
            sa.Column("relationship_state_json", sa.Text(), nullable=True, comment="关系状态(JSON)"),
            sa.Column("known_information", sa.Text(), nullable=True, comment="已知信息"),
            sa.Column("state_changes_json", sa.Text(), nullable=True, comment="状态变更记录(JSON)"),
            sa.Column("evidence_text", sa.Text(), nullable=True, comment="状态证据文本片段"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id",
                "character_id",
                "chapter_id",
                name="uq_character_state_snapshot_project_character_chapter",
            ),
        )
        op.create_index(
            op.f("ix_character_state_snapshots_id"),
            "character_state_snapshots",
            ["id"],
        )
        op.create_index(
            op.f("ix_character_state_snapshots_project_id"),
            "character_state_snapshots",
            ["project_id"],
        )
        op.create_index(
            op.f("ix_character_state_snapshots_character_id"),
            "character_state_snapshots",
            ["character_id"],
        )
        op.create_index(
            op.f("ix_character_state_snapshots_chapter_id"),
            "character_state_snapshots",
            ["chapter_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("character_state_snapshots"):
        op.drop_table("character_state_snapshots")

    if inspector.has_table("characters"):
        existing_columns = {column["name"] for column in inspector.get_columns("characters")}
        for column_name, _comment in reversed(BASELINE_COLUMNS):
            if column_name in existing_columns:
                op.drop_column("characters", column_name)
