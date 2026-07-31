"""
returnable best-of-2 择优返回测试（设计文档 §5.4 / §14 第 8 步 · 子块 A）

覆盖两部分：
- 纯逻辑：returnable ε 分桶（与 shadow 域分离）、运行期熔断（滚动作废率越限）、配置 from_env。
- async 编排：choose_returnable_variant 决策链（开关/密钥/授权/熔断/ε/池空短路回退冠军，
  双路择优挑战者胜出 vs 平局回退，检测不可用回退，供应商异常 fail-safe 回退），
  依赖注入 async rewrite/detect + 假 consent，sqlite 可测。
"""
import json
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
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.models.prompt_experiment import (
    PromptChallenger,
    PromptChallengerStateTransition,
    PromptExperiment,
    PromptExperimentBudget,
)
from app.services.prompt_evolution.challenger_repository import ChallengerRepository
from app.services.prompt_evolution.experiment_contract import (
    EXPERIMENT_EVALUATION_POLICY_VERSION,
    LIGHT_JUDGE_VERSION,
    FrozenModelContract,
    ServingMode,
)
from app.services.prompt_evolution.experiment_privacy import PayloadVault
from app.services.prompt_evolution.experiment_repository import ExperimentRepository
from app.services.prompt_evolution.returnable_service import (
    BestOfTwoOutcome,
    ReturnableConfig,
    ReturnableDeps,
    approve_returnable,
    choose_returnable_variant,
    is_circuit_open,
    parse_ai_threshold,
    parse_max_attempts,
    persist_returnable_experiment,
    returnable_bucket_hit,
    returnable_reduce,
)
from app.services.prompt_evolution.review_verdict import (
    VERDICT_CONFIRMED_WIN,
    VERDICT_INVALIDATED_WIN,
)


# ---------------------------------------------------------------------------
# 测试夹具与辅助
# ---------------------------------------------------------------------------

@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (
        PromptChallenger,
        PromptChallengerStateTransition,
        PromptExperiment,
        PromptExperimentBudget,
    ):
        model.__table__.create(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield db
    finally:
        db.close()


class _FakeConsent:
    """假授权注册表（duck-typing has_consent）"""

    def __init__(self, granted=True):
        self._granted = granted

    def has_consent(self, subject_id):  # noqa: D401
        return self._granted


def _config(**overrides):
    base = dict(
        enabled=True,
        epsilon=1.0,
        margin_threshold=5.0,
        bucket_secret="secret-key",
        ai_threshold=25.0,
        invalidation_rate_max=0.05,
    )
    base.update(overrides)
    return ReturnableConfig(**base)


def _make_deps(*, challenger_text, challenger_score, consent=True, rewrite_raises=False):
    calls = {"rewrite": 0, "detect": 0, "model_id": None}

    async def rewrite_fn(prompt_text, original_text, model_id):
        calls["rewrite"] += 1
        calls["model_id"] = model_id
        if rewrite_raises:
            raise RuntimeError("provider down")
        return challenger_text

    async def detect_fn(text):
        calls["detect"] += 1
        return challenger_score

    deps = ReturnableDeps(
        rewrite_fn=rewrite_fn,
        detect_fn=detect_fn,
        consent_registry=_FakeConsent(consent),
    )
    return deps, calls


def _seed_returnable(session, challenger_id, genre, *, family="sentence"):
    ChallengerRepository(session).upsert_challenger(
        challenger_id=challenger_id,
        genre=genre,
        prompt_text="改善句式结构，降低连续同构句比例",
        prompt_hash=f"sha256:{challenger_id}",
        strategy_desc="降低连续同构句比例",
        strategy_family=family,
        source_batch="batch_20260730_01",
        offline_gate_passed=True,
        offline_scores={},
        serving_mode=ServingMode.RETURNABLE.value,
    )


def _add_settled(
    session, *, challenger_id, genre, outcome, count, serving_mode="shadow", finished_at=None
):
    for i in range(count):
        session.add(
            PromptExperiment(
                experiment_id=f"exp_{challenger_id}_{serving_mode}_{outcome}_{i}",
                request_id=f"req_{challenger_id}_{serving_mode}_{outcome}_{i}",
                challenger_id=challenger_id,
                genre=genre,
                status="settled",
                champion_id="champ-1",
                assignment_bucket=1,
                serving_mode=serving_mode,
                resolved_model_id="m1",
                model_selection_source="prompt_combination",
                prompt_version_id="v1",
                provider_parameters_hash="phash",
                light_judge_version=LIGHT_JUDGE_VERSION,
                evaluation_policy_version=EXPERIMENT_EVALUATION_POLICY_VERSION,
                champion_prompt_hash="chash",
                challenger_prompt_hash="ghash",
                outcome=outcome,
                finished_at=finished_at,
            )
        )
    session.flush()


# 长度充足、单段、无数字、无禁用词的中性文本，两路复用以隔离仅 AI 分驱动的 margin
_ORIGINAL = (
    "午后的阳光透过老旧的木窗斜斜地洒进屋内，在斑驳的地板上投下细碎的光影，"
    "空气里浮动着淡淡的尘埃与旧书的气味，一切都显得那样安静而缓慢。"
)
_REWRITE = (
    "斜斜的午后阳光穿过陈旧木窗落进屋里，把细碎光影铺在斑驳地板上，"
    "空气中飘着尘埃和旧书混合的气味，整个房间安静得近乎凝滞。"
)


# ---------------------------------------------------------------------------
# 纯逻辑：分桶与熔断
# ---------------------------------------------------------------------------

def test_returnable_bucket_hit_epsilon_zero_never():
    config = _config(epsilon=0.0)
    assert returnable_bucket_hit(config, "user-1", "玄幻") is False


def test_returnable_bucket_hit_epsilon_one_always():
    config = _config(epsilon=1.0)
    assert returnable_bucket_hit(config, "user-1", "玄幻") is True


def test_circuit_open_false_when_no_samples(session):
    assert is_circuit_open(session, _config()) is False


def test_circuit_open_true_when_invalidation_exceeds(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # returnable 窗口内 1 confirmed + 1 invalidated → 作废率 0.5 > 0.05（门槛降到 2 隔离越限分支）
    now = datetime.now(timezone.utc)
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_CONFIRMED_WIN,
        count=1, serving_mode="returnable", finished_at=now,
    )
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_INVALIDATED_WIN,
        count=1, serving_mode="returnable", finished_at=now,
    )
    assert is_circuit_open(session, _config(circuit_min_samples=2, warmup_min_samples=1)) is True


