import asyncio
import base64
import hashlib
import json
import os
import secrets
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from fastapi.security import HTTPAuthorizationCredentials


def _dummy_request():
    """构造最小 Request（测试直接调用 get_current_user 时使用，cookie 来源用空）。"""
    from fastapi import Request

    return Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 123),
            "scheme": "http",
        }
    )

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 在导入 app.* 之前固定测试环境，避免读取到本机脏环境变量。
os.environ["DEBUG"] = "false"
os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:5432/test_db"
# openid 加密存储（P2-4.1）的测试密钥由 tests/conftest.py 统一注入

from fastapi import FastAPI, HTTPException, Request, status
from httpx import ASGITransport, AsyncClient, Cookies, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.crypto as crypto
import app.core.security as security
from app.core.config import settings
from app.core.password_policy import PASSWORD_POLICY_ERROR_MESSAGE
from jose import jwt as jose_jwt

fake_db_base = types.ModuleType("app.db.base")
_original_db_base_module = sys.modules.get("app.db.base")
_original_user_module = sys.modules.get("app.models.user")
_original_role_module = sys.modules.get("app.models.role")


class AuthTestBase(DeclarativeBase):
    pass


def stub_get_db():
    raise RuntimeError("测试中应由 dependency_overrides 提供数据库会话")


fake_db_base.Base = AuthTestBase
fake_db_base.get_db = stub_get_db
fake_db_base.SessionLocal = lambda: None
sys.modules["app.db.base"] = fake_db_base
for polluted_module in ("app.models.user", "app.models.role"):
    sys.modules.pop(polluted_module, None)

from app.core.security import create_access_token, hash_password, make_unusable_password_hash
from app.db.base import Base, get_db
from app.models.audit_log import AuditLog
from app.models.consent_record import ConsentRecord
from app.models.password_history import PasswordHistory
from app.models.role import Role, user_roles
from app.models.user import User


def load_auth_module():
    auth_path = ROOT_DIR / "app" / "api" / "v1" / "auth.py"
    spec = spec_from_file_location("test_auth_module", auth_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载认证路由模块")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


auth = load_auth_module()

# 支付宝签名/验签服务模块引用
from app.services import oauth_service as oauth_svc

# 清理模块级 monkeypatch，避免污染后续测试的真实导入链路。
if _original_db_base_module is not None:
    sys.modules["app.db.base"] = _original_db_base_module
else:
    sys.modules.pop("app.db.base", None)

if _original_user_module is not None:
    sys.modules["app.models.user"] = _original_user_module
else:
    sys.modules.pop("app.models.user", None)

if _original_role_module is not None:
    sys.modules["app.models.role"] = _original_role_module
else:
    sys.modules.pop("app.models.role", None)


class CompatTestClient:
    """兼容 httpx 0.28+ 的轻量测试客户端。

    P2-4.5 收尾：维护 cookie jar 模拟浏览器会话——登录/刷新后 httpOnly
    access/refresh/csrf cookie 自动保持并随后续请求携带（body 不再返回 token）。
    """

    def __init__(self, app: FastAPI):
        self._app = app
        self._base_url = "http://testserver"
        self._cookies: Cookies = Cookies()

    async def _request_async(self, method: str, url: str, **kwargs) -> Response:
        # 附加已存 cookie（模拟浏览器会话保持）；显式传入 cookies 时以显式为准
        if kwargs.get("cookies") is None and self._cookies:
            kwargs["cookies"] = self._cookies
        # P2-4.5 真双重提交：unsafe 方法自动带 X-CSRF-Token（模拟浏览器 JS 读非 httpOnly csrf cookie）。
        # 调用方**显式**传入该头时以显式为准（含空串），否则"故意缺头/错头"的用例会被自动补头而假绿。
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            headers = dict(kwargs.get("headers") or {})
            explicit_csrf = any(str(key).lower() == "x-csrf-token" for key in headers)
            if not explicit_csrf:
                csrf_token = self._cookies.get(security.csrf_cookie_name())
                if csrf_token:
                    headers["X-CSRF-Token"] = csrf_token
            if headers:
                kwargs["headers"] = headers
        transport = ASGITransport(app=self._app)
        async with AsyncClient(
            transport=transport,
            base_url=self._base_url,
            follow_redirects=True,
        ) as client:
            response = await client.request(method, url, **kwargs)
        # 合并响应 set-cookie（httpOnly 认证 cookie 均自动保持）
        for name, value in response.cookies.items():
            self._cookies.set(name, value)
        return response

    def request(self, method: str, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async(method, url, **kwargs))

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)


def _access_token(response: Response) -> str:
    """从响应 httpOnly access cookie 提取 token（P2-4.5 收尾：body 不再返回 token）。"""
    token = response.cookies.get(security.access_cookie_name())
    assert token, "响应中缺少 access_token cookie"
    return token


def _refresh_token(response: Response) -> str:
    """从响应 httpOnly refresh cookie 提取 token。"""
    token = response.cookies.get(security.refresh_cookie_name())
    assert token, "响应中缺少 refresh_token cookie"
    return token


class FakeJtiService:
    """测试用内存 jti 吊销服务，替代 Redis 实现（P1-3.5）。"""

    def __init__(self):
        self.revoked: dict[str, int] = {}
        self.fail_redis = False

    async def revoke(self, jti: str, exp: int) -> None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        self.revoked[jti] = exp

    async def is_revoked(self, jti: str) -> bool:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        return jti in self.revoked


class FakeRateLimiter:
    """测试用内存限流器，复刻真实计数+超限语义（P1-3.1）。"""

    def __init__(self):
        self.counts: dict[str, int] = {}
        self.fail_redis = False

    async def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.counts[key] > limit:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")


class FakeCodeGuard:
    """测试用内存 OAuth code 换票锁（P1-3.1）。"""

    def __init__(self):
        self.locks: set[str] = set()
        self.used: set[str] = set()
        self.fail_redis = False

    @staticmethod
    def _hash(code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()[:16]

    async def acquire(self, code: str) -> str:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        code_hash = self._hash(code)
        if code_hash in self.used or code_hash in self.locks:
            raise HTTPException(status_code=400, detail="授权码已被使用")
        self.locks.add(code_hash)
        return code_hash

    async def mark_used(self, code_hash: str) -> None:
        self.used.add(code_hash)
        self.locks.discard(code_hash)

    async def release(self, code_hash: str) -> None:
        self.locks.discard(code_hash)


class FakePasswordResetService:
    """测试用内存找回密码验证码服务，替代 Redis 实现（P1-3.4）。"""

    def __init__(self):
        self.codes: dict[int, str] = {}
        self.fail_redis = False

    async def issue_code(self, user_id: int) -> str | None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        code = "123456"
        self.codes[user_id] = code
        return code

    async def verify_code(self, user_id: int, code: str) -> bool:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        if self.codes.get(user_id) == code:
            self.codes.pop(user_id, None)
            return True
        return False

    async def delete_code(self, user_id: int) -> None:
        self.codes.pop(user_id, None)


class FakeRefreshService:
    """测试用内存 refresh token 服务，复刻真实轮换语义（P1-3.7）。

    - issue：签发原始 token，内存存 SHA-256 哈希 -> JSON payload；
    - consume：原子消费（读到即删除，对应 Redis GETDEL）；
    - restore：失败写回（NX 语义：仅当 key 不存在时写回）；
    - revoke：删除（登出吊销）；
    - 锁：acquire_lock/release_lock（对应 SET NX EX 5，无自动过期，由测试控制）。
    """

    def __init__(self):
        self.tokens: dict[str, str] = {}
        self.locks: set[str] = set()
        self.fail_redis = False
        self.fail_issue = False

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def issue(self, user_id: int, tv: int) -> str:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        if self.fail_issue:
            # 模拟签发阶段 Redis 写失败（对应真实 issue 抛 503）
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        token = "fake-refresh-" + secrets.token_urlsafe(16)
        self.tokens[self._hash(token)] = json.dumps({"user_id": user_id, "tv": tv})
        return token

    async def consume(self, token: str) -> str | None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        return self.tokens.pop(self._hash(token), None)

    async def restore(self, token: str, raw: str) -> None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        self.tokens.setdefault(self._hash(token), raw)

    async def revoke(self, token: str) -> None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        self.tokens.pop(self._hash(token), None)

    async def acquire_lock(self, token: str) -> bool:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        token_hash = self._hash(token)
        if token_hash in self.locks:
            return False
        self.locks.add(token_hash)
        return True

    async def release_lock(self, token: str) -> None:
        self.locks.discard(self._hash(token))


class UnboundedRateLimiter(FakeRateLimiter):
    """锁定测试专用：不复刻 3.1 的 429（锁定窗口内尝试次数必然超过 5 次/分钟）。

    生产环境两者并存：3.1 挡高频刷接口，锁定挡同一账号慢速试；单测各自验证。
    """

    async def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        self.counts[key] = self.counts.get(key, 0) + 1


class FakeAccountLockoutService:
    """测试用内存账户锁定服务，复刻真实计数/锁定/清零语义（P2-4.6）。"""

    def __init__(self, max_attempts: int = 5):
        self.max_attempts = max_attempts
        self.failures: dict[str, int] = {}
        self.locked: set[str] = set()
        self.fail_redis = False

    async def is_locked(self, account_hash: str) -> bool:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        return account_hash in self.locked

    async def register_failure(self, account_hash: str) -> bool:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        count = self.failures.get(account_hash, 0) + 1
        self.failures[account_hash] = count
        if count >= self.max_attempts:
            self.locked.add(account_hash)
            return True
        return False

    async def clear(self, account_hash: str) -> None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        self.failures.pop(account_hash, None)
        self.locked.discard(account_hash)


class FakeEmailVerifyService:
    """测试用内存邮箱验证码服务，替代 Redis 实现（P1-3.8）。"""

    def __init__(self):
        self.codes: dict[str, str] = {}
        self.fail_redis = False

    async def issue_code(self, email: str) -> str | None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        code = "654321"
        self.codes[email] = code
        return code

    async def verify_code(self, email: str, code: str) -> bool:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        if self.codes.get(email) == code:
            self.codes.pop(email, None)
            return True
        return False

    async def delete_code(self, email: str) -> None:
        self.codes.pop(email, None)


class FakeOAuthPendingService:
    """测试用内存 OAuth 建号票据服务，替代 Redis 实现（P1-3.2）。"""

    def __init__(self):
        self.pending: dict[str, dict] = {}
        self.counter = 0
        self.fail_redis = False

    async def store(self, payload: dict, ttl: int = 600) -> str:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        self.counter += 1
        ticket = f"ticket-{self.counter}"
        self.pending[ticket] = payload
        return ticket

    async def consume(self, ticket: str) -> dict | None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        return self.pending.pop(ticket, None)

    async def restore(self, ticket: str, payload: dict, ttl: int = 600) -> None:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        self.pending[ticket] = payload


def build_test_client(override_current_user: bool = True) -> tuple[CompatTestClient, sessionmaker]:
    auth.password_reset_service = FakePasswordResetService()
    auth.password_reset_email_service = auth.EmailService()
    auth.email_verification_service = FakeEmailVerifyService()
    auth.email_verification_email_service = auth.EmailService()
    auth.oauth_pending_registration = FakeOAuthPendingService()
    auth.auth_rate_limiter = FakeRateLimiter()
    auth.oauth_code_guard = FakeCodeGuard()
    security.account_lockout_service = FakeAccountLockoutService()
    security.jti_revocation_service = FakeJtiService()
    security.refresh_token_service = FakeRefreshService()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Role.__table__,
            user_roles,
            PasswordHistory.__table__,
            AuditLog.__table__,  # P2-4.4：登录链路审计埋点
            ConsentRecord.__table__,  # P2-4.3/5.2：注册/绑定同意记录
        ],
    )

    app = FastAPI()
    app.include_router(auth.router)

    # P2-4.5：cookie 会话 CSRF 双重提交（复用 security.csrf_check，与 main.py 同实现）
    from fastapi.responses import JSONResponse

    from app.core.security import csrf_check

    @app.middleware("http")
    async def _test_csrf_guard(request, call_next):
        error = csrf_check(request)
        if error:
            return JSONResponse(status_code=403, content={"detail": error})
        return await call_next(request)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    async def override_get_current_user(request: Request) -> User:
        auth_header = request.headers.get("Authorization", "")
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        payload = security.verify_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        db = testing_session_local()
        try:
            user = db.query(User).filter(User.id == int(user_id)).first()
            validated_user = security._validate_user_status(user)
            db.expunge(validated_user)
            return validated_user
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[security.get_db] = override_get_db
    if override_current_user:
        app.dependency_overrides[auth.get_current_user] = override_get_current_user
        app.dependency_overrides[security.get_current_user] = override_get_current_user
    return CompatTestClient(app), testing_session_local


def create_user(
    session_factory: sessionmaker,
    *,
    username: str,
    email: str | None = None,
    password_hash: str,
    phone: str | None = None,
    is_active: bool = True,
) -> User:
    db = session_factory()
    try:
        user = User(
            username=username,
            email=email,
            phone=phone,
            password_hash=password_hash,
            full_name=username,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def set_user_active(session_factory: sessionmaker, user_id: int, is_active: bool) -> None:
    db = session_factory()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise AssertionError("测试用户不存在")
        user.is_active = is_active
        db.add(user)
        db.commit()
    finally:
        db.close()


def build_auth_headers(user_id: int) -> dict[str, str]:
    token = create_access_token(data={"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def _install_fake_verify_email_service(captured: dict) -> None:
    """替换邮箱验证邮件服务为捕获式 fake，便于断言收件人与验证码。"""

    class FakeEmailService:
        def is_configured(self) -> bool:
            return True

        async def send_email_verification_code(self, to_email: str, code: str) -> None:
            captured["email"] = to_email
            captured["code"] = code

    auth.email_verification_email_service = FakeEmailService()


_DEFAULT = object()


class _FakeRedisManager:
    """替代 LoopBoundRedis 的测试桩：get() 恒返回注入的假客户端。

    Redis 服务单测通过 `svc._redis = _FakeRedisManager(fake)` 注入，
    模拟连接错误/命令错误等场景（原字段 `_redis_client` 已改为按事件循环管理）。
    """

    def __init__(self, client):
        self._client = client

    async def get(self):
        return self._client

    def invalidate(self) -> None:
        pass


def _default_consent(phone: str | None) -> dict:
    """默认同意：勾选隐私政策与年满 14 周岁声明；带手机号时勾选手机号收集（敏感个人信息）。"""
    consent = {"privacy_policy": "v2", "age_eligibility": "v1"}
    if phone:
        consent["phone_collection"] = "v1"
    return consent


# P2-5.2：建号/绑定需携带用户勾选的同意（后端只记录真实勾选的项）
# 合规修订：注册/OAuth 建号需同时确认隐私政策与 age_eligibility（年满 14 周岁声明）
REGISTER_CONSENT = {"privacy_policy": "v2", "age_eligibility": "v1"}
OAUTH_CONSENT = {"privacy_policy": "v2", "oauth_sync": "v1", "age_eligibility": "v1"}
BIND_CONSENT = {"oauth_sync": "v1"}


def _two_step_register(
    client: CompatTestClient,
    *,
    username: str,
    email: str,
    password: str,
    phone: str | None = None,
    consent: dict | None | object = _DEFAULT,
) -> tuple[Response, Response, str]:
    """完成两步注册（发码 -> 确认），返回 (发码响应, 确认响应, 验证码)。

    consent：默认勾选隐私政策（带手机号时含 phone_collection）；
    显式传 None 表示"未勾选任何同意"，用于验证未同意不放行（P2-5.2）。
    """
    captured: dict[str, str] = {}
    _install_fake_verify_email_service(captured)

    send = client.post("/api/v1/auth/register/send-code", json={"email": email})
    if send.status_code != 200:
        return send, send, ""

    body: dict = {
        "username": username,
        "email": email,
        "password": password,
        "code": captured["code"],
    }
    if phone:
        body["phone"] = phone

    resolved = _default_consent(phone) if consent is _DEFAULT else consent
    if resolved is not None:
        body["consent"] = resolved

    confirm = client.post("/api/v1/auth/register/confirm", json=body)
    return send, confirm, captured["code"]


def test_register_and_login_with_username():
    client, _ = build_test_client()

    _, register_response, _ = _two_step_register(
        client,
        username="admin",
        email="Admin@example.com",
        password="Admin123",
        phone="13800138000",
    )

    assert register_response.status_code == 200
    payload = register_response.json()
    assert payload["user"]["username"] == "admin"
    assert payload["user"]["email"] == "admin@example.com"
    assert payload["user"]["phone"] == "13800138000"
    # 两步注册建号即已验证邮箱（P1-3.8）
    assert payload["user"]["email_verified"] is True

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "Admin123",
        },
    )

    assert login_response.status_code == 200
    login_payload = login_response.json()
    assert login_payload["user"]["username"] == "admin"
    assert _access_token(login_response)


def test_login_with_wrong_password_returns_clear_error():
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="writer",
        email="writer@example.com",
        phone="13900139000",
        password_hash=hash_password("correct-password"),
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "writer@example.com",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "用户名、邮箱、手机号或密码错误"


def test_request_reset_code_and_reset_password():
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="storyman",
        email="storyman@example.com",
        phone="13700137000",
        password_hash=hash_password("Oldpass123"),
    )

    captured: dict[str, str] = {}

    class FakeEmailService:
        def is_configured(self) -> bool:
            return True

        async def send_password_reset_code(self, to_email: str, code: str) -> None:
            captured["email"] = to_email
            captured["code"] = code

    auth.password_reset_email_service = FakeEmailService()

    request_response = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "storyman"},
    )

    assert request_response.status_code == 200
    assert request_response.json()["message"] == "如果账号存在且已绑定本地密码，验证码将发送到注册邮箱"
    assert request_response.json()["expires_in"] == 600
    assert request_response.json()["resend_in"] == 60
    assert captured["email"] == "storyman@example.com"
    assert len(captured["code"]) == 6

    reset_response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "account": "storyman",
            "code": captured["code"],
            "new_password": "Newpass123",
        },
    )

    assert reset_response.status_code == 200
    assert reset_response.json()["message"] == "密码重置成功，请使用新密码登录"

    old_login = client.post(
        "/api/v1/auth/login",
        json={"username": "storyman", "password": "Oldpass123"},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/login",
        json={"username": "storyman", "password": "Newpass123"},
    )
    assert new_login.status_code == 200


