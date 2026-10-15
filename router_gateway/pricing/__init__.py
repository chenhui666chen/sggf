# -*- coding: utf-8 -*-
"""路线报价模型：按秒与按条两种计费方式。

所有金额使用 Decimal，避免 0.42×29 这类浮点误差影响路由决策。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class PriceQuote:
    amount: Decimal
    billing: str  # per_second / per_use


class PerSecond:
    """按秒计费：费用 = 该分辨率费率 × 请求时长（不是成片实长）。"""

    billing = "per_second"

    def __init__(self, resolution_rates: dict[str, Decimal]):
        self.resolution_rates = {
            k.lower(): Decimal(v) for k, v in resolution_rates.items()}

    def quote(self, resolution: str, duration_seconds: int) -> Optional[PriceQuote]:
        rate = self.resolution_rates.get(resolution.lower())
        if rate is None:
            return None
        return PriceQuote(amount=(rate * Decimal(duration_seconds)).quantize(Decimal("0.01")),
                          billing=self.billing)


class PerUse:
    """按条计费：同一路线在支持时长范围内费用与时长无关。"""

    billing = "per_use"

    def __init__(self, amount: Decimal):
        self.amount = Decimal(amount)

    def quote(self, resolution: str, duration_seconds: int) -> PriceQuote:
        return PriceQuote(amount=self.amount, billing=self.billing)
