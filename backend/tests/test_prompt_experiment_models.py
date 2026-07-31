"""
在线实验持久化底座测试（设计文档 §6：四张表 + 关键约束）
"""
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
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
    PromptExperimentBudget,
)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PromptChallenger.__table__.create(bind=engine)
    PromptExperiment.__table__.create(bind=engine)
    PromptExperimentBudget.__table__.create(bind=engine)
    PromptChampionAssignment.__table__.create(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield db
    finally:
        db.close()


def _make_challenger(**overrides) -> PromptChallenger:
    data = dict(
        challenger_id="chg_玄幻_20260730_a1b2",
        genre="玄幻",
        prompt_text="改写提示词全文",
        prompt_hash="sha256:abc",
        strategy_desc="降低连续同构句比例",
        strategy_family="sentence_structure",
        source_batch="evolution_20260730_01",
    )
    data.update(overrides)
    return PromptChallenger(**data)


def _make_experiment(**overrides) -> PromptExperiment:
    data = dict(
        experiment_id="exp_0001",
        request_id="req_0001",
        challenger_id="chg_玄幻_20260730_a1b2",
        genre="玄幻",
        champion_id="v_20260701",
        assignment_bucket=4271,
        serving_mode="shadow",
        resolved_model_id="deepseek-v3",
        model_selection_source="prompt_combination",
        prompt_version_id="v_20260701",
        provider_parameters_hash="ab12cd34ef56ab12",
        light_judge_version="light-judge-v1",
        evaluation_policy_version="experiment-policy-v1",
        champion_prompt_hash="sha256:champ",
        challenger_prompt_hash="sha256:chall",
    )
    data.update(overrides)
    return PromptExperiment(**data)


# ============ prompt_challengers ============

def test_challenger_defaults(session):
    session.add(_make_challenger())
    session.commit()
    row = session.query(PromptChallenger).one()
    assert row.serving_mode == "shadow"
    assert row.offline_gate_passed is False
    assert row.offline_scores == {}
    assert row.created_at is not None


def test_challenger_id_unique(session):
    session.add(_make_challenger())
    session.commit()
    session.add(_make_challenger(genre="都市"))
    with pytest.raises(IntegrityError):
        session.commit()


# ============ prompt_experiments ============

def test_experiment_task_defaults(session):
    session.add(_make_experiment())
    session.commit()
    row = session.query(PromptExperiment).one()
    assert row.status == "pending"
    assert row.attempt_count == 0
    assert row.outcome is None
    assert row.payload_ref is None


def test_experiment_settlement_unique_constraint(session):
    """(request_id, challenger_id, evaluation_policy_version) 唯一——防复评晚到重复结算"""
    session.add(_make_experiment())
    session.commit()
    session.add(_make_experiment(experiment_id="exp_0002"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_experiment_new_policy_version_opens_new_window(session):
    session.add(_make_experiment())
    session.commit()
    session.add(
        _make_experiment(
            experiment_id="exp_0002",
            evaluation_policy_version="experiment-policy-v2",
        )
    )
    session.commit()
    assert session.query(PromptExperiment).count() == 2


def test_experiment_stores_opaque_payload_ref_only(session):
    """任务行只允许携带 opaque payload reference，无原文列"""
    columns = {c.name for c in PromptExperiment.__table__.columns}
    assert "payload_ref" in columns
    assert "payload_expires_at" in columns
    for forbidden in ("original_text", "text", "payload_text"):
        assert forbidden not in columns


def test_experiment_champion_ai_score_column_nullable_defaults_none(session):
    """冠军原始 AI 检测分列（§11.2 champion_ai_score_rise 信号 3a）：可空、默认 None"""
    column = PromptExperiment.__table__.columns["champion_ai_score"]
    assert column.nullable is True
    session.add(_make_experiment())
    session.commit()
    row = session.query(PromptExperiment).one()
    assert row.champion_ai_score is None


# ============ prompt_experiment_budgets ============

def test_budget_scope_unique(session):
    session.add(
        PromptExperimentBudget(budget_date="2026-07-30", scope="genre", scope_key="玄幻")
    )
    session.commit()
    session.add(
        PromptExperimentBudget(budget_date="2026-07-30", scope="genre", scope_key="玄幻")
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_budget_counters_default_zero(session):
    session.add(PromptExperimentBudget(budget_date="2026-07-30", scope="global", scope_key=""))
    session.commit()
    row = session.query(PromptExperimentBudget).one()
    assert row.calls_used == 0
    assert row.cost_used == 0.0
    assert row.reserved_cost == 0.0


# ============ prompt_champion_assignments ============

def test_assignment_current_pointer_lookup(session):
    session.add(
        PromptChampionAssignment(
            genre="玄幻",
            prompt_version_id="v_old",
            prompt_hash="sha256:old",
        )
    )
    session.commit()
    # 切换：旧行关闭区间，新行 effective_until 为空 = 当前指针
    old = session.query(PromptChampionAssignment).one()
    from datetime import datetime, timezone

    old.effective_until = datetime.now(timezone.utc)
    session.add(
        PromptChampionAssignment(
            genre="玄幻",
            prompt_version_id="v_new",
            prompt_hash="sha256:new",
            previous_version_id="v_old",
            operator="admin-1",
        )
    )
    session.commit()

    current = (
        session.query(PromptChampionAssignment)
        .filter(
            PromptChampionAssignment.genre == "玄幻",
            PromptChampionAssignment.effective_until.is_(None),
        )
        .one()
    )
    assert current.prompt_version_id == "v_new"
    assert current.previous_version_id == "v_old"


def test_assignment_gate_override_defaults(session):
    session.add(
        PromptChampionAssignment(genre="玄幻", prompt_version_id="v1", prompt_hash="h1")
    )
    session.commit()
    row = session.query(PromptChampionAssignment).one()
    assert row.gate_overridden is False
    assert row.override_reason is None
