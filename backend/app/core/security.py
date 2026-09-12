"""
安全和认证工具
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Optional

import bcrypt
import redis.exceptions
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis_client import LoopBoundRedis
from app.db.base import get_db
from app.models.user import User
from app.schemas.user import UserResponse, build_user_response

logger = logging.getLogger(__name__)

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)
UNUSABLE_PASSWORD_PREFIX = "!oauth-disabled!"

# Lua：原子 INCR + 首次设置 TTL（限流与账户锁定共用，固定窗口计数）
INCR_WITH_TTL_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


# ============================================================
# Cookie 认证（P2-4.5）：access/refresh/csrf 均入 httpOnly cookie
# ============================================================

def access_cookie_name() -> str:
    return f"{settings.COOKIE_PREFIX}access_token"


def refresh_cookie_name() -> str:
    return f"{settings.COOKIE_PREFIX}refresh_token"


def csrf_cookie_name() -> str:
    return f"{settings.COOKIE_PREFIX}csrf"


def create_csrf_token() -> str:
    """生成 CSRF token：明文入 csrf cookie，sha256 摘要入 JWT `csrf` claim。"""
    return secrets.token_urlsafe(32)


def csrf_claim_hash(csrf_token: str) -> str:
    return hashlib.sha256(csrf_token.encode("utf-8")).hexdigest()


def set_auth_cookies(response, *, access_token: str, refresh_token: str, csrf_token: str) -> None:
    """把 access/refresh/csrf 写入 cookie（P2-4.5）。

    - access / refresh：httpOnly + SameSite=Lax（OAuth 回跳后首个同源 XHR 仍携带）；
    - csrf：**非 httpOnly** + SameSite=Strict——JS 需读取它以构造 `X-CSRF-Token` 头
      （真双重提交）；csrf token 非会话密钥（access 仍 httpOnly），XSS 可读不扩大危害。
    """
    secure = bool(settings.COOKIE_SECURE)
    access_max_age = max(int(settings.JWT_ACCESS_EXPIRATION_MINUTES) * 60, 1)
    refresh_max_age = max(int(settings.JWT_REFRESH_EXPIRATION_DAYS) * 86400, 1)
    for key, value, max_age, samesite in (
        (access_cookie_name(), access_token, access_max_age, "lax"),
        (refresh_cookie_name(), refresh_token, refresh_max_age, "lax"),
        (csrf_cookie_name(), csrf_token, refresh_max_age, "strict"),
    ):
        response.set_cookie(
            key,
            value,
            max_age=max_age,
            path="/",
            secure=secure,
            httponly=(key != csrf_cookie_name()),  # csrf 需 JS 可读以构造 X-CSRF-Token 头
            samesite=samesite,
        )


def clear_auth_cookies(response) -> None:
    """登出/会话失效时清除三个认证 cookie。"""
    for name in (access_cookie_name(), refresh_cookie_name(), csrf_cookie_name()):
        response.delete_cookie(name, path="/")


def csrf_check(request) -> Optional[str]:
    """P2-4.5：cookie 认证会话的 unsafe 方法 CSRF 校验（真双重提交）。

    - 仅当请求携带 httpOnly access cookie（浏览器 cookie 会话）时校验：
      请求头 `X-CSRF-Token` 必须等于 csrf cookie 值，且 csrf cookie 的 sha256
      必须等于 JWT `csrf` claim（会话绑定）；
    - 跨站表单无法构造该头（csrf cookie 非 httpOnly 但 SameSite=Strict，跨站不携带，
      且攻击者拿不到同源 JS 读取的合法值），SameSite 与显式头双重保障；
    - Authorization 头认证（非 cookie 会话，无 CSRF 攻击面）与公共端点跳过；
    - 返回 None 表示通过，否则返回用户可见错误文案。
    """
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    access_cookie = request.cookies.get(access_cookie_name())
    if not access_cookie:
        return None

    csrf_cookie = request.cookies.get(csrf_cookie_name())
    header_token = request.headers.get("x-csrf-token", "")
    try:
        payload = verify_token(access_cookie)
    except HTTPException:
        return None  # token 无效交给认证层处理，不在 CSRF 层暴露

    claim = str(payload.get("csrf") or "") if payload else ""
    if (
        not csrf_cookie
        or not claim
        or not header_token
        or header_token != csrf_cookie
        or csrf_claim_hash(csrf_cookie) != claim
    ):
        return "CSRF 校验失败"
    return None


class JtiRevocationService:
    """jti 单会话吊销服务（Redis，fail-closed，P1-3.5）。

    - 登出时把当前 token 的 jti 写入黑名单，TTL 为 token 剩余有效期；
    - get_current_user 每次校验 jti 是否被吊销（单会话登出）；
    - Redis 不可用时返回 503，不静默放行（否则吊销形同虚设）。
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = str(redis_url or settings.REDIS_URL).strip()
        self._redis = LoopBoundRedis(self.redis_url)

    async def _get_redis_client(self):
        return await self._redis.get()

    @staticmethod
    def _key(jti: str) -> str:
        return f"jti:revoked:{jti}"

    async def revoke(self, jti: str, exp: int) -> None:
        """登出时吊销当前会话的 jti（TTL=token 剩余有效期，过期自动清理）。"""
        now = int(datetime.now(timezone.utc).timestamp())
        ttl = max(int(exp) - now, 1)
        try:
            client = await self._get_redis_client()
            await client.setex(self._key(jti), ttl, "1")
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def is_revoked(self, jti: str) -> bool:
        """查询 jti 是否已被登出吊销。Redis 不可用时 503（fail-closed）。"""
        try:
            client = await self._get_redis_client()
            return bool(await client.exists(self._key(jti)))
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc


