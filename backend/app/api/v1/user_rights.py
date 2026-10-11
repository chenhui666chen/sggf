"""
用户数据权利 API（P2-4.3）。

端点：
- POST /api/v1/user/data/export    导出个人数据（PIPL 可携权，范围见架构 5.1）
- POST /api/v1/user/account/delete 注销账户（软删除 + 冷静期，5.3）
- PUT  /api/v1/user/profile        修改个人信息
- GET  /api/v1/user/consent        查看同意记录（5.2）
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.core.security as core_security
from app.core.config import settings
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.schemas.user import UserResponse, build_user_response
from app.schemas.user_rights import (
    AccountDeleteResponse,
    ConsentListResponse,
    ConsentRecordOut,
    DataExportResponse,
    OAuthBindingInfo,
    UserProfileUpdate,
)
from app.services.audit_log_service import EVENT_ACCOUNT_DELETE, EVENT_DATA_EXPORT, record_audit
from app.services.consent_service import consent_service

router = APIRouter(prefix="/api/v1/user", tags=["user-rights"])


def _client_ip(request: Request) -> Optional[str]:
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip
    client = getattr(request, "client", None)
    return client.host if client else None


def _user_agent(request: Request) -> Optional[str]:
    return request.headers.get("user-agent")


@router.get("/consent", response_model=ConsentListResponse)
async def list_consents(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看当前用户的同意记录（5.2 同意可审计）。"""
    records = consent_service.list_for_user(db, current_user.id)
    return ConsentListResponse(items=[ConsentRecordOut.model_validate(r) for r in records])


@router.post("/data/export", response_model=DataExportResponse)
async def export_user_data(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导出个人数据（PIPL 可携权）。

    openid 属第三方平台标识，绑定标记足以行权且避免二次泄露；
    密文 openid 不下发（决策见 P2 日志批次 D）。
    """
    consents = consent_service.list_for_user(db, current_user.id)
    payload = DataExportResponse(
        username=current_user.username,
        email=current_user.email,
        phone=current_user.phone,
        full_name=current_user.full_name,
        avatar_url=current_user.avatar_url,
        email_verified=current_user.email_verified,
        created_at=current_user.created_at,
        consent_version=current_user.consent_version,
        oauth_bindings=[
            OAuthBindingInfo(provider="alipay", bound=bool(current_user.alipay_openid_hash)),
            OAuthBindingInfo(
                provider="wechat",
                bound=bool(current_user.wechat_openid_hash or current_user.wechat_unionid_hash),
            ),
        ],
        consents=[ConsentRecordOut.model_validate(r) for r in consents],
        generated_at=datetime.now(timezone.utc),
    )
    record_audit(
        db,
        event_type=EVENT_DATA_EXPORT,
        user_id=current_user.id,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return payload


@router.post("/account/delete", response_model=AccountDeleteResponse)
async def delete_account(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """注销账户（5.3）：软删除 + 冷静期。

    - token_version +1：立即失效全部会话（旧 access/refresh 下次校验 401）；
    - is_active=False + deleted_at=now：登录态不可再访问；
    - 冷静期（ACCOUNT_DELETE_COOLING_DAYS）后由匿名化脚本处理。
    """
    # 依赖注入实例可能绑定在其他会话（测试/多依赖场景），按 id 重查再写
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该账号已注销",
        )

    cooling_days = int(settings.ACCOUNT_DELETE_COOLING_DAYS or 30)
    deleted_at = datetime.now(timezone.utc)
    user.is_active = False
    user.deleted_at = deleted_at
    user.token_version += 1
    db.add(user)
    db.commit()

    record_audit(
        db,
        event_type=EVENT_ACCOUNT_DELETE,
        user_id=user.id,
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )

    core_security.clear_auth_cookies(response)
    return AccountDeleteResponse(
        message=f"账号已注销。数据将在 {cooling_days} 天冷静期后匿名化处理；同意记录依法保留。",
        deleted_at=deleted_at,
        cooling_days=cooling_days,
    )


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    profile: UserProfileUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改个人信息。

    手机号变更不走本接口：必须经短信验证绑定流程（/auth/phone/bind-confirm），
    否则任意登录态可冒填他人手机号（抢注/冒用风险）。手机号收集同意记录在绑定流程中落库。
    """
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if profile.phone is not None and profile.phone != user.phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="修改手机号请通过短信验证绑定流程",
        )

    if profile.username is not None:
        user.username = profile.username
    if profile.full_name is not None:
        user.full_name = profile.full_name
    if profile.avatar_url is not None:
        user.avatar_url = profile.avatar_url

    try:
        db.add(user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已被占用",
        )

    db.refresh(user)
    return build_user_response(user)
