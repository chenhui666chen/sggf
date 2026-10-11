"""用户数据权利 API 测试（P2-4.3）。

覆盖：/user/data/export、/user/account/delete（软删除+冷静期+清 cookie）、
/user/profile（含手机号同意记录）、/user/consent、已注销用户访问拒绝。
AUDIT_LOG_PEPPER 由 conftest 注入。
"""
import asyncio
import os
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request, status
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["DEBUG"] = "false"
os.environ["DATABASE_URL"] = "postgresql://test:test@127.0.0.1:5432/test_db"

import app.core.crypto as crypto  # noqa: E402
import app.core.security as security  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402

fake_db_base = types.ModuleType("app.db.base")
_original_db_base_module = sys.modules.get("app.db.base")
_original_user_module = sys.modules.get("app.models.user")
_original_audit_module = sys.modules.get("app.models.audit_log")
_original_consent_module = sys.modules.get("app.models.consent_record")
_original_role_module = sys.modules.get("app.models.role")


class RightsTestBase(DeclarativeBase):
    pass


def stub_get_db():
    raise RuntimeError("测试中应由 dependency_overrides 提供数据库会话")


fake_db_base.Base = RightsTestBase
fake_db_base.get_db = stub_get_db
fake_db_base.SessionLocal = lambda: None
sys.modules["app.db.base"] = fake_db_base
for _mod in (
    "app.models.user",
    "app.models.audit_log",
    "app.models.consent_record",
    "app.models.role",
):
    sys.modules.pop(_mod, None)

from app.db.base import Base, get_db  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.consent_record import ConsentRecord  # noqa: E402
from app.models.role import Role, user_roles  # noqa: E402,F401  # User mapper 需要 user_roles
from app.models.user import User  # noqa: E402


def load_user_rights_module():
    path = ROOT_DIR / "app" / "api" / "v1" / "user_rights.py"
    spec = spec_from_file_location("test_user_rights_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载用户权利路由模块")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rights = load_user_rights_module()

# 还原真实模块（后续其他测试文件正常导入）
if _original_db_base_module is not None:
    sys.modules["app.db.base"] = _original_db_base_module
else:
    sys.modules.pop("app.db.base", None)
for _name, _mod in (
    ("app.models.user", _original_user_module),
    ("app.models.audit_log", _original_audit_module),
    ("app.models.consent_record", _original_consent_module),
    ("app.models.role", _original_role_module),
):
    if _mod is not None:
        sys.modules[_name] = _mod
    else:
        sys.modules.pop(_name, None)


class CompatTestClient:
    def __init__(self, app: FastAPI):
        self._app = app
        self._base_url = "http://testserver"

    async def _request_async(self, method: str, url: str, **kwargs) -> Response:
        transport = ASGITransport(app=self._app)
        async with AsyncClient(
            transport=transport, base_url=self._base_url, follow_redirects=True
        ) as client:
            return await client.request(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async(method, url, **kwargs))

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)

    def put(self, url: str, **kwargs) -> Response:
        return self.request("PUT", url, **kwargs)


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    testing_session_local = sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Role.__table__,
            user_roles,
            AuditLog.__table__,
            ConsentRecord.__table__,
        ],
    )

    app = FastAPI()
    app.include_router(rights.router)

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
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        payload = security.verify_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
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
    app.dependency_overrides[security.get_current_user] = override_get_current_user
    return CompatTestClient(app), testing_session_local


