"""量化质量监控（P3）：章节张力趋势 + 浅层文风漂移。

职责（对应指导文档第 8 节）：
- 张力 5 指标（tension/conflict_progress/emotion_change/information_gain/ending_hook）
  搭车 P2 写后消化 LLM 输出（不新增 LLM 调用），滚动存入
  ``review_meta.quality_trend``，并计算最近章节趋势告警；
- 文风漂移只做纯 Python 浅层特征（平均句长/对话占比/套话密度等），
  与项目基线对比，只作为修订信号记录，绝不覆盖用户稿件；
- 量化指标不替代失败码，仅作为证据与现有修订路由配合。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("uvicorn.error")

QUALITY_TREND_KEY = "quality_trend"
STYLE_TREND_KEY = "style_trend"
# 滚动保留的指标章节数
TREND_WINDOW = 10

# 张力阈值（低于即视为低谷）
TENSION_LOW_THRESHOLD = 40
HOOK_LOW_THRESHOLD = 40
PROGRESS_LOW_THRESHOLD = 40

_METRIC_FIELDS = (
    "tension_score",
    "conflict_progress_score",
    "emotion_change_score",
    "information_gain_score",
    "ending_hook_score",
)

# 浅层文风套话/AI痕迹词表（首期保守，只取高区分度项）
_CLICHE_WORDS = (
    "突然", "瞬间", "不禁", "然而", "此刻", "此时此刻",
    "仿佛", "缓缓", "淡淡", "竟然", "顿时", "只见",
)
_SENTENCE_END_RE = re.compile(r"[。！？!?…]+")
_QUOTE_RE = re.compile(r"[「『“\"“]([^”\"』」]*?)[”\"』」]")


# ---------------------------------------------------------------------------
# 张力指标（搭车 P2 消化输出）
# ---------------------------------------------------------------------------
def validate_quality_metrics(raw: Any) -> Dict[str, int]:
    """校验并裁剪消化输出的张力指标；缺失/非法字段不保留。"""
    metrics: Dict[str, int] = {}
    if not isinstance(raw, dict):
        return metrics
    for field in _METRIC_FIELDS:
        value = raw.get(field)
        try:
            score = int(round(float(value)))
        except (TypeError, ValueError):
            continue
        metrics[field] = max(0, min(100, score))
    return metrics


def record_quality_metrics(
    review_meta: Dict[str, Any],
    chapter_number: int,
    metrics: Dict[str, int],
) -> bool:
    """将张力指标滚动写入 review_meta.quality_trend；无指标时跳过。"""
    if not isinstance(review_meta, dict) or not metrics:
        return False
    trend = review_meta.get(QUALITY_TREND_KEY)
    if not isinstance(trend, dict):
        trend = {}
    chapters = trend.get("chapters")
    if not isinstance(chapters, dict):
        chapters = {}
    chapters[str(int(chapter_number))] = metrics
    if len(chapters) > TREND_WINDOW:
        ordered = sorted(chapters.keys(), key=lambda key: int(key) if key.isdigit() else 0)
        for obsolete in ordered[: len(chapters) - TREND_WINDOW]:
            chapters.pop(obsolete, None)
    trend["chapters"] = chapters
    trend["alerts"] = evaluate_quality_trend_alerts(chapters)
    review_meta[QUALITY_TREND_KEY] = trend
    return True


def evaluate_quality_trend_alerts(chapters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按文档 8.1 触发策略计算趋势告警（只记录，不强制重写）。

    - 连续两章 tension 低于阈值 → planning_diagnosis（进入规划诊断）
    - 单章结尾钩子与推进分同时过低 → targeted_revision（定向修订）
    - 单章低谷且章节定位允许 → 仅记录，不告警
    """
    alerts: List[Dict[str, Any]] = []
    ordered_keys = sorted(
        (key for key in chapters.keys() if key.isdigit()),
        key=lambda key: int(key),
    )
    if not ordered_keys:
        return alerts

    latest_key = ordered_keys[-1]
    latest = chapters.get(latest_key) or {}

    hook = latest.get("ending_hook_score")
    progress = latest.get("conflict_progress_score")
    if (
        isinstance(hook, int) and hook < HOOK_LOW_THRESHOLD
        and isinstance(progress, int) and progress < PROGRESS_LOW_THRESHOLD
    ):
        alerts.append(
            {
                "type": "targeted_revision",
                "chapter": int(latest_key),
                "detail": f"第{latest_key}章结尾钩子({hook})与冲突推进({progress})同时过低，建议定向修订",
            }
        )

    if len(ordered_keys) >= 2:
        prev_key = ordered_keys[-2]
        prev = chapters.get(prev_key) or {}
        latest_tension = latest.get("tension_score")
        prev_tension = prev.get("tension_score")
        if (
            isinstance(latest_tension, int) and latest_tension < TENSION_LOW_THRESHOLD
            and isinstance(prev_tension, int) and prev_tension < TENSION_LOW_THRESHOLD
        ):
            alerts.append(
                {
                    "type": "planning_diagnosis",
                    "chapter": int(latest_key),
                    "detail": (
                        f"第{prev_key}章({prev_tension})与第{latest_key}章({latest_tension})"
                        "张力连续低于阈值，下一章规划需诊断推进停滞原因"
                    ),
                }
            )
    return alerts


