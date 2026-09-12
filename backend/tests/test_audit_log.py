"""审计日志服务测试（P2-4.4）。

覆盖：脱敏哈希（确定性/独立 pepper）、record 只落哈希不落明文、90 天保留清理、
pepper 缺失 fail-closed。AUDIT_LOG_PEPPER 由 conftest 注入。
"""
import os
import re
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

from app.models.audit_log import AuditLog  # noqa: E402
from app.models.role import Role, user_roles  # noqa: E402,F401  # 注册 user_roles，User mapper 配置所需
from app.services.audit_log_service import (  # noqa: E402
    audit_hash,
    audit_ip_hash,
    audit_user_agent_hash,
    cleanup_expired_audit_logs,
    record_audit,
)
from app.utils.datetime_utils import utc_now  # noqa: E402

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    AuditLog.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_audit_hash_is_deterministic_and_peppered():
    """同值同哈希（可检索）；换 pepper 哈希全变；不落明文。"""
    first = audit_hash("127.0.0.1")
    assert _HEX64.match(first)
    assert first == audit_hash("127.0.0.1")
    assert first != audit_hash("127.0.0.2")


def test_record_only_stores_hashes_not_plaintext(db):
    """record 落 IP/UA 哈希，绝不落明文 IP / UA / 账号信息。"""
    log = record_audit(
        db,
        event_type="login",
        user_id=42,
        ip="203.0.113.7",
        user_agent="Mozilla/5.0 (X11; Linux) test-agent",
    )
    assert log.ip_hash == audit_ip_hash("203.0.113.7")
    assert log.user_agent_hash == audit_user_agent_hash("Mozilla/5.0 (X11; Linux) test-agent")
    assert "203.0.113.7" not in str(log.ip_hash)
    assert "Mozilla" not in str(log.user_agent_hash)


def test_cleanup_removes_only_expired(db):
    """超保留期（90 天）的删除，新记录保留。"""
    old = record_audit(db, event_type="login", user_id=1)
    old_id = old.id  # 提前捕获：清理后该实例已删除，再访问会触发 reload 报错
    db.query(AuditLog).filter(AuditLog.id == old_id).update(
        {"created_at": utc_now() - timedelta(days=91)}
    )
    db.commit()

    fresh = record_audit(db, event_type="logout", user_id=2)
    fresh_id = fresh.id

    purged = cleanup_expired_audit_logs(db, retention_days=90)
    assert purged == 1
    assert db.query(AuditLog).filter(AuditLog.id == fresh_id).first() is not None
    assert db.query(AuditLog).filter(AuditLog.id == old_id).first() is None


def test_record_rejects_empty_pepper(monkeypatch, db):
    """pepper 缺失（fail-closed）：拒绝记录，避免退化为已知 key 哈希。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "AUDIT_LOG_PEPPER", "")
    with pytest.raises(ValueError, match="AUDIT_LOG_PEPPER"):
        record_audit(
            db, event_type="login", user_id=1, ip="1.2.3.4", user_agent="ua"
        )


def test_privacy_policy_content_hash_covers_full_text():
    """P2-5.5：privacy_policy 的 content_hash 必须基于政策正文全文，不得退化为短文案。

    存证对象 = 用户勾选同意时看到的政策文本（/privacy 展示页与
    docs/PRIVACY_POLICY.md 的内容）。正文变更须升版本并重新征得同意。
    """
    from app.services.consent_service import (
        CONSENT_TEXTS,
        PRIVACY_POLICY_V1_TEXT,
        sha256_content_hash,
    )

    text = CONSENT_TEXTS["privacy_policy"]
    assert text == PRIVACY_POLICY_V1_TEXT
    assert len(text) > 1000, "存证对象必须是政策正文全文，不得退化为短文案"

    # 5.5 大纲七项关键要素 + 定稿信息逐一在正文出现
    for keyword in (
        "收集的个人信息",
        "保存期限",
        "共享",
        "你的权利",
        "未成年人",
        "本政策如何更新",
        "371640372@qq.com",
        "南京拾光工坊信息科技有限公司",
        "2026 年 9 月 2 日",
    ):
        assert keyword in text, f"政策正文缺少关键要素：{keyword}"

    # content_hash 可由正文确定性重现（存证可校验）
    assert sha256_content_hash(text) == sha256_content_hash(PRIVACY_POLICY_V1_TEXT)
