"""Seed Audio V2 阶段 0 时间轴契约验证基础设施。

本包只承载阶段 0 基线冻结与时间轴四合同验证所需的确定性定义与指标计算，
不包含任何生产链路调用；真实供应商实测由 scripts/validate_seed_audio_timeline.py 驱动。
"""

from .baseline_scenarios import (
    BASELINE_CATALOG_ID,
    BASELINE_CATALOG_VERSION,
    build_baseline_catalog,
    catalog_canonical_hash,
    get_baseline_scenario,
)
from .metrics import (
    ELIGIBILITY_POLICY_VERSION,
    EligibilityThresholds,
    RunMetrics,
    SubtitleEvent,
    aggregate_run_metrics,
    align_speech_events,
    compute_run_metrics,
    decide_timeline_eligibility,
    extract_subtitle_events,
    percentile,
    summarize,
)

__all__ = [
    "BASELINE_CATALOG_ID",
    "BASELINE_CATALOG_VERSION",
    "ELIGIBILITY_POLICY_VERSION",
    "EligibilityThresholds",
    "RunMetrics",
    "SubtitleEvent",
    "aggregate_run_metrics",
    "align_speech_events",
    "build_baseline_catalog",
    "catalog_canonical_hash",
    "compute_run_metrics",
    "decide_timeline_eligibility",
    "extract_subtitle_events",
    "get_baseline_scenario",
    "percentile",
    "summarize",
]
