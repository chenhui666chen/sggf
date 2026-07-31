"""
晋升统计 + 硬闸门/推荐指标评估（设计文档 §7.1 / §8.1 / §8.2 · §14 第 9 步 · 子块 A）

回答「这个提示词长期更好吗」（§3.3 决策二）。纯逻辑：把某挑战者一批已结算
verdict 聚合为统计口径，再按硬闸门（不可绕过）与推荐指标（管理员权衡）评估。

口径（§7.1）：
- 晋升只用 confirmed_win 做分子；胜负分母 decisive_total = confirmed_win + loss；
- invalidated_win 不计胜负，仅入作废率（判定器误判监控）；
- infrastructure_failure 不计质量账，不进有效样本、不进任何分母（§5.5）；
- 有效样本 effective_total = confirmed + loss + invalidated + hard_failure（排除 infra/provisional）。

作废率与有效样本口径与 replay_calibration.compute_replay_consistency 保持一致（DRY）。
本模块只做纯统计与评估，不触 DB、不接外部 API；原子切换/回滚编排属子块 B。
"""
import math
import os
from dataclasses import dataclass, field
from typing import List, Sequence

from .replay_calibration import compute_replay_consistency
from .review_verdict import (
    VERDICT_CONFIRMED_WIN,
    VERDICT_HARD_FAILURE,
    VERDICT_LOSS,
)

# 硬闸门默认值（§8.1，配置项）
DEFAULT_MIN_EFFECTIVE_SAMPLES = 100
DEFAULT_MAX_HARD_FAIL_RATE = 0.01
# 推荐指标默认值（§8.2，配置项）
DEFAULT_MIN_WIN_RATE = 0.60
DEFAULT_MIN_WILSON_LOWER_BOUND = 0.50
DEFAULT_MAX_INVALIDATION_RATE = 0.05
DEFAULT_WILSON_Z = 1.96  # 95% 置信；小流量期可放宽至 90%（1.645）


def wilson_lower_bound(successes: int, total: int, z: float = DEFAULT_WILSON_Z) -> float:
    """
    Wilson score 置信区间下界（§8.2）。total=0 返回 0.0（无证据不放行）。
    z=1.96 → 95%；z=1.645 → 90%。
    """
    if total <= 0:
        return 0.0
    p = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = p + z2 / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total))
    return (center - margin) / denom


@dataclass(frozen=True)
class ChallengerStats:
    total: int                    # 全部样本（含 infra）
    effective_total: int          # 排除 infra 的有效样本（§8.1 #1 口径）
    confirmed_win: int
    loss: int
    invalidated_win: int
    hard_failure: int
    infrastructure_failure: int
    decisive_total: int           # confirmed + loss（胜负分母）
    win_rate: float               # confirmed / decisive_total
    invalidation_rate: float      # invalidated / (confirmed + invalidated)
    hard_fail_rate: float         # hard_failure / effective_total
    wilson_lower_bound: float     # confirmed / decisive_total 的 Wilson 下界


def aggregate_challenger_stats(
    verdicts: Sequence[str],
    *,
    z: float = DEFAULT_WILSON_Z,
) -> ChallengerStats:
    """把某挑战者一批已结算 verdict 聚合为晋升统计口径。"""
    report = compute_replay_consistency(verdicts)
    counts = report.verdict_counts

    confirmed = counts.get(VERDICT_CONFIRMED_WIN, 0)
    loss = counts.get(VERDICT_LOSS, 0)
    invalidated = report.invalidated_win_count
    hard = counts.get(VERDICT_HARD_FAILURE, 0)
    infra = report.total - report.effective_total  # 复用 compute 口径

    decisive_total = confirmed + loss
    win_rate = confirmed / decisive_total if decisive_total > 0 else 0.0
    hard_fail_rate = hard / report.effective_total if report.effective_total > 0 else 0.0

    return ChallengerStats(
        total=report.total,
        effective_total=report.effective_total,
        confirmed_win=confirmed,
        loss=loss,
        invalidated_win=invalidated,
        hard_failure=hard,
        infrastructure_failure=infra,
        decisive_total=decisive_total,
        win_rate=win_rate,
        invalidation_rate=report.invalidation_rate,
        hard_fail_rate=hard_fail_rate,
        wilson_lower_bound=wilson_lower_bound(confirmed, decisive_total, z=z),
    )


