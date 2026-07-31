"""
shadow 实验执行器测试（设计文档 §5.2 / §5.3 / §5.5 / §7.1 / §14 第 6 步子块 B-2）

覆盖 run_shadow_batch / execute_experiment 编排核心：
认领 → 载荷读取 → 挑战者生成 → AI 检测 → 同步轻判 → 异步复评 → verdict 归类
→ 结算（record_settlement + 四维预算 settle + 载荷删除）。

外部调用（生成/检测/复评）全部依赖注入假函数，sqlite 内存库可测全状态机；
真实供应商装配属 Celery 薄壳（experiment_tasks.py），不在本测试范围。
"""
import json
import os
import sys
from datetime import datetime, timezone
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
from app.services.prompt_evolution.budget_ledger import BudgetLedger
from app.services.prompt_evolution.challenger_repository import ChallengerRepository
from app.services.prompt_evolution.experiment_privacy import PayloadVault
from app.services.prompt_evolution.experiment_repository import ExperimentRepository
from app.services.prompt_evolution.shadow_executor import (
    ShadowExecutionDeps,
    run_shadow_batch,
)

# 中性长文本（≥30 字符、无禁用词、无阿拉伯数字、单段），规避轻判硬门槛的长度/数字/结构分支
ORIGINAL_TEXT = (
    "少年背着旧剑走入山门，雪片落在他的肩头。他沿着石阶缓缓向上，"
    "心里反复想着师父临别时说过的那句话，直到暮色漫过远处的山脊。"
)
CHAMPION_TEXT = (
    "少年负着旧剑踏进山门，雪花一片片落上肩头。他顺着石阶慢慢往上走，"
    "脑中回响着师父分别时留下的话，直到暮色淹没了远山的轮廓。"
)
CHALLENGER_TEXT = (
    "背着旧剑的少年迈入山门，肩头覆着细雪。他拾级而上，步子不快，"
    "师父临别的叮嘱在心底盘旋不去，暮色渐渐吞没了远处山脊的线条。"
)

GOOD_REVIEW = {
    "available": True,
    "hard_fail": False,
    "fidelity": 92.0,
    "fact": 95.0,
    "completeness": 90.0,
    "over_rewrite_risk": "low",
    "confidence": 0.9,
}
MEDIOCRE_REVIEW = {**GOOD_REVIEW, "fidelity": 85.0, "fact": 91.0, "completeness": 80.0}
UNAVAILABLE_REVIEW = {"available": False}

ESTIMATED_COST = 0.01
BUDGET_SCOPES = (("global", ""), ("genre", "玄幻"), ("challenger", "chg_玄幻_20260730_a1b2"), ("user", "user-1"))


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


@pytest.fixture()
def vault(tmp_path):
    return PayloadVault("test-payload-key", storage_dir=str(tmp_path / "vault"))


def _seed_experiment(session, vault, *, attempt_count=0, payload_ref="auto", skip_challenger=False):
    """模拟子块 B-1 dispatch 的落库结果：挑战者行 + pending 实验行 + 四维预算 reserve + 加密载荷"""
    if not skip_challenger:
        ChallengerRepository(session).upsert_challenger(
            challenger_id="chg_玄幻_20260730_a1b2",
            genre="玄幻",
            prompt_text="改善句式结构，保留题材语域",
            prompt_hash="sha256:a1b2c3d4e5f6a7b8",
            strategy_desc="降低连续同构句比例",
            strategy_family="sentence_structure",
            source_batch="batch_20260730_01",
            offline_gate_passed=True,
            offline_scores={"semantic_fidelity": 88.0},
        )
    if payload_ref == "auto":
        payload_ref = vault.put(
            "user-1",
            json.dumps(
                {
                    "subject_id": "user-1",
                    "original_text": ORIGINAL_TEXT,
                    "champion_text": CHAMPION_TEXT,
                    "original_ai_score": 72.0,
                    "champion_ai_score": 45.0,
                },
                ensure_ascii=False,
            ),
        )
    row = ExperimentRepository(session).create_experiment(
        experiment_id="exp_0000000000000001",
        request_id="req-0001",
        challenger_id="chg_玄幻_20260730_a1b2",
        genre="玄幻",
        champion_id="initial-玄幻",
        assignment_bucket=42,
        serving_mode="shadow",
        resolved_model_id="qwen-max",
        model_selection_source="admin_selected",
        prompt_version_id="initial-玄幻",
        provider_parameters_hash="abcd1234abcd1234",
        light_judge_version="light-judge-v1",
        evaluation_policy_version="experiment-policy-v1",
        champion_prompt_hash="sha256:" + "c" * 16,
        challenger_prompt_hash="sha256:a1b2c3d4e5f6a7b8",
        payload_ref=payload_ref,
    )
    row.attempt_count = attempt_count
    ledger = BudgetLedger(session)
    budget_date = row.created_at.strftime("%Y-%m-%d") if row.created_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for scope, scope_key in BUDGET_SCOPES:
        ledger.reserve(budget_date, scope, scope_key, cost=ESTIMATED_COST, calls=1)
    session.commit()
    return row


