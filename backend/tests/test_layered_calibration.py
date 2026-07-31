"""
四层校准测试（设计文档 §3.4 / §14 第 7 步）

覆盖两部分：
- 纯逻辑：按全局/题材/策略族/挑战者分组聚合 shadow 结算样本，逐层门槛判定，
  某挑战者四层全过 → 解锁（可推 eligible）。复用 replay_calibration.compute_replay_consistency。
- 编排：list_settlement_samples 联表取样本、update_serving_mode 合法转换、
  promote_calibrated_challengers 把四层全过的 shadow 挑战者推进到 eligible。
"""
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.models.prompt_experiment import (
    PromptChallenger,
    PromptExperiment,
    PromptExperimentBudget,
)
from app.services.prompt_evolution.challenger_repository import ChallengerRepository
from app.services.prompt_evolution.experiment_contract import (
    EXPERIMENT_EVALUATION_POLICY_VERSION,
    LIGHT_JUDGE_VERSION,
)
from app.services.prompt_evolution.experiment_repository import ExperimentRepository
from app.services.prompt_evolution.layered_calibration import (
    CalibrationSample,
    CalibrationThresholds,
    build_layered_calibration,
    challenger_unlocked,
    eligible_challenger_ids,
    promote_calibrated_challengers,
)
from app.services.prompt_evolution.review_verdict import (
    VERDICT_CONFIRMED_WIN,
    VERDICT_INFRASTRUCTURE_FAILURE,
    VERDICT_INVALIDATED_WIN,
    VERDICT_LOSS,
)


# ---------------------------------------------------------------------------
# 纯逻辑：分组聚合与逐层门槛
# ---------------------------------------------------------------------------

def _small_thresholds(**overrides):
    base = dict(
        layer1_min=5,
        layer2_min=3,
        layer3_min=2,
        layer4_min=2,
        max_invalidation_rate=0.05,
    )
    base.update(overrides)
    return CalibrationThresholds(**base)


def _samples(genre, family, challenger_id, *, confirmed=0, invalidated=0, loss=0, infra=0):
    out = []
    for verdict, n in (
        (VERDICT_CONFIRMED_WIN, confirmed),
        (VERDICT_INVALIDATED_WIN, invalidated),
        (VERDICT_LOSS, loss),
        (VERDICT_INFRASTRUCTURE_FAILURE, infra),
    ):
        out.extend(
            CalibrationSample(genre=genre, strategy_family=family, challenger_id=challenger_id, outcome=verdict)
            for _ in range(n)
        )
    return out


def test_build_groups_by_all_four_dimensions():
    samples = (
        _samples("玄幻", "sentence", "chg-a", confirmed=6)
        + _samples("言情", "vocab", "chg-b", confirmed=4)
    )
    report = build_layered_calibration(samples, _small_thresholds())

    assert report.layer1.report.effective_total == 10
    assert set(report.layer2) == {"玄幻", "言情"}
    assert set(report.layer3) == {"sentence", "vocab"}
    assert set(report.layer4) == {"chg-a", "chg-b"}
    assert report.layer2["玄幻"].report.effective_total == 6
    assert report.layer4["chg-b"].report.effective_total == 4


def test_layer_passes_when_samples_sufficient_and_rate_ok():
    samples = _samples("玄幻", "sentence", "chg-a", confirmed=6)
    report = build_layered_calibration(samples, _small_thresholds())
    assert report.layer1.passed is True
    assert report.layer2["玄幻"].passed is True
    assert report.layer3["sentence"].passed is True
    assert report.layer4["chg-a"].passed is True


def test_layer_fails_when_samples_insufficient():
    samples = _samples("玄幻", "sentence", "chg-a", confirmed=3)  # 全局 min=5
    report = build_layered_calibration(samples, _small_thresholds())
    assert report.layer1.passed is False


def test_infrastructure_failure_excluded_from_effective_total():
    samples = _samples("玄幻", "sentence", "chg-a", confirmed=5, infra=4)
    report = build_layered_calibration(samples, _small_thresholds())
    assert report.layer1.report.total == 9
    assert report.layer1.report.effective_total == 5
    assert report.layer1.passed is True


def test_layer_fails_when_invalidation_rate_exceeds_limit():
    # 5 confirmed + 5 invalidated → 作废率 0.5 > 0.05
    samples = _samples("玄幻", "sentence", "chg-a", confirmed=5, invalidated=5)
    report = build_layered_calibration(samples, _small_thresholds())
    assert report.layer1.report.invalidation_rate == pytest.approx(0.5)
    assert report.layer1.passed is False