def test_circuit_open_false_when_invalidation_ok(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # 窗口内 20 confirmed + 0 invalidated → 作废率 0.0 <= 0.05
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_CONFIRMED_WIN,
        count=20, serving_mode="returnable", finished_at=datetime.now(timezone.utc),
    )
    assert is_circuit_open(session, _config(circuit_min_samples=2, warmup_min_samples=1)) is False


def test_circuit_open_ignores_shadow_samples(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # shadow 场景样本不计入 returnable 熔断域（ε 量级碾压会稀释信号）
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_INVALIDATED_WIN,
        count=5, serving_mode="shadow", finished_at=datetime.now(timezone.utc),
    )
    assert is_circuit_open(session, _config(circuit_min_samples=2, warmup_min_samples=1)) is False


def test_circuit_open_ignores_samples_outside_window(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # 8 天前的作废样本在默认 168h 窗口外：历史不稀释、也不误伤当下
    old = datetime.now(timezone.utc) - timedelta(days=8)
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_INVALIDATED_WIN,
        count=5, serving_mode="returnable", finished_at=old,
    )
    assert is_circuit_open(session, _config(circuit_min_samples=2, warmup_min_samples=1)) is False


def test_circuit_open_warmup_below_min_samples(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # 100% 作废但有效样本连预热门槛（warmup_min_samples 默认 20）都未达
    # → 不熔断，避免 1/1 即停摆
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_INVALIDATED_WIN,
        count=3, serving_mode="returnable", finished_at=datetime.now(timezone.utc),
    )
    assert is_circuit_open(session, _config()) is False


def test_circuit_opens_on_severe_warmup_degradation(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # 五轮评审②：预热期（20 <= 有效样本 < 200）严重劣化必须熔断——
    # 25 样本作废率 0.8 > warmup_invalidation_rate_max(0.20)，旧逻辑无条件放行是盲区
    now = datetime.now(timezone.utc)
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_INVALIDATED_WIN,
        count=20, serving_mode="returnable", finished_at=now,
    )
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_CONFIRMED_WIN,
        count=5, serving_mode="returnable", finished_at=now,
    )
    assert is_circuit_open(session, _config()) is True


def test_circuit_stays_closed_on_small_benign_warmup_sample(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # 预热期用更宽阈值：25 样本作废率 0.12 越成熟期阈值（0.05）
    # 但未越预热期阈值（0.20）→ 不熔断，容忍小样本统计噪声
    now = datetime.now(timezone.utc)
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_INVALIDATED_WIN,
        count=3, serving_mode="returnable", finished_at=now,
    )
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_CONFIRMED_WIN,
        count=22, serving_mode="returnable", finished_at=now,
    )
    assert is_circuit_open(session, _config()) is False


