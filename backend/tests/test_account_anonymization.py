"""账户注销后匿名化服务测试（P2-4.3 / 5.3）。

覆盖：超过冷静期（30 天）的已注销账号被匿名化（字段清空/派生 username/历史删除）、
冷静期内不处理、dry-run 不写库、活跃账号不受影响。
"""
import hashlib
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["DEBUG"] = "false"

from app.db.base import Base  # noqa: E402
from app.models.password_history import PasswordHistory  # noqa: E402
from app.models.role import Role, user_roles  # noqa: E402,F401  # 注册 user_roles，User mapper 配置所需
from app.models.user import User  # noqa: E402
from app.services.account_anonymization_service import anonymize_expired_accounts  # noqa: E402
from app.utils.datetime_utils import utc_now  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine, tables=[User.__table__, PasswordHistory.__table__])
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def _make_user(session, *, username: str, deleted_days_ago: int | None) -> User:
    tag = hashlib.sha256(username.encode("utf-8")).hexdigest()[:32]
    user = User(
        username=username,
        email=f"{username}@example.com",
        phone=f"139{int(tag[:8], 16) % 100000000:08d}",
        full_name=username,
        avatar_url="http://example.com/avatar.png",
        password_hash="fakehash",
        email_verified=True,
        consent_version="v1",
        alipay_openid_hash=tag + "a",
        alipay_openid_encrypted="cipher-a-" + username,
        wechat_openid_hash=tag + "b",
        wechat_openid_encrypted="cipher-b-" + username,
        wechat_unionid_hash=tag + "c",
        wechat_unionid_encrypted="cipher-c-" + username,
        token_version=1,
    )
    if deleted_days_ago is not None:
        user.is_active = False
        user.deleted_at = utc_now() - timedelta(days=deleted_days_ago)
    session.add(user)
    session.commit()
    session.refresh(user)
    if deleted_days_ago is not None:
        session.add(
            PasswordHistory(user_id=user.id, password_pepper_hash="p" * 64)
        )
        session.commit()
    return user


def test_anonymize_expired_accounts(db):
    expired = _make_user(session=db, username="old_deleted", deleted_days_ago=40)
    recent = _make_user(session=db, username="recent_deleted", deleted_days_ago=10)
    active = _make_user(session=db, username="active_user", deleted_days_ago=None)

    count = anonymize_expired_accounts(db, cooling_days=30)
    assert count == 1

    old = db.query(User).filter(User.id == expired.id).first()
    assert old.username == f"deleted_{expired.id}"
    assert old.email is None and old.phone is None
    assert old.full_name is None and old.avatar_url is None
    assert old.password_hash is None
    assert old.email_verified is False
    assert old.consent_version is None
    assert old.alipay_openid_hash is None and old.alipay_openid_encrypted is None
    assert old.wechat_openid_hash is None and old.wechat_unionid_encrypted is None
    assert old.token_version == 2, "匿名化必须递增 tv（残留会话全失效）"
    assert (
        db.query(PasswordHistory).filter(PasswordHistory.user_id == expired.id).first() is None
    ), "密码历史随匿名化删除"

    still_recent = db.query(User).filter(User.id == recent.id).first()
    assert still_recent.email == "recent_deleted@example.com", "冷静期内不得匿名化"
    assert still_recent.deleted_at is not None

    untouched = db.query(User).filter(User.id == active.id).first()
    assert untouched.username == "active_user"


def test_dry_run_does_not_write(db):
    expired = _make_user(session=db, username="dry_run_user", deleted_days_ago=40)

    count = anonymize_expired_accounts(db, cooling_days=30, apply_write=False)
    assert count == 1

    row = db.query(User).filter(User.id == expired.id).first()
    assert row.username == "dry_run_user", "dry-run 不得改动数据"
    assert row.email == "dry_run_user@example.com"
    assert row.deleted_at is not None
