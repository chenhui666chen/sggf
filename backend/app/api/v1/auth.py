"""
认证 API 路由
"""
import hashlib
import json
import logging
import secrets
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import redis.exceptions
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.crypto import (
    OpenIDCryptoNotConfiguredError,
    OpenIDDecryptError,
    get_openid_crypto,
)
import app.core.security as core_security
from app.core.redis_client import LoopBoundRedis
from app.core.security import (
    INCR_WITH_TTL_LUA,
    build_token_response,
    clear_auth_cookies,
    create_access_token,
    create_csrf_token,
    csrf_claim_hash,
    get_current_user,
    has_usable_password_hash,
    hash_password,
    set_auth_cookies,
    verify_password,
    verify_token,
)
from app.db.base import get_db
from app.models.user import User
from app.schemas.user import (
    EMAIL_PATTERN,
    PHONE_PATTERN,
    EmailVerifyConfirmRequest,
    EmailVerifySendCodeRequest,
    BindConfirmRequest,
    ConsentAcceptance,
    LogoutRequest,
    OAuthCallbackResponse,
    OAuthConfirmRequest,
    OAuthConfirmResponse,
    PasswordChange,
    PasswordResetCodeRequest,
    PasswordResetCodeResponse,
    PasswordResetConfirm,
    PasswordSetRequest,
    PhoneBindConfirmRequest,
    PhoneCheckStatusRequest,
    PhoneSendCodeRequest,
    PhoneStatusResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RegisterConfirmRequest,
    RegisterSendCodeRequest,
    TokenResponse,
    UserLogin,
    UserResponse,
    build_user_response,
    mask_phone,
    VerificationCodeResponse,
    normalize_identity,
    normalize_optional_phone,
)
from app.services.email_service import (
    EmailDeliveryError,
    EmailService,
    EmailServiceNotConfiguredError,
)
from app.services.email_verification_service import EmailVerificationService
from app.services.oauth_service import (
    AlipayOAuthService,
    OAuthService,
    WechatOAuthService,
    _find_by_openid,
    _sync_openid,
)
from app.services.audit_log_service import (
    EVENT_BIND,
    EVENT_LOGIN,
    EVENT_LOGIN_FAILED,
    EVENT_LOGOUT,
    EVENT_OAUTH_LOGIN,
    EVENT_OAUTH_REGISTER,
    EVENT_PASSWORD_CHANGE,
    EVENT_PASSWORD_RESET,
    EVENT_PASSWORD_SET,
    EVENT_PHONE_BIND,
    EVENT_PHONE_TAKEOVER,
    EVENT_REFRESH,
    EVENT_REFRESH_FAILED,
    EVENT_REGISTER,
    EVENT_UNBIND,
    FAILURE_DISABLED,
    FAILURE_INVALID_PASSWORD,
    FAILURE_INVALID_REFRESH,
    FAILURE_LOCKED,
    FAILURE_NOT_FOUND,
    record_audit,
)
from app.services.password_history_service import password_history_service
from app.services.password_reset_service import PasswordResetService
from app.services.sms_service import (
    SmsDeliveryError,
    SmsService,
    SmsServiceNotConfiguredError,
)
from app.services.sms_verification_service import (
    SmsBudgetExhaustedError,
    SmsVerificationService,
)
from app.services.consent_service import (
    CONSENT_LABELS,
    CURRENT_CONSENT_VERSIONS,
    consent_service,
    sha256_content_hash,
)
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
password_reset_service = PasswordResetService()
password_reset_email_service = EmailService()
email_verification_service = EmailVerificationService()
email_verification_email_service = EmailService()
sms_service = SmsService()
sms_verification_service = SmsVerificationService()
phone_notice_email_service = EmailService()


class OAuthStateService:
    """OAuth state 服务端存储与原子消费（基于 Redis，fail-closed）。

    - state 由服务端生成并绑定 provider 与 redirect_uri；
    - callback 时一次性消费（GETDEL/Lua），校验失败同样删除，防重放；
    - Redis 不可用时返回 503，不静默降级为"不校验"。
    """

    STATE_TTL_SECONDS = 600

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = str(redis_url or settings.REDIS_URL).strip()
        self._redis = LoopBoundRedis(self.redis_url)

    async def _get_redis_client(self):
        return await self._redis.get()

    @staticmethod
    def _key(state: str) -> str:
        return f"oauth:state:{state}"

    async def store(
        self,
        state: str,
        provider: str,
        redirect_uri: str,
        ttl: int = STATE_TTL_SECONDS,
        extra: Optional[dict] = None,
    ) -> None:
        """存储 state，绑定 provider 与 redirect_uri。Redis 不可用返回 503。

        extra（如 P2-4.2 的 intent / user_id）会并入 payload，callback 消费时一并带回。
        """
        try:
            client = await self._get_redis_client()
            payload = {"provider": provider, "redirect_uri": redirect_uri}
            if extra:
                payload.update(extra)
            await client.setex(
                self._key(state),
                ttl,
                json.dumps(payload),
            )
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("OAuth state 存储失败（Redis 不可用）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def consume(self, state: str, expected_provider: str) -> Dict[str, Any]:
        """原子消费并校验 state。失败也删除（一次性）。Redis 不可用返回 503。

        兼容路径与 refresh/pending 同构：仅当 Redis 不支持 GETDEL 命令（< 6.2 返回含
        "unknown command" 的 ResponseError）时回退 Lua 原子 GET+DEL；其余服务端错误
        （WRONGTYPE/OOM 等）与连接失败/超时/认证等异常一律向外抛 -> 503（fail-closed），
        不得把真实 Redis 故障误判为"无效的登录状态"（用户需重新发起授权）。
        """
        key = self._key(state)
        try:
            client = await self._get_redis_client()
            try:
                raw = await client.getdel(key)  # Redis 6.2+
            except redis.exceptions.ResponseError as exc:
                # 只认"命令不支持"（旧版带 "ERR" 前缀，统一按子串小写匹配）；
                # 其余 ResponseError 原样抛出 -> 503，不走 Lua 回退
                if "unknown command" not in str(exc).lower():
                    raise
                raw = await client.eval(
                    "local v = redis.call('GET', KEYS[1]); redis.call('DEL', KEYS[1]); return v",
                    1,
                    key,
                )
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("OAuth state 消费失败（Redis 不可用）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

        if not raw:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的登录状态，请重新发起",
            )

        payload = json.loads(raw)
        if payload.get("provider") != expected_provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="登录提供方不匹配",
            )
        return payload


oauth_state_service = OAuthStateService()


