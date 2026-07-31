"""
离线回放一致率校准（设计文档 §3.4 第 1 层 / §14 第 5 步）

用进化历史三元组（original / rewritten / llm_review）回放，统计同步判定器与
异步权威评审的一致率、作废率，预热第 1 层"全局判定器基础校准"。

数据限制说明：磁盘进化历史 `PromptVersion.to_dict` 将原文 / 改写文截断为 100 字符，
故回放的同步门槛以**分数类口径**（AI 检测阈值、内容安全，不受截断影响）为准，
全文结构类硬门槛（长度收缩、数字丢失、段落破坏）在离线回放阶段不参与判定，
待 shadow 上线（§14 步骤 6）拿到完整全文样本后再纳入逐层校准（§14 步骤 7）。

verdict 归类复用 review_verdict.classify_verdict，避免逻辑重复。
"""
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence

from .review_verdict import (
    ALL_VERDICTS,
    VERDICT_CONFIRMED_WIN,
    VERDICT_INFRASTRUCTURE_FAILURE,
    VERDICT_INVALIDATED_WIN,
    async_review_hard_fail,
    classify_verdict,
)

# 第 1 层校准门槛（§3.4，配置项默认值）
DEFAULT_MIN_SAMPLES = 200
DEFAULT_MAX_INVALIDATION_RATE = 0.05


@dataclass(frozen=True)
class ReplayConsistencyReport:
    total: int
    effective_total: int          # 排除 infrastructure_failure 的有效样本
    verdict_counts: Dict[str, int]
    sync_win_count: int           # confirmed_win + invalidated_win（同步判胜场次）
    confirmed_win_count: int
    invalidated_win_count: int
    invalidation_rate: float      # invalidated / sync_win（判定器误判率 = 作废率）
    consistency_rate: float       # confirmed / sync_win（同步判胜且异步确认的比例）


def compute_replay_consistency(verdicts: Sequence[str]) -> ReplayConsistencyReport:
    """聚合一批回放 verdict，得出一致率 / 作废率报告。"""
    counts: Dict[str, int] = {v: 0 for v in ALL_VERDICTS}
    for verdict in verdicts:
        counts[verdict] = counts.get(verdict, 0) + 1

    total = len(verdicts)
    infra = counts.get(VERDICT_INFRASTRUCTURE_FAILURE, 0)
    effective_total = total - infra

    confirmed = counts.get(VERDICT_CONFIRMED_WIN, 0)
    invalidated = counts.get(VERDICT_INVALIDATED_WIN, 0)
    sync_win = confirmed + invalidated

    invalidation_rate = invalidated / sync_win if sync_win > 0 else 0.0
    consistency_rate = confirmed / sync_win if sync_win > 0 else 0.0

    return ReplayConsistencyReport(
        total=total,
        effective_total=effective_total,
        verdict_counts=counts,
        sync_win_count=sync_win,
        confirmed_win_count=confirmed,
        invalidated_win_count=invalidated,
        invalidation_rate=invalidation_rate,
        consistency_rate=consistency_rate,
    )


def calibration_layer1_passed(
    report: ReplayConsistencyReport,
    *,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    max_invalidation_rate: float = DEFAULT_MAX_INVALIDATION_RATE,
) -> bool:
    """第 1 层校准是否达标：有效样本充足 且 作废率不越限。"""
    return (
        report.effective_total >= min_samples
        and report.invalidation_rate <= max_invalidation_rate
    )


def _sync_gate_passes(rewritten_ai_score: Optional[float], ai_threshold: float) -> bool:
    """回放同步门槛（分数类口径）：AI 检测分不高于阈值即放行。缺失分数保守判不放行。"""
    if rewritten_ai_score is None:
        return False
    return float(rewritten_ai_score) <= float(ai_threshold)


def replay_history_record(record: Mapping) -> str:
    """
    单条历史记录 → verdict。record 期望字段：
      rewritten_ai_score / ai_threshold / detector_available / llm_review(dict)
    """
    llm_review = record.get("llm_review") or {}
    detector_available = bool(record.get("detector_available", True))
    review_available = bool(llm_review.get("available", False))

    sync_pass = _sync_gate_passes(
        record.get("rewritten_ai_score"), record.get("ai_threshold", 50.0)
    )
    async_confirms = not async_review_hard_fail(llm_review)

    return classify_verdict(
        returned_challenger=sync_pass,
        infra_ok=detector_available and review_available,
        challenger_hard_fail=False,
        async_reviewed=True,
        async_confirms_win=async_confirms,
    )


def replay_history_records(records: Sequence[Mapping]) -> List[str]:
    """批量回放，返回 verdict 列表。"""
    return [replay_history_record(record) for record in records]
