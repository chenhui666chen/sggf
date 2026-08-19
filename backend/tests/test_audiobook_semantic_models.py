"""阶段 5 Omni 影子评审输出 Schema 测试（指导文档 §10.3）。

覆盖：

- schema_version 固定为 scene-semantic-review-v1；
- 评审维度为十个固定维度，缺失/多余均拒绝；
- finding 必须可定位：时间区间（start_ms ≤ end_ms）、期望、观察结果与
  置信度（0-1）；
- Prompt 允许 not_assessable，不得强迫模型猜测：维度评审状态与
  recommended_action 均接受 not_assessable；
- 结果身份哈希只由评审内容决定（评审缓存键的一部分），reviewed_at
  等运行元数据不入哈希。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_quality.semantic_models import (  # noqa: E402
    REVIEW_DIMENSIONS,
    SCENE_SEMANTIC_REVIEW_SCHEMA_VERSION,
    SemanticFinding,
    SemanticReviewResult,
)


def _dimensions(**overrides):
    dims = {name: "pass" for name in REVIEW_DIMENSIONS}
    dims.update(overrides)
    return dims


def _finding(**overrides):
    payload = {
        "code": "speaker_assignment_mismatch",
        "severity": "major",
        "confidence": 0.9,
        "start_ms": 1200,
        "end_ms": 4600,
        "expected": "男子2 说第二句台词",
        "observed": "声音更接近男子1",
        "suggested_action": "manual_review",
    }
    payload.update(overrides)
    return SemanticFinding(**payload)


class TestFindingLocalization:
    def test_valid_finding_is_accepted(self) -> None:
        finding = _finding()
        assert finding.code == "speaker_assignment_mismatch"
        assert finding.start_ms == 1200
        assert finding.end_ms == 4600

    def test_inverted_time_window_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _finding(start_ms=5000, end_ms=1000)

    def test_missing_evidence_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _finding(expected="")
        with pytest.raises(ValueError):
            _finding(observed="")

    def test_confidence_must_be_within_unit_interval(self) -> None:
        with pytest.raises(ValueError):
            _finding(confidence=1.5)
        with pytest.raises(ValueError):
            _finding(confidence=-0.1)

    def test_unknown_severity_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _finding(severity="catastrophic")


class TestNotAssessable:
    def test_dimension_may_be_not_assessable(self) -> None:
        result = SemanticReviewResult(
            passed=True,
            confidence=0.5,
            dimensions=_dimensions(acoustic_space="not_assessable"),
            findings=(),
            recommended_action="accept",
        )
        assert result.dimensions["acoustic_space"] == "not_assessable"

    def test_recommended_action_may_be_not_assessable(self) -> None:
        result = SemanticReviewResult(
            passed=True,
            confidence=0.0,
            dimensions=_dimensions(),
            findings=(),
            recommended_action="not_assessable",
        )
        assert result.recommended_action == "not_assessable"


class TestReviewResultValidation:
    def test_schema_version_is_fixed(self) -> None:
        result = SemanticReviewResult(
            passed=True,
            confidence=0.8,
            dimensions=_dimensions(),
            findings=(),
            recommended_action="accept",
        )
        assert result.schema_version == SCENE_SEMANTIC_REVIEW_SCHEMA_VERSION
        assert result.schema_version == "scene-semantic-review-v1"

    def test_missing_dimension_is_rejected(self) -> None:
        dims = _dimensions()
        del dims["mix_balance"]
        with pytest.raises(ValueError):
            SemanticReviewResult(
                passed=True,
                confidence=0.5,
                dimensions=dims,
                findings=(),
                recommended_action="accept",
            )

    def test_extra_dimension_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            SemanticReviewResult(
                passed=True,
                confidence=0.5,
                dimensions=_dimensions(extra_dimension="pass"),
                findings=(),
                recommended_action="accept",
            )

    def test_unknown_dimension_status_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            SemanticReviewResult(
                passed=True,
                confidence=0.5,
                dimensions=_dimensions(music="maybe"),
                findings=(),
                recommended_action="accept",
            )

    def test_failed_result_requires_findings(self) -> None:
        with pytest.raises(ValueError):
            SemanticReviewResult(
                passed=False,
                confidence=0.5,
                dimensions=_dimensions(),
                findings=(),
                recommended_action="manual_review",
            )


class TestResultIdentityHash:
    def _result(self, reviewed_at: float = 0.0) -> SemanticReviewResult:
        return SemanticReviewResult(
            passed=False,
            confidence=0.75,
            dimensions=_dimensions(speaker_assignment="fail"),
            findings=(_finding(),),
            recommended_action="manual_review",
            reviewed_at=reviewed_at,
        )

    def test_hash_is_deterministic_and_ignores_runtime_metadata(self) -> None:
        assert self._result(1.0).result_hash == self._result(2.0).result_hash

    def test_hash_changes_with_findings_order(self) -> None:
        first = self._result()
        second_finding = _finding(
            code="missing_dialogue", start_ms=9000, end_ms=11000,
            expected="第三句台词", observed="未听到",
        )
        reversed_result = SemanticReviewResult(
            passed=False,
            confidence=0.75,
            dimensions=_dimensions(speaker_assignment="fail"),
            findings=(second_finding, _finding()),
            recommended_action="manual_review",
        )
        assert first.result_hash != reversed_result.result_hash
