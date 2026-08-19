"""阶段 6 有限自动恢复决策测试（指导文档 §10.6 阶段 C/阶段 6）。

覆盖：

- 仅经标定的错误代码可自动触发一次针对性重试；
- 高置信、可定位、严重问题三重门槛联合判定；
- 主观风格问题（minor）不得自动处置；
- 每场景一次、每章成本上限，超限拒绝；
- 拒绝原因码确定性、可审计（携带 finding code 与策略指纹）；
- 重试按真实 Seed 响应计费语义进入决策记录。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_quality.auto_recovery import (  # noqa: E402
    AutoRecoveryDecision,
    decide_auto_recovery,
)
from app.services.audiobook.scene_quality.calibration import (  # noqa: E402
    FindingCalibration,
)
from app.services.audiobook.scene_quality.semantic_models import (  # noqa: E402
    SemanticFinding,
)
from app.services.audiobook.scene_quality.semantic_quality_policy import (  # noqa: E402
    DEFAULT_SEMANTIC_QUALITY_POLICY,
)


def _finding(**overrides) -> SemanticFinding:
    payload = {
        "code": "missing_dialogue",
        "severity": "major",
        "confidence": 0.95,
        "start_ms": 4_000,
        "end_ms": 9_000,
        "expected": "林晚说出关键台词",
        "observed": "该区间内未检测到对应台词",
        "suggested_action": "retry_once",
    }
    payload.update(overrides)
    return SemanticFinding(**payload)


def _calibrated(**overrides) -> FindingCalibration:
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


def _decide(finding=None, policy=None, calibration=None, **kwargs) -> AutoRecoveryDecision:
    kwargs.setdefault("scene_attempts_used", 0)
    kwargs.setdefault("chapter_attempts_used", 0)
    return decide_auto_recovery(
        finding or _finding(),
        policy or DEFAULT_SEMANTIC_QUALITY_POLICY,
        calibration if calibration is not None else {"missing_dialogue": _calibrated()},
        **kwargs,
    )


class TestAllowedPath:
    def test_calibrated_severe_locatable_high_confidence_is_allowed(self) -> None:
        decision = _decide(scene_attempts_used=0, chapter_attempts_used=0)
        assert decision.allow is True
        assert decision.reason_code == "allowed"
        assert decision.finding_code == "missing_dialogue"

    def test_confidence_at_threshold_is_allowed(self) -> None:
        finding = _finding(confidence=DEFAULT_SEMANTIC_QUALITY_POLICY.min_confidence)
        assert _decide(finding=finding).allow is True

    def test_allowed_decision_bills_retry_as_real_seed_response(self) -> None:
        decision = _decide()
        assert decision.bills_as_seed_response is True


class TestPolicyGates:
    def test_disabled_policy_denies_everything_first(self) -> None:
        from app.services.audiobook.scene_quality.semantic_quality_policy import (
            SemanticQualityPolicy,
        )

        policy = SemanticQualityPolicy(
            calibration_version="1.0.0",
            calibration_fingerprint="abc",
            enabled=False,
        )
        decision = _decide(policy=policy)
        assert decision.allow is False
        assert decision.reason_code == "disabled_by_policy"

    def test_auto_retry_switch_denies(self) -> None:
        from app.services.audiobook.scene_quality.semantic_quality_policy import (
            SemanticQualityPolicy,
        )

        policy = SemanticQualityPolicy(
            calibration_version="1.0.0",
            calibration_fingerprint="abc",
            auto_retry_enabled=False,
        )
        assert _decide(policy=policy).reason_code == "auto_retry_disabled"


class TestCalibrationGate:
    def test_uncalibrated_code_denied(self) -> None:
        finding = _finding(code="extra_dialogue")
        decision = _decide(finding=finding)
        assert decision.allow is False
        assert decision.reason_code == "uncalibrated_code"

    def test_failed_calibration_denied(self) -> None:
        record = _calibrated(precision=0.5)
        decision = _decide(calibration={"missing_dialogue": record})
        assert decision.allow is False
        assert decision.reason_code == "uncalibrated_code"

    def test_subjective_minor_finding_denied(self) -> None:
        decision = _decide(finding=_finding(severity="minor"))
        assert decision.allow is False
        assert decision.reason_code == "subjective_finding"


class TestFindingQualityGates:
    def test_low_confidence_denied(self) -> None:
        finding = _finding(confidence=0.5)
        assert _decide(finding=finding).reason_code == "low_confidence"

    def test_zero_length_interval_not_locatable(self) -> None:
        finding = _finding(start_ms=4_000, end_ms=4_000)
        assert _decide(finding=finding).reason_code == "not_locatable"

    def test_locatable_requirement_can_be_relaxed_by_policy(self) -> None:
        from app.services.audiobook.scene_quality.semantic_quality_policy import (
            SemanticQualityPolicy,
        )

        policy = SemanticQualityPolicy(
            calibration_version="1.0.0",
            calibration_fingerprint="abc",
            require_locatable=False,
        )
        finding = _finding(start_ms=4_000, end_ms=4_000)
        assert _decide(finding=finding, policy=policy).allow is True


class TestBudgetGates:
    def test_scene_budget_exhausted_after_single_retry(self) -> None:
        # §10.6 阶段 C：Omni 触发的 Seed 重试每场景最多一次。
        decision = _decide(scene_attempts_used=1, chapter_attempts_used=1)
        assert decision.allow is False
        assert decision.reason_code == "scene_retry_budget_exhausted"

    def test_chapter_cost_cap_denies(self) -> None:
        cap = DEFAULT_SEMANTIC_QUALITY_POLICY.max_auto_retries_per_chapter
        decision = _decide(scene_attempts_used=0, chapter_attempts_used=cap)
        assert decision.allow is False
        assert decision.reason_code == "chapter_retry_budget_exhausted"

    def test_negative_attempt_counters_rejected(self) -> None:
        with pytest.raises(ValueError):
            _decide(scene_attempts_used=-1)


class TestDecisionAuditability:
    def test_decision_carries_policy_fingerprint(self) -> None:
        decision = _decide()
        assert decision.policy_fingerprint == (
            DEFAULT_SEMANTIC_QUALITY_POLICY.fingerprint()
        )

    def test_decision_is_deterministic(self) -> None:
        first = _decide(finding=_finding(code="extra_dialogue"))
        second = _decide(
            finding=_finding(code="extra_dialogue"),
            calibration={"extra_dialogue": _calibrated(finding_code="extra_dialogue")},
        )
        assert first.reason_code == "uncalibrated_code"
        assert second.allow is True
