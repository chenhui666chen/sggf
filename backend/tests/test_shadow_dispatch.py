"""
shadow 分流决策 + 入队编排测试（设计文档 §5.1 / §5.5 / §10 / §14 第 6 步子块 B-1）

覆盖 maybe_create_shadow_experiment 决策链：
总开关 → 密钥存在（失败关闭）→ opt-in 授权 → HMAC 分桶 ε → 池内确定性选挑战者
→ 幂等预查 → 四维预算 reserve（同事务原子）→ PayloadVault 加密载荷 → pending 实验行。

红线：任何环节失败只静默跳过（dispatched=False + 结构化 reason），绝不影响冠军路径；
预算任一维失败整体回滚，不留半截实验行/半截账本占用。
不接 Celery、不调外部 API。
"""
import json
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
from app.services.prompt_evolution.experiment_contract import FrozenModelContract
from app.services.prompt_evolution.experiment_privacy import (
    ExperimentConsentRegistry,
    PayloadVault,
)
from app.services.prompt_evolution.shadow_dispatch import (
    ShadowDispatchConfig,
    maybe_create_shadow_experiment,
)


# ============ fixtures ============

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
def consent(tmp_path):
    return ExperimentConsentRegistry(storage_dir=str(tmp_path / "consent"))


@pytest.fixture()
def vault(tmp_path):
    return PayloadVault("test-payload-key", storage_dir=str(tmp_path / "vault"))


def _config(**overrides):
    data = dict(
        enabled=True,
        epsilon=1.0,
        bucket_secret="test-bucket-secret",
        payload_key="test-payload-key",
        payload_ttl_seconds=3600,
        estimated_cost=0.01,
        daily_calls_limit=100,
        daily_cost_limit=10.0,
        per_genre_cost_limit=5.0,
        per_challenger_cost_limit=2.0,
        per_user_daily_calls=10,
    )
    data.update(overrides)
    return ShadowDispatchConfig(**data)


def _contract():
    return FrozenModelContract.freeze(
        resolved_model_id="qwen-max",
        model_selection_source="admin_selected",
        model_config_version=None,
        prompt_version_id="initial-玄幻",
        temperature=0.8,
    )


def _seed_challenger(session, challenger_id="chg_玄幻_20260730_a1b2", **overrides):
    repo = ChallengerRepository(session)
    data = dict(
        challenger_id=challenger_id,
        genre="玄幻",
        prompt_text="改善句式结构，保留题材语域",
        prompt_hash=f"sha256:{challenger_id[-4:] * 4}",
        strategy_desc="降低连续同构句比例",
        strategy_family="sentence_structure",
        source_batch="batch_20260730_01",
        offline_gate_passed=True,
        offline_scores={"semantic_fidelity": 88.0},
    )
    data.update(overrides)
    row = repo.upsert_challenger(**data)
    session.commit()
    return row


def _dispatch(session, consent, vault, config, **overrides):
    kwargs = dict(
        subject_id="user-1",
        genre="玄幻",
        request_id="req-0001",
        original_text="原始待改写文本",
        champion_text="冠军改写产出文本",
        original_ai_score=72.0,
        champion_ai_score=45.0,
        champion_prompt_text="冠军当前提示词全文",
        contract=_contract(),
        config=config,
        consent_registry=consent,
        vault=vault,
    )
    kwargs.update(overrides)
    return maybe_create_shadow_experiment(session, **kwargs)


def _experiment_count(session):
    return session.query(PromptExperiment).count()


def _budget_row(session, scope, scope_key):
    return (
        session.query(PromptExperimentBudget)
        .filter(
            PromptExperimentBudget.scope == scope,
            PromptExperimentBudget.scope_key == scope_key,
        )
        .one_or_none()
    )


# ============ 决策链逐环节跳过 ============

def test_disabled_skips(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session)
    result = _dispatch(session, consent, vault, _config(enabled=False))
    assert result.dispatched is False
    assert result.reason == "disabled"
    assert _experiment_count(session) == 0


def test_missing_bucket_secret_skips(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session)
    result = _dispatch(session, consent, vault, _config(bucket_secret=""))
    assert result.dispatched is False
    assert result.reason == "missing_config"
    assert _experiment_count(session) == 0


def test_missing_payload_key_skips(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session)
    result = _dispatch(session, consent, vault, _config(payload_key=""))
    assert result.dispatched is False
    assert result.reason == "missing_config"
    assert _experiment_count(session) == 0


def test_no_consent_skips(session, consent, vault):
    # 默认拒绝：未 grant 即无授权
    _seed_challenger(session)
    result = _dispatch(session, consent, vault, _config())
    assert result.dispatched is False
    assert result.reason == "no_consent"
    assert _experiment_count(session) == 0


def test_epsilon_zero_skips(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session)
    result = _dispatch(session, consent, vault, _config(epsilon=0.0))
    assert result.dispatched is False
    assert result.reason == "epsilon_miss"
    assert _experiment_count(session) == 0


