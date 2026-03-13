"""
用户管理 API
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.core.permissions import require_admin, require_permission
from app.core.security import hash_password
from app.db.base import get_db
from app.models.user import User
from app.models.role import Role
from app.schemas.admin import (
    UserAdminResponse,
    UserListResponse,
    UserCreateByAdmin,
    UserUpdateByAdmin,
    UserStatusUpdate,
    UserRoleUpdate,
)

router = APIRouter()


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    role_code: Optional[str] = None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户列表（分页/搜索/过滤）"""
    query = db.query(User)
    
    if search:
        query = query.filter(
            or_(
                User.username.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                User.phone.ilike(f"%{search}%"),
            )
        )
    
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    
    if role_code:
        query = query.join(User.roles).filter(Role.code == role_code)
    
    if created_after:
        query = query.filter(User.created_at >= created_after)
    
    if created_before:
        query = query.filter(User.created_at <= created_before)
    
    total = query.count()
    total_pages = (total + page_size - 1) // page_size
    
    users = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return UserListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=[UserAdminResponse.model_validate(user) for user in users],
    )


@router.get("/{user_id}", response_model=UserAdminResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户详情"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    return UserAdminResponse.model_validate(user)


@router.post("", response_model=UserAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreateByAdmin,
    current_user: User = Depends(require_permission("user:write")),
    db: Session = Depends(get_db),
):
    """新建用户"""
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册"
        )
    
    if user_data.phone and db.query(User).filter(User.phone == user_data.phone).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="手机号已被注册"
        )
    
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已被使用"
        )
    
    user = User(
        username=user_data.username,
        email=user_data.email,
        phone=user_data.phone,
        password_hash=hash_password(user_data.password),
        full_name=user_data.full_name or user_data.username,
    )
    
    if user_data.role_ids:
        roles = db.query(Role).filter(Role.id.in_(user_data.role_ids)).all()
        user.roles = roles
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return UserAdminResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserAdminResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdateByAdmin,
    current_user: User = Depends(require_permission("user:write")),
    db: Session = Depends(get_db),
):
    """编辑用户信息"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    update_data = user_data.model_dump(exclude_unset=True, exclude={"role_ids"})
    
    for field, value in update_data.items():
        setattr(user, field, value)
    
    if user_data.role_ids is not None:
        roles = db.query(Role).filter(Role.id.in_(user_data.role_ids)).all()
        user.roles = roles
    
    db.commit()
    db.refresh(user)
    
    return UserAdminResponse.model_validate(user)


@router.patch("/{user_id}/status", response_model=UserAdminResponse)
async def update_user_status(
    user_id: int,
    status_data: UserStatusUpdate,
    current_user: User = Depends(require_permission("user:write")),
    db: Session = Depends(get_db),
):
    """启用/禁用账号"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能禁用自己的账号"
        )
    
    user.is_active = status_data.is_active
    db.commit()
    db.refresh(user)
    
    return UserAdminResponse.model_validate(user)


@router.post("/{user_id}/roles", response_model=UserAdminResponse)
async def assign_user_roles(
    user_id: int,
    role_data: UserRoleUpdate,
    current_user: User = Depends(require_permission("user:write")),
    db: Session = Depends(get_db),
):
    """分配角色"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    roles = db.query(Role).filter(Role.id.in_(role_data.role_ids)).all()
    user.roles = roles
    
    db.commit()
    db.refresh(user)
    
    return UserAdminResponse.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_permission("user:delete")),
    db: Session = Depends(get_db),
):
    """删除用户"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除自己的账号"
        )
    
    db.delete(user)
    db.commit()
    
    return None