def test_circuit_switches_to_mature_threshold_at_min_samples(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # 有效样本恰达 circuit_min_samples → 切换成熟期阈值：
    # 作废率 0.1 未越预热期阈值（0.20）但越成熟期阈值（0.05）→ 熔断
    now = datetime.now(timezone.utc)
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_INVALIDATED_WIN,
        count=1, serving_mode="returnable", finished_at=now,
    )
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_CONFIRMED_WIN,
        count=9, serving_mode="returnable", finished_at=now,
    )
    config = _config(
        circuit_min_samples=10, warmup_min_samples=5, warmup_invalidation_rate_max=0.20
    )
    assert is_circuit_open(session, config) is True


def test_config_from_env_defaults(monkeypatch):
    for key in (
        "EXPERIMENT_ENABLED",
        "EXPERIMENT_EPSILON_RETURNABLE",
        "EXPERIMENT_MARGIN_THRESHOLD",
        "EXPERIMENT_BUCKET_SECRET",
        "EXPERIMENT_AI_SCORE_THRESHOLD",
        "EXPERIMENT_INVALIDATED_RATE_MAX",
        "EXPERIMENT_CIRCUIT_WINDOW_HOURS",
        "EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES",
        "EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES",
        "EXPERIMENT_CIRCUIT_WARMUP_INVALIDATED_RATE_MAX",
    ):
        monkeypatch.delenv(key, raising=False)
    config = ReturnableConfig.from_env()
    assert config.enabled is False
    assert config.epsilon == pytest.approx(0.0)
    assert config.margin_threshold == pytest.approx(5.0)
    assert config.bucket_secret == ""
    assert config.ai_threshold == pytest.approx(25.0)
    assert config.invalidation_rate_max == pytest.approx(0.05)
    # 熔断窗口默认 168h（§5.4 既定 7 日）；样本门槛复用 replay 校准同语义常量 200
    assert config.circuit_window_hours == pytest.approx(168.0)
    assert config.circuit_min_samples == 200
    # 预热期双层规则（五轮评审②）：20/0.20 为评审建议初值，非文档既定值
    assert config.warmup_min_samples == 20
    assert config.warmup_invalidation_rate_max == pytest.approx(0.20)


def test_config_from_env_overrides(monkeypatch):
    monkeypatch.setenv("EXPERIMENT_ENABLED", "true")
    monkeypatch.setenv("EXPERIMENT_EPSILON_RETURNABLE", "0.05")
    monkeypatch.setenv("EXPERIMENT_MARGIN_THRESHOLD", "8")
    monkeypatch.setenv("EXPERIMENT_INVALIDATED_RATE_MAX", "0.03")
    monkeypatch.setenv("EXPERIMENT_CIRCUIT_WINDOW_HOURS", "72")
    monkeypatch.setenv("EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES", "50")
    monkeypatch.setenv("EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES", "10")
    monkeypatch.setenv("EXPERIMENT_CIRCUIT_WARMUP_INVALIDATED_RATE_MAX", "0.30")
    config = ReturnableConfig.from_env()
    assert config.enabled is True
    assert config.epsilon == pytest.approx(0.05)
    assert config.margin_threshold == pytest.approx(8.0)
    assert config.invalidation_rate_max == pytest.approx(0.03)
    assert config.circuit_window_hours == pytest.approx(72.0)
    assert config.circuit_min_samples == 50
    assert config.warmup_min_samples == 10
    assert config.warmup_invalidation_rate_max == pytest.approx(0.30)


def test_config_rejects_non_positive_circuit_window():
    # 五轮评审③：负窗口使 since 落在未来 → 查询永无样本 → 熔断静默永久关闭（危险侧），
    # 必须失败关闭：非法配置带配置名抛 ValueError，而非静默失效
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_WINDOW_HOURS"):
        _config(circuit_window_hours=0.0)
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_WINDOW_HOURS"):
        _config(circuit_window_hours=-1.0)
    # "nan" 是合法 float 解析，_env_float 不走 except 回退，必须在构造期拦截
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_WINDOW_HOURS"):
        _config(circuit_window_hours=float("nan"))


def test_config_rejects_non_positive_min_samples():
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES"):
        _config(circuit_min_samples=0)
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES"):
        _config(warmup_min_samples=0)


def test_config_rejects_rate_outside_zero_one():
    with pytest.raises(ValueError, match="EXPERIMENT_INVALIDATED_RATE_MAX"):
        _config(invalidation_rate_max=1.5)
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_WARMUP_INVALIDATED_RATE_MAX"):
        _config(warmup_invalidation_rate_max=-0.1)


def test_config_rejects_epsilon_outside_zero_one():
    with pytest.raises(ValueError, match="EXPERIMENT_EPSILON_RETURNABLE"):
        _config(epsilon=1.2)
    with pytest.raises(ValueError, match="EXPERIMENT_EPSILON_RETURNABLE"):
        _config(epsilon=-0.01)


