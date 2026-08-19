"""域 3+4 合同级测试（GUIDE §6/§7）。

覆盖：
- 父任务聚合互斥矩阵（R17/P1-2 穷尽规则）
- normalize_run_status 投影映射
- ledger 转态服务（pending → succeeded/confirmed_failed/manual_reconciliation）
- strict barrier 校验
- run 终态关账逻辑
- finalizer 前置条件校验
"""

import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")


# ---------------------------------------------------------------------------
# normalize_run_status 投影映射
# ---------------------------------------------------------------------------

class TestNormalizeRunStatus:
    def setup_method(self):
        from app.services.audiobook.task_aggregation_service import normalize_run_status
        self.normalize = normalize_run_status

    def test_pending_maps_to_queued(self):
        assert self.normalize("pending") == "queued"

    def test_queued_stays_queued(self):
        assert self.normalize("queued") == "queued"

    def test_running_stays_running(self):
        assert self.normalize("running") == "running"

    def test_paused_stays_paused(self):
        assert self.normalize("paused") == "paused"

    def test_pause_requested_stays(self):
        assert self.normalize("pause_requested") == "pause_requested"

    def test_completed_maps_to_succeeded(self):
        assert self.normalize("completed") == "succeeded"

    def test_expired_maps_to_cancelled(self):
        """R15/P0-1：expired 归入 cancelled"""
        assert self.normalize("expired") == "cancelled"

    def test_failed_stays_failed(self):
        assert self.normalize("failed") == "failed"

    def test_canceled_maps_to_cancelled(self):
        assert self.normalize("canceled") == "cancelled"

    def test_cancelled_stays_cancelled(self):
        assert self.normalize("cancelled") == "cancelled"

    def test_null_maps_to_unknown(self):
        assert self.normalize(None) == "unknown"

    def test_empty_string_maps_to_unknown(self):
        assert self.normalize("") == "unknown"

    def test_arbitrary_value_maps_to_unknown(self):
        assert self.normalize("something_weird") == "unknown"


# ---------------------------------------------------------------------------
# 父任务聚合互斥矩阵（R17/P1-2）
# ---------------------------------------------------------------------------

class TestParentTaskAggregationMatrix:
    """互斥矩阵穷尽测试（R17/P1-2 修复 {cancelled, failed} 无结果缺陷）。"""

    def setup_method(self):
        from app.services.audiobook.task_aggregation_service import aggregate_parent_task_status
        self.aggregate = aggregate_parent_task_status

    def _make_db(self, run_statuses):
        """构造 mock db，返回指定状态的 run 列表。"""
        mock_runs = [SimpleNamespace(status=s) for s in run_statuses]
        mock_query = MagicMock()
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = mock_runs
        db = MagicMock()
        db.query.return_value = mock_query
        return db

    def test_rule_1_any_unknown_fails_closed(self):
        """① 任一 unknown → fail-closed: failed"""
        db = self._make_db(["completed", "something_weird"])
        result = self.aggregate(db, task_id=1)
        assert result["status"] == "failed"
        assert "aggregation_unknown_status" in str(result.get("detail", {}))

    def test_rule_2_any_running_parent_running(self):
        """② 任一 running/queued → running"""
        db = self._make_db(["completed", "running"])
        result = self.aggregate(db, task_id=1)
        assert result["status"] == "running"

    def test_rule_2_any_queued_parent_running(self):
        """② 任一 queued 也算进行中"""
        db = self._make_db(["completed", "pending"])
        result = self.aggregate(db, task_id=1)
        assert result["status"] == "running"

    def test_rule_3_all_succeeded_completed(self):
        """③ 全部 succeeded → completed"""
        db = self._make_db(["completed", "completed"])
        result = self.aggregate(db, task_id=1)
        assert result["status"] == "completed"

    def test_rule_4_all_cancelled(self):
        """④ 全部 cancelled → cancelled"""
        db = self._make_db(["cancelled", "canceled"])
        result = self.aggregate(db, task_id=1)
        assert result["status"] == "cancelled"

    def test_rule_5_succeeded_plus_failed_partial(self):
        """⑤ 至少 succeeded + 存在 failed → completed_with_partial_failure"""
        db = self._make_db(["completed", "failed"])
        result = self.aggregate(db, task_id=1)
        assert result["status"] == "completed_with_partial_failure"

    def test_rule_5_succeeded_plus_cancelled_partial(self):
        """⑤ 至少 succeeded + cancelled → completed_with_partial_failure"""
        db = self._make_db(["completed", "cancelled"])
        result = self.aggregate(db, task_id=1)
        assert result["status"] == "completed_with_partial_failure"

    def test_rule_6_no_succeeded_with_failed(self):
        """⑥ 无 succeeded + 至少 failed → failed"""
        db = self._make_db(["failed"])
        result = self.aggregate(db, task_id=1)
        assert result["status"] == "failed"

    def test_rule_6_cancelled_plus_failed(self):
        """⑥ {cancelled, failed} → failed（R17/P1-2 补定义的组合）"""
        db = self._make_db(["cancelled", "failed"])
        result = self.aggregate(db, task_id=1)
        assert result["status"] == "failed"

    def test_no_dispatches_returns_none(self):
        """无子派发 → 不适用矩阵"""
        mock_query = MagicMock()
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        db = MagicMock()
        db.query.return_value = mock_query
        result = self.aggregate(db, task_id=1)
        assert result["status"] is None


