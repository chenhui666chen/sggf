"""
用户模型
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, DateTime, Boolean, Text, Integer, false
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.db.base import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # 昵称（原 username 字段，用于展示，不作为登录凭证）
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # 邮箱（作为登录凭证；OAuth 用户允许为 NULL，P1-3.2）
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    # 手机号（可选，也可作为登录凭证）
    phone: Mapped[Optional[str]] = mapped_column(String(20), unique=True, index=True, nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # 邮箱是否已验证（P1-3.8：两步注册建号即已验证；重置成功亦置已验证）
    # server_default 与迁移口径一致：原始 SQL 插入时同样默认未验证
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # 会话版本号：改密/重置/禁用时递增，用于使所有历史 JWT 立即失效
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 昵称（用于展示，与 username 相同，保留 full_name 字段以兼容）
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # 第三方 openid 存储（P2-4.1）：不再落明文。
    # - *_hash：HMAC-SHA256 确定性哈希，UNIQUE，专用于等值查找
    #   （不能用密文做等值查询：Fernet 带随机 IV，同值密文不同）
    # - *_encrypted：Fernet 密文，用于还原原始 openid
    alipay_openid_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    alipay_openid_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    wechat_openid_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    wechat_openid_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    wechat_unionid_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    wechat_unionid_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 数据权利（P2-4.3）：注销软删除时间戳（5.3 冷静期后由匿名化脚本处理）；
    # consent_version 为用户当前同意的文案版本号（5.2，完整记录在 consent_records）
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    roles: Mapped[List["Role"]] = relationship("Role", secondary="user_roles", back_populates="users")
    
    def __repr__(self):
        return f"<User {self.username}>"