jti_revocation_service = JtiRevocationService()


class AccountLockoutService:
    """账号锁定服务（Redis 计数，fail-closed，P2-4.6）。

    - 仅"账号存在 + 有可用密码 + 密码错误"计入（OAuth 账户与不存在账号不计数，
      由路由侧判定，本服务只管计数原语）；
    - 连续 ACCOUNT_LOCKOUT_ATTEMPTS 次失败即写 locked 标记（TTL = 锁定窗口）；
    - 锁定窗口内失败不续期（避免把窗口变成"永久锁"）；
    - 与 3.1 限流独立 key（lockout:* vs rate:*），互不抢占语义；
    - 成功登录清空计数与标记（路由侧在放行前调用）；
    - 锁定窗口内的响应语义（含正确密码也 401 统一文案）由路由实现（D1：静默 401）；
    - Redis 不可用 503（fail-closed，登录关键路径本就依赖 Redis，锁定 fail-open 等于没有）。
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = str(redis_url or settings.REDIS_URL).strip()
        self._redis = LoopBoundRedis(self.redis_url)

    async def _get_redis_client(self):
        return await self._redis.get()

    @staticmethod
    def _attempts_key(account_hash: str) -> str:
        return f"lockout:attempts:{account_hash}"

    @staticmethod
    def _locked_key(account_hash: str) -> str:
        return f"lockout:locked:{account_hash}"

    @property
    def _window_seconds(self) -> int:
        return int(settings.ACCOUNT_LOCKOUT_MINUTES) * 60

    async def is_locked(self, account_hash: str) -> bool:
        """查询账号是否处于锁定窗口。Redis 不可用 503。"""
        try:
            client = await self._get_redis_client()
            return bool(await client.exists(self._locked_key(account_hash)))
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("账户锁定查询 Redis 不可用（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def register_failure(self, account_hash: str) -> bool:
        """计一次失败；达到阈值写锁定标记，返回是否触发锁定。Redis 不可用 503。"""
        try:
            client = await self._get_redis_client()
            count = await client.eval(
                INCR_WITH_TTL_LUA, 1, self._attempts_key(account_hash), self._window_seconds
            )
            if int(count) >= int(settings.ACCOUNT_LOCKOUT_ATTEMPTS):
                await client.set(
                    self._locked_key(account_hash), "1", ex=self._window_seconds
                )
                return True
            return False
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("账户锁定计数 Redis 不可用（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def clear(self, account_hash: str) -> None:
        """成功登录后清空失败计数与锁定标记（用户已证明持有密码）。Redis 不可用 503。"""
        try:
            client = await self._get_redis_client()
            await client.delete(
                self._attempts_key(account_hash), self._locked_key(account_hash)
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("账户锁定清零 Redis 不可用（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc


account_lockout_service = AccountLockoutService()


class RefreshTokenService:
    """refresh token 服务（Redis 存 SHA-256 哈希，fail-closed，P1-3.7）。

    - 原始 token 只发给客户端一次，服务端只存 `refresh:{sha256(token)}` -> JSON；
    - 轮换用 GETDEL 原子消费（读到即删除，重放即失效）；
    - consume/issue/restore/revoke/锁 均为原语，业务编排在 auth.py 的 /refresh 路由；
    - Redis 不可用时抛 503（fail-closed，不静默放行）。
    """

    LOCK_TTL_SECONDS = 5

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = str(redis_url or settings.REDIS_URL).strip()
        self._redis = LoopBoundRedis(self.redis_url)

    async def _get_redis_client(self):
        return await self._redis.get()

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _key(token_hash: str) -> str:
        return f"refresh:{token_hash}"

    @staticmethod
    def _lock_key(token_hash: str) -> str:
        return f"refresh:lock:{token_hash}"

    def _ttl_seconds(self) -> int:
        return settings.JWT_REFRESH_EXPIRATION_DAYS * 24 * 3600

    def _issue_token_value(self) -> str:
        return secrets.token_urlsafe(32)

    async def issue(self, user_id: int, tv: int) -> str:
        """签发 refresh token（原始值仅本次返回，Redis 只存哈希）。"""
        token = self._issue_token_value()
        payload = json.dumps(
            {"user_id": user_id, "tv": tv, "issued_at": int(datetime.now(timezone.utc).timestamp())}
        )
        try:
            client = await self._get_redis_client()
            await client.setex(self._key(self._hash(token)), self._ttl_seconds(), payload)
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc
        return token

    async def consume(self, token: str) -> Optional[str]:
        """原子消费（GETDEL 语义）：返回原始 payload 字符串，不存在返回 None。

        兼容路径：仅当 Redis 不支持 GETDEL 命令（< 6.2 返回 "unknown command"
        的 ResponseError）时回退 Lua 原子 GET+DEL；其余服务端错误（WRONGTYPE/OOM 等）
        与连接失败/超时/认证等异常一律向外抛 -> 503（fail-closed），
        不得把真实 Redis 故障误判为"token 不存在"（会把用户踢下线）。
        """
        key = self._key(self._hash(token))
        try:
            client = await self._get_redis_client()
            try:
                return await client.getdel(key)  # Redis 6.2+
            except redis.exceptions.ResponseError as exc:
                # 只认"命令不支持"（旧版带 "ERR" 前缀，统一按子串小写匹配）；
                # 其余 ResponseError 原样抛出 -> 503，不走 Lua 回退
                if "unknown command" not in str(exc).lower():
                    raise
                return await client.eval(
                    "local v = redis.call('GET', KEYS[1]); redis.call('DEL', KEYS[1]); return v",
                    1,
                    key,
                )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - 连接/超时/认证等其余异常 fail-closed
            self._redis.invalidate()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def restore(self, token: str, raw: str) -> None:
        """签发失败时写回旧值（NX：不覆盖并发请求已写入的新值），让用户可重试。"""
        try:
            client = await self._get_redis_client()
            await client.set(self._key(self._hash(token)), raw, nx=True, ex=self._ttl_seconds())
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def revoke(self, token: str) -> None:
        """登出吊销：删除对应 refresh 会话。"""
        try:
            client = await self._get_redis_client()
            await client.delete(self._key(self._hash(token)))
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def acquire_lock(self, token: str) -> bool:
        """并发刷新短锁（SET NX EX 5）：拿到返回 True，否则 False。"""
        try:
            client = await self._get_redis_client()
            return bool(
                await client.set(
                    self._lock_key(self._hash(token)), "1", nx=True, ex=self.LOCK_TTL_SECONDS
                )
            )
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def release_lock(self, token: str) -> None:
        """释放并发刷新短锁。"""
        try:
            client = await self._get_redis_client()
            await client.delete(self._lock_key(self._hash(token)))
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.warning("refresh 并发锁释放失败（随 TTL 自动过期）: %s", exc)


refresh_token_service = RefreshTokenService()


def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码。"""
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def make_unusable_password_hash() -> str:
    """为第三方登录账户生成不可用于本地密码登录的占位哈希。"""
    return UNUSABLE_PASSWORD_PREFIX


