"""
第三方登录服务
"""
import base64
import json
from typing import Any, Dict, Optional

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import get_openid_crypto
from app.core.security import make_unusable_password_hash
from app.models.user import User


def _find_by_openid(db: Session, field: str, openid: Optional[str]) -> Optional[User]:
    """按 openid 的确定性查找哈希匹配用户（库内已无明文，只能比对哈希）。"""
    if not openid:
        return None
    return (
        db.query(User)
        .filter(getattr(User, f"{field}_hash") == get_openid_crypto().lookup_hash(openid))
        .first()
    )


def _sync_openid(user: User, field: str, openid: Optional[str]) -> bool:
    """写入 openid 的查找哈希与密文，返回是否发生变更。

    比对用哈希（无需解密即可判定变更），写入必须 hash 与 encrypted 成对更新。
    """
    if not openid:
        return False
    crypto = get_openid_crypto()
    lookup_hash = crypto.lookup_hash(openid)
    if getattr(user, f"{field}_hash") == lookup_hash:
        return False
    setattr(user, f"{field}_hash", lookup_hash)
    setattr(user, f"{field}_encrypted", crypto.encrypt(openid))
    return True


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


def extract_response_sign_content(raw_text: str) -> Optional[str]:
    """从响应原文中提取待验签串：内层业务包裹体（xxx_response）的 JSON 子串。

    真实网关约定（线上取证）：响应外层只有业务包裹体与末尾 sign 字段，
    签名只覆盖内层包裹体本身。直接对原文切片而非解析后重序列化，
    避免重序列化引入的转义/空格差异导致验签失败。
    """
    sign_idx = raw_text.rfind('"sign"')
    if sign_idx <= 0:
        return None
    seg = raw_text[:sign_idx].rstrip()
    if seg.endswith(","):
        seg = seg[:-1].rstrip()
    if not (seg.startswith("{") and seg.endswith("}")):
        return None
    colon_idx = seg.find(":")
    if colon_idx < 0:
        return None
    inner = seg[colon_idx + 1 :].strip()
    if not (inner.startswith("{") and inner.endswith("}")):
        return None
    return inner


