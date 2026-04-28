"""协同扩展历史耗时校准。

该模块只做一件事：在现有静态估时基础上，用相似历史任务的实际耗时做温和校准。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.utils.datetime_utils import parse_datetime_utc


HISTORY_LIMIT = 80
MIN_VALID_DURATION_MINUTES = 1.0
MAX_VALID_DURATION_MINUTES = 180.0
MIN_CALIBRATION_RATIO = 0.6
MAX_CALIBRATION_RATIO = 2.5


@dataclass(frozen=True)
class StoryExpansionDurationFeatures:
    execution_mode: str
    expansion_mode: str
    estimated_rounds: int
    chapter_delta: int
    character_delta: int
    volume_span: int
    base_min_minutes: int
    base_max_minutes: int
    project_id: Optional[int] = None

    @property
    def base_mid_minutes(self) -> float:
        return max(1.0, (self.base_min_minutes + self.base_max_minutes) / 2.0)


@dataclass(frozen=True)
class StoryExpansionDurationSample:
    features: StoryExpansionDurationFeatures
    actual_minutes: float
    completed_rank: int = 0

    @property
    def actual_to_estimate_ratio(self) -> float:
        return self.actual_minutes / self.features.base_mid_minutes


@dataclass(frozen=True)
class StoryExpansionDurationCalibration:
    min_minutes: int
    max_minutes: int
    source: str
    confidence: str
    sample_count: int
    calibration_ratio: float
    reason: str


def _to_positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _to_non_negative_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, number)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_mode(value: Any, default: str) -> str:
    raw = str(value or "").strip()
    return raw or default


def _extract_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}

    value: Any = raw.strip()
    for _ in range(2):
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            value = json.loads(value)
        except Exception:
            return {}
        if isinstance(value, dict):
            return value
    return {}


def _safe_span_from_range(value: Any) -> int:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return 0
    start = _to_positive_int(value[0])
    end = _to_positive_int(value[1])
    if start is None or end is None:
        return 0
    return max(0, end - start + 1)


def _resolve_count_delta(
    *,
    current: Any,
    target: Any,
    fallback_delta: Any = None,
) -> int:
    current_count = _to_non_negative_int(current)
    target_count = _to_non_negative_int(target)
    if current_count is not None and target_count is not None:
        return max(0, target_count - current_count)

    fallback = _to_non_negative_int(fallback_delta)
    return fallback or 0


def extract_duration_features_from_analysis(
    analysis: dict[str, Any],
    *,
    project_id: Optional[int] = None,
) -> Optional[StoryExpansionDurationFeatures]:
    """从协同扩展分析结果中抽取可用于估时校准的特征。"""
    analysis_dict = _as_dict(analysis)
    validation = _as_dict(analysis_dict.get("validation"))
    auto_supplement = _as_dict(analysis_dict.get("auto_supplement"))
    volume_detail = _as_dict(analysis_dict.get("volume_detail"))
    model_plan = _as_dict(analysis_dict.get("model_plan"))

    base_min = (
        _to_positive_int(analysis_dict.get("duration_estimate_base_minutes_min"))
        or _to_positive_int(analysis_dict.get("estimated_duration_minutes_min"))
    )
    base_max = (
        _to_positive_int(analysis_dict.get("duration_estimate_base_minutes_max"))
        or _to_positive_int(analysis_dict.get("estimated_duration_minutes_max"))
    )
    if base_min is None and base_max is None:
        return None
    if base_min is None:
        base_min = base_max
    if base_max is None:
        base_max = base_min
    if base_min is None or base_max is None:
        return None
    base_min, base_max = min(base_min, base_max), max(base_min, base_max)

    estimated_rounds = (
        _to_positive_int(analysis_dict.get("estimated_rounds"))
        or _to_positive_int(model_plan.get("estimated_rounds"))
        or 1
    )
    chapter_delta = _resolve_count_delta(
        current=validation.get("chapter_count"),
        target=analysis_dict.get("effective_target_chapter_count"),
        fallback_delta=auto_supplement.get("chapter_delta"),
    )
    character_delta = _resolve_count_delta(
        current=validation.get("character_count"),
        target=analysis_dict.get("effective_target_character_count"),
        fallback_delta=auto_supplement.get("character_delta"),
    )
    volume_span = _safe_span_from_range(volume_detail.get("chapter_range"))

    return StoryExpansionDurationFeatures(
        execution_mode=_normalize_mode(analysis_dict.get("execution_mode"), "delta"),
        expansion_mode=_normalize_mode(analysis_dict.get("effective_expansion_mode"), "total"),
        estimated_rounds=estimated_rounds,
        chapter_delta=chapter_delta,
        character_delta=character_delta,
        volume_span=volume_span,
        base_min_minutes=base_min,
        base_max_minutes=base_max,
        project_id=project_id,
    )


def extract_duration_features_from_result(
    result_payload: dict[str, Any],
    *,
    project_id: Optional[int] = None,
) -> Optional[StoryExpansionDurationFeatures]:
    """从历史协同扩展任务结果中抽取估时特征。"""
    payload = _as_dict(result_payload)
    analysis = _as_dict(payload.get("expansion_analysis"))
    if not analysis:
        return None

    features = extract_duration_features_from_analysis(analysis, project_id=project_id)
    if features is None:
        return None

    execution_mode = _normalize_mode(payload.get("execution_mode") or features.execution_mode, features.execution_mode)
    expansion_mode = _normalize_mode(payload.get("story_expansion_mode") or features.expansion_mode, features.expansion_mode)
    execution_rounds = payload.get("execution_rounds")
    estimated_rounds = features.estimated_rounds
    if isinstance(execution_rounds, list) and execution_rounds:
        estimated_rounds = max(estimated_rounds, len(execution_rounds))

    validation_before = _as_dict(payload.get("validation_before"))
    chapter_delta = _resolve_count_delta(
        current=validation_before.get("chapter_count"),
        target=payload.get("target_chapter_count") or analysis.get("effective_target_chapter_count"),
        fallback_delta=features.chapter_delta,
    )
    character_delta = _resolve_count_delta(
        current=validation_before.get("character_count"),
        target=payload.get("target_character_count") or analysis.get("effective_target_character_count"),
        fallback_delta=features.character_delta,
    )
    volume_span = _safe_span_from_range(payload.get("volume_chapter_range")) or features.volume_span

    return StoryExpansionDurationFeatures(
        execution_mode=execution_mode,
        expansion_mode=expansion_mode,
        estimated_rounds=estimated_rounds,
        chapter_delta=chapter_delta,
        character_delta=character_delta,
        volume_span=volume_span,
        base_min_minutes=features.base_min_minutes,
        base_max_minutes=features.base_max_minutes,
        project_id=project_id,
    )


def _ratio_similarity(current: int, historical: int, *, floor: int) -> float:
    if current == historical:
        return 1.0
    scale = max(floor, current, historical)
    return 1.0 / (1.0 + abs(current - historical) / scale)


def _sample_weight(current: StoryExpansionDurationFeatures, sample: StoryExpansionDurationSample) -> float:
    historical = sample.features
    if current.execution_mode != historical.execution_mode:
        return 0.0

    weight = 1.0
    if current.expansion_mode != historical.expansion_mode:
        weight *= 0.7

    weight *= 1.0 / (1.0 + abs(current.estimated_rounds - historical.estimated_rounds))
    weight *= _ratio_similarity(current.chapter_delta, historical.chapter_delta, floor=10)
    weight *= _ratio_similarity(current.character_delta, historical.character_delta, floor=5)

    if current.volume_span or historical.volume_span:
        weight *= _ratio_similarity(current.volume_span, historical.volume_span, floor=10)

    if current.project_id is not None and current.project_id == historical.project_id:
        weight *= 1.15

    weight *= max(0.35, math.pow(0.96, max(0, sample.completed_rank)))
    return weight


def calibrate_duration_from_samples(
    current: StoryExpansionDurationFeatures,
    samples: Iterable[StoryExpansionDurationSample],
) -> StoryExpansionDurationCalibration:
    weighted_ratios: list[tuple[float, float]] = []
    for sample in samples:
        ratio = sample.actual_to_estimate_ratio
        if not math.isfinite(ratio) or ratio <= 0:
            continue
        weight = _sample_weight(current, sample)
        if weight <= 0:
            continue
        weighted_ratios.append((weight, max(0.35, min(3.5, ratio))))

    if not weighted_ratios:
        return StoryExpansionDurationCalibration(
            min_minutes=current.base_min_minutes,
            max_minutes=current.base_max_minutes,
            source="static",
            confidence="low",
            sample_count=0,
            calibration_ratio=1.0,
            reason="暂无同模式历史协同扩展任务，使用任务规模预估。",
        )

    total_weight = sum(weight for weight, _ in weighted_ratios)
    weighted_ratio = sum(weight * ratio for weight, ratio in weighted_ratios) / total_weight
    # 样本少时只做温和校准，避免一次异常任务污染后续估时。
    strength = min(1.0, max(0.25, total_weight / 2.5))
    calibration_ratio = 1.0 + (weighted_ratio - 1.0) * strength
    calibration_ratio = max(MIN_CALIBRATION_RATIO, min(MAX_CALIBRATION_RATIO, calibration_ratio))

    min_minutes = max(1, int(math.ceil(current.base_min_minutes * calibration_ratio)))
    max_minutes = max(min_minutes + 1, int(math.ceil(current.base_max_minutes * calibration_ratio)))

    sample_count = len(weighted_ratios)
    confidence = "low"
    if sample_count >= 8 and total_weight >= 4.0:
        confidence = "high"
    elif sample_count >= 3 and total_weight >= 1.2:
        confidence = "medium"

    return StoryExpansionDurationCalibration(
        min_minutes=min_minutes,
        max_minutes=max_minutes,
        source="history_calibrated",
        confidence=confidence,
        sample_count=sample_count,
        calibration_ratio=round(calibration_ratio, 3),
        reason=(
            f"基于 {sample_count} 条同模式、相近轮次、相近章节与人物增量的历史协同扩展任务校准。"
        ),
    )


def _build_sample_from_history_row(row: Any, completed_rank: int) -> Optional[StoryExpansionDurationSample]:
    project_id = _to_positive_int(getattr(row, "project_id", None) if hasattr(row, "project_id") else row[0])
    raw_result = getattr(row, "result", None) if hasattr(row, "result") else row[1]
    created_at_raw = getattr(row, "created_at", None) if hasattr(row, "created_at") else row[2]
    completed_at_raw = getattr(row, "completed_at", None) if hasattr(row, "completed_at") else row[3]

    created_at = parse_datetime_utc(created_at_raw)
    completed_at = parse_datetime_utc(completed_at_raw)
    if created_at is None or completed_at is None or completed_at <= created_at:
        return None

    actual_minutes = (completed_at - created_at).total_seconds() / 60.0
    if actual_minutes < MIN_VALID_DURATION_MINUTES or actual_minutes > MAX_VALID_DURATION_MINUTES:
        return None

    payload = _extract_json_object(raw_result)
    features = extract_duration_features_from_result(payload, project_id=project_id)
    if features is None:
        return None

    return StoryExpansionDurationSample(
        features=features,
        actual_minutes=actual_minutes,
        completed_rank=completed_rank,
    )


def load_story_expansion_duration_samples(
    db: Session,
    *,
    user_id: int,
    limit: int = HISTORY_LIMIT,
) -> list[StoryExpansionDurationSample]:
    query = text(
        """
        SELECT gh.project_id, gh.result, gh.created_at, gh.completed_at
        FROM generation_history gh
        INNER JOIN projects p ON gh.project_id = p.id
        WHERE p.user_id = :user_id
          AND gh.task_type = 'expand_story'
          AND gh.status = 'completed'
          AND gh.result IS NOT NULL
          AND gh.created_at IS NOT NULL
          AND gh.completed_at IS NOT NULL
        ORDER BY gh.completed_at DESC
        LIMIT :limit
        """
    )
    rows = db.execute(query, {"user_id": user_id, "limit": max(1, int(limit))}).fetchall()

    samples: list[StoryExpansionDurationSample] = []
    for index, row in enumerate(rows):
        sample = _build_sample_from_history_row(row, index)
        if sample is not None:
            samples.append(sample)
    return samples


def apply_story_expansion_duration_history_calibration(
    db: Session,
    *,
    user_id: int,
    project_id: int,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """返回带历史校准估时字段的分析结果副本。"""
    next_analysis = dict(analysis)
    current = extract_duration_features_from_analysis(next_analysis, project_id=project_id)
    if current is None:
        return next_analysis

    samples = load_story_expansion_duration_samples(db, user_id=user_id)
    calibration = calibrate_duration_from_samples(current, samples)

    next_analysis["duration_estimate_base_minutes_min"] = current.base_min_minutes
    next_analysis["duration_estimate_base_minutes_max"] = current.base_max_minutes
    next_analysis["duration_estimate_source"] = calibration.source
    next_analysis["duration_estimate_confidence"] = calibration.confidence
    next_analysis["duration_estimate_sample_count"] = calibration.sample_count
    next_analysis["duration_estimate_calibration_ratio"] = calibration.calibration_ratio
    next_analysis["duration_estimate_reason"] = calibration.reason

    if calibration.source == "history_calibrated":
        next_analysis["estimated_duration_minutes_min"] = calibration.min_minutes
        next_analysis["estimated_duration_minutes_max"] = calibration.max_minutes

    return next_analysis