class AuthRateLimiterService:
    """认证端点限流（Redis 计数 + TTL，fail-closed，P1-3.1）。

    - Lua 保证 INCR 与首次 EXPIRE 原子；
    - 超过阈值抛 429；Redis 不可用抛 503（不静默放行，否则限流形同虚设）；
    - 账号维限流由路由函数在 Pydantic 解析后调用（账号哈希做 key），
      不在中间件层读 body（避免二次解析与 Starlette 行为差异）。
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = str(redis_url or settings.REDIS_URL).strip()
        self._redis = LoopBoundRedis(self.redis_url)

    async def _get_redis_client(self):
        return await self._redis.get()

    async def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        """计数并校验，超过 limit 抛 429；Redis 不可用抛 503。"""
        try:
            client = await self._get_redis_client()
            count = await client.eval(INCR_WITH_TTL_LUA, 1, key, window_seconds)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("认证限流 Redis 不可用（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

        if int(count) > int(limit):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="请求过于频繁，请稍后重试",
            )


auth_rate_limiter = AuthRateLimiterService()


class OAuthCodeGuard:
    """OAuth 授权码换票锁（Redis SET NX，P1-3.1）。

    - 换票前获取 30 秒短锁，防并发双换票（code 在支付宝/微信侧换一次即作废）；
    - 换票成功或确认 code 已被消费 -> 落 code_used 标记（10 分钟）；
    - 网络/签名/其他错误释放锁，允许用户重试。
    """

    LOCK_TTL_SECONDS = 30
    USED_TTL_SECONDS = 600

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = str(redis_url or settings.REDIS_URL).strip()
        self._redis = LoopBoundRedis(self.redis_url)

    async def _get_redis_client(self):
        return await self._redis.get()

    @staticmethod
    def _hash(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _lock_key(code_hash: str) -> str:
        return f"oauth:code_lock:{code_hash}"

    @staticmethod
    def _used_key(code_hash: str) -> str:
        return f"oauth:code_used:{code_hash}"

    async def acquire(self, code: str) -> str:
        """换票前获取短锁，返回 code_hash 供后续使用；已被使用抛 400。"""
        code_hash = self._hash(code)
        try:
            client = await self._get_redis_client()
            if await client.exists(self._used_key(code_hash)):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="授权码已被使用",
                )
            acquired = await client.set(
                self._lock_key(code_hash), "1", nx=True, ex=self.LOCK_TTL_SECONDS
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("OAuth code 换票锁 Redis 不可用（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

        if not acquired:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="授权码已被使用",
            )
        return code_hash

    async def mark_used(self, code_hash: str) -> None:
        """换票成功（或确认 code 已被消费）后标记，并清除短锁。"""
        try:
            client = await self._get_redis_client()
            await client.set(
                self._used_key(code_hash), "1", nx=True, ex=self.USED_TTL_SECONDS
            )
            await client.delete(self._lock_key(code_hash))
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("OAuth code 标记失败（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def release(self, code_hash: str) -> None:
        """换票失败（网络/签名类错误）时释放锁，允许用户重试。"""
        try:
            client = await self._get_redis_client()
            await client.delete(self._lock_key(code_hash))
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("OAuth code 锁释放失败: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc


oauth_code_guard = OAuthCodeGuard()


class OAuthPendingRegistrationService:
    """OAuth 首次建号票据（Redis 存储与原子消费，fail-closed，P1-3.2）。

    - callback 识别新用户后，将身份信息（openid 等）存入 Redis，仅返回不透明票据；
      openid 不进浏览器，票据本身不携带身份信息；
    - /oauth/confirm 一次性消费（GETDEL/Lua），防并发双建号与重放；
    - Redis 不可用时返回 503，不静默降级为自动建号（否则确认页形同虚设）。
    """

    TICKET_TTL_SECONDS = 600

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = str(redis_url or settings.REDIS_URL).strip()
        self._redis = LoopBoundRedis(self.redis_url)

    async def _get_redis_client(self):
        return await self._redis.get()

    @staticmethod
    def _key(ticket: str) -> str:
        return f"oauth:pending:{ticket}"

    async def store(self, payload: Dict[str, Any], ttl: int = TICKET_TTL_SECONDS) -> str:
        """存储待建号身份信息，返回不透明票据。Redis 不可用返回 503。"""
        ticket = secrets.token_urlsafe(32)
        try:
            client = await self._get_redis_client()
            await client.setex(
                self._key(ticket), ttl, json.dumps(payload, ensure_ascii=False)
            )
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("OAuth 建号票据存储失败（Redis 不可用）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc
        return ticket

    async def consume(self, ticket: str) -> Optional[Dict[str, Any]]:
        """原子消费票据（读到即删除）；不存在/已过期返回 None。Redis 不可用返回 503。

        兼容路径与 refresh 同构：仅当 Redis 不支持 GETDEL 命令（< 6.2 返回含
        "unknown command" 的 ResponseError）时回退 Lua 原子 GET+DEL；其余服务端
        错误（WRONGTYPE/OOM 等）与连接失败/超时/认证等异常一律向外抛 -> 503
        （fail-closed），不得把真实 Redis 故障误判为"票据过期"（用户会被卡在确认页）。
        """
        key = self._key(ticket)
        try:
            client = await self._get_redis_client()
            try:
                raw = await client.getdel(key)  # Redis 6.2+
            except redis.exceptions.ResponseError as exc:
                # 只认"命令不支持"（旧版带 "ERR" 前缀，统一按子串小写匹配）；
                # 其余 ResponseError 原样抛出 -> 503，不走 Lua 回退
                if "unknown command" not in str(exc).lower():
                    raise
                raw = await client.eval(
                    "local v = redis.call('GET', KEYS[1]); redis.call('DEL', KEYS[1]); return v",
                    1,
                    key,
                )
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("OAuth 建号票据消费失败（Redis 不可用）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

        if not raw:
            return None
        return json.loads(raw)

    async def restore(
        self,
        ticket: str,
        payload: Dict[str, Any],
        ttl: int = TICKET_TTL_SECONDS,
    ) -> None:
        """建号失败时写回票据（NX：不覆盖并发已消费/更新的票据），让用户可重试。

        与 refresh 的 restore 同构：确认建号在 GETDEL 消费之后才执行，若建号或签发
        token 失败票据已丢，用户只能重走 OAuth；此处把票据写回（带原 TTL）。
        """
        try:
            client = await self._get_redis_client()
            await client.set(
                self._key(ticket),
                json.dumps(payload, ensure_ascii=False),
                nx=True,
                ex=ttl,
            )
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("OAuth 建号票据写回失败（Redis 不可用）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc


oauth_pending_registration = OAuthPendingRegistrationService()


def _require_consents(
    consent: Optional[ConsentAcceptance], required: list[str]
) -> dict[str, str]:
    """校验必需同意项已勾选且版本为当前版本（P2-5.2）。

    必须在**建号/绑定之前**调用：未勾选不处理个人信息，直接 400。
    返回 {同意类型: 用户勾选的版本} 供后续落库，只记录用户真实勾选的项。
    """
    accepted = consent or ConsentAcceptance()
    resolved: dict[str, str] = {}
    for consent_type in required:
        version = getattr(accepted, consent_type, None)
        label = CONSENT_LABELS.get(consent_type, consent_type)
        if not version:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"请先阅读并勾选{label}",
            )
        if version != CURRENT_CONSENT_VERSIONS.get(consent_type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{label}条款已更新，请重新勾选同意",
            )
        resolved[consent_type] = version
    return resolved


def _client_ip(request: Request) -> str:
    """提取客户端真实 IP（限流 key 用）。

    优先读 nginx 设置的 X-Real-IP（proxy_set_header X-Real-IP $remote_addr 强制覆盖，
    不可被客户端伪造）：反代后 request.client.host 是容器/内网 IP，IP 维限流会全站共桶。
    无该头（开发/测试直连）时回退 socket 地址。
    注意：后端端口不得绕过 nginx 对公网暴露，否则此头可被伪造。
    """
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _account_hash(identifier: str) -> str:
    """账号哈希做限流 key（不落明文账号，降低 Redis 泄露时的隐私暴露面）。"""
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]


def _audit_record(
    db: Session,
    *,
    event_type: str,
    request: Request,
    user_id: Optional[int] = None,
    provider: Optional[str] = None,
    success: bool = True,
    failure_reason: Optional[str] = None,
) -> None:
    """审计埋点助手（P2-4.4）：统一从 Request 提取 IP/UA 并转哈希，失败原因只存类别。"""
    record_audit(
        db,
        event_type=event_type,
        user_id=user_id,
        provider=provider,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        success=success,
        failure_reason=failure_reason,
    )


# 时序防护：登录失败路径执行一次真实 bcrypt verify，消除账号存在与否的响应时间差异
_DUMMY_PASSWORD = "timing-constant-dummy"
_DUMMY_BCRYPT_HASH: Optional[str] = None


def initialize_security_globals() -> None:
    """应用启动时预生成时序防护用 dummy bcrypt 哈希（避免运行时首次生成阻塞）。"""
    global _DUMMY_BCRYPT_HASH
    if _DUMMY_BCRYPT_HASH is None:
        _DUMMY_BCRYPT_HASH = hash_password(_DUMMY_PASSWORD)


def _verify_with_timing_guard() -> None:
    """执行一次真实 bcrypt 校验，用于账号不存在时的时序防护。"""
    global _DUMMY_BCRYPT_HASH
    if _DUMMY_BCRYPT_HASH is None:
        _DUMMY_BCRYPT_HASH = hash_password(_DUMMY_PASSWORD)
    verify_password(_DUMMY_PASSWORD, _DUMMY_BCRYPT_HASH)


def _validate_redirect_uri(redirect_uri: str) -> None:
    """精确校验 OAuth 回调地址是否在白名单内。"""
    parsed = urlparse(redirect_uri)

    # 生产/staging 仅允许 HTTPS；开发环境允许精确的 localhost HTTP 项
    if settings.APP_ENV in ("production", "staging"):
        if parsed.scheme != "https":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="回调地址必须使用 HTTPS",
            )

    # 禁止 userinfo、query、fragment 注入
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="无效的回调地址")
    if parsed.query or parsed.fragment:
        raise HTTPException(status_code=400, detail="回调地址不得携带查询参数或片段")

    whitelist = set(settings.OAUTH_REDIRECT_URI_WHITELIST or [])
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if normalized not in whitelist:
        raise HTTPException(status_code=400, detail="无效的回调地址")

    # 防御 lookalike 域名（如 your-domain.com.evil.com）
    allowed_hosts = {urlparse(u).netloc for u in whitelist}
    if parsed.netloc not in allowed_hosts:
        raise HTTPException(status_code=400, detail="无效的回调地址")


class OAuthCallbackRequest(BaseModel):
    """OAuth 回调请求。

    state 字段保留 Optional，但后端强制校验非空（缺失返回 400 而非 422，
    错误语义统一为"无效的登录状态"，与 state 不匹配一致）。
    """

    code: str
    state: Optional[str] = None


class AlipayAuthUrlRequest(BaseModel):
    """支付宝授权地址请求。"""

    redirect_uri: str
    state: Optional[str] = None
    # P2-4.2：login=普通登录/首次建号；bind=已登录用户绑定第三方登录
    intent: str = "login"


class WechatAuthUrlRequest(BaseModel):
    """微信授权地址请求。"""

    redirect_uri: str
    state: Optional[str] = None
    intent: str = "login"


def _normalize_username(value: str) -> str:
    return value.strip()


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _normalize_phone(value: Optional[str]) -> Optional[str]:
    return normalize_optional_phone(value)


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


def _build_password_reset_code_response(*, message: str) -> dict:
    return {
        "message": message,
        "expires_in": settings.PASSWORD_RESET_CODE_TTL_SECONDS,
        "resend_in": settings.PASSWORD_RESET_RESEND_INTERVAL_SECONDS,
    }


def _build_verification_code_response(*, message: str) -> dict:
    return {
        "message": message,
        "expires_in": settings.EMAIL_VERIFY_CODE_TTL_SECONDS,
        "resend_in": settings.EMAIL_VERIFY_RESEND_INTERVAL_SECONDS,
    }


def _email_verify_code_sent_message() -> str:
    return "验证码已发送到您的邮箱，请注意查收"


def _sms_code_sent_message() -> str:
    return "验证码已发送到您的手机，请注意查收"


def _build_sms_code_response(*, message: str) -> dict:
    return {
        "message": message,
        "expires_in": settings.SMS_VERIFY_CODE_TTL_SECONDS,
        "resend_in": settings.SMS_VERIFY_RESEND_INTERVAL_SECONDS,
    }


def _password_reset_request_sms_message() -> str:
    return "如果账号存在且已绑定本地密码，验证码将发送到绑定手机号"


async def _notify_phone_takeover(previous_owner: User, phone: str) -> None:
    """手机号申诉接管后通知原主人（尽力而为：邮件未配置/发送失败不阻塞流程）。

    抢占本身已由短信验码证明号码持有权，通知失败只影响知情权，不回滚转移。
    """
    if not previous_owner.email:
        logger.warning("手机号被接管但原主人无邮箱，无法邮件通知")
        return
    if not phone_notice_email_service.is_configured():
        return
    try:
        await phone_notice_email_service.send_phone_unbind_notice(previous_owner.email, mask_phone(phone))
    except Exception:  # noqa: BLE001
        logger.warning("发送手机号解绑通知邮件失败（忽略，接管已生效）")


def _resolve_intent_state(intent: str, current_user: Optional[User]) -> Optional[dict]:
    """校验 OAuth auth-url 的 intent 并返回 state 附加字段（P2-4.2）。

    intent=bind 必须登录态（在 auth-url 就 401，避免用户走完授权才发现没登录）；
    state 里绑定的 user_id 只当线索，最终鉴权在登录态 /auth/bind/confirm。
    """
    normalized = str(intent or "login").strip().lower()
    if normalized not in ("login", "bind"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的授权意图")
    if normalized == "bind":
        if current_user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
        return {"intent": "bind", "user_id": current_user.id}
    return {"intent": "login"}


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


def _ensure_openid_crypto() -> None:
    """openid 加密存储未配置时 fail-closed 503，不退回明文处理（P2-4.1）。"""
    try:
        get_openid_crypto()
    except OpenIDCryptoNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="第三方登录尚未完成服务端配置",
        ) from exc


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


@router.post("/register/send-code", response_model=VerificationCodeResponse)
async def register_send_code(
    payload: RegisterSendCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """注册第一步：发送邮箱验证码（P1-3.8 两步注册）。

    防枚举：不区分邮箱是否已注册，统一 200 同文案（冲突延迟到建号阶段统一文案拒绝）；
    已注册邮箱直接跳过发码（不发信），消除对已有用户的邮件轰炸/钓鱼面。
    限流：IP 维防脚本刷接口，邮箱哈希维防对单一邮箱邮件轰炸。
    """
    await auth_rate_limiter.check(
        f"rate:register:ip:{_client_ip(request)}",
        settings.AUTH_RATE_LIMIT_REGISTER_PER_MINUTE,
    )
    await auth_rate_limiter.check(
        f"rate:register:email:{_account_hash(payload.email)}",
        settings.AUTH_RATE_LIMIT_REGISTER_PER_MINUTE,
    )

    if not settings.DEBUG and not email_verification_email_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="注册邮件服务尚未完成服务端配置",
        )

    # 防枚举 + 防邮件轰炸：已注册邮箱不再真实发码（响应仍统一 200 同文案）
    if (
        db.query(User)
        .filter(func.lower(User.email) == str(payload.email).lower())
        .first()
    ):
        return _build_verification_code_response(message=_email_verify_code_sent_message())

    code = await email_verification_service.issue_code(payload.email)
    if code is None:
        # 重发间隔内：不重发也不报错，统一文案（防探测重发间隔）
        return _build_verification_code_response(message=_email_verify_code_sent_message())

    try:
        await email_verification_email_service.send_email_verification_code(payload.email, code)
    except EmailServiceNotConfiguredError as exc:
        await email_verification_service.delete_code(payload.email)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="注册邮件服务尚未完成服务端配置",
        ) from exc
    except EmailDeliveryError as exc:
        await email_verification_service.delete_code(payload.email)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="验证码发送失败，请稍后重试",
        ) from exc

    return _build_verification_code_response(message=_email_verify_code_sent_message())


@router.post("/register/confirm", response_model=TokenResponse)
async def register_confirm(
    user_data: RegisterConfirmRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """注册第二步：验证邮箱验证码并建号（P1-3.8：建号即 email_verified=True）。

    所有冲突场景统一返回相同文案，避免账号枚举（PIPL 合规）。
    """
    await auth_rate_limiter.check(
        f"rate:register:ip:{_client_ip(request)}",
        settings.AUTH_RATE_LIMIT_REGISTER_PER_MINUTE,
    )

    normalized_username = _normalize_username(user_data.username)
    normalized_email = _normalize_email(str(user_data.email))
    normalized_phone = _normalize_phone(user_data.phone)

    # P2-5.2：未勾选同意不得处理个人信息——在建号与任何库查询之前拒绝
    # 合规修订：注册/建号须同时确认 privacy_policy 与"年满 14 周岁"声明（age_eligibility）
    required_consents = ["privacy_policy", "age_eligibility"]
    if normalized_phone:
        required_consents.append("phone_collection")
    accepted_consents = _require_consents(user_data.consent, required_consents)

    is_valid = await email_verification_service.verify_code(normalized_email, user_data.code)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码无效或已过期",
        )

    if db.query(User).filter(func.lower(User.email) == normalized_email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="注册失败，请检查输入信息",
        )

    # 手机号被占用：必须提供申诉验证码才能抢占（验码后原主人清空手机号并收邮件通知）；
    # 无验证码一律统一文案拒绝（与其余冲突场景同语义，防账号枚举）
    phone_previous_owner: Optional[User] = None
    if normalized_phone:
        phone_previous_owner = db.query(User).filter(User.phone == normalized_phone).first()
        if phone_previous_owner:
            if not user_data.phone_code:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="注册失败，请检查输入信息",
                )
            is_phone_valid = await sms_verification_service.verify_code(
                "takeover", normalized_phone, user_data.phone_code
            )
            if not is_phone_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="注册失败，请检查输入信息",
                )
            phone_previous_owner.phone = None
            db.add(phone_previous_owner)

    if db.query(User).filter(User.username == normalized_username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="注册失败，请检查输入信息",
        )

    user = User(
        username=normalized_username,
        email=normalized_email,
        phone=normalized_phone,
        password_hash=hash_password(user_data.password),
        full_name=normalized_username,
        email_verified=True,  # 两步注册：验码通过即邮箱所有权已证明
        email_verified_at=utc_now(),
    )

    db.add(user)
    db.flush()  # 先取 id：密码历史与建号同事务写入（P2-4.6）
    password_history_service.record(db, user.id, user_data.password)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="注册失败，请检查输入信息",
        )
    db.refresh(user)

    # P2-5.2：只记录用户真实勾选的同意项（未勾选的项不留痕）
    for consent_type, version in accepted_consents.items():
        consent_service.record_accepted(
            db,
            user=user,
            consent_type=consent_type,
            version=version,
            ip=_client_ip(request),
        )
    _audit_record(db, event_type=EVENT_REGISTER, request=request, user_id=user.id)

    # 手机号抢占生效后的审计与通知（建号已提交，通知失败不回滚）
    if phone_previous_owner is not None:
        _audit_record(db, event_type=EVENT_PHONE_TAKEOVER, request=request, user_id=user.id)
        await _notify_phone_takeover(phone_previous_owner, normalized_phone)

    payload = await build_token_response(user)
    set_auth_cookies(
        response,
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        csrf_token=payload["csrf_token"],
    )
    return payload


@router.post("/phone/check-status", response_model=PhoneStatusResponse)
async def phone_check_status(
    payload: PhoneCheckStatusRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """手机号占用状态查询（注册/用户中心绑定前置：判断是否需要申诉验码）。

    只回布尔值，不暴露占用者任何身份信息。
    """
    await auth_rate_limiter.check(
        f"rate:sms:ip:{_client_ip(request)}",
        settings.AUTH_RATE_LIMIT_REGISTER_PER_MINUTE,
    )

    occupied = db.query(User).filter(User.phone == payload.phone).first() is not None
    return PhoneStatusResponse(occupied=occupied)


@router.post("/phone/send-code", response_model=VerificationCodeResponse)
async def phone_send_code(
    payload: PhoneSendCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """发送手机号验证码（注册申诉抢占 / 用户中心绑定）。防滥用五层：

    1. 流程过滤：未占用号码不发短信（随机探测不消耗短信）；
    2. 号码/IP 维限流：每分钟 + 每日上限（防单号轰炸与换号刷接口）；
    3. 重发间隔：间隔内不重发也不报错，统一文案（防探测）；
    4. 全局日预算熔断：成本封顶；
    5. 验码阶段尝试上限（SmsVerificationService）。
    """
    await auth_rate_limiter.check(
        f"rate:sms:ip:{_client_ip(request)}",
        settings.AUTH_RATE_LIMIT_REGISTER_PER_MINUTE,
    )
    await auth_rate_limiter.check(
        f"rate:sms:phone:{_account_hash(payload.phone)}",
        settings.AUTH_RATE_LIMIT_REGISTER_PER_MINUTE,
    )
    await auth_rate_limiter.check(
        f"rate:sms:daily:ip:{_client_ip(request)}",
        settings.SMS_DAILY_LIMIT_PER_IP,
        window_seconds=86400,
    )
    await auth_rate_limiter.check(
        f"rate:sms:daily:phone:{_account_hash(payload.phone)}",
        settings.SMS_DAILY_LIMIT_PER_PHONE,
        window_seconds=86400,
    )

    if not settings.DEBUG and not sms_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="短信服务尚未完成服务端配置",
        )

    # 第一层流程过滤：未占用号码不发短信（申诉/绑定只针对已被绑定的号码）
    if db.query(User).filter(User.phone == payload.phone).first() is None:
        return _build_sms_code_response(message=_sms_code_sent_message())

    code = await sms_verification_service.issue_code(payload.purpose, payload.phone)
    if code is None:
        # 重发间隔内：不重发也不报错，统一文案（防探测重发间隔）
        return _build_sms_code_response(message=_sms_code_sent_message())

    try:
        await sms_verification_service.reserve_budget()
    except SmsBudgetExhaustedError:
        await sms_verification_service.delete_code(payload.purpose, payload.phone)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="验证码发送失败，请稍后重试",
        )

    try:
        await sms_service.send_verification_code(payload.phone, code)
    except SmsServiceNotConfiguredError as exc:
        await sms_verification_service.delete_code(payload.purpose, payload.phone)
        await sms_verification_service.release_budget()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="短信服务尚未完成服务端配置",
        ) from exc
    except SmsDeliveryError as exc:
        await sms_verification_service.delete_code(payload.purpose, payload.phone)
        await sms_verification_service.release_budget()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="验证码发送失败，请稍后重试",
        ) from exc

    return _build_sms_code_response(message=_sms_code_sent_message())


@router.post("/phone/bind-confirm", response_model=UserResponse)
async def phone_bind_confirm(
    payload: PhoneBindConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用户中心绑定/换绑手机号（登录态），与注册流程同逻辑：

    号码未被占用 → 直接绑定（不消耗短信）；
    号码已被他人占用 → 申诉抢占：必须短信验码证明持有权，原主人手机号清空（其余凭证保留）+ 邮件通知。
    收集手机号须勾选 phone_collection 同意。
    """
    normalized_phone = _normalize_phone(payload.phone)
    accepted_consents = _require_consents(payload.consent, ["phone_collection"])

    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    if user.phone == normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该手机号已绑定当前账号",
        )

    previous_owner = (
        db.query(User)
        .filter(User.phone == normalized_phone, User.id != user.id)
        .first()
    )
    if previous_owner:
        # 申诉抢占：短信验码证明号码持有权（code 与 purpose=bind 的发码配套）
        is_valid = await sms_verification_service.verify_code("bind", normalized_phone, payload.code)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="验证码无效或已过期",
            )
        previous_owner.phone = None
        db.add(previous_owner)

    user.phone = normalized_phone
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # 并发竞态兜底：UNIQUE 冲突统一文案，不暴露占用者信息
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该手机号已被占用",
        )

    for consent_type, version in accepted_consents.items():
        consent_service.record_accepted(
            db,
            user=user,
            consent_type=consent_type,
            version=version,
            ip=_client_ip(request),
        )
    if previous_owner:
        _audit_record(db, event_type=EVENT_PHONE_TAKEOVER, request=request, user_id=user.id)
        await _notify_phone_takeover(previous_owner, normalized_phone)
    _audit_record(db, event_type=EVENT_PHONE_BIND, request=request, user_id=user.id)

    db.refresh(user)
    return build_user_response(user)


