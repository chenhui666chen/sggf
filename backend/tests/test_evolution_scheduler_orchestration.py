"""
进化调度编排：信号采集 + 状态落盘 + tick 编排（设计文档 §11 · §14 第 10 步 · 子块 B）

把子块 A 的纯逻辑（evolution_scheduler）接入真实数据源。测试分三层：
1. SchedulerStateStore：三态落盘（tmp_path，实例间持久化）；
2. 信号采集纯/DB 函数：跨批次提升序列 + 挑战者反超 Wilson 下界（sqlite）；
3. run_scheduler_tick：三态转移编排 + 落盘（sqlite + 注入中性信号）。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for _path in (BACKEND_ROOT, PROJECT_ROOT):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.models.prompt_experiment import PromptChallenger, PromptExperiment
from app.services.prompt_evolution.challenger_repository import ChallengerRepository
from app.services.prompt_evolution.evolution_scheduler import (
    STATE_AWAKE,
    STATE_RUNNING,
    STATE_SLEEPING,
)
from app.services.prompt_evolution.experiment_repository import ExperimentRepository
from app.services.prompt_evolution.review_verdict import (
    VERDICT_CONFIRMED_WIN,
    VERDICT_LOSS,
)
from app.services.prompt_evolution.scheduler_orchestration import (
    DEFAULT_FIDELITY_WINDOW,
    SchedulerTickDeps,
    compute_best_challenger_wilson_lower_bound,
    compute_champion_ai_score_rise,
    compute_champion_fidelity_drop,
    compute_recent_improvements,
    is_genre_converged,
    run_scheduler_tick,
)
from app.services.prompt_evolution.scheduler_state import (
    SchedulerStateRecord,
    SchedulerStateStore,
)

POLICY = "experiment-policy-v1"
GENRE = "玄幻"


# ---------------- SchedulerStateStore（三态落盘） ----------------

def test_state_store_defaults_to_running(tmp_path):
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    record = store.get(GENRE)
    assert isinstance(record, SchedulerStateRecord)
    assert record.state == STATE_RUNNING
    assert record.genre == GENRE


def test_state_store_set_and_get_round_trip(tmp_path):
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_SLEEPING, reasons=["budget_exhausted"], now="2026-07-25T00:00:00+00:00")
    record = store.get(GENRE)
    assert record.state == STATE_SLEEPING
    assert record.reasons == ["budget_exhausted"]
    assert record.updated_at == "2026-07-25T00:00:00+00:00"


def test_state_store_persists_across_instances(tmp_path):
    SchedulerStateStore(storage_dir=str(tmp_path)).set(
        GENRE, STATE_AWAKE, reasons=["challenger_overtook"], now="2026-07-25T01:00:00+00:00"
    )
    reopened = SchedulerStateStore(storage_dir=str(tmp_path))
    assert reopened.get(GENRE).state == STATE_AWAKE


def test_state_store_snapshot_lists_all_genres(tmp_path):
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set("玄幻", STATE_SLEEPING, reasons=[], now="2026-07-25T00:00:00+00:00")
    store.set("都市", STATE_RUNNING, reasons=[], now="2026-07-25T00:00:00+00:00")
    snapshot = store.snapshot()
    assert set(snapshot.keys()) == {"玄幻", "都市"}
    assert snapshot["玄幻"].state == STATE_SLEEPING


def test_state_store_touch_updates_last_tick(tmp_path):
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_RUNNING, reasons=[], now="2026-07-25T00:00:00+00:00")
    store.touch(GENRE, now="2026-07-25T02:00:00+00:00")
    record = store.get(GENRE)
    assert record.state == STATE_RUNNING           # touch 不改状态
    assert record.last_tick_at == "2026-07-25T02:00:00+00:00"


# ---------------- compute_recent_improvements（跨批次提升序列） ----------------

def _summary(evolution_id, genre, status, best_score, started_at):
    return {
        "evolution_id": evolution_id,
        "genre": genre,
        "status": status,
        "best_score": best_score,
        "started_at": started_at,
    }


def test_recent_improvements_computes_consecutive_drops():
    # 综合分越低越好：10→8→7→6.5，相邻提升 = 前 - 后 = [2, 1, 0.5]
    summaries = [
        _summary("e1", GENRE, "completed", 10.0, "2026-07-20T00:00:00"),
        _summary("e2", GENRE, "completed", 8.0, "2026-07-21T00:00:00"),
        _summary("e3", GENRE, "completed", 7.0, "2026-07-22T00:00:00"),
        _summary("e4", GENRE, "completed", 6.5, "2026-07-23T00:00:00"),
    ]
    result = compute_recent_improvements(summaries, GENRE, limit=3)
    assert result == pytest.approx([2.0, 1.0, 0.5])


def test_recent_improvements_filters_genre_and_status():
    summaries = [
        _summary("e1", GENRE, "completed", 10.0, "2026-07-20T00:00:00"),
        _summary("d1", "都市", "completed", 5.0, "2026-07-20T12:00:00"),  # 异题材，排除
        _summary("e2", GENRE, "running", 3.0, "2026-07-21T00:00:00"),     # 未完成，排除
        _summary("e3", GENRE, "completed", 8.0, "2026-07-22T00:00:00"),
    ]
    result = compute_recent_improvements(summaries, GENRE, limit=5)
    assert result == pytest.approx([2.0])  # 仅 e1→e3


def test_recent_improvements_limit_truncates_to_latest():
    summaries = [
        _summary("e1", GENRE, "completed", 10.0, "2026-07-20T00:00:00"),
        _summary("e2", GENRE, "completed", 9.0, "2026-07-21T00:00:00"),
        _summary("e3", GENRE, "completed", 8.0, "2026-07-22T00:00:00"),
        _summary("e4", GENRE, "completed", 7.0, "2026-07-23T00:00:00"),
    ]
    result = compute_recent_improvements(summaries, GENRE, limit=2)
    assert result == pytest.approx([1.0, 1.0])  # 仅最近两批提升


def test_recent_improvements_empty_when_insufficient():
    summaries = [_summary("e1", GENRE, "completed", 10.0, "2026-07-20T00:00:00")]
    assert compute_recent_improvements(summaries, GENRE, limit=3) == []


# ---------------- compute_best_challenger_wilson_lower_bound（反超信号） ----------------

def _build_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    PromptChallenger.__table__.create(bind=engine)
    PromptExperiment.__table__.create(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _seed_challenger(session_local, challenger_id, *, serving_mode="returnable", genre=GENRE):
    db = session_local()
    try:
        repo = ChallengerRepository(db)
        repo.upsert_challenger(
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
        repo.get_by_challenger_id(challenger_id).serving_mode = serving_mode
        db.commit()
    finally:
        db.close()


def _seed_outcomes(session_local, challenger_id, *, confirmed=0, loss=0, genre=GENRE, policy=POLICY):
    db = session_local()
    try:
        exp_repo = ExperimentRepository(db)
        idx = 0
        for outcome, count in [(VERDICT_CONFIRMED_WIN, confirmed), (VERDICT_LOSS, loss)]:
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
        db.commit()
    finally:
        db.close()


def test_best_challenger_wilson_zero_when_no_returnable():
    session_local = _build_db()
    db = session_local()
    try:
        assert compute_best_challenger_wilson_lower_bound(
            db, GENRE, policy=POLICY
        ) == pytest.approx(0.0)
    finally:
        db.close()


def test_best_challenger_wilson_takes_max_over_returnable():
    session_local = _build_db()
    _seed_challenger(session_local, "chal_strong", serving_mode="returnable")
    _seed_outcomes(session_local, "chal_strong", confirmed=90, loss=10)
    _seed_challenger(session_local, "chal_weak", serving_mode="returnable")
    _seed_outcomes(session_local, "chal_weak", confirmed=60, loss=40)
    db = session_local()
    try:
        value = compute_best_challenger_wilson_lower_bound(db, GENRE, policy=POLICY)
        # 90/100 Wilson 下界 ≈ 0.826，取最大
        assert value == pytest.approx(0.826, abs=1e-2)
    finally:
        db.close()


def test_best_challenger_wilson_ignores_non_returnable():
    session_local = _build_db()
    _seed_challenger(session_local, "chal_shadow", serving_mode="shadow")
    _seed_outcomes(session_local, "chal_shadow", confirmed=90, loss=10)
    db = session_local()
    try:
        # shadow 挑战者不计入反超（只看 returnable）
        assert compute_best_challenger_wilson_lower_bound(db, GENRE, policy=POLICY) == pytest.approx(0.0)
    finally:
        db.close()


# ---------------- run_scheduler_tick（三态转移编排 + 落盘） ----------------

def _quiet_deps(**overrides):
    """默认全中性信号：不休眠、不唤醒。"""
    base = dict(
        list_history_summaries=lambda: [],
        is_budget_exhausted=lambda g: False,
    )
    base.update(overrides)
    return SchedulerTickDeps(**base)


def test_tick_running_stays_running_when_quiet(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE], deps=_quiet_deps(), state_store=store, policy=POLICY,
            now="2026-07-25T00:00:00+00:00",
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_RUNNING
    assert result[GENRE]["changed"] is False
    assert store.get(GENRE).state == STATE_RUNNING


def test_tick_running_to_sleeping_on_budget_exhausted(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE],
            deps=_quiet_deps(is_budget_exhausted=lambda g: True),
            state_store=store, policy=POLICY, now="2026-07-25T00:00:00+00:00",
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_SLEEPING
    assert result[GENRE]["changed"] is True
    assert "budget_exhausted" in result[GENRE]["reasons"]
    assert store.get(GENRE).state == STATE_SLEEPING


def test_tick_sleeping_to_awake_on_challenger_overtook(tmp_path):
    session_local = _build_db()
    _seed_challenger(session_local, "chal_strong", serving_mode="returnable")
    _seed_outcomes(session_local, "chal_strong", confirmed=90, loss=10)
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_SLEEPING, reasons=["budget_exhausted"], now="2026-07-25T00:00:00+00:00")
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE], deps=_quiet_deps(), state_store=store, policy=POLICY,
            now="2026-07-25T03:00:00+00:00",
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_AWAKE
    assert result[GENRE]["changed"] is True
    assert "challenger_overtook" in result[GENRE]["reasons"]
    assert store.get(GENRE).state == STATE_AWAKE


def test_tick_awake_transitions_to_running(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_AWAKE, reasons=["challenger_overtook"], now="2026-07-25T00:00:00+00:00")
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE], deps=_quiet_deps(), state_store=store, policy=POLICY,
            now="2026-07-25T04:00:00+00:00",
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_RUNNING
    assert result[GENRE]["changed"] is True
    assert store.get(GENRE).state == STATE_RUNNING


def test_tick_multi_genre_independent(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, ["玄幻", "都市"],
            deps=_quiet_deps(is_budget_exhausted=lambda g: g == "玄幻"),
            state_store=store, policy=POLICY, now="2026-07-25T00:00:00+00:00",
        )
    finally:
        db.close()
    assert result["玄幻"]["to"] == STATE_SLEEPING
    assert result["都市"]["to"] == STATE_RUNNING


def test_tick_touches_last_tick_when_unchanged(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_RUNNING, reasons=[], now="2026-07-25T00:00:00+00:00")
    db = session_local()
    try:
        run_scheduler_tick(
            db, [GENRE], deps=_quiet_deps(), state_store=store, policy=POLICY,
            now="2026-07-25T05:00:00+00:00",
        )
    finally:
        db.close()
    assert store.get(GENRE).last_tick_at == "2026-07-25T05:00:00+00:00"


# ---------------- is_genre_converged（综合分达标，信号 1 接真实源） ----------------

def _ct_summary(evolution_id, genre, status, best_score, target_score, started_at):
    return {
        "evolution_id": evolution_id,
        "genre": genre,
        "status": status,
        "best_score": best_score,
        "target_score": target_score,
        "started_at": started_at,
    }


def test_converged_true_when_latest_batch_meets_target():
    # 综合分越低越好：最新完成批次 best_score(10) ≤ target_score(10) → 达标
    summaries = [
        _ct_summary("e1", GENRE, "completed", 20.0, 10.0, "2026-07-20T00:00:00"),
        _ct_summary("e2", GENRE, "completed", 10.0, 10.0, "2026-07-22T00:00:00"),
    ]
    assert is_genre_converged(summaries, GENRE) is True


def test_converged_false_when_latest_batch_above_target():
    # 最新完成批次 best_score(11) > target_score(10) → 未达标（即便更早批次曾达标）
    summaries = [
        _ct_summary("e1", GENRE, "completed", 9.0, 10.0, "2026-07-20T00:00:00"),
        _ct_summary("e2", GENRE, "completed", 11.0, 10.0, "2026-07-22T00:00:00"),
    ]
    assert is_genre_converged(summaries, GENRE) is False


def test_converged_filters_genre_and_status():
    # 只看本题材 completed 批次；异题材已达标 / 本题材 running 均不参与判定
    summaries = [
        _ct_summary("d1", "都市", "completed", 5.0, 10.0, "2026-07-23T00:00:00"),
        _ct_summary("e1", GENRE, "running", 5.0, 10.0, "2026-07-24T00:00:00"),
        _ct_summary("e2", GENRE, "completed", 12.0, 10.0, "2026-07-22T00:00:00"),
    ]
    assert is_genre_converged(summaries, GENRE) is False


def test_converged_false_when_no_qualified_batch():
    assert is_genre_converged([], GENRE) is False
    # best_score 或 target_score 缺失的批次不参与
    summaries = [_ct_summary("e1", GENRE, "completed", None, 10.0, "2026-07-20T00:00:00")]
    assert is_genre_converged(summaries, GENRE) is False


# ---------------- list_champion_reviews / compute_champion_fidelity_drop（信号 3b 接真实源） ----------------

def _seed_champion_reviews(session_local, values, *, genre=GENRE, policy=POLICY, available=True):
    """
    按给定 (semantic_fidelity, fact_consistency) 序列播种已结算实验的 champion 异步复评，
    finished_at 随 idx 递增（升序）。values 中元素为 None 表示 champion 不可用（应被跳过）。
    """
    db = session_local()
    try:
        exp_repo = ExperimentRepository(db)
        base = datetime(2026, 7, 20, tzinfo=timezone.utc)
        for idx, value in enumerate(values):
            exp_id = f"exp_rev_{genre}_{idx}"
            exp_repo.create_experiment(
                experiment_id=exp_id,
                request_id=f"req_rev_{genre}_{idx}",
                challenger_id="chal_rev",
                genre=genre,
                champion_id="champ",
                assignment_bucket=1,
                serving_mode="shadow",
                resolved_model_id="m1",
                model_selection_source="prompt_combination",
                prompt_version_id="pv1",
                provider_parameters_hash="ph1",
                light_judge_version="lj-v1",
                evaluation_policy_version=policy,
                champion_prompt_hash="cph",
                challenger_prompt_hash="chph",
            )
            if value is None:
                champion = {"available": False}
            else:
                semantic, fact = value
                champion = {
                    "available": True,
                    "semantic_fidelity": {"score": semantic},
                    "fact_consistency": {"score": fact},
                }
            exp_repo.record_settlement(
                exp_id,
                light_judge_result={},
                returned_variant="challenger",
                async_review_result={"challenger": {}, "champion": champion},
                outcome=VERDICT_LOSS,
                finished_at=base + timedelta(hours=idx),
            )
        db.commit()
    finally:
        db.close()


def test_list_champion_reviews_ordered_by_finished_at():
    session_local = _build_db()
    _seed_champion_reviews(session_local, [(90.0, 95.0), (80.0, 85.0)])
    db = session_local()
    try:
        rows = ExperimentRepository(db).list_champion_reviews(GENRE, POLICY)
    finally:
        db.close()
    assert len(rows) == 2
    # 升序（finished_at 递增）
    assert rows[0][0] < rows[1][0]
    assert rows[0][1]["champion"]["semantic_fidelity"]["score"] == 90.0


def test_list_champion_reviews_filters_genre_and_policy():
    session_local = _build_db()
    _seed_champion_reviews(session_local, [(90.0, 95.0)], genre="都市")
    db = session_local()
    try:
        assert ExperimentRepository(db).list_champion_reviews(GENRE, POLICY) == []
        assert ExperimentRepository(db).list_champion_reviews(GENRE, "other-policy") == []
    finally:
        db.close()


def test_fidelity_drop_zero_when_insufficient_samples():
    session_local = _build_db()
    _seed_champion_reviews(session_local, [(90.0, 90.0), (80.0, 80.0)])  # 仅 2 < 2*window(=4)
    db = session_local()
    try:
        assert compute_champion_fidelity_drop(
            db, GENRE, policy=POLICY, window=2
        ) == pytest.approx(0.0)
    finally:
        db.close()


def test_fidelity_drop_positive_when_recent_degrades():
    session_local = _build_db()
    # 基线窗（先 2 个）保真 90，近窗（后 2 个）保真 80 → drop = 90 - 80 = 10
    _seed_champion_reviews(
        session_local, [(90.0, 90.0), (90.0, 90.0), (80.0, 80.0), (80.0, 80.0)]
    )
    db = session_local()
    try:
        assert compute_champion_fidelity_drop(
            db, GENRE, policy=POLICY, window=2
        ) == pytest.approx(10.0)
    finally:
        db.close()


def test_fidelity_drop_skips_unavailable_champion():
    session_local = _build_db()
    # 中间插入不可用复评（应跳过），有效样本仍为 4 个：基线 90、近窗 80
    _seed_champion_reviews(
        session_local,
        [(90.0, 90.0), None, (90.0, 90.0), None, (80.0, 80.0), (80.0, 80.0)],
    )
    db = session_local()
    try:
        assert compute_champion_fidelity_drop(
            db, GENRE, policy=POLICY, window=2
        ) == pytest.approx(10.0)
    finally:
        db.close()


def test_fidelity_drop_default_window_is_positive_int():
    assert isinstance(DEFAULT_FIDELITY_WINDOW, int)
    assert DEFAULT_FIDELITY_WINDOW >= 1


# ---------------- run_scheduler_tick 接入真实 converged / fidelity_drop ----------------

def test_tick_running_to_sleeping_on_converged_and_marginal(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    # 达标（最新 best 10 ≤ target 10）+ 连续 3 批提升均 < 2.0（12→11→10.5→10 → [1,0.5,0.5]）
    summaries = [
        _ct_summary("e1", GENRE, "completed", 12.0, 10.0, "2026-07-20T00:00:00"),
        _ct_summary("e2", GENRE, "completed", 11.0, 10.0, "2026-07-21T00:00:00"),
        _ct_summary("e3", GENRE, "completed", 10.5, 10.0, "2026-07-22T00:00:00"),
        _ct_summary("e4", GENRE, "completed", 10.0, 10.0, "2026-07-23T00:00:00"),
    ]
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE],
            deps=_quiet_deps(list_history_summaries=lambda: summaries),
            state_store=store, policy=POLICY, now="2026-07-25T00:00:00+00:00",
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_SLEEPING
    assert result[GENRE]["changed"] is True
    assert "marginal_gain_exhausted" in result[GENRE]["reasons"]


def test_tick_running_stays_when_not_converged(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    # 边际枯竭但最新批未达标（best 11 > target 10）→ 不休眠
    summaries = [
        _ct_summary("e1", GENRE, "completed", 13.0, 10.0, "2026-07-20T00:00:00"),
        _ct_summary("e2", GENRE, "completed", 12.0, 10.0, "2026-07-21T00:00:00"),
        _ct_summary("e3", GENRE, "completed", 11.5, 10.0, "2026-07-22T00:00:00"),
        _ct_summary("e4", GENRE, "completed", 11.0, 10.0, "2026-07-23T00:00:00"),
    ]
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE],
            deps=_quiet_deps(list_history_summaries=lambda: summaries),
            state_store=store, policy=POLICY, now="2026-07-25T00:00:00+00:00",
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_RUNNING
    assert result[GENRE]["changed"] is False


def test_tick_sleeping_to_awake_on_champion_fidelity_drop(tmp_path):
    session_local = _build_db()
    # 基线保真 90、近窗保真 80 → drop 10 > wake_fidelity_drop(5.0)
    _seed_champion_reviews(
        session_local, [(90.0, 90.0), (90.0, 90.0), (80.0, 80.0), (80.0, 80.0)]
    )
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_SLEEPING, reasons=["budget_exhausted"], now="2026-07-25T00:00:00+00:00")
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE], deps=_quiet_deps(), state_store=store, policy=POLICY,
            now="2026-07-25T03:00:00+00:00", fidelity_window=2,
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_AWAKE
    assert result[GENRE]["changed"] is True
    assert "champion_fidelity_drop" in result[GENRE]["reasons"]
    assert store.get(GENRE).state == STATE_AWAKE


# ---------------- list_champion_ai_scores / compute_champion_ai_score_rise（信号 3a 接真实源） ----------------

def _seed_champion_ai_scores(session_local, values, *, genre=GENRE, policy=POLICY):
    """
    按给定 champion_ai_score 序列播种已结算实验，finished_at 随 idx 递增（升序）。
    values 中元素为 None 表示该行未落分（应被 list_champion_ai_scores 排除）。
    """
    db = session_local()
    try:
        exp_repo = ExperimentRepository(db)
        base = datetime(2026, 7, 20, tzinfo=timezone.utc)
        for idx, score in enumerate(values):
            exp_id = f"exp_ai_{genre}_{idx}"
            exp_repo.create_experiment(
                experiment_id=exp_id,
                request_id=f"req_ai_{genre}_{idx}",
                challenger_id=f"chal_ai_{idx}",
                genre=genre,
                champion_id="champ",
                assignment_bucket=1,
                serving_mode="shadow",
                resolved_model_id="m1",
                model_selection_source="prompt_combination",
                prompt_version_id="pv1",
                provider_parameters_hash="ph1",
                light_judge_version="lj-v1",
                evaluation_policy_version=policy,
                champion_prompt_hash="cph",
                challenger_prompt_hash=f"chph{idx}",
            )
            exp_repo.record_settlement(
                exp_id,
                light_judge_result={},
                returned_variant="challenger",
                async_review_result={},
                outcome=VERDICT_LOSS,
                champion_ai_score=score,
                finished_at=base + timedelta(hours=idx),
            )
        db.commit()
    finally:
        db.close()


def test_ai_score_rise_zero_when_insufficient_samples():
    session_local = _build_db()
    _seed_champion_ai_scores(session_local, [40.0, 42.0])  # 仅 2 < 2*window(=4)
    db = session_local()
    try:
        assert compute_champion_ai_score_rise(
            db, GENRE, policy=POLICY, window=2
        ) == pytest.approx(0.0)
    finally:
        db.close()


def test_ai_score_rise_positive_when_recent_rises():
    session_local = _build_db()
    # 基线窗（先 2 个）AI 率 40，近窗（后 2 个）AI 率 55 → rise = 55 - 40 = 15（越高越差）
    _seed_champion_ai_scores(session_local, [40.0, 40.0, 55.0, 55.0])
    db = session_local()
    try:
        assert compute_champion_ai_score_rise(
            db, GENRE, policy=POLICY, window=2
        ) == pytest.approx(15.0)
    finally:
        db.close()


def test_ai_score_rise_skips_null_samples():
    session_local = _build_db()
    # 中间插入未落分行（应跳过），有效样本仍为 4 个：基线 40、近窗 55
    _seed_champion_ai_scores(
        session_local, [40.0, None, 40.0, None, 55.0, 55.0]
    )
    db = session_local()
    try:
        assert compute_champion_ai_score_rise(
            db, GENRE, policy=POLICY, window=2
        ) == pytest.approx(15.0)
    finally:
        db.close()


def test_tick_sleeping_to_awake_on_champion_ai_score_rise(tmp_path):
    session_local = _build_db()
    # 基线 AI 率 40、近窗 55 → rise 15 > wake_ai_score_rise(8.0)
    _seed_champion_ai_scores(session_local, [40.0, 40.0, 55.0, 55.0])
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_SLEEPING, reasons=["budget_exhausted"], now="2026-07-25T00:00:00+00:00")
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE], deps=_quiet_deps(), state_store=store, policy=POLICY,
            now="2026-07-25T03:00:00+00:00", fidelity_window=2,
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_AWAKE
    assert result[GENRE]["changed"] is True
    assert "champion_ai_degraded" in result[GENRE]["reasons"]
    assert store.get(GENRE).state == STATE_AWAKE


# ---------------- 信号 4 环境变更（env_snapshot 快照 + 指纹对比） ----------------

def test_state_store_env_snapshot_round_trip(tmp_path):
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(
        GENRE, STATE_SLEEPING, reasons=["budget_exhausted"],
        now="2026-07-25T00:00:00+00:00", env_snapshot={"policy": "v1"},
    )
    assert store.get(GENRE).env_snapshot == {"policy": "v1"}


def test_state_store_default_env_snapshot_is_none(tmp_path):
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    assert store.get(GENRE).env_snapshot is None
    store.set(GENRE, STATE_RUNNING, reasons=[], now="2026-07-25T00:00:00+00:00")
    assert store.get(GENRE).env_snapshot is None


def test_state_store_set_none_snapshot_preserves_existing(tmp_path):
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_SLEEPING, reasons=[], now="t0", env_snapshot={"policy": "v1"})
    # 不带快照的后续 set（如转出 sleeping）不应清空既有快照
    store.set(GENRE, STATE_AWAKE, reasons=["x"], now="t1")
    assert store.get(GENRE).env_snapshot == {"policy": "v1"}


def test_state_store_touch_preserves_snapshot(tmp_path):
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_SLEEPING, reasons=[], now="t0", env_snapshot={"policy": "v1"})
    store.touch(GENRE, now="t1")
    assert store.get(GENRE).env_snapshot == {"policy": "v1"}


def test_tick_empty_fingerprint_does_not_trigger_wake(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_SLEEPING, reasons=["budget_exhausted"], now="t0")  # 无快照
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE],
            deps=_quiet_deps(env_fingerprint=lambda g: {}),
            state_store=store, policy=POLICY, now="t1",
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_SLEEPING
    assert result[GENRE]["changed"] is False


def test_tick_sleeping_stays_when_fingerprint_unchanged(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(
        GENRE, STATE_SLEEPING, reasons=["budget_exhausted"], now="t0",
        env_snapshot={"policy": "v1"},
    )
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE],
            deps=_quiet_deps(env_fingerprint=lambda g: {"policy": "v1"}),
            state_store=store, policy=POLICY, now="t1",
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_SLEEPING
    assert result[GENRE]["changed"] is False


def test_tick_sleeping_to_awake_on_environment_changed(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(
        GENRE, STATE_SLEEPING, reasons=["budget_exhausted"], now="t0",
        env_snapshot={"policy": "v1"},
    )
    db = session_local()
    try:
        result = run_scheduler_tick(
            db, [GENRE],
            deps=_quiet_deps(env_fingerprint=lambda g: {"policy": "v2"}),
            state_store=store, policy=POLICY, now="t1",
        )
    finally:
        db.close()
    assert result[GENRE]["to"] == STATE_AWAKE
    assert result[GENRE]["changed"] is True
    assert "environment_changed" in result[GENRE]["reasons"]


def test_tick_running_to_sleeping_captures_env_snapshot(tmp_path):
    session_local = _build_db()
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    db = session_local()
    try:
        run_scheduler_tick(
            db, [GENRE],
            deps=_quiet_deps(
                is_budget_exhausted=lambda g: True,
                env_fingerprint=lambda g: {"policy": "v1"},
            ),
            state_store=store, policy=POLICY, now="t1",
        )
    finally:
        db.close()
    record = store.get(GENRE)
    assert record.state == STATE_SLEEPING
    assert record.env_snapshot == {"policy": "v1"}