def test_reset_password_rejects_invalid_code():
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="coder",
        email="coder@example.com",
        phone="13600136000",
        password_hash=hash_password("Oldpass123"),
    )

    class FakeEmailService:
        def is_configured(self) -> bool:
            return True

        async def send_password_reset_code(self, _to_email: str, _code: str) -> None:
            return None

    auth.password_reset_email_service = FakeEmailService()

    request_response = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "coder"},
    )
    assert request_response.status_code == 200

    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "account": "coder",
            "code": "000000",
            "new_password": "Newpass123",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "验证码无效或已过期"


def test_request_reset_password_skips_oauth_only_account():
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="wechat_user",
        email="wechat_user@wechat.temp",
        password_hash=make_unusable_password_hash(),
    )

    captured: dict[str, str] = {}

    class FakeEmailService:
        def is_configured(self) -> bool:
            return True

        async def send_password_reset_code(self, to_email: str, code: str) -> None:
            captured["email"] = to_email
            captured["code"] = code

    auth.password_reset_email_service = FakeEmailService()

    response = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "wechat_user"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "如果账号存在且已绑定本地密码，验证码将发送到注册邮箱"
    assert captured == {}


def test_request_reset_password_requires_email_service_configuration():
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="mail_user",
        email="mail_user@example.com",
        phone="13400134000",
        password_hash=hash_password("Oldpass123"),
    )

    class FakeEmailService:
        def is_configured(self) -> bool:
            return False

    auth.password_reset_email_service = FakeEmailService()

    response = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "mail_user"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "找回密码邮件服务尚未完成服务端配置"


def test_reset_password_rejects_inactive_user_after_code_requested():
    client, session_factory = build_test_client()
    user = create_user(
        session_factory,
        username="disabled_writer",
        email="disabled@example.com",
        phone="13500135000",
        password_hash=hash_password("Oldpass123"),
        is_active=True,
    )

    captured: dict[str, str] = {}

    class FakeEmailService:
        def is_configured(self) -> bool:
            return True

        async def send_password_reset_code(self, to_email: str, code: str) -> None:
            captured["email"] = to_email
            captured["code"] = code

    auth.password_reset_email_service = FakeEmailService()

    request_response = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "disabled_writer"},
    )
    assert request_response.status_code == 200

    set_user_active(session_factory, user.id, False)

    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "account": "disabled_writer",
            "code": captured["code"],
            "new_password": "Newpass123",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "用户账户已被禁用"


def test_change_password_returns_chinese_success_message():
    client, session_factory = build_test_client()
    user = create_user(
        session_factory,
        username="settings_user",
        email="settings_user@example.com",
        phone="13300133000",
        password_hash=hash_password("Oldpass123"),
    )

    response = client.post(
        "/api/v1/auth/change-password",
        json={
            "old_password": "Oldpass123",
            "new_password": "Newpass123",
        },
        headers=build_auth_headers(user.id),
    )

    assert response.status_code == 200
    assert response.json()["message"] == "密码修改成功"

    new_login = client.post(
        "/api/v1/auth/login",
        json={"username": "settings_user", "password": "Newpass123"},
    )
    assert new_login.status_code == 200


def test_logout_returns_chinese_success_message():
    client, session_factory = build_test_client()
    user = create_user(
        session_factory,
        username="logout_user",
        email="logout_user@example.com",
        phone="13200132000",
        password_hash=hash_password("logout123"),
    )

    response = client.post(
        "/api/v1/auth/logout",
        headers=build_auth_headers(user.id),
    )

    assert response.status_code == 200
    assert response.json()["message"] == "退出登录成功"


# ============================================================
# P0-2.1 生产环境安全基线
# ============================================================

def test_settings_defaults_are_safe():
    """APP_ENV 必须存在且默认 development，DEBUG 默认必须为 False。"""
    from app.core.config import settings
    assert settings.APP_ENV == "development"
    assert settings.DEBUG is False


def test_development_env_whitelist_includes_localhost():
    """development 环境默认白名单必须包含本地 localhost 回调地址（否则本机 OAuth 直接 400）。"""
    from app.core.config import settings
    assert "http://localhost:5173/login/callback" in settings.OAUTH_REDIRECT_URI_WHITELIST


# ============================================================
# P0-2.2 支付宝 RSA2 签名与验签
# ============================================================

def _generate_rsa_keypair() -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def test_alipay_sign_and_verify_roundtrip():
    """支付宝 RSA2 签名可被对应公钥独立验证通过。"""
    private_pem, public_pem = _generate_rsa_keypair()
    service = auth.AlipayOAuthService(
        app_id="test_app",
        private_key=private_pem,
        public_key=public_pem,
        sandbox=False,
    )
    params = {
        "app_id": "test_app",
        "method": "alipay.system.oauth.token",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "code": "abc123",
    }
    sign = service._sign(params)
    assert sign
    # 用支付宝公钥独立验证签名内容
    content = oauth_svc.build_sign_content(params)
    public_key = oauth_svc.load_alipay_public_key(public_pem)
    public_key.verify(
        base64.b64decode(sign.encode("ascii")),
        content.encode("utf-8"),
        oauth_svc.padding.PKCS1v15(),
        oauth_svc.hashes.SHA256(),
    )


def test_alipay_get_access_token_includes_sign():
    """换取 token 的请求必须携带 RSA2 签名。"""
    private_pem, public_pem = _generate_rsa_keypair()
    service = auth.AlipayOAuthService(
        app_id="test_app",
        private_key=private_pem,
        public_key=public_pem,
        sandbox=False,
    )

    captured: dict = {}

    inner = {"access_token": "at", "user_id": "u"}
    # 真实网关约定（线上取证）：签名只覆盖内层包裹体紧凑 JSON，外层 sign 收尾
    inner_text = json.dumps(inner, separators=(",", ":"))
    private_key = oauth_svc.load_alipay_private_key(private_pem)
    sig = base64.b64encode(
        private_key.sign(
            inner_text.encode("utf-8"), oauth_svc.padding.PKCS1v15(), oauth_svc.hashes.SHA256()
        )
    ).decode("ascii")
    final_text = f'{{"alipay_system_oauth_token_response": {inner_text}, "sign": "{sig}"}}'
    payload_with_sign = json.loads(final_text)

    class FakePostResponse:
        text = final_text

        def raise_for_status(self):
            pass

        def json(self):
            return payload_with_sign

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data=None, **kwargs):
            captured["url"] = url
            captured["data"] = data
            return FakePostResponse()

    original = oauth_svc.httpx.AsyncClient
    oauth_svc.httpx.AsyncClient = FakeClient
    try:
        result = asyncio.run(service.get_access_token("code123"))
    finally:
        oauth_svc.httpx.AsyncClient = original

    assert result["access_token"] == "at"
    assert "sign" in captured["data"]
    assert captured["data"]["sign_type"] == "RSA2"


def test_alipay_verify_response_rejects_tampered():
    """支付宝响应被篡改后，验签必须失败。"""
    private_pem, public_pem = _generate_rsa_keypair()
    service = auth.AlipayOAuthService(
        app_id="test_app",
        private_key=private_pem,
        public_key=public_pem,
        sandbox=False,
    )

    inner = {"access_token": "at", "user_id": "u"}
    inner_text = json.dumps(inner, separators=(",", ":"))
    private_key = oauth_svc.load_alipay_private_key(private_pem)
    sig = base64.b64encode(
        private_key.sign(
            inner_text.encode("utf-8"), oauth_svc.padding.PKCS1v15(), oauth_svc.hashes.SHA256()
        )
    ).decode("ascii")

    # 正确响应验签通过（网关格式：内层包裹体为验签对象）
    ok_raw = f'{{"alipay_system_oauth_token_response": {inner_text}, "sign": "{sig}"}}'
    ok_payload = json.loads(ok_raw)
    assert service._verify_response(ok_raw, ok_payload) is True

    # 篡改响应体后验签失败（签名不变，内层内容已变）
    tampered_inner = json.dumps({"access_token": "evil", "user_id": "u"}, separators=(",", ":"))
    tampered_raw = f'{{"alipay_system_oauth_token_response": {tampered_inner}, "sign": "{sig}"}}'
    tampered_payload = json.loads(tampered_raw)
    assert service._verify_response(tampered_raw, tampered_payload) is False


def test_alipay_service_sandbox_gateway():
    """沙箱模式必须使用 openapi.alipaydev.com 网关。"""
    private_pem, public_pem = _generate_rsa_keypair()
    sandbox_service = auth.AlipayOAuthService(
        app_id="test_app", private_key=private_pem, public_key=public_pem, sandbox=True
    )
    prod_service = auth.AlipayOAuthService(
        app_id="test_app", private_key=private_pem, public_key=public_pem, sandbox=False
    )
    assert "alipaydev.com" in sandbox_service.auth_url
    assert "alipay.com" in prod_service.auth_url


# ============================================================
# P0-2.3 OAuth state 服务端原子消费
# ============================================================

class FakeOAuthStateService:
    """测试用内存 state 服务，替换 Redis 实现。"""

    def __init__(self):
        self.data: dict[str, dict] = {}
        self.fail_redis = False

    async def store(self, state: str, provider: str, redirect_uri: str, ttl: int = 600) -> None:
        if self.fail_redis:
            raise RuntimeError("redis down")
        self.data[state] = {"provider": provider, "redirect_uri": redirect_uri}

    async def consume(self, state: str, expected_provider: str) -> dict:
        if self.fail_redis:
            raise HTTPException(status_code=503, detail="认证服务暂时不可用")
        raw = self.data.pop(state, None)
        if not raw:
            raise HTTPException(status_code=400, detail="无效的登录状态，请重新发起")
        if raw["provider"] != expected_provider:
            raise HTTPException(status_code=400, detail="登录提供方不匹配")
        return raw


def _install_fake_state_service() -> FakeOAuthStateService:
    fake = FakeOAuthStateService()
    auth.oauth_state_service = fake
    return fake


class FakeAlipayOAuthService:
    """测试用支付宝服务，替换真实网关调用（避免依赖 .env 真实配置和网络）。"""

    def __init__(self, *args, **kwargs):
        pass

    def get_auth_url(self, redirect_uri: str, state=None) -> str:
        return "https://fake.alipay/auth"

    async def get_access_token(self, code: str) -> dict:
        return {"access_token": "fake_access_token", "user_id": "u1"}

    async def get_user_info(self, access_token: str) -> dict:
        return {"user_id": "u1", "nick_name": "测试用户"}


def _install_fake_alipay_service() -> None:
    auth.AlipayOAuthService = FakeAlipayOAuthService
    # 走到换票的测试必须同时替换 code 换票锁（真实实现依赖 Redis）
    auth.oauth_code_guard = FakeCodeGuard()


def test_oauth_callback_without_state_rejected():
    """缺少 state 的 OAuth 回调必须被拒绝。"""
    client, _ = build_test_client()
    _install_fake_state_service()
    _install_fake_alipay_service()
    response = client.post(
        "/api/v1/auth/alipay/callback",
        json={"code": "code_without_state"},
    )
    assert response.status_code == 400


def test_oauth_callback_state_mismatch_rejected():
    """state 与 provider 不匹配时必须被拒绝且一次性消费。"""
    client, _ = build_test_client()
    fake = _install_fake_state_service()
    _install_fake_alipay_service()
    asyncio.run(fake.store("st-1", "wechat", "https://your-domain.com/login/callback"))
    response = client.post(
        "/api/v1/auth/alipay/callback",
        json={"code": "code123", "state": "st-1"},
    )
    assert response.status_code == 400


