"""
认证API路由
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import Optional
from pydantic import BaseModel
from app.db.base import get_db
from app.models.user import User
from app.schemas.user import (
    UserCreate, UserLogin, TokenResponse, UserResponse, PasswordChange
)
from app.core.security import (
    hash_password, verify_password, create_access_token, get_current_user
)
from app.services.oauth_service import OAuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class OAuthCallbackRequest(BaseModel):
    """OAuth回调请求"""
    code: str
    state: Optional[str] = None


class AlipayAuthUrlRequest(BaseModel):
    """支付宝授权URL请求"""
    redirect_uri: str
    state: Optional[str] = None


class WechatAuthUrlRequest(BaseModel):
    """微信授权URL请求"""
    redirect_uri: str
    state: Optional[str] = None


@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """用户注册"""
    # 检查用户是否已存在
    existing_user = db.query(User).filter(
        (User.username == user_data.username) | (User.email == user_data.email)
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered"
        )
    
    # 创建新用户
    user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        full_name=user_data.full_name
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # 生成token
    access_token = create_access_token(data={"sub": str(user.id)})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse.from_orm(user)
    }


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """用户登录"""
    user = db.query(User).filter(User.username == credentials.username).first()
    
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    # 生成token
    access_token = create_access_token(data={"sub": str(user.id)})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse.from_orm(user)
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserResponse.from_orm(current_user)


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """用户登出"""
    return {"message": "Logged out successfully"}


@router.post("/change-password")
async def change_password(
    password_data: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """修改密码"""
    if not verify_password(password_data.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Old password is incorrect"
        )
    
    current_user.password_hash = hash_password(password_data.new_password)
    db.add(current_user)
    db.commit()
    
    return {"message": "Password changed successfully"}


@router.post("/alipay/auth-url")
async def get_alipay_auth_url(request: AlipayAuthUrlRequest):
    """获取支付宝授权URL"""
    from app.core.config import settings
    
    alipay_service = OAuthService.AlipayOAuthService(
        app_id=settings.ALIPAY_APP_ID,
        private_key=settings.ALIPAY_PRIVATE_KEY,
        public_key=settings.ALIPAY_PUBLIC_KEY
    )
    
    auth_url = alipay_service.get_auth_url(request.redirect_uri, request.state)
    
    return {"auth_url": auth_url}


@router.post("/alipay/callback", response_model=TokenResponse)
async def alipay_callback(
    request: OAuthCallbackRequest,
    db: Session = Depends(get_db)
):
    """支付宝OAuth回调"""
    from app.core.config import settings
    
    alipay_service = OAuthService.AlipayOAuthService(
        app_id=settings.ALIPAY_APP_ID,
        private_key=settings.ALIPAY_PRIVATE_KEY,
        public_key=settings.ALIPAY_PUBLIC_KEY
    )
    
    token_data = await alipay_service.get_access_token(request.code)
    
    if "error" in token_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=token_data.get("error_description", "Alipay authentication failed")
        )
    
    access_token = token_data.get("access_token")
    user_info = await alipay_service.get_user_info(access_token)
    
    if "error" in user_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get user info from Alipay"
        )
    
    return OAuthService.handle_alipay_login(db, user_info)


@router.post("/wechat/auth-url")
async def get_wechat_auth_url(request: WechatAuthUrlRequest):
    """获取微信授权URL"""
    from app.core.config import settings
    
    wechat_service = OAuthService.WechatOAuthService(
        app_id=settings.WECHAT_APP_ID,
        app_secret=settings.WECHAT_APP_SECRET
    )
    
    auth_url = wechat_service.get_auth_url(request.redirect_uri, request.state)
    
    return {"auth_url": auth_url}


@router.post("/wechat/callback", response_model=TokenResponse)
async def wechat_callback(
    request: OAuthCallbackRequest,
    db: Session = Depends(get_db)
):
    """微信OAuth回调"""
    from app.core.config import settings
    
    wechat_service = OAuthService.WechatOAuthService(
        app_id=settings.WECHAT_APP_ID,
        app_secret=settings.WECHAT_APP_SECRET
    )
    
    token_data = await wechat_service.get_access_token(request.code)
    
    if "errcode" in token_data and token_data["errcode"] != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=token_data.get("errmsg", "WeChat authentication failed")
        )
    
    access_token = token_data.get("access_token")
    openid = token_data.get("openid")
    unionid = token_data.get("unionid")
    
    user_info = await wechat_service.get_user_info(access_token, openid)
    
    if "errcode" in user_info and user_info["errcode"] != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get user info from WeChat"
        )
    
    return OAuthService.handle_wechat_login(db, user_info, openid, unionid)

