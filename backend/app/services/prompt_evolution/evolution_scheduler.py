"""
进化自动启停调度纯逻辑（设计文档 §11 · §14 第 10 步 · 子块 A）

回答「进化该继续、休眠、还是被唤醒」（§11）。纯逻辑：把外部采集的信号
聚合为休眠/唤醒判定，再按三态转移（含 §11.3 滞回）给出下一状态决策。

三态（§11 首段）：
- running   运行中：离线持续生成新变体、成对实验监控、best-of-2 择优；
- sleeping  休眠：只停「离线生成新变体」，成对实验监控与择优照常（休眠≠失明/停择优）；
- awake     被唤醒：休眠期命中唤醒信号后的过渡态，消费一次即重启进化转回 running。

风险不对称（§11.2）：唤醒门槛比休眠门槛更重要——休眠是 AND 组合（多条件同时
满足才敢停），唤醒是 OR 组合（任一退化/反超信号即恢复）。滞回（§11.3）：休眠开、
唤醒关阈值分离，缓冲带防抖动；running 态不判唤醒、sleeping 态不判休眠，天然隔离。

本模块只做纯判定与状态转移，不触 DB、不接 Celery、不接外部 API；信号采集、
状态落盘、beat 编排属子块 B，管理面板属子块 C。
"""
import os
from dataclasses import dataclass, field
from typing import List

# 三态（§11）
STATE_RUNNING = "running"
STATE_SLEEPING = "sleeping"
STATE_AWAKE = "awake"

# 休眠门槛默认值（§11.1，配置项）
DEFAULT_CONVERGENCE_BATCHES = 3          # 连续 N 批次考察边际收益
DEFAULT_MIN_BATCH_IMPROVEMENT = 2.0      # 每批最佳提升 < 此值视为枯竭
DEFAULT_MAX_HOLDOUT_SCORE_GAP = 5.0      # holdout 复评分差 > 此值视为过拟合假象
# 唤醒门槛默认值（§11.2 / §11.3 滞回，配置项）
DEFAULT_WAKE_AI_SCORE_RISE = 8.0         # 冠军 AI 率回升 > 此值即退化
DEFAULT_WAKE_FIDELITY_DROP = 5.0         # 冠军保真/事实分下降 > 此值即退化
DEFAULT_WAKE_CHALLENGER_WILSON = 0.55    # 某挑战者 Wilson 下界 > 此值视为反超


@dataclass(frozen=True)
class SchedulerThresholds:
    # 休眠门槛（§11.1）
    convergence_batches: int = DEFAULT_CONVERGENCE_BATCHES
    min_batch_improvement: float = DEFAULT_MIN_BATCH_IMPROVEMENT
    max_holdout_score_gap: float = DEFAULT_MAX_HOLDOUT_SCORE_GAP
    # 唤醒门槛（§11.2 / §11.3 滞回，与休眠阈值分离）
    wake_ai_score_rise: float = DEFAULT_WAKE_AI_SCORE_RISE
    wake_fidelity_drop: float = DEFAULT_WAKE_FIDELITY_DROP
    wake_challenger_wilson_lower_bound: float = DEFAULT_WAKE_CHALLENGER_WILSON

    @classmethod
    def from_env(cls) -> "SchedulerThresholds":
        return cls(
            convergence_batches=int(
                os.getenv("EVOLUTION_CONVERGENCE_BATCHES", str(DEFAULT_CONVERGENCE_BATCHES))
            ),
            min_batch_improvement=float(
                os.getenv("EVOLUTION_MIN_BATCH_IMPROVEMENT", str(DEFAULT_MIN_BATCH_IMPROVEMENT))
            ),
            max_holdout_score_gap=float(
                os.getenv("EVOLUTION_MAX_HOLDOUT_SCORE_GAP", str(DEFAULT_MAX_HOLDOUT_SCORE_GAP))
            ),
            wake_ai_score_rise=float(
                os.getenv("EVOLUTION_WAKE_AI_SCORE_RISE", str(DEFAULT_WAKE_AI_SCORE_RISE))
            ),
            wake_fidelity_drop=float(
                os.getenv("EVOLUTION_WAKE_FIDELITY_DROP", str(DEFAULT_WAKE_FIDELITY_DROP))
            ),
            wake_challenger_wilson_lower_bound=float(
                os.getenv("EVOLUTION_WAKE_CHALLENGER_WILSON", str(DEFAULT_WAKE_CHALLENGER_WILSON))
            ),
        )


@dataclass(frozen=True)
class SleepSignals:
    """休眠信号快照（§11.1，由子块 B 采集）。"""
    converged: bool                       # 综合分达标（区别于单次运行内 stop conditions）
    recent_improvements: List[float]      # 最近批次最佳提升序列（相邻批 best_score 差，跨批次层）
    holdout_score_gap: float              # 新鲜样本复评冠军与样本池分差（防过拟合）
    budget_exhausted: bool                # 周期进化费用达上限


