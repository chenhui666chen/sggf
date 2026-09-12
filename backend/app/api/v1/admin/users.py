"""
用户管理 API
"""
import math
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.permissions import is_super_admin, require_admin
from app.core.security import hash_password
from app.db.base import get_db
from app.models.admin_log import AdminOperationLog
from app.models.user import User
from app.models.role import Role
from app.services.password_history_service import password_history_service
from app.schemas.admin import (
    UserAdminResponse,
    UserListResponse,
    UserCreateByAdmin,
    UserUpdateByAdmin,
    UserStatusUpdate,
    UserRoleUpdate,
    UserPointsAdjustmentCreate,
    UserPointsAdjustmentListResponse,
    UserPointsAdjustmentResponse,
    UserPointsAccountOverviewResponse,
    UserPointsBillingEventListResponse,
)
from app.schemas.user_center import UserCenterPointsEntry
from app.services.admin_points_billing import points_billing_log_to_response
from app.services.user_center_points import POINTS_SOURCE_LABELS
from app.services.user_center_points_events import (
    list_user_points_billing_logs,
)
from app.services.user_points_read_model import UserPointsReadModelSnapshot, build_user_points_read_model
from app.utils.datetime_utils import ensure_utc_datetime, utc_now

router = APIRouter()


def _resolve_assignable_roles(
    db: Session, role_ids: list[int], current_user: User
) -> list[Role]:
    """解析并校验可分配角色（P1-3.9 提权防护）。

    普通 admin 不得分配 super_admin 角色（含给自己/他人），否则可自提权；
    super_admin 角色仅 super_admin 可分配。
    """
    roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
    if not is_super_admin(current_user) and any(
        role.code == "super_admin" for role in roles
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权分配超级管理员角色",
        )
    return roles


def _points_adjustment_log_to_response(log: AdminOperationLog) -> UserPointsAdjustmentResponse:
    payload = log.request_params or {}
    return UserPointsAdjustmentResponse(
        id=log.id,
        target_user_id=int(log.resource_id or payload.get("target_user_id") or 0),
        operator_user_id=log.user_id,
        operator_username=log.username,
        delta=float(payload.get("delta") or 0),
        reason=str(payload.get("reason") or "").strip(),
        adjustment_type=str(payload.get("adjustment_type") or "manual_grant").strip() or "manual_grant",
        expires_at=payload.get("expires_at"),
        created_at=log.created_at,
    )


def _points_entry_snapshot_to_response(snapshot: object) -> UserCenterPointsEntry:
    source_key = str(getattr(snapshot, "source_key", "") or "").strip()
    return UserCenterPointsEntry(
        key=str(getattr(snapshot, "key", "") or "").strip(),
        source_key=source_key,
        source_label=POINTS_SOURCE_LABELS.get(source_key, source_key),
        title=str(getattr(snapshot, "title", "") or "").strip(),
        summary=str(getattr(snapshot, "summary", "") or "").strip(),
        amount=float(getattr(snapshot, "amount", 0) or 0),
        direction=getattr(snapshot, "direction", "income"),
        status=getattr(snapshot, "status", "active"),
        occurred_at=getattr(snapshot, "occurred_at", None),
        expires_at=getattr(snapshot, "expires_at", None),
        action_path=getattr(snapshot, "action_path", None),
        action_label=getattr(snapshot, "action_label", None),
    )


def _points_account_overview_to_response(
    *,
    target_user_id: int,
    read_model: UserPointsReadModelSnapshot,
) -> UserPointsAccountOverviewResponse:
    account = read_model.points_bundle.account
    account_is_live = account.connected_source_count > 0
    balance = round(float(account.balance), 2) if account_is_live else None
    frozen = round(float(account.frozen), 2) if account_is_live else None
    available = round(float(account.balance - account.frozen), 2) if account_is_live else None
    expiring_soon = round(float(account.expiring_soon), 2) if account_is_live else None

    return UserPointsAccountOverviewResponse(
        target_user_id=target_user_id,
        balance=balance,
        frozen=frozen,
        available=available,
        expiring_soon=expiring_soon,
        status="partial" if account_is_live else "planned",
        connected_source_count=account.connected_source_count,
        entries=[
            _points_entry_snapshot_to_response(entry)
            for entry in read_model.points_bundle.entries[:20]
        ],
    )

