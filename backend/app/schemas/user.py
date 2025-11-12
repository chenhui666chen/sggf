"""
用户Schema
"""
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


class UserBase(BaseModel):
    """用户基础Schema"""
    username: str
    email: EmailStr
    full_name: Optional[str] = None


class UserCreate(UserBase):
    """用户创建Schema"""
    password: str


class UserUpdate(BaseModel):
    """用户更新Schema"""
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserResponse(UserBase):
    """用户响应Schema"""
    id: int
    avatar_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    """用户登录Schema"""
    username: str
    password: str


class TokenResponse(BaseModel):
    """Token响应Schema"""
    access_token: str
    token_type: str
    user: UserResponse


class PasswordChange(BaseModel):
    """密码修改Schema"""
    old_password: str
    new_password: str

