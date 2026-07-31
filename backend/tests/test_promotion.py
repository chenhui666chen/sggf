"""
晋升统计 + 硬闸门/推荐指标评估（设计文档 §7.1 / §8.1 / §8.2 · §14 第 9 步 · 子块 A）

纯逻辑测试：Wilson 置信下界 + 按挑战者聚合 verdict 统计 + 硬闸门逐条 + 推荐指标。
不触 DB、不接外部 API，全部确定性验证。
"""
import math

import pytest

from app.services.prompt_evolution.promotion import (
    PromotionThresholds,
    aggregate_challenger_stats,
    evaluate_promotion_gate,
    wilson_lower_bound,
)
from app.services.prompt_evolution.review_verdict import (
    VERDICT_CONFIRMED_WIN,
    VERDICT_HARD_FAILURE,
    VERDICT_INFRASTRUCTURE_FAILURE,
    VERDICT_INVALIDATED_WIN,
    VERDICT_LOSS,
)


def _verdicts(*, confirmed=0, loss=0, invalidated=0, hard=0, infra=0):
    """按各类计数拼出一段 verdict 序列（顺序无关，聚合只看计数）。"""
    return (
        [VERDICT_CONFIRMED_WIN] * confirmed
        + [VERDICT_LOSS] * loss
        + [VERDICT_INVALIDATED_WIN] * invalidated
        + [VERDICT_HARD_FAILURE] * hard
        + [VERDICT_INFRASTRUCTURE_FAILURE] * infra
    )


# ---------------- wilson_lower_bound ----------------

def test_wilson_lower_bound_zero_total_returns_zero():
    assert wilson_lower_bound(0, 0) == 0.0


def test_wilson_lower_bound_known_value_60_of_100():
    # 60/100，z=1.96 → 约 0.5020
    assert wilson_lower_bound(60, 100) == pytest.approx(0.5020, abs=1e-3)


def test_wilson_lower_bound_known_value_90_of_100():
    # 90/100，z=1.96 → 约 0.8256
    assert wilson_lower_bound(90, 100) == pytest.approx(0.8256, abs=1e-3)


def test_wilson_lower_bound_lower_than_point_estimate():
    # 下界必严格小于点估计（除边界外）
    lb = wilson_lower_bound(70, 100)
    assert 0.0 < lb < 0.70


def test_wilson_lower_bound_wider_ci_at_90_confidence():
    # 90% 置信（z=1.645）下界应高于 95%（z=1.96），因区间更窄
    lb95 = wilson_lower_bound(60, 100, z=1.96)
    lb90 = wilson_lower_bound(60, 100, z=1.645)
    assert lb90 > lb95


# ---------------- aggregate_challenger_stats ----------------

def test_aggregate_basic_counts_and_rates():
    stats = aggregate_challenger_stats(_verdicts(confirmed=70, loss=30))
    assert stats.confirmed_win == 70
    assert stats.loss == 30
    assert stats.decisive_total == 100
    assert stats.effective_total == 100
    assert stats.win_rate == pytest.approx(0.70)
    assert stats.hard_fail_rate == pytest.approx(0.0)
    assert stats.invalidation_rate == pytest.approx(0.0)


def test_aggregate_excludes_infra_from_effective_total():
    # 基础设施失败不进有效样本、不进胜负分母（§5.5 / §7.1）
    stats = aggregate_challenger_stats(_verdicts(confirmed=60, loss=30, infra=10))
    assert stats.infrastructure_failure == 10
    assert stats.effective_total == 90       # 60 + 30，排除 infra
    assert stats.decisive_total == 90
    assert stats.win_rate == pytest.approx(60 / 90)


def test_aggregate_invalidation_rate_and_hard_fail_rate():
    stats = aggregate_challenger_stats(
        _verdicts(confirmed=70, loss=20, invalidated=10, hard=5)
    )
    # 作废率 = invalidated / (confirmed + invalidated)（与 replay_calibration 同口径）
    assert stats.invalidation_rate == pytest.approx(10 / 80)
    # 有效样本 = confirmed + loss + invalidated + hard（排除 infra/provisional）
    assert stats.effective_total == 105
    assert stats.hard_fail_rate == pytest.approx(5 / 105)
    # 胜负分母只含 confirmed + loss，invalidated 不计胜负
    assert stats.decisive_total == 90
    assert stats.win_rate == pytest.approx(70 / 90)


def test_aggregate_empty_is_all_zero():
    stats = aggregate_challenger_stats([])
    assert stats.effective_total == 0
    assert stats.decisive_total == 0
    assert stats.win_rate == 0.0
    assert stats.wilson_lower_bound == 0.0


def test_aggregate_wilson_lower_bound_uses_decisive_total():
    stats = aggregate_challenger_stats(_verdicts(confirmed=70, loss=30))
    assert stats.wilson_lower_bound == pytest.approx(wilson_lower_bound(70, 100), abs=1e-6)


# ---------------- evaluate_promotion_gate ----------------

def _passing_stats():
    # 70 胜 / 30 负，无硬失败无作废，有效样本恰 100
    return aggregate_challenger_stats(_verdicts(confirmed=70, loss=30))