@dataclass(frozen=True)
class WakeSignals:
    """唤醒信号快照（§11.2，由子块 B 采集）。"""
    champion_ai_score_rise: float             # 滚动窗口 AI 率均值回升幅度
    champion_fidelity_drop: float             # 异步评审保真/事实分下降幅度
    best_challenger_wilson_lower_bound: float # 最强挑战者 confirmed 胜率 Wilson 下界
    environment_changed: bool                 # 环境变更事件（模型切换/检测版本变化/新题材/主链改）
    sentinel_degraded: bool                   # 哨兵巡检发现冠军退化


@dataclass(frozen=True)
class SleepDecision:
    should_sleep: bool
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class WakeDecision:
    should_wake: bool
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class StateDecision:
    next_state: str
    changed: bool
    reasons: List[str] = field(default_factory=list)


def evaluate_sleep_gate(
    signals: SleepSignals,
    *,
    thresholds: SchedulerThresholds = None,
) -> SleepDecision:
    """
    评估是否应休眠（§11.1）。两条独立触发路径（OR）：

    A. 预算触顶：周期进化费用达上限，强制休眠（无视达标与否）；
    B. 达标 + 边际收益枯竭 + 新鲜样本验证（三者 AND）：
       - converged（综合分达标）；
       - 最近连续 convergence_batches 批最佳提升均 < min_batch_improvement（边际枯竭）；
       - holdout_score_gap ≤ 上限（分差过大说明过拟合假象，阻止带水分入眠）。
    """
    thresholds = thresholds or SchedulerThresholds()
    reasons: List[str] = []

    if signals.budget_exhausted:
        reasons.append("budget_exhausted")

    marginal_exhausted = _is_marginal_gain_exhausted(signals, thresholds)
    holdout_ok = signals.holdout_score_gap <= thresholds.max_holdout_score_gap
    if signals.converged and marginal_exhausted and holdout_ok:
        reasons.append("marginal_gain_exhausted")

    return SleepDecision(should_sleep=bool(reasons), reasons=reasons)


def _is_marginal_gain_exhausted(
    signals: SleepSignals,
    thresholds: SchedulerThresholds,
) -> bool:
    """连续 convergence_batches 批最佳提升均 < 阈值才算枯竭；批次不足则不判定。"""
    n = thresholds.convergence_batches
    if len(signals.recent_improvements) < n:
        return False
    recent = signals.recent_improvements[-n:]
    return all(imp < thresholds.min_batch_improvement for imp in recent)


def evaluate_wake_gate(
    signals: WakeSignals,
    *,
    thresholds: SchedulerThresholds = None,
) -> WakeDecision:
    """
    评估是否应唤醒（§11.2 风险不对称，OR 组合——任一信号即唤醒）：
      - champion_ai_degraded：冠军 AI 率回升 > 阈值（在线退化，成本零）；
      - champion_fidelity_drop：冠军保真/事实分下降 > 阈值（在线退化，成本零）；
      - challenger_overtook：某挑战者 Wilson 下界 > 阈值（反超，休眠判断错了，成本零）；
      - environment_changed：环境变更事件（事件驱动）；
      - sentinel_degraded：哨兵巡检发现退化（低成本兜底）。
    唤醒阈值与休眠阈值分离，形成 §11.3 滞回缓冲带防抖动。
    """
    thresholds = thresholds or SchedulerThresholds()
    reasons: List[str] = []

    if signals.champion_ai_score_rise > thresholds.wake_ai_score_rise:
        reasons.append("champion_ai_degraded")
    if signals.champion_fidelity_drop > thresholds.wake_fidelity_drop:
        reasons.append("champion_fidelity_drop")
    if signals.best_challenger_wilson_lower_bound > thresholds.wake_challenger_wilson_lower_bound:
        reasons.append("challenger_overtook")
    if signals.environment_changed:
        reasons.append("environment_changed")
    if signals.sentinel_degraded:
        reasons.append("sentinel_degraded")

    return WakeDecision(should_wake=bool(reasons), reasons=reasons)


def decide_next_state(
    current_state: str,
    *,
    sleep_signals: SleepSignals,
    wake_signals: WakeSignals,
    thresholds: SchedulerThresholds = None,
) -> StateDecision:
    """
    三态转移决策（§11.3 滞回：按当前态只判一侧门槛，天然隔离防抖动）：
      - running：只判休眠门槛，命中 → sleeping，否则保持；
      - sleeping：只判唤醒门槛，命中 → awake，否则保持；
      - awake：过渡态，消费一次即重启定向进化 → running。
    """
    thresholds = thresholds or SchedulerThresholds()

    if current_state == STATE_SLEEPING:
        wake = evaluate_wake_gate(wake_signals, thresholds=thresholds)
        if wake.should_wake:
            return StateDecision(next_state=STATE_AWAKE, changed=True, reasons=wake.reasons)
        return StateDecision(next_state=STATE_SLEEPING, changed=False)

    if current_state == STATE_AWAKE:
        return StateDecision(next_state=STATE_RUNNING, changed=True)

    # STATE_RUNNING（默认）
    sleep = evaluate_sleep_gate(sleep_signals, thresholds=thresholds)
    if sleep.should_sleep:
        return StateDecision(next_state=STATE_SLEEPING, changed=True, reasons=sleep.reasons)
    return StateDecision(next_state=STATE_RUNNING, changed=False)
