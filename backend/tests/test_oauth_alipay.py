"""支付宝 OAuth 签名/验签与回调登录测试。"""
import asyncio
import base64
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

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base, get_db
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


def test_strip_sign_fields_roundtrip():
    body = {"alipay_system_oauth_token_response": {"code": "10000"}}
    base = json.dumps(body)
    raw = json.dumps({**body, "sign": "AAAA", "sign_type": "RSA2"})
    assert oauth_module.strip_sign_fields(raw) == base


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
    base_text = json.dumps(body, separators=(",", ":"))
    signed_raw = json.dumps(
        {**body, "sign": _sign_text(alipay_priv, base_text), "sign_type": "RSA2"},
        separators=(",", ":"),
    )
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

    body = {
        "alipay_system_oauth_token_response": {
            "code": "10000",
            "access_token": "at-123",
            "user_id": "2088001",
        }
    }
    base_text = json.dumps(body, separators=(",", ":"))
    tampered_text = base_text.replace("at-123", "at-hacked")
    signed_raw = json.dumps(
        {**json.loads(tampered_text), "sign": _sign_text(alipay_priv, base_text), "sign_type": "RSA2"},
        separators=(",", ":"),
    )
    _reset_fake_client(signed_raw)
    monkeypatch.setattr(oauth_module.httpx, "AsyncClient", FakeAsyncClient)

    service = oauth_module.AlipayOAuthService(
        app_id="test_app", private_key=app_priv_b64, public_key=alipay_pub_b64
    )
    token_data = asyncio.run(service.get_access_token("auth-code-1"))

    assert token_data["error"] == "alipay_sign_verify_failed"


def build_test_client() -> CompatTestClient:
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
    Base.metadata.create_all(bind=engine, tables=[User.__table__])

    app = FastAPI()
    app.include_router(auth.router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return CompatTestClient(app)


class FakeAlipayService:
    def __init__(self, app_id, private_key, public_key):
        pass

    async def get_access_token(self, code: str):
        return {"code": "10000", "access_token": "at-1", "user_id": "2088001"}

    async def get_user_info(self, access_token: str):
        return {"code": "10000", "user_id": "2088001", "nick_name": "支付宝用户"}


def test_alipay_callback_creates_user_and_returns_token(monkeypatch):
    saved = {
        "ALIPAY_APP_ID": auth.settings.ALIPAY_APP_ID,
        "ALIPAY_PRIVATE_KEY": auth.settings.ALIPAY_PRIVATE_KEY,
        "ALIPAY_PUBLIC_KEY": auth.settings.ALIPAY_PUBLIC_KEY,
    }
    auth.settings.ALIPAY_APP_ID = "test_app"
    auth.settings.ALIPAY_PRIVATE_KEY = "x"
    auth.settings.ALIPAY_PUBLIC_KEY = "x"
    monkeypatch.setattr(auth, "AlipayOAuthService", FakeAlipayService)
    try:
        client = build_test_client()
        response = client.post("/api/v1/auth/alipay/callback", json={"code": "auth-code-1"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["access_token"]
        assert payload["user"]["full_name"] == "支付宝用户"
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
        client = build_test_client()
        response = client.post("/api/v1/auth/alipay/callback", json={"code": "auth-code-1"})
        assert response.status_code == 503
    finally:
        for key, value in saved.items():
            setattr(auth.settings, key, value)
