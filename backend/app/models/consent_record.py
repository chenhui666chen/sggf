"""
同意记录模型（P2-4.3 / 架构文档 5.2，版本化、可审计）。

设计要点：
- 同意记录是合规证明，**注销后永久保留**（5.3），不随用户匿名化删除；
- 只存 IP 哈希（脱敏），不存 token/openid/email/phone；
- scope 为 JSON 文本（同意的数据范围），content_hash 为同意文案的 SHA-256；
- 撤回（withdrawn_at）留字段，当前不暴露撤销接口（YAGNI）。
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class ConsentRecord(Base):
    """同意记录表"""
    __tablename__ = "consent_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # 注销匿名化后 user_id 保留（合规证明需要归属线索），不设 FK ON DELETE
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    consent_type: Mapped[str] = mapped_column(String(50), index=True)  # privacy_policy / oauth_sync / phone_collection
    version: Mapped[str] = mapped_column(String(20))  # 同意文案版本号
    content_hash: Mapped[str] = mapped_column(String(64))  # 同意文案 SHA-256
    scope: Mapped[str] = mapped_column(Text)  # JSON，同意的数据范围
    ip_hash: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<ConsentRecord user={self.user_id} type={self.consent_type} v{self.version}>"
