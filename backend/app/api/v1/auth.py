"""
认证 API 路由
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    get_current_user,
    has_usable_password_hash,
    hash_password,
    verify_password,
)
from app.db.base import get_db
from app.models.user import User
from app.schemas.user import (
    EMAIL_PATTERN,
    PHONE_PATTERN,
    PasswordChange,
    PasswordResetCodeRequest,
    PasswordResetCodeResponse,
    PasswordResetConfirm,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    normalize_identity,
    normalize_optional_phone,
)
from app.services.email_service import (
    EmailDeliveryError,
    EmailService,
    EmailServiceNotConfiguredError,
)
from app.services.oauth_service import (
    AlipayOAuthService,
    OAuthService,
    WechatOAuthService,
)
from app.services.password_reset_service import PasswordResetService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
password_reset_service = PasswordResetService()
password_reset_email_service = EmailService()


class OAuthCallbackRequest(BaseModel):
    """OAuth 回调请求。"""

    code: str
    state: Optional[str] = None


class AlipayAuthUrlRequest(BaseModel):
    """支付宝授权地址请求。"""

    redirect_uri: str
    state: Optional[str] = None


class WechatAuthUrlRequest(BaseModel):
    """微信授权地址请求。"""

    redirect_uri: str
    state: Optional[str] = None


def _normalize_username(value: str) -> str:
    return value.strip()


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _normalize_phone(value: Optional[str]) -> Optional[str]:
    return normalize_optional_phone(value)


def _build_token_response(user: User) -> dict:
    """统一构造登录响应。"""
    return {
        "access_token": create_access_token(data={"sub": str(user.id)}),
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
    }


def _find_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    normalized = normalize_identity(identifier)

    if EMAIL_PATTERN.match(normalized):
        return db.query(User).filter(func.lower(User.email) == normalized).first()

    if PHONE_PATTERN.match(normalized):
        return db.query(User).filter(User.phone == normalized).first()

    return db.query(User).filter(User.username == normalized).first()


def _ensure_local_password_account(user: User) -> None:
    if not has_usable_password_hash(user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前账号未启用本地密码登录，请使用原登录方式",
        )


def _password_reset_request_message() -> str:
    return "如果账号存在且已绑定本地密码，验证码将发送到注册邮箱"


def _build_password_reset_code_response(*, message: str, dev_code: str | None = None) -> dict:
    response = {
        "message": message,
        "expires_in": settings.PASSWORD_RESET_CODE_TTL_SECONDS,
        "resend_in": settings.PASSWORD_RESET_RESEND_INTERVAL_SECONDS,
    }
    if dev_code:
        response["dev_code"] = dev_code
    return response


def _ensure_alipay_configured() -> None:
    missing = [
        name
        for name, value in {
            "ALIPAY_APP_ID": settings.ALIPAY_APP_ID,
            "ALIPAY_PRIVATE_KEY": settings.ALIPAY_PRIVATE_KEY,
            "ALIPAY_PUBLIC_KEY": settings.ALIPAY_PUBLIC_KEY,
        }.items()
        if not str(value or "").strip()
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="支付宝登录尚未完成服务端配置",
        )


def _ensure_wechat_configured() -> None:
    missing = [
        name
        for name, value in {
            "WECHAT_APP_ID": settings.WECHAT_APP_ID,
            "WECHAT_APP_SECRET": settings.WECHAT_APP_SECRET,
        }.items()
        if not str(value or "").strip()
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="微信登录尚未完成服务端配置",
        )


@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """用户注册。"""
    normalized_username = _normalize_username(user_data.username)
    normalized_email = _normalize_email(str(user_data.email))
    normalized_phone = _normalize_phone(user_data.phone)

    if db.query(User).filter(func.lower(User.email) == normalized_email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册",
        )

    if normalized_phone and db.query(User).filter(User.phone == normalized_phone).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="手机号已被注册",
        )

    if db.query(User).filter(User.username == normalized_username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已被使用",
        )

    user = User(
        username=normalized_username,
        email=normalized_email,
        phone=normalized_phone,
        password_hash=hash_password(user_data.password),
        full_name=normalized_username,
    )

    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="注册信息已存在，请更换后重试",
        )
    db.refresh(user)

    return _build_token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """用户登录，支持用户名、邮箱或手机号。"""
    user = _find_user_by_identifier(db, credentials.username)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名、邮箱、手机号或密码错误",
        )

    _ensure_local_password_account(user)

    if not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名、邮箱、手机号或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户账户已被禁用",
        )

    return _build_token_response(user)


@router.post("/reset-password/request-code", response_model=PasswordResetCodeResponse)
async def request_password_reset_code(
    payload: PasswordResetCodeRequest,
    db: Session = Depends(get_db),
):
    """发送找回密码验证码。"""
    if not settings.DEBUG and not password_reset_email_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="找回密码邮件服务尚未完成服务端配置",
        )

    user = _find_user_by_identifier(db, payload.account)
    dev_code: str | None = None

    if not user or not user.is_active or not has_usable_password_hash(user.password_hash):
        return _build_password_reset_code_response(message=_password_reset_request_message())

    code = await password_reset_service.issue_code(user.id)
    if code is None:
        return _build_password_reset_code_response(message=_password_reset_request_message())

    try:
        await password_reset_email_service.send_password_reset_code(user.email, code)
    except EmailServiceNotConfiguredError as exc:
        await password_reset_service.delete_code(user.id)
        if settings.DEBUG:
            dev_code = code
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="找回密码邮件服务尚未完成服务端配置",
            ) from exc
    except EmailDeliveryError as exc:
        await password_reset_service.delete_code(user.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="验证码发送失败，请稍后重试",
        ) from exc

    return _build_password_reset_code_response(
        message=_password_reset_request_message(),
        dev_code=dev_code,
    )


@router.post("/reset-password")
async def reset_password(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    """通过邮箱验证码重置本地密码。"""
    user = _find_user_by_identifier(db, payload.account)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码无效或已过期",
        )

    is_valid = await password_reset_service.verify_code(user.id, payload.code)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码无效或已过期",
        )

    _ensure_local_password_account(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户账户已被禁用",
        )

    user.password_hash = hash_password(payload.new_password)
    db.add(user)
    db.commit()

    return {"message": "密码重置成功，请使用新密码登录"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """获取当前用户信息。"""
    return UserResponse.model_validate(current_user)


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """用户登出。"""
    return {"message": "退出登录成功"}


@router.post("/change-password")
async def change_password(
    password_data: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改密码。"""
    _ensure_local_password_account(current_user)

    if not verify_password(password_data.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码错误",
        )

    current_user.password_hash = hash_password(password_data.new_password)
    db.add(current_user)
    db.commit()

    return {"message": "密码修改成功"}