@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    role_code: Optional[str] = None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户列表（分页/搜索/过滤）"""
    query = db.query(User)
    
    if search:
        query = query.filter(
            or_(
                User.username.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                User.phone.ilike(f"%{search}%"),
            )
        )
    
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    
    if role_code:
        query = query.join(User.roles).filter(Role.code == role_code)
    
    if created_after:
        query = query.filter(User.created_at >= created_after)
    
    if created_before:
        query = query.filter(User.created_at <= created_before)
    
    total = query.count()
    total_pages = (total + page_size - 1) // page_size
    
    users = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return UserListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=[UserAdminResponse.model_validate(user) for user in users],
    )


@router.get("/{user_id}", response_model=UserAdminResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户详情"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    return UserAdminResponse.model_validate(user)


@router.post("", response_model=UserAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreateByAdmin,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """新建用户"""
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册"
        )
    
    if user_data.phone and db.query(User).filter(User.phone == user_data.phone).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="手机号已被注册"
        )
    
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已被使用"
        )
    
    user = User(
        username=user_data.username,
        email=user_data.email,
        phone=user_data.phone,
        password_hash=hash_password(user_data.password),
        full_name=user_data.full_name or user_data.username,
    )
    
    if user_data.role_ids:
        user.roles = _resolve_assignable_roles(db, user_data.role_ids, current_user)
    
    db.add(user)
    db.flush()  # 先取 id：初始密码与建号同事务登记入历史（评审 #3）
    password_history_service.record(db, user.id, user_data.password)
    db.commit()
    db.refresh(user)
    
    return UserAdminResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserAdminResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdateByAdmin,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """编辑用户信息"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    update_data = user_data.model_dump(exclude_unset=True, exclude={"role_ids"})
    
    for field, value in update_data.items():
        setattr(user, field, value)
    
    if user_data.role_ids is not None:
        user.roles = _resolve_assignable_roles(db, user_data.role_ids, current_user)
    
    db.commit()
    db.refresh(user)
    
    return UserAdminResponse.model_validate(user)


@router.patch("/{user_id}/status", response_model=UserAdminResponse)
async def update_user_status(
    user_id: int,
    status_data: UserStatusUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """启用/禁用账号"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能禁用自己的账号"
        )
    
    user.is_active = status_data.is_active
    # 禁用账号必须递增 token_version，吊销其全部已签发 JWT（重新启用后旧 token 也不复活）
    if not status_data.is_active:
        user.token_version += 1
    db.commit()
    db.refresh(user)
    
    return UserAdminResponse.model_validate(user)


@router.post("/{user_id}/roles", response_model=UserAdminResponse)
async def assign_user_roles(
    user_id: int,
    role_data: UserRoleUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """分配角色"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    roles = _resolve_assignable_roles(db, role_data.role_ids, current_user)
    user.roles = roles
    
    db.commit()
    db.refresh(user)
    
    return UserAdminResponse.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """删除用户"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除自己的账号"
        )
    
    db.delete(user)
    db.commit()
    
    return None


@router.get("/{user_id}/points-adjustments", response_model=UserPointsAdjustmentListResponse)
async def list_user_points_adjustments(
    user_id: int,
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """查询用户的人工积分调整记录"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    logs = (
        db.query(AdminOperationLog)
        .filter(
            AdminOperationLog.operation_type == "POINTS_ADJUST",
            AdminOperationLog.resource_type == "USER_POINTS",
            AdminOperationLog.resource_id == user_id,
            AdminOperationLog.response_status < 400,
        )
        .order_by(AdminOperationLog.created_at.desc(), AdminOperationLog.id.desc())
        .limit(limit)
        .all()
    )

    return UserPointsAdjustmentListResponse(
        items=[_points_adjustment_log_to_response(log) for log in logs],
    )


@router.get("/{user_id}/points-account", response_model=UserPointsAccountOverviewResponse)
async def get_user_points_account(
    user_id: int,
    _current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """查询目标用户当前积分账户读模型"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    read_model = build_user_points_read_model(db=db, user_id=user_id)
    return _points_account_overview_to_response(target_user_id=user_id, read_model=read_model)


@router.get("/{user_id}/points-billing-events", response_model=UserPointsBillingEventListResponse)
async def list_user_points_billing_events(
    user_id: int,
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """查询用户正式积分计费事件"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    logs = list_user_points_billing_logs(
        db=db,
        target_user_id=user_id,
        limit=limit,
    )

    return UserPointsBillingEventListResponse(
        items=[points_billing_log_to_response(log) for log in logs],
    )


@router.post("/{user_id}/points-adjustments", response_model=UserPointsAdjustmentResponse, status_code=status.HTTP_201_CREATED)
async def create_user_points_adjustment(
    user_id: int,
    adjustment_data: UserPointsAdjustmentCreate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """为用户手工补发、充值或扣减积分"""
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    delta = float(adjustment_data.delta)
    if not math.isfinite(delta) or delta == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="积分调整值不能为 0",
        )

    expires_at = ensure_utc_datetime(adjustment_data.expires_at)
    if delta > 0 and expires_at is not None and expires_at <= utc_now():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="正向积分调整的过期时间必须晚于当前时间",
        )

    payload = {
        "target_user_id": target_user.id,
        "delta": round(delta, 2),
        "reason": adjustment_data.reason.strip(),
        "adjustment_type": adjustment_data.adjustment_type.strip() or "manual_grant",
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    sign = "+" if payload["delta"] > 0 else ""

    log = AdminOperationLog(
        user_id=current_user.id,
        username=current_user.username,
        operation_type="POINTS_ADJUST",
        resource_type="USER_POINTS",
        resource_id=target_user.id,
        operation_desc=f"为用户 {target_user.username} 调整积分 {sign}{payload['delta']:.2f}",
        request_method="POST",
        request_path=f"/api/v1/admin/users/{target_user.id}/points-adjustments",
        request_params=payload,
        response_status=status.HTTP_201_CREATED,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent"),
        duration_ms=0,
        error_message=None,
    )

    db.add(log)
    db.commit()
    db.refresh(log)

    return _points_adjustment_log_to_response(log)