@router.post("/verify-email/request-code", response_model=VerificationCodeResponse)
async def verify_email_request_code(
    payload: EmailVerifySendCodeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """登录态邮箱验证第一步（P1-3.8：验证/换绑邮箱）：发送验证码。

    防枚举：不区分目标邮箱是否已被占用，统一 200 同文案，冲突在确认阶段统一文案拒绝。
    """
    await auth_rate_limiter.check(
        f"rate:emailverify:ip:{_client_ip(request)}",
        settings.AUTH_RATE_LIMIT_REGISTER_PER_MINUTE,
    )
    await auth_rate_limiter.check(
        f"rate:emailverify:email:{_account_hash(payload.email)}",
        settings.AUTH_RATE_LIMIT_REGISTER_PER_MINUTE,
    )

    if not settings.DEBUG and not email_verification_email_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="邮箱验证邮件服务尚未完成服务端配置",
        )

    code = await email_verification_service.issue_code(payload.email)
    if code is None:
        return _build_verification_code_response(message=_email_verify_code_sent_message())

    try:
        await email_verification_email_service.send_email_verification_code(payload.email, code)
    except EmailServiceNotConfiguredError as exc:
        await email_verification_service.delete_code(payload.email)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="邮箱验证邮件服务尚未完成服务端配置",
        ) from exc
    except EmailDeliveryError as exc:
        await email_verification_service.delete_code(payload.email)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="验证码发送失败，请稍后重试",
        ) from exc

    return _build_verification_code_response(message=_email_verify_code_sent_message())