def test_config_rejects_non_positive_payload_ttl():
    with pytest.raises(ValueError, match="EXPERIMENT_PAYLOAD_TTL"):
        _config(payload_ttl_seconds=0)


def test_env_float_unparsable_raises_with_config_name(monkeypatch):
    # 六轮评审②：已设置但不可解析 → 带配置名 ValueError 失败关闭，
    # 不得静默回退默认值掩盖部署侧配置错误
    monkeypatch.setenv("EXPERIMENT_CIRCUIT_WINDOW_HOURS", "abc")
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_WINDOW_HOURS"):
        ReturnableConfig.from_env()


def test_env_int_unparsable_raises_with_config_name(monkeypatch):
    monkeypatch.setenv("EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES", "abc")
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES"):
        ReturnableConfig.from_env()


def test_env_int_rejects_decimal_string(monkeypatch):
    # "10.9" 不得经 float→int 被隐式截断为 10（六轮评审②）
    monkeypatch.setenv("EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES", "10.9")
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES"):
        ReturnableConfig.from_env()


def test_env_blank_treated_as_unset(monkeypatch):
    # 未设置/空白串视为未配置 → 默认值（区别于"已设置但不可解析"）
    monkeypatch.setenv("EXPERIMENT_CIRCUIT_WINDOW_HOURS", "   ")
    monkeypatch.setenv("EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES", "")
    config = ReturnableConfig.from_env()
    assert config.circuit_window_hours == pytest.approx(168.0)
    assert config.circuit_min_samples == 200


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-1", "101"])
def test_config_rejects_invalid_ai_threshold(monkeypatch, value):
    # 七轮评审①：硬门槛为 ai_score > ai_threshold，nan 使比较恒 False → AI 保护
    # 静默失效（危险侧）；业务量表 0-100（compute_ranking_score 以 100.0 为最差占位）
    monkeypatch.setenv("EXPERIMENT_AI_SCORE_THRESHOLD", value)
    with pytest.raises(ValueError, match="EXPERIMENT_AI_SCORE_THRESHOLD"):
        ReturnableConfig.from_env()


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-1"])
def test_config_rejects_invalid_margin_threshold(monkeypatch, value):
    # 七轮评审①：负值/-inf 使无显著领先的挑战者通过 margin（放水），
    # inf 永不返回挑战者，nan 恒不过且配置错误不可见
    monkeypatch.setenv("EXPERIMENT_MARGIN_THRESHOLD", value)
    with pytest.raises(ValueError, match="EXPERIMENT_MARGIN_THRESHOLD"):
        ReturnableConfig.from_env()


def test_config_rejects_warmup_not_below_circuit_min_samples():
    # 七轮评审②：warmup >= circuit 时预热分支恒假，预热保护静默失效
    # （#13 区间 warmup ≤ 有效样本 < circuit 为空集）；文档未定义"相等 = 关闭
    # 预热"语义，失败关闭要求严格小于
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES"):
        _config(circuit_min_samples=20, warmup_min_samples=200)
    with pytest.raises(ValueError, match="EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES"):
        _config(circuit_min_samples=20, warmup_min_samples=20)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-1", "101", "abc"])
def test_parse_ai_threshold_rejects_invalid(monkeypatch, value):
    # 八轮评审①：公共解析函数须与 ReturnableConfig 同一规则——shadow/returnable
    # 两路径共用，杜绝裸 float() 放行 nan/inf/负值/越界导致配置语义分裂
    monkeypatch.setenv("EXPERIMENT_AI_SCORE_THRESHOLD", value)
    with pytest.raises(ValueError, match="EXPERIMENT_AI_SCORE_THRESHOLD"):
        parse_ai_threshold()


def test_parse_ai_threshold_accepts_valid_and_default(monkeypatch):
    monkeypatch.setenv("EXPERIMENT_AI_SCORE_THRESHOLD", "80")
    assert parse_ai_threshold() == pytest.approx(80.0)
    monkeypatch.delenv("EXPERIMENT_AI_SCORE_THRESHOLD", raising=False)
    assert parse_ai_threshold() == pytest.approx(25.0)
    # 边界：0 与 100 合法
    monkeypatch.setenv("EXPERIMENT_AI_SCORE_THRESHOLD", "0")
    assert parse_ai_threshold() == pytest.approx(0.0)
    monkeypatch.setenv("EXPERIMENT_AI_SCORE_THRESHOLD", "100")
    assert parse_ai_threshold() == pytest.approx(100.0)


