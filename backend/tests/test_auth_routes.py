import asyncio
import os
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 在导入 app.* 之前固定测试环境，避免读取到本机脏环境变量。
os.environ["DEBUG"] = "false"
os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:5432/test_db"

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

fake_db_base = types.ModuleType("app.db.base")


class AuthTestBase(DeclarativeBase):
    pass


def stub_get_db():
    raise RuntimeError("测试中应由 dependency_overrides 提供数据库会话")


fake_db_base.Base = AuthTestBase
fake_db_base.get_db = stub_get_db
sys.modules["app.db.base"] = fake_db_base

from app.core.security import create_access_token, hash_password, make_unusable_password_hash
from app.db.base import Base, get_db
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

    def request(self, method: str, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async(method, url, **kwargs))

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)


def build_test_client() -> tuple[CompatTestClient, sessionmaker]:
    auth.password_reset_service = auth.PasswordResetService(redis_url="redis://127.0.0.1:0/0")
    auth.password_reset_service._redis_checked = True
    auth.password_reset_email_service = auth.EmailService()

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
    Base.metadata.create_all(bind=engine, tables=[User.__table__, Role.__table__, user_roles])

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


def create_user(
    session_factory: sessionmaker,
    *,
    username: str,
    email: str,
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


def test_register_and_login_with_username():
    client, _ = build_test_client()

    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "admin",
            "email": "Admin@example.com",
            "phone": "13800138000",
            "password": "admin123",
        },
    )

    assert register_response.status_code == 200
    payload = register_response.json()
    assert payload["user"]["username"] == "admin"
    assert payload["user"]["email"] == "admin@example.com"
    assert payload["user"]["phone"] == "13800138000"

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "admin123",
        },
    )

    assert login_response.status_code == 200
    login_payload = login_response.json()
    assert login_payload["user"]["username"] == "admin"
    assert login_payload["access_token"]


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
        password_hash=hash_password("oldpass123"),
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
            "new_password": "newpass123",
        },
    )

    assert reset_response.status_code == 200
    assert reset_response.json()["message"] == "密码重置成功，请使用新密码登录"

    old_login = client.post(
        "/api/v1/auth/login",
        json={"username": "storyman", "password": "oldpass123"},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/login",
        json={"username": "storyman", "password": "newpass123"},
    )
    assert new_login.status_code == 200


def test_reset_password_rejects_invalid_code():
    client, session_factory = build_test_client()
    create_user(
        session_factory,
        username="coder",
        email="coder@example.com",
        phone="13600136000",
        password_hash=hash_password("oldpass123"),
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
            "new_password": "newpass123",
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
        password_hash=hash_password("oldpass123"),
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
        password_hash=hash_password("oldpass123"),
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
            "new_password": "newpass123",
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
        password_hash=hash_password("oldpass123"),
    )

    response = client.post(
        "/api/v1/auth/change-password",
        json={
            "old_password": "oldpass123",
            "new_password": "newpass123",
        },
        headers=build_auth_headers(user.id),
    )

    assert response.status_code == 200
    assert response.json()["message"] == "密码修改成功"

    new_login = client.post(
        "/api/v1/auth/login",
        json={"username": "settings_user", "password": "newpass123"},
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