def extract_gateway_error(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """识别支付宝网关错误包裹体并转为结构化错误。

    错误响应包在 error_response 里（成功响应才是 alipay_xxx_response）；
    且真实网关对错误响应的签名无法用支付宝公钥验证（实测 344 字符非 2048 位
    RSA 签名长度），因此错误分支必须先于验签判定。
    """
    error_data = payload.get("error_response")
    if not isinstance(error_data, dict):
        return None
    return {
        "error": error_data.get("sub_code") or error_data.get("code") or "alipay_gateway_error",
        "error_description": error_data.get("sub_msg") or error_data.get("msg") or "Alipay gateway error",
    }


class AlipayOAuthService:
    """支付宝 OAuth 服务（请求需 RSA2 签名，响应使用支付宝公钥验签）。"""

    def __init__(self, app_id: str, private_key: str, public_key: str, sandbox: bool = False):
        self.app_id = app_id
        # 沙箱环境使用 openapi.alipaydev.com 网关，生产使用 openapi.alipay.com
        self.auth_url = (
            "https://openapi.alipaydev.com/gateway.do"
            if sandbox
            else "https://openapi.alipay.com/gateway.do"
        )
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
        """使用支付宝公钥验证响应签名：验签对象为内层包裹体（线上取证约定）。"""
        if self._public_key is None:
            return True
        sign = str(payload.get("sign") or "")
        if not sign:
            return False
        content = extract_response_sign_content(raw_text)
        if content is None:
            return False
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

        gateway_error = extract_gateway_error(payload)
        if gateway_error is not None:
            return gateway_error

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

        gateway_error = extract_gateway_error(payload)
        if gateway_error is not None:
            return gateway_error

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
        # 线上取证：应用开启 openid 配置后网关只回 open_id；登录链路只认 user_id，
        # 此处归一化（已有 user_id 时不覆盖，兼容旧约定）
        if not user_info.get("user_id") and user_info.get("open_id"):
            user_info["user_id"] = user_info["open_id"]
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
    def _allocate_username(db: Session, provider: str, raw_id: str) -> str:
        """为 OAuth 用户分配唯一用户名（P1-3.2：不再分配假邮箱）。

        P2-4.1：由 openid 的查找哈希派生，不再取明文后 12 位——username 随
        UserResponse 下发前端，用明文片段等于把 openid 大部分泄露出去。
        HMAC 片段不可反推，且同一 openid 仍稳定映射到同一 username。
        """
        base = f"{provider}_{get_openid_crypto().lookup_hash(raw_id)[:12]}".lower()
        candidate = base
        index = 1

        while db.query(User).filter(User.username == candidate).first():
            index += 1
            candidate = f"{base}_{index}"

        return candidate

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

        if _sync_openid(user, "alipay_openid", alipay_openid):
            changed = True

        if _sync_openid(user, "wechat_openid", wechat_openid):
            changed = True

        if _sync_openid(user, "wechat_unionid", wechat_unionid):
            changed = True

        if changed:
            db.add(user)
            db.commit()
            db.refresh(user)

        return user

    @staticmethod
    def create_confirmed_user(
        db: Session,
        provider: str,
        raw_id: str,
        full_name: str,
        avatar_url: Optional[str] = None,
        alipay_openid: Optional[str] = None,
        wechat_openid: Optional[str] = None,
        wechat_unionid: Optional[str] = None,
    ) -> User:
        """OAuth 建号确认入口（P1-3.2）：email=NULL，不分配假邮箱。

        先按 openid 查已有用户（并发双确认/历史建号兼容），命中则同步返回，
        避免唯一索引冲突或重复建号。
        """
        if alipay_openid:
            existing = _find_by_openid(db, "alipay_openid", alipay_openid)
            if existing:
                return existing
        if wechat_openid:
            existing = _find_by_openid(db, "wechat_openid", wechat_openid)
            if existing:
                return existing

        username = OAuthService._allocate_username(db, provider, raw_id)
        user = User(
            username=username,
            email=None,
            phone=None,
            password_hash=make_unusable_password_hash(),
            full_name=full_name,
            avatar_url=avatar_url,
            is_active=True,
        )
        _sync_openid(user, "alipay_openid", alipay_openid)
        _sync_openid(user, "wechat_openid", wechat_openid)
        _sync_openid(user, "wechat_unionid", wechat_unionid)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # P2-4.3：已被注销（冷静期）用户占用 openid 时不得回落登录，按冲突报错
            if alipay_openid:
                existing = _find_by_openid(db, "alipay_openid", alipay_openid)
                if existing and existing.deleted_at is None:
                    return existing
            if wechat_openid:
                existing = _find_by_openid(db, "wechat_openid", wechat_openid)
                if existing and existing.deleted_at is None:
                    return existing
            raise
        db.refresh(user)
        return user

    @staticmethod
    async def handle_alipay_login(db: Session, user_info: Dict[str, Any]) -> Optional[User]:
        """处理支付宝登录（P1-3.2：仅匹配已有用户，新用户返回 None 由路由发改号票据）。"""
        alipay_user_id = str(user_info.get("user_id") or "").strip()
        if not alipay_user_id:
            raise ValueError("Invalid Alipay user info")

        full_name = str(user_info.get("nick_name") or f"alipay_{alipay_user_id[-6:]}")

        user = _find_by_openid(db, "alipay_openid", alipay_user_id)
        # P2-4.3：已注销（冷静期）账户不通过 OAuth 重新登录，按新用户走建号流程
        if not user or user.deleted_at is not None:
            return None

        user = OAuthService._sync_external_user(
            db,
            user,
            full_name=full_name,
            alipay_openid=alipay_user_id,
        )

        return OAuthService._ensure_active(user)

    @staticmethod
    async def handle_wechat_login(
        db: Session,
        user_info: Dict[str, Any],
        openid: str,
        unionid: Optional[str] = None,
    ) -> Optional[User]:
        """处理微信登录（P1-3.2：unionid 优先匹配，命中后回写最新 openid）。"""
        openid = str(openid or "").strip()
        unionid = str(unionid or "").strip() or None
        if not openid:
            raise ValueError("Invalid WeChat user info")

        full_name = str(user_info.get("nickname") or f"wechat_{openid[-6:]}")
        avatar_url = user_info.get("headimgurl")

        user: Optional[User] = None
        if unionid:
            user = _find_by_openid(db, "wechat_unionid", unionid)
        if not user:
            user = _find_by_openid(db, "wechat_openid", openid)

        # P2-4.3：已注销（冷静期）账户不通过 OAuth 重新登录
        if not user or user.deleted_at is not None:
            return None

        user = OAuthService._sync_external_user(
            db,
            user,
            full_name=full_name,
            avatar_url=avatar_url,
            wechat_openid=openid,
            wechat_unionid=unionid,
        )

        return OAuthService._ensure_active(user)