@pytest.mark.parametrize("value", ["abc", "0", "-1", "1.5"])
def test_parse_max_attempts_rejects_invalid(monkeypatch, value):
    # 九轮评审：0/-1 装配后使执行器 attempt_count >= max_attempts 首次异常即入 dead、
    # 重试保护失效；1.5 小数串由 _env_int 直接 int() 拒绝；abc 不可解析
    monkeypatch.setenv("EXPERIMENT_MAX_ATTEMPTS", value)
    with pytest.raises(ValueError, match="EXPERIMENT_MAX_ATTEMPTS"):
        parse_max_attempts()


def test_parse_max_attempts_accepts_valid_and_default(monkeypatch):
    monkeypatch.setenv("EXPERIMENT_MAX_ATTEMPTS", "5")
    assert parse_max_attempts() == 5
    monkeypatch.delenv("EXPERIMENT_MAX_ATTEMPTS", raising=False)
    assert parse_max_attempts() == 3
    # 边界：1 合法
    monkeypatch.setenv("EXPERIMENT_MAX_ATTEMPTS", "1")
    assert parse_max_attempts() == 1


# ---------------------------------------------------------------------------
# async 编排：决策链短路与双路择优
# ---------------------------------------------------------------------------

async def _choose(session, deps, config, *, genre="玄幻", champion_ai_score=10.0):
    return await choose_returnable_variant(
        session,
        subject_id="user-1",
        genre=genre,
        original_text=_ORIGINAL,
        champion_text=_REWRITE,
        champion_ai_score=champion_ai_score,
        model_id="m1",
        deps=deps,
        config=config,
    )


@pytest.mark.asyncio
async def test_disabled_returns_champion(session):
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=1.0)
    result = await _choose(session, deps, _config(enabled=False))
    assert result.returned_variant == "champion"
    assert result.returned_text == _REWRITE
    assert result.reason == "disabled"
    assert calls["rewrite"] == 0


@pytest.mark.asyncio
async def test_missing_bucket_secret_returns_champion(session):
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=1.0)
    result = await _choose(session, deps, _config(bucket_secret=""))
    assert result.returned_variant == "champion"
    assert result.reason == "missing_config"
    assert calls["rewrite"] == 0


@pytest.mark.asyncio
async def test_no_consent_returns_champion(session):
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=1.0, consent=False)
    result = await _choose(session, deps, _config())
    assert result.returned_variant == "champion"
    assert result.reason == "no_consent"
    assert calls["rewrite"] == 0


@pytest.mark.asyncio
async def test_circuit_open_returns_champion(session):
    _seed_returnable(session, "chg-a", "玄幻")
    now = datetime.now(timezone.utc)
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_CONFIRMED_WIN,
        count=1, serving_mode="returnable", finished_at=now,
    )
    _add_settled(
        session, challenger_id="chg-a", genre="玄幻", outcome=VERDICT_INVALIDATED_WIN,
        count=1, serving_mode="returnable", finished_at=now,
    )
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=1.0)
    result = await _choose(session, deps, _config(circuit_min_samples=2, warmup_min_samples=1))
    assert result.returned_variant == "champion"
    assert result.reason == "circuit_open"
    assert calls["rewrite"] == 0


@pytest.mark.asyncio
async def test_epsilon_miss_returns_champion(session):
    _seed_returnable(session, "chg-a", "玄幻")
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=1.0)
    result = await _choose(session, deps, _config(epsilon=0.0))
    assert result.returned_variant == "champion"
    assert result.reason == "epsilon_miss"
    assert calls["rewrite"] == 0


@pytest.mark.asyncio
async def test_no_returnable_challenger_returns_champion(session):
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=1.0)
    result = await _choose(session, deps, _config())
    assert result.returned_variant == "champion"
    assert result.reason == "no_challenger"
    assert calls["rewrite"] == 0


@pytest.mark.asyncio
async def test_challenger_wins_by_margin(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # 冠军 AI 分 24（<=阈值 25 过门槛），挑战者 AI 分 1 → 分差 0.4*(24-1)=9.2 >= margin 5
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=1.0)
    result = await _choose(session, deps, _config(), champion_ai_score=24.0)
    assert result.returned_variant == "challenger"
    assert result.returned_text == _REWRITE
    assert result.reason == "best_of_2"
    assert result.challenger_id == "chg-a"
    assert result.light_judge_result is not None
    assert result.light_judge_result["margin_passed"] is True
    assert calls["rewrite"] == 1
    assert calls["detect"] == 1
    assert calls["model_id"] == "m1"


@pytest.mark.asyncio
async def test_champion_wins_when_margin_not_passed(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # 冠军 10、挑战者 9 → 分差 0.4*(10-9)=0.4 < margin 5 → 回退冠军
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=9.0)
    result = await _choose(session, deps, _config(), champion_ai_score=10.0)
    assert result.returned_variant == "champion"
    assert result.returned_text == _REWRITE
    assert result.reason == "best_of_2"
    assert result.light_judge_result["margin_passed"] is False
    assert calls["rewrite"] == 1


