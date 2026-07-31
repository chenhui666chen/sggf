"""
实验任务仓储测试（设计文档 §5.2 / §6.2 / §14 第 6 步）

覆盖 prompt_experiments 表的持久化契约：
- create_experiment    幂等 on (request_id, challenger_id, evaluation_policy_version)
- claim_next           按 (status, lease_until) 认领待处理任务，租约 + attempt_count 推进
- advance_status       可重入状态转换（仅当处于期望前态才推进，重复调用幂等空操作）
- record_settlement    写回四段结果并转 settled（终态）
- mark_dead            转 dead + last_error_code（不落原文）

纯持久化层：不接 Celery、不调外部 API、不碰 /ai-trace 请求路径。sqlite 内存库可测。
"""
import os
import sys
from datetime import datetime, timedelta
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

from app.models.prompt_experiment import PromptExperiment
from app.services.prompt_evolution.experiment_repository import ExperimentRepository


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PromptExperiment.__table__.create(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield db
    finally:
        db.close()


def _experiment_kwargs(**overrides):
    data = dict(
        experiment_id="exp_20260730_0001",
        request_id="req_abc",
        challenger_id="chg_玄幻_20260730_a1b2",
        genre="玄幻",
        champion_id="champion_玄幻_v3",
        assignment_bucket=4271,
        serving_mode="shadow",
        resolved_model_id="qwen-max",
        model_selection_source="prompt_combination",
        prompt_version_id="v3",
        provider_parameters_hash="ph_deadbeef",
        light_judge_version="v1",
        evaluation_policy_version="experiment-policy-v1",
        champion_prompt_hash="sha256:champ0001",
        challenger_prompt_hash="sha256:chal0001",
    )
    data.update(overrides)
    return data


# ============ create_experiment（幂等 on 结算键） ============

def test_create_experiment_inserts_pending_row(session):
    repo = ExperimentRepository(session)
    row = repo.create_experiment(**_experiment_kwargs())
    session.commit()
    assert row.id is not None
    assert row.status == "pending"
    assert row.attempt_count == 0
    assert row.lease_until is None
    assert session.query(PromptExperiment).count() == 1


def test_create_experiment_idempotent_on_settlement_key(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    # 相同 (request_id, challenger_id, evaluation_policy_version) 复评晚到重复创建不产生第二行
    row2 = repo.create_experiment(**_experiment_kwargs(experiment_id="exp_20260730_0001_dup"))
    session.commit()
    assert session.query(PromptExperiment).count() == 1
    # 返回既有行（沿用原 experiment_id）
    assert row2.experiment_id == "exp_20260730_0001"


def test_create_experiment_distinct_challenger_creates_row(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    repo.create_experiment(
        **_experiment_kwargs(
            experiment_id="exp_20260730_0002",
            challenger_id="chg_玄幻_20260730_c3d4",
            challenger_prompt_hash="sha256:chal0002",
        )
    )
    session.commit()
    assert session.query(PromptExperiment).count() == 2


def test_get_by_experiment_id(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    assert repo.get_by_experiment_id("exp_20260730_0001") is not None
    assert repo.get_by_experiment_id("exp_不存在") is None


# ============ claim_next（租约认领） ============

def test_claim_next_leases_pending_row(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    now = datetime(2026, 7, 30, 12, 0, 0)
    claimed = repo.claim_next(now=now, lease_seconds=120, limit=5)
    assert len(claimed) == 1
    row = claimed[0]
    assert row.attempt_count == 1
    assert row.lease_until == now + timedelta(seconds=120)
    assert row.started_at == now


def test_claim_next_skips_active_lease(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    now = datetime(2026, 7, 30, 12, 0, 0)
    repo.claim_next(now=now, lease_seconds=120)
    session.commit()
    # 租约未过期，第二次认领拿不到
    again = repo.claim_next(now=now + timedelta(seconds=60), lease_seconds=120)
    assert again == []


def test_claim_next_reclaims_expired_lease(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    now = datetime(2026, 7, 30, 12, 0, 0)
    repo.claim_next(now=now, lease_seconds=120)
    session.commit()
    # 租约过期后可重新认领（worker 崩溃恢复），attempt_count 递增
    reclaimed = repo.claim_next(now=now + timedelta(seconds=200), lease_seconds=120)
    assert len(reclaimed) == 1
    assert reclaimed[0].attempt_count == 2


def test_claim_next_ignores_settled(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    repo.record_settlement(
        "exp_20260730_0001",
        light_judge_result={"hard_fail": False},
        returned_variant="champion",
        async_review_result={},
        outcome="loss",
    )
    session.commit()
    now = datetime(2026, 7, 30, 12, 0, 0)
    assert repo.claim_next(now=now, lease_seconds=120) == []


# ============ advance_status（可重入状态转换） ============

def test_advance_status_transitions_from_expected(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    assert repo.advance_status("exp_20260730_0001", expected_status="pending", new_status="generating") is True
    assert repo.get_by_experiment_id("exp_20260730_0001").status == "generating"


def test_advance_status_noop_when_not_expected(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    repo.advance_status("exp_20260730_0001", expected_status="pending", new_status="generating")
    session.commit()
    # 重复以 pending 为前态推进 → 幂等空操作（已是 generating）
    assert repo.advance_status("exp_20260730_0001", expected_status="pending", new_status="generating") is False
    assert repo.get_by_experiment_id("exp_20260730_0001").status == "generating"


# ============ record_settlement / mark_dead ============

def test_record_settlement_writes_results_and_settles(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    row = repo.record_settlement(
        "exp_20260730_0001",
        light_judge_result={"hard_fail": False, "score_challenger": 78},
        returned_variant="challenger",
        async_review_result={"verdict": "confirmed_win"},
        outcome="confirmed_win",
        latency_ms={"champion": 42000, "challenger": 51000},
        cost={"generation": 0.012},
    )
    session.commit()
    assert row.status == "settled"
    assert row.outcome == "confirmed_win"
    assert row.returned_variant == "challenger"
    assert row.finished_at is not None
    assert row.async_review_result["verdict"] == "confirmed_win"


def test_mark_dead_sets_error_code(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    row = repo.mark_dead("exp_20260730_0001", last_error_code="max_retry_exceeded")
    session.commit()
    assert row.status == "dead"
    assert row.last_error_code == "max_retry_exceeded"
    assert row.finished_at is not None


# ============ champion_ai_score 落库与只读序列（§11.2 信号 3a） ============

def test_record_settlement_persists_champion_ai_score(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    row = repo.record_settlement(
        "exp_20260730_0001",
        light_judge_result={"hard_fail": False},
        returned_variant="champion",
        async_review_result={},
        outcome="loss",
        champion_ai_score=45.0,
    )
    session.commit()
    assert row.champion_ai_score == 45.0


def test_record_settlement_champion_ai_score_defaults_none(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    row = repo.record_settlement(
        "exp_20260730_0001",
        light_judge_result={"hard_fail": False},
        returned_variant="champion",
        async_review_result={},
        outcome="loss",
    )
    session.commit()
    assert row.champion_ai_score is None


def _settle_with_ai_score(repo, session, *, idx, score, genre="玄幻", policy="experiment-policy-v1"):
    """播种一条已结算实验并写入 champion_ai_score，finished_at 随 idx 递增。"""
    exp_id = f"exp_ai_{genre}_{idx}"
    repo.create_experiment(
        **_experiment_kwargs(
            experiment_id=exp_id,
            request_id=f"req_ai_{genre}_{idx}",
            challenger_id=f"chg_{genre}_{idx}",
            challenger_prompt_hash=f"sha256:chal{idx}",
            genre=genre,
            evaluation_policy_version=policy,
        )
    )
    repo.record_settlement(
        exp_id,
        light_judge_result={},
        returned_variant="challenger",
        async_review_result={},
        outcome="loss",
        champion_ai_score=score,
        finished_at=datetime(2026, 7, 20, 0, 0, 0) + timedelta(hours=idx),
    )


def test_list_champion_ai_scores_ordered_by_finished_at(session):
    repo = ExperimentRepository(session)
    _settle_with_ai_score(repo, session, idx=0, score=40.0)
    _settle_with_ai_score(repo, session, idx=1, score=55.0)
    session.commit()
    rows = repo.list_champion_ai_scores("玄幻", "experiment-policy-v1")
    assert len(rows) == 2
    assert rows[0][0] < rows[1][0]          # finished_at 升序
    assert rows[0][1] == 40.0
    assert rows[1][1] == 55.0


def test_list_champion_ai_scores_skips_null(session):
    repo = ExperimentRepository(session)
    _settle_with_ai_score(repo, session, idx=0, score=40.0)
    _settle_with_ai_score(repo, session, idx=1, score=None)  # 未落分 → 应被排除
    session.commit()
    rows = repo.list_champion_ai_scores("玄幻", "experiment-policy-v1")
    assert [r[1] for r in rows] == [40.0]


def test_list_champion_ai_scores_filters_genre_and_policy(session):
    repo = ExperimentRepository(session)
    _settle_with_ai_score(repo, session, idx=0, score=40.0, genre="都市")
    session.commit()
    assert repo.list_champion_ai_scores("玄幻", "experiment-policy-v1") == []
    assert repo.list_champion_ai_scores("都市", "other-policy") == []


# ============ 终态保护（settled / dead 不可覆写） ============

def test_record_settlement_noop_when_already_settled(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    repo.record_settlement(
        "exp_20260730_0001",
        light_judge_result={"hard_fail": False},
        returned_variant="champion",
        async_review_result={"verdict": "loss"},
        outcome="loss",
    )
    session.commit()
    # 晚到的重复结算不得覆盖已落定的 outcome
    row = repo.record_settlement(
        "exp_20260730_0001",
        light_judge_result={"hard_fail": False},
        returned_variant="challenger",
        async_review_result={"verdict": "confirmed_win"},
        outcome="confirmed_win",
    )
    session.commit()
    assert row.status == "settled"
    assert row.outcome == "loss"
    assert row.returned_variant == "champion"


def test_mark_dead_does_not_override_settled(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    repo.record_settlement(
        "exp_20260730_0001",
        light_judge_result={"hard_fail": False},
        returned_variant="champion",
        async_review_result={},
        outcome="loss",
    )
    session.commit()
    # 晚到的重试失败不得把已结算实验改判 dead
    row = repo.mark_dead("exp_20260730_0001", last_error_code="max_retry_exceeded")
    session.commit()
    assert row.status == "settled"
    assert row.last_error_code is None


def test_record_settlement_noop_when_dead(session):
    repo = ExperimentRepository(session)
    repo.create_experiment(**_experiment_kwargs())
    session.commit()
    repo.mark_dead("exp_20260730_0001", last_error_code="payload_expired")
    session.commit()
    row = repo.record_settlement(
        "exp_20260730_0001",
        light_judge_result={"hard_fail": False},
        returned_variant="champion",
        async_review_result={},
        outcome="loss",
    )
    session.commit()
    assert row.status == "dead"
    assert row.outcome is None
