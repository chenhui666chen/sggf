"""add snapshots and confidence to setting items

Revision ID: add_snapshots_confidence_to_setting_items
Revises: add_setting_models
Create Date: 2025-12-01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_snapshots_confidence_to_setting_items"
down_revision = "add_setting_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """添加快照与置信度字段到 setting_items 表"""
    with op.batch_alter_table("setting_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("snapshots", sa.Text(), nullable=True, comment="版本快照JSON数组")
        )
        batch_op.add_column(
            sa.Column("confidence_score", sa.Float(), nullable=True, comment="置信度分数0-1")
        )


def downgrade() -> None:
    """移除快照与置信度字段"""
    with op.batch_alter_table("setting_items", schema=None) as batch_op:
        batch_op.drop_column("confidence_score")
        batch_op.drop_column("snapshots")