def create_user(
    session_factory,
    *,
    username: str,
    email: str | None = None,
    password_hash: str | None = None,
) -> User:
    db = session_factory()
    try:
        user = User(
            username=username,
            email=email,
            password_hash=password_hash,
            full_name=username,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def auth_header(user_id: int, tv: int = 1) -> dict:
    return {"Authorization": f"Bearer {create_access_token(data={'sub': str(user_id), 'tv': tv})}"}


def test_export_returns_profile_bindings_and_consents(client):
    test_client, session_factory = client
    crypto_obj = crypto.get_openid_crypto()
    user = create_user(
        session_factory,
        username="exporter",
        email="exporter@example.com",
        password_hash=hash_password("Export123"),
    )
    db = session_factory()
    try:
        user.alipay_openid_hash = crypto_obj.lookup_hash("alipay-export")
        user.alipay_openid_encrypted = crypto_obj.encrypt("alipay-export")
        db.add(user)
        db.commit()
    finally:
        db.close()

    response = test_client.post(
        "/api/v1/user/data/export", headers=auth_header(user.id, user.token_version)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "exporter"
    assert body["email"] == "exporter@example.com"
    bindings = {b["provider"]: b["bound"] for b in body["oauth_bindings"]}
    assert bindings == {"alipay": True, "wechat": False}
    assert body["generated_at"]

    db = session_factory()
    try:
        audit = db.query(AuditLog).filter(AuditLog.event_type == "data_export").first()
        assert audit is not None and audit.user_id == user.id
    finally:
        db.close()


def test_account_delete_soft_deletes_and_clears_cookies(client):
    test_client, session_factory = client
    user = create_user(
        session_factory, username="deleter", email="deleter@example.com", password_hash=hash_password("Delete123")
    )

    response = test_client.post(
        "/api/v1/user/account/delete", headers=auth_header(user.id, user.token_version)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["deleted_at"]
    assert body["cooling_days"] == 30
    assert "冷静期" in body["message"]
    assert response.headers.get("set-cookie") is None or "Max-Age=0" in response.headers.get("set-cookie", "")

    db = session_factory()
    try:
        row = db.query(User).filter(User.id == user.id).first()
        assert row.deleted_at is not None, "注销必须落软删除时间戳"
        assert row.is_active is False
        assert row.token_version == user.token_version + 1, "注销必须递增 token_version（全量下线）"
        audit = db.query(AuditLog).filter(AuditLog.event_type == "account_delete").first()
        assert audit is not None and audit.user_id == user.id
    finally:
        db.close()


def test_account_delete_is_idempotent_rejected(client):
    test_client, session_factory = client
    user = create_user(session_factory, username="delete_twice", password_hash=hash_password("Delete123"))
    db = session_factory()
    try:
        from app.utils.datetime_utils import utc_now

        user.deleted_at = utc_now()
        user.is_active = False
        db.add(user)
        db.commit()
    finally:
        db.close()

    response = test_client.post(
        "/api/v1/user/account/delete", headers=auth_header(user.id, user.token_version)
    )
    # 已注销账户在认证层即被拦截（视同不存在 401），路由内"已注销"400 为纵深防御
    assert response.status_code == 401


def test_profile_update_full_name(client):
    test_client, session_factory = client
    user = create_user(session_factory, username="profiler", email="profiler@example.com")

    response = test_client.put(
        "/api/v1/user/profile",
        headers=auth_header(user.id, user.token_version),
        json={"full_name": "新昵称"},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "新昵称"


def test_profile_direct_phone_change_rejected(client):
    """profile 直写手机号必须被拒：须走短信验证绑定流程（防冒填他人号码抢注）。"""
    test_client, session_factory = client
    user = create_user(session_factory, username="profiler2", email="profiler2@example.com")

    response = test_client.put(
        "/api/v1/user/profile",
        headers=auth_header(user.id, user.token_version),
        json={"full_name": "新昵称", "phone": "13900139000"},
    )
    assert response.status_code == 400
    assert "短信验证" in response.json()["detail"]

    db = session_factory()
    try:
        row = db.query(User).filter(User.id == user.id).first()
        assert row.phone is None, "profile 直写手机号不得落库"
    finally:
        db.close()


def test_profile_update_conflict_returns_409(client):
    test_client, session_factory = client
    create_user(session_factory, username="taken_name")
    user = create_user(session_factory, username="renamer")

    response = test_client.put(
        "/api/v1/user/profile",
        headers=auth_header(user.id, user.token_version),
        json={"username": "taken_name"},
    )
    assert response.status_code == 409


def test_consent_list_returns_records(client):
    test_client, session_factory = client
    user = create_user(session_factory, username="consenter", email="consenter@example.com")

    from app.services.consent_service import consent_service

    db = session_factory()
    try:
        consent_service.record(
            db,
            user=user,
            consent_type="privacy_policy",
            version="v1",
            content_hash="a" * 64,
            scope={"purpose": "account_creation"},
        )
    finally:
        db.close()

    response = test_client.get("/api/v1/user/consent", headers=auth_header(user.id, user.token_version))
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["consent_type"] == "privacy_policy"


def test_deleted_user_rejected_by_protected_endpoint(client):
    """注销后访问任何登录态接口：401（P2-4.3 软删除拦截）。"""
    test_client, session_factory = client
    user = create_user(session_factory, username="ghost")
    db = session_factory()
    try:
        from app.utils.datetime_utils import utc_now

        user.deleted_at = utc_now()
        user.is_active = False
        db.add(user)
        db.commit()
    finally:
        db.close()

    response = test_client.get("/api/v1/user/consent", headers=auth_header(user.id, user.token_version))
    assert response.status_code == 401
