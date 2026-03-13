"""
权限控制依赖注入
"""
from typing import Set
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User


def get_user_permissions(user: User, db: Session) -> Set[str]:
    """获取用户所有权限代码"""
    permissions = set()
    for role in user.roles:
        if role.code == "super_admin":
            return {"*"}
        for permission in role.permissions:
            permissions.add(permission.code)
            permissions.add(f"{permission.resource}:*")
    return permissions


def has_permission(user: User, permission_code: str, db: Session) -> bool:
    """检查用户是否有特定权限"""
    user_permissions = get_user_permissions(user, db)
    return "*" in user_permissions or permission_code in user_permissions


def is_admin(user: User) -> bool:
    """检查用户是否为管理员"""
    user_role_codes = {role.code for role in user.roles}
    return "admin" in user_role_codes or "super_admin" in user_role_codes


def is_super_admin(user: User) -> bool:
    """检查用户是否为超级管理员"""
    user_role_codes = {role.code for role in user.roles}
    return "super_admin" in user_role_codes


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """要求管理员权限"""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限"
        )
    return current_user


async def require_super_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """要求超级管理员权限"""
    if not is_super_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要超级管理员权限"
        )
    return current_user


def require_permission(permission_code: str):
    """权限检查装饰器"""
    async def permission_checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ) -> User:
        if not has_permission(current_user, permission_code, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要权限: {permission_code}"
            )
        return current_user
    return Depends(permission_checker)