@pytest.mark.asyncio
async def test_detector_unavailable_returns_champion(session):
    _seed_returnable(session, "chg-a", "玄幻")
    # detect_fn 返回 None → 检测不可用 → 硬门槛判失败 → 回退冠军
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=None)
    result = await _choose(session, deps, _config(), champion_ai_score=10.0)
    assert result.returned_variant == "champion"
    assert result.reason == "best_of_2"
    assert calls["rewrite"] == 1


@pytest.mark.asyncio
async def test_rewrite_exception_falls_back_to_champion(session):
    _seed_returnable(session, "chg-a", "玄幻")
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=1.0, rewrite_raises=True)
    result = await _choose(session, deps, _config(), champion_ai_score=24.0)
    assert result.returned_variant == "champion"
    assert result.returned_text == _REWRITE
    assert result.reason.startswith("error:")
    assert calls["rewrite"] == 1


# ---------------------------------------------------------------------------
# 子块 B：命中双路结果落库统计回流（persist_returnable_experiment）
# ---------------------------------------------------------------------------

@pytest.fixture()
def vault(tmp_path):
    return PayloadVault("test-payload-key", storage_dir=str(tmp_path / "vault"))


def _contract():
    return FrozenModelContract.freeze(
        resolved_model_id="m1",
        model_selection_source="prompt_combination",
        model_config_version="mcv1",
        prompt_version_id="v1",
        temperature=0.8,
    )


def _win_outcome():
    return BestOfTwoOutcome(
        returned_variant="challenger",
        returned_text=_REWRITE,
        reason="best_of_2",
        challenger_id="chg-a",
        light_judge_result={"margin_passed": True, "returned_variant": "challenger"},
        challenger_text=_REWRITE,
        challenger_ai_score=1.0,
    )


def _persist(session, outcome, config, vault, *, request_id="req-1"):
    return persist_returnable_experiment(
        session,
        outcome=outcome,
        subject_id="user-1",
        genre="玄幻",
        request_id=request_id,
        original_text=_ORIGINAL,
        champion_text=_REWRITE,
        champion_ai_score=10.0,
        contract=_contract(),
        champion_prompt_text="改写提示词-冠军",
        config=config,
        vault=vault,
    )


def test_persist_creates_returnable_pending_row(session, vault):
    _seed_returnable(session, "chg-a", "玄幻")
    exp_id = _persist(session, _win_outcome(), _config(payload_key="test-payload-key"), vault)
    assert exp_id is not None
    row = ExperimentRepository(session).get_by_experiment_id(exp_id)
    assert row.status == "pending"
    assert row.serving_mode == ServingMode.RETURNABLE.value
    assert row.challenger_id == "chg-a"
    assert row.resolved_model_id == "m1"
    assert row.prompt_version_id == "v1"
    payload = json.loads(vault.get(row.payload_ref))
    preset = payload["preset_challenger"]
    assert preset["challenger_text"] == _REWRITE
    assert preset["returned_variant"] == "challenger"
    assert preset["challenger_ai_score"] == pytest.approx(1.0)
    assert preset["light_judge_result"]["margin_passed"] is True


def test_persist_skips_non_best_of_2(session, vault):
    _seed_returnable(session, "chg-a", "玄幻")
    champion_outcome = BestOfTwoOutcome(
        returned_variant="champion", returned_text=_REWRITE, reason="epsilon_miss"
    )
    assert _persist(session, champion_outcome, _config(payload_key="test-payload-key"), vault) is None
    assert session.query(PromptExperiment).count() == 0


def test_persist_idempotent_on_settlement_key(session, vault):
    _seed_returnable(session, "chg-a", "玄幻")
    config = _config(payload_key="test-payload-key")
    first = _persist(session, _win_outcome(), config, vault, request_id="req-dup")
    second = _persist(session, _win_outcome(), config, vault, request_id="req-dup")
    assert first == second
    assert session.query(PromptExperiment).count() == 1


def test_persist_missing_payload_key_returns_none(session, vault):
    _seed_returnable(session, "chg-a", "玄幻")
    assert _persist(session, _win_outcome(), _config(payload_key=""), vault) is None
    assert session.query(PromptExperiment).count() == 0


def test_persist_missing_challenger_returns_none(session, vault):
    # 未 seed 挑战者行 → 无法取 prompt_hash → None
    assert _persist(session, _win_outcome(), _config(payload_key="test-payload-key"), vault) is None
    assert session.query(PromptExperiment).count() == 0


