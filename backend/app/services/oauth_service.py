"""
第三方登录服务
"""
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, make_unusable_password_hash
from app.models.user import User


class AlipayOAuthService:
    """支付宝 OAuth 服务。"""

    def __init__(self, app_id: str, private_key: str, public_key: str):
        self.app_id = app_id
        self.private_key = private_key
        self.public_key = public_key
        self.auth_url = "https://openapi.alipay.com/gateway.do"

    def get_auth_url(self, redirect_uri: str, state: Optional[str] = None) -> str:
        """获取支付宝授权地址。"""
        from urllib.parse import urlencode

        params = {
            "app_id": self.app_id,
            "scope": "auth_user",
            "redirect_uri": redirect_uri,
            "response_type": "code",
        }
        if state:
            params["state"] = state

        return f"https://openauth.alipay.com/oauth2/publicAppAuthorize.htm?{urlencode(params)}"

    async def get_access_token(self, code: str) -> Dict[str, Any]:
        """通过授权码换取访问令牌。"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self.auth_url,
                data={
                    "app_id": self.app_id,
                    "method": "alipay.system.oauth.token",
                    "charset": "utf-8",
                    "sign_type": "RSA2",
                    "timestamp": self._get_timestamp(),
                    "version": "1.0",
                    "grant_type": "authorization_code",
                    "code": code,
                },
            )
            response.raise_for_status()
            payload = response.json()

        token_data = payload.get("alipay_system_oauth_token_response", payload)
        if str(token_data.get("code", "10000")) != "10000":
            return {
                "error": token_data.get("sub_code") or token_data.get("code") or "alipay_auth_failed",
                "error_description": token_data.get("sub_msg") or token_data.get("msg") or "Alipay authentication failed",
            }
        return token_data

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """获取支付宝用户信息。"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self.auth_url,
                data={
                    "app_id": self.app_id,
                    "method": "alipay.user.info.share",
                    "charset": "utf-8",
                    "sign_type": "RSA2",
                    "timestamp": self._get_timestamp(),
                    "version": "1.0",
                    "auth_token": access_token,
                },
            )
            response.raise_for_status()
            payload = response.json()

        user_info = payload.get("alipay_user_info_share_response", payload)
        if str(user_info.get("code", "10000")) != "10000":
            return {
                "error": user_info.get("sub_code") or user_info.get("code") or "alipay_user_info_failed",
                "error_description": user_info.get("sub_msg") or user_info.get("msg") or "Failed to get user info from Alipay",
            }
        return user_info

    def _get_timestamp(self) -> str:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class WechatOAuthService:
    """微信 OAuth 服务。"""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.auth_url = "https://open.weixin.qq.com/connect/qrconnect"
        self.api_url = "https://api.weixin.qq.com"

    def get_auth_url(self, redirect_uri: str, state: Optional[str] = None) -> str:
        """获取微信授权地址。"""
        from urllib.parse import urlencode

        params = {
            "appid": self.app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "snsapi_login",
        }
        if state:
            params["state"] = state

        return f"{self.auth_url}?{urlencode(params)}#wechat_redirect"

    async def get_access_token(self, code: str) -> Dict[str, Any]:
        """通过授权码换取访问令牌。"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.api_url}/sns/oauth2/access_token",
                params={
                    "appid": self.app_id,
                    "secret": self.app_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_user_info(self, access_token: str, openid: str) -> Dict[str, Any]:
        """获取微信用户信息。"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.api_url}/sns/userinfo",
                params={
                    "access_token": access_token,
                    "openid": openid,
                },
            )
            response.raise_for_status()
            return response.json()


