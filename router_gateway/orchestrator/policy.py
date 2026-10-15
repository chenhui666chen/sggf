# -*- coding: utf-8 -*-
"""编排纯策略：无数据库、无网络、无时钟副作用，全部可独立单测。

语义依据 docs/VIDEO_API_SMART_ROUTING_GUIDE.md §5：
- 故障切换跳过本任务已尝试过的路线；
- 对冲优先选择另一家供应商的合格路线，降低同源故障概率；
- 慢任务阈值取该路线同档 P95，样本不足回退固定秒数；
- 截止时间过后不再启动新尝试。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from ..router import RankedRoute
from ..stats import MIN_SAMPLES_TO_TRUST, RouteStats


TERMINAL_JOB = frozenset({"succeeded", "failed"})
TERMINAL_ATTEMPT = frozenset({"succeeded", "failed", "unknown", "superseded"})
ACTIVE_ATTEMPT = frozenset({"submitted", "queued", "running"})
DELIVERY_PENDING_ATTEMPT = frozenset({"delivery_pending"})
# 人工核对挂起：不判失败、不自动退、不切换、不对冲，但仍占用任务并持续对账
REVIEW_ATTEMPT = frozenset({"review"})
# 占用任务、需要继续轮询对账的尝试（活动态 + 审核挂起态）
OCCUPIED_ATTEMPT = ACTIVE_ATTEMPT | REVIEW_ATTEMPT
# 派发中占位：add_attempt 之后、首次 submit 返回之前的瞬时态。
# 没有 upstream_task_id 不能对账，但必须占用任务，防止 worker tick
# 在 submit 网络窗口内把它误判为失败而向第二家供应商重复下单
DISPATCHING_ATTEMPT = frozenset({"created"})


def is_terminal(status: str, terminal_set=frozenset) -> bool:
    return status in terminal_set


def select_failover_route(ranked: Sequence[RankedRoute],
                          used_route_ids: set[str]) -> Optional[RankedRoute]:
    """故障切换：按排序取下一条本任务未用过的路线。"""
    for item in ranked:
        if item.route.route_id not in used_route_ids:
            return item
    return None


def select_hedge_route(ranked: Sequence[RankedRoute], used_route_ids: set[str],
                       active_providers: set[str]) -> Optional[RankedRoute]:
    """对冲选路：跨供应商优先；全部同源时才选同源剩余路线。"""
    cross_source = same_source = None
    for item in ranked:
        if item.route.route_id in used_route_ids:
            continue
        if item.route.provider not in active_providers:
            cross_source = cross_source or item
        else:
            same_source = same_source or item
    return cross_source or same_source


def hedge_due(attempt, *, stats: Optional[RouteStats], fallback_seconds: int,
              now: datetime, active_attempt_count: int, max_parallel: int,
              allow_hedge: bool, remaining_seconds: Optional[int]) -> bool:
    """判定某个活动尝试是否已慢到值得开对冲。"""
    if not allow_hedge:
        return False
    if attempt.status not in ACTIVE_ATTEMPT:
        return False
    if active_attempt_count >= max_parallel:
        return False
    if remaining_seconds is not None and remaining_seconds <= 0:
        return False
    if attempt.submit_at is None:
        return False
    if stats is not None and stats.samples >= MIN_SAMPLES_TO_TRUST and stats.p95_seconds > 0:
        threshold = stats.p95_seconds
    else:
        threshold = fallback_seconds
    elapsed = (now - attempt.submit_at).total_seconds()
    return elapsed >= threshold


def deadline_remaining(created_at: datetime, *, deadline_seconds: Optional[int],
                       now: datetime) -> Optional[int]:
    if deadline_seconds is None:
        return None
    elapsed = (now - created_at).total_seconds()
    return int(deadline_seconds - elapsed)
