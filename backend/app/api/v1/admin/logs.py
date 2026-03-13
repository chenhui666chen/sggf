"""
操作日志查询 API
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.permissions import require_admin, require_permission
from app.db.base import get_db
from app.models.user import User
from app.models.admin_log import AdminOperationLog, AdminLoginLog
from app.schemas.admin import (
    OperationLogListResponse,
    LoginLogListResponse,
    AdminOperationLogResponse,
    AdminLoginLogResponse,
)

router = APIRouter()


@router.get("/operations", response_model=OperationLogListResponse)
async def list_operation_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = None,
    operation_type: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(require_permission("log:read")),
    db: Session = Depends(get_db),
):
    """操作日志列表"""
    query = db.query(AdminOperationLog)
    
    if user_id:
        query = query.filter(AdminOperationLog.user_id == user_id)
    
    if operation_type:
        query = query.filter(AdminOperationLog.operation_type == operation_type)
    
    if resource_type:
        query = query.filter(AdminOperationLog.resource_type == resource_type)
    
    if start_date:
        query = query.filter(AdminOperationLog.created_at >= start_date)
    
    if end_date:
        query = query.filter(AdminOperationLog.created_at <= end_date)
    
    total = query.count()
    total_pages = (total + page_size - 1) // page_size
    
    logs = query.order_by(AdminOperationLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return OperationLogListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=[AdminOperationLogResponse.model_validate(log) for log in logs],
    )


@router.get("/logins", response_model=LoginLogListResponse)
async def list_login_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = None,
    login_type: Optional[str] = None,
    login_status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: User = Depends(require_permission("log:read")),
    db: Session = Depends(get_db),
):
    """登录日志列表"""
    query = db.query(AdminLoginLog)
    
    if user_id:
        query = query.filter(AdminLoginLog.user_id == user_id)
    
    if login_type:
        query = query.filter(AdminLoginLog.login_type == login_type)
    
    if login_status:
        query = query.filter(AdminLoginLog.login_status == login_status)
    
    if start_date:
        query = query.filter(AdminLoginLog.created_at >= start_date)
    
    if end_date:
        query = query.filter(AdminLoginLog.created_at <= end_date)
    
    total = query.count()
    total_pages = (total + page_size - 1) // page_size
    
    logs = query.order_by(AdminLoginLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return LoginLogListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=[AdminLoginLogResponse.model_validate(log) for log in logs],
    )
