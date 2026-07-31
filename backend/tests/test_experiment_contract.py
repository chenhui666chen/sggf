"""
实验契约冻结模块测试（设计文档 §4：模型冻结 / HMAC 分桶 / 版本体系 / serving_mode 状态机）
"""
import hashlib
import hmac

import pytest

from app.services.prompt_evolution.experiment_contract import (
    BUCKET_COUNT,
    EVOLUTION_GENRES,
    EXPERIMENT_EVALUATION_POLICY_VERSION,
    LIGHT_JUDGE_VERSION,
    FrozenModelContract,
    ServingMode,
    assert_transition,
    assign_bucket,
    bucket_hits_epsilon,
    can_transition,
    select_challenger_index,
)


SECRET = "test-bucket-secret"


# ============ 进化题材契约常量（单一来源） ============

def test_evolution_genres_contract():
    # 7 题材、无重复、非空字符串；API 层与任务层均须引用本常量（同一性断言见
    # test_evolution_scheduler_api.py，避免契约测试引入 celery/api 重依赖）
    assert isinstance(EVOLUTION_GENRES, list)
    assert len(EVOLUTION_GENRES) == 7
    assert len(set(EVOLUTION_GENRES)) == len(EVOLUTION_GENRES)
    assert all(isinstance(g, str) and g for g in EVOLUTION_GENRES)


# ============ HMAC 确定性分桶 ============

def test_assign_bucket_is_deterministic_across_calls():
    a = assign_bucket(SECRET, "user-1", "玄幻", "exp-2026")
    b = assign_bucket(SECRET, "user-1", "玄幻", "exp-2026")
    assert a == b


