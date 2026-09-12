"""add token_version to users

Revision ID: add_user_token_version
Revises: add_snapshot_chapter_number
Create Date: 2026-08-25

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_user_token_version"
down_revision = "add_snapshot_chapter_number"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """添加 token_version 字段到 users 表。

    会话版本号：改密/重置/禁用时递增，用于使所有历史 JWT 立即失效。
    存量用户默认 1（与无 tv 的旧 token 兼容，避免上线瞬间集体掉线）。
    """
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "token_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
                comment="会话版本号：改密/重置/禁用时递增，使旧 JWT 立即失效",
            )
        )


def downgrade() -> None:
    """移除 token_version 字段"""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("token_version")
