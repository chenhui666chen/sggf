"""
进化调度编排：信号采集 + tick 编排（设计文档 §11 · §14 第 10 步 · 子块 B）

把子块 A 的纯逻辑（evolution_scheduler）接入真实数据源：
- compute_recent_improvements：从进化历史摘要算某题材跨批次最佳提升序列（§11.1 边际枯竭）；
- is_genre_converged：从进化历史摘要判某题材最新完成批次是否达标（§11.1 达标口径）；
- compute_champion_fidelity_drop：从 champion 异步复评滚动窗口算保真下降幅度（§11.2 唤醒）；
- compute_champion_ai_score_rise：从 champion 原始 AI 检测分滚动窗口算 AI 率回升幅度（§11.2 唤醒）；
- compute_best_challenger_wilson_lower_bound：从 returnable 挑战者结算序列取最大 Wilson
  下界（§11.2 挑战者反超信号）；
- run_scheduler_tick：逐题材装配信号 → decide_next_state → 状态变化落盘、否则 touch。

编排层与外部依赖注入分离（SchedulerTickDeps）：现已接入真实源的信号（预算、跨批次
提升、综合分达标、冠军保真下降、冠军在线 AI 率回升、挑战者反超、环境变更〔入眠指纹快照
对比〕）在本层直接采集；holdout 分差与哨兵巡检退化经 deps 注入（任务层装配为分别读
holdout_probe / sentinel_probe 低频缓存），至此全部启停信号均已接入数据源。本层
不接 Celery、不调外部 API；真实供应商装配在 tasks/experiment_tasks.py 薄壳。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List

from sqlalchemy.orm import Session

from .challenger_repository import ChallengerRepository
from .evolution_scheduler import (
    STATE_SLEEPING,
    SchedulerThresholds,
    SleepSignals,
    WakeSignals,
    decide_next_state,
)
from .experiment_contract import ServingMode
from .experiment_repository import ExperimentRepository
from .promotion import DEFAULT_WILSON_Z, aggregate_challenger_stats

# 冠军保真滚动窗口样本数（结构参数，非质量阈值）：近窗与基线窗各取此数，
# 有效样本不足 2*window 时证据不足不触发唤醒（§11.2 champion_fidelity_drop）。
DEFAULT_FIDELITY_WINDOW = 10


def is_genre_converged(summaries: List[dict], genre: str) -> bool:
    """
    综合分达标判定（§11.1 达标口径，信号 1 接真实源）。

    综合分越低越好。仅看该题材 completed 且 best_score / target_score 均非空的批次，
    按 started_at 升序取最新一批，best_score ≤ target_score 即达标。无合格批次返回
    False（无证据不敢停）。
    """
    scored = [
        s
        for s in summaries
        if s.get("genre") == genre
        and s.get("status") == "completed"
        and s.get("best_score") is not None
        and s.get("target_score") is not None
    ]
    if not scored:
        return False
    scored.sort(key=lambda s: s.get("started_at") or "")
    latest = scored[-1]
    return latest["best_score"] <= latest["target_score"]


def compute_champion_fidelity_drop(
    db: Session,
    genre: str,
    *,
    policy: str,
    window: int = DEFAULT_FIDELITY_WINDOW,
) -> float:
    """
    冠军保真下降幅度（§11.2 champion_fidelity_drop 唤醒信号，信号 3b 接真实源）。

    从该题材已结算实验的 champion 异步复评序列（按 finished_at 升序）取保真度量
    = mean(semantic_fidelity.score, fact_consistency.score)（均 0-100 越高越好）。以最近
    window 个为近窗、其前 window 个为基线窗，返回 baseline_avg - recent_avg（正=保真
    下降）。仅统计 champion 可用且两分齐备的样本；有效样本 < 2*window 时证据不足返回
    0.0（不触发唤醒）。
    """
    exp_repo = ExperimentRepository(db)
    metrics: List[float] = []
    for _finished_at, review in exp_repo.list_champion_reviews(genre, policy):
        champion = (review or {}).get("champion") or {}
        if not champion.get("available"):
            continue
        fidelity = champion.get("semantic_fidelity") or {}
        fact = champion.get("fact_consistency") or {}
        if "score" not in fidelity or "score" not in fact:
            continue
        metrics.append((float(fidelity["score"]) + float(fact["score"])) / 2.0)

    if len(metrics) < 2 * window:
        return 0.0
    baseline = metrics[-2 * window : -window]
    recent = metrics[-window:]
    baseline_avg = sum(baseline) / len(baseline)
    recent_avg = sum(recent) / len(recent)
    return baseline_avg - recent_avg


def compute_champion_ai_score_rise(
    db: Session,
    genre: str,
    *,
    policy: str,
    window: int = DEFAULT_FIDELITY_WINDOW,
) -> float:
    """
    冠军在线 AI 率回升幅度（§11.2 champion_ai_score_rise 唤醒信号 3a 接真实源）。

    从该题材已结算实验的 champion 原始 AI 检测分序列（按 finished_at 升序，落库前
    历史行为空自动排除）取值（0-100 越高越差）。以最近 window 个为近窗、其前 window
    个为基线窗，返回 recent_avg - baseline_avg（正=AI 率回升=在线退化）。有效样本
    < 2*window 时证据不足返回 0.0（不触发唤醒）。
    """
    exp_repo = ExperimentRepository(db)
    scores = [
        float(score)
        for _finished_at, score in exp_repo.list_champion_ai_scores(genre, policy)
        if score is not None
    ]
    if len(scores) < 2 * window:
        return 0.0
    baseline = scores[-2 * window : -window]
    recent = scores[-window:]
    baseline_avg = sum(baseline) / len(baseline)
    recent_avg = sum(recent) / len(recent)
    return recent_avg - baseline_avg


def compute_recent_improvements(
    summaries: List[dict],
    genre: str,
    *,
    limit: int,
) -> List[float]:
    """
    从进化历史摘要（storage.list_evolution_histories 输出）算某题材跨批次最佳提升序列。

    综合分越低越好，相邻批次提升 = 前批 best_score - 后批 best_score（正=提升）。
    仅取该题材 completed 且 best_score 非空的批次，按 started_at 升序；返回最近 limit 个。
    批次不足 2 时无法算提升，返回 []。
    """
    scored = [
        s
        for s in summaries
        if s.get("genre") == genre
        and s.get("status") == "completed"
        and s.get("best_score") is not None
    ]
    scored.sort(key=lambda s: s.get("started_at") or "")
    improvements = [
        scored[i - 1]["best_score"] - scored[i]["best_score"]
        for i in range(1, len(scored))
    ]
    return improvements[-limit:] if limit > 0 else improvements


def compute_best_challenger_wilson_lower_bound(
    db: Session,
    genre: str,
    *,
    policy: str,
    z: float = DEFAULT_WILSON_Z,
) -> float:
    """
    某题材 returnable 挑战者中最大的 confirmed 胜率 Wilson 下界（§11.2 反超信号）。

    遍历该题材 returnable 挑战者本策略版本窗口的已结算 verdict 序列，逐个聚合统计，
    取最大 Wilson 下界。无 returnable 挑战者返回 0.0（无证据不触发唤醒）。
    """
    chal_repo = ChallengerRepository(db)
    exp_repo = ExperimentRepository(db)
    challengers = chal_repo.list_serving(genre, ServingMode.RETURNABLE.value)

    best = 0.0
    for challenger in challengers:
        verdicts = exp_repo.list_outcomes_for_challenger(challenger.challenger_id, policy)
        stats = aggregate_challenger_stats(verdicts, z=z)
        if stats.wilson_lower_bound > best:
            best = stats.wilson_lower_bound
    return best


@dataclass(frozen=True)
class SchedulerTickDeps:
    """
    tick 编排的外部依赖（可注入，便于测试替换）。

    - list_history_summaries：全量进化历史摘要来源（storage.list_evolution_histories）；
    - is_budget_exhausted：按题材查预算是否触顶（BudgetLedger.is_exhausted 包装）。
    - env_fingerprint：按题材取当前环境版本指纹 dict（§11.2 environment_changed 信号 4）；
      sleeping 期与入眠时快照对比，不一致即环境变更唤醒。默认空 dict（无指纹不误触发）。
    - holdout_score_gap：冠军训练/留出新鲜复评分差（§11.1 信号 2）；任务层装配为读
      holdout_probe 低频缓存，无缓存/policy 不一致降级 0.0 中性。默认 0.0（不阻止入眠）。
    - sentinel_degraded：哨兵巡检退化（§11.2 信号 5）；任务层装配为读 sentinel_probe
      低频缓存，无缓存/policy 不一致降级 False。默认 False（不误唤醒）。
    注：综合分达标（converged）、冠军保真下降（champion_fidelity_drop）、冠军在线 AI 率
    回升（champion_ai_score_rise）已接真实源，在 run_scheduler_tick 内经 is_genre_converged
    / compute_champion_fidelity_drop / compute_champion_ai_score_rise 直接采集。
    """
    list_history_summaries: Callable[[], List[dict]]
    is_budget_exhausted: Callable[[str], bool]
    env_fingerprint: Callable[[str], dict] = field(default=lambda genre: {})
    holdout_score_gap: Callable[[str], float] = field(default=lambda genre: 0.0)
    sentinel_degraded: Callable[[str], bool] = field(default=lambda genre: False)


def run_scheduler_tick(
    db: Session,
    genres: List[str],
    *,
    deps: SchedulerTickDeps,
    state_store,
    policy: str,
    thresholds: SchedulerThresholds = None,
    now: str,
    fidelity_window: int = DEFAULT_FIDELITY_WINDOW,
) -> Dict[str, dict]:
    """
    逐题材执行一次调度 tick：装配信号 → decide_next_state → 状态变化落盘、否则仅 touch。

    返回每题材 {from, to, changed, reasons}，供 beat 日志与管理面板消费。
    """
    thresholds = thresholds or SchedulerThresholds()
    summaries = deps.list_history_summaries()
    result: Dict[str, dict] = {}

    for genre in genres:
        record = state_store.get(genre)
        current_state = record.state

        # 环境变更（§11.2 信号 4）：仅 sleeping 且有入眠快照时，当前指纹与快照不一致即唤醒。
        current_fingerprint = deps.env_fingerprint(genre)
        environment_changed = (
            current_state == STATE_SLEEPING
            and bool(record.env_snapshot)
            and current_fingerprint != record.env_snapshot
        )

        sleep_signals = SleepSignals(
            converged=is_genre_converged(summaries, genre),
            recent_improvements=compute_recent_improvements(
                summaries, genre, limit=thresholds.convergence_batches
            ),
            holdout_score_gap=deps.holdout_score_gap(genre),
            budget_exhausted=deps.is_budget_exhausted(genre),
        )
        wake_signals = WakeSignals(
            champion_ai_score_rise=compute_champion_ai_score_rise(
                db, genre, policy=policy, window=fidelity_window
            ),
            champion_fidelity_drop=compute_champion_fidelity_drop(
                db, genre, policy=policy, window=fidelity_window
            ),
            best_challenger_wilson_lower_bound=compute_best_challenger_wilson_lower_bound(
                db, genre, policy=policy
            ),
            environment_changed=environment_changed,
            sentinel_degraded=deps.sentinel_degraded(genre),
        )

        decision = decide_next_state(
            current_state,
            sleep_signals=sleep_signals,
            wake_signals=wake_signals,
            thresholds=thresholds,
        )

        if decision.changed:
            # 转入 sleeping 时抓拍当前环境指纹为唤醒基准；其余转移不带快照（保留既有）。
            env_snapshot = (
                current_fingerprint if decision.next_state == STATE_SLEEPING else None
            )
            state_store.set(
                genre, decision.next_state, reasons=decision.reasons,
                now=now, env_snapshot=env_snapshot,
            )
        else:
            state_store.touch(genre, now=now)

        result[genre] = {
            "from": current_state,
            "to": decision.next_state,
            "changed": decision.changed,
            "reasons": decision.reasons,
        }

    return result