@dataclass(frozen=True)
class PromotionThresholds:
    # 硬闸门（§8.1）
    min_effective_samples: int = DEFAULT_MIN_EFFECTIVE_SAMPLES
    max_hard_fail_rate: float = DEFAULT_MAX_HARD_FAIL_RATE
    # 推荐指标（§8.2）
    min_win_rate: float = DEFAULT_MIN_WIN_RATE
    min_wilson_lower_bound: float = DEFAULT_MIN_WILSON_LOWER_BOUND
    max_invalidation_rate: float = DEFAULT_MAX_INVALIDATION_RATE
    wilson_z: float = DEFAULT_WILSON_Z

    @classmethod
    def from_env(cls) -> "PromotionThresholds":
        return cls(
            min_effective_samples=int(
                os.getenv("PROMOTION_MIN_EFFECTIVE_SAMPLES", str(DEFAULT_MIN_EFFECTIVE_SAMPLES))
            ),
            max_hard_fail_rate=float(
                os.getenv("PROMOTION_MAX_HARD_FAIL_RATE", str(DEFAULT_MAX_HARD_FAIL_RATE))
            ),
            min_win_rate=float(os.getenv("PROMOTION_MIN_WIN_RATE", str(DEFAULT_MIN_WIN_RATE))),
            min_wilson_lower_bound=float(
                os.getenv("PROMOTION_MIN_WILSON_LOWER_BOUND", str(DEFAULT_MIN_WILSON_LOWER_BOUND))
            ),
            max_invalidation_rate=float(
                os.getenv("PROMOTION_MAX_INVALIDATION_RATE", str(DEFAULT_MAX_INVALIDATION_RATE))
            ),
            wilson_z=float(os.getenv("PROMOTION_WILSON_Z", str(DEFAULT_WILSON_Z))),
        )


@dataclass(frozen=True)
class PromotionGateResult:
    hard_gate_passed: bool
    hard_gate_failures: List[str] = field(default_factory=list)
    recommended: bool = False
    recommend_failures: List[str] = field(default_factory=list)


def evaluate_promotion_gate(
    stats: ChallengerStats,
    *,
    offline_gate_passed: bool,
    policy_version_consistent: bool = True,
    has_unresolved_safety_incident: bool = False,
    thresholds: PromotionThresholds = None,
) -> PromotionGateResult:
    """
    评估某挑战者是否达晋升门槛。

    硬闸门（§8.1，全部满足才 hard_gate_passed）：
      1. 有效样本 ≥ 阈值；2. 离线安全准入通过；3. 硬失败率 ≤ 上限；
      4. 评审策略版本一致（数据源保证，此处显式断言）；5. 无未处理安全事件。
    推荐指标（§8.2，硬闸门通过 且 全部满足才 recommended）：
      有效胜率 ≥ 下限；Wilson 下界 > 下限；作废率 ≤ 上限。
      P95 延迟 / 单请求成本 / 题材覆盖第一版为 informational，不阻断。
    """
    thresholds = thresholds or PromotionThresholds()

    hard_failures: List[str] = []
    if stats.effective_total < thresholds.min_effective_samples:
        hard_failures.append("min_effective_samples")
    if not offline_gate_passed:
        hard_failures.append("offline_gate")
    if stats.hard_fail_rate > thresholds.max_hard_fail_rate:
        hard_failures.append("hard_fail_rate")
    if not policy_version_consistent:
        hard_failures.append("policy_version_consistent")
    if has_unresolved_safety_incident:
        hard_failures.append("safety_incident")
    hard_gate_passed = not hard_failures

    recommend_failures: List[str] = []
    if stats.win_rate < thresholds.min_win_rate:
        recommend_failures.append("win_rate")
    if stats.wilson_lower_bound <= thresholds.min_wilson_lower_bound:
        recommend_failures.append("wilson_lower_bound")
    if stats.invalidation_rate > thresholds.max_invalidation_rate:
        recommend_failures.append("invalidation_rate")
    recommended = hard_gate_passed and not recommend_failures

    return PromotionGateResult(
        hard_gate_passed=hard_gate_passed,
        hard_gate_failures=hard_failures,
        recommended=recommended,
        recommend_failures=recommend_failures,
    )