@router.post("/verify-email/confirm")
async def verify_email_confirm(
    payload: EmailVerifyConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """登录态邮箱验证第二步：验码后绑定邮箱并置已验证。

    冲突统一文案，不暴露占用者身份。
    """
    normalized_email = _normalize_email(str(payload.email))

    is_valid = await email_verification_service.verify_code(normalized_email, payload.code)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码无效或已过期",
        )

    occupied = (
        db.query(User)
        .filter(func.lower(User.email) == normalized_email, User.id != current_user.id)
        .first()
    )
    if occupied:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱验证失败，请检查输入信息",
        )

    current_user.email = normalized_email
    current_user.email_verified = True
    current_user.email_verified_at = utc_now()
    merged = db.merge(current_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱验证失败，请检查输入信息",
        )
    # commit 默认过期所有属性；会话关闭前重新加载（含 roles 等关系），
    # 避免 expunge 后实例在响应序列化时触发惰性加载失败（DetachedInstanceError）
    db.refresh(merged)

    return {"message": "邮箱验证成功"}


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """用户登录，支持用户名、邮箱或手机号。

    所有失败场景（账号不存在/密码错误/第三方账户）统一返回 401 同文案，
    并对不存在账号执行一次真实 bcrypt 校验以消除时序差异（防账号枚举）。
    限流（P1-3.1）：IP 维防撞库扫描，账号维防单账号暴力破解。
    """
    await auth_rate_limiter.check(
        f"rate:login:ip:{_client_ip(request)}",
        settings.AUTH_RATE_LIMIT_LOGIN_IP_PER_MINUTE,
    )
    # 账号维 key 先规范化（与 _find_user_by_identifier 同口径）：
    # 否则 alice@x.com / ALICE@x.com 大小写变体会打进不同桶，账号维限流可被绕过
    account_identity = normalize_identity(credentials.username)
    account_key = _account_hash(account_identity)
    await auth_rate_limiter.check(
        f"rate:login:account:{account_key}",
        settings.AUTH_RATE_LIMIT_LOGIN_ACCOUNT_PER_MINUTE,
    )

    # 账户锁定（P2-4.6）：与 3.1 限流独立 key；锁定窗口内的响应语义见下方锁定分支
    locked = await core_security.account_lockout_service.is_locked(account_key)

    user = _find_user_by_identifier(db, credentials.username)

    if not user:
        _verify_with_timing_guard()
        _audit_record(
            db,
            event_type=EVENT_LOGIN_FAILED,
            request=request,
            success=False,
            failure_reason=FAILURE_NOT_FOUND,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名、邮箱、手机号或密码错误",
        )

    # P2-4.3：已注销账户视同不存在（静默 401，不泄露注销状态）
    if user.deleted_at is not None:
        _verify_with_timing_guard()
        _audit_record(
            db,
            event_type=EVENT_LOGIN_FAILED,
            request=request,
            user_id=user.id,
            success=False,
            failure_reason=FAILURE_NOT_FOUND,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名、邮箱、手机号或密码错误",
        )

    # 第三方账户（password_hash=!oauth-disabled!）在此同样返回 False → 401，不泄露账户类型
    if not verify_password(credentials.password, user.password_hash):
        # 仅"存在 + 有可用密码 + 密码错误"计入锁定（P2-4.6）：
        # OAuth 账户与不存在账号不计数；锁定窗口内失败不续期（避免"永久锁"）
        if not locked and has_usable_password_hash(user.password_hash):
            await core_security.account_lockout_service.register_failure(account_key)
        _audit_record(
            db,
            event_type=EVENT_LOGIN_FAILED,
            request=request,
            user_id=user.id,
            success=False,
            failure_reason=(
                FAILURE_LOCKED if locked else FAILURE_INVALID_PASSWORD
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名、邮箱、手机号或密码错误",
        )

    if locked:
        # 锁定窗口内正确密码同样 401 统一文案（D1 静默 401）：
        # 若放行正确密码，锁定对爆破零增益（第 6 次起命中即进），退化为 3.1 的重复实现；
        # 拒绝也保持同一文案/状态码，攻击者无法借此区分"锁定/密码错误/账号不存在"
        _audit_record(
            db,
            event_type=EVENT_LOGIN_FAILED,
            request=request,
            user_id=user.id,
            success=False,
            failure_reason=FAILURE_LOCKED,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名、邮箱、手机号或密码错误",
        )

    if not user.is_active:
        _audit_record(
            db,
            event_type=EVENT_LOGIN_FAILED,
            request=request,
            user_id=user.id,
            success=False,
            failure_reason=FAILURE_DISABLED,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户账户已被禁用",
        )

    # 成功登录即证明持有密码：清空失败计数与锁定标记
    await core_security.account_lockout_service.clear(account_key)

    _audit_record(
        db,
        event_type=EVENT_LOGIN,
        request=request,
        user_id=user.id,
    )

    payload = await build_token_response(user)
    # P2-4.5：access/refresh/csrf 三 cookie 落盘（httpOnly），前端零持久化
    core_security.set_auth_cookies(
        response,
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        csrf_token=payload["csrf_token"],
    )
    return payload


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    payload: RefreshTokenRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """refresh token 轮换（P1-3.7 + P2-4.5）。

    流程（与架构文档 3.7 方案一致）：
    1. 短锁（SET NX EX 5）拦并发刷新；
    2. GETDEL 原子消费旧 refresh（读到即删除，重放即 401）；
    3. 校验用户存在/未禁用/tv 一致（改密/重置/禁用后 refresh 全部失效）；
    4. 签发新 access（短 TTL）+ 新 refresh；
    5. 签发侧失败（非 401）时 NX 写回旧值，用户可重试不掉线。

    P2-4.5：refresh token 优先取 httpOnly cookie（前端不再持有原始值），
    body 兜底兼容既有调用；新令牌与 csrf 一并写回 cookie。
    """
    refresh_token_value = str(payload.refresh_token or "").strip() or request.cookies.get(
        core_security.refresh_cookie_name()
    )
    # 缺 cookie 且 body 为空：直接 401，不打 Redis（避免无谓抢锁与 fail-closed 噪音）
    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态已失效，请重新登录",
        )

    if not await core_security.refresh_token_service.acquire_lock(refresh_token_value):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="刷新过于频繁，请稍后重试",
        )

    raw = None
    try:
        raw = await core_security.refresh_token_service.consume(refresh_token_value)
        if not raw:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录状态已失效，请重新登录",
            )

        data = json.loads(raw)
        user = db.query(User).filter(User.id == int(data["user_id"])).first()
        # P2-4.3：已注销账户的 refresh 一律失效（视同不存在）
        if (
            not user
            or not user.is_active
            or user.deleted_at is not None
            or int(data.get("tv", 0)) != int(user.token_version or 1)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录状态已失效，请重新登录",
            )

        new_refresh = await core_security.refresh_token_service.issue(
            user.id, user.token_version
        )
        csrf_token = create_csrf_token()
        access_token = create_access_token(
            data={
                "sub": str(user.id),
                "tv": user.token_version,
                "csrf": csrf_claim_hash(csrf_token),
            }
        )
        set_auth_cookies(
            response,
            access_token=access_token,
            refresh_token=new_refresh,
            csrf_token=csrf_token,
        )
        _audit_record(db, event_type=EVENT_REFRESH, request=request, user_id=user.id)
        # P2-4.5 收尾：新令牌已由 set_auth_cookies 写入 httpOnly cookie，body 不返回
        return {"message": "刷新成功"}
    except HTTPException as exc:
        # 401（无效/失效 token）不写回：重放攻击不得复活旧值；
        # 其余失败（如签发路径 503）写回旧值（NX，不覆盖并发新值）让用户可重试
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            _audit_record(
                db,
                event_type=EVENT_REFRESH_FAILED,
                request=request,
                user_id=user.id if "user" in locals() and user else None,
                success=False,
                failure_reason=FAILURE_INVALID_REFRESH,
            )
        if exc.status_code != status.HTTP_401_UNAUTHORIZED and raw is not None:
            await core_security.refresh_token_service.restore(refresh_token_value, raw)
        raise
    finally:
        await core_security.refresh_token_service.release_lock(refresh_token_value)


