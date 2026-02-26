"""add third party login fields to users

Revision ID: add_third_party_login_fields
Revises: add_audio_config_to_projects
Create Date: 2026-02-07

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_third_party_login_fields"
down_revision = "add_audio_config_to_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """添加第三方登录字段到 users 表"""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "alipay_openid",
                sa.String(255),
                nullable=True,
                comment="支付宝OpenID"
            )
        )
        batch_op.add_column(
            sa.Column(
                "wechat_openid",
                sa.String(255),
                nullable=True,
                comment="微信OpenID"
            )
        )
        batch_op.add_column(
            sa.Column(
                "wechat_unionid",
                sa.String(255),
                nullable=True,
                comment="微信UnionID"
            )
        )
    
    op.create_index(op.f("ix_users_alipay_openid"), "users", ["alipay_openid"], unique=False)
    op.create_index(op.f("ix_users_wechat_openid"), "users", ["wechat_openid"], unique=False)
    op.create_index(op.f("ix_users_wechat_unionid"), "users", ["wechat_unionid"], unique=False)


def downgrade() -> None:
    """移除第三方登录字段"""
    op.drop_index(op.f("ix_users_wechat_unionid"), table_name="users")
    op.drop_index(op.f("ix_users_wechat_openid"), table_name="users")
    op.drop_index(op.f("ix_users_alipay_openid"), table_name="users")
    
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("wechat_unionid")
        batch_op.drop_column("wechat_openid")
        batch_op.drop_column("alipay_openid")