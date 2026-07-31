"""
离线回放一致率校准测试（设计文档 §3.4 第 1 层 / §14 第 5 步）

用进化历史样本回放，统计同步判定器与异步权威评审的一致率 / 作废率，
预热第 1 层"全局判定器基础校准"（样本 ≥200，作废率 ≤5%）。
纯逻辑，回放记录以构造样本注入，不依赖真实存储 IO。
"""
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.prompt_evolution.replay_calibration import (
    ReplayConsistencyReport,
    calibration_layer1_passed,
    compute_replay_consistency,
    replay_history_record,
    replay_history_records,
)
from app.services.prompt_evolution.review_verdict import (
    VERDICT_CONFIRMED_WIN,
    VERDICT_INFRASTRUCTURE_FAILURE,
    VERDICT_INVALIDATED_WIN,
    VERDICT_LOSS,
)


# ---------------------------------------------------------------------------
# compute_replay_consistency
# ---------------------------------------------------------------------------
def test_empty_report_is_zeroed():
    report = compute_replay_consistency([])
    assert isinstance(report, ReplayConsistencyReport)
    assert report.total == 0
    assert report.effective_total == 0
    assert report.sync_win_count == 0
    assert report.invalidation_rate == 0.0
    assert report.consistency_rate == 0.0


def test_report_counts_and_rates():
    verdicts = (
        [VERDICT_CONFIRMED_WIN] * 8
        + [VERDICT_INVALIDATED_WIN] * 2
        + [VERDICT_LOSS] * 5
        + [VERDICT_INFRASTRUCTURE_FAILURE] * 3
    )
    report = compute_replay_consistency(verdicts)
    assert report.total == 18
    # 有效样本排除 infrastructure_failure
    assert report.effective_total == 15
    assert report.confirmed_win_count == 8
    assert report.invalidated_win_count == 2
    assert report.sync_win_count == 10
    assert report.invalidation_rate == 0.2
    assert report.consistency_rate == 0.8
    assert report.verdict_counts[VERDICT_LOSS] == 5


# ---------------------------------------------------------------------------
# calibration_layer1_passed：≥200 有效样本 且 作废率 ≤5%
# ---------------------------------------------------------------------------
def test_calibration_passes_with_enough_samples_and_low_invalidation():
    verdicts = [VERDICT_CONFIRMED_WIN] * 195 + [VERDICT_INVALIDATED_WIN] * 5
    report = compute_replay_consistency(verdicts)
    assert report.invalidation_rate == 0.025
    assert calibration_layer1_passed(report) is True


def test_calibration_fails_with_insufficient_samples():
    verdicts = [VERDICT_CONFIRMED_WIN] * 100
    report = compute_replay_consistency(verdicts)
    assert calibration_layer1_passed(report) is False


def test_calibration_fails_when_invalidation_rate_too_high():
    verdicts = [VERDICT_CONFIRMED_WIN] * 189 + [VERDICT_INVALIDATED_WIN] * 11
    report = compute_replay_consistency(verdicts)
    assert report.invalidation_rate > 0.05
    assert calibration_layer1_passed(report) is False


def test_calibration_boundary_5_percent_passes():
    verdicts = [VERDICT_CONFIRMED_WIN] * 190 + [VERDICT_INVALIDATED_WIN] * 10
    report = compute_replay_consistency(verdicts)
    assert report.invalidation_rate == 0.05
    assert calibration_layer1_passed(report) is True


def test_calibration_infrastructure_failures_excluded_from_sample_count():
    # 190 有效胜场 + 大量基础设施失败，有效样本不足 200 → 不通过
    verdicts = [VERDICT_CONFIRMED_WIN] * 190 + [VERDICT_INFRASTRUCTURE_FAILURE] * 50
    report = compute_replay_consistency(verdicts)
    assert report.effective_total == 190
    assert calibration_layer1_passed(report) is False


# ---------------------------------------------------------------------------
# replay_history_record：单条历史 → verdict（复用 classify_verdict）
# ---------------------------------------------------------------------------
def _record(**overrides):
    base = dict(
        rewritten_ai_score=20.0,
        ai_threshold=50.0,
        detector_available=True,
        llm_review=dict(
            available=True,
            hard_fail=False,
            fidelity=91.0,
            fact=95.0,
            completeness=88.0,
            over_rewrite_risk="low",
            confidence=0.8,
        ),
    )
    base.update(overrides)
    return base


def test_replay_confirmed_win():
    # 同步 AI 门槛放行 + 异步合格 → confirmed_win
    assert replay_history_record(_record()) == VERDICT_CONFIRMED_WIN


def test_replay_invalidated_win():
    # 同步放行，但异步硬失败 → 判定器误放行
    rec = _record(llm_review=dict(available=True, hard_fail=True, fidelity=91.0, fact=95.0, completeness=88.0, over_rewrite_risk="low", confidence=0.8))
    assert replay_history_record(rec) == VERDICT_INVALIDATED_WIN


def test_replay_loss_when_ai_gate_fails():
    # AI 分高于阈值 → 同步不放行 → loss
    rec = _record(rewritten_ai_score=80.0, ai_threshold=50.0)
    assert replay_history_record(rec) == VERDICT_LOSS


def test_replay_infrastructure_failure_when_review_unavailable():
    rec = _record(llm_review=dict(available=False))
    assert replay_history_record(rec) == VERDICT_INFRASTRUCTURE_FAILURE


def test_replay_infrastructure_failure_when_detector_unavailable():
    rec = _record(detector_available=False)
    assert replay_history_record(rec) == VERDICT_INFRASTRUCTURE_FAILURE


def test_replay_loss_when_ai_score_missing():
    # 缺失分数无法判定同步放行 → 保守判未放行（loss）
    rec = _record(rewritten_ai_score=None)
    assert replay_history_record(rec) == VERDICT_LOSS


def test_replay_records_batch_matches_individual():
    records = [_record(), _record(rewritten_ai_score=80.0)]
    verdicts = replay_history_records(records)
    assert verdicts == [VERDICT_CONFIRMED_WIN, VERDICT_LOSS]
