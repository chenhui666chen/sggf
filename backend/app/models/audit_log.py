"""
审计日志模型（P2-4.4，脱敏）。

设计约束（架构文档 4.4）：
- 只存 IP / User-Agent 的 HMAC 哈希，绝不存明文；
- ❌ 不存储：验证码、token、openid、email、phone、密码；
- 保留 90 天（AUDIT_LOG_RETENTION_DAYS），仅管理员可查询。
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class AuditLog(Base):
    """审计日志表（脱敏）"""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # 关联用户（匿名登录失败/未知账号可空；注销匿名化后此列保留为 id，不存 email/username）
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), index=True)  # login/logout/register/...
    provider: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # alipay/wechat/...
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # HMAC-SHA256
    user_agent_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # HMAC-SHA256
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.event_type} user={self.user_id} success={self.success}>"
