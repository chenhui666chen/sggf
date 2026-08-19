"""阶段 5 Omni 影子评审策略测试（指导文档 §10.6/§10.7/§12.1）。

覆盖：

- 默认策略：影子评审（mode=shadow）、不阻断、不自动重试、不改变账单；
- 独立开关：semantic_review_enabled 一键关闭；mode 枚举只接受
  shadow/manual_assisted，阶段 C 的 limited_auto 未在阶段 5 开放；
- 预算与超时：章节/场景评审次数上限、单次调用超时、音频时长上限均
  必须为正，非法配置拒绝；
- 错误分类：超时/供应商错误/Schema 无效/预算超限/预处理失败各自独立
  归因，全部落为 recorded_error（只记录，不阻断），未知错误拒绝；
- 策略指纹：版本化且确定性，policy 变化进入评审缓存键。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR,):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_quality.semantic_policy import (  # noqa: E402
    DEFAULT_SEMANTIC_REVIEW_POLICY,
    REVIEW_ERROR_KINDS,
    SemanticReviewPolicy,
    classify_review_error,
)


class TestDefaultPolicy:
    def test_default_is_shadow_and_non_blocking(self) -> None:
        policy = DEFAULT_SEMANTIC_REVIEW_POLICY
        assert policy.enabled is True
        assert policy.mode == "shadow"
        assert policy.blocks_output is False
        assert policy.allow_auto_retry is False
        assert policy.changes_billing is False

    def test_default_budgets_are_positive(self) -> None:
        policy = DEFAULT_SEMANTIC_REVIEW_POLICY
        assert policy.max_scene_reviews_per_chapter > 0
        assert policy.max_seam_reviews_per_chapter > 0
        assert policy.request_timeout_s > 0
        assert policy.max_audio_duration_s > 0


class TestPolicyValidation:
    def test_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            SemanticReviewPolicy.from_mapping({"mode": "live_blocking"})

    def test_limited_auto_mode_is_not_open_in_phase_5(self) -> None:
        with pytest.raises(ValueError):
            SemanticReviewPolicy.from_mapping({"mode": "limited_auto"})

    @pytest.mark.parametrize(
        "override",
        [
            {"max_scene_reviews_per_chapter": 0},
            {"max_seam_reviews_per_chapter": -1},
            {"request_timeout_s": 0},
            {"max_audio_duration_s": 0},
        ],
    )
    def test_non_positive_budgets_are_rejected(self, override) -> None:
        with pytest.raises(ValueError):
            SemanticReviewPolicy.from_mapping(override)

    def test_from_mapping_merges_over_defaults(self) -> None:
        policy = SemanticReviewPolicy.from_mapping({"request_timeout_s": 45.0})
        assert policy.request_timeout_s == 45.0
        assert policy.mode == DEFAULT_SEMANTIC_REVIEW_POLICY.mode

    def test_disabled_policy_refuses_review(self) -> None:
        policy = SemanticReviewPolicy.from_mapping({"enabled": False})
        assert policy.should_review_scene is False
        assert DEFAULT_SEMANTIC_REVIEW_POLICY.should_review_scene is True


class TestErrorClassification:
    def test_all_error_kinds_are_recorded_not_blocking(self) -> None:
        assert set(REVIEW_ERROR_KINDS) == {
            "timeout",
            "provider_error",
            "schema_invalid",
            "budget_exceeded",
            "preprocessing_failed",
        }
        for kind in REVIEW_ERROR_KINDS:
            outcome = classify_review_error(kind)
            assert outcome["error_kind"] == kind
            assert outcome["outcome"] == "recorded_error"
            assert outcome["blocks_output"] is False
            assert outcome["triggers_retry"] is False

    def test_unknown_error_kind_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            classify_review_error("cosmic_ray")


class TestPolicyFingerprint:
    def test_fingerprint_is_versioned_and_deterministic(self) -> None:
        policy = DEFAULT_SEMANTIC_REVIEW_POLICY
        assert policy.policy_version
        assert policy.fingerprint() == policy.fingerprint()

    def test_fingerprint_changes_with_policy_fields(self) -> None:
        base = DEFAULT_SEMANTIC_REVIEW_POLICY.fingerprint()
        changed = SemanticReviewPolicy.from_mapping(
            {"request_timeout_s": 99.0}
        ).fingerprint()
        assert base != changed
