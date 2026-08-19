"""盲评标定合同（指导文档 §13.4/阶段 6）。

Omni 结果必须与人工盲评对比，按 finding code 统计六项指标；在每类
严重问题没有足够正负样本前，Omni 只能作为影子或人工辅助评审。
门槛与最小样本量为版本化常量，调整须按进度文档登记决策变更。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from ..hashing import canonical_hash

CALIBRATION_CONTRACT_NAME = "finding_calibration_set"

# §11.2 针对性重试代码集合中可由 Omni 语义 finding 触发自动处置的部分；
# provider_or_technical_error 为技术错误，不属于 Omni 语义标定范围。
AUTO_RETRY_FINDING_CODES = (
    "missing_dialogue",
    "extra_dialogue",
    "dialogue_order_invalid",
    "speaker_assignment_mismatch",
    "foreground_masked",
    "required_sound_event_missing",
    "acoustic_treatment_missing",
    "invalid_timeline",
)

# 版本化门槛（阶段 6 初始值；真实盲评数据到位后按 DEC 调整）。
CALIBRATION_MIN_PRECISION = 0.85
CALIBRATION_MIN_RECALL = 0.70
CALIBRATION_MIN_POSITIVE_SAMPLES = 30
CALIBRATION_MIN_NEGATIVE_SAMPLES = 30
CALIBRATION_THRESHOLDS_VERSION = "1.0.0"


@dataclass(frozen=True)
class FindingCalibration:
    """单个 finding code 的盲评标定记录（§13.4 六项指标）。"""

    finding_code: str
    positive_samples: int
    negative_samples: int
    precision: float
    recall: float
    false_positive_rate: float
    false_negative_rate: float
    confidence_calibration_error: float
    repeat_review_agreement: float

    def __post_init__(self) -> None:
        if self.finding_code not in AUTO_RETRY_FINDING_CODES:
            raise ValueError(
                f"finding code not in auto-retry calibration set: {self.finding_code}"
            )
        for label, value in (
            ("precision", self.precision),
            ("recall", self.recall),
            ("false_positive_rate", self.false_positive_rate),
            ("false_negative_rate", self.false_negative_rate),
            ("confidence_calibration_error", self.confidence_calibration_error),
            ("repeat_review_agreement", self.repeat_review_agreement),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{label} must be within [0, 1]")
        if int(self.positive_samples) < 0 or int(self.negative_samples) < 0:
            raise ValueError("sample counts must be non-negative")

    @property
    def disqualification_reasons(self) -> List[str]:
        reasons: List[str] = []
        if self.precision < CALIBRATION_MIN_PRECISION:
            reasons.append(
                f"precision {self.precision:.3f} below threshold "
                f"{CALIBRATION_MIN_PRECISION:.3f}"
            )
        if self.recall < CALIBRATION_MIN_RECALL:
            reasons.append(
                f"recall {self.recall:.3f} below threshold "
                f"{CALIBRATION_MIN_RECALL:.3f}"
            )
        if self.positive_samples < CALIBRATION_MIN_POSITIVE_SAMPLES:
            reasons.append(
                f"positive samples {self.positive_samples} below minimum "
                f"{CALIBRATION_MIN_POSITIVE_SAMPLES}"
            )
        if self.negative_samples < CALIBRATION_MIN_NEGATIVE_SAMPLES:
            reasons.append(
                f"negative samples {self.negative_samples} below minimum "
                f"{CALIBRATION_MIN_NEGATIVE_SAMPLES}"
            )
        return reasons

    @property
    def is_calibrated(self) -> bool:
        return not self.disqualification_reasons

    def canonical_payload(self) -> Dict[str, Any]:
        return {
            "finding_code": self.finding_code,
            "positive_samples": int(self.positive_samples),
            "negative_samples": int(self.negative_samples),
            "precision": float(self.precision),
            "recall": float(self.recall),
            "false_positive_rate": float(self.false_positive_rate),
            "false_negative_rate": float(self.false_negative_rate),
            "confidence_calibration_error": float(self.confidence_calibration_error),
            "repeat_review_agreement": float(self.repeat_review_agreement),
        }


def calibration_set_fingerprint(
    records: Sequence[FindingCalibration], *, calibration_version: str
) -> str:
    """标定集合版本化指纹：进入语义质量策略与自动处置决策审计。"""
    if not str(calibration_version).strip():
        raise ValueError("calibration_version must be non-empty")
    codes = [record.finding_code for record in records]
    if len(codes) != len(set(codes)):
        raise ValueError("duplicate finding codes in calibration set")
    ordered = sorted(records, key=lambda record: record.finding_code)
    return canonical_hash(
        {
            "calibration_version": calibration_version,
            "thresholds_version": CALIBRATION_THRESHOLDS_VERSION,
            "min_precision": CALIBRATION_MIN_PRECISION,
            "min_recall": CALIBRATION_MIN_RECALL,
            "min_positive_samples": CALIBRATION_MIN_POSITIVE_SAMPLES,
            "min_negative_samples": CALIBRATION_MIN_NEGATIVE_SAMPLES,
            "records": [record.canonical_payload() for record in ordered],
        },
        contract_name=CALIBRATION_CONTRACT_NAME,
        contract_version=calibration_version,
    )


__all__ = [
    "AUTO_RETRY_FINDING_CODES",
    "CALIBRATION_MIN_NEGATIVE_SAMPLES",
    "CALIBRATION_MIN_POSITIVE_SAMPLES",
    "CALIBRATION_MIN_PRECISION",
    "CALIBRATION_MIN_RECALL",
    "CALIBRATION_THRESHOLDS_VERSION",
    "FindingCalibration",
    "calibration_set_fingerprint",
]
