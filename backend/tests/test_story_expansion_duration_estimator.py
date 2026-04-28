import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DEBUG", "false")

from app.services.story_expansion_duration_estimator import (
    StoryExpansionDurationFeatures,
    StoryExpansionDurationSample,
    calibrate_duration_from_samples,
    extract_duration_features_from_analysis,
    extract_duration_features_from_result,
)


def _features(**overrides) -> StoryExpansionDurationFeatures:
    values = {
        "execution_mode": "iterative",
        "expansion_mode": "total",
        "estimated_rounds": 8,
        "chapter_delta": 80,
        "character_delta": 20,
        "volume_span": 0,
        "base_min_minutes": 29,
        "base_max_minutes": 47,
        "project_id": 1,
    }
    values.update(overrides)
    return StoryExpansionDurationFeatures(**values)


def test_calibrate_duration_uses_similar_round_chapter_and_character_samples() -> None:
    current = _features()
    samples = [
        StoryExpansionDurationSample(_features(base_min_minutes=30, base_max_minutes=50), actual_minutes=82, completed_rank=0),
        StoryExpansionDurationSample(
            _features(estimated_rounds=7, chapter_delta=72, character_delta=18, base_min_minutes=28, base_max_minutes=44),
            actual_minutes=68,
            completed_rank=1,
        ),
        StoryExpansionDurationSample(
            _features(estimated_rounds=8, chapter_delta=85, character_delta=22, base_min_minutes=31, base_max_minutes=49),
            actual_minutes=79,
            completed_rank=2,
        ),
    ]

    calibration = calibrate_duration_from_samples(current, samples)

    assert calibration.source == "history_calibrated"
    assert calibration.sample_count == 3
    assert calibration.min_minutes > current.base_min_minutes
    assert calibration.max_minutes > current.base_max_minutes
    assert calibration.confidence in {"medium", "high"}


def test_calibrate_duration_ignores_different_execution_mode_samples() -> None:
    current = _features()
    samples = [
        StoryExpansionDurationSample(
            _features(execution_mode="epic", estimated_rounds=1, base_min_minutes=8, base_max_minutes=14),
            actual_minutes=90,
            completed_rank=0,
        ),
    ]

    calibration = calibrate_duration_from_samples(current, samples)

    assert calibration.source == "static"
    assert calibration.sample_count == 0
    assert calibration.min_minutes == current.base_min_minutes
    assert calibration.max_minutes == current.base_max_minutes


def test_extract_duration_features_from_analysis_counts_requested_delta() -> None:
    analysis = {
        "execution_mode": "iterative",
        "effective_expansion_mode": "total",
        "estimated_rounds": 6,
        "estimated_duration_minutes_min": 20,
        "estimated_duration_minutes_max": 40,
        "effective_target_chapter_count": 120,
        "effective_target_character_count": 35,
        "validation": {
            "chapter_count": 60,
            "character_count": 12,
        },
    }

    features = extract_duration_features_from_analysis(analysis, project_id=9)

    assert features is not None
    assert features.execution_mode == "iterative"
    assert features.estimated_rounds == 6
    assert features.chapter_delta == 60
    assert features.character_delta == 23
    assert features.project_id == 9


def test_extract_duration_features_from_result_prefers_history_payload_targets() -> None:
    result = {
        "execution_mode": "volume_detail",
        "story_expansion_mode": "volume_detail",
        "target_chapter_count": 80,
        "target_character_count": 28,
        "volume_chapter_range": [1, 80],
        "validation_before": {
            "chapter_count": 0,
            "character_count": 20,
        },
        "execution_rounds": [{"round": 1}, {"round": 2}],
        "expansion_analysis": {
            "execution_mode": "volume_detail",
            "effective_expansion_mode": "volume_detail",
            "estimated_rounds": 1,
            "estimated_duration_minutes_min": 29,
            "estimated_duration_minutes_max": 47,
            "effective_target_chapter_count": 80,
            "effective_target_character_count": 28,
            "validation": {
                "chapter_count": 0,
                "character_count": 20,
            },
            "volume_detail": {
                "chapter_range": [1, 80],
            },
        },
    }

    features = extract_duration_features_from_result(result, project_id=3)

    assert features is not None
    assert features.execution_mode == "volume_detail"
    assert features.estimated_rounds == 2
    assert features.chapter_delta == 80
    assert features.character_delta == 8
    assert features.volume_span == 80