def test_empty_pool_skips(session, consent, vault):
    consent.grant("user-1")
    result = _dispatch(session, consent, vault, _config())
    assert result.dispatched is False
    assert result.reason == "no_challenger"
    assert _experiment_count(session) == 0


# ============ 成功创建 ============

def test_created_persists_pending_experiment(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session)
    result = _dispatch(session, consent, vault, _config())
    assert result.dispatched is True
    assert result.reason == "created"
    assert result.experiment_id
    assert result.challenger_id == "chg_玄幻_20260730_a1b2"

    row = (
        session.query(PromptExperiment)
        .filter(PromptExperiment.experiment_id == result.experiment_id)
        .one()
    )
    assert row.status == "pending"
    assert row.genre == "玄幻"
    assert row.request_id == "req-0001"
    assert row.serving_mode == "shadow"
    assert 0 <= row.assignment_bucket < 10000
    # 冠军契约冻结字段
    assert row.resolved_model_id == "qwen-max"
    assert row.model_selection_source == "admin_selected"
    assert row.prompt_version_id == "initial-玄幻"
    assert row.provider_parameters_hash
    assert row.champion_prompt_hash.startswith("sha256:")
    assert row.challenger_prompt_hash.startswith("sha256:")
    assert row.payload_ref
    assert row.payload_expires_at is not None


def test_created_payload_encrypted_in_vault(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session)
    result = _dispatch(session, consent, vault, _config())
    row = (
        session.query(PromptExperiment)
        .filter(PromptExperiment.experiment_id == result.experiment_id)
        .one()
    )
    payload = json.loads(vault.get(row.payload_ref))
    assert payload["original_text"] == "原始待改写文本"
    assert payload["champion_text"] == "冠军改写产出文本"
    assert payload["original_ai_score"] == 72.0
    assert payload["champion_ai_score"] == 45.0
    # 结算 user 维预算需回溯主体（vault 索引本就存 subject_id，加密载荷内携带不违反隐私红线）
    assert payload["subject_id"] == "user-1"


def test_created_reserves_four_budget_scopes(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session)
    _dispatch(session, consent, vault, _config())

    global_row = _budget_row(session, "global", "")
    assert global_row is not None
    assert global_row.calls_used == 1
    assert global_row.reserved_cost == pytest.approx(0.01)
    assert global_row.calls_limit == 100
    assert global_row.cost_limit == pytest.approx(10.0)

    genre_row = _budget_row(session, "genre", "玄幻")
    assert genre_row is not None
    assert genre_row.reserved_cost == pytest.approx(0.01)
    assert genre_row.cost_limit == pytest.approx(5.0)

    challenger_row = _budget_row(session, "challenger", "chg_玄幻_20260730_a1b2")
    assert challenger_row is not None
    assert challenger_row.cost_limit == pytest.approx(2.0)

    user_row = _budget_row(session, "user", "user-1")
    assert user_row is not None
    assert user_row.calls_used == 1
    assert user_row.calls_limit == 10


# ============ 预算失败回滚 / 幂等 / 确定性 ============

def test_budget_exhausted_rolls_back_everything(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session)
    result = _dispatch(session, consent, vault, _config(daily_calls_limit=0))
    assert result.dispatched is False
    assert result.reason == "budget_exhausted"
    assert _experiment_count(session) == 0
    # 回滚后不留半截账本占用
    global_row = _budget_row(session, "global", "")
    assert global_row is None or global_row.calls_used == 0


def test_repeat_request_is_idempotent_no_double_charge(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session)
    first = _dispatch(session, consent, vault, _config())
    second = _dispatch(session, consent, vault, _config())
    assert first.dispatched is True
    assert second.dispatched is False
    assert second.reason == "already_exists"
    assert second.experiment_id == first.experiment_id
    assert _experiment_count(session) == 1
    # 幂等命中不得重复扣预算
    assert _budget_row(session, "global", "").calls_used == 1


def test_challenger_selection_is_deterministic(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session, challenger_id="chg_玄幻_20260730_a1b2")
    _seed_challenger(session, challenger_id="chg_玄幻_20260730_zzzz")
    first = _dispatch(session, consent, vault, _config(), request_id="req-0001")
    second = _dispatch(session, consent, vault, _config(), request_id="req-0002")
    # 同 subject × genre × 统计窗口内选择恒定（campaign 级确定性）
    assert first.challenger_id == second.challenger_id


# ============ 异常 fail-safe ============

class _BrokenVault:
    def put(self, subject_id, text, ttl_seconds=None):
        raise RuntimeError("vault 故障注入")


def test_unexpected_error_fails_safe(session, consent, vault):
    consent.grant("user-1")
    _seed_challenger(session)
    result = _dispatch(session, consent, _BrokenVault(), _config())
    assert result.dispatched is False
    assert result.reason == "error:RuntimeError"
    assert _experiment_count(session) == 0