def _deps(
    vault,
    *,
    challenger_text=CHALLENGER_TEXT,
    detect_score=10.0,
    challenger_review=GOOD_REVIEW,
    champion_review=MEDIOCRE_REVIEW,
    rewrite_error=None,
    max_attempts=3,
):
    def rewrite_fn(prompt_text, original_text, model_id):
        if rewrite_error is not None:
            raise rewrite_error
        return challenger_text

    def detect_fn(text):
        return detect_score

    def review_fn(original, rewritten, genre):
        return challenger_review if rewritten == challenger_text else champion_review

    return ShadowExecutionDeps(
        rewrite_fn=rewrite_fn,
        detect_fn=detect_fn,
        review_fn=review_fn,
        vault=vault,
        estimated_cost=ESTIMATED_COST,
        ai_threshold=50.0,
        max_attempts=max_attempts,
    )


def _run(session, deps, limit=5):
    return run_shadow_batch(
        session, deps, now=datetime.now(timezone.utc), limit=limit, lease_seconds=600
    )


def _reload(session, experiment_id="exp_0000000000000001"):
    session.expire_all()
    return (
        session.query(PromptExperiment)
        .filter(PromptExperiment.experiment_id == experiment_id)
        .one()
    )


def _budget_row(session, scope, scope_key):
    return (
        session.query(PromptExperimentBudget)
        .filter(
            PromptExperimentBudget.scope == scope,
            PromptExperimentBudget.scope_key == scope_key,
        )
        .one()
    )


# ============ 批处理入口 ============

def test_batch_empty_queue(session, vault):
    stats = _run(session, _deps(vault))
    assert stats["claimed"] == 0
    assert stats["settled"] == 0


# ============ 成功结算路径 ============

def test_confirmed_win_settles_with_budget_and_payload_cleanup(session, vault):
    row = _seed_experiment(session, vault)
    payload_ref = row.payload_ref
    stats = _run(session, _deps(vault, detect_score=10.0))
    assert stats == {"claimed": 1, "settled": 1, "dead": 0, "retry": 0}

    row = _reload(session)
    assert row.status == "settled"
    assert row.outcome == "confirmed_win"
    assert row.returned_variant == "challenger"
    assert row.light_judge_result["margin_passed"] is True
    assert row.async_review_result["challenger"]["fidelity"] == 92.0
    assert row.finished_at is not None
    # 处理完成载荷立即删除（§10）
    assert vault.get(payload_ref) is None
    # 四维预算 settle：预留额释放、实际花费入账、调用配额不回退
    for scope, scope_key in BUDGET_SCOPES:
        budget = _budget_row(session, scope, scope_key)
        assert budget.reserved_cost == pytest.approx(0.0)
        assert budget.cost_used == pytest.approx(ESTIMATED_COST)
        assert budget.calls_used == 1


def test_champion_ai_score_persisted_on_settlement(session, vault):
    """结算落库冠军原始 AI 检测分（§11.2 信号 3a），供休眠期在线退化唤醒"""
    _seed_experiment(session, vault)  # 载荷内 champion_ai_score=45.0
    _run(session, _deps(vault, detect_score=10.0))
    row = _reload(session)
    assert row.status == "settled"
    assert row.champion_ai_score == 45.0


def test_loss_when_challenger_not_ahead_enough(session, vault):
    # 挑战者 AI 分与冠军接近（45 vs 44），排序分差 < margin → 返回冠军 → loss
    _seed_experiment(session, vault)
    _run(session, _deps(vault, detect_score=44.0))
    row = _reload(session)
    assert row.status == "settled"
    assert row.outcome == "loss"
    assert row.returned_variant == "champion"


def test_invalidated_win_when_review_rejects(session, vault):
    # 同步判挑战者胜，但复评保真低于门槛 → 作废
    bad_review = {**GOOD_REVIEW, "fidelity": 60.0}
    _seed_experiment(session, vault)
    _run(session, _deps(vault, detect_score=10.0, challenger_review=bad_review))
    row = _reload(session)
    assert row.outcome == "invalidated_win"


