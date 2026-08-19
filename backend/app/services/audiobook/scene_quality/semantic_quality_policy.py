"""版本化语义质量策略（指导文档 §10.6 阶段 C/阶段 6）。

阶段 6 发布版本化语义质量策略：仅开放高置信、可定位、严重问题的
一次自动重试，具备明确 precision/recall 门槛（绑定标定集合指纹）、
成本上限与一键关闭开关。主观风格问题（minor）不得进入自动处置。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from ..hashing import canonical_hash
from .calibration import AUTO_RETRY_FINDING_CODES

QUALITY_POLICY_CONTRACT_NAME = "semantic_quality_policy"

# 严重问题白名单上限：minor 属主观风格，永不进自动处置（§10.6 阶段 C）。
_ELIGIBLE_SEVERITY_UNIVERSE = ("major", "critical")


@dataclass(frozen=True)
class SemanticQualityPolicy:
    """版本化语义质量策略；指纹进入自动处置决策审计。"""

    enabled: bool = True
    auto_retry_enabled: bool = True
    policy_version: str = "1.0.0"
    min_confidence: float = 0.85
    eligible_severities: Tuple[str, ...] = _ELIGIBLE_SEVERITY_UNIVERSE
    require_locatable: bool = True
    max_auto_retries_per_scene: int = 1
    max_auto_retries_per_chapter: int = 5
    calibration_version: str = "0.0.0"
    calibration_fingerprint: str = "no-calibration"

    def __post_init__(self) -> None:
        if not str(self.policy_version).strip():
            raise ValueError("policy_version must be non-empty")
        if not str(self.calibration_version).strip():
            raise ValueError("calibration_version must be non-empty")
        if not str(self.calibration_fingerprint).strip():
            raise ValueError("calibration_fingerprint must be non-empty")
        if not 0.0 < float(self.min_confidence) <= 1.0:
            raise ValueError("min_confidence must be within (0, 1]")
        severities = tuple(self.eligible_severities)
        if not severities:
            raise ValueError("eligible_severities must not be empty")
        for severity in severities:
            if severity not in _ELIGIBLE_SEVERITY_UNIVERSE:
                raise ValueError(
                    "subjective severity not eligible for auto disposition: "
                    f"{severity}"
                )
        object.__setattr__(self, "eligible_severities", severities)
        # §10.6 阶段 C：Omni 触发的 Seed 重试每场景最多一次，硬约束。
        if int(self.max_auto_retries_per_scene) != 1:
            raise ValueError("max_auto_retries_per_scene must be exactly 1")
        if int(self.max_auto_retries_per_chapter) < 1:
            raise ValueError("max_auto_retries_per_chapter must be positive")

    @property
    def blocks_output(self) -> bool:
        """语义质量策略不阻断成品输出。"""
        return False

    @property
    def bills_seed_retry_as_real_response(self) -> bool:
        """重试成本按真实 Seed 成功响应继续计费和审计（§10.6 阶段 C）。"""
        return True

    def auto_retry_allowed(self, finding_code: str, severity: str) -> bool:
        """一键关闭开关 + 标定代码集合 + severity 白名单联合判定。"""
        return (
            bool(self.enabled)
            and bool(self.auto_retry_enabled)
            and finding_code in AUTO_RETRY_FINDING_CODES
            and severity in self.eligible_severities
        )

    @classmethod
    def from_mapping(cls, overrides: Mapping[str, Any]) -> SemanticQualityPolicy:
        base = DEFAULT_SEMANTIC_QUALITY_POLICY
        merged: Dict[str, Any] = {
            "enabled": base.enabled,
            "auto_retry_enabled": base.auto_retry_enabled,
            "policy_version": base.policy_version,
            "min_confidence": base.min_confidence,
            "eligible_severities": base.eligible_severities,
            "require_locatable": base.require_locatable,
            "max_auto_retries_per_scene": base.max_auto_retries_per_scene,
            "max_auto_retries_per_chapter": base.max_auto_retries_per_chapter,
            "calibration_version": base.calibration_version,
            "calibration_fingerprint": base.calibration_fingerprint,
        }
        for key, value in overrides.items():
            if key not in merged:
                raise ValueError(f"unknown semantic quality policy field: {key}")
            merged[key] = value
        return cls(**merged)

    def fingerprint(self) -> str:
        return canonical_hash(
            {
                "enabled": bool(self.enabled),
                "auto_retry_enabled": bool(self.auto_retry_enabled),
                "policy_version": self.policy_version,
                "min_confidence": float(self.min_confidence),
                "eligible_severities": list(self.eligible_severities),
                "require_locatable": bool(self.require_locatable),
                "max_auto_retries_per_scene": self.max_auto_retries_per_scene,
                "max_auto_retries_per_chapter": self.max_auto_retries_per_chapter,
                "calibration_version": self.calibration_version,
                "calibration_fingerprint": self.calibration_fingerprint,
            },
            contract_name=QUALITY_POLICY_CONTRACT_NAME,
            contract_version=self.policy_version,
        )


DEFAULT_SEMANTIC_QUALITY_POLICY = SemanticQualityPolicy()


__all__ = [
    "DEFAULT_SEMANTIC_QUALITY_POLICY",
    "SemanticQualityPolicy",
]