@router.post("/reset-password/request-code", response_model=PasswordResetCodeResponse)
async def request_password_reset_code(
    payload: PasswordResetCodeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """发送找回密码验证码（双重找回：邮箱通道 + 手机号短信通道）。

    通道按输入类型分流：手机号→短信，邮箱/用户名→邮件。
    限流（P1-3.1）：账号维防对同一账号邮件/短信轰炸；IP 维防随机账号刷接口。
    """
    # 账号维 key 先规范化（同 login：大小写变体不绕过限流）
    await auth_rate_limiter.check(
        f"rate:pwreset:account:{_account_hash(normalize_identity(payload.account))}",
        settings.AUTH_RATE_LIMIT_PASSWORD_RESET_PER_MINUTE,
    )
    await auth_rate_limiter.check(
        f"rate:pwreset:ip:{_client_ip(request)}",
        settings.AUTH_RATE_LIMIT_LOGIN_IP_PER_MINUTE,
    )

    user = _find_user_by_identifier(db, payload.account)

    if PHONE_PATTERN.match(normalize_identity(payload.account)):
        # 短信通道：忘邮箱用户的找回途径；未绑定手机号/无密码不真实发信（统一文案防枚举）
        if not settings.DEBUG and not sms_service.is_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="找回密码短信服务尚未完成服务端配置",
            )

        if (
            not user
            or not user.is_active
            or not user.phone
            or not has_usable_password_hash(user.password_hash)
        ):
            return _build_password_reset_code_response(message=_password_reset_request_sms_message())

        # 号码维日限流（短信防滥用，与 /phone/send-code 同源）
        await auth_rate_limiter.check(
            f"rate:sms:daily:phone:{_account_hash(user.phone)}",
            settings.SMS_DAILY_LIMIT_PER_PHONE,
            window_seconds=86400,
        )

        code = await password_reset_service.issue_code(user.id)
        if code is None:
            return _build_password_reset_code_response(message=_password_reset_request_sms_message())

        try:
            await sms_verification_service.reserve_budget()
        except SmsBudgetExhaustedError:
            await password_reset_service.delete_code(user.id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="验证码发送失败，请稍后重试",
            )

        try:
            await sms_service.send_verification_code(user.phone, code)
        except SmsServiceNotConfiguredError as exc:
            await password_reset_service.delete_code(user.id)
            await sms_verification_service.release_budget()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="找回密码短信服务尚未完成服务端配置",
            ) from exc
        except SmsDeliveryError as exc:
            await password_reset_service.delete_code(user.id)
            await sms_verification_service.release_budget()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="验证码发送失败，请稍后重试",
            ) from exc

        return _build_password_reset_code_response(message=_password_reset_request_sms_message())

    # 邮箱通道（原逻辑不变）
    if not settings.DEBUG and not password_reset_email_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="找回密码邮件服务尚未完成服务端配置",
        )

    # 无邮箱账号（OAuth 建号 email=NULL）无法发码：统一文案不泄露账号特征（P1-3.2）
    if (
        not user
        or not user.is_active
        or not user.email
        or not has_usable_password_hash(user.password_hash)
    ):
        return _build_password_reset_code_response(message=_password_reset_request_message())

    code = await password_reset_service.issue_code(user.id)
    if code is None:
        return _build_password_reset_code_response(message=_password_reset_request_message())

    try:
        await password_reset_email_service.send_password_reset_code(user.email, code)
    except EmailServiceNotConfiguredError as exc:
        await password_reset_service.delete_code(user.id)
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

    return _build_password_reset_code_response(message=_password_reset_request_message())


