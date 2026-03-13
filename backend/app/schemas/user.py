"""
用户 Schema
"""
from pydantic import BaseModel, EmailStr, validator
from datetime import datetime
from typing import Optional
import re


class UserBase(BaseModel):
    """用户基础 Schema"""
    username: str  # 昵称
    email: EmailStr
    phone: Optional[str] = None  # 可选手机号


class UserCreate(UserBase):
    """用户创建 Schema"""
    password: str
    
    @validator('username')
    def validate_username(cls, v):
        """验证昵称"""
        if not v or len(v.strip()) == 0:
            raise ValueError('昵称不能为空')
        if len(v) < 2 or len(v) > 50:
            raise ValueError('昵称长度必须在 2-50 个字符之间')
        return v.strip()
    
    @validator('phone')
    def validate_phone(cls, v):
        """验证手机号"""
        if v is None or v == '':
            return v
        # 中国大陆手机号验证
        pattern = r'^1[3-9]\d{9}$'
        if not re.match(pattern, v):
            raise ValueError('请输入有效的手机号码')
        return v
    
    @validator('password')
    def validate_password(cls, v):
        """验证密码"""
        if len(v) < 6 or len(v) > 50:
            raise ValueError('密码长度必须在 6-50 个字符之间')
        return v


class UserUpdate(BaseModel):
    """用户更新 Schema"""
    username: Optional[str] = None  # 昵称
    avatar_url: Optional[str] = None
    phone: Optional[str] = None
    
    @validator('username')
    def validate_username(cls, v):
        """验证昵称"""
        if v is not None:
            if len(v) < 2 or len(v) > 50:
                raise ValueError('昵称长度必须在 2-50 个字符之间')
            return v.strip()
        return v
    
    @validator('phone')
    def validate_phone(cls, v):
        """验证手机号"""
        if v is not None and v != '':
            pattern = r'^1[3-9]\d{9}$'
            if not re.match(pattern, v):
                raise ValueError('请输入有效的手机号码')
        return v


class UserResponse(UserBase):
    """用户响应 Schema"""
    id: int
    avatar_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    """用户登录 Schema"""
    username: str  # 可以是邮箱或手机号
    password: str
    
    @validator('username')
    def validate_username(cls, v):
        """验证登录用户名（邮箱或手机号）"""
        v = v.strip()
        # 验证是否为邮箱
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        # 验证是否为手机号
        phone_pattern = r'^1[3-9]\d{9}$'
        
        if not (re.match(email_pattern, v) or re.match(phone_pattern, v)):
            raise ValueError('请输入有效的邮箱或手机号码')
        return v


class TokenResponse(BaseModel):
    """Token 响应 Schema"""
    access_token: str
    token_type: str
    user: UserResponse


class PasswordChange(BaseModel):
    """密码修改 Schema"""
    old_password: str
    new_password: str

