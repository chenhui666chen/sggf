"""
审计日志（脱敏）查询 API（P2-4.4）。

- 仅管理员可查（复用 log:read 权限）；
- 返回的 IP/UA 均为哈希，不含 email/phone/openid/token；
- 查询时顺带懒清理超过保留期（90 天）的记录。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.permissions import require_permission
from app.db.base import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.admin import AdminAuditLogResponse, AuditLogListResponse
from app.services.audit_log_service import cleanup_expired_audit_logs

router = APIRouter()


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = None,
    event_type: Optional[str] = None,
    success: Optional[bool] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(require_permission("log:read")),
    db: Session = Depends(get_db),
):
    """审计日志列表（脱敏）。"""
    cleanup_expired_audit_logs(db)

    query = db.query(AuditLog)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    if success is not None:
        query = query.filter(AuditLog.success == success)
    if start_date:
        query = query.filter(AuditLog.created_at >= start_date)
    if end_date:
        query = query.filter(AuditLog.created_at <= end_date)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size
    items = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return AuditLogListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=[AdminAuditLogResponse.model_validate(log) for log in items],
    )