def test_oauth_callback_with_valid_state_succeeds():
    """state 匹配时，首次 OAuth 回调返回建号票据（P1-3.2：不再自动建号）。"""
    client, session_factory = build_test_client()
    fake = _install_fake_state_service()
    _install_fake_alipay_service()
    # 白名单隔离：不得读取本机 .env 真实白名单
    saved_whitelist = auth.settings.OAUTH_REDIRECT_URI_WHITELIST
    auth.settings.OAUTH_REDIRECT_URI_WHITELIST = ["https://your-domain.com/login/callback"]
    asyncio.run(fake.store("st-ok", "alipay", "https://your-domain.com/login/callback"))
    try:
        response = client.post(
            "/api/v1/auth/alipay/callback",
            json={"code": "code123", "state": "st-ok"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "new_user"
        assert payload["registration_ticket"]
        assert payload.get("token") is None
        # 自动建号被移除：回调后不得存在任何新用户行（也无假邮箱）
        db = session_factory()
        try:
            assert db.query(User).count() == 0
        finally:
            db.close()
    finally:
        auth.settings.OAUTH_REDIRECT_URI_WHITELIST = saved_whitelist


def test_oauth_callback_rejects_tampered_redirect_uri():
    """state 中绑定的 redirect_uri 被篡改后，callback 必须拒绝（纵深校验）。"""
    client, _ = build_test_client()
    fake = _install_fake_state_service()
    _install_fake_alipay_service()
    asyncio.run(fake.store("st-bad-uri", "alipay", "http://evil.com/cb"))
    response = client.post(
        "/api/v1/auth/alipay/callback",
        json={"code": "code123", "state": "st-bad-uri"},
    )
    assert response.status_code == 400


def test_build_token_response_serializes_user_via_user_response_schema():
    """统一签发函数的用户序列化必须走 UserResponse，本地登录与 OAuth 响应一致，避免手搓字段分叉。"""
    from app.schemas.user import UserResponse

    _, session_factory = build_test_client()
    create_user(
        session_factory,
        username="payload_user",
        email="payload@example.com",
        password_hash=hash_password("Abcdef123"),
    )
    db = session_factory()
    try:
        user = db.query(User).filter(User.username == "payload_user").first()
        payload = asyncio.run(security.build_token_response(user))
        assert isinstance(payload["user"], UserResponse)
        assert payload["token_type"] == "bearer"
        assert payload["access_token"]
        assert payload["refresh_token"]
    finally:
        db.close()


def test_oauth_state_consume_is_single_use():
    """state 必须一次性消费：第二次使用返回 400。"""
    fake = _install_fake_state_service()
    asyncio.run(fake.store("st-single", "alipay", "https://your-domain.com/login/callback"))
    first = asyncio.run(fake.consume("st-single", "alipay"))
    assert first["provider"] == "alipay"
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(fake.consume("st-single", "alipay"))
    assert exc_info.value.status_code == 400


def test_oauth_state_fail_closed_when_redis_down():
    """Redis 不可用时 state 校验必须返回 503（fail-closed），不静默降级。"""
    fake = _install_fake_state_service()
    fake.fail_redis = True
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(fake.consume("any", "alipay"))
    assert exc_info.value.status_code == 503


# ============================================================
# P0-2.4 redirect_uri 精确白名单
# ============================================================

def test_validate_redirect_uri_rejects_evil_urls():
    """非法 redirect_uri 必须被拒绝。"""
    saved_env = auth.settings.APP_ENV
    saved_whitelist = auth.settings.OAUTH_REDIRECT_URI_WHITELIST
    auth.settings.APP_ENV = "production"
    auth.settings.OAUTH_REDIRECT_URI_WHITELIST = ["https://your-domain.com/login/callback"]
    try:
        evil_urls = [
            "https://your-domain.com.evil.com/login/callback",  # 子域名欺骗
            "https://your-domain.com/login/callback?x=1",  # query 注入
            "https://your-domain.com/login/callback#frag",  # fragment 注入
            "http://your-domain.com/login/callback",  # 生产强制 HTTPS
            "https://evil.com/login/callback",  # 域名不匹配
            "https://user@your-domain.com/login/callback",  # userinfo 注入
        ]
        for url in evil_urls:
            with pytest.raises(HTTPException) as exc_info:
                auth._validate_redirect_uri(url)
            assert exc_info.value.status_code == 400, f"URL 未被拒绝: {url}"
    finally:
        auth.settings.APP_ENV = saved_env
        auth.settings.OAUTH_REDIRECT_URI_WHITELIST = saved_whitelist


def test_validate_redirect_uri_accepts_whitelisted_url():
    """白名单内的 HTTPS 回调必须被接受。"""
    saved_env = auth.settings.APP_ENV
    saved_whitelist = auth.settings.OAUTH_REDIRECT_URI_WHITELIST
    auth.settings.APP_ENV = "production"
    auth.settings.OAUTH_REDIRECT_URI_WHITELIST = ["https://your-domain.com/login/callback"]
    try:
        auth._validate_redirect_uri("https://your-domain.com/login/callback")
    finally:
        auth.settings.APP_ENV = saved_env
        auth.settings.OAUTH_REDIRECT_URI_WHITELIST = saved_whitelist


# ============================================================
# P0-2.5 全局 token_version 吊销
# ============================================================

def test_get_current_user_rejects_stale_token_version():
    """token_version 与签发时不符（改密/重置/禁用后）的 token 必须返回 401。"""
    _, session_factory = build_test_client()
    user = create_user(
        session_factory,
        username="tv_user",
        email="tv_user@example.com",
        password_hash=hash_password("Oldpass123"),
    )

    db = session_factory()
    try:
        assert user.token_version == 1
    finally:
        db.close()

    # 签发时 tv=1，token_version=1 → 通过
    fresh_creds = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=create_access_token(data={"sub": str(user.id), "tv": 1}),
    )
    db = session_factory()
    try:
        result = asyncio.run(security.get_current_user(_dummy_request(), fresh_creds, db))
        assert result.id == user.id
    finally:
        db.close()

    # 模拟改密后 token_version 递增到 2，旧的 tv=1 token 失效
    db = session_factory()
    try:
        u = db.query(User).filter(User.id == user.id).first()
        u.token_version = 2
        db.add(u)
        db.commit()
    finally:
        db.close()

    stale_creds = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=create_access_token(data={"sub": str(user.id), "tv": 1}),
    )
    db = session_factory()
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(security.get_current_user(_dummy_request(), stale_creds, db))
        assert exc_info.value.status_code == 401
    finally:
        db.close()


def test_get_current_user_accepts_token_without_tv_during_migration():
    """迁移窗口期内，无 tv 的旧 token 应视为 tv=1 兼容（不集体掉线）。"""
    _, session_factory = build_test_client()
    user = create_user(
        session_factory,
        username="tv_migrate",
        email="tv_migrate@example.com",
        password_hash=hash_password("Oldpass123"),
    )
    legacy_creds = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=create_access_token(data={"sub": str(user.id)}),  # 无 tv
    )
    db = session_factory()
    try:
        result = asyncio.run(security.get_current_user(_dummy_request(), legacy_creds, db))
        assert result.id == user.id
    finally:
        db.close()


# ============================================================
# P0-2.6 账号枚举防护
# ============================================================

def test_register_duplicate_email_returns_unified_message():
    """重复邮箱在确认建号阶段必须返回统一文案，不暴露邮箱已存在。

    竞态场景：发码时邮箱未注册（正常拿到码），confirm 前被他人占用，
    建号阶段仍须统一文案拒绝（send-code 只拦"发码时刻已注册"的邮箱）。
    """
    client, session_factory = build_test_client()
    captured: dict[str, str] = {}
    _install_fake_verify_email_service(captured)
    send = client.post(
        "/api/v1/auth/register/send-code",
        json={"email": "dup@example.com"},
    )
    assert send.status_code == 200
    code = captured["code"]
    # confirm 前邮箱被占用（模拟竞态/重复注册）
    create_user(
        session_factory,
        username="first_user",
        email="dup@example.com",
        password_hash=hash_password("Abcdef123"),
    )
    confirm = client.post(
        "/api/v1/auth/register/confirm",
        json={
            "username": "second_user",
            "email": "dup@example.com",
            "password": "Abcdef123",
            "code": code,
            "consent": REGISTER_CONSENT,
        },
    )
    assert confirm.status_code == 400
    assert confirm.json()["detail"] == "注册失败，请检查输入信息"


def test_login_oauth_account_returns_unified_error():
    """第三方登录账户使用密码登录时，必须返回与普通失败一致的口径。"""
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="oauth_only",
        email="oauth_only@alipay.temp",
        password_hash=make_unusable_password_hash(),
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "oauth_only", "password": "whatever123"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "用户名、邮箱、手机号或密码错误"


# ============================================================
# P1-3.5 单会话登出（jti 吊销）
# ============================================================

def test_logout_revokes_only_current_session_token():
    """登出只吊销当前会话：旧 token 立即 401，新登录的 token 不受影响。"""
    client, session_factory = build_test_client(override_current_user=False)
    create_user(
        session_factory,
        username="jti_user",
        email="jti_user@example.com",
        password_hash=hash_password("Jtipass123"),
    )

    def _login() -> str:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "jti_user", "password": "Jtipass123"},
        )
        assert response.status_code == 200
        return _access_token(response)

    token = _login()
    me_headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=me_headers).status_code == 200

    logout = client.post("/api/v1/auth/logout", headers=me_headers)
    assert logout.status_code == 200

    # 登出后当前会话 token 立即失效（jti 黑名单）
    me_resp = client.get("/api/v1/auth/me", headers=me_headers)
    assert me_resp.status_code == 401

    # 重新登录签发新 jti，不受上一个会话登出影响
    new_token = _login()
    new_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert new_me.status_code == 200


def test_logout_does_not_affect_token_without_jti():
    """迁移窗口：无 jti 的旧 token 不受 jti 黑名单影响（无法吊销，随过期自然失效）。"""
    from datetime import datetime, timedelta, timezone

    client, session_factory = build_test_client(override_current_user=False)
    user = create_user(
        session_factory,
        username="legacy_user",
        email="legacy@example.com",
        password_hash=hash_password("Legacypass123"),
    )

    # 手工构造无 jti 的旧版 token（P0 改造之前签发形态）
    now = datetime.now(timezone.utc)
    legacy_token = jose_jwt.encode(
        {
            "sub": str(user.id),
            "tv": user.token_version,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        auth.settings.JWT_SECRET,
        algorithm=auth.settings.JWT_ALGORITHM,
    )
    legacy_headers = {"Authorization": f"Bearer {legacy_token}"}
    assert client.get("/api/v1/auth/me", headers=legacy_headers).status_code == 200

    # 新会话登录并登出（带 jti 的 token 被吊销）
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username": "legacy_user", "password": "Legacypass123"},
    )
    assert login_resp.status_code == 200
    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {_access_token(login_resp)}"},
    )
    assert logout.status_code == 200

    # 无 jti 旧 token 仍可用（迁移窗口放行）
    legacy_me = client.get("/api/v1/auth/me", headers=legacy_headers)
    assert legacy_me.status_code == 200


def test_get_current_user_returns_503_when_jti_redis_down():
    """jti 校验 fail-closed：Redis 不可用时拒绝请求（503），不静默放行。"""
    client, session_factory = build_test_client(override_current_user=False)
    user = create_user(
        session_factory,
        username="jti_redis_down",
        email="jti_redis@example.com",
        password_hash=hash_password("redispass123"),
    )
    token = security.create_access_token(
        data={"sub": str(user.id), "tv": user.token_version}
    )

    fake_jti = security.jti_revocation_service
    assert isinstance(fake_jti, FakeJtiService)
    fake_jti.fail_redis = True

    me_resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_resp.status_code == 503


# ============================================================
# P1-3.4 密码重置链路加固
# ============================================================

def test_request_reset_code_returns_503_when_redis_down():
    """找回密码验证码存储 fail-closed：Redis 不可用时返回 503（不再回退进程内存）。"""
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="redisdown",
        email="redisdown@example.com",
        password_hash=hash_password("Oldpass123"),
    )

    class FakeEmailService:
        def is_configured(self) -> bool:
            return True

        async def send_password_reset_code(self, _to_email: str, _code: str) -> None:
            return None

    auth.password_reset_email_service = FakeEmailService()

    fake_reset = auth.password_reset_service
    assert isinstance(fake_reset, FakePasswordResetService)
    fake_reset.fail_redis = True

    response = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "redisdown"},
    )
    assert response.status_code == 503


def test_password_reset_response_schema_has_no_dev_code():
    """dev_code 字段必须从响应模型中移除（验证码不得回传客户端，DEBUG 也不例外）。"""
    from app.schemas.user import PasswordResetCodeResponse

    assert "dev_code" not in PasswordResetCodeResponse.model_fields


def test_password_reset_service_fails_closed_without_redis():
    """服务层 fail-closed：Redis 不可用时验证码服务必须抛 503，不得回退进程内存。

    注意：端口用 1 而非 0——redis-py 会把 port=0 解析为默认 6379，本机若有
    真实 Redis 会误连成功（还污染共享实例）。
    """
    service = auth.PasswordResetService(redis_url="redis://127.0.0.1:1/0")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.issue_code(1))
    assert exc_info.value.status_code == 503


# ============================================================
# P1-3.1 登录与注册限流（账号+IP 维度）
# ============================================================

def test_login_account_rate_limit_returns_429():
    """账号维限流：同账号连续登录失败超过阈值后返回 429。"""
    client, _session_factory = build_test_client()

    statuses = [
        client.post(
            "/api/v1/auth/login",
            json={"username": "bruteforce", "password": "badpass123"},
        ).status_code
        for _ in range(6)
    ]
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429


def test_login_ip_rate_limit_returns_429():
    """IP 维限流：同来源连续请求超过阈值后返回 429（即使账号各不相同）。"""
    client, _session_factory = build_test_client()

    statuses = [
        client.post(
            "/api/v1/auth/login",
            json={"username": f"nouser{i}", "password": "badpass123"},
        ).status_code
        for i in range(21)
    ]
    assert statuses[:20] == [401] * 20
    assert statuses[20] == 429


def test_register_rate_limit_returns_429():
    """注册发码 IP 维限流：同来源连续请求超过阈值后返回 429。"""
    client, _session_factory = build_test_client()
    _install_fake_verify_email_service({})

    statuses = []
    for i in range(4):
        statuses.append(
            client.post(
                "/api/v1/auth/register/send-code",
                json={"email": f"reg_user_{i}@example.com"},
            ).status_code
        )
    assert statuses[:3] == [200] * 3
    assert statuses[3] == 429


def test_request_reset_code_account_rate_limit_returns_429():
    """找回密码验证码请求账号维限流：同账号短时间重复请求返回 429（防邮件轰炸）。"""
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="spamer",
        email="spamer@example.com",
        password_hash=hash_password("Oldpass123"),
    )

    class FakeEmailService:
        def is_configured(self) -> bool:
            return True

        async def send_password_reset_code(self, _to_email: str, _code: str) -> None:
            return None

    auth.password_reset_email_service = FakeEmailService()

    first = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "spamer"},
    )
    second = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "spamer"},
    )
    assert first.status_code == 200
    assert second.status_code == 429


# ============================================================
# P1 批次 1 复审修复（2026-08-27）
# ============================================================

def test_client_ip_prefers_nginx_x_real_ip():
    """_client_ip 必须优先读 nginx 设置的 X-Real-IP（反代后 request.client.host 是容器 IP，IP 限流会全站共桶）。"""
    from starlette.datastructures import Headers

    headers_with_real_ip = Headers({"x-real-ip": "203.0.113.10"})
    request = Request(scope={
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": headers_with_real_ip.raw,
        "client": ("172.17.0.1", 12345),
    })
    assert auth._client_ip(request) == "203.0.113.10"

    # 无 X-Real-IP（开发/测试直连）：回退 socket 地址
    headers_no_real_ip = Headers({})
    request_direct = Request(scope={
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": headers_no_real_ip.raw,
        "client": ("192.168.1.5", 54321),
    })
    assert auth._client_ip(request_direct) == "192.168.1.5"


def test_login_rate_limit_normalizes_account_case():
    """账号维限流 key 必须规范化：Alice@x.com 与 alice@x.com 是同一账号，应命中同一限流桶。"""
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="case_user",
        email="alice@example.com",
        password_hash=hash_password("casepass123"),
    )

    # 同一账号的多种大小写写法轮换（规范化后同桶）：第 6 次（limit=5）触发账号维 429
    variants = [
        "alice@example.com",
        "ALICE@example.com",
        "Alice@Example.com",
        "alice@example.com",
        "alice@EXAMPLE.com",
        "AlIcE@example.com",
    ]
    statuses = [
        client.post(
            "/api/v1/auth/login",
            json={"username": v, "password": "badpass123"},
        ).status_code
        for v in variants
    ]
    # 前 5 次打进同一桶（若不规范化，大小写变体会分桶、5 次全 401）
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429


def test_alipay_callback_marks_code_used_immediately_after_exchange():
    """换票拿到 access_token 即落 used 标记：用户信息接口失败后，同 code 重试必须直接 400（不再打网关）。"""
    client, _session_factory = build_test_client()

    fake_state = _install_fake_state_service()
    fake_guard = auth.oauth_code_guard
    assert isinstance(fake_guard, FakeCodeGuard)

    # 支付宝配置可用 + state 合法
    saved = {
        "ALIPAY_APP_ID": auth.settings.ALIPAY_APP_ID,
        "ALIPAY_PRIVATE_KEY": auth.settings.ALIPAY_PRIVATE_KEY,
        "ALIPAY_PUBLIC_KEY": auth.settings.ALIPAY_PUBLIC_KEY,
        "OAUTH_REDIRECT_URI_WHITELIST": auth.settings.OAUTH_REDIRECT_URI_WHITELIST,
    }
    auth.settings.ALIPAY_APP_ID = "test_app"
    auth.settings.ALIPAY_PRIVATE_KEY = "x"
    auth.settings.ALIPAY_PUBLIC_KEY = "x"
    auth.settings.OAUTH_REDIRECT_URI_WHITELIST = ["https://your-domain.com/login/callback"]

    class FakeUserInfoFailsService:
        """换票成功但用户信息失败：暴露 code 是否被提前标记。"""

        def __init__(self, *args, **kwargs):
            pass

        async def get_access_token(self, code: str) -> dict:
            return {"access_token": "at-1", "user_id": "2088001"}

        async def get_user_info(self, access_token: str) -> dict:
            return {"error": "20001", "error_description": "获取用户信息失败"}

    auth.AlipayOAuthService = FakeUserInfoFailsService
    asyncio.run(fake_state.store("st-fix1", "alipay", "https://your-domain.com/login/callback"))

    try:
        first = client.post(
            "/api/v1/auth/alipay/callback",
            json={"code": "fix-code-1", "state": "st-fix1"},
        )
        assert first.status_code == 400  # 用户信息失败 -> 400

        # code 已在换票成功时标记：新 state 重试同 code 不应再打网关
        asyncio.run(fake_state.store("st-fix2", "alipay", "https://your-domain.com/login/callback"))
        second = client.post(
            "/api/v1/auth/alipay/callback",
            json={"code": "fix-code-1", "state": "st-fix2"},
        )
        assert second.status_code == 400
        assert second.json()["detail"] == "授权码已被使用"
        # 网关不应被第二次调用（FakeUserInfoFailsService 无调用计数，此处以 used 集合为准）
        code_hash = fake_guard._hash("fix-code-1")
        assert code_hash in fake_guard.used
    finally:
        for key, value in saved.items():
            setattr(auth.settings, key, value)
        _install_fake_alipay_service()


