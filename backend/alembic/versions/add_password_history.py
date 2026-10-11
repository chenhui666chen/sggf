"""password_history 密码历史表（P2 批次 B：4.6）

- 新表：user_id + password_pepper_hash（HMAC-SHA256 十六进制，独立 pepper）+ created_at；
- 只存摘要，绝不存 bcrypt/明文；per 用户保留最近 3 条，由服务层在写入时清理；
- 用于"新密码不与最近 3 次重复"检查，与登录 password_hash 完全分离。

Revision ID: add_password_history
Revises: add_openid_encrypted_storage
Create Date: 2026-08-31
"""
import sqlalchemy as sa
from alembic import op


revision = "add_password_history"
down_revision = "add_openid_encrypted_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_history",
        sa.Column("id", sa.Integer(), nullable=False),
        # 评审 #8：加外键级联，用户删除（4.3 注销落地后）不残留孤儿行
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("password_pepper_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_password_history_id"), "password_history", ["id"], unique=False)
    op.create_index(
        op.f("ix_password_history_user_id"), "password_history", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_password_history_user_id"), table_name="password_history")
    op.drop_index(op.f("ix_password_history_id"), table_name="password_history")
    op.drop_table("password_history")
