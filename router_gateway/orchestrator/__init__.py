# -*- coding: utf-8 -*-
"""任务编排：幂等提交、候选排序、故障切换、慢任务对冲与状态一致性。"""
from ..router import RankedRoute, rank_candidates
from .policy import (
    ACTIVE_ATTEMPT,
    OCCUPIED_ATTEMPT,
    REVIEW_ATTEMPT,
    TERMINAL_ATTEMPT,
    TERMINAL_JOB,
    deadline_remaining,
    hedge_due,
    select_failover_route,
    select_hedge_route,
)
from .service import AttemptView, JobView, Orchestrator, OrchestratorError

__all__ = [
    "Orchestrator",
    "OrchestratorError",
    "JobView",
    "AttemptView",
    "rank_candidates",
    "select_failover_route",
    "select_hedge_route",
    "hedge_due",
    "deadline_remaining",
    "RankedRoute",
    "TERMINAL_JOB",
    "TERMINAL_ATTEMPT",
    "ACTIVE_ATTEMPT",
    "REVIEW_ATTEMPT",
    "OCCUPIED_ATTEMPT",
]