@router.post("/reset-password")
async def reset_password(
    payload: PasswordResetConfirm,
    request: Request,
    db: Session = Depends(get_db),
):
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

    # 密码历史（P2-4.6）：重置同样不得复用最近 3 次密码
    if password_history_service.is_reused(db, user.id, payload.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与最近使用过的密码相同",
        )

    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1  # 使所有旧 JWT 立即失效
    # 重置成功即证明邮箱所有权：置已验证（解存量未验证用户死锁，批次 3 决策）
    user.email_verified = True
    user.email_verified_at = utc_now()
    password_history_service.record(db, user.id, payload.new_password)
    db.add(user)
    db.commit()

    _audit_record(db, event_type=EVENT_PASSWORD_RESET, request=request, user_id=user.id)
    return {"message": "密码重置成功，请使用新密码登录"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户信息。

    依赖注入返回的实例可能已脱离会话（expunge），此处按 id 重新加载并预取 roles，
    避免响应序列化时对惰性关系触发 DetachedInstanceError。
    """
    user = (
        db.query(User)
        .options(joinedload(User.roles))
        .filter(User.id == current_user.id)
        .first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return build_user_response(user)


_optional_bearer = HTTPBearer(auto_error=False)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    body: Optional[LogoutRequest] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    """用户登出：吊销当前会话的 jti 与 refresh token（单会话失效，不影响其他设备）。

    全设备下线是 token_version 的职责（改密/重置/禁用时递增），登出只吊销本会话。
    兼容三种形态：
    - Bearer 头携带 access token（既有客户端）；
    - body 携带 access_token/refresh_token（P1-3.7 前端：短 access 过期后仍能完成吊销，
      否则登出后 refresh 会"复活"会话）；
    - httpOnly cookie 携带 access/refresh（P2-4.5 浏览器主路径）。
    登出是清理操作：token 已过期/无效时跳过对应吊销分支，不因此报错；
    但吊销存储（Redis）不可用时 fail-closed 返回 503。登出响应一律清除三个 cookie。
    """
    token_value = None
    if credentials and credentials.credentials:
        token_value = credentials.credentials
    elif body and body.access_token:
        token_value = body.access_token
    elif request.cookies.get(core_security.access_cookie_name()):
        token_value = request.cookies.get(core_security.access_cookie_name())

    if token_value:
        try:
            token_payload = verify_token(token_value)
        except HTTPException:
            token_payload = None  # 已过期/无效的 token 无需吊销
        if token_payload:
            jti = token_payload.get("jti")
            exp = token_payload.get("exp")
            if jti and exp:
                # 通过模块属性访问（测试替换 security.jti_revocation_service 后生效）
                await core_security.jti_revocation_service.revoke(str(jti), int(exp))

    cookie_refresh = request.cookies.get(core_security.refresh_cookie_name())
    if body and body.refresh_token:
        await core_security.refresh_token_service.revoke(body.refresh_token)
    elif cookie_refresh:
        await core_security.refresh_token_service.revoke(cookie_refresh)

    # P2-4.5：清除 access/refresh/csrf 三个 cookie
    clear_auth_cookies(response)

    # P2-4.4：审计登出（user_id 取 token 内的 sub；无效 token 时为 None）
    logout_user_id = None
    if token_value:
        try:
            _payload = verify_token(token_value)
            if _payload.get("sub"):
                logout_user_id = int(_payload["sub"])
        except HTTPException:
            pass
    _audit_record(db, event_type=EVENT_LOGOUT, request=request, user_id=logout_user_id)

    return {"message": "退出登录成功"}


@router.post("/change-password")
async def change_password(
    password_data: PasswordChange,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改密码（P2-4.5：成功后清除会话 cookie，旧会话立即失效）。"""
    _ensure_local_password_account(current_user)

    if not verify_password(password_data.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码错误",
        )

    # 依赖注入的实例可能绑定在其他会话（测试/多依赖场景），按 id 重查再写（与 set-password 同款）
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    # 密码历史（P2-4.6）：新密码不得与最近 3 次重复（含当前密码，注册/设密时已入历史）
    if password_history_service.is_reused(db, user.id, password_data.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与最近使用过的密码相同",
        )

    user.password_hash = hash_password(password_data.new_password)
    user.token_version += 1  # 使所有旧 JWT 立即失效
    password_history_service.record(db, user.id, password_data.new_password)
    db.add(user)
    db.commit()

    # P2-4.5：改密已递增 tv，当前会话失效，同步清除 cookie
    clear_auth_cookies(response)

    _audit_record(db, event_type=EVENT_PASSWORD_CHANGE, request=request, user_id=user.id)
    return {"message": "密码修改成功"}


@router.post("/set-password")
async def set_password(
    payload: PasswordSetRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """OAuth 用户首次设置本地密码（P2-4.2）：不要求旧密码。

    前置：仅无可用密码的账户可走（已有密码必须走 change-password 验证旧密码）。
    成功：替换 !oauth-disabled! 占位哈希、递增 token_version（与改密/重置同构，
    旧 access 立即失效、旧 refresh 下次刷新 401）、当前密码进入历史。
    """
    if has_usable_password_hash(current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前账号已设置密码，请使用修改密码功能",
        )

    # 依赖注入的实例可能绑定在其他会话（测试/多依赖场景），按 id 重查再写（与 /me 同款）
    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    if password_history_service.is_reused(db, user.id, payload.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与最近使用过的密码相同",
        )

    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1  # 与改密/重置同构：所有旧 token 立即失效
    password_history_service.record(db, user.id, payload.new_password)
    db.add(user)
    db.commit()

    # P2-4.5：设密已递增 tv，当前会话失效，同步清除 cookie
    clear_auth_cookies(response)

    _audit_record(db, event_type=EVENT_PASSWORD_SET, request=request, user_id=user.id)
    return {"message": "密码设置成功"}


@router.post("/oauth/confirm", response_model=OAuthConfirmResponse)
async def oauth_confirm_registration(
    payload: OAuthConfirmRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """OAuth 首次建号确认（P1-3.2）。

    GETDEL 原子消费票据：confirm 建号（email=NULL）并登录；cancel 仅消费不建号。
    票据缺失/过期/重放统一 400。

    P2-4.1：票据内 openid 为密文（Redis 内不落明文），此处解密后建号。
    """
    _ensure_openid_crypto()

    pending = await oauth_pending_registration.consume(payload.ticket)
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="注册票据已过期，请重新登录",
        )

    if payload.action == "cancel":
        return {"message": "已取消注册"}

    async def _restore_ticket() -> None:
        # 建号/签发 token 失败：票据已被 GETDEL 消费，NX 写回让用户可重试，
        # 避免只能重走 OAuth（与 refresh 的 restore 语义一致）。写回失败不掩盖原异常。
        try:
            await oauth_pending_registration.restore(payload.ticket, pending)
        except Exception:
            logger.exception("OAuth 建号失败且票据写回失败（原异常）")

    try:
        provider = str(pending.get("provider") or "")
        raw_openid = str(pending.get("openid") or "").strip()
        raw_unionid = str(pending.get("unionid") or "").strip()
        nickname = str(pending.get("nickname") or "").strip()
        avatar_url = pending.get("avatar_url")
        if provider not in ("alipay", "wechat") or not raw_openid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="注册票据已过期，请重新登录",
            )

        # 票据内 openid 为密文：不可解（如加密密钥已轮换）按票据过期处理，返回 400 不写回
        try:
            openid = get_openid_crypto().decrypt(raw_openid)
            unionid = get_openid_crypto().decrypt(raw_unionid) if raw_unionid else None
        except OpenIDDecryptError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="注册票据已过期，请重新登录",
            ) from exc

        # P2-5.2：建号前校验同意——未勾选不建号、不记录
        # 合规修订：OAuth 首次建号须同时确认 privacy_policy、oauth_sync 与 age_eligibility
        accepted_consents = _require_consents(
            payload.consent, ["privacy_policy", "oauth_sync", "age_eligibility"]
        )

        user = OAuthService.create_confirmed_user(
            db,
            provider=provider,
            raw_id=openid,
            full_name=nickname or f"{provider}_user",
            avatar_url=str(avatar_url) if avatar_url else None,
            alipay_openid=openid if provider == "alipay" else None,
            wechat_openid=openid if provider == "wechat" else None,
            wechat_unionid=unionid if provider == "wechat" else None,
        )
        user = OAuthService._ensure_active(user)

        # P2-5.2：只记录用户真实勾选的同意项
        for consent_type, version in accepted_consents.items():
            consent_service.record_accepted(
                db,
                user=user,
                consent_type=consent_type,
                version=version,
                ip=_client_ip(request),
                extra_scope={"provider": provider} if consent_type == "oauth_sync" else None,
            )
        _audit_record(
            db,
            event_type=EVENT_OAUTH_REGISTER,
            request=request,
            user_id=user.id,
            provider=provider,
        )

        token_payload = await build_token_response(user)
        set_auth_cookies(
            response,
            access_token=token_payload["access_token"],
            refresh_token=token_payload["refresh_token"],
            csrf_token=token_payload["csrf_token"],
        )
        # P2-4.5 收尾：令牌仅入 httpOnly cookie，body 只回 user——不得把 access/refresh/csrf 漏回 JSON
        return {"user": token_payload["user"]}
    except HTTPException as exc:
        # 400 客户端错误（无效 provider / 空 openid 等）不写回：坏票据不得复活，
        # 与 refresh 的"401 不写回"语义一致；其余 HTTPException（如签发 token 的
        # 503）仍写回让用户可重试。
        if exc.status_code != status.HTTP_400_BAD_REQUEST:
            await _restore_ticket()
        raise
    except Exception:
        await _restore_ticket()
        raise


