# -*- coding: utf-8 -*-
"""决策器：硬条件过滤 + 期望成本排序。

路线选择与“按秒/按条”无关——价格由路线自己的报价公式给出，
切换临界点由期望成本自动决定，不硬编码秒数。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..catalog import Route, VideoSpec
from ..stats import RouteStats
from .preflight import preflight


@dataclass(frozen=True)
class RankedRoute:
    route: Route
    quote: Decimal
    expected_cost: Decimal


def filter_candidates(routes: list[Route], req: VideoSpec) -> list[Route]:
    """返回同时满足本次请求全部硬条件的路线；不要求路线之间能力相同。

    enabled 与质量组是路由范围约束；时长/分辨率/比例/模式/槽位/总数/报价
    等能力判定统一走 preflight 单一规则源，与提交前防御保持一致。
    """
    result = []
    for r in routes:
        if not r.enabled:
            continue
        # 指定对外模型（质量组）时，只允许同组路线，避免跨模型串档
        if req.quality_group is not None and r.quality_group != req.quality_group:
            continue
        if preflight(req, r):
            continue
        result.append(r)
    return result


def rank_candidates(routes: list[Route], req: VideoSpec,
                    stats: dict[str, RouteStats]) -> list[RankedRoute]:
    """全部合格候选按期望成本升序返回，供故障切换与对冲依次取用。"""
    ranked: list[RankedRoute] = []
    for route in filter_candidates(routes, req):
        quote = route.price_plan().quote(req.resolution, req.duration_seconds)
        if quote is None:
            continue
        route_stats = stats.get(route.route_id)
        if route_stats is not None and route_stats.is_tripped():
            continue
        rate = route_stats.effective_success_rate() if route_stats else 0.95
        quality = (route_stats.effective_quality_rate()
                   if route_stats and route_stats.quality_samples else 1.0)
        effective_rate = max(rate * max(quality, 0.2), 1e-6)
        ranked.append(RankedRoute(
            route=route,
            quote=quote.amount,
            expected_cost=quote.amount / Decimal(str(effective_rate)),
        ))
    ranked.sort(key=lambda item: (
        int(item.route.standby), item.expected_cost, item.route.route_id))
    return ranked


def decide(routes: list[Route], req: VideoSpec,
           stats: dict[str, RouteStats]) -> Route | None:
    """在合格候选中选期望成本最低者；无候选返回 None（能力不支持）。"""
    ranked = rank_candidates(routes, req, stats)
    return ranked[0].route if ranked else None