# ---------------------------------------------------------------------------
# 子块 C：reduce 端点编排（returnable_reduce = choose + persist 组合）
# ---------------------------------------------------------------------------

async def _reduce(session, deps, config, vault, *, champion_ai_score=10.0, request_id="req-c"):
    return await returnable_reduce(
        session,
        subject_id="user-1",
        genre="玄幻",
        request_id=request_id,
        original_text=_ORIGINAL,
        champion_text=_REWRITE,
        champion_ai_score=champion_ai_score,
        model_id="m1",
        contract=_contract(),
        champion_prompt_text="改写提示词-冠军",
        deps=deps,
        config=config,
        vault=vault,
    )


@pytest.mark.asyncio
async def test_returnable_reduce_challenger_win_persists(session, vault):
    _seed_returnable(session, "chg-a", "玄幻")
    # 冠军 24（过门槛）、挑战者 1 → margin 过 → 挑战者胜出并落一条 returnable 样本
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=1.0)
    outcome = await _reduce(
        session, deps, _config(payload_key="test-payload-key"), vault, champion_ai_score=24.0
    )
    assert outcome.returned_variant == "challenger"
    assert outcome.reason == "best_of_2"
    rows = session.query(PromptExperiment).all()
    assert len(rows) == 1
    assert rows[0].serving_mode == ServingMode.RETURNABLE.value
    assert rows[0].status == "pending"
    assert calls["rewrite"] == 1


@pytest.mark.asyncio
async def test_returnable_reduce_epsilon_miss_no_persist(session, vault):
    _seed_returnable(session, "chg-a", "玄幻")
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=1.0)
    outcome = await _reduce(
        session, deps, _config(payload_key="test-payload-key", epsilon=0.0), vault
    )
    assert outcome.returned_variant == "champion"
    assert outcome.reason == "epsilon_miss"
    assert calls["rewrite"] == 0
    assert session.query(PromptExperiment).count() == 0


@pytest.mark.asyncio
async def test_returnable_reduce_best_of_2_champion_still_persists(session, vault):
    _seed_returnable(session, "chg-a", "玄幻")
    # 冠军 10、挑战者 9 → margin 未过 → 返回冠军，但仍是 best_of_2 比较 → 落一条样本
    deps, calls = _make_deps(challenger_text=_REWRITE, challenger_score=9.0)
    outcome = await _reduce(
        session, deps, _config(payload_key="test-payload-key"), vault, champion_ai_score=10.0
    )
    assert outcome.returned_variant == "champion"
    assert outcome.reason == "best_of_2"
    assert session.query(PromptExperiment).count() == 1


# ---------------------------------------------------------------------------
# 人工开闸 approve_returnable（§14 第 8 步生产闭环：eligible → returnable）
# ---------------------------------------------------------------------------

def _seed_mode(session, challenger_id, genre, serving_mode):
    ChallengerRepository(session).upsert_challenger(
        challenger_id=challenger_id,
        genre=genre,
        prompt_text="改善句式结构，降低连续同构句比例",
        prompt_hash=f"sha256:{challenger_id}",
        strategy_desc="降低连续同构句比例",
        strategy_family="sentence",
        source_batch="batch_20260730_01",
        offline_gate_passed=True,
        offline_scores={},
        serving_mode=serving_mode,
    )
    session.commit()


def test_approve_returnable_from_eligible(session):
    _seed_mode(session, "chg-a", "玄幻", ServingMode.ELIGIBLE.value)
    row = approve_returnable(session, "chg-a", operator="prompt-admin", reason="首批放量")
    assert row is not None
    assert row.serving_mode == ServingMode.RETURNABLE.value
    # 服务层已 commit：重查持久生效
    persisted = ChallengerRepository(session).get_by_challenger_id("chg-a")
    assert persisted.serving_mode == ServingMode.RETURNABLE.value
    assert persisted.state_changed_at is not None


def test_approve_returnable_writes_audit_row(session):
    # 审计语义（五轮评审①）：operator + reason 必须与状态变更同事务落库，
    # 普通日志可轮转/丢失，不构成审计记录
    _seed_mode(session, "chg-audit", "都市", ServingMode.ELIGIBLE.value)
    approve_returnable(session, "chg-audit", operator="prompt-admin", reason="首批小流量放量")
    audits = (
        session.query(PromptChallengerStateTransition)
        .filter_by(challenger_id="chg-audit")
        .all()
    )
    assert len(audits) == 1
    audit = audits[0]
    assert audit.genre == "都市"
    assert audit.from_mode == ServingMode.ELIGIBLE.value
    assert audit.to_mode == ServingMode.RETURNABLE.value
    assert audit.operator == "prompt-admin"
    assert audit.reason == "首批小流量放量"
    assert audit.created_at is not None


