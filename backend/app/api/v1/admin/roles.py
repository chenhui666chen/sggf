"""
角色权限管理 API
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import require_admin, require_super_admin, require_permission
from app.db.base import get_db
from app.models.user import User
from app.models.role import Role, Permission
from app.schemas.admin import (
    RoleResponse,
    RoleListResponse,
    RoleCreate,
    RoleUpdate,
    PermissionResponse,
)

router = APIRouter()


@router.get("", response_model=RoleListResponse)
async def list_roles(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """角色列表"""
    roles = db.query(Role).order_by(Role.created_at.desc()).all()
    
    return RoleListResponse(
        total=len(roles),
        page=1,
        page_size=len(roles),
        total_pages=1,
        items=[RoleResponse.model_validate(role) for role in roles],
    )


@router.post("", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    role_data: RoleCreate,
    current_user: User = Depends(require_permission("role:write")),
    db: Session = Depends(get_db),
):
    """创建角色"""
    if db.query(Role).filter(Role.name == role_data.name).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="角色名称已存在"
        )
    
    if db.query(Role).filter(Role.code == role_data.code).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="角色代码已存在"
        )
    
    role = Role(
        name=role_data.name,
        code=role_data.code,
        description=role_data.description,
    )
    
    if role_data.permission_ids:
        permissions = db.query(Permission).filter(Permission.id.in_(role_data.permission_ids)).all()
        role.permissions = permissions
    
    db.add(role)
    db.commit()
    db.refresh(role)
    
    return RoleResponse.model_validate(role)


@router.get("/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """角色详情"""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在"
        )
    return RoleResponse.model_validate(role)


@router.patch("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: int,
    role_data: RoleUpdate,
    current_user: User = Depends(require_permission("role:write")),
    db: Session = Depends(get_db),
):
    """编辑角色"""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在"
        )
    
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="系统角色不能修改"
        )
    
    update_data = role_data.model_dump(exclude_unset=True, exclude={"permission_ids"})
    
    for field, value in update_data.items():
        setattr(role, field, value)
    
    if role_data.permission_ids is not None:
        permissions = db.query(Permission).filter(Permission.id.in_(role_data.permission_ids)).all()
        role.permissions = permissions
    
    db.commit()
    db.refresh(role)
    
    return RoleResponse.model_validate(role)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int,
    current_user: User = Depends(require_permission("role:delete")),
    db: Session = Depends(get_db),
):
    """删除角色"""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在"
        )
    
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="系统角色不能删除"
        )
    
    if role.users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="角色下还有用户，不能删除"
        )
    
    db.delete(role)
    db.commit()
    
    return None


@router.get("/permissions/all", response_model=List[PermissionResponse])
async def list_permissions(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """权限树（树形结构）"""
    permissions = db.query(Permission).filter(Permission.parent_id == None).all()
    return [PermissionResponse.model_validate(p) for p in permissions]


@router.post("/{role_id}/permissions", response_model=RoleResponse)
async def assign_role_permissions(
    role_id: int,
    permission_ids: List[int],
    current_user: User = Depends(require_permission("role:write")),
    db: Session = Depends(get_db),
):
    """批量分配权限"""
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="角色不存在"
        )
    
    permissions = db.query(Permission).filter(Permission.id.in_(permission_ids)).all()
    role.permissions = permissions
    
    db.commit()
    db.refresh(role)
    
    return RoleResponse.model_validate(role)