def hash_password_for_history(password: str) -> str:
    """密码历史专用 HMAC（P2-4.6）。

    实现在 password_history_service（需独立 pepper 与数据库语义），
    此处转发以保持"密码原语都在 security"的调用习惯。
    """
    from app.services.password_history_service import hash_password_for_history as _hash

    return _hash(password)


def has_usable_password_hash(hashed_password: Optional[str]) -> bool:
    """判断账户是否配置了可用于密码登录的哈希。"""
    return bool(hashed_password) and not hashed_password.startswith(UNUSABLE_PASSWORD_PREFIX)


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """校验密码，兼容第三方账户和异常哈希。"""
    if not has_usable_password_hash(hashed_password):
        return False

    password_bytes = plain_password.encode("utf-8")
    try:
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except ValueError:
        logger.warning("Detected invalid password hash during login attempt")
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT token。

    每次签发附带唯一 jti（用于后续单会话登出吊销）与 iat。
    token 版本号 tv 由调用方通过 data 传入（见 build_token_response）。
    P1-3.7：默认有效期缩短为 JWT_ACCESS_EXPIRATION_MINUTES（15-30 分钟），
    长会话由 refresh token 轮换维持。
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = (
        now + expires_delta
        if expires_delta
        else now + timedelta(minutes=settings.JWT_ACCESS_EXPIRATION_MINUTES)
    )
    to_encode.update({
        "exp": expire,
        "iat": now,
        "jti": secrets.token_urlsafe(16),
    })
    return jwt.encode(
        to_encode,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


async def build_token_response(user: User) -> dict:
    """统一构造登录响应：签发携带 tv 的短 access token + refresh token + 用户序列化。

    本地密码登录与第三方 OAuth 登录共用此函数，避免两处签发逻辑分叉
    （以后新增 claim 时只需改一处）。

    P2-4.5：额外生成 CSRF token（明文入响应供路由写入 cookie，sha256 摘要入 JWT
    `csrf` claim），access/refresh/csrf 三 cookie 由路由侧 set_auth_cookies 落盘。
    """
    csrf_token = create_csrf_token()
    return {
        "access_token": create_access_token(
            data={
                "sub": str(user.id),
                "tv": user.token_version,
                "csrf": csrf_claim_hash(csrf_token),
            }
        ),
        "token_type": "bearer",
        "refresh_token": await refresh_token_service.issue(user.id, user.token_version),
        "user": build_user_response(user),
        "csrf_token": csrf_token,
    }


def verify_token(token: str) -> dict:
    """验证并解析 JWT。"""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


def _validate_user_status(user: Optional[User]) -> User:
    """统一校验用户存在性和可用状态。"""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # P2-4.3：已注销（软删除）账户视同不存在（401），优先于禁用检查——
    # 注销后不应再暴露"禁用"这种与活跃账户不同的语义
    if user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return user


def _check_token_version(payload: dict, user: User) -> None:
    """校验 JWT 中的 tv 是否与用户当前 token_version 一致。

    改密/重置/禁用会递增 token_version，使所有旧 JWT 立即失效。
    迁移窗口：无 tv 的旧 token 视为版本 1，避免上线瞬间集体掉线。
    """
    token_version = payload.get("tv")
    if token_version is None:
        token_version = 1

    if int(token_version) != int(user.token_version or 1):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated",
        )


