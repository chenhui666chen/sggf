"""
实验预算账本测试（设计文档 §9 / §5.5 / §14 第 6 步）

覆盖 prompt_experiment_budgets 表的原子扣减契约：
- reserve   任务创建时预留预估成本 + 占用调用配额；超限或熔断则拒绝（返回 False）
- settle    任务成功：释放预留、记实际花费
- release   任务失败/取消：释放预留（成本已发生的调用配额不回退，防并发超发）
- 熔断 / 预算耗尽判定 → 供上游反推 ε=0

纯持久化层：不接 Celery、不调外部 API。sqlite 内存库可测。
"""
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.models.prompt_experiment import PromptExperimentBudget
from app.services.prompt_evolution.budget_ledger import BudgetLedger

_DATE = "2026-07-30"
_SCOPE = "global"
_KEY = ""


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PromptExperimentBudget.__table__.create(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield db
    finally:
        db.close()


def test_reserve_creates_row_and_accumulates(session):
    ledger = BudgetLedger(session)
    assert ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.02) is True
    session.commit()
    row = ledger.get(_DATE, _SCOPE, _KEY)
    assert row.reserved_cost == pytest.approx(0.02)
    assert row.calls_used == 1


def test_reserve_respects_cost_limit(session):
    ledger = BudgetLedger(session)
    ledger.set_limits(_DATE, _SCOPE, _KEY, cost_limit=0.05, calls_limit=None)
    assert ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.03) is True
    # 再预留 0.03 会使 reserved 累计 0.06 超过 0.05 → 拒绝
    assert ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.03) is False
    row = ledger.get(_DATE, _SCOPE, _KEY)
    assert row.reserved_cost == pytest.approx(0.03)
    assert row.calls_used == 1


def test_reserve_respects_calls_limit(session):
    ledger = BudgetLedger(session)
    ledger.set_limits(_DATE, _SCOPE, _KEY, cost_limit=None, calls_limit=2)
    assert ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.01) is True
    assert ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.01) is True
    assert ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.01) is False


def test_reserve_rejected_when_circuit_open(session):
    ledger = BudgetLedger(session)
    ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.01)
    ledger.open_circuit(_DATE, _SCOPE, _KEY)
    session.commit()
    assert ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.01) is False


def test_settle_releases_reservation_and_records_actual(session):
    ledger = BudgetLedger(session)
    ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.02)
    ledger.settle(_DATE, _SCOPE, _KEY, reserved_cost=0.02, actual_cost=0.015)
    session.commit()
    row = ledger.get(_DATE, _SCOPE, _KEY)
    assert row.reserved_cost == pytest.approx(0.0)
    assert row.cost_used == pytest.approx(0.015)
    assert row.calls_used == 1  # 调用配额不因结算回退


def test_release_frees_reservation_without_cost(session):
    ledger = BudgetLedger(session)
    ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.02)
    ledger.release(_DATE, _SCOPE, _KEY, reserved_cost=0.02)
    session.commit()
    row = ledger.get(_DATE, _SCOPE, _KEY)
    assert row.reserved_cost == pytest.approx(0.0)
    assert row.cost_used == pytest.approx(0.0)
    # 失败释放不回退调用配额（成本可能已发生，防并发超发）
    assert row.calls_used == 1


def test_reserved_cost_never_negative_on_over_release(session):
    ledger = BudgetLedger(session)
    ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.02)
    ledger.release(_DATE, _SCOPE, _KEY, reserved_cost=0.05)  # 释放多于预留
    session.commit()
    row = ledger.get(_DATE, _SCOPE, _KEY)
    assert row.reserved_cost == pytest.approx(0.0)


def test_is_exhausted_by_cost(session):
    ledger = BudgetLedger(session)
    ledger.set_limits(_DATE, _SCOPE, _KEY, cost_limit=0.05, calls_limit=None)
    ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.02)
    ledger.settle(_DATE, _SCOPE, _KEY, reserved_cost=0.02, actual_cost=0.05)
    session.commit()
    assert ledger.is_exhausted(_DATE, _SCOPE, _KEY) is True


def test_is_exhausted_by_calls(session):
    ledger = BudgetLedger(session)
    ledger.set_limits(_DATE, _SCOPE, _KEY, cost_limit=None, calls_limit=1)
    ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.01)
    session.commit()
    assert ledger.is_exhausted(_DATE, _SCOPE, _KEY) is True


def test_is_exhausted_when_circuit_open(session):
    ledger = BudgetLedger(session)
    ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.01)
    ledger.open_circuit(_DATE, _SCOPE, _KEY)
    session.commit()
    assert ledger.is_exhausted(_DATE, _SCOPE, _KEY) is True


def test_is_exhausted_false_within_budget(session):
    ledger = BudgetLedger(session)
    ledger.set_limits(_DATE, _SCOPE, _KEY, cost_limit=1.0, calls_limit=100)
    ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.01)
    session.commit()
    assert ledger.is_exhausted(_DATE, _SCOPE, _KEY) is False


def test_missing_budget_is_not_exhausted(session):
    ledger = BudgetLedger(session)
    # 无该维度账本行 = 未设限，不视为耗尽
    assert ledger.is_exhausted(_DATE, "genre", "科幻") is False


def test_close_circuit_reenables_reserve(session):
    ledger = BudgetLedger(session)
    ledger.open_circuit(_DATE, _SCOPE, _KEY)
    ledger.close_circuit(_DATE, _SCOPE, _KEY)
    session.commit()
    assert ledger.reserve(_DATE, _SCOPE, _KEY, cost=0.01) is True
