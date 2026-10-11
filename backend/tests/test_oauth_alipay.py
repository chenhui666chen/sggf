"""支付宝 OAuth 签名/验签与回调登录测试。"""
import asyncio
import base64
import hashlib
import json
import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 在导入 app.* 之前固定测试环境，避免读取到本机脏环境变量。
os.environ["DEBUG"] = "false"
os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:5432/test_db"
os.environ["ALIPAY_APP_ID"] = ""
os.environ["ALIPAY_PRIVATE_KEY"] = ""
os.environ["ALIPAY_PUBLIC_KEY"] = ""
# openid 加密存储（P2-4.1）的测试密钥由 tests/conftest.py 统一注入

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.crypto as crypto
from app.core.security import verify_token
import app.core.security as security
from app.db.base import Base, get_db
from app.models.audit_log import AuditLog
from app.models.consent_record import ConsentRecord
from app.models.role import Role, user_roles
from app.models.user import User


def _load_module(name: str, relative_path: str):
    path = ROOT_DIR / relative_path
    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


oauth_module = _load_module("test_oauth_service_module", "app/services/oauth_service.py")
auth = _load_module("test_oauth_auth_module", "app/api/v1/auth.py")


def _generate_keypair_b64() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_b64 = base64.b64encode(
        key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode()
    pub_b64 = base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode()
    return priv_b64, pub_b64


def _sign_text(private_key, text: str) -> str:
    signature = private_key.sign(text.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("ascii")


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class FakeAsyncClient:
    """记录请求并返回预设响应的 httpx 替身。"""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, **kwargs):
        FakeAsyncClient.requests.append({"url": url, "data": data})
        return FakeResponse(FakeAsyncClient.response_text)


FakeAsyncClient.requests = []
FakeAsyncClient.response_text = "{}"


def _reset_fake_client(response_text: str) -> None:
    FakeAsyncClient.requests = []
    FakeAsyncClient.response_text = response_text


class CompatTestClient:
    """兼容 httpx 0.28+ 的轻量测试客户端。"""

    def __init__(self, app: FastAPI):
        self._app = app
        self._base_url = "http://testserver"

    async def _request_async(self, method: str, url: str, **kwargs) -> Response:
        transport = ASGITransport(app=self._app)
        async with AsyncClient(
            transport=transport,
            base_url=self._base_url,
            follow_redirects=True,
        ) as client:
            return await client.request(method, url, **kwargs)

    def post(self, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async("POST", url, **kwargs))


def test_build_sign_content_sorted_and_filtered():
    content = oauth_module.build_sign_content(
        {"b": "2", "a": "1", "sign": "ignored", "empty": "", "none": None}
    )
    assert content == "a=1&b=2"


def test_extract_response_sign_content_roundtrip():
    inner = json.dumps({"code": "10000"}, separators=(",", ":"))
    raw = f'{{"alipay_system_oauth_token_response": {inner}, "sign": "AAAA"}}'
    assert oauth_module.extract_response_sign_content(raw) == inner
    # 无 sign 字段 / 非包裹体结构 → 提取失败（验签拒绝）
    assert oauth_module.extract_response_sign_content('{"a":1}') is None


def test_key_material_normalization_accepts_single_line_b64():
    priv_b64, pub_b64 = _generate_keypair_b64()
    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=priv_b64, public_key=pub_b64
    )
    params = {"app_id": "test_app", "method": "m"}
    signature = service._sign(params)
    content = oauth_module.build_sign_content(params)
    service._public_key.verify(
        base64.b64decode(signature),
        content.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_get_access_token_signs_request_and_verifies_response(monkeypatch):
    app_priv_b64, _ = _generate_keypair_b64()
    alipay_priv_b64, alipay_pub_b64 = _generate_keypair_b64()
    alipay_priv = oauth_module.load_alipay_private_key(alipay_priv_b64)

    body = {
        "alipay_system_oauth_token_response": {
            "code": "10000",
            "access_token": "at-123",
            "user_id": "2088001",
        }
    }
    # 真实网关约定（线上取证）：签名只覆盖内层包裹体的紧凑序列化，外层带空格且 sign 收尾
    inner_text = json.dumps(body["alipay_system_oauth_token_response"], separators=(",", ":"))
    signed_raw = f'{{"alipay_system_oauth_token_response": {inner_text}, "sign": "{_sign_text(alipay_priv, inner_text)}"}}'
    _reset_fake_client(signed_raw)
    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", FakeAsyncClient)

    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=app_priv_b64, public_key=alipay_pub_b64
    )
    token_data = asyncio.run(service.get_access_token("auth-code-1"))

    assert token_data["access_token"] == "at-123"
    request_data = FakeAsyncClient.requests[0]["data"]
    assert request_data["sign"]
    assert request_data["code"] == "auth-code-1"
    # 请求签名可用应用公钥验证
    app_pub = oauth_module.load_alipay_public_key(
        base64.b64encode(
            oauth_module.load_alipay_private_key(app_priv_b64)
            .public_key()
            .public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).decode()
    )
    app_pub.verify(
        base64.b64decode(request_data["sign"]),
        oauth_module.build_sign_content(
            {k: v for k, v in request_data.items() if k != "sign"}
        ).encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_get_access_token_rejects_tampered_response(monkeypatch):
    app_priv_b64, _ = _generate_keypair_b64()
    alipay_priv_b64, alipay_pub_b64 = _generate_keypair_b64()
    alipay_priv = oauth_module.load_alipay_private_key(alipay_priv_b64)

    inner = {"code": "10000", "access_token": "at-123", "user_id": "2088001"}
    inner_text = json.dumps(inner, separators=(",", ":"))
    sig = _sign_text(alipay_priv, inner_text)
    tampered_inner = json.dumps({**inner, "access_token": "at-hacked"}, separators=(",", ":"))
    signed_raw = f'{{"alipay_system_oauth_token_response": {tampered_inner}, "sign": "{sig}"}}'
    _reset_fake_client(signed_raw)
    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", FakeAsyncClient)

    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=app_priv_b64, public_key=alipay_pub_b64
    )
    token_data = asyncio.run(service.get_access_token("auth-code-1"))

    assert token_data["error"] == "alipay_sign_verify_failed"