def test_challenger_unlocked_requires_all_four_layers():
    samples = _samples("玄幻", "sentence", "chg-a", confirmed=6)
    report = build_layered_calibration(samples, _small_thresholds())
    assert challenger_unlocked(report, "chg-a") is True


def test_challenger_not_unlocked_when_genre_layer_fails():
    # chg-a 自身样本足够，但其题材总量因阈值抬高而不足
    samples = _samples("玄幻", "sentence", "chg-a", confirmed=6)
    report = build_layered_calibration(samples, _small_thresholds(layer2_min=100))
    assert report.layer4["chg-a"].passed is True
    assert report.layer2["玄幻"].passed is False
    assert challenger_unlocked(report, "chg-a") is False


def test_challenger_not_unlocked_when_own_samples_insufficient():
    # 全局/题材/策略族靠 chg-a 撑够，chg-b 自身样本不足 layer4
    samples = (
        _samples("玄幻", "sentence", "chg-a", confirmed=8)
        + _samples("玄幻", "sentence", "chg-b", confirmed=1)
    )
    report = build_layered_calibration(samples, _small_thresholds())
    assert report.layer1.passed is True
    assert report.layer4["chg-b"].passed is False
    assert challenger_unlocked(report, "chg-b") is False


def test_challenger_unlocked_false_for_unknown_challenger():
    samples = _samples("玄幻", "sentence", "chg-a", confirmed=6)
    report = build_layered_calibration(samples, _small_thresholds())
    assert challenger_unlocked(report, "chg-unknown") is False


def test_eligible_challenger_ids_returns_only_fully_passing():
    samples = (
        _samples("玄幻", "sentence", "chg-a", confirmed=8)
        + _samples("玄幻", "sentence", "chg-b", confirmed=1)
    )
    report = build_layered_calibration(samples, _small_thresholds())
    assert eligible_challenger_ids(report) == ["chg-a"]


def test_thresholds_from_env_defaults(monkeypatch):
    for key in (
        "CALIBRATION_MIN_SAMPLES_GLOBAL",
        "CALIBRATION_MIN_SAMPLES_GENRE",
        "CALIBRATION_MIN_SAMPLES_FAMILY",
        "CALIBRATION_MIN_SAMPLES_CHALLENGER",
        "EXPERIMENT_INVALIDATED_RATE_MAX",
    ):
        monkeypatch.delenv(key, raising=False)
    thresholds = CalibrationThresholds.from_env()
    assert thresholds.layer1_min == 200
    assert thresholds.layer2_min == 50
    assert thresholds.layer3_min == 30
    assert thresholds.layer4_min == 20
    assert thresholds.max_invalidation_rate == pytest.approx(0.05)


def test_thresholds_from_env_overrides(monkeypatch):
    monkeypatch.setenv("CALIBRATION_MIN_SAMPLES_GLOBAL", "120")
    monkeypatch.setenv("CALIBRATION_MIN_SAMPLES_CHALLENGER", "25")
    monkeypatch.setenv("EXPERIMENT_INVALIDATED_RATE_MAX", "0.03")
    thresholds = CalibrationThresholds.from_env()
    assert thresholds.layer1_min == 120
    assert thresholds.layer4_min == 25
    assert thresholds.max_invalidation_rate == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# 编排：仓储查询 + 状态推进
# ---------------------------------------------------------------------------