def format_quality_trend_advice(review_meta: Optional[Dict[str, Any]]) -> str:
    """将趋势告警格式化为规划提示词建议；无告警返回空串。"""
    trend = ((review_meta or {}).get(QUALITY_TREND_KEY) or {})
    alerts = trend.get("alerts") or []
    if not alerts:
        return ""
    lines = ["【质量趋势告警】（量化指标证据，规划时必须针对性处理）"]
    for alert in alerts[:3]:
        lines.append(f"- {alert.get('detail')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 浅层文风漂移（纯 Python，无 LLM；只记录不覆盖稿件）
# ---------------------------------------------------------------------------
def compute_style_features(text: str) -> Dict[str, float]:
    """计算章节浅层风格特征；文本过短返回空 dict。"""
    content = str(text or "").strip()
    if len(content) < 400:
        return {}

    sentences = [s.strip() for s in _SENTENCE_END_RE.split(content) if s.strip()]
    avg_sentence_len = (
        round(sum(len(s) for s in sentences) / len(sentences), 1) if sentences else 0.0
    )

    dialogue_chars = sum(len(match.group(1)) for match in _QUOTE_RE.finditer(content))
    dialogue_ratio = round(dialogue_chars / len(content), 3)

    cliches = sum(content.count(word) for word in _CLICHE_WORDS)
    cliches_per_1k = round(cliches * 1000 / len(content), 2)

    exclamations = content.count("！") + content.count("!")
    exclamation_per_1k = round(exclamations * 1000 / len(content), 2)

    return {
        "avg_sentence_len": avg_sentence_len,
        "dialogue_ratio": dialogue_ratio,
        "cliches_per_1k": cliches_per_1k,
        "exclamation_per_1k": exclamation_per_1k,
    }


def _relative_deviation(value: float, baseline: float) -> float:
    if baseline <= 0:
        return 0.0
    return abs(value - baseline) / baseline


def detect_style_drift(
    review_meta: Dict[str, Any],
    chapter_number: int,
    features: Dict[str, float],
    *,
    sentence_deviation_threshold: float = 0.35,
    dialogue_deviation_threshold: float = 0.35,
    cliche_delta_threshold: float = 2.0,
) -> Dict[str, Any]:
    """将本章特征与项目基线（此前各章均值）对比，返回漂移判定。

    基线章节不足 3 章时只记录不判定（样本不足）。
    """
    result: Dict[str, Any] = {
        "features": features,
        "drift": False,
        "flags": [],
        "baseline_size": 0,
    }
    if not features:
        return result

    trend = (review_meta or {}).get(STYLE_TREND_KEY) or {}
    chapters = trend.get("chapters") or {}
    prior = [
        feats for key, feats in chapters.items()
        if key.isdigit() and int(key) < int(chapter_number) and isinstance(feats, dict)
    ][-10:]
    result["baseline_size"] = len(prior)
    if len(prior) < 3:
        return result

    def _baseline(field: str) -> float:
        values = [float(p.get(field) or 0.0) for p in prior]
        return sum(values) / len(values) if values else 0.0

    for field, threshold in (
        ("avg_sentence_len", sentence_deviation_threshold),
        ("dialogue_ratio", dialogue_deviation_threshold),
    ):
        baseline = _baseline(field)
        deviation = _relative_deviation(float(features.get(field) or 0.0), baseline)
        if baseline > 0 and deviation > threshold:
            result["flags"].append(
                {
                    "field": field,
                    "value": features.get(field),
                    "baseline": round(baseline, 3),
                    "deviation": round(deviation, 3),
                }
            )

    cliche_baseline = _baseline("cliches_per_1k")
    cliche_delta = float(features.get("cliches_per_1k") or 0.0) - cliche_baseline
    if cliche_delta > cliche_delta_threshold:
        result["flags"].append(
            {
                "field": "cliches_per_1k",
                "value": features.get("cliches_per_1k"),
                "baseline": round(cliche_baseline, 2),
                "deviation": round(cliche_delta, 2),
            }
        )

    result["drift"] = bool(result["flags"])
    return result


def record_style_trend(
    review_meta: Dict[str, Any],
    chapter_number: int,
    chapter_content: str,
) -> Dict[str, Any]:
    """计算本章风格特征、检测漂移并滚动落库（review_meta.style_trend）。

    只记录信号，不修改稿件；任何失败返回空结果不抛异常。
    """
    result: Dict[str, Any] = {"drift": False, "flags": []}
    try:
        if not isinstance(review_meta, dict):
            return result
        features = compute_style_features(chapter_content)
        if not features:
            return result
        drift_result = detect_style_drift(review_meta, chapter_number, features)
        result = drift_result

        trend = review_meta.get(STYLE_TREND_KEY)
        if not isinstance(trend, dict):
            trend = {}
        chapters = trend.get("chapters")
        if not isinstance(chapters, dict):
            chapters = {}
        chapters[str(int(chapter_number))] = features
        if len(chapters) > TREND_WINDOW:
            ordered = sorted(chapters.keys(), key=lambda key: int(key) if key.isdigit() else 0)
            for obsolete in ordered[: len(chapters) - TREND_WINDOW]:
                chapters.pop(obsolete, None)
        trend["chapters"] = chapters
        if drift_result["drift"]:
            trend["last_drift"] = {
                "chapter": int(chapter_number),
                "flags": drift_result["flags"],
            }
        review_meta[STYLE_TREND_KEY] = trend
    except Exception as exc:
        logger.warning("文风漂移记录失败（不影响主流程）: %s", exc)
        return {"drift": False, "flags": []}
    return result