def test_hard_failure_on_short_challenger_output(session, vault):
    _seed_experiment(session, vault)
    _run(session, _deps(vault, challenger_text="太短"))
    row = _reload(session)
    assert row.status == "settled"
    assert row.outcome == "hard_failure"
    assert row.returned_variant == "champion"


# ============ 基础设施异常（不进胜率分母） ============

def test_detector_unavailable_is_infrastructure_failure(session, vault):
    _seed_experiment(session, vault)
    _run(session, _deps(vault, detect_score=None))
    row = _reload(session)
    assert row.status == "settled"
    assert row.outcome == "infrastructure_failure"


def test_review_unavailable_is_infrastructure_failure(session, vault):
    _seed_experiment(session, vault)
    _run(session, _deps(vault, challenger_review=UNAVAILABLE_REVIEW))
    row = _reload(session)
    assert row.outcome == "infrastructure_failure"


# ============ 重试与死信 ============

def test_rewrite_error_leaves_pending_for_retry(session, vault):
    _seed_experiment(session, vault)
    stats = _run(session, _deps(vault, rewrite_error=RuntimeError("供应商超时")))
    assert stats["retry"] == 1
    row = _reload(session)
    # 留 pending（租约到期自动重试），预算预留保持占用
    assert row.status == "pending"
    assert row.attempt_count == 1
    assert _budget_row(session, "global", "").reserved_cost == pytest.approx(ESTIMATED_COST)


def test_rewrite_error_at_max_attempts_marks_dead_and_releases(session, vault):
    _seed_experiment(session, vault, attempt_count=2)  # 认领后 attempt_count=3 达上限
    stats = _run(session, _deps(vault, rewrite_error=RuntimeError("供应商超时"), max_attempts=3))
    assert stats["dead"] == 1
    row = _reload(session)
    assert row.status == "dead"
    assert row.last_error_code.startswith("max_attempts")
    # 死信释放全部预留额（调用配额不回退）
    for scope, scope_key in BUDGET_SCOPES:
        budget = _budget_row(session, scope, scope_key)
        assert budget.reserved_cost == pytest.approx(0.0)
        assert budget.cost_used == pytest.approx(0.0)
        assert budget.calls_used == 1


def test_payload_missing_marks_dead(session, vault):
    _seed_experiment(session, vault, payload_ref="ref-not-exists")
    stats = _run(session, _deps(vault))
    assert stats["dead"] == 1
    row = _reload(session)
    assert row.status == "dead"
    assert row.last_error_code == "payload_missing"


def test_challenger_row_missing_marks_dead(session, vault):
    _seed_experiment(session, vault, skip_challenger=True)
    _run(session, _deps(vault))
    row = _reload(session)
    assert row.status == "dead"
    assert row.last_error_code == "challenger_missing"


# ============ 认领互斥（租约内不重复处理） ============

def test_leased_experiment_not_reclaimed(session, vault):
    _seed_experiment(session, vault)
    _run(session, _deps(vault, rewrite_error=RuntimeError("供应商超时")))
    # 第一次失败后仍在租约期内，第二次批处理不应认领
    stats = _run(session, _deps(vault))
    assert stats["claimed"] == 0
    assert _reload(session).attempt_count == 1


# ============ returnable 预置分支（子块 B：跳过重复生成，只补异步复评） ============

def _seed_preset_experiment(
    session,
    vault,
    *,
    returned_variant="challenger",
    challenger_ai_score=10.0,
    light_result=None,
    experiment_id="exp_preset_00000001",
):
    """模拟子块 B returnable 落库：挑战者行 + pending 行(serving_mode=returnable) + 预置双路载荷，无预算 reserve"""
    ChallengerRepository(session).upsert_challenger(
        challenger_id="chg_玄幻_20260730_a1b2",
        genre="玄幻",
        prompt_text="改善句式结构，保留题材语域",
        prompt_hash="sha256:a1b2c3d4e5f6a7b8",
        strategy_desc="降低连续同构句比例",
        strategy_family="sentence_structure",
        source_batch="batch_20260730_01",
        offline_gate_passed=True,
        offline_scores={"semantic_fidelity": 88.0},
    )
    if light_result is None:
        light_result = {"margin_passed": True, "returned_variant": returned_variant}
    payload_ref = vault.put(
        "user-1",
        json.dumps(
            {
                "subject_id": "user-1",
                "original_text": ORIGINAL_TEXT,
                "champion_text": CHAMPION_TEXT,
                "champion_ai_score": 45.0,
                "preset_challenger": {
                    "challenger_text": CHALLENGER_TEXT,
                    "challenger_ai_score": challenger_ai_score,
                    "light_judge_result": light_result,
                    "returned_variant": returned_variant,
                },
            },
            ensure_ascii=False,
        ),
    )
    ExperimentRepository(session).create_experiment(
        experiment_id=experiment_id,
        request_id="req-preset-1",
        challenger_id="chg_玄幻_20260730_a1b2",
        genre="玄幻",
        champion_id="initial-玄幻",
        assignment_bucket=42,
        serving_mode="returnable",
        resolved_model_id="qwen-max",
        model_selection_source="admin_selected",
        prompt_version_id="initial-玄幻",
        provider_parameters_hash="abcd1234abcd1234",
        light_judge_version="light-judge-v1",
        evaluation_policy_version="experiment-policy-v1",
        champion_prompt_hash="sha256:" + "c" * 16,
        challenger_prompt_hash="sha256:a1b2c3d4e5f6a7b8",
        payload_ref=payload_ref,
    )
    session.commit()