def test_approve_returnable_rejects_non_eligible(session):
    # 开闸语义限定 eligible 出发（cooldown 恢复走既有状态机路径，不经人工开闸）
    _seed_mode(session, "chg-b", "玄幻", ServingMode.SHADOW.value)
    with pytest.raises(ValueError, match="eligible"):
        approve_returnable(session, "chg-b", operator="prompt-admin", reason="误操作")
    assert (
        ChallengerRepository(session).get_by_challenger_id("chg-b").serving_mode
        == ServingMode.SHADOW.value
    )
    # 拒绝时不得留下审计行（审计只记录真实发生的状态变更）
    assert session.query(PromptChallengerStateTransition).count() == 0


def test_approve_returnable_missing_returns_none(session):
    assert approve_returnable(session, "chg-nope", operator="prompt-admin", reason="任意") is None
    assert session.query(PromptChallengerStateTransition).count() == 0


def test_approve_returnable_rejects_blank_reason(session):
    # 五轮评审④：纯空白/换行 reason 无审计价值，服务层防御验证不依赖 HTTP 层
    _seed_mode(session, "chg-blank", "玄幻", ServingMode.ELIGIBLE.value)
    with pytest.raises(ValueError, match="审批原因"):
        approve_returnable(session, "chg-blank", operator="prompt-admin", reason="  \r\n\t ")
    # 状态未被改动、不留审计行
    assert (
        ChallengerRepository(session).get_by_challenger_id("chg-blank").serving_mode
        == ServingMode.ELIGIBLE.value
    )
    assert session.query(PromptChallengerStateTransition).count() == 0


def test_approve_returnable_rejects_overlong_reason(session):
    # 上限对齐审计表 reason String(500)，超长失败关闭而非静默截断
    _seed_mode(session, "chg-long", "玄幻", ServingMode.ELIGIBLE.value)
    with pytest.raises(ValueError, match="审批原因"):
        approve_returnable(session, "chg-long", operator="prompt-admin", reason="长" * 501)
    assert (
        ChallengerRepository(session).get_by_challenger_id("chg-long").serving_mode
        == ServingMode.ELIGIBLE.value
    )
    assert session.query(PromptChallengerStateTransition).count() == 0


def test_approve_returnable_normalizes_reason_newlines(session):
    # 换行/多余空白规范化为单个空格后落审计行，防日志与审计记录注入伪造行
    _seed_mode(session, "chg-norm", "玄幻", ServingMode.ELIGIBLE.value)
    approve_returnable(
        session, "chg-norm", operator="prompt-admin", reason="  首批\r\n小流量\n放量\t验证  "
    )
    audit = (
        session.query(PromptChallengerStateTransition)
        .filter_by(challenger_id="chg-norm")
        .one()
    )
    assert audit.reason == "首批 小流量 放量 验证"


def test_approve_returnable_concurrent_stale_read_single_audit(session, monkeypatch):
    # 六轮评审①：两管理员并发审批同一挑战者——B 在 A 读到 eligible 之后完成开闸，
    # A 的条件更新必须失败关闭：只有一个请求成功、全库仅一条 eligible → returnable 审计行
    _seed_mode(session, "chg-race", "玄幻", ServingMode.ELIGIBLE.value)
    other_session = sessionmaker(
        autocommit=False, autoflush=False, bind=session.get_bind()
    )()
    original_get = ChallengerRepository.get_by_challenger_id
    fired = {"done": False}

    def racing_get(self, challenger_id):
        row = original_get(self, challenger_id)
        # 仅拦截 A（session）的首次读取：读到 eligible 后让 B 抢先完成审批
        if self.session is session and challenger_id == "chg-race" and not fired["done"]:
            fired["done"] = True
            approve_returnable(
                other_session, "chg-race", operator="admin-b", reason="B 先完成审批"
            )
        return row

    monkeypatch.setattr(ChallengerRepository, "get_by_challenger_id", racing_get)
    try:
        with pytest.raises(ValueError, match="并发冲突"):
            approve_returnable(
                session, "chg-race", operator="admin-a", reason="A 基于陈旧读审批"
            )
    finally:
        other_session.close()
    # 只有 B 成功：仅一条审计行，且归属 B；最终状态 returnable
    audits = (
        session.query(PromptChallengerStateTransition)
        .filter_by(challenger_id="chg-race")
        .all()
    )
    assert len(audits) == 1
    assert audits[0].operator == "admin-b"
    assert audits[0].from_mode == ServingMode.ELIGIBLE.value
    assert audits[0].to_mode == ServingMode.RETURNABLE.value
    session.expire_all()
    assert (
        ChallengerRepository(session).get_by_challenger_id("chg-race").serving_mode
        == ServingMode.RETURNABLE.value
    )