def test_assign_bucket_matches_hmac_sha256_spec():
    # 规范：HMAC-SHA256(secret, "subject:genre:experiment") 前 4 字节大端 % 10000
    digest = hmac.new(
        SECRET.encode("utf-8"),
        "user-1:玄幻:exp-2026".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected = int.from_bytes(digest[:4], "big") % BUCKET_COUNT
    assert assign_bucket(SECRET, "user-1", "玄幻", "exp-2026") == expected


def test_assign_bucket_range_and_input_sensitivity():
    buckets = {
        assign_bucket(SECRET, f"user-{i}", "玄幻", "exp-2026") for i in range(50)
    }
    assert all(0 <= b < BUCKET_COUNT for b in buckets)
    # 50 个不同主体不应全部落入同一桶
    assert len(buckets) > 1
    # 题材、实验 ID 变化均影响结果
    base = assign_bucket(SECRET, "user-1", "玄幻", "exp-2026")
    assert (
        assign_bucket(SECRET, "user-1", "言情", "exp-2026") != base
        or assign_bucket(SECRET, "user-1", "玄幻", "exp-2027") != base
    )


def test_select_challenger_index_deterministic_and_domain_separated():
    idx1 = select_challenger_index(SECRET, "user-1", "玄幻", "exp-2026", 3)
    idx2 = select_challenger_index(SECRET, "user-1", "玄幻", "exp-2026", 3)
    assert idx1 == idx2
    assert 0 <= idx1 < 3
    # 域分离：挑战者索引不应恒等于分桶结果的简单取模（至少在多组输入上不全相同）
    diverged = any(
        select_challenger_index(SECRET, f"u{i}", "玄幻", "e", 10)
        != assign_bucket(SECRET, f"u{i}", "玄幻", "e") % 10
        for i in range(20)
    )
    assert diverged


def test_select_challenger_index_rejects_non_positive_count():
    with pytest.raises(ValueError):
        select_challenger_index(SECRET, "user-1", "玄幻", "exp-2026", 0)


def test_bucket_hits_epsilon_boundary():
    assert bucket_hits_epsilon(0, 0.05) is True
    assert bucket_hits_epsilon(499, 0.05) is True
    assert bucket_hits_epsilon(500, 0.05) is False
    assert bucket_hits_epsilon(9999, 0.0) is False
    assert bucket_hits_epsilon(9999, 1.0) is True


# ============ 模型冻结契约 ============

def test_frozen_model_contract_is_immutable():
    contract = FrozenModelContract.freeze(
        resolved_model_id="deepseek-v4-pro",
        model_selection_source="prompt_combination",
        model_config_version="2026-07-29T10:00:00",
        prompt_version_id="v-玄幻-001",
        temperature=0.8,
        max_tokens=4096,
    )
    with pytest.raises(Exception):
        contract.resolved_model_id = "other"  # type: ignore[misc]


def test_provider_parameters_hash_stable_for_same_params():
    kwargs = dict(
        resolved_model_id="deepseek-v4-pro",
        model_selection_source="admin_selected",
        model_config_version="v1",
        prompt_version_id="p1",
        temperature=0.8,
        max_tokens=4096,
    )
    c1 = FrozenModelContract.freeze(**kwargs)
    c2 = FrozenModelContract.freeze(**kwargs)
    assert c1.provider_parameters_hash == c2.provider_parameters_hash


def test_provider_parameters_hash_changes_with_sampling_params():
    base = dict(
        resolved_model_id="deepseek-v4-pro",
        model_selection_source="admin_selected",
        model_config_version="v1",
        prompt_version_id="p1",
        max_tokens=4096,
    )
    c1 = FrozenModelContract.freeze(temperature=0.8, **base)
    c2 = FrozenModelContract.freeze(temperature=0.7, **base)
    assert c1.provider_parameters_hash != c2.provider_parameters_hash


def test_provider_parameters_hash_includes_extra_provider_params():
    base = dict(
        resolved_model_id="m",
        model_selection_source="genre_model_summary",
        model_config_version="v1",
        prompt_version_id="p1",
        temperature=0.8,
        max_tokens=4096,
    )
    c1 = FrozenModelContract.freeze(**base)
    c2 = FrozenModelContract.freeze(**base, extra_provider_params={"top_p": 0.9})
    assert c1.provider_parameters_hash != c2.provider_parameters_hash


# ============ serving_mode 状态机 ============

def test_normal_promotion_path_is_allowed():
    assert can_transition(ServingMode.SHADOW, ServingMode.ELIGIBLE)
    assert can_transition(ServingMode.ELIGIBLE, ServingMode.RETURNABLE)
    assert can_transition(ServingMode.RETURNABLE, ServingMode.CHAMPION)


def test_skipping_states_is_rejected():
    assert not can_transition(ServingMode.SHADOW, ServingMode.RETURNABLE)
    assert not can_transition(ServingMode.SHADOW, ServingMode.CHAMPION)
    assert not can_transition(ServingMode.ELIGIBLE, ServingMode.CHAMPION)


def test_any_active_state_can_be_suspended_or_eliminated():
    for state in (ServingMode.SHADOW, ServingMode.ELIGIBLE, ServingMode.RETURNABLE):
        assert can_transition(state, ServingMode.SUSPENDED)
        assert can_transition(state, ServingMode.ELIMINATED)
        assert can_transition(state, ServingMode.COOLDOWN)


def test_eliminated_is_terminal():
    for target in ServingMode:
        if target is ServingMode.ELIMINATED:
            continue
        assert not can_transition(ServingMode.ELIMINATED, target)


def test_suspended_resumes_only_to_shadow():
    # 暂停恢复须重新经历校准，不得直接回到 returnable
    assert can_transition(ServingMode.SUSPENDED, ServingMode.SHADOW)
    assert not can_transition(ServingMode.SUSPENDED, ServingMode.RETURNABLE)


def test_cooldown_resumes_to_pre_cooldown_states():
    # 冷却是基础设施故障，恢复到冷却前的活跃状态（不含 champion）
    assert can_transition(ServingMode.COOLDOWN, ServingMode.SHADOW)
    assert can_transition(ServingMode.COOLDOWN, ServingMode.ELIGIBLE)
    assert can_transition(ServingMode.COOLDOWN, ServingMode.RETURNABLE)
    assert not can_transition(ServingMode.COOLDOWN, ServingMode.CHAMPION)


def test_assert_transition_raises_on_illegal_move():
    with pytest.raises(ValueError):
        assert_transition(ServingMode.SHADOW, ServingMode.CHAMPION)
    # 合法转换不抛异常
    assert_transition(ServingMode.SHADOW, ServingMode.ELIGIBLE)


# ============ 版本体系 ============

def test_version_constants_are_nonempty_strings():
    assert isinstance(LIGHT_JUDGE_VERSION, str) and LIGHT_JUDGE_VERSION
    assert isinstance(EXPERIMENT_EVALUATION_POLICY_VERSION, str)
    assert EXPERIMENT_EVALUATION_POLICY_VERSION