def test_verify_response_matches_real_gateway_signing_content(monkeypatch):
    """线上取证：网关签名只覆盖内层包裹体紧凑 JSON（外层含空格、无 sign_type、
    成功响应内层无 code 字段）；旧实现的剔除外层 sign 策略必然验签失败。"""
    app_priv_b64, _ = _generate_keypair_b64()
    alipay_priv_b64, alipay_pub_b64 = _generate_keypair_b64()
    alipay_priv = oauth_module.load_alipay_private_key(alipay_priv_b64)

    # 模拟真实网关成功响应：内层无 code、外层带空格、sign 收尾
    inner = {"access_token": "at-123", "expires_in": "3600", "open_id": "oid-1"}
    inner_text = json.dumps(inner, separators=(",", ":"))
    signed_raw = f'{{"alipay_system_oauth_token_response": {inner_text}, "sign": "{_sign_text(alipay_priv, inner_text)}"}}'
    _reset_fake_client(signed_raw)
    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", FakeAsyncClient)

    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=app_priv_b64, public_key=alipay_pub_b64
    )
    token_data = asyncio.run(service.get_access_token("auth-code-1"))

    assert token_data.get("error") is None
    assert token_data["access_token"] == "at-123"


def test_verify_response_user_info_matches_real_gateway_signing_content(monkeypatch):
    """get_user_info 同约定：内层包裹体（alipay_user_info_share_response）为验签对象。"""
    app_priv_b64, _ = _generate_keypair_b64()
    alipay_priv_b64, alipay_pub_b64 = _generate_keypair_b64()
    alipay_priv = oauth_module.load_alipay_private_key(alipay_priv_b64)

    inner = {"code": "10000", "user_id": "2088001", "nick_name": "支付宝用户"}
    inner_text = json.dumps(inner, separators=(",", ":"), ensure_ascii=False)
    signed_raw = f'{{"alipay_user_info_share_response": {inner_text}, "sign": "{_sign_text(alipay_priv, inner_text)}"}}'
    _reset_fake_client(signed_raw)
    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", FakeAsyncClient)

    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=app_priv_b64, public_key=alipay_pub_b64
    )
    user_info = asyncio.run(service.get_user_info("at-123"))

    assert user_info.get("error") is None
    assert user_info["user_id"] == "2088001"


