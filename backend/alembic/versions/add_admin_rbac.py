"""add admin rbac models

Revision ID: add_admin_rbac
Revises: add_chapter_summary_fields
Create Date: 2026-03-13

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_admin_rbac'
down_revision = 'add_chapter_summary_fields_to_existing_table'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False, comment='角色名称'),
        sa.Column('code', sa.String(length=50), nullable=False, comment='角色代码'),
        sa.Column('description', sa.Text(), nullable=True, comment='角色描述'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1', comment='是否启用'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='0', comment='是否系统角色'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('code')
    )
    op.create_index('ix_roles_name', 'roles', ['name'])
    op.create_index('ix_roles_code', 'roles', ['code'])

    op.create_table(
        'permissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False, comment='权限名称'),
        sa.Column('code', sa.String(length=100), nullable=False, comment='权限代码'),
        sa.Column('resource', sa.String(length=50), nullable=False, comment='资源类型'),
        sa.Column('action', sa.String(length=50), nullable=False, comment='操作类型'),
        sa.Column('description', sa.Text(), nullable=True, comment='权限描述'),
        sa.Column('parent_id', sa.Integer(), nullable=True, comment='父权限ID'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['parent_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('code')
    )
    op.create_index('ix_permissions_name', 'permissions', ['name'])
    op.create_index('ix_permissions_code', 'permissions', ['code'])
    op.create_index('ix_permissions_resource', 'permissions', ['resource'])

    op.create_table(
        'user_roles',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'role_id')
    )

    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_id')
    )

    op.create_table(
        'admin_operation_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='操作用户ID'),
        sa.Column('username', sa.String(length=255), nullable=False, comment='操作用户名'),
        sa.Column('operation_type', sa.String(length=50), nullable=False, comment='操作类型'),
        sa.Column('resource_type', sa.String(length=50), nullable=False, comment='资源类型'),
        sa.Column('resource_id', sa.Integer(), nullable=True, comment='资源ID'),
        sa.Column('operation_desc', sa.Text(), nullable=False, comment='操作描述'),
        sa.Column('request_method', sa.String(length=10), nullable=False, comment='请求方法'),
        sa.Column('request_path', sa.String(length=500), nullable=False, comment='请求路径'),
        sa.Column('request_params', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='请求参数'),
        sa.Column('response_status', sa.Integer(), nullable=False, comment='响应状态码'),
        sa.Column('ip_address', sa.String(length=50), nullable=False, comment='IP地址'),
        sa.Column('user_agent', sa.String(length=500), nullable=True, comment='用户代理'),
        sa.Column('duration_ms', sa.Integer(), nullable=True, comment='执行时长(毫秒)'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_admin_operation_logs_user_id', 'admin_operation_logs', ['user_id'])
    op.create_index('ix_admin_operation_logs_operation_type', 'admin_operation_logs', ['operation_type'])
    op.create_index('ix_admin_operation_logs_resource_type', 'admin_operation_logs', ['resource_type'])
    op.create_index('ix_admin_operation_logs_created_at', 'admin_operation_logs', ['created_at'])

    op.create_table(
        'admin_login_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户ID'),
        sa.Column('username', sa.String(length=255), nullable=False, comment='用户名'),
        sa.Column('login_type', sa.String(length=20), nullable=False, comment='登录类型'),
        sa.Column('login_status', sa.String(length=20), nullable=False, comment='登录状态'),
        sa.Column('ip_address', sa.String(length=50), nullable=False, comment='IP地址'),
        sa.Column('user_agent', sa.String(length=500), nullable=True, comment='用户代理'),
        sa.Column('failure_reason', sa.Text(), nullable=True, comment='失败原因'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_admin_login_logs_user_id', 'admin_login_logs', ['user_id'])
    op.create_index('ix_admin_login_logs_created_at', 'admin_login_logs', ['created_at'])


def downgrade():
    op.drop_table('admin_login_logs')
    op.drop_table('admin_operation_logs')
    op.drop_table('role_permissions')
    op.drop_table('user_roles')
    op.drop_table('permissions')
    op.drop_table('roles')