def test_gate_all_pass_hard_and_recommended():
    result = evaluate_promotion_gate(
        _passing_stats(),
        offline_gate_passed=True,
        policy_version_consistent=True,
        has_unresolved_safety_incident=False,
    )
    assert result.hard_gate_passed is True
    assert result.hard_gate_failures == []
    assert result.recommended is True
    assert result.recommend_failures == []


def test_gate_fails_on_insufficient_samples():
    stats = aggregate_challenger_stats(_verdicts(confirmed=7, loss=3))
    result = evaluate_promotion_gate(
        stats,
        offline_gate_passed=True,
        policy_version_consistent=True,
        has_unresolved_safety_incident=False,
    )
    assert result.hard_gate_passed is False
    assert "min_effective_samples" in result.hard_gate_failures


def test_gate_fails_on_offline_gate_not_passed():
    result = evaluate_promotion_gate(
        _passing_stats(),
        offline_gate_passed=False,
        policy_version_consistent=True,
        has_unresolved_safety_incident=False,
    )
    assert result.hard_gate_passed is False
    assert "offline_gate" in result.hard_gate_failures


def test_gate_fails_on_high_hard_fail_rate():
    # 70 胜 / 25 负 / 5 硬失败 → 硬失败率 5/100 = 0.05 > 0.01
    stats = aggregate_challenger_stats(_verdicts(confirmed=70, loss=25, hard=5))
    result = evaluate_promotion_gate(
        stats,
        offline_gate_passed=True,
        policy_version_consistent=True,
        has_unresolved_safety_incident=False,
    )
    assert result.hard_gate_passed is False
    assert "hard_fail_rate" in result.hard_gate_failures


def test_gate_fails_on_policy_version_inconsistent():
    result = evaluate_promotion_gate(
        _passing_stats(),
        offline_gate_passed=True,
        policy_version_consistent=False,
        has_unresolved_safety_incident=False,
    )
    assert result.hard_gate_passed is False
    assert "policy_version_consistent" in result.hard_gate_failures


def test_gate_fails_on_unresolved_safety_incident():
    result = evaluate_promotion_gate(
        _passing_stats(),
        offline_gate_passed=True,
        policy_version_consistent=True,
        has_unresolved_safety_incident=True,
    )
    assert result.hard_gate_passed is False
    assert "safety_incident" in result.hard_gate_failures


def test_gate_hard_passes_but_recommend_fails_on_low_win_rate():
    # 55 胜 / 45 负 → 有效样本 100 硬闸门过，但胜率 0.55 < 0.60 且 wilson 下界 < 0.50
    stats = aggregate_challenger_stats(_verdicts(confirmed=55, loss=45))
    result = evaluate_promotion_gate(
        stats,
        offline_gate_passed=True,
        policy_version_consistent=True,
        has_unresolved_safety_incident=False,
    )
    assert result.hard_gate_passed is True
    assert result.recommended is False
    assert "win_rate" in result.recommend_failures
    assert "wilson_lower_bound" in result.recommend_failures


def test_gate_hard_passes_but_recommend_fails_on_high_invalidation():
    # 70 胜 / 30 负 / 10 作废 → 作废率 10/80 = 0.125 > 0.05
    stats = aggregate_challenger_stats(_verdicts(confirmed=70, loss=30, invalidated=10))
    result = evaluate_promotion_gate(
        stats,
        offline_gate_passed=True,
        policy_version_consistent=True,
        has_unresolved_safety_incident=False,
    )
    assert result.hard_gate_passed is True
    assert result.recommended is False
    assert "invalidation_rate" in result.recommend_failures


def test_thresholds_from_env(monkeypatch):
    monkeypatch.setenv("PROMOTION_MIN_EFFECTIVE_SAMPLES", "200")
    monkeypatch.setenv("PROMOTION_MAX_HARD_FAIL_RATE", "0.02")
    monkeypatch.setenv("PROMOTION_MIN_WIN_RATE", "0.65")
    monkeypatch.setenv("PROMOTION_MIN_WILSON_LOWER_BOUND", "0.55")
    monkeypatch.setenv("PROMOTION_MAX_INVALIDATION_RATE", "0.03")
    monkeypatch.setenv("PROMOTION_WILSON_Z", "1.645")
    t = PromotionThresholds.from_env()
    assert t.min_effective_samples == 200
    assert t.max_hard_fail_rate == pytest.approx(0.02)
    assert t.min_win_rate == pytest.approx(0.65)
    assert t.min_wilson_lower_bound == pytest.approx(0.55)
    assert t.max_invalidation_rate == pytest.approx(0.03)
    assert t.wilson_z == pytest.approx(1.645)


def test_thresholds_defaults():
    t = PromotionThresholds()
    assert t.min_effective_samples == 100
    assert t.max_hard_fail_rate == pytest.approx(0.01)
    assert t.min_win_rate == pytest.approx(0.60)
    assert t.min_wilson_lower_bound == pytest.approx(0.50)
    assert t.max_invalidation_rate == pytest.approx(0.05)
    assert t.wilson_z == pytest.approx(1.96)
