"""seed default roles and permissions

P1-3.9：预置 super_admin / admin / user 三个系统角色与权限集。
幂等：按唯一 code 检查，缺失才插入；重复执行安全。
不自动创建超管账号（见 docs：首个注册用户不得自动超管，初始管理员由脚本创建）。

Revision ID: seed_default_roles_permissions
Revises: add_user_token_version
Create Date: 2026-08-28

"""
from alembic import op
import sqlalchemy as sa

revision = "seed_default_roles_permissions"
down_revision = "add_user_token_version"
branch_labels = None
depends_on = None

PERMISSIONS = [
    # 用户管理
    {"code": "user:read", "name": "查看用户", "resource": "user", "action": "read"},
    {"code": "user:write", "name": "编辑用户", "resource": "user", "action": "write"},
    {"code": "user:delete", "name": "删除用户", "resource": "user", "action": "delete"},
    # 角色管理
    {"code": "role:read", "name": "查看角色", "resource": "role", "action": "read"},
    {"code": "role:write", "name": "编辑角色", "resource": "role", "action": "write"},
    {"code": "role:delete", "name": "删除角色", "resource": "role", "action": "delete"},
    # 日志管理
    {"code": "log:read", "name": "查看日志", "resource": "log", "action": "read"},
    {"code": "log:export", "name": "导出日志", "resource": "log", "action": "export"},
    # 统计数据
    {"code": "stats:read", "name": "查看统计", "resource": "stats", "action": "read"},
    # 系统配置
    {"code": "system:read", "name": "查看配置", "resource": "system", "action": "read"},
    {"code": "system:write", "name": "修改配置", "resource": "system", "action": "write"},
]

# super_admin 权限语义为 "*"，由 get_user_permissions 直接短路返回，不落关联表
ROLES = [
    {
        "code": "super_admin",
        "name": "超级管理员",
        "description": "拥有所有权限",
        "is_active": True,
        "is_system": True,
    },
    {
        "code": "admin",
        "name": "管理员",
        "description": "用户管理、日志查看、统计",
        "is_active": True,
        "is_system": True,
    },
    {
        "code": "user",
        "name": "普通用户",
        "description": "基础用户角色",
        "is_active": True,
        "is_system": True,
    },
]

# admin 角色关联的权限 code（与 init_admin_data.py 一致）
ADMIN_PERMISSION_CODES = [
    "user:read", "user:write",
    "role:read",
    "log:read", "log:export",
    "stats:read",
    "system:read",
]


def _seed_rows(table_name: str, rows: list[dict]) -> None:
    """幂等插入：按唯一 code 检查，缺失才插入。"""
    connection = op.get_bind()
    table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
    for row in rows:
        existing = connection.execute(
            sa.select(table.c.code).where(table.c.code == row["code"])
        ).first()
        if existing is None:
            connection.execute(table.insert().values(row))


def upgrade() -> None:
    _seed_rows("permissions", PERMISSIONS)
    _seed_rows("roles", ROLES)

    # admin 角色关联权限（幂等）
    connection = op.get_bind()
    metadata = sa.MetaData()
    permissions = sa.Table("permissions", metadata, autoload_with=connection)
    roles = sa.Table("roles", metadata, autoload_with=connection)
    role_permissions = sa.Table("role_permissions", metadata, autoload_with=connection)

    admin_role = connection.execute(
        sa.select(roles.c.id).where(roles.c.code == "admin")
    ).first()
    if admin_role is None:
        return
    admin_role_id = admin_role[0]

    perm_ids = [
        row[0]
        for row in connection.execute(
            sa.select(permissions.c.id).where(
                permissions.c.code.in_(ADMIN_PERMISSION_CODES)
            )
        ).all()
    ]
    for permission_id in perm_ids:
        exists = connection.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == admin_role_id,
                role_permissions.c.permission_id == permission_id,
            )
        ).first()
        if exists is None:
            connection.execute(
                role_permissions.insert().values(
                    role_id=admin_role_id, permission_id=permission_id
                )
            )


def downgrade() -> None:
    # 系统角色/权限为应用运行基础，降级不删除数据（仅回滚表结构时由 add_admin_rbac 处理）
    pass