@router.post("/bind/confirm")
async def bind_confirm(
    payload: BindConfirmRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """已登录用户绑定第三方登录（P2-4.2，D4：票据 + 登录态 confirm）。

    GETDEL 原子消费绑定票据：票据内 user_id 只当线索，鉴权在本端点的登录态；
    目标 openid 已被其他用户绑定 → 409，绝不回落到 existing login（P1 不做账号合并）；
    同 provider 重绑允许覆盖当前用户自己的旧绑定（D3）。
    """
    _ensure_openid_crypto()

    pending = await oauth_pending_registration.consume(payload.bind_ticket)
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="绑定已过期，请重新发起",
        )

    async def _restore_ticket() -> None:
        try:
            await oauth_pending_registration.restore(payload.bind_ticket, pending)
        except Exception:
            logger.exception("绑定失败且票据写回失败（原异常）")

    try:
        if pending.get("intent") != "bind":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="绑定票据无效，请重新发起",
            )
        provider = str(pending.get("provider") or "")
        if provider not in ("alipay", "wechat") or not pending.get("openid"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="绑定票据无效，请重新发起",
            )
        if int(pending.get("user_id") or 0) != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="绑定信息与当前登录用户不一致，请重新发起",
            )

        # P2-5.2：绑定前校验同意——未勾选不绑定、不记录（票据由 except 分支写回可重试）
        accepted_consents = _require_consents(payload.consent, ["oauth_sync"])

        raw_openid = str(pending.get("openid") or "").strip()
        raw_unionid = str(pending.get("unionid") or "").strip()
        try:
            openid = get_openid_crypto().decrypt(raw_openid)
            unionid = get_openid_crypto().decrypt(raw_unionid) if raw_unionid else None
        except OpenIDDecryptError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="绑定已过期，请重新发起",
            ) from exc

        # 冲突检查（D3：仅"被他人占用" 409，允许覆盖自己）
        openid_field = f"{provider}_openid"
        existing = _find_by_openid(db, openid_field, openid)
        if existing and existing.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该第三方账号已绑定其他用户",
            )
        if provider == "wechat" and unionid:
            union_existing = _find_by_openid(db, "wechat_unionid", unionid)
            if union_existing and union_existing.id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="该第三方账号已绑定其他用户",
                )

        user = db.query(User).filter(User.id == current_user.id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在",
            )

        _sync_openid(user, openid_field, openid)
        if provider == "wechat":
            if unionid:
                _sync_openid(user, "wechat_unionid", unionid)
            else:
                # 评审 #2：一次绑定一种微信身份——新票据无 unionid 时显式清空旧值，
                # 避免跨 App 匹配把新微信号与旧 unionid 搅在一起
                user.wechat_unionid_hash = None
                user.wechat_unionid_encrypted = None
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # 并发竞态兜底：UNIQUE hash 冲突翻译成 409，绝不回落 existing login
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该第三方账号已绑定其他用户",
            )

        # P2-5.2：只记录用户真实勾选的同意项
        for consent_type, version in accepted_consents.items():
            consent_service.record_accepted(
                db,
                user=user,
                consent_type=consent_type,
                version=version,
                ip=_client_ip(request),
                extra_scope={"provider": provider},
            )
        _audit_record(
            db,
            event_type=EVENT_BIND,
            request=request,
            user_id=user.id,
            provider=provider,
        )
        return {"message": "绑定成功"}
    except HTTPException as exc:
        # 400/409 客户端错误不写回（坏票据不得复活）；服务端失败（503 等）写回可重试
        if exc.status_code not in (status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT):
            await _restore_ticket()
        raise
    except Exception:
        await _restore_ticket()
        raise


@router.post("/unbind/{provider}")
async def unbind_provider(
    provider: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """解绑第三方登录（P2-4.2）：至少保留一种登录方式，成功递增 token_version。"""
    if provider not in ("alipay", "wechat"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的登录方式")

    user = db.query(User).filter(User.id == current_user.id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    has_password = has_usable_password_hash(user.password_hash)
    alipay_bound = bool(user.alipay_openid_hash)
    wechat_bound = bool(user.wechat_openid_hash or user.wechat_unionid_hash)

    if provider == "alipay":
        if not alipay_bound:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="当前账号未绑定支付宝登录",
            )
        remaining = (1 if has_password else 0) + (1 if wechat_bound else 0)
    else:
        if not wechat_bound:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="当前账号未绑定微信登录",
            )
        remaining = (1 if has_password else 0) + (1 if alipay_bound else 0)

    if remaining < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少保留一种登录方式",
        )

    if provider == "alipay":
        user.alipay_openid_hash = None
        user.alipay_openid_encrypted = None
    else:
        # 微信一次清 openid 与 unionid（跨 App 匹配断点，两个字段视为一种登录方式）
        user.wechat_openid_hash = None
        user.wechat_openid_encrypted = None
        user.wechat_unionid_hash = None
        user.wechat_unionid_encrypted = None

    # 登录方式集合变化：旧会话风险升高，递增 tv 全量下线（与设密/改密同构语义）
    user.token_version += 1
    db.add(user)
    db.commit()

    _audit_record(
        db,
        event_type=EVENT_UNBIND,
        request=request,
        user_id=user.id,
        provider=provider,
    )
    return {"message": "解绑成功"}


@router.post("/alipay/auth-url")
async def get_alipay_auth_url(
    request: AlipayAuthUrlRequest,
    current_user: Optional[User] = Depends(core_security.get_current_user_optional),
):
    """获取支付宝授权地址。

    服务端生成 state 并绑定 provider + redirect_uri 存入 Redis；
    校验 redirect_uri 白名单；返回 state 供前端回调时回传。
    P2-4.2：intent=bind 时必须登录态，state 附带 user_id 作为线索。
    """
    state_extra = _resolve_intent_state(request.intent, current_user)
    _ensure_alipay_configured()
    _validate_redirect_uri(request.redirect_uri)

    state = secrets.token_urlsafe(32)
    await oauth_state_service.store(state, "alipay", request.redirect_uri, extra=state_extra)

    alipay_service = AlipayOAuthService(
        app_id=settings.ALIPAY_APP_ID,
        private_key=settings.ALIPAY_PRIVATE_KEY,
        public_key=settings.ALIPAY_PUBLIC_KEY,
        sandbox=settings.ALIPAY_SANDBOX,
    )
    return {
        "auth_url": alipay_service.get_auth_url(request.redirect_uri, state),
        "state": state,
    }


