"""add genre planning fields to projects

Revision ID: add_genre_planning_to_projects
Revises: add_snapshots_confidence_to_setting_items
Create Date: 2025-12-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_genre_planning_to_projects"
down_revision = "add_snapshots_confidence_to_setting_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """添加题材与篇幅规划字段到 projects 表"""
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("sub_genre", sa.String(length=100), nullable=True, comment="子流派")
        )
        batch_op.add_column(
            sa.Column("planned_length_type", sa.String(length=20), nullable=True, comment="篇幅类型: short/mid/long/epic")
        )
        batch_op.add_column(
            sa.Column("planned_chapters_min", sa.Integer(), nullable=True, comment="预期最少章节数")
        )
        batch_op.add_column(
            sa.Column("planned_chapters_max", sa.Integer(), nullable=True, comment="预期最多章节数")
        )
        batch_op.add_column(
            sa.Column("user_outline_plan", sa.Text(), nullable=True, comment="用户自定义大纲规划原文")
        )


def downgrade() -> None:
    """移除题材与篇幅规划字段"""
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_column("user_outline_plan")
        batch_op.drop_column("planned_chapters_max")
        batch_op.drop_column("planned_chapters_min")
        batch_op.drop_column("planned_length_type")
        batch_op.drop_column("sub_genre")
