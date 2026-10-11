"""users 邮箱验证字段 + email 放开非空（P1 批次 3：3.2/3.8）

- 新增 email_verified / email_verified_at：注册两步流程建号即已验证，
  存量默认未验证（登录提示验证），重置密码成功即置已验证。
- email 放开非空：OAuth 用户不再分配假邮箱（email=NULL）。
- 数据清洗：历史 OAuth 假邮箱（*.temp）置空（无存量真实用户，测试数据直接清理）。

Revision ID: add_email_verification_nullable_email
Revises: seed_default_roles_permissions
Create Date: 2026-08-28
"""
from alembic import op
import sqlalchemy as sa


revision = "add_email_verification_nullable_email"
down_revision = "seed_default_roles_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 先加列（带 server_default，不重写表）
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. 清理历史 OAuth 假邮箱（占位域名，见 OAuthService 旧实现），
    #    必须在 email 放开非空前后的任何时点执行均可，此处先行清理
    op.execute(
        "UPDATE users SET email = NULL "
        "WHERE email LIKE '%@alipay.temp' OR email LIKE '%@wechat.temp'"
    )

    # 3. email 放开非空：OAuth 用户允许 email=NULL（PG 唯一索引允许多 NULL）
    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    # NULL 邮箱回填占位值后恢复非空（与旧假邮箱口径一致，仅保可逆性）
    op.execute(
        "UPDATE users SET email = username || '@local.invalid' WHERE email IS NULL"
    )
    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