# ============================================================
# P1-3.7 短 access token + 可吊销 refresh token
# ============================================================

def test_login_and_register_response_include_refresh_token():
    """登录与注册响应都必须携带 refresh_token（一次性下发，服务端只存哈希）。"""
    client, _ = build_test_client()

    _, register_response, _ = _two_step_register(
        client,
        username="refresh_user",
        email="refresh_user@example.com",
        password="Refreshpass123",
    )
    assert register_response.status_code == 200
    # P2-4.5 收尾：refresh_token 仅入 httpOnly cookie，body 不返回
    assert _refresh_token(register_response)

    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "refresh_user", "password": "Refreshpass123"},
    )
    assert login_response.status_code == 200
    assert _refresh_token(login_response)
    assert _refresh_token(login_response) != _refresh_token(register_response)


def test_access_token_default_ttl_is_short():
    """access token 默认有效期必须是短时（<=30 分钟），不再使用 24 小时。"""
    token = security.create_access_token(data={"sub": "1", "tv": 1})
    payload = security.verify_token(token)
    ttl_seconds = payload["exp"] - payload["iat"]

    minutes = security.settings.JWT_ACCESS_EXPIRATION_MINUTES
    assert minutes <= 30, "短 token 方案要求 access token 有效期不超过 30 分钟"
    assert abs(ttl_seconds - minutes * 60) <= 60


