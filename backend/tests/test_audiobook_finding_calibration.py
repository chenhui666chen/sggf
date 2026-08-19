"""阶段 6 盲评标定合同测试（指导文档 §13.4/阶段 6）。

覆盖：

- 标定记录按 finding code 统计 §13.4 六项指标（precision/recall/
  false positive rate/false negative rate/置信度校准/重复评审一致率）；
- 门槛版本化：precision/recall 门槛与最小正负样本量为版本化常量；
- 未满足门槛或样本量不足的 code 判定为未标定——在每类严重问题没有
  足够正负样本前，Omni 只能作为影子或人工辅助评审；
- 未知 finding code 拒绝（与 §11.2 针对性重试代码集合一致）；
- 标定集合指纹版本化且确定性。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_quality.calibration import (  # noqa: E402
    AUTO_RETRY_FINDING_CODES,
    CALIBRATION_MIN_NEGATIVE_SAMPLES,
    CALIBRATION_MIN_POSITIVE_SAMPLES,
    CALIBRATION_MIN_PRECISION,
    CALIBRATION_MIN_RECALL,
    FindingCalibration,
    calibration_set_fingerprint,
)


def _calibration(**overrides):
    payload = {
        "finding_code": "missing_dialogue",
        "positive_samples": 40,
        "negative_samples": 60,
        "precision": 0.92,
        "recall": 0.88,
        "false_positive_rate": 0.05,
        "false_negative_rate": 0.12,
        "confidence_calibration_error": 0.08,
        "repeat_review_agreement": 0.9,
    }
    payload.update(overrides)
    return FindingCalibration(**payload)


class TestCalibrationRecord:
    def test_well_calibrated_code_passes(self) -> None:
        assert _calibration().is_calibrated is True

    def test_metrics_must_be_within_unit_interval(self) -> None:
        with pytest.raises(ValueError):
            _calibration(precision=1.2)
        with pytest.raises(ValueError):
            _calibration(recall=-0.1)

    def test_unknown_finding_code_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _calibration(finding_code="vague_subjective_opinion")

    def test_auto_retry_code_set_matches_targeted_retry_codes(self) -> None:
        # §11.2 针对性重试代码集合（provider_or_technical_error 不属于
        # Omni 语义 finding，不进自动处置标定集合）。
        assert "provider_or_technical_error" not in AUTO_RETRY_FINDING_CODES
        assert "missing_dialogue" in AUTO_RETRY_FINDING_CODES
        assert "speaker_assignment_mismatch" in AUTO_RETRY_FINDING_CODES


class TestThresholdGates:
    def test_thresholds_are_versioned_constants(self) -> None:
        assert 0 < CALIBRATION_MIN_PRECISION <= 1
        assert 0 < CALIBRATION_MIN_RECALL <= 1
        assert CALIBRATION_MIN_POSITIVE_SAMPLES > 0
        assert CALIBRATION_MIN_NEGATIVE_SAMPLES > 0

    def test_low_precision_is_not_calibrated(self) -> None:
        record = _calibration(precision=CALIBRATION_MIN_PRECISION - 0.01)
        assert record.is_calibrated is False
        assert "precision" in record.disqualification_reasons[0]

    def test_low_recall_is_not_calibrated(self) -> None:
        record = _calibration(recall=CALIBRATION_MIN_RECALL - 0.01)
        assert record.is_calibrated is False
        assert any("recall" in reason for reason in record.disqualification_reasons)

    def test_insufficient_positive_samples_is_not_calibrated(self) -> None:
        record = _calibration(positive_samples=CALIBRATION_MIN_POSITIVE_SAMPLES - 1)
        assert record.is_calibrated is False
        assert any("positive" in reason for reason in record.disqualification_reasons)

    def test_insufficient_negative_samples_is_not_calibrated(self) -> None:
        record = _calibration(negative_samples=CALIBRATION_MIN_NEGATIVE_SAMPLES - 1)
        assert record.is_calibrated is False
        assert any("negative" in reason for reason in record.disqualification_reasons)


class TestCalibrationSetFingerprint:
    def test_fingerprint_is_deterministic_and_order_independent(self) -> None:
        a = _calibration()
        b = _calibration(finding_code="extra_dialogue")
        assert calibration_set_fingerprint(
            [a, b], calibration_version="1.0.0"
        ) == calibration_set_fingerprint([b, a], calibration_version="1.0.0")

    def test_fingerprint_changes_with_version_or_content(self) -> None:
        a = _calibration()
        base = calibration_set_fingerprint([a], calibration_version="1.0.0")
        assert (
            calibration_set_fingerprint([a], calibration_version="1.1.0") != base
        )
        mutated = _calibration(precision=0.99)
        assert (
            calibration_set_fingerprint([mutated], calibration_version="1.0.0")
            != base
        )

    def test_duplicate_codes_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            calibration_set_fingerprint(
                [_calibration(), _calibration()], calibration_version="1.0.0"
            )
