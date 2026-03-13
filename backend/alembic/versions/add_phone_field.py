"""add phone field to users

Revision ID: add_phone_field
Revises: previous_revision
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_phone_field'
down_revision = None  # 需要设置为最新的 migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 phone 字段到 users 表
    op.add_column('users', sa.Column('phone', sa.String(20), nullable=True))
    
    # 创建索引
    op.create_index(op.f('ix_users_phone'), 'users', ['phone'], unique=True)


def downgrade() -> None:
    # 删除索引
    op.drop_index(op.f('ix_users_phone'), table_name='users')
    
    # 删除 phone 字段
    op.drop_column('users', 'phone')
