"""
用户模型
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.base import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # 昵称（原 username 字段，用于展示，不作为登录凭证）
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # 邮箱（作为登录凭证）
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # 手机号（可选，也可作为登录凭证）
    phone: Mapped[Optional[str]] = mapped_column(String(20), unique=True, index=True, nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # 昵称（用于展示，与 username 相同，保留 full_name 字段以兼容）
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    alipay_openid: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    wechat_openid: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    wechat_unionid: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<User {self.username}>"