def test_get_user_info_normalizes_open_id_to_user_id(monkeypatch):
    """线上取证：应用开启 openid 配置后网关只回 open_id；登录链路只认 user_id，
    服务层必须归一化，否则真实登录必然报 Invalid Alipay user info。"""
    app_priv_b64, _ = _generate_keypair_b64()
    alipay_priv_b64, alipay_pub_b64 = _generate_keypair_b64()
    alipay_priv = oauth_module.load_alipay_private_key(alipay_priv_b64)

    inner = {"code": "10000", "msg": "Success", "open_id": "064J7-openid-value"}
    inner_text = json.dumps(inner, separators=(",", ":"))
    signed_raw = f'{{"alipay_user_info_share_response": {inner_text}, "sign": "{_sign_text(alipay_priv, inner_text)}"}}'
    _reset_fake_client(signed_raw)
    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", FakeAsyncClient)

    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=app_priv_b64, public_key=alipay_pub_b64
    )
    user_info = asyncio.run(service.get_user_info("at-123"))

    assert user_info.get("error") is None
    assert user_info["user_id"] == "064J7-openid-value"


def test_get_user_info_keeps_existing_user_id(monkeypatch):
    """兼容旧约定：网关同时回 user_id 时不被 open_id 覆盖。"""
    app_priv_b64, _ = _generate_keypair_b64()
    alipay_priv_b64, alipay_pub_b64 = _generate_keypair_b64()
    alipay_priv = oauth_module.load_alipay_private_key(alipay_priv_b64)

    inner = {"code": "10000", "user_id": "2088001", "open_id": "064J7-openid-value"}
    inner_text = json.dumps(inner, separators=(",", ":"))
    signed_raw = f'{{"alipay_user_info_share_response": {inner_text}, "sign": "{_sign_text(alipay_priv, inner_text)}"}}'
    _reset_fake_client(signed_raw)
    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", FakeAsyncClient)

    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=app_priv_b64, public_key=alipay_pub_b64
    )
    user_info = asyncio.run(service.get_user_info("at-123"))

    assert user_info["user_id"] == "2088001"