class OAuthService:
    """第三方登录统一入口。"""

    @staticmethod
    def _build_user_payload(user: User) -> Dict[str, Any]:
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        }

    @staticmethod
    def _allocate_identity(db: Session, provider: str, raw_id: str) -> tuple[str, str]:
        base = f"{provider}_{raw_id[-12:]}".lower()
        candidate = base
        index = 1

        while db.query(User).filter(User.username == candidate).first():
            index += 1
            candidate = f"{base}_{index}"

        return candidate, f"{candidate}@{provider}.temp"

    @staticmethod
    def _ensure_active(user: User) -> User:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户账户已被禁用",
            )
        return user

    @staticmethod
    def _sync_external_user(
        db: Session,
        user: User,
        *,
        full_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
        alipay_openid: Optional[str] = None,
        wechat_openid: Optional[str] = None,
        wechat_unionid: Optional[str] = None,
    ) -> User:
        changed = False

        if full_name and user.full_name != full_name:
            user.full_name = full_name
            changed = True

        if avatar_url and user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            changed = True

        if alipay_openid and user.alipay_openid != alipay_openid:
            user.alipay_openid = alipay_openid
            changed = True

        if wechat_openid and user.wechat_openid != wechat_openid:
            user.wechat_openid = wechat_openid
            changed = True

        if wechat_unionid and user.wechat_unionid != wechat_unionid:
            user.wechat_unionid = wechat_unionid
            changed = True

        if changed:
            db.add(user)
            db.commit()
            db.refresh(user)

        return user

    @staticmethod
    def _create_external_user(
        db: Session,
        provider: str,
        raw_id: str,
        full_name: str,
        avatar_url: Optional[str] = None,
        alipay_openid: Optional[str] = None,
        wechat_openid: Optional[str] = None,
        wechat_unionid: Optional[str] = None,
    ) -> User:
        username, email = OAuthService._allocate_identity(db, provider, raw_id)
        user = User(
            username=username,
            email=email,
            phone=None,
            password_hash=make_unusable_password_hash(),
            full_name=full_name,
            avatar_url=avatar_url,
            alipay_openid=alipay_openid,
            wechat_openid=wechat_openid,
            wechat_unionid=wechat_unionid,
            is_active=True,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if alipay_openid:
                existing = db.query(User).filter(User.alipay_openid == alipay_openid).first()
                if existing:
                    return existing
            if wechat_openid:
                existing = db.query(User).filter(User.wechat_openid == wechat_openid).first()
                if existing:
                    return existing
            raise
        db.refresh(user)
        return user

    @staticmethod
    def handle_alipay_login(db: Session, user_info: Dict[str, Any]) -> Dict[str, Any]:
        """处理支付宝登录。"""
        alipay_user_id = str(user_info.get("user_id") or "").strip()
        if not alipay_user_id:
            raise ValueError("Invalid Alipay user info")

        full_name = str(user_info.get("nick_name") or f"alipay_{alipay_user_id[-6:]}")

        user = db.query(User).filter(User.alipay_openid == alipay_user_id).first()
        if not user:
            user = OAuthService._create_external_user(
                db=db,
                provider="alipay",
                raw_id=alipay_user_id,
                full_name=full_name,
                alipay_openid=alipay_user_id,
            )
        else:
            user = OAuthService._sync_external_user(
                db,
                user,
                full_name=full_name,
                alipay_openid=alipay_user_id,
            )

        user = OAuthService._ensure_active(user)

        access_token = create_access_token(data={"sub": str(user.id)})
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": OAuthService._build_user_payload(user),
        }

    @staticmethod
    def handle_wechat_login(
        db: Session,
        user_info: Dict[str, Any],
        openid: str,
        unionid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """处理微信登录。"""
        openid = str(openid or "").strip()
        unionid = str(unionid or "").strip() or None
        if not openid:
            raise ValueError("Invalid WeChat user info")

        full_name = str(user_info.get("nickname") or f"wechat_{openid[-6:]}")
        avatar_url = user_info.get("headimgurl")

        user = db.query(User).filter(User.wechat_openid == openid).first()
        if not user and unionid:
            user = db.query(User).filter(User.wechat_unionid == unionid).first()

        if not user:
            user = OAuthService._create_external_user(
                db=db,
                provider="wechat",
                raw_id=openid,
                full_name=full_name,
                avatar_url=avatar_url,
                wechat_openid=openid,
                wechat_unionid=unionid,
            )
        else:
            user = OAuthService._sync_external_user(
                db,
                user,
                full_name=full_name,
                avatar_url=avatar_url,
                wechat_openid=openid,
                wechat_unionid=unionid,
            )

        user = OAuthService._ensure_active(user)

        access_token = create_access_token(data={"sub": str(user.id)})
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": OAuthService._build_user_payload(user),
        }