def _login_for_refresh(client: CompatTestClient) -> tuple[str, str]:
    """登录并返回 (access_token, refresh_token)。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "rt_user", "password": "Rtpass123"},
    )
    assert response.status_code == 200
    return _access_token(response), _refresh_token(response)


def _create_refresh_test_user(session_factory: sessionmaker) -> None:
    create_user(
        session_factory,
        username="rt_user",
        email="rt_user@example.com",
        password_hash=hash_password("Rtpass123"),
    )


def test_refresh_rotates_tokens_and_old_refresh_is_single_use():
    """refresh 成功签发新 access + 新 refresh；旧 refresh 原子消费后重用必须 401。"""
    client, session_factory = build_test_client(override_current_user=False)
    _create_refresh_test_user(session_factory)
    access_token, refresh_token = _login_for_refresh(client)

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_response.status_code == 200
    # P2-4.5 收尾：新令牌仅入 httpOnly cookie，body 不返回
    new_access = _access_token(refresh_response)
    new_refresh = _refresh_token(refresh_response)
    assert new_access
    assert new_refresh
    assert new_refresh != refresh_token

    # 新 access token 可正常访问受保护接口
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert me.status_code == 200

    # 旧 refresh 已被原子消费（GETDEL 语义）：重放 -> 401
    replay = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert replay.status_code == 401

    # 新 refresh 可继续轮换（链路不因重放攻击中断）
    second = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_refresh},
    )
    assert second.status_code == 200


def test_refresh_rejects_unknown_token():
    """伪造/未知 refresh token 一律 401，不泄露任何信息。"""
    client, session_factory = build_test_client()
    _create_refresh_test_user(session_factory)

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "totally-unknown-token"},
    )
    assert response.status_code == 401


def test_refresh_empty_value_returns_401_without_hitting_redis():
    """缺 refresh token（body 空 + 无 cookie）：直接 401，不打 Redis（P2-4.5 收尾）。"""
    client, session_factory = build_test_client()
    fake = security.refresh_token_service
    assert isinstance(fake, FakeRefreshService)
    original_acquire = fake.acquire_lock
    calls = 0

    async def counting_acquire(token: str) -> bool:
        nonlocal calls
        calls += 1
        return await original_acquire(token)

    fake.acquire_lock = counting_acquire  # type: ignore[method-assign]
    try:
        response = client.post("/api/v1/auth/refresh", json={})
        assert response.status_code == 401
        assert response.json()["detail"] == "登录状态已失效，请重新登录"
        assert calls == 0, "空 refresh 值必须短路，不得打 Redis 抢锁"
    finally:
        fake.acquire_lock = original_acquire


def test_refresh_concurrent_lock_returns_429():
    """同一 refresh token 并发刷新被短锁拦截（5 秒锁窗口内第二个请求 429）。"""
    client, session_factory = build_test_client()
    _create_refresh_test_user(session_factory)
    _, refresh_token = _login_for_refresh(client)

    fake = security.refresh_token_service
    assert isinstance(fake, FakeRefreshService)
    # 模拟另一并发请求正持有锁
    assert asyncio.run(fake.acquire_lock(refresh_token))

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 429


def test_refresh_rejects_after_token_version_increment():
    """改密/重置/禁用递增 tv 后，refresh 必须失效（全设备下线语义覆盖 refresh 链路）。"""
    client, session_factory = build_test_client()
    _create_refresh_test_user(session_factory)
    _, refresh_token = _login_for_refresh(client)

    # 模拟改密：tv 递增
    db = session_factory()
    try:
        user = db.query(User).filter(User.username == "rt_user").first()
        user.token_version += 1
        db.add(user)
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 401


def test_refresh_rejects_disabled_user():
    """禁用用户刷新 refresh 必须失败。"""
    client, session_factory = build_test_client()
    user = create_user(
        session_factory,
        username="rt_user",
        email="rt_user@example.com",
        password_hash=hash_password("Rtpass123"),
    )
    _, refresh_token = _login_for_refresh(client)
    set_user_active(session_factory, user.id, False)

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 401


def test_refresh_returns_503_when_redis_down():
    """refresh 链路 fail-closed：Redis 不可用返回 503，不静默放行。"""
    client, session_factory = build_test_client()
    _create_refresh_test_user(session_factory)
    _, refresh_token = _login_for_refresh(client)

    fake = security.refresh_token_service
    assert isinstance(fake, FakeRefreshService)
    fake.fail_redis = True

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 503


def test_logout_with_refresh_token_revokes_refresh_session():
    """登出必须吊销 refresh token：否则短 access 过期后 refresh 会"复活"会话。"""
    client, session_factory = build_test_client(override_current_user=False)
    _create_refresh_test_user(session_factory)
    access_token, refresh_token = _login_for_refresh(client)
    headers = {"Authorization": f"Bearer {access_token}"}

    logout = client.post(
        "/api/v1/auth/logout",
        headers=headers,
        json={"refresh_token": refresh_token},
    )
    assert logout.status_code == 200

    # access 立即失效（jti 吊销）
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 401

    # refresh 同步失效：换不出新 access
    refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh.status_code == 401


def test_logout_without_redis_still_returns_503():
    """登出吊销 refresh 依赖 Redis：不可用时 fail-closed 返回 503。"""
    client, session_factory = build_test_client()
    _create_refresh_test_user(session_factory)
    _, refresh_token = _login_for_refresh(client)

    fake = security.refresh_token_service
    assert isinstance(fake, FakeRefreshService)
    fake.fail_redis = True

    response = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 503


def test_resolve_user_from_token_enforces_jti_and_tv():
    """memories 等裸 token（query parameter）场景必须走完整校验链路（tv + jti）。

    登出/改密后，URL 中的旧 token 不得再通过校验（P1 批次 1 遗留边角收口）。
    """
    client, session_factory = build_test_client(override_current_user=False)
    user = create_user(
        session_factory,
        username="raw_token_user",
        email="raw_token@example.com",
        password_hash=hash_password("rawpass123"),
    )
    token = security.create_access_token(
        data={"sub": str(user.id), "tv": user.token_version}
    )

    # 有效 token 可解析
    db = session_factory()
    try:
        resolved = asyncio.run(security.resolve_user_from_token(token, db))
        assert resolved is not None
        assert resolved.id == user.id
    finally:
        db.close()

    # 登出吊销 jti 后 -> 拒绝
    payload = security.verify_token(token)
    asyncio.run(
        security.jti_revocation_service.revoke(str(payload["jti"]), int(payload["exp"]))
    )
    db = session_factory()
    try:
        assert asyncio.run(security.resolve_user_from_token(token, db)) is None
    finally:
        db.close()

    # tv 递增（改密/禁用）后 -> 拒绝
    token_v2 = security.create_access_token(
        data={"sub": str(user.id), "tv": user.token_version}
    )
    db = session_factory()
    try:
        user_row = db.query(User).filter(User.id == user.id).first()
        user_row.token_version += 1
        db.add(user_row)
        db.commit()
    finally:
        db.close()
    db = session_factory()
    try:
        assert asyncio.run(security.resolve_user_from_token(token_v2, db)) is None
    finally:
        db.close()


# ============================================================
# P1-3.7 复审修复（2026-08-28 批次 2 用户复审）
# ============================================================

def test_refresh_consume_does_not_fallback_to_lua_on_connection_error():
    """consume 的 GETDEL 失败必须区分原因：连接/超时/认证类异常不得回退 Lua。

    现状（修复前）把 getdel 任意异常都当"旧 Redis 不支持 GETDEL"走 Lua 回退，
    Lua 在真实 Redis 挂时返回 None -> 路由把真实 503 误判为"token 不存在"-> 401 踢用户。
    修复后：仅 ResponseError（unknown command）回退 Lua，其余直接 503（fail-closed）。
    """
    from app.core.security import RefreshTokenService
    from redis.exceptions import ConnectionError as RedisConnectionError

    svc = RefreshTokenService(redis_url="redis://localhost:6379/0")

    class FakeClient:
        def __init__(self):
            self.eval_called = False

        async def getdel(self, key):
            raise RedisConnectionError("connection lost")

        async def eval(self, *args, **kwargs):
            self.eval_called = True
            return None

    fake = FakeClient()
    svc._redis = _FakeRedisManager(fake)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.consume("some-token"))
    assert exc_info.value.status_code == 503
    assert fake.eval_called is False, "连接失败不得走 Lua 兼容路径"


def test_refresh_consume_falls_back_to_lua_on_unknown_command():
    """仅命令不支持（Redis < 6.2 无 GETDEL -> ResponseError）才回退 Lua 原子 GET+DEL。"""
    from app.core.security import RefreshTokenService
    from redis.exceptions import ResponseError

    svc = RefreshTokenService(redis_url="redis://localhost:6379/0")

    class FakeClient:
        def __init__(self):
            self.eval_called = False

        async def getdel(self, key):
            raise ResponseError("unknown command 'GETDEL'")

        async def eval(self, script, numkeys, key):
            self.eval_called = True
            return '{"user_id": 1, "tv": 1}'

    fake = FakeClient()
    svc._redis = _FakeRedisManager(fake)

    result = asyncio.run(svc.consume("some-token"))
    assert result == '{"user_id": 1, "tv": 1}'
    assert fake.eval_called is True


def test_refresh_consume_does_not_fallback_to_lua_on_other_response_errors():
    """ResponseError 判定只认"命令不支持"：WRONGTYPE/OOM 等其余服务端错误
    不得走 Lua 回退（会把真实故障误判为 token 不存在 -> 401 踢用户），必须 503。"""
    from app.core.security import RefreshTokenService
    from redis.exceptions import ResponseError

    svc = RefreshTokenService(redis_url="redis://localhost:6379/0")

    class FakeClient:
        def __init__(self):
            self.eval_called = False

        async def getdel(self, key):
            raise ResponseError(
                "WRONGTYPE Operation against a key holding the wrong kind of value"
            )

        async def eval(self, *args, **kwargs):
            self.eval_called = True
            return None

    fake = FakeClient()
    svc._redis = _FakeRedisManager(fake)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.consume("some-token"))
    assert exc_info.value.status_code == 503
    assert fake.eval_called is False, "非 unknown command 的 ResponseError 不得走 Lua 兼容路径"


def test_refresh_issue_failure_restores_old_refresh():
    """签发失败（503）后 NX 写回旧值：用户用原 refresh 重试仍可换票（防掉线核心分支）。"""
    client, session_factory = build_test_client()
    _create_refresh_test_user(session_factory)
    _, refresh_token = _login_for_refresh(client)

    fake = security.refresh_token_service
    assert isinstance(fake, FakeRefreshService)
    fake.fail_issue = True  # 模拟签发阶段 Redis 写失败

    first = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert first.status_code == 503

    fake.fail_issue = False
    # restore 成功后旧 refresh 仍可用：不因一次签发失败把用户踢下线
    second = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert second.status_code == 200
    assert _access_token(second)
    assert _refresh_token(second) != refresh_token


# ============================================================
# P1 批次 3：3.8 邮箱验证（两步注册 + 登录态验证）
# ============================================================

def test_legacy_single_step_register_removed():
    """单步 /register 端点必须下线（双路径会绕过邮箱验证）。"""
    client, _ = build_test_client()
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "legacy_reg",
            "email": "legacy_reg@example.com",
            "password": "Legacypass123",
        },
    )
    assert response.status_code == 404


def test_register_send_code_unified_response_for_registered_email():
    """防注册枚举：邮箱已注册时发码响应与未注册完全一致（统一 200）。

    修复前：已注册邮箱也会真实发码（对已有用户的邮件轰炸/钓鱼面）。
    修复后：同样 200 同文案，但已存在则跳过发码、不发信（已注册用户无需注册码）。
    """
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="existing_owner",
        email="taken@example.com",
        password_hash=hash_password("Abcdef123"),
    )
    captured: dict[str, str] = {}
    _install_fake_verify_email_service(captured)

    response = client.post(
        "/api/v1/auth/register/send-code",
        json={"email": "taken@example.com"},
    )
    assert response.status_code == 200
    assert "验证码" in response.json()["message"]
    assert captured == {}, "已注册邮箱不得真实发信"


def test_register_confirm_rejects_invalid_code():
    """验证码错误时不得建号，统一返回验证码无效文案。"""
    client, session_factory = build_test_client()
    captured: dict[str, str] = {}
    _install_fake_verify_email_service(captured)
    send = client.post(
        "/api/v1/auth/register/send-code",
        json={"email": "wrongcode@example.com"},
    )
    assert send.status_code == 200

    response = client.post(
        "/api/v1/auth/register/confirm",
        json={
            "username": "wrongcode_user",
            "email": "wrongcode@example.com",
            "password": "Wrongpass123",
            "code": "000000",
            "consent": REGISTER_CONSENT,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "验证码无效或已过期"
    db = session_factory()
    try:
        assert db.query(User).filter(User.username == "wrongcode_user").first() is None
    finally:
        db.close()


def test_register_confirm_without_send_code_rejected():
    """未发码直接确认建号必须被拒绝（验证码不存在）。"""
    client, _ = build_test_client()
    response = client.post(
        "/api/v1/auth/register/confirm",
        json={
            "username": "nosend_user",
            "email": "nosend@example.com",
            "password": "Nosendpass1",
            "code": "654321",
            "consent": REGISTER_CONSENT,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "验证码无效或已过期"


def test_register_send_code_returns_503_when_redis_down():
    """邮箱验证码存储 fail-closed：Redis 不可用时返回 503。"""
    client, _ = build_test_client()
    _install_fake_verify_email_service({})
    fake = auth.email_verification_service
    assert isinstance(fake, FakeEmailVerifyService)
    fake.fail_redis = True

    response = client.post(
        "/api/v1/auth/register/send-code",
        json={"email": "redisdown2@example.com"},
    )
    assert response.status_code == 503


def test_email_verification_service_fails_closed_without_redis():
    """服务层 fail-closed：Redis 不可用时邮箱验证码服务必须抛 503，不得回退进程内存。

    端口用 1 而非 0（redis-py 会把 port=0 解析为默认 6379，可能误连本机真实 Redis）。
    """
    from app.services.email_verification_service import EmailVerificationService

    service = EmailVerificationService(redis_url="redis://127.0.0.1:1/0")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.issue_code("probe@example.com"))
    assert exc_info.value.status_code == 503


def test_verify_email_flow_marks_user_verified():
    """登录态邮箱验证：发码 + 确认后 /me 返回新邮箱与 email_verified=True。"""
    client, session_factory = build_test_client()
    user = create_user(
        session_factory,
        username="verify_user",
        email="verify_user@example.com",
        password_hash=hash_password("verifypass1"),
    )
    captured: dict[str, str] = {}
    _install_fake_verify_email_service(captured)

    send = client.post(
        "/api/v1/auth/verify-email/request-code",
        json={"email": "bound@example.com"},
        headers=build_auth_headers(user.id),
    )
    assert send.status_code == 200
    assert captured["email"] == "bound@example.com"

    confirm = client.post(
        "/api/v1/auth/verify-email/confirm",
        json={"email": "bound@example.com", "code": captured["code"]},
        headers=build_auth_headers(user.id),
    )
    assert confirm.status_code == 200

    me = client.get("/api/v1/auth/me", headers=build_auth_headers(user.id))
    assert me.status_code == 200
    payload = me.json()
    assert payload["email"] == "bound@example.com"
    assert payload["email_verified"] is True


def test_verify_email_confirm_rejects_email_taken_by_other():
    """绑定已被他人占用的邮箱必须失败，统一文案不暴露占用者身份。"""
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="owner_user",
        email="occupied@example.com",
        password_hash=hash_password("Abcdef123"),
    )
    binder = create_user(
        session_factory,
        username="binder_user",
        email="binder@example.com",
        password_hash=hash_password("Abcdef123"),
    )
    captured: dict[str, str] = {}
    _install_fake_verify_email_service(captured)

    send = client.post(
        "/api/v1/auth/verify-email/request-code",
        json={"email": "occupied@example.com"},
        headers=build_auth_headers(binder.id),
    )
    assert send.status_code == 200

    confirm = client.post(
        "/api/v1/auth/verify-email/confirm",
        json={"email": "occupied@example.com", "code": captured["code"]},
        headers=build_auth_headers(binder.id),
    )
    assert confirm.status_code == 400
    assert confirm.json()["detail"] == "邮箱验证失败，请检查输入信息"


def test_reset_password_marks_email_verified():
    """重置密码成功即证明邮箱所有权：重置后 email_verified 置为 True（解存量死锁决策）。"""
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="unverified_user",
        email="unverified@example.com",
        password_hash=hash_password("Oldpass123"),
    )

    captured: dict[str, str] = {}

    class FakeEmailService:
        def is_configured(self) -> bool:
            return True

        async def send_password_reset_code(self, to_email: str, code: str) -> None:
            captured["email"] = to_email
            captured["code"] = code

    auth.password_reset_email_service = FakeEmailService()

    request_response = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "unverified_user"},
    )
    assert request_response.status_code == 200

    reset_response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "account": "unverified_user",
            "code": captured["code"],
            "new_password": "Newpass123",
        },
    )
    assert reset_response.status_code == 200

    db = session_factory()
    try:
        user = db.query(User).filter(User.username == "unverified_user").first()
        assert user.email_verified is True
        assert user.email_verified_at is not None
    finally:
        db.close()


# ============================================================
# P1 批次 3：3.2 OAuth 首次建号确认（Redis 票据）
# ============================================================

def test_oauth_state_consume_does_not_fallback_to_lua_on_connection_error():
    """OAuth state consume 与 refresh/pending 同构：连接失败不得回退 Lua，必须 503。

    现状（修复前）把 getdel 任意异常都当"旧 Redis 不支持 GETDEL"走 Lua 回退，
    Lua 在真实 Redis 挂时返回空 -> 路由把真实故障误判为"无效的登录状态"400，
    用户需重新发起授权。
    """
    from app.api.v1.auth import OAuthStateService
    from redis.exceptions import ConnectionError as RedisConnectionError

    svc = OAuthStateService(redis_url="redis://localhost:6379/0")

    class FakeClient:
        def __init__(self):
            self.eval_called = False

        async def getdel(self, key):
            raise RedisConnectionError("connection lost")

        async def eval(self, *args, **kwargs):
            self.eval_called = True
            return None

    fake = FakeClient()
    svc._redis = _FakeRedisManager(fake)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.consume("some-state", "alipay"))
    assert exc_info.value.status_code == 503
    assert fake.eval_called is False, "连接失败不得走 Lua 兼容路径"


def test_oauth_state_consume_does_not_fallback_to_lua_on_other_response_errors():
    """同 refresh：ResponseError 只认 unknown command，WRONGTYPE/OOM 等必须 503 不进 Lua。"""
    from app.api.v1.auth import OAuthStateService
    from redis.exceptions import ResponseError

    svc = OAuthStateService(redis_url="redis://localhost:6379/0")

    class FakeClient:
        def __init__(self):
            self.eval_called = False

        async def getdel(self, key):
            raise ResponseError(
                "WRONGTYPE Operation against a key holding the wrong kind of value"
            )

        async def eval(self, *args, **kwargs):
            self.eval_called = True
            return None

    fake = FakeClient()
    svc._redis = _FakeRedisManager(fake)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.consume("some-state", "alipay"))
    assert exc_info.value.status_code == 503
    assert fake.eval_called is False, "非 unknown command 的 ResponseError 不得走 Lua 兼容路径"


def test_oauth_consume_does_not_fallback_to_lua_on_connection_error():
    """OAuth 建号票据 consume 与 refresh 同构：连接失败不得回退 Lua，必须 503。

    现状（修复前）把 getdel 任意异常都当"旧 Redis 不支持 GETDEL"走 Lua 回退，
    Lua 在真实 Redis 挂时返回空 -> 路由把真实故障误判为"票据过期"-> 用户卡在确认页。
    """
    from app.api.v1.auth import OAuthPendingRegistrationService
    from redis.exceptions import ConnectionError as RedisConnectionError

    svc = OAuthPendingRegistrationService(redis_url="redis://localhost:6379/0")

    class FakeClient:
        def __init__(self):
            self.eval_called = False

        async def getdel(self, key):
            raise RedisConnectionError("connection lost")

        async def eval(self, *args, **kwargs):
            self.eval_called = True
            return None

    fake = FakeClient()
    svc._redis = _FakeRedisManager(fake)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.consume("some-ticket"))
    assert exc_info.value.status_code == 503
    assert fake.eval_called is False, "连接失败不得走 Lua 兼容路径"


def test_oauth_consume_does_not_fallback_to_lua_on_other_response_errors():
    """同 refresh：ResponseError 只认 unknown command，WRONGTYPE/OOM 等必须 503 不进 Lua。"""
    from app.api.v1.auth import OAuthPendingRegistrationService
    from redis.exceptions import ResponseError

    svc = OAuthPendingRegistrationService(redis_url="redis://localhost:6379/0")

    class FakeClient:
        def __init__(self):
            self.eval_called = False

        async def getdel(self, key):
            raise ResponseError(
                "WRONGTYPE Operation against a key holding the wrong kind of value"
            )

        async def eval(self, *args, **kwargs):
            self.eval_called = True
            return None

    fake = FakeClient()
    svc._redis = _FakeRedisManager(fake)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(svc.consume("some-ticket"))
    assert exc_info.value.status_code == 503
    assert fake.eval_called is False, "非 unknown command 的 ResponseError 不得走 Lua 兼容路径"


def encrypt_openid_columns(field: str, value: str) -> dict:
    """构造 `{field}_hash` / `{field}_encrypted` 字段对（P2-4.1：库内不存明文 openid）。"""
    crypto_obj = crypto.get_openid_crypto()
    return {
        f"{field}_hash": crypto_obj.lookup_hash(value),
        f"{field}_encrypted": crypto_obj.encrypt(value),
    }


def build_pending_payload(provider: str, openid: str = "", **extra) -> dict:
    """构造待建号票据：openid 以密文入 Redis（P2-4.1），与 callback 写入口径一致。"""
    crypto_obj = crypto.get_openid_crypto()
    payload = {
        "provider": provider,
        "openid": crypto_obj.encrypt(openid) if openid else "",
    }
    payload.update(extra)
    return payload


def test_oauth_confirm_creates_user_with_pending_ticket():
    """票据确认建号：返回 token，用户无邮箱（不再分配假邮箱）；票据一次性消费。"""
    client, session_factory = build_test_client()
    fake = auth.oauth_pending_registration
    assert isinstance(fake, FakeOAuthPendingService)
    ticket = asyncio.run(
        fake.store(build_pending_payload("alipay", "2088001", nickname="支付宝用户"))
    )

    response = client.post(
        "/api/v1/auth/oauth/confirm",
        json={"ticket": ticket, "action": "confirm", "consent": OAUTH_CONSENT},
    )
    assert response.status_code == 200
    payload = response.json()
    # P2-4.5 收尾：oauth/confirm 不得把令牌漏回 body，token 只入 httpOnly cookie
    assert "access_token" not in payload
    assert "refresh_token" not in payload
    assert "csrf_token" not in payload
    assert response.cookies.get(security.access_cookie_name()), "confirm 建号必须写 access cookie"
    assert payload["user"]["email"] is None
    assert payload["user"]["email_verified"] is False

    db = session_factory()
    try:
        user = (
            db.query(User)
            .filter(User.alipay_openid_hash == crypto.get_openid_crypto().lookup_hash("2088001"))
            .first()
        )
        assert user is not None
        assert user.email is None
    finally:
        db.close()

    # 票据已被 GETDEL 原子消费：重放必须 400（防并发双建号）
    replay = client.post(
        "/api/v1/auth/oauth/confirm",
        json={"ticket": ticket, "action": "confirm", "consent": OAUTH_CONSENT},
    )
    assert replay.status_code == 400
    assert replay.json()["detail"] == "注册票据已过期，请重新登录"


def test_oauth_confirm_restores_ticket_on_user_creation_failure(monkeypatch):
    """确认建号在 GETDEL 消费之后：建号/发 token 失败时票据必须写回，用户可重试。

    现状（修复前）consume 后直接建号，create_confirmed_user 或签发 token 失败时
    票据已被删除，用户只能重走 OAuth（与 refresh 的 restore 语义一致）。
    """
    from app.services.oauth_service import OAuthService

    client, session_factory = build_test_client()
    fake = auth.oauth_pending_registration
    assert isinstance(fake, FakeOAuthPendingService)
    ticket = asyncio.run(
        fake.store(build_pending_payload("alipay", "2088002", nickname="支付宝用户"))
    )

    original_create = OAuthService.create_confirmed_user

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(OAuthService, "create_confirmed_user", staticmethod(boom))

    # TestClient 默认 raise_server_exceptions=True：500 时把服务器异常重新抛出
    with pytest.raises(RuntimeError):
        client.post(
            "/api/v1/auth/oauth/confirm",
            json={"ticket": ticket, "action": "confirm", "consent": OAUTH_CONSENT},
        )
    # 票据被写回：用户可直接重试，无需重新 OAuth
    assert ticket in fake.pending

    monkeypatch.setattr(OAuthService, "create_confirmed_user", original_create)
    retry = client.post(
        "/api/v1/auth/oauth/confirm",
        json={"ticket": ticket, "action": "confirm", "consent": OAUTH_CONSENT},
    )
    assert retry.status_code == 200
    assert ticket not in fake.pending  # 重试成功，票据被消费


def test_oauth_confirm_does_not_restore_invalid_provider_ticket():
    """无效 provider / 空 openid 的坏票据：400 后不得 NX 写回（坏票不得复活）。

    与 refresh 的"401 不写回"语义一致：客户端错误不 restore；
    只有建号/签发 token 的服务端失败才写回让用户可重试。
    """
    client, session_factory = build_test_client()
    fake = auth.oauth_pending_registration
    assert isinstance(fake, FakeOAuthPendingService)
    ticket = asyncio.run(fake.store(build_pending_payload("unknown", "", nickname="x")))

    response = client.post(
        "/api/v1/auth/oauth/confirm",
        json={"ticket": ticket, "action": "confirm", "consent": OAUTH_CONSENT},
    )
    assert response.status_code == 400
    assert ticket not in fake.pending, "400 客户端错误不得把坏票据写回复活"


def test_oauth_confirm_cancel_consumes_ticket_without_user():
    """取消建号：票据被消费但不建用户。"""
    client, session_factory = build_test_client()
    fake = auth.oauth_pending_registration
    assert isinstance(fake, FakeOAuthPendingService)
    ticket = asyncio.run(
        fake.store(build_pending_payload("wechat", "wx-open-1", nickname="微信用户"))
    )

    response = client.post(
        "/api/v1/auth/oauth/confirm",
        json={"ticket": ticket, "action": "cancel"},
    )
    assert response.status_code == 200

    db = session_factory()
    try:
        assert db.query(User).count() == 0
    finally:
        db.close()

    replay = client.post(
        "/api/v1/auth/oauth/confirm",
        json={"ticket": ticket, "action": "confirm", "consent": OAUTH_CONSENT},
    )
    assert replay.status_code == 400


def test_oauth_confirm_unknown_ticket_rejected():
    """伪造/过期票据必须被拒绝。"""
    client, _ = build_test_client()
    response = client.post(
        "/api/v1/auth/oauth/confirm",
        json={"ticket": "no-such-ticket", "action": "confirm", "consent": OAUTH_CONSENT},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "注册票据已过期，请重新登录"


def test_wechat_unionid_priority_matches_existing_and_updates_openid():
    """微信匹配必须 unionid 优先：命中已有用户后回写最新 openid（可能换了 AppId）。"""
    _, session_factory = build_test_client()
    db = session_factory()
    try:
        user = User(
            username="wx_union_user",
            email=None,
            password_hash=make_unusable_password_hash(),
            full_name="wx_union_user",
            **encrypt_openid_columns("wechat_openid", "old_openid"),
            **encrypt_openid_columns("wechat_unionid", "union-1"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        found = asyncio.run(
            auth.OAuthService.handle_wechat_login(
                db,
                {"nickname": "微信用户"},
                openid="new_openid",
                unionid="union-1",
            )
        )
        assert found is not None
        assert found.id == user.id
        db.refresh(user)
        assert (
            crypto.get_openid_crypto().decrypt(user.wechat_openid_encrypted) == "new_openid"
        )

        # 未知身份（无匹配）不再自动建号，返回 None（由 callback 发改号票据）
        assert (
            asyncio.run(
                auth.OAuthService.handle_wechat_login(
                    db, {"nickname": "新用户"}, openid="stranger", unionid=None
                )
            )
            is None
        )
    finally:
        db.close()


def test_oauth_user_stores_only_hash_and_ciphertext():
    """建号后库中不得残留明文 openid：只存确定性查找哈希（UNIQUE）+ Fernet 密文。"""
    client, session_factory = build_test_client()
    fake = auth.oauth_pending_registration
    ticket = asyncio.run(
        fake.store(build_pending_payload("alipay", "2088003", nickname="支付宝用户"))
    )
    assert client.post(
        "/api/v1/auth/oauth/confirm", json={"ticket": ticket, "action": "confirm", "consent": OAUTH_CONSENT}
    ).status_code == 200

    crypto_obj = crypto.get_openid_crypto()
    db = session_factory()
    try:
        assert not hasattr(User, "alipay_openid"), "明文 openid 列必须已删除"
        user = (
            db.query(User)
            .filter(User.alipay_openid_hash == crypto_obj.lookup_hash("2088003"))
            .first()
        )
        assert user is not None
        assert "2088003" not in (user.alipay_openid_encrypted or ""), "密文不得含明文"
        assert crypto_obj.decrypt(user.alipay_openid_encrypted) == "2088003"
    finally:
        db.close()


def test_oauth_username_does_not_leak_openid():
    """username 必须不可反推：不得包含 openid 明文片段（P2-4.1）。

    旧实现取 openid 明文后 12 位，而 username 随 UserResponse 下发到前端，
    等于把 openid 的大部分泄露出去，加密存储形同虚设。改为 HMAC 哈希片段：
    不可反推，且同一 openid 仍稳定映射到同一 username。
    """
    client, _ = build_test_client()
    fake = auth.oauth_pending_registration
    openid = "2088001234567890"
    ticket = asyncio.run(
        fake.store(build_pending_payload("alipay", openid, nickname="支付宝用户"))
    )
    response = client.post(
        "/api/v1/auth/oauth/confirm", json={"ticket": ticket, "action": "confirm", "consent": OAUTH_CONSENT}
    )
    assert response.status_code == 200

    username = response.json()["user"]["username"]
    assert username.startswith("alipay_")
    assert openid[-12:] not in username, "username 不得含 openid 明文片段"
    assert username == f"alipay_{crypto.get_openid_crypto().lookup_hash(openid)[:12]}"


def test_oauth_confirm_rejects_undecryptable_ticket_without_server_error(monkeypatch):
    """加密密钥已轮换时，在途票据不可解：须按"票据过期"处理（400），不得 500。

    坏票据不写回（与既有 400 语义一致），用户重新发起授权即可。
    """
    client, _ = build_test_client()
    fake = auth.oauth_pending_registration
    # 用另一把加密密钥模拟"轮换前签发的在途票据"
    rotated = crypto.OpenIDCrypto(
        crypto.settings.OPENID_LOOKUP_KEY, "rAI1wyJSq-gIkjEuLqOiBcA-W6KI4eqigC0YqwKygVk="
    )
    ticket = asyncio.run(
        fake.store({"provider": "alipay", "openid": rotated.encrypt("2088004"), "nickname": "支付宝用户"})
    )

    response = client.post(
        "/api/v1/auth/oauth/confirm", json={"ticket": ticket, "action": "confirm", "consent": OAUTH_CONSENT}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "注册票据已过期，请重新登录"
    assert ticket not in fake.pending, "不可解的票据不得写回复活"


def test_login_sets_auth_cookies():
    """登录响应 Set-Cookie 下发三 cookie：access/refresh httpOnly，csrf **非** httpOnly（P2-4.5）。

    csrf 必须**非** httpOnly——前端 JS 需读取它构造 X-CSRF-Token 头（真双重提交）。
    若被改回 httpOnly，真双重提交即失效，此处必须能测出来（不能只断言"存在一个 httponly"）。
    """
    client, session_factory = build_test_client()
    create_user(
        session_factory, username="cookie_login", password_hash=hash_password("CookiePass1")
    )
    response = client.post(
        "/api/v1/auth/login", json={"username": "cookie_login", "password": "CookiePass1"}
    )
    assert response.status_code == 200

    cookies = response.cookies
    assert security.access_cookie_name() in cookies
    assert security.refresh_cookie_name() in cookies
    assert security.csrf_cookie_name() in cookies

    set_cookie_headers = response.headers.get_list("set-cookie")
    assert set_cookie_headers, "必须通过 Set-Cookie 下发认证 cookie"

    def _header_for(name: str) -> str:
        for header in set_cookie_headers:
            if header.startswith(f"{name}="):
                return header.lower()
        raise AssertionError(f"缺少 {name} 的 Set-Cookie 头")

    # access / refresh：httpOnly + SameSite=Lax
    for name in (security.access_cookie_name(), security.refresh_cookie_name()):
        header = _header_for(name)
        assert "httponly" in header, f"{name} 必须 httpOnly"
        assert "samesite=lax" in header, f"{name} 必须 SameSite=Lax"

    # csrf：非 httpOnly（JS 可读）+ SameSite=Strict
    csrf_header = _header_for(security.csrf_cookie_name())
    assert "httponly" not in csrf_header, (
        "csrf cookie 必须非 httpOnly——前端需读取它构造 X-CSRF-Token 头（真双重提交）"
    )
    assert "samesite=strict" in csrf_header, "csrf cookie 必须 SameSite=Strict"


def test_me_accepts_access_token_from_cookie():
    """P2-4.5：access token 经 httpOnly cookie 认证，无需 Authorization 头。"""
    client, session_factory = build_test_client(override_current_user=False)
    user = create_user(
        session_factory, username="cookie_user", password_hash=hash_password("CookiePass1")
    )
    token = create_access_token(
        data={
            "sub": str(user.id),
            "tv": user.token_version,
            "csrf": security.csrf_claim_hash("csrf-token"),
        }
    )
    response = client.get(
        "/api/v1/auth/me", cookies={security.access_cookie_name(): token}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "cookie_user"


def test_refresh_reads_refresh_token_from_cookie():
    """P2-4.5：/refresh 从 httpOnly cookie 读 refresh token，轮换后 cookie 更新。"""
    client, session_factory = build_test_client()
    user = create_user(
        session_factory, username="cookie_refresh", password_hash=hash_password("CookiePass1")
    )
    refresh_token = asyncio.run(
        security.refresh_token_service.issue(user.id, user.token_version)
    )
    response = client.post(
        "/api/v1/auth/refresh",
        json={},
        cookies={security.refresh_cookie_name(): refresh_token},
    )
    assert response.status_code == 200
    # P2-4.5 收尾：新令牌仅入 httpOnly cookie，body 不返回
    assert _access_token(response)
    assert security.refresh_cookie_name() in response.cookies
    assert security.access_cookie_name() in response.cookies
    assert security.csrf_cookie_name() in response.cookies


def test_cookie_authenticated_unsafe_method_requires_csrf():
    """P2-4.5：cookie 会话的 unsafe 方法必须通过 CSRF 双重提交（缺头/错头 → 403）。

    真双重提交：X-CSRF-Token 头必须等于 csrf cookie 值，且 csrf cookie 的
    sha256 等于 JWT csrf claim。
    """
    client, session_factory = build_test_client(override_current_user=False)
    user = create_user(
        session_factory, username="csrf_user", password_hash=hash_password("CookiePass1")
    )
    token = create_access_token(
        data={
            "sub": str(user.id),
            "tv": user.token_version,
            "csrf": security.csrf_claim_hash("csrf-abc"),
        }
    )
    cookies = {security.access_cookie_name(): token}
    body = {"old_password": "CookiePass1", "new_password": "Newpass123"}

    # 缺 X-CSRF-Token 头 → 403
    missing = client.post("/api/v1/auth/change-password", json=body, cookies=cookies)
    assert missing.status_code == 403
    assert missing.json()["detail"] == "CSRF 校验失败"

    # 头与 csrf cookie 不匹配 → 403
    mismatched = client.post(
        "/api/v1/auth/change-password",
        json=body,
        cookies={**cookies, security.csrf_cookie_name(): "csrf-abc"},
        headers={"X-CSRF-Token": "wrong-token"},
    )
    assert mismatched.status_code == 403

    # 头 == csrf cookie，且 csrf cookie 的 sha256 == JWT csrf claim → 200
    matched = client.post(
        "/api/v1/auth/change-password",
        json=body,
        cookies={**cookies, security.csrf_cookie_name(): "csrf-abc"},
        headers={"X-CSRF-Token": "csrf-abc"},
    )
    assert matched.status_code == 200


def test_csrf_header_is_not_overwritten_by_client_helper():
    """自动补头不得覆盖调用方显式传入的 X-CSRF-Token（否则缺头/错头用例会假绿）。

    探针用 unbind（未绑定 → 400，无副作用、不递增 tv），避免 change-password 改密后
    影响后续登录断言。
    """
    client, session_factory = build_test_client(override_current_user=False)
    create_user(
        session_factory, username="csrf_logged", password_hash=hash_password("CookiePass1")
    )
    login = client.post(
        "/api/v1/auth/login", json={"username": "csrf_logged", "password": "CookiePass1"}
    )
    assert login.status_code == 200

    # 会话已建立（jar 含 csrf）：不传头 → 助手自动补头 → 通过 CSRF（400 = 未绑定，非 403）
    auto = client.post("/api/v1/auth/unbind/wechat")
    assert auto.status_code == 400, "自动补头应通过 CSRF 校验（400 为未绑定业务码）"

    # 显式错头 → 403（助手不得用 jar 里的正确值覆盖，否则假绿）
    wrong = client.post("/api/v1/auth/unbind/wechat", headers={"X-CSRF-Token": "tampered"})
    assert wrong.status_code == 403

    # 显式空头（模拟缺头）→ 403
    empty = client.post("/api/v1/auth/unbind/wechat", headers={"X-CSRF-Token": ""})
    assert empty.status_code == 403


def test_header_authenticated_unsafe_method_skips_csrf():
    """Authorization 头认证（非 cookie 会话）不受 CSRF 约束（P2-4.5）。"""
    client, session_factory = build_test_client()
    user = create_user(
        session_factory, username="header_csrf", password_hash=hash_password("CookiePass1")
    )
    token = create_access_token(data={"sub": str(user.id), "tv": user.token_version})
    response = client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "CookiePass1", "new_password": "Newpass123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_logout_clears_auth_cookies():
    """登出响应清除三个认证 cookie（P2-4.5）。"""
    client, session_factory = build_test_client()
    create_user(
        session_factory, username="cookie_logout", password_hash=hash_password("CookiePass1")
    )
    login = client.post(
        "/api/v1/auth/login", json={"username": "cookie_logout", "password": "CookiePass1"}
    )
    assert login.status_code == 200

    logout = client.post("/api/v1/auth/logout", cookies=dict(login.cookies))
    assert logout.status_code == 200

    cleared = "; ".join(logout.headers.get_list("set-cookie")).lower()
    for name in (
        security.access_cookie_name(),
        security.refresh_cookie_name(),
        security.csrf_cookie_name(),
    ):
        assert f"{name.lower()}=" in cleared
        assert "max-age=0" in cleared, f"{name} 应以 Max-Age=0 清除"


def test_oauth_confirm_returns_503_when_openid_keys_not_configured(monkeypatch):
    """未配置 openid 密钥：OAuth 链路必须 fail-closed 503，不能退回明文处理。"""
    client, _ = build_test_client()
    fake = auth.oauth_pending_registration
    ticket = asyncio.run(
        fake.store(build_pending_payload("alipay", "2088005", nickname="支付宝用户"))
    )
    monkeypatch.setattr(crypto, "openid_crypto", None)

    response = client.post(
        "/api/v1/auth/oauth/confirm", json={"ticket": ticket, "action": "confirm", "consent": OAUTH_CONSENT}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "第三方登录尚未完成服务端配置"


def test_register_rejects_weak_password_with_unified_message():
    """注册走统一密码策略：弱密码 422，文案与前端本地拦截同源（P2-4.6）。"""
    client, _ = build_test_client()
    response = client.post(
        "/api/v1/auth/register/confirm",
        json={
            "username": "weak_pw_user",
            "email": "weak_pw_user@example.com",
            "password": "weakpass1",
            "code": "654321",
        },
    )
    assert response.status_code == 422
    assert PASSWORD_POLICY_ERROR_MESSAGE in response.text


def test_change_password_rejects_weak_password():
    client, session_factory = build_test_client()
    user = create_user(
        session_factory, username="chg_weak", password_hash=hash_password("Oldpass123")
    )
    token = create_access_token(data={"sub": str(user.id), "tv": user.token_version})
    response = client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "Oldpass123", "new_password": "weakpass1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert PASSWORD_POLICY_ERROR_MESSAGE in response.text


def test_reset_password_rejects_weak_password():
    client, session_factory = build_test_client()
    user = create_user(
        session_factory, username="reset_weak", password_hash=hash_password("Oldpass123")
    )
    auth.password_reset_service.codes[user.id] = "123456"
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"account": "reset_weak", "code": "123456", "new_password": "weakpass1"},
    )
    assert response.status_code == 422
    assert PASSWORD_POLICY_ERROR_MESSAGE in response.text


def test_login_locks_account_after_consecutive_failures():
    """连续 5 次失败即锁定；锁定窗口内一切尝试（含正确密码）都 401 同文案（P2-4.6/D1）。

    正确密码也拒绝是锁定的全部价值：否则第 6 次起命中即进，锁定退化为 3.1 的重复实现。
    """
    client, session_factory = build_test_client()
    auth.auth_rate_limiter = UnboundedRateLimiter()
    create_user(session_factory, username="lockuser", password_hash=hash_password("Lockpass1"))

    # 未达阈值前正确密码可正常登录
    for _ in range(settings.ACCOUNT_LOCKOUT_ATTEMPTS - 1):
        response = client.post(
            "/api/v1/auth/login", json={"username": "lockuser", "password": "Wrongpass9"}
        )
        assert response.status_code == 401
    assert client.post(
        "/api/v1/auth/login", json={"username": "lockuser", "password": "Lockpass1"}
    ).status_code == 200

    # 达到阈值：第 5 次失败当场锁定
    for _ in range(settings.ACCOUNT_LOCKOUT_ATTEMPTS):
        response = client.post(
            "/api/v1/auth/login", json={"username": "lockuser", "password": "Wrongpass9"}
        )
        assert response.status_code == 401

    # 锁定窗口内：正确密码与错误密码响应完全一致（防枚举，2.6 语义不破）
    locked_correct = client.post(
        "/api/v1/auth/login", json={"username": "lockuser", "password": "Lockpass1"}
    )
    locked_wrong = client.post(
        "/api/v1/auth/login", json={"username": "lockuser", "password": "Wrongpass9"}
    )
    assert locked_correct.status_code == 401
    assert locked_correct.json() == locked_wrong.json()


def test_lockout_response_matches_missing_account_response():
    """锁定账号的失败响应与"账号不存在"字节级一致（2.6 防枚举不回退）。"""
    client, session_factory = build_test_client()
    auth.auth_rate_limiter = UnboundedRateLimiter()
    create_user(session_factory, username="locked_user", password_hash=hash_password("Lockpass1"))
    for _ in range(settings.ACCOUNT_LOCKOUT_ATTEMPTS):
        client.post("/api/v1/auth/login", json={"username": "locked_user", "password": "Wrongpass9"})

    locked = client.post(
        "/api/v1/auth/login", json={"username": "locked_user", "password": "Wrongpass9"}
    )
    missing = client.post(
        "/api/v1/auth/login", json={"username": "ghost_user", "password": "Wrongpass9"}
    )
    assert locked.status_code == missing.status_code == 401
    assert locked.json() == missing.json()


def test_lockout_does_not_count_oauth_or_missing_accounts():
    """锁定计数仅针对"存在 + 有可用密码 + 密码错误"：OAuth 账户与不存在账号不计数。"""
    client, session_factory = build_test_client()
    auth.auth_rate_limiter = UnboundedRateLimiter()
    create_user(
        session_factory, username="oauth_only", password_hash=make_unusable_password_hash()
    )
    fake = security.account_lockout_service

    for _ in range(settings.ACCOUNT_LOCKOUT_ATTEMPTS + 3):
        client.post(
            "/api/v1/auth/login", json={"username": "oauth_only", "password": "Wrongpass9"}
        )
        client.post(
            "/api/v1/auth/login", json={"username": "ghost_user", "password": "Wrongpass9"}
        )
    assert fake.failures == {}, "OAuth 账户与不存在账号不得计入锁定"

    # 有密码账号照常计数
    create_user(session_factory, username="counted", password_hash=hash_password("Lockpass1"))
    client.post("/api/v1/auth/login", json={"username": "counted", "password": "Wrongpass9"})
    assert len(fake.failures) == 1


def test_successful_login_clears_lockout_state():
    """成功登录清空失败计数（未锁定的卫生逻辑）；清零后可重新累计。"""
    client, session_factory = build_test_client()
    auth.auth_rate_limiter = UnboundedRateLimiter()
    create_user(session_factory, username="clearuser", password_hash=hash_password("Lockpass1"))
    fake = security.account_lockout_service

    for _ in range(settings.ACCOUNT_LOCKOUT_ATTEMPTS - 1):
        client.post("/api/v1/auth/login", json={"username": "clearuser", "password": "Wrongpass9"})
    assert client.post(
        "/api/v1/auth/login", json={"username": "clearuser", "password": "Lockpass1"}
    ).status_code == 200
    assert fake.failures == {}, "成功登录必须清空失败计数"

    # 清零后可重新累计，不会带着旧计数提前锁定
    for _ in range(settings.ACCOUNT_LOCKOUT_ATTEMPTS - 1):
        client.post("/api/v1/auth/login", json={"username": "clearuser", "password": "Wrongpass9"})
    assert client.post(
        "/api/v1/auth/login", json={"username": "clearuser", "password": "Lockpass1"}
    ).status_code == 200


def test_lockout_service_unavailable_returns_503():
    """锁定服务（Redis）不可用：fail-closed 503，与既有认证服务口径一致。"""
    client, session_factory = build_test_client()
    create_user(session_factory, username="redisdown", password_hash=hash_password("Lockpass1"))
    security.account_lockout_service.fail_redis = True

    response = client.post(
        "/api/v1/auth/login", json={"username": "redisdown", "password": "Lockpass1"}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "认证服务暂时不可用"


def _register_user(client, username: str, password: str) -> dict:
    """走完整两步注册链路建号（历史记录等在真实流程中写入）。"""
    _, response, _ = _two_step_register(
        client,
        username=username,
        email=f"{username}@example.com",
        password=password,
    )
    assert response.status_code == 200
    return response.json()


def _history_hashes(session_factory, username: str) -> list[str]:
    db = session_factory()
    try:
        user = db.query(User).filter(User.username == username).first()
        rows = (
            db.query(PasswordHistory)
            .filter(PasswordHistory.user_id == user.id)
            .order_by(PasswordHistory.id.desc())
            .all()
        )
        return [row.password_pepper_hash for row in rows]
    finally:
        db.close()


def test_register_records_password_history():
    """注册建号即记录首个密码：当前密码恒为历史最近一条（P2-4.6）。"""
    client, session_factory = build_test_client()
    _register_user(client, "hist_reg", "RegPass123")
    hashes = _history_hashes(session_factory, "hist_reg")
    assert len(hashes) == 1
    assert security.hash_password_for_history("RegPass123") == hashes[0]


def test_password_history_stores_peppered_hmac_only():
    """历史表只存 HMAC 十六进制：不含明文、不含 bcrypt 哈希（独立 pepper，不复用登录哈希）。"""
    client, session_factory = build_test_client()
    _register_user(client, "hist_shape", "RegPass123")
    for row_hash in _history_hashes(session_factory, "hist_shape"):
        assert len(row_hash) == 64
        assert all(ch in "0123456789abcdef" for ch in row_hash)
        assert "RegPass123" not in row_hash
        assert not row_hash.startswith("$2")


def test_change_password_rejects_reuse_within_recent_three():
    """新密码命中最近 3 条历史即拒绝；滑出窗口后允许复用（P2-4.6）。"""
    client, session_factory = build_test_client()
    auth.auth_rate_limiter = UnboundedRateLimiter()
    _register_user(client, "hist_cycle", "RegPass123")

    def _history_login(client, username: str, password: str) -> str:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200
        return _access_token(response)

    def _change(old: str, new: str):
        token = _history_login(client, "hist_cycle", old)
        return client.post(
            "/api/v1/auth/change-password",
            json={"old_password": old, "new_password": new},
            headers={"Authorization": f"Bearer {token}"},
        )

    # 依次换到 New / Third / Fourth：每一步当前密码都进历史
    assert _change("RegPass123", "Newpass123").status_code == 200
    assert _change("Newpass123", "ThirdPass1").status_code == 200

    # 回退到前两代：命中最近 3 条，拒绝
    rejected = _change("ThirdPass1", "RegPass123")
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "新密码不能与最近使用过的密码相同"
    rejected = _change("ThirdPass1", "Newpass123")
    assert rejected.status_code == 400

    # 换到第四代后 RegPass123 滑出窗口，允许复用
    assert _change("ThirdPass1", "FourthPas1").status_code == 200
    assert _change("FourthPas1", "RegPass123").status_code == 200
    # 历史只保留最近 3 条
    assert len(_history_hashes(session_factory, "hist_cycle")) == 3


def test_set_password_allows_oauth_user_without_old_password():
    """OAuth 用户首次设密：不要求旧密码；成功后 tv+1、!oauth-disabled! 被替换（P2-4.2）。"""
    # override_current_user=False：走真实 get_current_user，才能验证 tv 递增后的旧 token 失效
    client, session_factory = build_test_client(override_current_user=False)
    user = create_user(
        session_factory, username="setpw_oauth", password_hash=make_unusable_password_hash()
    )
    old_token = create_access_token(data={"sub": str(user.id), "tv": user.token_version})
    # 设密前签发的 refresh（旧 tv）：设密后刷新必须 401（3.7 机制：tv 对不上即失效）
    stale_refresh = asyncio.run(
        security.refresh_token_service.issue(user.id, user.token_version)
    )

    response = client.post(
        "/api/v1/auth/set-password",
        json={"new_password": "SetPass11"},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert response.status_code == 200

    # 新密码可登录；旧 access 因 tv 递增立即失效；旧 refresh 下次刷新 401
    assert client.post(
        "/api/v1/auth/login", json={"username": "setpw_oauth", "password": "SetPass11"}
    ).status_code == 200
    assert client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/refresh", json={"refresh_token": stale_refresh}
    ).status_code == 401

    db = session_factory()
    try:
        refreshed = db.query(User).filter(User.id == user.id).first()
        assert security.has_usable_password_hash(refreshed.password_hash)
    finally:
        db.close()


def test_set_password_rejects_user_with_usable_password():
    """已有可用密码的账号必须走改密（要求旧密码），不得绕过。"""
    client, session_factory = build_test_client()
    user = create_user(
        session_factory, username="setpw_local", password_hash=hash_password("Oldpass123")
    )
    token = create_access_token(data={"sub": str(user.id), "tv": user.token_version})

    response = client.post(
        "/api/v1/auth/set-password",
        json={"new_password": "SetPass11"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "当前账号已设置密码，请使用修改密码功能"


def test_bind_confirm_writes_openid_to_current_user():
    """绑定确认：openid 写入当前用户（哈希+密文成对，不落明文）；票据一次性消费（P2-4.2）。"""
    client, session_factory = build_test_client()
    user = create_user(session_factory, username="binder", password_hash=hash_password("Bindpass1"))
    token = create_access_token(data={"sub": str(user.id), "tv": user.token_version})
    crypto_obj = crypto.get_openid_crypto()
    ticket = asyncio.run(
        auth.oauth_pending_registration.store(
            {
                "intent": "bind",
                "user_id": user.id,
                "provider": "wechat",
                "openid": crypto_obj.encrypt("wx-bind-1"),
                "unionid": crypto_obj.encrypt("union-bind-1"),
            }
        )
    )

    response = client.post(
        "/api/v1/auth/bind/confirm",
        json={"bind_ticket": ticket, "consent": BIND_CONSENT},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    db = session_factory()
    try:
        row = db.query(User).filter(User.id == user.id).first()
        assert row.wechat_openid_hash == crypto_obj.lookup_hash("wx-bind-1")
        assert crypto_obj.decrypt(row.wechat_openid_encrypted) == "wx-bind-1"
        assert row.wechat_unionid_hash == crypto_obj.lookup_hash("union-bind-1")
        assert "wx-bind-1" not in (row.wechat_openid_encrypted or "")
    finally:
        db.close()

    # 票据已一次性消费：重放 400（坏票不复活）
    replay = client.post(
        "/api/v1/auth/bind/confirm",
        json={"bind_ticket": ticket, "consent": BIND_CONSENT},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert replay.status_code == 400


def test_bind_confirm_conflict_with_other_user_returns_409():
    """目标 openid 已被其他用户绑定 → 409，绝不回落 existing login（P2-4.2/D3）。"""
    client, session_factory = build_test_client()
    owner = create_user(session_factory, username="bind_owner", password_hash=hash_password("Bindpass1"))
    other = create_user(session_factory, username="bind_other", password_hash=hash_password("Bindpass2"))
    token = create_access_token(data={"sub": str(other.id), "tv": other.token_version})
    crypto_obj = crypto.get_openid_crypto()
    db = session_factory()
    try:
        owner.alipay_openid_hash = crypto_obj.lookup_hash("alipay-owned-1")
        owner.alipay_openid_encrypted = crypto_obj.encrypt("alipay-owned-1")
        db.add(owner)
        db.commit()
    finally:
        db.close()

    ticket = asyncio.run(
        auth.oauth_pending_registration.store(
            {
                "intent": "bind",
                "user_id": other.id,
                "provider": "alipay",
                "openid": crypto_obj.encrypt("alipay-owned-1"),
            }
        )
    )
    response = client.post(
        "/api/v1/auth/bind/confirm",
        json={"bind_ticket": ticket, "consent": BIND_CONSENT},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "该第三方账号已绑定其他用户"


def test_bind_confirm_rejects_state_user_mismatch():
    """票据内 user_id 与当前登录用户不一致 → 400（user_id 只当线索，不作凭证）。"""
    client, session_factory = build_test_client()
    user = create_user(session_factory, username="bind_self", password_hash=hash_password("Bindpass1"))
    token = create_access_token(data={"sub": str(user.id), "tv": user.token_version})
    crypto_obj = crypto.get_openid_crypto()
    ticket = asyncio.run(
        auth.oauth_pending_registration.store(
            {
                "intent": "bind",
                "user_id": user.id + 999,  # 票据归属他人
                "provider": "alipay",
                "openid": crypto_obj.encrypt("alipay-x1"),
            }
        )
    )
    response = client.post(
        "/api/v1/auth/bind/confirm",
        json={"bind_ticket": ticket, "consent": BIND_CONSENT},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "绑定信息与当前登录用户不一致，请重新发起"
    assert ticket not in auth.oauth_pending_registration.pending, "400 客户端错误不得写回票据"


def test_bind_confirm_wechat_clears_stale_unionid_when_absent():
    """微信重绑：新票据无 unionid 时必须清空旧 unionid，避免跨 App 匹配混淆（评审 #2）。"""
    client, session_factory = build_test_client()
    crypto_obj = crypto.get_openid_crypto()
    user = create_user(
        session_factory, username="rebin_wx", password_hash=hash_password("Bindpass1")
    )
    token = create_access_token(data={"sub": str(user.id), "tv": user.token_version})
    db = session_factory()
    try:
        user.wechat_openid_hash = crypto_obj.lookup_hash("wx-old")
        user.wechat_openid_encrypted = crypto_obj.encrypt("wx-old")
        user.wechat_unionid_hash = crypto_obj.lookup_hash("union-old")
        user.wechat_unionid_encrypted = crypto_obj.encrypt("union-old")
        db.add(user)
        db.commit()
        user_id = user.id
    finally:
        db.close()

    # 新票据只有 openid、没有 unionid
    ticket = asyncio.run(
        auth.oauth_pending_registration.store(
            {
                "intent": "bind",
                "user_id": user_id,
                "provider": "wechat",
                "openid": crypto_obj.encrypt("wx-new"),
            }
        )
    )
    response = client.post(
        "/api/v1/auth/bind/confirm",
        json={"bind_ticket": ticket, "consent": BIND_CONSENT},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    db = session_factory()
    try:
        row = db.query(User).filter(User.id == user_id).first()
        assert row.wechat_openid_hash == crypto_obj.lookup_hash("wx-new")
        assert row.wechat_unionid_hash is None, "无 unionid 的新绑定必须清空旧 unionid"
        assert row.wechat_unionid_encrypted is None
    finally:
        db.close()


def test_password_history_size_follows_settings(monkeypatch):
    """历史保留数可配置（评审 #9）：PASSWORD_HISTORY_SIZE=2 时只保留最近 2 条。"""
    monkeypatch.setattr(settings, "PASSWORD_HISTORY_SIZE", 2)
    client, session_factory = build_test_client()
    auth.auth_rate_limiter = UnboundedRateLimiter()
    _register_user(client, "hist_size", "RegPass123")

    def _change(old: str, new: str):
        login_response = client.post(
            "/api/v1/auth/login", json={"username": "hist_size", "password": old}
        )
        return client.post(
            "/api/v1/auth/change-password",
            json={"old_password": old, "new_password": new},
            headers={"Authorization": f"Bearer {_access_token(login_response)}"},
        )

    assert _change("RegPass123", "Newpass123").status_code == 200
    assert _change("Newpass123", "ThirdPass1").status_code == 200
    assert len(_history_hashes(session_factory, "hist_size")) == 2


def test_bind_confirm_returns_503_when_openid_keys_missing(monkeypatch):
    client, session_factory = build_test_client()
    user = create_user(session_factory, username="bind_nokeys", password_hash=hash_password("Bindpass1"))
    token = create_access_token(data={"sub": str(user.id), "tv": user.token_version})
    crypto_obj = crypto.get_openid_crypto()
    ticket = asyncio.run(
        auth.oauth_pending_registration.store(
            {"intent": "bind", "user_id": user.id, "provider": "alipay",
             "openid": crypto_obj.encrypt("alipay-y1")}
        )
    )
    monkeypatch.setattr(crypto, "openid_crypto", None)
    response = client.post(
        "/api/v1/auth/bind/confirm",
        json={"bind_ticket": ticket, "consent": BIND_CONSENT},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "第三方登录尚未完成服务端配置"


def test_bind_auth_url_with_intent_bind_requires_login():
    """intent=bind 的授权地址必须登录态：未登录直接 401（别让用户走完授权才发现没登录）。"""
    client, _ = build_test_client()
    response = client.post(
        "/api/v1/auth/alipay/auth-url",
        json={"redirect_uri": "https://your-domain.com/login/callback", "intent": "bind"},
    )
    assert response.status_code == 401


def test_unbind_requires_remaining_login_method():
    """解绑后不得把自己锁死：无密码且只剩一个 OAuth 时拒绝解绑（P2-4.2）。"""
    client, session_factory = build_test_client()
    crypto_obj = crypto.get_openid_crypto()
    user = create_user(
        session_factory, username="unbind_alone", password_hash=make_unusable_password_hash()
    )
    token = create_access_token(data={"sub": str(user.id), "tv": user.token_version})
    db = session_factory()
    try:
        user.alipay_openid_hash = crypto_obj.lookup_hash("alipay-1")
        user.alipay_openid_encrypted = crypto_obj.encrypt("alipay-1")
        db.add(user)
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/unbind/alipay", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "至少保留一种登录方式"


def test_unbind_clears_fields_and_bumps_token_version():
    """解绑成功：清对应字段（微信一次清 openid+unionid）、tv+1；未绑定时拒绝。"""
    client, session_factory = build_test_client()
    crypto_obj = crypto.get_openid_crypto()
    user = create_user(session_factory, username="unbinder", password_hash=hash_password("Bindpass1"))
    token = create_access_token(data={"sub": str(user.id), "tv": user.token_version})
    db = session_factory()
    try:
        user.wechat_openid_hash = crypto_obj.lookup_hash("wx-1")
        user.wechat_openid_encrypted = crypto_obj.encrypt("wx-1")
        user.wechat_unionid_hash = crypto_obj.lookup_hash("union-1")
        user.wechat_unionid_encrypted = crypto_obj.encrypt("union-1")
        user.alipay_openid_hash = crypto_obj.lookup_hash("alipay-2")
        user.alipay_openid_encrypted = crypto_obj.encrypt("alipay-2")
        db.add(user)
        db.commit()
        user_id = user.id
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/unbind/wechat", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200

    db = session_factory()
    try:
        row = db.query(User).filter(User.id == user_id).first()
        assert row.wechat_openid_hash is None
        assert row.wechat_openid_encrypted is None
        assert row.wechat_unionid_hash is None
        assert row.wechat_unionid_encrypted is None
        assert row.alipay_openid_hash == crypto_obj.lookup_hash("alipay-2"), "其他 provider 不受影响"
        assert row.token_version == 2, "解绑成功必须递增 token_version（登录方式集合变化）"
    finally:
        db.close()

    # 重复解绑：未绑定 → 400
    replay = client.post(
        "/api/v1/auth/unbind/wechat", headers={"Authorization": f"Bearer {token}"}
    )
    assert replay.status_code == 400
    assert replay.json()["detail"] == "当前账号未绑定微信登录"


def test_reset_password_rejects_reused_password():
    """找回密码重置同样受历史约束，且重置后的密码进入历史。"""
    client, session_factory = build_test_client()
    payload = _register_user(client, "hist_reset", "RegPass123")
    user_id = int(payload["user"]["id"])

    def _reset(new_password: str):
        auth.password_reset_service.codes[user_id] = "123456"
        return client.post(
            "/api/v1/auth/reset-password",
            json={"account": "hist_reset", "code": "123456", "new_password": new_password},
        )

    assert _reset("Newpass123").status_code == 200
    # 重置回上一代（注册密码）：命中历史，拒绝
    rejected = _reset("RegPass123")
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "新密码不能与最近使用过的密码相同"
    assert _reset("ThirdPass1").status_code == 200


# ============================================================
# P2-4.3/4.4：审计埋点 + 同意记录
# ============================================================

def _audit_rows(session_factory, event_type: str) -> list:
    db = session_factory()
    try:
        return db.query(AuditLog).filter(AuditLog.event_type == event_type).all()
    finally:
        db.close()


def test_register_writes_audit_and_privacy_consent():
    """注册建号：写 register 审计 + privacy_policy 同意记录（P2-4.3/4.4）。"""
    client, session_factory = build_test_client()

    _, register_response, _ = _two_step_register(
        client,
        username="audit_register",
        email="audit_register@example.com",
        password="Audit123",
    )
    assert register_response.status_code == 200
    user_id = register_response.json()["user"]["id"]

    rows = _audit_rows(session_factory, "register")
    assert len(rows) == 1
    assert rows[0].user_id == user_id
    assert rows[0].success is True
    assert rows[0].ip_hash, "IP 必须落脱敏哈希"

    db = session_factory()
    try:
        consent = db.query(ConsentRecord).filter(
            ConsentRecord.user_id == user_id,
            ConsentRecord.consent_type == "privacy_policy",
        ).first()
        assert consent is not None, "注册必须记录 privacy_policy 同意（5.2）"
        assert consent.version == "v2"
        assert consent.ip_hash, "同意记录 IP 落脱敏哈希"
    finally:
        db.close()


def test_login_success_and_failure_write_audit():
    """登录成功/失败都写审计：成功 event=login，失败 event=login_failed + 类别原因。"""
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="audit_login",
        email="audit_login@example.com",
        password_hash=hash_password("Audit123"),
    )

    ok = client.post(
        "/api/v1/auth/login", json={"username": "audit_login", "password": "Audit123"}
    )
    assert ok.status_code == 200
    login_rows = _audit_rows(session_factory, "login")
    assert len(login_rows) == 1
    assert login_rows[0].success is True

    fail = client.post(
        "/api/v1/auth/login", json={"username": "audit_login", "password": "Wrong123"}
    )
    assert fail.status_code == 401
    fail_rows = _audit_rows(session_factory, "login_failed")
    assert len(fail_rows) == 1
    assert fail_rows[0].success is False
    assert fail_rows[0].failure_reason == "invalid_password"
    assert fail_rows[0].user_id is not None


def test_login_unknown_user_writes_audit_without_user_id():
    """未知账号登录失败：审计 user_id=None、reason=not_found（不落账号信息）。"""
    client, session_factory = build_test_client()

    response = client.post(
        "/api/v1/auth/login", json={"username": "no_such_user", "password": "Audit123"}
    )
    assert response.status_code == 401

    rows = _audit_rows(session_factory, "login_failed")
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert rows[0].failure_reason == "not_found"


# ============================================================
# P2-5.2：真实同意（未勾选不记录、不放行）
# ============================================================

def test_register_without_consent_is_rejected():
    """未勾选同意：注册被拒，且不产生用户——不得记录用户从未表达的同意。"""
    client, session_factory = build_test_client()

    _, response, _ = _two_step_register(
        client,
        username="no_consent",
        email="nc@example.com",
        password="RegPass123",
        consent=None,
    )
    assert response.status_code in (400, 422)

    db = session_factory()
    try:
        assert db.query(User).filter(User.username == "no_consent").first() is None
        assert db.query(ConsentRecord).count() == 0, "未同意不得留下任何同意记录"
    finally:
        db.close()


def test_register_records_only_accepted_consents():
    """只记录用户实际勾选的项：仅 privacy_policy 时不写 oauth_sync / phone_collection。"""
    client, session_factory = build_test_client()

    _, response, _ = _two_step_register(
        client,
        username="consent_ok",
        email="co@example.com",
        password="RegPass123",
        consent={"privacy_policy": "v2", "age_eligibility": "v1"},
    )
    assert response.status_code == 200
    user_id = response.json()["user"]["id"]

    db = session_factory()
    try:
        rows = db.query(ConsentRecord).filter(ConsentRecord.user_id == user_id).all()
        accepted = {row.consent_type: row.version for row in rows}
        assert accepted == {
            "privacy_policy": "v2",
            "age_eligibility": "v1",
        }, f"记录了未勾选的同意：{accepted}"
    finally:
        db.close()


def test_register_with_phone_requires_phone_consent():
    """提供手机号（敏感个人信息）但未勾选收集同意 → 拒绝且不建号。"""
    client, session_factory = build_test_client()

    _, response, _ = _two_step_register(
        client,
        username="phone_no_consent",
        email="pn@example.com",
        password="RegPass123",
        phone="13800138000",
        consent={"privacy_policy": "v2", "age_eligibility": "v1"},  # 缺 phone_collection
    )
    assert response.status_code in (400, 422)

    db = session_factory()
    try:
        assert db.query(User).filter(User.username == "phone_no_consent").first() is None
    finally:
        db.close()


def test_register_rejects_stale_consent_version():
    """勾选的不是当前版本条款 → 拒绝（需重新勾选最新版本）。"""
    client, session_factory = build_test_client()

    _, response, _ = _two_step_register(
        client,
        username="stale_ver",
        email="sv@example.com",
        password="RegPass123",
        consent={"privacy_policy": "v0"},
    )
    assert response.status_code in (400, 422)

    db = session_factory()
    try:
        assert db.query(User).filter(User.username == "stale_ver").first() is None
    finally:
        db.close()


def test_register_rejects_missing_age_eligibility():
    """合规修订：注册未勾选"我已年满 14 周岁"声明（age_eligibility）→ 拒绝建号。"""
    client, session_factory = build_test_client()

    _, response, _ = _two_step_register(
        client,
        username="no_age_decl",
        email="nad@example.com",
        password="RegPass123",
        consent={"privacy_policy": "v2"},  # 缺 age_eligibility
    )
    assert response.status_code in (400, 422)

    db = session_factory()
    try:
        assert db.query(User).filter(User.username == "no_age_decl").first() is None
    finally:
        db.close()


def test_register_records_age_eligibility_consent():
    """合规修订：注册成功时记录 age_eligibility 声明（与隐私政策一起作为建号必选同意）。"""
    client, session_factory = build_test_client()

    _, response, _ = _two_step_register(
        client,
        username="age_ok",
        email="ao@example.com",
        password="RegPass123",
        consent={"privacy_policy": "v2", "age_eligibility": "v1"},
    )
    assert response.status_code == 200
    user_id = response.json()["user"]["id"]

    db = session_factory()
    try:
        rows = db.query(ConsentRecord).filter(ConsentRecord.user_id == user_id).all()
        accepted = {row.consent_type: row.version for row in rows}
        assert accepted == {
            "privacy_policy": "v2",
            "age_eligibility": "v1",
        }, f"age_eligibility 未正确记录：{accepted}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 手机号短信验证（占用检查 / 发码 / 申诉抢占 / 双重找回）
# ---------------------------------------------------------------------------


class FakeSmsVerifyService:
    """短信验证码服务 fake：固定码 123456，按 (purpose, phone) 验码。"""

    def __init__(self):
        self.valid_codes: dict[tuple[str, str], str] = {}
        self.issued: list[tuple[str, str]] = []
        self.budget_released = 0

    async def issue_code(self, purpose: str, phone: str) -> str:
        code = "123456"
        self.valid_codes[(purpose, phone)] = code
        self.issued.append((purpose, phone))
        return code

    async def verify_code(self, purpose: str, phone: str, code: str) -> bool:
        expected = self.valid_codes.pop((purpose, phone), None)
        return expected is not None and expected == code

    async def delete_code(self, purpose: str, phone: str) -> None:
        self.valid_codes.pop((purpose, phone), None)

    async def reserve_budget(self) -> None:
        return None

    async def release_budget(self) -> None:
        self.budget_released += 1


class FakeSmsService:
    """短信发送服务 fake：捕获发送记录，可切未配置态。"""

    def __init__(self, configured: bool = True):
        self.configured = configured
        self.sent: list[tuple[str, str]] = []

    def is_configured(self) -> bool:
        return self.configured

    async def send_verification_code(self, phone: str, code: str) -> None:
        self.sent.append((phone, code))


def _install_fake_sms_services(
    captured: dict, *, configured: bool = True
) -> tuple[FakeSmsVerifyService, FakeSmsService]:
    """替换短信三件套为 fake，捕获发送与解绑通知。"""
    sms_verify = FakeSmsVerifyService()
    sms_send = FakeSmsService(configured)
    auth.sms_verification_service = sms_verify
    auth.sms_service = sms_send

    class FakeNoticeEmailService:
        def is_configured(self) -> bool:
            return True

        async def send_phone_unbind_notice(self, to_email: str, masked_phone: str) -> None:
            captured["notice_email"] = to_email
            captured["notice_phone"] = masked_phone

    auth.phone_notice_email_service = FakeNoticeEmailService()
    return sms_verify, sms_send


def test_phone_check_status_reports_occupancy():
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="phone_owner",
        email="po@example.com",
        phone="13500135000",
        password_hash=hash_password("Oldpass123"),
    )

    occupied = client.post("/api/v1/auth/phone/check-status", json={"phone": "13500135000"})
    assert occupied.status_code == 200
    assert occupied.json()["occupied"] is True

    free = client.post("/api/v1/auth/phone/check-status", json={"phone": "13500135001"})
    assert free.status_code == 200
    assert free.json()["occupied"] is False


