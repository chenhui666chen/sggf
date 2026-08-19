"""阶段 0 时间轴遵循精度指标与 eligible 判定。

所有函数均为纯函数、确定性输出，可被单元测试完整覆盖；
真实响应的解析入口是供应商字幕（``subtitle.sentences[]``，毫秒级）。

判定阈值本身是版本化合同（``ELIGIBILITY_POLICY_VERSION``）：
阶段 0 结论必须带着阈值版本一起记录；阈值调整属于决策变更，
必须在进度文档按 DEC 模板登记后提升版本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

ELIGIBILITY_POLICY_VERSION = "1.0.0"

# 单位：毫秒。阈值为阶段 0 首版判定合同，实测后可按决策变更调整。
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "min_runs": 3,
    # strict：全部 speech 事件可对齐的比例下限（每次运行）
    "strict_min_alignment_ratio": 1.0,
    "strict_start_end_p50_ms": 800.0,
    "strict_start_end_p95_ms": 1500.0,
    "strict_duration_p95_ms": 3000.0,
    "strict_event_alignment_p95_ms": 2000.0,
    # bounded：关键窗口容忍度
    "bounded_within_window_ratio": 0.6,
    "bounded_tolerance_ms": 2000.0,
    "bounded_duration_p95_ms": 5000.0,
}


@dataclass(frozen=True)
class EligibilityThresholds:
    min_runs: int = 3
    strict_min_alignment_ratio: float = 1.0
    strict_start_end_p50_ms: float = 800.0
    strict_start_end_p95_ms: float = 1500.0
    strict_duration_p95_ms: float = 3000.0
    strict_event_alignment_p95_ms: float = 2000.0
    bounded_within_window_ratio: float = 0.6
    bounded_tolerance_ms: float = 2000.0
    bounded_duration_p95_ms: float = 5000.0

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "EligibilityThresholds":
        merged = {**DEFAULT_THRESHOLDS, **dict(values)}
        return cls(
            min_runs=int(merged["min_runs"]),
            strict_min_alignment_ratio=float(merged["strict_min_alignment_ratio"]),
            strict_start_end_p50_ms=float(merged["strict_start_end_p50_ms"]),
            strict_start_end_p95_ms=float(merged["strict_start_end_p95_ms"]),
            strict_duration_p95_ms=float(merged["strict_duration_p95_ms"]),
            strict_event_alignment_p95_ms=float(merged["strict_event_alignment_p95_ms"]),
            bounded_within_window_ratio=float(merged["bounded_within_window_ratio"]),
            bounded_tolerance_ms=float(merged["bounded_tolerance_ms"]),
            bounded_duration_p95_ms=float(merged["bounded_duration_p95_ms"]),
        )


@dataclass(frozen=True)
class SubtitleEvent:
    """供应商字幕中的一个可观测发声区间（毫秒）。"""

    start_ms: int
    end_ms: int
    text: str


@dataclass
class RunMetrics:
    """单次生成的时间轴遵循指标。"""

    run_id: str
    success: bool
    start_errors_ms: List[float] = field(default_factory=list)
    end_errors_ms: List[float] = field(default_factory=list)
    duration_error_ms: Optional[float] = None
    event_alignment_errors_ms: List[float] = field(default_factory=list)
    alignment_ratio: Optional[float] = None
    within_window_ratio: Optional[float] = None
    unmatched_texts: List[str] = field(default_factory=list)
    observed_duration_ms: Optional[float] = None
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "success": self.success,
            "start_errors_ms": list(self.start_errors_ms),
            "end_errors_ms": list(self.end_errors_ms),
            "duration_error_ms": self.duration_error_ms,
            "event_alignment_errors_ms": list(self.event_alignment_errors_ms),
            "alignment_ratio": self.alignment_ratio,
            "within_window_ratio": self.within_window_ratio,
            "unmatched_texts": list(self.unmatched_texts),
            "observed_duration_ms": self.observed_duration_ms,
            "error": self.error,
        }


def extract_subtitle_events(metadata: Mapping[str, Any] | None) -> List[SubtitleEvent]:
    """从供应商响应 metadata 解析毫秒级字幕事件。

    兼容两种结构：``{"subtitles": {"sentences": [...]}}`` 与
    ``{"subtitles": [...]}``；句级缺失 words 不影响区间提取。
    """
    if not metadata:
        return []
    raw = metadata.get("subtitles")
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    sentences: Any = None
    if isinstance(raw, dict):
        sentences = raw.get("sentences")
    elif isinstance(raw, list):
        sentences = raw
    if not isinstance(sentences, list):
        return []

    events: List[SubtitleEvent] = []
    for sentence in sentences:
        if not isinstance(sentence, Mapping):
            continue
        start_ms = _to_ms(sentence.get("start_time"))
        end_ms = _to_ms(sentence.get("end_time"))
        text = str(sentence.get("text") or "").strip()
        if start_ms is None or end_ms is None or not text:
            continue
        events.append(SubtitleEvent(start_ms=start_ms, end_ms=end_ms, text=text))
    return events


def _to_ms(value: Any) -> Optional[int]:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def align_speech_events(
    events: Sequence[Mapping[str, Any]],
    subtitles: Sequence[SubtitleEvent],
) -> Dict[str, Any]:
    """把目标 speech 事件按顺序贪心对齐到字幕区间。

    返回每个事件的匹配结果与未匹配台词列表。对齐规则：按目标事件顺序，
    在字幕中取文本包含关系成立且未被占用的最近区间（以窗口中心距最小者优先）。
    """
    speech = [event for event in events if event.get("kind") == "speech"]
    used: set[int] = set()
    matched: List[Dict[str, Any]] = []
    unmatched: List[str] = []

    for event in speech:
        text = str(event.get("text") or "")
        target_center_ms = (float(event["start_s"]) + float(event["end_s"])) * 500.0
        best_index: Optional[int] = None
        best_distance: Optional[float] = None
        for index, subtitle in enumerate(subtitles):
            if index in used:
                continue
            if text not in subtitle.text and subtitle.text not in text:
                continue
            center_ms = (subtitle.start_ms + subtitle.end_ms) / 2.0
            distance = abs(center_ms - target_center_ms)
            if best_distance is None or distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            unmatched.append(text)
            continue
        used.add(best_index)
        subtitle = subtitles[best_index]
        matched.append(
            {
                "event_id": event.get("id"),
                "text": text,
                "target_start_ms": float(event["start_s"]) * 1000.0,
                "target_end_ms": float(event["end_s"]) * 1000.0,
                "actual_start_ms": float(subtitle.start_ms),
                "actual_end_ms": float(subtitle.end_ms),
            }
        )

    return {
        "matched": matched,
        "unmatched": unmatched,
        "alignment_ratio": (len(matched) / len(speech)) if speech else None,
        "unmatched_subtitles": [
            {"text": item.text, "start_ms": item.start_ms, "end_ms": item.end_ms}
            for index, item in enumerate(subtitles)
            if index not in used
        ],
    }


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    """线性插值百分位数；空序列返回 None。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize(values: Sequence[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"p50": None, "p95": None, "max": None, "count": 0}
    return {
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": max(values),
        "count": len(values),
    }


def compute_run_metrics(
    run_id: str,
    *,
    success: bool,
    events: Sequence[Mapping[str, Any]],
    subtitles: Sequence[SubtitleEvent],
    total_duration_s: float,
    observed_duration_ms: Optional[float] = None,
    error: str = "",
) -> RunMetrics:
    """计算单次运行的四类误差（单位毫秒）。"""
    metrics = RunMetrics(run_id=run_id, success=success, error=error)
    if not success:
        return metrics

    alignment = align_speech_events(events, subtitles)
    metrics.alignment_ratio = alignment["alignment_ratio"]
    metrics.unmatched_texts = list(alignment["unmatched"])

    within_window = 0
    for item in alignment["matched"]:
        start_error = item["actual_start_ms"] - item["target_start_ms"]
        end_error = item["actual_end_ms"] - item["target_end_ms"]
        metrics.start_errors_ms.append(abs(start_error))
        metrics.end_errors_ms.append(abs(end_error))
        within_tolerance = (
            abs(start_error) <= DEFAULT_THRESHOLDS["bounded_tolerance_ms"]
            and abs(end_error) <= DEFAULT_THRESHOLDS["bounded_tolerance_ms"]
            and item["actual_start_ms"] >= item["target_start_ms"]
            and item["actual_end_ms"] <= item["target_end_ms"] + DEFAULT_THRESHOLDS["bounded_tolerance_ms"]
        )
        if within_tolerance:
            within_window += 1
    if alignment["matched"]:
        metrics.within_window_ratio = within_window / len(alignment["matched"])

    # 事件对齐误差：speech 事件取 start 偏差；非语音事件无字幕观测手段，
    # 记入证据但不产生数值（阶段 0 如实记录该盲区）。
    metrics.event_alignment_errors_ms = list(metrics.start_errors_ms)

    if observed_duration_ms is not None:
        metrics.observed_duration_ms = float(observed_duration_ms)
        metrics.duration_error_ms = abs(
            float(observed_duration_ms) - total_duration_s * 1000.0
        )
    return metrics


def aggregate_run_metrics(runs: Sequence[RunMetrics]) -> Dict[str, Any]:
    """跨运行聚合：四项误差的 P50/P95/最大偏差。"""
    successful = [run for run in runs if run.success]
    start_errors = [value for run in successful for value in run.start_errors_ms]
    end_errors = [value for run in successful for value in run.end_errors_ms]
    duration_errors = [
        run.duration_error_ms for run in successful if run.duration_error_ms is not None
    ]
    event_errors = [
        value for run in successful for value in run.event_alignment_errors_ms
    ]
    return {
        "run_count": len(runs),
        "successful_run_count": len(successful),
        "start_error_ms": summarize(start_errors),
        "end_error_ms": summarize(end_errors),
        "duration_error_ms": summarize(duration_errors),
        "event_alignment_error_ms": summarize(event_errors),
    }


def decide_timeline_eligibility(
    runs: Sequence[RunMetrics],
    thresholds: EligibilityThresholds | None = None,
) -> Dict[str, Any]:
    """输出版本化的 bounded / strict eligible 结论。

    结论仅由指标与阈值决定，不引入人工裁量；任何阈值解释都属于
    进度文档的记录职责。
    """
    policy = thresholds or EligibilityThresholds()
    successful = [run for run in runs if run.success]
    aggregate = aggregate_run_metrics(runs)

    def _p95(block: Dict[str, Any]) -> Optional[float]:
        return block.get("p95")

    start_stats = aggregate["start_error_ms"]
    end_stats = aggregate["end_error_ms"]
    duration_stats = aggregate["duration_error_ms"]
    event_stats = aggregate["event_alignment_error_ms"]

    strict_reasons: List[str] = []
    if len(successful) < policy.min_runs:
        strict_reasons.append(
            f"成功运行数 {len(successful)} 少于最低要求 {policy.min_runs}"
        )
    alignment_ratios = [
        run.alignment_ratio for run in successful if run.alignment_ratio is not None
    ]
    if not alignment_ratios or min(alignment_ratios) < policy.strict_min_alignment_ratio:
        strict_reasons.append("存在台词未全部对齐的运行")
    for name, stats, limit in (
        ("start_error_ms", start_stats, policy.strict_start_end_p50_ms),
        ("end_error_ms", end_stats, policy.strict_start_end_p50_ms),
    ):
        p50 = stats.get("p50")
        if p50 is None or p50 > limit:
            strict_reasons.append(f"{name} P50 缺失或超过 {limit:.0f}ms")
    for name, stats, limit in (
        ("start_error_ms", start_stats, policy.strict_start_end_p95_ms),
        ("end_error_ms", end_stats, policy.strict_start_end_p95_ms),
        ("event_alignment_error_ms", event_stats, policy.strict_event_alignment_p95_ms),
    ):
        p95 = _p95(stats)
        if p95 is None or p95 > limit:
            strict_reasons.append(f"{name} P95 缺失或超过 {limit:.0f}ms")
    duration_p95 = _p95(duration_stats)
    if duration_p95 is None or duration_p95 > policy.strict_duration_p95_ms:
        strict_reasons.append(
            f"duration_error_ms P95 缺失或超过 {policy.strict_duration_p95_ms:.0f}ms"
        )

    bounded_reasons: List[str] = []
    if len(successful) < policy.min_runs:
        bounded_reasons.append(
            f"成功运行数 {len(successful)} 少于最低要求 {policy.min_runs}"
        )
    within_ratios = [
        run.within_window_ratio
        for run in successful
        if run.within_window_ratio is not None
    ]
    if not within_ratios:
        bounded_reasons.append("没有任何运行产生可对齐的台词窗口")
    else:
        covered = sum(1 for ratio in within_ratios if ratio >= policy.bounded_within_window_ratio)
        if covered < max(1, len(successful) - 1):
            bounded_reasons.append(
                f"窗口内比例 >= {policy.bounded_within_window_ratio:.0%} 的运行不足"
            )
    duration_p95_bounded = _p95(duration_stats)
    if duration_p95_bounded is None or duration_p95_bounded > policy.bounded_duration_p95_ms:
        bounded_reasons.append(
            f"duration_error_ms P95 缺失或超过 {policy.bounded_duration_p95_ms:.0f}ms"
        )

    return {
        "policy_version": ELIGIBILITY_POLICY_VERSION,
        "thresholds": {
            "min_runs": policy.min_runs,
            "strict_min_alignment_ratio": policy.strict_min_alignment_ratio,
            "strict_start_end_p50_ms": policy.strict_start_end_p50_ms,
            "strict_start_end_p95_ms": policy.strict_start_end_p95_ms,
            "strict_duration_p95_ms": policy.strict_duration_p95_ms,
            "strict_event_alignment_p95_ms": policy.strict_event_alignment_p95_ms,
            "bounded_within_window_ratio": policy.bounded_within_window_ratio,
            "bounded_tolerance_ms": policy.bounded_tolerance_ms,
            "bounded_duration_p95_ms": policy.bounded_duration_p95_ms,
        },
        "aggregate": aggregate,
        "strict_timeline_eligible": not strict_reasons,
        "strict_reasons": strict_reasons,
        "bounded_timeline_eligible": not bounded_reasons,
        "bounded_reasons": bounded_reasons,
    }