# ---------------------------------------------------------------------------
# ledger 转态服务
# ---------------------------------------------------------------------------

class TestLedgerTransitionService:
    def test_record_pending_call_creates_ledger(self):
        from app.services.audiobook.ledger_transition_service import record_pending_call

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.flush = MagicMock()

        result = record_pending_call(
            db,
            run_id=1,
            attempt_key="test:1",
            provider="dashscope_seed",
            usage_kind="seed_render",
            unit="second",
        )
        db.add.assert_called_once()
        db.flush.assert_called_once()
        assert result.status == "pending"
        assert result.commit_stage == "pre_call"

    def test_record_pending_call_idempotent(self):
        """同 run 同 attempt_key 幂等"""
        from app.services.audiobook.ledger_transition_service import record_pending_call

        existing = SimpleNamespace(
            id=42, run_id=1, attempt_key="test:1", status="pending"
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing

        result = record_pending_call(
            db, run_id=1, attempt_key="test:1",
            provider="dashscope_seed", usage_kind="seed_render", unit="second",
        )
        assert result is existing  # 返回原记录，不新增

    def test_close_accounting_no_evidence_confirmed_failed(self):
        """无供应商证据 → confirmed_failed"""
        from app.services.audiobook.ledger_transition_service import close_accounting_on_run_terminal

        ledger = SimpleNamespace(
            id=1, run_id=10, status="pending",
            commit_stage="pre_call", provider_request_id=None,
            idempotency_key_sent=False,
        )
        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.all.return_value = [ledger]
        db.query.return_value = mock_query

        result = close_accounting_on_run_terminal(db, run_id=10)
        assert result["confirmed_failed"] == 1
        assert ledger.status == "confirmed_failed"

    def test_close_accounting_with_evidence_manual_reconciliation(self):
        """已发出请求但结果不明 → manual_reconciliation"""
        from app.services.audiobook.ledger_transition_service import close_accounting_on_run_terminal

        ledger = SimpleNamespace(
            id=2, run_id=10, status="pending",
            commit_stage="post_call", provider_request_id="req-123",
            idempotency_key_sent=True,
        )
        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.all.return_value = [ledger]
        db.query.return_value = mock_query

        result = close_accounting_on_run_terminal(db, run_id=10)
        assert result["manual_reconciliation"] == 1
        assert ledger.status == "manual_reconciliation"


# ---------------------------------------------------------------------------
# strict barrier 校验
# ---------------------------------------------------------------------------

class TestStrictBarrier:
    def test_barrier_passes_all_terminal(self):
        from app.services.audiobook.ledger_transition_service import check_strict_barrier

        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.group_by.return_value.all.return_value = [
            ("succeeded", 3),
            ("confirmed_failed", 1),
        ]
        db.query.return_value = mock_query

        result = check_strict_barrier(db, run_id=1)
        assert result["passed"] is True

    def test_barrier_fails_with_pending(self):
        from app.services.audiobook.ledger_transition_service import check_strict_barrier

        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.group_by.return_value.all.return_value = [
            ("succeeded", 2),
            ("pending", 1),
        ]
        db.query.return_value = mock_query

        result = check_strict_barrier(db, run_id=1)
        assert result["passed"] is False
        assert result["pending_count"] == 1

    def test_barrier_fails_with_manual_reconciliation(self):
        from app.services.audiobook.ledger_transition_service import check_strict_barrier

        db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.group_by.return_value.all.return_value = [
            ("succeeded", 2),
            ("manual_reconciliation", 1),
        ]
        db.query.return_value = mock_query

        result = check_strict_barrier(db, run_id=1)
        assert result["passed"] is False
        assert result["manual_count"] == 1


# ---------------------------------------------------------------------------
# finalizer 前置条件
# ---------------------------------------------------------------------------

class TestFinalizerPreconditions:
    def test_terminal_statuses(self):
        from app.services.audiobook.billing_finalizer_service import TERMINAL_RUN_STATUSES

        assert "completed" in TERMINAL_RUN_STATUSES
        assert "failed" in TERMINAL_RUN_STATUSES
        assert "cancelled" in TERMINAL_RUN_STATUSES
        assert "canceled" in TERMINAL_RUN_STATUSES
        assert "expired" in TERMINAL_RUN_STATUSES
        assert "running" not in TERMINAL_RUN_STATUSES
        assert "pending" not in TERMINAL_RUN_STATUSES

    def test_worker_lease_valid_future(self):
        from app.services.audiobook.billing_finalizer_service import _worker_lease_valid
        from datetime import timedelta
        from app.utils.datetime_utils import utc_now

        run = SimpleNamespace(lease_expires_at=utc_now() + timedelta(hours=1))
        assert _worker_lease_valid(run) is True

    def test_worker_lease_valid_expired(self):
        from app.services.audiobook.billing_finalizer_service import _worker_lease_valid
        from datetime import timedelta
        from app.utils.datetime_utils import utc_now

        run = SimpleNamespace(lease_expires_at=utc_now() - timedelta(hours=1))
        assert _worker_lease_valid(run) is False

    def test_worker_lease_valid_null(self):
        from app.services.audiobook.billing_finalizer_service import _worker_lease_valid

        run = SimpleNamespace(lease_expires_at=None)
        assert _worker_lease_valid(run) is False
