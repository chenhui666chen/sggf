"""Omni 影子评审输出 Schema（指导文档 §10.3）。

评审结果只记录、不阻断（阶段 A 影子评审）；Schema 校验保证每条失败
finding 可定位到时间区间，且 Prompt 允许 ``not_assessable``，不强迫
模型猜测。结果身份哈希只由评审内容决定，运行元数据（reviewed_at 等）
不入哈希。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple

from ..hashing import canonical_hash

SCENE_SEMANTIC_REVIEW_SCHEMA_VERSION = "scene-semantic-review-v1"

# §10.3 十个固定评审维度。
REVIEW_DIMENSIONS: Tuple[str, ...] = (
    "dialogue_fidelity",
    "speaker_assignment",
    "speaker_separation",
    "performance",
    "vocalizations",
    "sound_events",
    "music",
    "ambient",
    "acoustic_space",
    "mix_balance",
)

# 维度评审状态；not_assessable 表示模型无法从音频中判断，不得强迫猜测。
DIMENSION_STATUSES = ("pass", "fail", "not_assessable")

# §10.3 建议动作；影子阶段只记录，manual_review/retry_once 供后续阶段消费。
RECOMMENDED_ACTIONS = ("accept", "manual_review", "retry_once", "not_assessable")

FINDING_SEVERITIES = ("minor", "major", "critical")

FINDING_SUGGESTED_ACTIONS = ("accept", "manual_review", "retry_once", "not_assessable")

RESULT_CONTRACT_NAME = "scene_semantic_review_result"
_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True)
class SemanticFinding:
    """失败 finding：必须给出时间区间、期望、观察结果和置信度（§10.3）。"""

    code: str
    severity: str
    confidence: float
    start_ms: int
    end_ms: int
    expected: str
    observed: str
    suggested_action: str

    def __post_init__(self) -> None:
        if not str(self.code).strip():
            raise ValueError("finding code must be non-empty")
        if self.severity not in FINDING_SEVERITIES:
            raise ValueError(f"unknown finding severity: {self.severity}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("finding confidence must be within [0, 1]")
        if int(self.start_ms) > int(self.end_ms):
            raise ValueError("finding start_ms must not exceed end_ms")
        if not str(self.expected).strip():
            raise ValueError("finding must carry expected evidence")
        if not str(self.observed).strip():
            raise ValueError("finding must carry observed evidence")
        if self.suggested_action not in FINDING_SUGGESTED_ACTIONS:
            raise ValueError(f"unknown suggested action: {self.suggested_action}")

    def canonical_payload(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "confidence": float(self.confidence),
            "start_ms": int(self.start_ms),
            "end_ms": int(self.end_ms),
            "expected": self.expected,
            "observed": self.observed,
            "suggested_action": self.suggested_action,
        }


@dataclass(frozen=True)
class SemanticReviewResult:
    """场景/接缝语义评审结果（scene-semantic-review-v1）。"""

    passed: bool
    confidence: float
    dimensions: Mapping[str, str]
    findings: Tuple[SemanticFinding, ...]
    recommended_action: str
    reviewed_at: float = 0.0
    schema_version: str = field(
        init=False, default=SCENE_SEMANTIC_REVIEW_SCHEMA_VERSION
    )

    def __post_init__(self) -> None:
        if set(self.dimensions) != set(REVIEW_DIMENSIONS):
            raise ValueError(
                "dimensions must cover exactly the ten review dimensions"
            )
        for name, status in self.dimensions.items():
            if status not in DIMENSION_STATUSES:
                raise ValueError(f"unknown dimension status for {name}: {status}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("review confidence must be within [0, 1]")
        if self.recommended_action not in RECOMMENDED_ACTIONS:
            raise ValueError(
                f"unknown recommended action: {self.recommended_action}"
            )
        if not self.passed and not self.findings:
            raise ValueError("failed review must carry at least one finding")

    @property
    def result_hash(self) -> str:
        """评审内容身份哈希；reviewed_at 等运行元数据不参与。"""
        return canonical_hash(
            {
                "schema_version": self.schema_version,
                "passed": bool(self.passed),
                "confidence": float(self.confidence),
                "dimensions": dict(self.dimensions),
                "findings": [
                    finding.canonical_payload() for finding in self.findings
                ],
                "recommended_action": self.recommended_action,
            },
            contract_name=RESULT_CONTRACT_NAME,
            contract_version=_CONTRACT_VERSION,
        )


__all__ = [
    "DIMENSION_STATUSES",
    "FINDING_SEVERITIES",
    "FINDING_SUGGESTED_ACTIONS",
    "RECOMMENDED_ACTIONS",
    "REVIEW_DIMENSIONS",
    "SCENE_SEMANTIC_REVIEW_SCHEMA_VERSION",
    "SemanticFinding",
    "SemanticReviewResult",
]
