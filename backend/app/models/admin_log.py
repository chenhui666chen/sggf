"""
操作日志模型
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Text, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base


class AdminOperationLog(Base):
    """管理员操作日志表"""
    __tablename__ = "admin_operation_logs"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, comment="操作用户ID")
    username: Mapped[str] = mapped_column(String(255), comment="操作用户名")
    operation_type: Mapped[str] = mapped_column(String(50), index=True, comment="操作类型")
    resource_type: Mapped[str] = mapped_column(String(50), index=True, comment="资源类型")
    resource_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="资源ID")
    operation_desc: Mapped[str] = mapped_column(Text, comment="操作描述")
    request_method: Mapped[str] = mapped_column(String(10), comment="请求方法")
    request_path: Mapped[str] = mapped_column(String(500), comment="请求路径")
    request_params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="请求参数")
    response_status: Mapped[int] = mapped_column(Integer, comment="响应状态码")
    ip_address: Mapped[str] = mapped_column(String(50), comment="IP地址")
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="用户代理")
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="执行时长(毫秒)")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="错误信息")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    def __repr__(self):
        return f"<AdminOperationLog {self.operation_type} by {self.username}>"


class AdminLoginLog(Base):
    """管理员登录日志表"""
    __tablename__ = "admin_login_logs"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, comment="用户ID")
    username: Mapped[str] = mapped_column(String(255), comment="用户名")
    login_type: Mapped[str] = mapped_column(String(20), comment="登录类型: login/logout")
    login_status: Mapped[str] = mapped_column(String(20), comment="登录状态: success/failed")
    ip_address: Mapped[str] = mapped_column(String(50), comment="IP地址")
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="用户代理")
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="失败原因")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    def __repr__(self):
        return f"<AdminLoginLog {self.login_type} by {self.username}>"
