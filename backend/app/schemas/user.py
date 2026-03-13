"""
用户 Schema
"""
from datetime import datetime
from typing import List
import re

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


class RoleSimple(BaseModel):
    """角色简单 Schema"""
    id: int
    code: str
    name: str
    
    model_config = ConfigDict(from_attributes=True)


def normalize_identity(value: str) -> str:
    normalized = value.strip()
    if EMAIL_PATTERN.match(normalized):
        return normalized.lower()
    return normalized


def normalize_optional_phone(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


class UserBase(BaseModel):
    """用户基础 Schema"""

    username: str
    email: EmailStr
    phone: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        normalized = normalize_optional_phone(value)
        if normalized is None:
            return None

        if not PHONE_PATTERN.match(normalized):
            raise ValueError("请输入有效的手机号")

        return normalized


class UserCreate(UserBase):
    """用户创建 Schema"""

    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("用户名不能为空")
        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("用户名长度必须在 2-50 个字符之间")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 6 or len(value) > 50:
            raise ValueError("密码长度必须在 6-50 个字符之间")
        return value


class UserUpdate(BaseModel):
    """用户更新 Schema"""

    username: str | None = None
    avatar_url: str | None = None
    phone: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("用户名长度必须在 2-50 个字符之间")
        return normalized

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        normalized = normalize_optional_phone(value)
        if normalized is None:
            return None

        if not PHONE_PATTERN.match(normalized):
            raise ValueError("请输入有效的手机号")

        return normalized


class UserResponse(UserBase):
    """用户响应 Schema"""

    id: int
    full_name: str | None = None
    avatar_url: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    roles: List[RoleSimple] = []

    model_config = ConfigDict(from_attributes=True)


class UserLogin(BaseModel):
    """用户登录 Schema"""

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = normalize_identity(value)
        if not normalized:
            raise ValueError("请输入用户名、邮箱或手机号")

        if PHONE_PATTERN.match(normalized):
            return normalized

        if EMAIL_PATTERN.match(normalized):
            return normalized

        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("请输入有效的用户名、邮箱或手机号")

        return normalized


class PasswordChange(BaseModel):
    """密码修改 Schema"""

    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        if len(value) < 6 or len(value) > 50:
            raise ValueError("新密码长度必须在 6-50 个字符之间")
        return value


class PasswordResetCodeRequest(BaseModel):
    """找回密码验证码发送请求。"""

    account: str

    @field_validator("account")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        normalized = normalize_identity(value)
        if not normalized:
            raise ValueError("请输入用户名、邮箱或手机号")

        if PHONE_PATTERN.match(normalized):
            return normalized

        if EMAIL_PATTERN.match(normalized):
            return normalized

        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("请输入有效的用户名、邮箱或手机号")

        return normalized


class PasswordResetConfirm(BaseModel):
    """找回密码确认请求。"""

    account: str
    code: str
    new_password: str

    @field_validator("account")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        normalized = normalize_identity(value)
        if not normalized:
            raise ValueError("请输入用户名、邮箱或手机号")

        if PHONE_PATTERN.match(normalized):
            return normalized

        if EMAIL_PATTERN.match(normalized):
            return normalized

        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("请输入有效的用户名、邮箱或手机号")

        return normalized

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("请输入验证码")
        if not normalized.isdigit() or len(normalized) != 6:
            raise ValueError("请输入 6 位数字验证码")
        return normalized

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 6 or len(value) > 50:
            raise ValueError("新密码长度必须在 6-50 个字符之间")
        return value


class PasswordResetCodeResponse(BaseModel):
    """找回密码验证码发送响应。"""

    message: str
    expires_in: int
    resend_in: int
    dev_code: str | None = None


class TokenResponse(BaseModel):
    """Token 响应 Schema"""

    access_token: str
    token_type: str
    user: UserResponse
