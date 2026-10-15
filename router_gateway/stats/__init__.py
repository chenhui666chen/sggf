# -*- coding: utf-8 -*-
"""路线滚动统计：成功率、耗时分位、质量抽检合格率。

样本不足时使用向中性先验收缩的有效成功率，避免少量观测就触发熔断
（见落地文档：至少约 30 个完成样本才完全相信实测失败率）。
"""
from __future__ import annotations

from dataclasses import dataclass

# 有效成功率向该先验收缩；样本越少收缩越强
PRIOR_MEAN = 0.95
PRIOR_STRENGTH = 30
# 熔断门槛：有效失败率超过 20% 才考虑暂停
BREAKER_FAILURE_RATE = 0.20
MIN_SAMPLES_TO_TRUST = 30


@dataclass(frozen=True)
class RouteStats:
    samples: int
    success_rate: float
    p50_seconds: float
    p95_seconds: float
    quality_pass_rate: float = 1.0
    quality_samples: int = 0

    def effective_quality_rate(self) -> float:
        return (self.quality_pass_rate * self.quality_samples + 10) / (self.quality_samples + 10)

    def effective_success_rate(self) -> float:
        """向先验收缩后的成功率，用于期望成本计算。"""
        total = self.samples + PRIOR_STRENGTH
        success = self.success_rate * self.samples + PRIOR_MEAN * PRIOR_STRENGTH
        return success / total

    def is_tripped(self) -> bool:
        if self.samples < MIN_SAMPLES_TO_TRUST:
            return False
        return (1 - self.success_rate) > BREAKER_FAILURE_RATE


@dataclass
class RollingWindow:
    """最近 N 条完成记录的滚动统计，按 路线×档位 维护。"""
    window: int = 100

    def __post_init__(self):
        self._records: dict[str, list[dict]] = {}

    def add(self, route_id: str, bucket: str, success: bool,
            elapsed_seconds: float, quality_pass: bool = True) -> None:
        key = f"{route_id}|{bucket}"
        arr = self._records.setdefault(key, [])
        arr.append({"success": success, "elapsed": elapsed_seconds,
                    "quality": quality_pass})
        if len(arr) > self.window:
            del arr[:-self.window]

    def stats(self, route_id: str, bucket: str = "default") -> RouteStats:
        arr = self._records.get(f"{route_id}|{bucket}", [])
        if not arr:
            return RouteStats(0, PRIOR_MEAN, 0.0, 0.0, 1.0)
        n = len(arr)
        ok = sum(1 for r in arr if r["success"])
        durations = sorted(r["elapsed"] for r in arr if r["success"])
        qn = sum(1 for r in arr if r["quality"])
        p50 = durations[len(durations) // 2] if durations else 0.0
        p95 = durations[min(len(durations) - 1, int(round(n * 0.95)) - 1)] if durations else 0.0
        return RouteStats(n, ok / n, p50, p95, qn / n)
