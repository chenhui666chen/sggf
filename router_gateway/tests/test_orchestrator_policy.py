# -*- coding: utf-8 -*-
"""编排纯策略测试：排序、故障切换选路、对冲选路、慢任务/截止判定。不碰数据库与网络。"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from router_gateway.catalog import (
    DurationRange,
    Mode,
    Route,
    RouteCapability,
    VideoSpec,
)
from router_gateway.orchestrator.policy import (
    TERMINAL_ATTEMPT,
    TERMINAL_JOB,
    deadline_remaining,
    hedge_due,
    is_terminal,
    select_failover_route,
    select_hedge_route,
)
from router_gateway.router import rank_candidates
from router_gateway.stats import RouteStats


T0 = datetime(2026, 10, 12, 0, 0, 0, tzinfo=timezone.utc)


def _cap():
    return RouteCapability(
        billing="per_second",
        duration=DurationRange(1, 30),
        resolutions=("720p",),
        aspect_ratios=("16:9",),
        input_modes=frozenset({Mode.TEXT}),
    )


def _route(route_id, provider="erchun", price="0.40"):
    return Route(route_id=route_id, provider=provider, upstream_model=f"m-{route_id}",
                 quality_group="h3", capability=_cap(), pricing={"720p": price})


def _req():
    return VideoSpec(prompt="x", duration_seconds=5, resolution="720p", aspect_ratio="16:9")


def test_rank按期望成本升序并带报价():
    cheap = _route("cheap", price="0.07")
    pricey = _route("pricey", price="0.40")
    ranked = rank_candidates([pricey, cheap], _req(), {})
    assert [r.route.route_id for r in ranked] == ["cheap", "pricey"]
    assert ranked[0].quote == Decimal("0.35")
    assert ranked[0].expected_cost > 0


def test_rank排除熔断路线():
    dead = _route("dead", price="0.01")
    alive = _route("alive", price="0.40")
    stats = {"dead": RouteStats(samples=100, success_rate=0.5, p50_seconds=100,
                                p95_seconds=200)}
    ranked = rank_candidates([dead, alive], _req(), stats)
    assert [r.route.route_id for r in ranked] == ["alive"]


def test_rank无候选返回空列表():
    # 路线时长上限 30s；60s 请求无合格候选
    assert rank_candidates([_route("r")], VideoSpec("x", 60, "720p", "16:9"), {}) == []


def test_rank兜底路线即使更便宜也沉到正常路线之后():
    # 实测排队约43分钟的便宜档标 standby：正常路线先选，兜底仍留在出片链中
    standby_cheap = replace(_route("standby-cheap", price="0.07"), standby=True)
    normal_pricey = _route("normal-pricey", price="0.72")
    ranked = rank_candidates([standby_cheap, normal_pricey], _req(), {})
    assert [r.route.route_id for r in ranked] == ["normal-pricey", "standby-cheap"]


def test_rank多条兜底路线内部仍按期望成本排序():
    a = replace(_route("sb-a", price="0.30"), standby=True)
    b = replace(_route("sb-b", price="0.10"), standby=True)
    normal = _route("normal", price="0.80")
    ranked = rank_candidates([a, normal, b], _req(), {})
    assert [r.route.route_id for r in ranked] == ["normal", "sb-b", "sb-a"]


def test_故障切换跳过本任务已用过的路线保持排序():
    a, b, c = _route("a", price="0.40"), _route("b", price="0.08"), _route("c", price="0.10")
    ranked = rank_candidates([a, b, c], _req(), {})
    nxt = select_failover_route(ranked, used_route_ids={"b"})
    assert nxt.route.route_id == "c"


def test_故障切换无剩余路线返回None():
    a = _route("a")
    ranked = rank_candidates([a], _req(), {})
    assert select_failover_route(ranked, used_route_ids={"a"}) is None


def test_对冲优先选另一家供应商的合格路线():
    # 同供应商更便宜，但对冲目的是降同源故障，跨源优先
    same_cheap = _route("erchun-2", provider="erchun", price="0.05")
    other = _route("suanliai-1", provider="suanliai", price="0.40")
    ranked = rank_candidates([same_cheap, other], _req(), {})
    pick = select_hedge_route(ranked, used_route_ids={"erchun-1"},
                              active_providers={"erchun"})
    assert pick.route.route_id == "suanliai-1"


def test_对冲没有跨源路线时才用同源剩余路线():
    a2 = _route("erchun-2", provider="erchun")
    ranked = rank_candidates([a2], _req(), {})
    pick = select_hedge_route(ranked, used_route_ids={"erchun-1"},
                              active_providers={"erchun"})
    assert pick.route.route_id == "erchun-2"


def test_对冲已用路线全部排除():
    a2 = _route("erchun-2", provider="erchun")
    ranked = rank_candidates([a2], _req(), {})
    assert select_hedge_route(ranked, used_route_ids={"erchun-1", "erchun-2"},
                              active_providers={"erchun"}) is None


class _Attempt:
    def __init__(self, status, submit_at, is_hedge=False):
        self.status = status
        self.submit_at = submit_at
        self.is_hedge = is_hedge


def test_超过p95基线且开关开启时对冲到期():
    active = _Attempt("running", T0)
    stats = RouteStats(samples=100, success_rate=0.99, p50_seconds=100, p95_seconds=200)
    assert hedge_due(active, stats=stats, fallback_seconds=600, now=T0 + timedelta(seconds=201),
                     active_attempt_count=1, max_parallel=2, allow_hedge=True,
                     remaining_seconds=60) is True


def test_未达p95基线不对冲():
    active = _Attempt("running", T0)
    stats = RouteStats(samples=100, success_rate=0.99, p50_seconds=100, p95_seconds=200)
    assert hedge_due(active, stats=stats, fallback_seconds=600, now=T0 + timedelta(seconds=199),
                     active_attempt_count=1, max_parallel=2, allow_hedge=True,
                     remaining_seconds=60) is False


def test_样本不足时回退固定秒数阈值():
    active = _Attempt("running", T0)
    stats = RouteStats(samples=3, success_rate=1.0, p50_seconds=50, p95_seconds=80)
    assert hedge_due(active, stats=stats, fallback_seconds=300, now=T0 + timedelta(seconds=299),
                     active_attempt_count=1, max_parallel=2, allow_hedge=True,
                     remaining_seconds=60) is False
    assert hedge_due(active, stats=stats, fallback_seconds=300, now=T0 + timedelta(seconds=301),
                     active_attempt_count=1, max_parallel=2, allow_hedge=True,
                     remaining_seconds=60) is True


def test_开关关闭或已达并行上限或无剩余时间不对冲():
    active = _Attempt("running", T0)
    stats = RouteStats(samples=100, success_rate=1.0, p50_seconds=100, p95_seconds=200)
    common = dict(stats=stats, fallback_seconds=300, now=T0 + timedelta(seconds=500))
    assert hedge_due(active, active_attempt_count=1, max_parallel=2, allow_hedge=False,
                     remaining_seconds=60, **common) is False
    assert hedge_due(active, active_attempt_count=2, max_parallel=2, allow_hedge=True,
                     remaining_seconds=60, **common) is False
    assert hedge_due(active, active_attempt_count=1, max_parallel=2, allow_hedge=True,
                     remaining_seconds=0, **common) is False


def test_排队中的尝试也可作为慢任务对冲对象():
    queued = _Attempt("queued", T0)
    stats = RouteStats(samples=100, success_rate=1.0, p50_seconds=100, p95_seconds=200)
    assert hedge_due(queued, stats=stats, fallback_seconds=600, now=T0 + timedelta(seconds=201),
                     active_attempt_count=1, max_parallel=2, allow_hedge=True,
                     remaining_seconds=60) is True


def test_终态尝试不参与对冲():
    done = _Attempt("succeeded", T0)
    stats = RouteStats(samples=100, success_rate=1.0, p50_seconds=100, p95_seconds=200)
    assert hedge_due(done, stats=stats, fallback_seconds=600, now=T0 + timedelta(seconds=9999),
                     active_attempt_count=1, max_parallel=2, allow_hedge=True,
                     remaining_seconds=60) is False


def test_审核挂起尝试不参与对冲():
    # review 是人工核对挂起：等待人工而非与上游竞速，再慢也不能开对冲
    reviewing = _Attempt("review", T0)
    stats = RouteStats(samples=100, success_rate=1.0, p50_seconds=100, p95_seconds=200)
    assert hedge_due(reviewing, stats=stats, fallback_seconds=300,
                     now=T0 + timedelta(seconds=9999),
                     active_attempt_count=1, max_parallel=2, allow_hedge=True,
                     remaining_seconds=60) is False


def test_截止剩余时间计算与无截止约定():
    created = T0
    assert deadline_remaining(created, deadline_seconds=600, now=T0 + timedelta(seconds=100)) == 500
    assert deadline_remaining(created, deadline_seconds=None, now=T0) is None
    assert deadline_remaining(created, deadline_seconds=10, now=T0 + timedelta(seconds=11)) == -1


def test_状态终态判定():
    assert is_terminal("succeeded", TERMINAL_JOB)
    assert is_terminal("failed", TERMINAL_JOB)
    assert not is_terminal("running", TERMINAL_JOB)
    assert is_terminal("failed", TERMINAL_ATTEMPT)
    assert is_terminal("unknown", TERMINAL_ATTEMPT)
    assert not is_terminal("queued", TERMINAL_ATTEMPT)