def test_get_access_token_returns_error_for_gateway_error_response(monkeypatch):
    """真实网关探测结论：错误响应包在 error_response 里，不得退回成功分支。"""
    app_priv_b64, _ = _generate_keypair_b64()
    _, alipay_pub_b64 = _generate_keypair_b64()

    raw = json.dumps(
        {
            "error_response": {
                "msg": "Invalid Arguments",
                "code": "40002",
                "sub_msg": "授权码code无效",
                "sub_code": "isv.code-invalid",
            },
            "sign": "ignored",
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    _reset_fake_client(raw)
    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", FakeAsyncClient)

    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=app_priv_b64, public_key=alipay_pub_b64
    )
    token_data = asyncio.run(service.get_access_token("auth-code-1"))

    assert token_data["error"] == "isv.code-invalid"
    assert token_data["error_description"] == "授权码code无效"
    assert "access_token" not in token_data


def test_get_user_info_returns_error_for_gateway_error_response(monkeypatch):
    """get_user_info 与换票同语义：error_response 必须落为结构化错误。"""
    app_priv_b64, _ = _generate_keypair_b64()
    _, alipay_pub_b64 = _generate_keypair_b64()

    raw = json.dumps(
        {
            "error_response": {
                "msg": "Insufficient Conditions",
                "code": "20001",
                "sub_msg": "授权权限不足",
                "sub_code": "aop.auth-permission-not-enough",
            },
            "sign": "ignored",
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    _reset_fake_client(raw)
    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", FakeAsyncClient)

    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=app_priv_b64, public_key=alipay_pub_b64
    )
    user_info = asyncio.run(service.get_user_info("at-123"))

    assert user_info["error"] == "aop.auth-permission-not-enough"
    assert user_info["error_description"] == "授权权限不足"


def test_get_access_token_error_response_checked_before_signature(monkeypatch):
    """真实网关的错误响应签名无法用支付宝公钥验证，错误分支必须先于验签判定，
    否则换票失败只会得到笼统的 alipay_sign_verify_failed。"""
    app_priv_b64, _ = _generate_keypair_b64()
    _, alipay_pub_b64 = _generate_keypair_b64()

    raw = json.dumps(
        {
            "error_response": {"msg": "Invalid Arguments", "code": "40002", "sub_code": "isv.code-invalid"},
            "sign": "not-a-real-signature",
        },
        separators=(",", ":"),
    )
    _reset_fake_client(raw)
    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", FakeAsyncClient)

    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=app_priv_b64, public_key=alipay_pub_b64
    )
    token_data = asyncio.run(service.get_access_token("auth-code-1"))

    assert token_data["error"] != "alipay_sign_verify_failed"


class FakeRefreshService:
    """测试用内存 refresh token 服务（P1-3.7）：只需 issue，避免连真实 Redis。"""

    def __init__(self):
        self.issued: list[str] = []

    async def issue(self, user_id: int, tv: int) -> str:
        token = f"fake-refresh-{len(self.issued)}"
        self.issued.append(token)
        return token


class FakeOAuthPendingService:
    """测试用内存 OAuth 建号票据服务（P1-3.2）：避免连真实 Redis。"""

    def __init__(self):
        self.pending: dict[str, dict] = {}
        self.counter = 0

    async def store(self, payload: dict, ttl: int = 600) -> str:
        self.counter += 1
        ticket = f"ticket-{self.counter}"
        self.pending[ticket] = payload
        return ticket

    async def consume(self, ticket: str) -> dict | None:
        return self.pending.pop(ticket, None)

    async def restore(self, ticket: str, payload: dict, ttl: int = 600) -> None:
        self.pending[ticket] = payload


def build_test_client() -> tuple[CompatTestClient, sessionmaker]:
    # callback 会经过 build_token_response 签发 refresh token：替换为内存实现，不连真实 Redis；
    # 新用户分支会存建号票据：同样替换（P1-3.2）
    security.refresh_token_service = FakeRefreshService()
    auth.oauth_pending_registration = FakeOAuthPendingService()
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
            AuditLog.__table__,  # P2-4.4：OAuth 登录审计埋点
            ConsentRecord.__table__,  # P2-4.3/5.2：OAuth 建号/绑定同意记录
        ],
    )

    app = FastAPI()
    app.include_router(auth.router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return CompatTestClient(app), testing_session_local


class FakeAlipayService:
    def __init__(self, app_id, private_key, public_key, **kwargs):
        pass

    async def get_access_token(self, code: str):
        return {"code": "10000", "access_token": "at-1", "user_id": "2088001"}

    async def get_user_info(self, access_token: str):
        return {"code": "10000", "user_id": "2088001", "nick_name": "支付宝用户"}


class FakeStateService:
    """测试用内存 state 服务，替代真实 Redis 实现。"""

    def __init__(self):
        self.data: dict[str, dict] = {}

    async def store(
        self,
        state: str,
        provider: str,
        redirect_uri: str,
        ttl: int = 600,
        extra: dict | None = None,
    ) -> None:
        self.data[state] = {"provider": provider, "redirect_uri": redirect_uri, **(extra or {})}

    async def consume(self, state: str, expected_provider: str) -> dict:
        raw = self.data.pop(state, None)
        if not raw:
            raise HTTPException(status_code=400, detail="无效的登录状态，请重新发起")
        if raw["provider"] != expected_provider:
            raise HTTPException(status_code=400, detail="登录提供方不匹配")
        return raw


class FakeCodeGuard:
    """测试用内存 OAuth code 换票锁，替代真实 Redis 实现（P1-3.1）。"""

    def __init__(self):
        self.locks: set[str] = set()
        self.used: set[str] = set()

    @staticmethod
    def _hash(code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()[:16]

    async def acquire(self, code: str) -> str:
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


def test_alipay_callback_existing_user_returns_token(monkeypatch):
    """已有用户回调返回 status=ok + token（P1-3.2：响应改为联合体）。"""
    from app.core.security import make_unusable_password_hash

    saved = {
        "ALIPAY_APP_ID": auth.settings.ALIPAY_APP_ID,
        "ALIPAY_PRIVATE_KEY": auth.settings.ALIPAY_PRIVATE_KEY,
        "ALIPAY_PUBLIC_KEY": auth.settings.ALIPAY_PUBLIC_KEY,
        "OAUTH_REDIRECT_URI_WHITELIST": auth.settings.OAUTH_REDIRECT_URI_WHITELIST,
    }
    auth.settings.ALIPAY_APP_ID = "test_app"
    auth.settings.ALIPAY_PRIVATE_KEY = "x"
    auth.settings.ALIPAY_PUBLIC_KEY = "x"
    # 白名单隔离：不得读取本机 .env 真实白名单（与 test_auth_routes.py 同约定）
    auth.settings.OAUTH_REDIRECT_URI_WHITELIST = ["https://your-domain.com/login/callback"]
    monkeypatch.setattr(auth, "AlipayOAuthService", FakeAlipayService)
    state_svc = FakeStateService()
    asyncio.run(
        state_svc.store("st-oauth-test", "alipay", "https://your-domain.com/login/callback")
    )
    monkeypatch.setattr(auth, "oauth_state_service", state_svc)
    monkeypatch.setattr(auth, "oauth_code_guard", FakeCodeGuard())
    try:
        client, session_factory = build_test_client()
        db = session_factory()
        try:
            crypto_obj = crypto.get_openid_crypto()
            db.add(
                User(
                    username="alipay_existing",
                    email=None,
                    password_hash=make_unusable_password_hash(),
                    full_name="支付宝用户",
                    alipay_openid_hash=crypto_obj.lookup_hash("2088001"),
                    alipay_openid_encrypted=crypto_obj.encrypt("2088001"),
                )
            )
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/api/v1/auth/alipay/callback",
            json={"code": "auth-code-1", "state": "st-oauth-test"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload.get("registration_ticket") is None
        # P2-4.5 收尾：OAuth 登录 token 仅入 httpOnly cookie，body 只回 user
        assert response.cookies.get(security.access_cookie_name()), "OAuth 登录必须写 access cookie"
        token_payload = verify_token(response.cookies.get(security.access_cookie_name()))
        # OAuth 登录签发的 token 必须携带 tv（2.5：改密/重置后旧 token 立即失效）
        assert token_payload.get("tv") == 1
        assert payload["user"]["full_name"] == "支付宝用户"
    finally:
        for key, value in saved.items():
            setattr(auth.settings, key, value)


def test_alipay_callback_new_user_returns_ticket_without_creating_user(monkeypatch):
    """首次登录不再自动建号：返回建号票据，库中无新用户行（P1-3.2）。"""
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
    monkeypatch.setattr(auth, "AlipayOAuthService", FakeAlipayService)
    state_svc = FakeStateService()
    asyncio.run(
        state_svc.store("st-new-user", "alipay", "https://your-domain.com/login/callback")
    )
    monkeypatch.setattr(auth, "oauth_state_service", state_svc)
    monkeypatch.setattr(auth, "oauth_code_guard", FakeCodeGuard())
    try:
        client, session_factory = build_test_client()
        response = client.post(
            "/api/v1/auth/alipay/callback",
            json={"code": "auth-code-new", "state": "st-new-user"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "new_user"
        assert payload["registration_ticket"]
        assert payload.get("token") is None
        # openid 不得回传客户端（反模式警示：openid 不进浏览器）
        assert "openid" not in response.text
        db = session_factory()
        try:
            assert db.query(User).count() == 0
        finally:
            db.close()
    finally:
        for key, value in saved.items():
            setattr(auth.settings, key, value)


def test_alipay_callback_ticket_keeps_openid_encrypted(monkeypatch):
    """待建号票据内 openid 必须是密文：Redis 泄露不得直接拿到 openid（P2-4.1）。"""
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
    monkeypatch.setattr(auth, "AlipayOAuthService", FakeAlipayService)
    state_svc = FakeStateService()
    asyncio.run(
        state_svc.store("st-ticket-crypto", "alipay", "https://your-domain.com/login/callback")
    )
    monkeypatch.setattr(auth, "oauth_state_service", state_svc)
    monkeypatch.setattr(auth, "oauth_code_guard", FakeCodeGuard())
    try:
        client, _ = build_test_client()
        response = client.post(
            "/api/v1/auth/alipay/callback",
            json={"code": "auth-code-crypto", "state": "st-ticket-crypto"},
        )
        assert response.status_code == 200
        ticket = response.json()["registration_ticket"]

        pending = auth.oauth_pending_registration.pending[ticket]
        assert pending["openid"] != "2088001", "票据内不得出现明文 openid"
        assert crypto.get_openid_crypto().decrypt(pending["openid"]) == "2088001"
    finally:
        for key, value in saved.items():
            setattr(auth.settings, key, value)


def test_alipay_callback_bind_intent_returns_bind_ticket(monkeypatch):
    """intent=bind：callback 不建号、不发 token，只回 bind_pending + 票据（P2-4.2）。"""
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
    monkeypatch.setattr(auth, "AlipayOAuthService", FakeAlipayService)
    state_svc = FakeStateService()
    asyncio.run(
        state_svc.store(
            "st-bind",
            "alipay",
            "https://your-domain.com/login/callback",
            extra={"intent": "bind", "user_id": 5},
        )
    )
    monkeypatch.setattr(auth, "oauth_state_service", state_svc)
    monkeypatch.setattr(auth, "oauth_code_guard", FakeCodeGuard())
    try:
        client, session_factory = build_test_client()
        response = client.post(
            "/api/v1/auth/alipay/callback",
            json={"code": "auth-code-bind", "state": "st-bind"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "bind_pending"
        assert payload["bind_ticket"]
        assert payload.get("token") is None
        assert payload.get("registration_ticket") is None

        pending = auth.oauth_pending_registration.pending[payload["bind_ticket"]]
        assert pending["intent"] == "bind"
        assert pending["user_id"] == 5
        assert pending["openid"] != "2088001", "票据内不得出现明文 openid"
        assert crypto.get_openid_crypto().decrypt(pending["openid"]) == "2088001"

        db = session_factory()
        try:
            assert db.query(User).count() == 0, "绑定意图不得建号"
        finally:
            db.close()
    finally:
        for key, value in saved.items():
            setattr(auth.settings, key, value)


def test_alipay_callback_returns_503_when_not_configured(monkeypatch):
    saved = {
        "ALIPAY_APP_ID": auth.settings.ALIPAY_APP_ID,
        "ALIPAY_PRIVATE_KEY": auth.settings.ALIPAY_PRIVATE_KEY,
        "ALIPAY_PUBLIC_KEY": auth.settings.ALIPAY_PUBLIC_KEY,
    }
    auth.settings.ALIPAY_APP_ID = ""
    auth.settings.ALIPAY_PRIVATE_KEY = ""
    auth.settings.ALIPAY_PUBLIC_KEY = ""
    try:
        client, _ = build_test_client()
        response = client.post("/api/v1/auth/alipay/callback", json={"code": "auth-code-1"})
        assert response.status_code == 503
    finally:
        for key, value in saved.items():
            setattr(auth.settings, key, value)


def test_alipay_callback_rejects_reused_code(monkeypatch):
    """换票锁（P1-3.1）：同一授权码第二次回调必须被拒绝（防并发/重放双换票）。"""
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
    monkeypatch.setattr(auth, "AlipayOAuthService", FakeAlipayService)
    state_svc = FakeStateService()
    asyncio.run(
        state_svc.store("st-code-1", "alipay", "https://your-domain.com/login/callback")
    )
    asyncio.run(
        state_svc.store("st-code-2", "alipay", "https://your-domain.com/login/callback")
    )
    monkeypatch.setattr(auth, "oauth_state_service", state_svc)
    monkeypatch.setattr(auth, "oauth_code_guard", FakeCodeGuard())
    try:
        client, _ = build_test_client()
        first = client.post(
            "/api/v1/auth/alipay/callback",
            json={"code": "auth-code-1", "state": "st-code-1"},
        )
        assert first.status_code == 200

        # 同一 code 换票（即使换了新 state）必须被换票锁拒绝
        second = client.post(
            "/api/v1/auth/alipay/callback",
            json={"code": "auth-code-1", "state": "st-code-2"},
        )
        assert second.status_code == 400
        assert second.json()["detail"] == "授权码已被使用"
    finally:
        for key, value in saved.items():
            setattr(auth.settings, key, value)