def test_phone_send_code_skips_unoccupied_phone():
    """第一层流程过滤：未占用号码不发短信（随机探测不消耗短信）。"""
    client, _ = build_test_client()
    captured: dict = {}
    _, sms_send = _install_fake_sms_services(captured)

    response = client.post(
        "/api/v1/auth/phone/send-code",
        json={"phone": "13500135002", "purpose": "takeover"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "验证码已发送到您的手机，请注意查收"
    assert sms_send.sent == [], "未占用号码不得真实发短信"


def test_phone_send_code_sends_for_occupied_phone():
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="phone_owner2",
        email="po2@example.com",
        phone="13500135003",
        password_hash=hash_password("Oldpass123"),
    )
    captured: dict = {}
    _, sms_send = _install_fake_sms_services(captured)

    response = client.post(
        "/api/v1/auth/phone/send-code",
        json={"phone": "13500135003", "purpose": "takeover"},
    )
    assert response.status_code == 200
    assert sms_send.sent == [("13500135003", "123456")]


def test_phone_send_code_503_when_sms_not_configured():
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="phone_owner3",
        email="po3@example.com",
        phone="13500135004",
        password_hash=hash_password("Oldpass123"),
    )
    captured: dict = {}
    _install_fake_sms_services(captured, configured=False)

    response = client.post(
        "/api/v1/auth/phone/send-code",
        json={"phone": "13500135004", "purpose": "bind"},
    )
    assert response.status_code == 503


