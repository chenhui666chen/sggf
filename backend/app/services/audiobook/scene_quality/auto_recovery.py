"""有限自动恢复决策（指导文档 §10.6 阶段 C/阶段 6）。

只有经过盲评标定、高置信、可定位的严重问题可以自动触发一次针对性
Seed 重试；主观风格问题不得自动处置；每场景最多一次，每章成本上限；
重试成本按真实 Seed 成功响应计费和审计。决策为确定性纯函数，拒绝
原因码可审计。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .semantic_models import SemanticFinding
from .calibration import FindingCalibration
from .semantic_quality_policy import SemanticQualityPolicy

RECOVERY_DECISION_REASONS = (
    "allowed",
    "disabled_by_policy",
    "auto_retry_disabled",
    "uncalibrated_code",
    "subjective_finding",
    "low_confidence",
    "not_locatable",
    "scene_retry_budget_exhausted",
    "chapter_retry_budget_exhausted",
)


@dataclass(frozen=True)
class AutoRecoveryDecision:
    """自动恢复决策记录：允许与否、原因码与审计追溯字段。"""

    allow: bool
    reason_code: str
    finding_code: str
    policy_fingerprint: str

    def __post_init__(self) -> None:
        if self.reason_code not in RECOVERY_DECISION_REASONS:
            raise ValueError(f"unknown recovery decision reason: {self.reason_code}")

    @property
    def bills_as_seed_response(self) -> bool:
        """允许的自动重试按真实 Seed 成功响应继续计费和审计。"""
        return bool(self.allow)


def decide_auto_recovery(
    finding: SemanticFinding,
    policy: SemanticQualityPolicy,
    calibration: Mapping[str, FindingCalibration],
    *,
    scene_attempts_used: int,
    chapter_attempts_used: int,
) -> AutoRecoveryDecision:
    """按固定顺序执行策略门槛、标定门槛、finding 质量门槛与预算门槛。"""
    if int(scene_attempts_used) < 0 or int(chapter_attempts_used) < 0:
        raise ValueError("attempt counters must be non-negative")

    def _deny(reason_code: str) -> AutoRecoveryDecision:
        return AutoRecoveryDecision(
            allow=False,
            reason_code=reason_code,
            finding_code=finding.code,
            policy_fingerprint=policy.fingerprint(),
        )

    # 1. 一键关闭开关：优先于一切判定。
    if not policy.enabled:
        return _deny("disabled_by_policy")
    if not policy.auto_retry_enabled:
        return _deny("auto_retry_disabled")
    # 2. 主观风格问题不得自动阻断。
    if finding.severity not in policy.eligible_severities:
        return _deny("subjective_finding")
    # 3. 只有经过标定的错误代码可以自动触发重试。
    record = calibration.get(finding.code)
    if record is None or not record.is_calibrated:
        return _deny("uncalibrated_code")
    # 4. 高置信门槛。
    if finding.confidence < policy.min_confidence:
        return _deny("low_confidence")
    # 5. 可定位门槛：零长度区间无法定位到时间区间。
    if policy.require_locatable and finding.start_ms == finding.end_ms:
        return _deny("not_locatable")
    # 6. 预算门槛：每场景最多一次，每章成本上限。
    if scene_attempts_used >= policy.max_auto_retries_per_scene:
        return _deny("scene_retry_budget_exhausted")
    if chapter_attempts_used >= policy.max_auto_retries_per_chapter:
        return _deny("chapter_retry_budget_exhausted")

    return AutoRecoveryDecision(
        allow=True,
        reason_code="allowed",
        finding_code=finding.code,
        policy_fingerprint=policy.fingerprint(),
    )


__all__ = [
    "AutoRecoveryDecision",
    "RECOVERY_DECISION_REASONS",
    "decide_auto_recovery",
]
