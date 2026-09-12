"""密码历史表（P2-4.6）

只存独立 pepper 的 HMAC-SHA256 十六进制，绝不存 bcrypt/明文；
与登录 password_hash 完全分离，避免一处泄露同时破译历史与当前密码。
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class PasswordHistory(Base):
    """用户历史密码（仅 HMAC 摘要），用于"新密码不与最近 N 次重复"检查。"""

    __tablename__ = "password_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    # HMAC-SHA256(PASSWORD_HISTORY_PEPPER, password) 的十六进制（64 字符）
    password_pepper_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