def test_register_occupied_phone_without_code_rejected():
    """手机号被占用且未提供申诉验证码：统一文案拒绝（防枚举）。"""
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="first_owner",
        email="fo@example.com",
        phone="13500135005",
        password_hash=hash_password("Oldpass123"),
    )
    captured: dict = {}
    _install_fake_sms_services(captured)

    _, response, _ = _two_step_register(
        client,
        username="second_user",
        email="su@example.com",
        password="RegPass123",
        phone="13500135005",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "注册失败，请检查输入信息"
    assert client.post("/api/v1/auth/login", json={"username": "second_user", "password": "RegPass123"}).status_code == 401


def test_register_takeover_phone_with_sms_code():
    """申诉抢占：验码通过后新账号获得号码，原主人手机号清空并收邮件通知。"""
    client, session_factory = build_test_client()
    owner = create_user(
        session_factory,
        username="old_owner",
        email="old@example.com",
        phone="13500135006",
        password_hash=hash_password("Oldpass123"),
    )
    captured: dict = {}
    sms_verify, _ = _install_fake_sms_services(captured)
    sms_verify.valid_codes[("takeover", "13500135006")] = "654321"

    email_captured: dict = {}
    _install_fake_verify_email_service(email_captured)
    send = client.post("/api/v1/auth/register/send-code", json={"email": "new@example.com"})
    assert send.status_code == 200

    confirm = client.post(
        "/api/v1/auth/register/confirm",
        json={
            "username": "new_owner",
            "email": "new@example.com",
            "password": "RegPass123",
            "code": email_captured["code"],
            "phone": "13500135006",
            "phone_code": "654321",
            "consent": _default_consent("13500135006"),
        },
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["user"]["phone"] == "13500135006"

    # 解绑通知：原主人收到邮件，手机号脱敏（不外发全量明文）
    assert captured["notice_email"] == "old@example.com"
    assert captured["notice_phone"] == "135****5006"

    db = session_factory()
    try:
        old_row = db.query(User).filter(User.id == owner.id).first()
        assert old_row.phone is None, "抢占后原主人手机号必须清空（其余凭证保留）"
        assert old_row.email == "old@example.com" and old_row.username == "old_owner"
        takeover = db.query(AuditLog).filter(AuditLog.event_type == "phone_takeover").first()
        assert takeover is not None
    finally:
        db.close()


def test_phone_bind_confirm_binds_free_phone_without_code():
    """用户中心绑定：未占用号码直接绑定（不消耗短信），记录 phone_collection 同意。"""
    client, session_factory = build_test_client()
    user = create_user(
        session_factory,
        username="binder",
        email="binder@example.com",
        password_hash=hash_password("Oldpass123"),
    )
    captured: dict = {}
    _, sms_send = _install_fake_sms_services(captured)

    response = client.post(
        "/api/v1/auth/phone/bind-confirm",
        headers=build_auth_headers(user.id),
        json={"phone": "13500135007", "consent": {"phone_collection": "v1"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["phone"] == "13500135007"
    assert sms_send.sent == []

    db = session_factory()
    try:
        consent = db.query(ConsentRecord).filter(
            ConsentRecord.user_id == user.id, ConsentRecord.consent_type == "phone_collection"
        ).first()
        assert consent is not None and consent.version == "v1"
    finally:
        db.close()


def test_phone_bind_confirm_takeover_requires_valid_code():
    """用户中心换绑：号码被他人占用时必须短信验码，错码拒绝且不得变更。"""
    client, session_factory = build_test_client()
    owner = create_user(
        session_factory,
        username="bound_owner",
        email="bo@example.com",
        phone="13500135008",
        password_hash=hash_password("Oldpass123"),
    )
    changer = create_user(
        session_factory,
        username="changer",
        email="changer@example.com",
        password_hash=hash_password("Oldpass123"),
    )
    captured: dict = {}
    _install_fake_sms_services(captured)

    wrong = client.post(
        "/api/v1/auth/phone/bind-confirm",
        headers=build_auth_headers(changer.id),
        json={"phone": "13500135008", "code": "000000", "consent": {"phone_collection": "v1"}},
    )
    assert wrong.status_code == 400

    db = session_factory()
    try:
        assert db.query(User).filter(User.id == owner.id).first().phone == "13500135008"
    finally:
        db.close()


def test_phone_bind_confirm_takeover_transfers_phone():
    """用户中心换绑抢占：验码通过后号码转移，原主人清空并收通知，审计落库。"""
    client, session_factory = build_test_client()
    owner = create_user(
        session_factory,
        username="bound_owner2",
        email="bo2@example.com",
        phone="13500135009",
        password_hash=hash_password("Oldpass123"),
    )
    changer = create_user(
        session_factory,
        username="changer2",
        email="changer2@example.com",
        password_hash=hash_password("Oldpass123"),
    )
    captured: dict = {}
    sms_verify, _ = _install_fake_sms_services(captured)
    sms_verify.valid_codes[("bind", "13500135009")] = "111222"

    response = client.post(
        "/api/v1/auth/phone/bind-confirm",
        headers=build_auth_headers(changer.id),
        json={"phone": "13500135009", "code": "111222", "consent": {"phone_collection": "v1"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["phone"] == "13500135009"
    assert captured["notice_email"] == "bo2@example.com"

    db = session_factory()
    try:
        assert db.query(User).filter(User.id == owner.id).first().phone is None
        bind_audit = db.query(AuditLog).filter(
            AuditLog.event_type == "phone_bind", AuditLog.user_id == changer.id
        ).first()
        assert bind_audit is not None
    finally:
        db.close()


def test_reset_password_via_phone_sends_sms():
    """双重找回：账号传手机号走短信通道，验码后重置密码成功。"""
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="forgetful",
        email="forgetful@example.com",
        phone="13500135010",
        password_hash=hash_password("Oldpass123"),
    )
    captured: dict = {}
    _, sms_send = _install_fake_sms_services(captured)

    request_response = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "13500135010"},
    )
    assert request_response.status_code == 200
    assert request_response.json()["message"] == "如果账号存在且已绑定本地密码，验证码将发送到绑定手机号"
    assert sms_send.sent == [("13500135010", "123456")]

    reset_response = client.post(
        "/api/v1/auth/reset-password",
        json={"account": "13500135010", "code": "123456", "new_password": "Newpass123"},
    )
    assert reset_response.status_code == 200, reset_response.text

    new_login = client.post(
        "/api/v1/auth/login",
        json={"username": "13500135010", "password": "Newpass123"},
    )
    assert new_login.status_code == 200


def test_reset_password_via_unbound_phone_sends_nothing():
    """未绑定手机号找回：统一文案不真实发短信（防枚举 + 防轰炸）。"""
    client, _ = build_test_client()
    captured: dict = {}
    _, sms_send = _install_fake_sms_services(captured)

    response = client.post(
        "/api/v1/auth/reset-password/request-code",
        json={"account": "13500135099"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "如果账号存在且已绑定本地密码，验证码将发送到绑定手机号"
    assert sms_send.sent == []