def _deps_no_generation(vault, **kwargs):
    """rewrite/detect 抛异常——断言预置分支绝不重复生成/检测"""

    def boom(*_args, **_kwargs):
        raise AssertionError("预置分支不应调用生成/检测")

    base = _deps(vault, **kwargs)
    return ShadowExecutionDeps(
        rewrite_fn=boom,
        detect_fn=boom,
        review_fn=base.review_fn,
        vault=base.vault,
        estimated_cost=base.estimated_cost,
        ai_threshold=base.ai_threshold,
        max_attempts=base.max_attempts,
    )


def test_preset_confirmed_win_skips_regeneration(session, vault):
    _seed_preset_experiment(session, vault, returned_variant="challenger", challenger_ai_score=10.0)
    stats = _run(session, _deps_no_generation(vault))
    assert stats == {"claimed": 1, "settled": 1, "dead": 0, "retry": 0}
    row = _reload(session, "exp_preset_00000001")
    assert row.status == "settled"
    assert row.outcome == "confirmed_win"
    assert row.returned_variant == "challenger"
    assert row.light_judge_result["margin_passed"] is True
    assert row.async_review_result["challenger"]["fidelity"] == 92.0


def test_preset_invalidated_win_when_review_rejects(session, vault):
    bad_review = {**GOOD_REVIEW, "fidelity": 60.0}
    _seed_preset_experiment(session, vault, returned_variant="challenger")
    _run(session, _deps_no_generation(vault, challenger_review=bad_review))
    row = _reload(session, "exp_preset_00000001")
    assert row.outcome == "invalidated_win"


def test_preset_returned_champion_is_loss(session, vault):
    _seed_preset_experiment(
        session,
        vault,
        returned_variant="champion",
        light_result={"margin_passed": False, "returned_variant": "champion"},
    )
    _run(session, _deps_no_generation(vault))
    row = _reload(session, "exp_preset_00000001")
    assert row.outcome == "loss"
    assert row.returned_variant == "champion"


def test_preset_detector_unavailable_is_infrastructure_failure(session, vault):
    _seed_preset_experiment(session, vault, challenger_ai_score=None)
    _run(session, _deps_no_generation(vault))
    row = _reload(session, "exp_preset_00000001")
    assert row.outcome == "infrastructure_failure"


def test_preset_returnable_skips_budget(session, vault):
    _seed_preset_experiment(session, vault)
    _run(session, _deps_no_generation(vault))
    # returnable 由风险治理（§5.1），不占用/结算 shadow 预算：无任何预算行
    assert session.query(PromptExperimentBudget).count() == 0


# ---------------------------------------------------------------------------
# Celery 装配层：AI 阈值配置校验（八轮评审①）
# shadow 与 returnable 须共用同一解析+范围校验，杜绝裸 float() 放行 nan/inf/负值
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-1", "101", "abc"])
def test_build_deps_rejects_invalid_ai_threshold(monkeypatch, value):
    from app.tasks.experiment_tasks import _build_deps

    monkeypatch.setenv("EXPERIMENT_AI_SCORE_THRESHOLD", value)
    with pytest.raises(ValueError, match="EXPERIMENT_AI_SCORE_THRESHOLD"):
        _build_deps()


@pytest.mark.parametrize("value", ["abc", "0", "-1", "1.5"])
def test_build_deps_rejects_invalid_max_attempts(monkeypatch, value):
    from app.tasks.experiment_tasks import _build_deps

    monkeypatch.setenv("EXPERIMENT_MAX_ATTEMPTS", value)
    with pytest.raises(ValueError, match="EXPERIMENT_MAX_ATTEMPTS"):
        _build_deps()