@router.post("/alipay/auth-url")
async def get_alipay_auth_url(request: AlipayAuthUrlRequest):
    """获取支付宝授权地址。"""
    _ensure_alipay_configured()
    alipay_service = AlipayOAuthService(
        app_id=settings.ALIPAY_APP_ID,
        private_key=settings.ALIPAY_PRIVATE_KEY,
        public_key=settings.ALIPAY_PUBLIC_KEY,
    )
    return {"auth_url": alipay_service.get_auth_url(request.redirect_uri, request.state)}


@router.post("/alipay/callback", response_model=TokenResponse)
async def alipay_callback(
    request: OAuthCallbackRequest,
    db: Session = Depends(get_db),
):
    """支付宝 OAuth 回调。"""
    _ensure_alipay_configured()
    alipay_service = AlipayOAuthService(
        app_id=settings.ALIPAY_APP_ID,
        private_key=settings.ALIPAY_PRIVATE_KEY,
        public_key=settings.ALIPAY_PUBLIC_KEY,
    )

    token_data = await alipay_service.get_access_token(request.code)
    if "error" in token_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=token_data.get("error_description") or token_data.get("sub_msg") or "支付宝认证失败",
        )

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="支付宝未返回 access_token",
        )

    user_info = await alipay_service.get_user_info(access_token)
    if "error" in user_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_info.get("error_description") or user_info.get("sub_msg") or "获取支付宝用户信息失败",
        )

    return OAuthService.handle_alipay_login(db, user_info)


@router.post("/wechat/auth-url")
async def get_wechat_auth_url(request: WechatAuthUrlRequest):
    """获取微信授权地址。"""
    _ensure_wechat_configured()
    wechat_service = WechatOAuthService(
        app_id=settings.WECHAT_APP_ID,
        app_secret=settings.WECHAT_APP_SECRET,
    )
    return {"auth_url": wechat_service.get_auth_url(request.redirect_uri, request.state)}


@router.post("/wechat/callback", response_model=TokenResponse)
async def wechat_callback(
    request: OAuthCallbackRequest,
    db: Session = Depends(get_db),
):
    """微信 OAuth 回调。"""
    _ensure_wechat_configured()
    wechat_service = WechatOAuthService(
        app_id=settings.WECHAT_APP_ID,
        app_secret=settings.WECHAT_APP_SECRET,
    )

    token_data = await wechat_service.get_access_token(request.code)
    if "errcode" in token_data and token_data["errcode"] != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=token_data.get("errmsg", "微信认证失败"),
        )

    access_token = token_data.get("access_token")
    openid = token_data.get("openid")
    unionid = token_data.get("unionid")
    if not access_token or not openid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="微信未返回完整授权信息",
        )

    user_info = await wechat_service.get_user_info(access_token, openid)
    if "errcode" in user_info and user_info["errcode"] != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_info.get("errmsg", "获取微信用户信息失败"),
        )

    return OAuthService.handle_wechat_login(db, user_info, openid, unionid)
