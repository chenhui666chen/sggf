"""历史 ledger 清洗合同测试（GUIDE R17/P1-4，验收 85）。

覆盖：
- succeeded 缺定价事实 → 从 run_input_snapshot 确定性恢复（回填 pricing_key/snapshot_id）
- 无法恢复 → 显式转 manual_reconciliation（拒绝自动结算，不 NULL 静默放行）
- unit 变体归一化（second/char）
- unit 无法归一 → manual_reconciliation
- 幂等：已清洗记录不再处理
"""

import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

from app.db.base import Base  # noqa: E402
from app.models.audiobook import (  # noqa: E402
    AudiobookProject,
    ChapterAudioRun,
)
from app.models.billing_usage_ledger import BillingUsageLedger  # noqa: E402
from app.models.project import Chapter, Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.audiobook.ledger_history_cleanup import (  # noqa: E402
    run_ledger_history_cleanup,
)

_TABLES = [
    User.__table__,
    Project.__table__,
    Chapter.__table__,
    AudiobookProject.__table__,
    ChapterAudioRun.__table__,
    BillingUsageLedger.__table__,
]


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _ignore_check_constraints(dbapi_conn, _record):
        # 模拟"施加收紧 CHECK 之前"的历史库：允许插入缺定价事实的 succeeded 脏数据
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA ignore_check_constraints = ON")
        cur.close()

    Base.metadata.create_all(bind=engine, tables=_TABLES)
    yield sessionmaker(bind=engine)
    engine.dispose()


def _seed_run(db, tag: str, *, run_input_snapshot: str = None):
    user = User(username=f"user_{tag}", email=f"{tag}@example.com", password_hash="h", is_active=True)
    db.add(user)
    db.flush()
    project = Project(title=f"proj_{tag}", user_id=user.id, display_no=1)
    db.add(project)
    db.flush()
    chapter = Chapter(project_id=project.id, chapter_number=1, title=f"ch_{tag}", content="x")
    db.add(chapter)
    db.flush()
    batch = AudiobookProject(project_id=project.id)
    db.add(batch)
    db.flush()
    run = ChapterAudioRun(
        audiobook_project_id=batch.id,
        chapter_id=chapter.id,
        run_type="full",
        status="completed",
        run_input_snapshot=run_input_snapshot,
    )
    db.add(run)
    db.flush()
    return run


def _make_snapshot():
    return json.dumps(
        {
            "signed_payload": {
                "billing_context": {
                    "billing_snapshot": {
                        "snapshot_id": "bs-hist-1",
                        "prices": {
                            "seed_scene": {"unit": "second", "price_per_second_yuan": 0.01},
                            "tts": {"unit": "char", "price_per_char_yuan": 0.001},
                        },
                    }
                }
            }
        }
    )


def test_restore_pricing_facts_from_snapshot(db_factory):
    """succeeded 缺定价事实 → 从快照确定性恢复。"""
    db = db_factory()
    run = _seed_run(db, "restore", run_input_snapshot=_make_snapshot())
    ledger = BillingUsageLedger(
        run_id=run.id,
        status="succeeded",
        attempt_key="att:1",
        provider="dashscope_seed",
        usage_kind="seed_render",
        unit="second",
        quantity=Decimal("10.0"),
        pricing_key=None,
        billing_snapshot_id=None,
    )
    db.add(ledger)
    db.commit()

    report = run_ledger_history_cleanup(db)
    assert report["scanned"] == 1
    assert report["restored_from_snapshot"] == 1
    assert report["manual_reconciliation"] == 0

    db.refresh(ledger)
    assert ledger.pricing_key == "seed_scene"
    assert ledger.billing_snapshot_id == "bs-hist-1"
    assert ledger.status == "succeeded"
    db.close()


def test_unrecoverable_goes_manual_reconciliation(db_factory):
    """无法恢复 → 显式 manual_reconciliation（拒绝自动结算）。"""
    db = db_factory()
    run = _seed_run(db, "unrecover", run_input_snapshot=None)
    ledger = BillingUsageLedger(
        run_id=run.id,
        status="succeeded",
        attempt_key="att:1",
        provider="dashscope_seed",
        usage_kind="seed_render",
        unit="second",
        quantity=Decimal("10.0"),
        pricing_key=None,
        billing_snapshot_id=None,
    )
    db.add(ledger)
    db.commit()

    report = run_ledger_history_cleanup(db)
    assert report["scanned"] == 1
    assert report["restored_from_snapshot"] == 0
    assert report["manual_reconciliation"] == 1

    db.refresh(ledger)
    assert ledger.status == "manual_reconciliation"
    db.close()


def test_unit_normalization(db_factory):
    """unit 变体归一化（second/char）。"""
    db = db_factory()
    run = _seed_run(db, "unitnorm", run_input_snapshot=_make_snapshot())
    ledger = BillingUsageLedger(
        run_id=run.id,
        status="succeeded",
        attempt_key="att:1",
        provider="dashscope_seed",
        usage_kind="tts_chars",
        unit="字",
        quantity=Decimal("100.0"),
        pricing_key="tts",
        billing_snapshot_id="bs-hist-1",
    )
    db.add(ledger)
    db.commit()

    report = run_ledger_history_cleanup(db)
    assert report["scanned"] == 1
    assert report["unit_normalized"] == 1

    db.refresh(ledger)
    assert ledger.unit == "char"
    db.close()


def test_unit_unrecoverable_goes_manual(db_factory):
    """unit 无法归一 → manual_reconciliation。"""
    db = db_factory()
    run = _seed_run(db, "unitbad", run_input_snapshot=_make_snapshot())
    ledger = BillingUsageLedger(
        run_id=run.id,
        status="succeeded",
        attempt_key="att:1",
        provider="dashscope_seed",
        usage_kind="tts_chars",
        unit="块",
        quantity=Decimal("100.0"),
        pricing_key="tts",
        billing_snapshot_id="bs-hist-1",
    )
    db.add(ledger)
    db.commit()

    report = run_ledger_history_cleanup(db)
    assert report["scanned"] == 1
    assert report["unit_unrecoverable"] == 1

    db.refresh(ledger)
    assert ledger.status == "manual_reconciliation"
    db.close()


def test_cleanup_is_idempotent(db_factory):
    """幂等：已清洗记录不再处理。"""
    db = db_factory()
    run = _seed_run(db, "idem", run_input_snapshot=_make_snapshot())
    ledger = BillingUsageLedger(
        run_id=run.id,
        status="succeeded",
        attempt_key="att:1",
        provider="dashscope_seed",
        usage_kind="seed_render",
        unit="second",
        quantity=Decimal("10.0"),
        pricing_key=None,
        billing_snapshot_id=None,
    )
    db.add(ledger)
    db.commit()

    first = run_ledger_history_cleanup(db)
    db.commit()
    second = run_ledger_history_cleanup(db)

    assert first["scanned"] == 1
    assert second["scanned"] == 0  # 已恢复定价事实，不再命中
    db.close()