async def _check_jti_revoked(payload: dict) -> None:
    """校验 jti 是否已被登出吊销（单会话语义）。

    迁移窗口：P0 改造前签发的旧 token 无 jti，无法吊销，直接放行
    （随过期自然失效，最长 24 小时窗口）。
    """
    jti = payload.get("jti")
    if not jti:
        return

    if await jti_revocation_service.is_revoked(str(jti)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )


def _resolve_access_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    """P2-4.5：access token 优先 Authorization 头（显式身份优先），其次 httpOnly cookie。

    浏览器主路径（纯 cookie）不发 Authorization 头，走 cookie；测试基建/非 cookie 客户端
    显式带头时以头为准，避免被 cookie 会话盖掉显式身份。二者在浏览器侧不会同时出现。
    """
    if credentials and credentials.credentials:
        return credentials.credentials
    return request.cookies.get(access_cookie_name())


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    db: Session = Depends(get_db),
) -> User:
    """获取当前用户（P2-4.5：支持 httpOnly cookie 与 Authorization 头双来源）。"""
    token = _resolve_access_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = verify_token(token)
    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    user = _validate_user_status(user)
    _check_token_version(payload, user)
    await _check_jti_revoked(payload)
    return user


async def get_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """解析 Bearer token 返回 payload（用于登出吊销等 token 层操作）。"""
    return verify_token(credentials.credentials)


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    db: Session = Depends(get_db),
) -> User | None:
    """获取当前用户，可选认证（P2-4.5：支持 cookie 与 Authorization 头）。"""
    token = _resolve_access_token(request, credentials)
    if not token:
        return None

    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            return None

        user = db.query(User).filter(User.id == int(user_id)).first()
        if user and user.is_active and user.deleted_at is None:
            _check_token_version(payload, user)
            # 可选认证场景：吊销/Redis 异常一律按匿名处理（fail-open 仅限展示类接口）
            jti = payload.get("jti")
            if jti and await jti_revocation_service.is_revoked(str(jti)):
                return None
            return user
        return None
    except Exception:
        return None


async def resolve_user_from_token(token: str, db: Session) -> User | None:
    """从裸 token 字符串解析用户（完整校验链路：签名/状态/tv/jti），无效返回 None。

    供 query parameter token 场景使用（如 memories auto-save 的 sendBeacon）：
    此类场景此前走裸 verify_token，登出（jti）或改密（tv）后旧 token 仍可能生效，
    P1-3.7 统一收口到与 get_current_user 相同的校验链路。
    """
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            return None

        user = db.query(User).filter(User.id == int(user_id)).first()
        user = _validate_user_status(user)
        _check_token_version(payload, user)
        await _check_jti_revoked(payload)
        return user
    except HTTPException:
        return None
