"""
第三方登录服务
"""
import base64
import json
import re
from typing import Any, Dict, Optional

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, make_unusable_password_hash
from app.models.user import User


def _normalize_key_material(material: str, label: str) -> bytes:
    """将单行 Base64 或 PEM 格式的密钥材料归一化为 PEM 字节串。"""
    text = str(material or "").strip()
    if text.startswith("-----BEGIN"):
        return text.encode("utf-8")
    body = "".join(text.split())
    if not body:
        raise ValueError("空的密钥材料")
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    return "-----BEGIN {label}-----\n{body}\n-----END {label}-----\n".format(
        label=label, body="\n".join(lines)
    ).encode("utf-8")


def load_alipay_private_key(material: str):
    """加载支付宝应用私钥（支持单行 Base64 或 PEM）。"""
    return serialization.load_pem_private_key(
        _normalize_key_material(material, "PRIVATE KEY"), password=None
    )


def load_alipay_public_key(material: str):
    """加载支付宝公钥（支持单行 Base64 或 PEM）。"""
    return serialization.load_pem_public_key(
        _normalize_key_material(material, "PUBLIC KEY")
    )


def build_sign_content(params: Dict[str, Any]) -> str:
    """按支付宝规则拼接待签名串：键 ASCII 升序，剔除 sign 与空值，值不做 URL 编码。"""
    return "&".join(
        f"{key}={params[key]}"
        for key in sorted(params)
        if key != "sign" and params[key] not in (None, "")
    )


def strip_sign_fields(raw_text: str) -> str:
    """从响应原文中剔除 sign/sign_type 字段，得到待验签串。"""
    stripped = re.sub(r'"sign"\s*:\s*"[^"]*"\s*,?', "", raw_text)
    stripped = re.sub(r'"sign_type"\s*:\s*"[^"]*"\s*,?', "", stripped)
    return re.sub(r",\s*}", "}", stripped)


class AlipayOAuthService:
    """支付宝 OAuth 服务（请求需 RSA2 签名，响应使用支付宝公钥验签）。"""

    def __init__(self, app_id: str, private_key: str, public_key: str):
        self.app_id = app_id
        self.auth_url = "https://openapi.alipay.com/gateway.do"
        try:
            self._private_key = load_alipay_private_key(private_key)
            self._public_key = load_alipay_public_key(public_key)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="支付宝密钥配置格式错误，请检查 ALIPAY_PRIVATE_KEY / ALIPAY_PUBLIC_KEY",
            ) from exc

    def _sign(self, params: Dict[str, Any]) -> str:
        """使用应用私钥对请求参数做 RSA2（SHA256withRSA）签名。"""
        content = build_sign_content(params)
        signature = self._private_key.sign(
            content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
        )
        return base64.b64encode(signature).decode("ascii")

    def _verify_response(self, raw_text: str, payload: Dict[str, Any]) -> bool:
        """使用支付宝公钥验证响应签名；未配置公钥时跳过验签。"""
        if self._public_key is None:
            return True
        sign = str(payload.get("sign") or "")
        if not sign:
            return False
        content = strip_sign_fields(raw_text)
        try:
            self._public_key.verify(
                base64.b64decode(sign),
                content.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError):
            return False
        return True

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
        """通过授权码换取访问令牌（请求带 RSA2 签名）。"""
        params = {
            "app_id": self.app_id,
            "method": "alipay.system.oauth.token",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": self._get_timestamp(),
            "version": "1.0",
            "grant_type": "authorization_code",
            "code": code,
        }
        params["sign"] = self._sign(params)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(self.auth_url, data=params)
            response.raise_for_status()
            payload = json.loads(response.text)

        if not self._verify_response(response.text, payload):
            return {
                "error": "alipay_sign_verify_failed",
                "error_description": "支付宝响应验签失败",
            }

        token_data = payload.get("alipay_system_oauth_token_response", payload)
        if str(token_data.get("code", "10000")) != "10000":
            return {
                "error": token_data.get("sub_code") or token_data.get("code") or "alipay_auth_failed",
                "error_description": token_data.get("sub_msg") or token_data.get("msg") or "Alipay authentication failed",
            }
        return token_data

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """获取支付宝用户信息（请求带 RSA2 签名）。"""
        params = {
            "app_id": self.app_id,
            "method": "alipay.user.info.share",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": self._get_timestamp(),
            "version": "1.0",
            "auth_token": access_token,
        }
        params["sign"] = self._sign(params)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(self.auth_url, data=params)
            response.raise_for_status()
            payload = json.loads(response.text)

        if not self._verify_response(response.text, payload):
            return {
                "error": "alipay_sign_verify_failed",
                "error_description": "支付宝响应验签失败",
            }

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
