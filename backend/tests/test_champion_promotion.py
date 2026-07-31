"""
冠军原子切换 + 回滚 + 按挑战者聚合（设计文档 §8.3 · §14 第 9 步 · 子块 B）

覆盖：
- ChampionAssignmentRepository：当前指针查询 / 原子切换（关旧+开新）/ 历史；
- ExperimentRepository.list_outcomes_for_challenger：按挑战者取 verdict 序列；
- champion_promotion.promote_champion / rollback_champion：硬闸门把关 + 原子指针 +
  serving_mode 推进（returnable→champion / champion→suspended）。
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
    PromptChampionAssignment,
    PromptExperiment,
)
from app.services.prompt_evolution.challenger_repository import ChallengerRepository
from app.services.prompt_evolution.champion_assignment_repository import (
    ChampionAssignmentRepository,
)
from app.services.prompt_evolution.champion_promotion import (
    promote_champion,
    rollback_champion,
)
from app.services.prompt_evolution.experiment_repository import ExperimentRepository
from app.services.prompt_evolution.review_verdict import (
    VERDICT_CONFIRMED_WIN,
    VERDICT_LOSS,
)

POLICY = "experiment-policy-v1"
GENRE = "玄幻"


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    PromptChallenger.__table__.create(bind=engine)
    PromptExperiment.__table__.create(bind=engine)
    PromptChampionAssignment.__table__.create(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield db
    finally:
        db.close()


def _seed_challenger(session, challenger_id, *, serving_mode="returnable", genre=GENRE):
    chal_repo = ChallengerRepository(session)
    row = chal_repo.upsert_challenger(
        challenger_id=challenger_id,
        genre=genre,
        prompt_text="改写提示词全文",
        prompt_hash=f"sha256:{challenger_id}",
        strategy_desc="降低连续同构句比例",
        strategy_family="sentence_structure",
        source_batch="evolution_20260730_01",
        offline_gate_passed=True,
        offline_scores={},
        serving_mode="shadow",
    )
    # 直接置目标状态（绕过状态机，仅测试用初值）
    row.serving_mode = serving_mode
    session.flush()
    return row


def _seed_outcomes(session, challenger_id, *, confirmed=0, loss=0, genre=GENRE, policy=POLICY):
    exp_repo = ExperimentRepository(session)
    specs = [(VERDICT_CONFIRMED_WIN, confirmed), (VERDICT_LOSS, loss)]
    idx = 0
    for outcome, count in specs:
        for _ in range(count):
            exp_id = f"exp_{challenger_id}_{idx}"
            exp_repo.create_experiment(
                experiment_id=exp_id,
                request_id=f"req_{challenger_id}_{idx}",
                challenger_id=challenger_id,
                genre=genre,
                champion_id="champ",
                assignment_bucket=1,
                serving_mode="returnable",
                resolved_model_id="m1",
                model_selection_source="prompt_combination",
                prompt_version_id="pv1",
                provider_parameters_hash="ph1",
                light_judge_version="lj-v1",
                evaluation_policy_version=policy,
                champion_prompt_hash="cph",
                challenger_prompt_hash="chph",
            )
            exp_repo.record_settlement(
                exp_id,
                light_judge_result={},
                returned_variant="challenger",
                async_review_result={},
                outcome=outcome,
            )
            idx += 1
    session.flush()


# ---------------- ChampionAssignmentRepository ----------------

def test_switch_creates_current_pointer(session):
    repo = ChampionAssignmentRepository(session)
    new = repo.switch_champion(
        GENRE, prompt_version_id="v1", prompt_hash="h1", operator="admin-1", reason="初始"
    )
    session.commit()
    assert new.effective_until is None
    current = repo.get_current(GENRE)
    assert current.prompt_version_id == "v1"
    assert current.previous_version_id is None


def test_switch_closes_old_and_chains_previous(session):
    repo = ChampionAssignmentRepository(session)
    repo.switch_champion(GENRE, prompt_version_id="v1", prompt_hash="h1")
    session.commit()
    repo.switch_champion(GENRE, prompt_version_id="v2", prompt_hash="h2", operator="admin-1")
    session.commit()

    current = repo.get_current(GENRE)
    assert current.prompt_version_id == "v2"
    assert current.previous_version_id == "v1"
    # 只有一条当前指针
    all_rows = repo.list_history(GENRE)
    assert len(all_rows) == 2
    open_rows = [r for r in all_rows if r.effective_until is None]
    assert len(open_rows) == 1


def test_get_current_none_when_empty(session):
    repo = ChampionAssignmentRepository(session)
    assert repo.get_current(GENRE) is None


def test_switch_genre_isolated(session):
    repo = ChampionAssignmentRepository(session)
    repo.switch_champion(GENRE, prompt_version_id="v1", prompt_hash="h1")
    repo.switch_champion("言情", prompt_version_id="rv1", prompt_hash="rh1")
    session.commit()
    assert repo.get_current(GENRE).prompt_version_id == "v1"
    assert repo.get_current("言情").prompt_version_id == "rv1"


# ---------------- ExperimentRepository.list_outcomes_for_challenger ----------------

def test_list_outcomes_for_challenger_filters(session):
    _seed_outcomes(session, "chg_a", confirmed=3, loss=2)
    _seed_outcomes(session, "chg_b", confirmed=1, loss=0)
    exp_repo = ExperimentRepository(session)
    outcomes = exp_repo.list_outcomes_for_challenger("chg_a", POLICY)
    assert len(outcomes) == 5
    assert outcomes.count(VERDICT_CONFIRMED_WIN) == 3
    assert outcomes.count(VERDICT_LOSS) == 2
    # 不同策略版本不聚合
    assert exp_repo.list_outcomes_for_challenger("chg_a", "other-policy") == []


# ---------------- promote_champion ----------------

def test_promote_champion_happy_path(session):
    _seed_challenger(session, "chg_win", serving_mode="returnable")
    _seed_outcomes(session, "chg_win", confirmed=70, loss=30)
    session.commit()

    result = promote_champion(
        session,
        genre=GENRE,
        challenger_id="chg_win",
        evaluation_policy_version=POLICY,
        operator="admin-1",
        offline_gate_passed=True,
    )
    assert result.promoted is True
    assert result.gate_result.hard_gate_passed is True
    # 指针切到该挑战者
    current = ChampionAssignmentRepository(session).get_current(GENRE)
    assert current.prompt_version_id == "chg_win"
    assert current.gate_overridden is False
    # serving_mode 推进到 champion
    chal = ChallengerRepository(session).get_by_challenger_id("chg_win")
    assert chal.serving_mode == "champion"


def test_promote_demotes_previous_champion_challenger(session):
    # 先有一个冠军挑战者
    _seed_challenger(session, "chg_old", serving_mode="champion")
    ChampionAssignmentRepository(session).switch_champion(
        GENRE, prompt_version_id="chg_old", prompt_hash="sha256:chg_old"
    )
    session.commit()
    # 新挑战者晋升
    _seed_challenger(session, "chg_new", serving_mode="returnable")
    _seed_outcomes(session, "chg_new", confirmed=70, loss=30)
    session.commit()

    result = promote_champion(
        session,
        genre=GENRE,
        challenger_id="chg_new",
        evaluation_policy_version=POLICY,
        operator="admin-1",
        offline_gate_passed=True,
    )
    assert result.promoted is True
    old = ChallengerRepository(session).get_by_challenger_id("chg_old")
    assert old.serving_mode == "suspended"  # 旧冠军降级保留可回滚
    current = ChampionAssignmentRepository(session).get_current(GENRE)
    assert current.previous_version_id == "chg_old"


def test_promote_rejected_when_hard_gate_fails(session):
    _seed_challenger(session, "chg_small", serving_mode="returnable")
    _seed_outcomes(session, "chg_small", confirmed=7, loss=3)  # 有效样本 10 < 100
    session.commit()

    result = promote_champion(
        session,
        genre=GENRE,
        challenger_id="chg_small",
        evaluation_policy_version=POLICY,
        operator="admin-1",
        offline_gate_passed=True,
    )
    assert result.promoted is False
    assert "min_effective_samples" in result.gate_result.hard_gate_failures
    # 指针未变，serving_mode 未变
    assert ChampionAssignmentRepository(session).get_current(GENRE) is None
    assert ChallengerRepository(session).get_by_challenger_id("chg_small").serving_mode == "returnable"


def test_promote_with_gate_override_records_reason(session):
    _seed_challenger(session, "chg_small", serving_mode="returnable")
    _seed_outcomes(session, "chg_small", confirmed=7, loss=3)
    session.commit()

    result = promote_champion(
        session,
        genre=GENRE,
        challenger_id="chg_small",
        evaluation_policy_version=POLICY,
        operator="admin-1",
        offline_gate_passed=True,
        gate_override=True,
        override_reason="人工确认小流量提前上线",
    )
    assert result.promoted is True
    current = ChampionAssignmentRepository(session).get_current(GENRE)
    assert current.gate_overridden is True
    assert current.override_reason == "人工确认小流量提前上线"


def test_promote_override_without_reason_raises(session):
    _seed_challenger(session, "chg_small", serving_mode="returnable")
    _seed_outcomes(session, "chg_small", confirmed=7, loss=3)
    session.commit()
    with pytest.raises(ValueError):
        promote_champion(
            session,
            genre=GENRE,
            challenger_id="chg_small",
            evaluation_policy_version=POLICY,
            operator="admin-1",
            offline_gate_passed=True,
            gate_override=True,
        )


def test_promote_rejected_when_not_returnable(session):
    _seed_challenger(session, "chg_elig", serving_mode="eligible")
    _seed_outcomes(session, "chg_elig", confirmed=70, loss=30)
    session.commit()
    result = promote_champion(
        session,
        genre=GENRE,
        challenger_id="chg_elig",
        evaluation_policy_version=POLICY,
        operator="admin-1",
        offline_gate_passed=True,
    )
    assert result.promoted is False
    assert result.reason == "not_returnable"


# ---------------- rollback_champion ----------------

def test_rollback_repoints_to_target(session):
    repo = ChampionAssignmentRepository(session)
    repo.switch_champion(GENRE, prompt_version_id="v1", prompt_hash="h1")
    session.commit()
    repo.switch_champion(GENRE, prompt_version_id="v2", prompt_hash="h2")
    session.commit()

    result = rollback_champion(
        session, genre=GENRE, target_version_id="v1", operator="admin-1", reason="v2 退化"
    )
    assert result.success is True
    current = repo.get_current(GENRE)
    assert current.prompt_version_id == "v1"
    assert current.previous_version_id == "v2"


def test_rollback_target_not_found(session):
    repo = ChampionAssignmentRepository(session)
    repo.switch_champion(GENRE, prompt_version_id="v2", prompt_hash="h2")
    session.commit()
    result = rollback_champion(
        session, genre=GENRE, target_version_id="v_missing", operator="admin-1", reason="x"
    )
    assert result.success is False
    assert result.reason == "target_not_found"
