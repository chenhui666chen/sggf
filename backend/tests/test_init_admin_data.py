"""初始超管密码去硬编码测试（P2-4.6）。

背景：init_admin_data.py 硬编码 Admin@123456 并在 stdout 打印，属可 grep 的固定默认密码。
"""
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings  # noqa: E402


def _load_script():
    path = ROOT_DIR / "app" / "scripts" / "init_admin_data.py"
    spec = spec_from_file_location("init_admin_data_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 init_admin_data 脚本")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


def test_resolve_prefers_configured_password(monkeypatch):
    """优先使用 INITIAL_ADMIN_PASSWORD 环境变量，不随机、不硬编码。"""
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "EnvAdmin1")
    assert script.resolve_initial_admin_password() == "EnvAdmin1"


def test_resolve_random_in_development(monkeypatch):
    """development 且未配置：随机生成一次（token_urlsafe），不返回空串。"""
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "")
    monkeypatch.setattr(settings, "APP_ENV", "development")
    password = script.resolve_initial_admin_password()
    assert password and len(password) >= 12


def test_resolve_requires_password_in_production(monkeypatch):
    """production/staging 未配置必须报错，禁止继续用可 grep 的默认密码建号。"""
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "")
    monkeypatch.setattr(settings, "APP_ENV", "production")
    with pytest.raises(RuntimeError, match="INITIAL_ADMIN_PASSWORD"):
        script.resolve_initial_admin_password()

    monkeypatch.setattr(settings, "APP_ENV", "staging")
    with pytest.raises(RuntimeError, match="INITIAL_ADMIN_PASSWORD"):
        script.resolve_initial_admin_password()


def test_resolve_rejects_weak_configured_password(monkeypatch):
    """环境变量给的密码必须过策略（评审 #4）：弱密码在任何环境都拒绝，不许原样建号。"""
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "123456")
    monkeypatch.setattr(settings, "APP_ENV", "production")
    with pytest.raises(RuntimeError, match="密码策略"):
        script.resolve_initial_admin_password()

    monkeypatch.setattr(settings, "APP_ENV", "development")
    with pytest.raises(RuntimeError, match="密码策略"):
        script.resolve_initial_admin_password()


def test_create_super_admin_records_password_history(monkeypatch):
    """超管首次创建必须登记初始密码入历史（评审收口）：否则可改回 INITIAL_ADMIN_PASSWORD。

    用真实 Base 建 SQLite 内存表（本测试文件不引入 fake-base 污染其它测试模块）。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.security import hash_password_for_history
    from app.db.base import Base
    from app.models.password_history import PasswordHistory
    from app.models.role import Permission, Role, user_roles
    from app.models.user import User

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Role.__table__,
            Permission.__table__,
            PasswordHistory.__table__,
            user_roles,
        ],
    )

    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "AdminStrong1")
    monkeypatch.setattr(settings, "APP_ENV", "development")

    db = Session()
    try:
        role = Role(code="super_admin", name="超级管理员", description="", is_system=True)
        db.add(role)
        db.commit()
        db.refresh(role)
        script.create_super_admin(db)
    finally:
        db.close()

    db = Session()
    try:
        admin = db.query(User).filter(User.email == "admin@sggf.net").first()
        assert admin is not None
        rows = db.query(PasswordHistory).filter(PasswordHistory.user_id == admin.id).all()
        assert len(rows) == 1, "超管初始密码必须登记入历史"
        assert rows[0].password_pepper_hash == hash_password_for_history("AdminStrong1")
    finally:
        db.close()


def test_resolve_random_password_retries_until_compliant(monkeypatch):
    """development 随机密码必须满足策略（base64url 可能缺数字/大写，需重试，评审 #4）。"""
    monkeypatch.setattr(settings, "INITIAL_ADMIN_PASSWORD", "")
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "PASSWORD_MIN_LENGTH", 8)

    calls = {"count": 0}

    def flaky_token_urlsafe(nbytes: int) -> str:
        calls["count"] += 1
        # 第一次返回无数字、无大写 -> 过不了策略；第二次合规
        if calls["count"] == 1:
            return "lowercaseonly-letters-here"
        return "G0odPass-ok"

    monkeypatch.setattr(script.secrets, "token_urlsafe", flaky_token_urlsafe)
    password = script.resolve_initial_admin_password()
    assert password == "G0odPass-ok"
    assert calls["count"] == 2
    from app.core.password_policy import check_password_strength

    assert check_password_strength(password) is None
