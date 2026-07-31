"""
实验预算账本（设计文档 §9 / §5.5 / §14 第 6 步）

prompt_experiment_budgets 表的原子扣减：按 (日期 × 维度 × 维度键) 一行，
预留（reserve）→ 结算（settle）/ 释放（release）三段式，配合供应商熔断。

语义（防并发超发是账本问题，不是 ε 比例问题）：
- reserve：任务创建时同事务预留预估成本 + 占用一次调用配额；超限或熔断则拒绝；
- settle：任务成功，释放预留额、累加实际花费（调用配额不回退）；
- release：任务失败/取消，仅释放预留额（成本可能已发生，调用配额不回退）；
- is_exhausted：熔断 / 费用达上限 / 调用达上限任一命中 → 上游据此把 ε 降为 0。

事务边界由调用方掌控，本层只 flush 不 commit。
纯持久化层：不接 Celery、不调外部 API。
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.prompt_experiment import PromptExperimentBudget

logger = logging.getLogger(__name__)


class BudgetLedger:
    """实验预算账本（prompt_experiment_budgets 表）"""

    def __init__(self, session: Session):
        self.session = session

    def get(
        self, budget_date: str, scope: str, scope_key: str, *, for_update: bool = False
    ) -> Optional[PromptExperimentBudget]:
        query = self.session.query(PromptExperimentBudget).filter(
            PromptExperimentBudget.budget_date == budget_date,
            PromptExperimentBudget.scope == scope,
            PromptExperimentBudget.scope_key == scope_key,
        )
        if for_update:
            # 资金路径行级锁：同一账本行的 read-modify-write 串行化，防并发超发
            # （sqlite 方言忽略 FOR UPDATE，不影响单测）
            query = query.with_for_update()
        return query.one_or_none()

    def _get_or_create(
        self, budget_date: str, scope: str, scope_key: str, *, for_update: bool = False
    ) -> PromptExperimentBudget:
        """
        并发说明：check-then-insert 存在竞态窗口，数据正确性由唯一约束
        uq_prompt_experiment_budgets_scope 兜底；并发双插时后提交方会收到
        IntegrityError，调用方应回滚后重试（重查必得既有行）。
        """
        row = self.get(budget_date, scope, scope_key, for_update=for_update)
        if row is None:
            row = PromptExperimentBudget(
                budget_date=budget_date,
                scope=scope,
                scope_key=scope_key,
            )
            self.session.add(row)
            self.session.flush()
        return row

    def set_limits(
        self,
        budget_date: str,
        scope: str,
        scope_key: str,
        *,
        cost_limit: Optional[float],
        calls_limit: Optional[int],
    ) -> PromptExperimentBudget:
        row = self._get_or_create(budget_date, scope, scope_key)
        row.cost_limit = cost_limit
        row.calls_limit = calls_limit
        self.session.flush()
        return row

    def reserve(
        self, budget_date: str, scope: str, scope_key: str, *, cost: float, calls: int = 1
    ) -> bool:
        """
        预留预估成本并占用调用配额。熔断开启或（叠加本次后）越限则拒绝，不改动账本。
        行级锁串行化同一账本行，防止并发 read-modify-write 双双越限（§9 原子扣减红线）。
        """
        row = self._get_or_create(budget_date, scope, scope_key, for_update=True)
        if row.circuit_open:
            return False
        if row.calls_limit is not None and row.calls_used + calls > row.calls_limit:
            return False
        if (
            row.cost_limit is not None
            and row.cost_used + row.reserved_cost + cost > row.cost_limit
        ):
            return False
        row.calls_used += calls
        row.reserved_cost += cost
        self.session.flush()
        return True

    def settle(
        self,
        budget_date: str,
        scope: str,
        scope_key: str,
        *,
        reserved_cost: float,
        actual_cost: float,
    ) -> PromptExperimentBudget:
        """任务成功：释放预留额、累加实际花费（行级锁防并发丢更新）。"""
        row = self._get_or_create(budget_date, scope, scope_key, for_update=True)
        row.reserved_cost = max(0.0, row.reserved_cost - reserved_cost)
        row.cost_used += actual_cost
        self.session.flush()
        return row

    def release(
        self, budget_date: str, scope: str, scope_key: str, *, reserved_cost: float
    ) -> PromptExperimentBudget:
        """任务失败/取消：仅释放预留额（调用配额不回退，成本可能已发生；行级锁防并发丢更新）。"""
        row = self._get_or_create(budget_date, scope, scope_key, for_update=True)
        row.reserved_cost = max(0.0, row.reserved_cost - reserved_cost)
        self.session.flush()
        return row

    def open_circuit(
        self, budget_date: str, scope: str, scope_key: str
    ) -> PromptExperimentBudget:
        """供应商连续超时/错误率越限时熔断该维度。"""
        row = self._get_or_create(budget_date, scope, scope_key)
        row.circuit_open = True
        self.session.flush()
        return row

    def close_circuit(
        self, budget_date: str, scope: str, scope_key: str
    ) -> PromptExperimentBudget:
        row = self._get_or_create(budget_date, scope, scope_key)
        row.circuit_open = False
        self.session.flush()
        return row

    def is_circuit_open(self, budget_date: str, scope: str, scope_key: str) -> bool:
        row = self.get(budget_date, scope, scope_key)
        return bool(row and row.circuit_open)

    def is_exhausted(self, budget_date: str, scope: str, scope_key: str) -> bool:
        """
        预算是否耗尽（供上游把 ε 降为 0）：无账本行视为未设限（不耗尽）。
        熔断 / 费用（已用 + 预留）达上限 / 调用达上限 任一命中即耗尽。
        """
        row = self.get(budget_date, scope, scope_key)
        if row is None:
            return False
        if row.circuit_open:
            return True
        if row.cost_limit is not None and row.cost_used + row.reserved_cost >= row.cost_limit:
            return True
        if row.calls_limit is not None and row.calls_used >= row.calls_limit:
            return True
        return False
