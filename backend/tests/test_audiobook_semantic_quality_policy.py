"""阶段 6 版本化语义质量策略测试（指导文档 §10.6 阶段 C/阶段 6）。

覆盖：

- 策略以 policy_version 版本化发布，指纹确定性；
- 一键关闭开关：enabled 关闭时自动处置整体不可用；
- 仅开放高置信、可定位、严重问题：置信度门槛、severity 白名单、
  可定位要求进入策略字段；
- 每场景最多一次自动重试（硬约束，策略拒绝放宽）；
- 每章成本上限为正整数；重试成本按真实 Seed 响应计费，不阻断成品；
- 标定集合指纹进入策略指纹：标定更新即策略指纹变化；
- from_mapping 拒绝未知字段，合并默认值。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_quality.semantic_quality_policy import (  # noqa: E402,E501
    DEFAULT_SEMANTIC_QUALITY_POLICY,
    SemanticQualityPolicy,
)


class TestDefaults:
    def test_defaults_open_limited_auto_recovery(self) -> None:
        policy = DEFAULT_SEMANTIC_QUALITY_POLICY
        assert policy.enabled is True
        assert policy.auto_retry_enabled is True
        assert policy.max_auto_retries_per_scene == 1
        assert policy.max_auto_retries_per_chapter >= 1
        assert 0 < policy.min_confidence <= 1
        assert policy.eligible_severities == ("major", "critical")
        assert policy.require_locatable is True

    def test_billing_and_blocking_semantics(self) -> None:
        # §10.6 阶段 C：重试成本按真实 Seed 成功响应继续计费；
        # 语义质量策略仍然不得阻断成品输出。
        policy = DEFAULT_SEMANTIC_QUALITY_POLICY
        assert policy.bills_seed_retry_as_real_response is True
        assert policy.blocks_output is False


class TestHardConstraints:
    def test_scene_retry_limit_cannot_be_raised_above_one(self) -> None:
        with pytest.raises(ValueError):
            SemanticQualityPolicy(
                calibration_version="1.0.0",
                calibration_fingerprint="abc",
                max_auto_retries_per_scene=2,
            )

    def test_minor_severity_never_eligible(self) -> None:
        # 主观风格问题不得自动阻断：minor 不进白名单。
        with pytest.raises(ValueError):
            SemanticQualityPolicy(
                calibration_version="1.0.0",
                calibration_fingerprint="abc",
                eligible_severities=("minor", "major"),
            )

    def test_empty_severity_whitelist_rejected(self) -> None:
        with pytest.raises(ValueError):
            SemanticQualityPolicy(
                calibration_version="1.0.0",
                calibration_fingerprint="abc",
                eligible_severities=(),
            )

    def test_calibration_binding_is_required(self) -> None:
        with pytest.raises(ValueError):
            SemanticQualityPolicy(calibration_version="", calibration_fingerprint="abc")
        with pytest.raises(ValueError):
            SemanticQualityPolicy(calibration_version="1.0.0", calibration_fingerprint="")


class TestKillSwitch:
    def test_disabled_policy_blocks_all_auto_dispositions(self) -> None:
        policy = SemanticQualityPolicy(
            calibration_version="1.0.0",
            calibration_fingerprint="abc",
            enabled=False,
        )
        assert policy.auto_retry_allowed("missing_dialogue", "major") is False

    def test_auto_retry_switch_is_independent(self) -> None:
        policy = SemanticQualityPolicy(
            calibration_version="1.0.0",
            calibration_fingerprint="abc",
            auto_retry_enabled=False,
        )
        assert policy.auto_retry_allowed("missing_dialogue", "major") is False

    def test_enabled_policy_admits_calibrated_severe_codes(self) -> None:
        policy = DEFAULT_SEMANTIC_QUALITY_POLICY
        assert policy.auto_retry_allowed("missing_dialogue", "major") is True
        assert policy.auto_retry_allowed("missing_dialogue", "minor") is False
        assert policy.auto_retry_allowed("unknown_code", "critical") is False


class TestFingerprint:
    def test_fingerprint_is_deterministic(self) -> None:
        a = DEFAULT_SEMANTIC_QUALITY_POLICY
        b = SemanticQualityPolicy(
            calibration_version=a.calibration_version,
            calibration_fingerprint=a.calibration_fingerprint,
        )
        assert a.fingerprint() == b.fingerprint()

    def test_fingerprint_changes_with_calibration_or_version(self) -> None:
        base = DEFAULT_SEMANTIC_QUALITY_POLICY.fingerprint()
        changed_calibration = SemanticQualityPolicy(
            calibration_version="1.0.0",
            calibration_fingerprint="different",
        )
        assert changed_calibration.fingerprint() != base
        new_version = SemanticQualityPolicy(
            policy_version="2.0.0",
            calibration_version="1.0.0",
            calibration_fingerprint="abc",
        )
        assert new_version.fingerprint() != base


class TestFromMapping:
    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValueError):
            SemanticQualityPolicy.from_mapping({"surprise_field": 1})

    def test_defaults_merged_over_mapping(self) -> None:
        policy = SemanticQualityPolicy.from_mapping({"min_confidence": 0.95})
        assert policy.min_confidence == 0.95
        assert policy.max_auto_retries_per_scene == 1
        assert policy.enabled is True
