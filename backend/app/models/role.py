"""
角色模型
"""
from datetime import datetime
from typing import List
from sqlalchemy import String, DateTime, Boolean, Text, Table, Column, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.db.base import Base


class Role(Base):
    """角色表"""
    __tablename__ = "roles"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True, comment="角色名称")
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, comment="角色代码")
    description: Mapped[str] = mapped_column(Text, nullable=True, comment="角色描述")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否系统角色")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    users: Mapped[List["User"]] = relationship("User", secondary="user_roles", back_populates="roles")
    permissions: Mapped[List["Permission"]] = relationship("Permission", secondary="role_permissions", back_populates="roles")
    
    def __repr__(self):
        return f"<Role {self.name}>"


class Permission(Base):
    """权限表"""
    __tablename__ = "permissions"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, comment="权限名称")
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, comment="权限代码")
    resource: Mapped[str] = mapped_column(String(50), index=True, comment="资源类型")
    action: Mapped[str] = mapped_column(String(50), comment="操作类型")
    description: Mapped[str] = mapped_column(Text, nullable=True, comment="权限描述")
    parent_id: Mapped[int] = mapped_column(Integer, ForeignKey("permissions.id"), nullable=True, comment="父权限ID")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    roles: Mapped[List["Role"]] = relationship("Role", secondary="role_permissions", back_populates="permissions")
    children: Mapped[List["Permission"]] = relationship("Permission", backref="parent", remote_side=[id])
    
    def __repr__(self):
        return f"<Permission {self.code}>"


user_roles = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime(timezone=True), server_default=func.now())
)

role_permissions = Table(
    'role_permissions',
    Base.metadata,
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime(timezone=True), server_default=func.now())
)