@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (PromptChallenger, PromptExperiment, PromptExperimentBudget):
        model.__table__.create(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield db
    finally:
        db.close()


def _seed_challenger(session, challenger_id, genre, family, *, serving_mode="shadow"):
    ChallengerRepository(session).upsert_challenger(
        challenger_id=challenger_id,
        genre=genre,
        prompt_text="改善句式结构",
        prompt_hash=f"sha256:{challenger_id}",
        strategy_desc="降低连续同构句比例",
        strategy_family=family,
        source_batch="batch_20260730_01",
        offline_gate_passed=True,
        offline_scores={},
        serving_mode=serving_mode,
    )


def _add_settled(session, *, challenger_id, genre, outcome, count,
                 policy=EXPERIMENT_EVALUATION_POLICY_VERSION, light=LIGHT_JUDGE_VERSION):
    for i in range(count):
        session.add(
            PromptExperiment(
                experiment_id=f"exp_{challenger_id}_{outcome}_{policy}_{i}",
                request_id=f"req_{challenger_id}_{outcome}_{policy}_{i}",
                challenger_id=challenger_id,
                genre=genre,
                status="settled",
                champion_id="champ-1",
                assignment_bucket=1,
                serving_mode="shadow",
                resolved_model_id="m1",
                model_selection_source="prompt_combination",
                prompt_version_id="v1",
                provider_parameters_hash="phash",
                light_judge_version=light,
                evaluation_policy_version=policy,
                champion_prompt_hash="chash",
                challenger_prompt_hash="ghash",
                outcome=outcome,
            )
        )
    session.flush()


def _add_nonsettled(session, *, challenger_id, genre, status, count):
    for i in range(count):
        session.add(
            PromptExperiment(
                experiment_id=f"exp_{challenger_id}_{status}_{i}",
                request_id=f"req_{challenger_id}_{status}_{i}",
                challenger_id=challenger_id,
                genre=genre,
                status=status,
                champion_id="champ-1",
                assignment_bucket=1,
                serving_mode="shadow",
                resolved_model_id="m1",
                model_selection_source="prompt_combination",
                prompt_version_id="v1",
                provider_parameters_hash="phash",
                light_judge_version=LIGHT_JUDGE_VERSION,
                evaluation_policy_version=EXPERIMENT_EVALUATION_POLICY_VERSION,
                champion_prompt_hash="chash",
                challenger_prompt_hash="ghash",
                outcome=None,
            )
        )
    session.flush()


def test_list_settlement_samples_joins_strategy_family(session):
    _seed_challenger(session, "chg-a", "玄幻", "sentence")
    _add_settled(session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_CONFIRMED_WIN, count=3)
    rows = ExperimentRepository(session).list_settlement_samples(EXPERIMENT_EVALUATION_POLICY_VERSION)
    assert len(rows) == 3
    genre, family, cid, outcome = rows[0]
    assert (genre, family, cid, outcome) == ("玄幻", "sentence", "chg-a", VERDICT_CONFIRMED_WIN)


def test_list_settlement_samples_excludes_nonsettled_and_wrong_version(session):
    _seed_challenger(session, "chg-a", "玄幻", "sentence")
    _add_settled(session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_CONFIRMED_WIN, count=2)
    _add_nonsettled(session, challenger_id="chg-a", genre="玄幻", status="pending", count=3)
    _add_nonsettled(session, challenger_id="chg-a", genre="玄幻", status="dead", count=1)
    _add_settled(session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_LOSS, count=2, policy="other-policy-v9")
    rows = ExperimentRepository(session).list_settlement_samples(EXPERIMENT_EVALUATION_POLICY_VERSION)
    assert len(rows) == 2  # 仅当前策略版本的 settled 行


def test_update_serving_mode_shadow_to_eligible(session):
    _seed_challenger(session, "chg-a", "玄幻", "sentence")
    repo = ChallengerRepository(session)
    row = repo.update_serving_mode("chg-a", "eligible")
    assert row.serving_mode == "eligible"
    assert row.state_changed_at is not None


def test_update_serving_mode_rejects_illegal_transition(session):
    _seed_challenger(session, "chg-a", "玄幻", "sentence")
    repo = ChallengerRepository(session)
    with pytest.raises(ValueError):
        repo.update_serving_mode("chg-a", "champion")  # shadow 不能直接跳到 champion


def test_promote_calibrated_challengers_promotes_fully_calibrated(session):
    _seed_challenger(session, "chg-a", "玄幻", "sentence")
    _seed_challenger(session, "chg-b", "言情", "vocab")
    # chg-a 四层全过（自身即撑起全局/题材/策略族）
    _add_settled(session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_CONFIRMED_WIN, count=8)
    # chg-b 样本不足，且题材单独不足
    _add_settled(session, challenger_id="chg-b", genre="言情", outcome=VERDICT_CONFIRMED_WIN, count=1)

    result = promote_calibrated_challengers(
        session,
        thresholds=_small_thresholds(),
        evaluation_policy_version=EXPERIMENT_EVALUATION_POLICY_VERSION,
    )
    assert result["promoted"] == ["chg-a"]

    repo = ChallengerRepository(session)
    assert repo.get_by_challenger_id("chg-a").serving_mode == "eligible"
    assert repo.get_by_challenger_id("chg-b").serving_mode == "shadow"


def test_promote_skips_challenger_not_in_shadow(session):
    # 已是 eligible 的挑战者即便四层全过也不重复推进（幂等）
    _seed_challenger(session, "chg-a", "玄幻", "sentence", serving_mode="eligible")
    _add_settled(session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_CONFIRMED_WIN, count=8)
    result = promote_calibrated_challengers(
        session,
        thresholds=_small_thresholds(),
        evaluation_policy_version=EXPERIMENT_EVALUATION_POLICY_VERSION,
    )
    assert result["promoted"] == []
    assert ChallengerRepository(session).get_by_challenger_id("chg-a").serving_mode == "eligible"