@router.post("/alipay/callback", response_model=OAuthCallbackResponse)
async def alipay_callback(
    request: OAuthCallbackRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """支付宝 OAuth 回调。

    服务端一次性消费并校验 state（防 CSRF/重放），随后换取 token。
    P1-3.2：已注册用户返回 status=ok + token；新用户不再自动建号，
    身份信息存 Redis 并返回不透明建号票据，由 /oauth/confirm 确认后建号。
    """
    _ensure_alipay_configured()
    _ensure_openid_crypto()
    if not request.state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的登录状态，请重新发起",
        )
    state_payload = await oauth_state_service.consume(request.state, "alipay")
    # 纵深：校验 state 绑定的 redirect_uri 仍在白名单内（防 state 数据被篡改）
    _validate_redirect_uri(str(state_payload.get("redirect_uri", "")))

    # 换票前获取短锁（防并发双换票），code_hash 供成功/失败分支使用
    code_hash = await oauth_code_guard.acquire(request.code)

    alipay_service = AlipayOAuthService(
        app_id=settings.ALIPAY_APP_ID,
        private_key=settings.ALIPAY_PRIVATE_KEY,
        public_key=settings.ALIPAY_PUBLIC_KEY,
        sandbox=settings.ALIPAY_SANDBOX,
    )

    try:
        token_data = await alipay_service.get_access_token(request.code)
    except Exception as exc:  # noqa: BLE001 - 网络/超时类错误，释放锁允许重试
        await oauth_code_guard.release(code_hash)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="支付宝认证失败，请重试",
        ) from exc

    if "error" in token_data:
        error_msg = str(token_data.get("error_description") or "")
        error_code = str(token_data.get("sub_code") or token_data.get("error") or "")
        # 只对明确的"code 已消费"落 code_used 标记；其他错误释放锁允许重试
        if "code been used" in error_msg.lower() or "code-invalid" in error_code.lower():
            await oauth_code_guard.mark_used(code_hash)
        else:
            await oauth_code_guard.release(code_hash)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=token_data.get("error_description") or token_data.get("sub_msg") or "支付宝认证失败",
        )

    access_token = token_data.get("access_token")
    if not access_token:
        await oauth_code_guard.release(code_hash)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="支付宝未返回 access_token",
        )

    # 换票已成功（拿到 access_token）：code 在支付宝侧已作废，立即落 used 标记。
    # 之后 get_user_info 失败也不再释放锁，重试同 code 直接 400，避免再打网关。
    await oauth_code_guard.mark_used(code_hash)

    user_info = await alipay_service.get_user_info(access_token)
    if "error" in user_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_info.get("error_description") or user_info.get("sub_msg") or "获取支付宝用户信息失败",
        )

    # P2-4.2：intent=bind 时不建号也不发 token，身份信息存票据由登录态 bind/confirm 消费
    if state_payload.get("intent") == "bind":
        crypto = get_openid_crypto()
        ticket = await oauth_pending_registration.store(
            {
                "intent": "bind",
                "user_id": int(state_payload.get("user_id") or 0),
                "provider": "alipay",
                "openid": crypto.encrypt(str(user_info.get("user_id") or "").strip()),
                "nickname": str(user_info.get("nick_name") or ""),
            }
        )
        return {"status": "bind_pending", "bind_ticket": ticket}

    user = await OAuthService.handle_alipay_login(db, user_info)
    if user:
        record_audit(
            db, event_type=EVENT_OAUTH_LOGIN, user_id=user.id, provider="alipay"
        )
        # P2-4.5 收尾：OAuth 登录同样写 httpOnly cookie（此前遗漏），body 只回 user
        token_payload = await build_token_response(user)
        set_auth_cookies(
            response,
            access_token=token_payload["access_token"],
            refresh_token=token_payload["refresh_token"],
            csrf_token=token_payload["csrf_token"],
        )
        return {"status": "ok", "user": token_payload["user"]}

    # 首次登录：不自动建号，身份信息存 Redis，仅回不透明票据
    # P2-4.1：openid 以密文入 Redis，票据本身仍不携带身份信息
    crypto = get_openid_crypto()
    ticket = await oauth_pending_registration.store(
        {
            "provider": "alipay",
            "openid": crypto.encrypt(str(user_info.get("user_id") or "").strip()),
            "nickname": str(user_info.get("nick_name") or ""),
        }
    )
    return {"status": "new_user", "registration_ticket": ticket}


@router.post("/wechat/auth-url")
async def get_wechat_auth_url(
    request: WechatAuthUrlRequest,
    current_user: Optional[User] = Depends(core_security.get_current_user_optional),
):
    """获取微信授权地址。服务端生成 state 并校验 redirect_uri 白名单。

    P2-4.2：intent=bind 时必须登录态，state 附带 user_id 作为线索。
    """
    state_extra = _resolve_intent_state(request.intent, current_user)
    _ensure_wechat_configured()
    _validate_redirect_uri(request.redirect_uri)

    state = secrets.token_urlsafe(32)
    await oauth_state_service.store(state, "wechat", request.redirect_uri, extra=state_extra)

    wechat_service = WechatOAuthService(
        app_id=settings.WECHAT_APP_ID,
        app_secret=settings.WECHAT_APP_SECRET,
    )
    return {
        "auth_url": wechat_service.get_auth_url(request.redirect_uri, state),
        "state": state,
    }


@router.post("/wechat/callback", response_model=OAuthCallbackResponse)
async def wechat_callback(
    request: OAuthCallbackRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """微信 OAuth 回调。服务端一次性消费并校验 state。

    P1-3.2：已注册用户返回 status=ok + token；新用户返回建号票据。
    """
    _ensure_wechat_configured()
    _ensure_openid_crypto()
    if not request.state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的登录状态，请重新发起",
        )
    state_payload = await oauth_state_service.consume(request.state, "wechat")
    # 纵深：校验 state 绑定的 redirect_uri 仍在白名单内（防 state 数据被篡改）
    _validate_redirect_uri(str(state_payload.get("redirect_uri", "")))

    # 换票前获取短锁（防并发双换票），code_hash 供成功/失败分支使用
    code_hash = await oauth_code_guard.acquire(request.code)

    wechat_service = WechatOAuthService(
        app_id=settings.WECHAT_APP_ID,
        app_secret=settings.WECHAT_APP_SECRET,
    )

    try:
        token_data = await wechat_service.get_access_token(request.code)
    except Exception as exc:  # noqa: BLE001 - 网络/超时类错误，释放锁允许重试
        await oauth_code_guard.release(code_hash)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="微信认证失败，请重试",
        ) from exc

    if "errcode" in token_data and token_data["errcode"] != 0:
        # errcode=40163 表示 code 已被使用
        errcode = int(token_data.get("errcode") or 0)
        if errcode == 40163:
            await oauth_code_guard.mark_used(code_hash)
        else:
            await oauth_code_guard.release(code_hash)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=token_data.get("errmsg", "微信认证失败"),
        )

    access_token = token_data.get("access_token")
    openid = token_data.get("openid")
    unionid = token_data.get("unionid")
    if not access_token or not openid:
        await oauth_code_guard.release(code_hash)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="微信未返回完整授权信息",
        )

    # 换票已成功（拿到 access_token）：code 在微信侧已作废，立即落 used 标记。
    # 之后 get_user_info 失败也不再释放锁，重试同 code 直接 400，避免再打网关。
    await oauth_code_guard.mark_used(code_hash)

    user_info = await wechat_service.get_user_info(access_token, openid)
    if "errcode" in user_info and user_info["errcode"] != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_info.get("errmsg", "获取微信用户信息失败"),
        )

    # P2-4.2：intent=bind 时不建号也不发 token，身份信息存票据由登录态 bind/confirm 消费
    if state_payload.get("intent") == "bind":
        crypto = get_openid_crypto()
        ticket = await oauth_pending_registration.store(
            {
                "intent": "bind",
                "user_id": int(state_payload.get("user_id") or 0),
                "provider": "wechat",
                "openid": crypto.encrypt(openid),
                "unionid": crypto.encrypt(unionid) if unionid else None,
                "nickname": str(user_info.get("nickname") or ""),
            }
        )
        return {"status": "bind_pending", "bind_ticket": ticket}

    user = await OAuthService.handle_wechat_login(db, user_info, openid, unionid)
    if user:
        record_audit(
            db, event_type=EVENT_OAUTH_LOGIN, user_id=user.id, provider="wechat"
        )
        # P2-4.5 收尾：OAuth 登录同样写 httpOnly cookie（此前遗漏），body 只回 user
        token_payload = await build_token_response(user)
        set_auth_cookies(
            response,
            access_token=token_payload["access_token"],
            refresh_token=token_payload["refresh_token"],
            csrf_token=token_payload["csrf_token"],
        )
        return {"status": "ok", "user": token_payload["user"]}

    # P2-4.1：openid / unionid 以密文入 Redis，票据本身仍不携带身份信息
    crypto = get_openid_crypto()
    ticket = await oauth_pending_registration.store(
        {
            "provider": "wechat",
            "openid": crypto.encrypt(openid),
            "unionid": crypto.encrypt(unionid) if unionid else None,
            "nickname": str(user_info.get("nickname") or ""),
            "avatar_url": user_info.get("headimgurl"),
        }
    )
    return {"status": "new_user", "registration_ticket": ticket}
