"""视频 API 应用与主站用户的归属关系。"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class VideoApiApplication(Base):
    __tablename__ = "video_api_applications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    gateway_client_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    plan_code: Mapped[str] = mapped_column(String(40), nullable=False, default="standard")
    rate_limit_per_second: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    burst_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_active_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_parallel_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    lifetime_task_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    api_key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    daily_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    monthly_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
