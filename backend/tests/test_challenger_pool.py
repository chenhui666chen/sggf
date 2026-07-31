"""
挑战者池纯逻辑测试（设计文档 §3.1 / §3.2 / §14 第 4 步）

覆盖：统一七项离线准入门槛、challenger_id/prompt_hash 生成、策略族分类。
纯函数，无 IO。
"""
import re

import pytest

from app.services.prompt_evolution.challenger_pool import (
    OfflineGateResult,
    classify_strategy_family,
    compute_prompt_hash,
    evaluate_offline_gate,
    find_forbidden_words,
    make_challenger_id,
)


# ============ prompt_hash ============

def test_prompt_hash_format_and_determinism():
    h1 = compute_prompt_hash("降低连续同构句比例的提示词")
    h2 = compute_prompt_hash("降低连续同构句比例的提示词")
    assert h1 == h2
    assert h1.startswith("sha256:")
    assert len(h1) == len("sha256:") + 16


def test_prompt_hash_sensitive_to_content():
    assert compute_prompt_hash("提示词A") != compute_prompt_hash("提示词B")


# ============ challenger_id ============

def test_challenger_id_format():
    cid = make_challenger_id("玄幻", "sha256:a1b2c3d4e5f6a7b8")
    assert re.match(r"^chg_玄幻_\d{8}_[0-9a-f]{4,}$", cid), cid


def test_challenger_id_deterministic_for_same_inputs():
    cid1 = make_challenger_id("玄幻", "sha256:a1b2c3d4e5f6a7b8", date_str="20260730")
    cid2 = make_challenger_id("玄幻", "sha256:a1b2c3d4e5f6a7b8", date_str="20260730")
    assert cid1 == cid2
    assert cid1 == "chg_玄幻_20260730_a1b2"


def test_challenger_id_differs_by_hash():
    a = make_challenger_id("玄幻", "sha256:aaaa1111bbbb2222", date_str="20260730")
    b = make_challenger_id("玄幻", "sha256:cccc3333dddd4444", date_str="20260730")
    assert a != b


# ============ strategy_family 分类 ============

def test_classify_sentence_structure():
    assert classify_strategy_family("降低连续同构句比例，调整句式长短") == "sentence_structure"


def test_classify_vocabulary():
    assert classify_strategy_family("替换高频华丽用词，改善措辞") == "vocabulary"


def test_classify_entity_compression():
    assert classify_strategy_family("压缩冗余的专名与实体重复") == "entity_compression"


def test_classify_rhythm():
    assert classify_strategy_family("调整段落节奏与停顿感") == "rhythm"


def test_classify_fallback_other():
    assert classify_strategy_family("完全无关的描述文本") == "other"


# ============ 禁用词检测 ============

def test_find_forbidden_words_hits():
    hits = find_forbidden_words("他震惊地看着这美轮美奂的景象")
    assert "震惊" in hits


def test_find_forbidden_words_clean():
    assert find_forbidden_words("平静的一天开始了") == []


# ============ 统一七项准入门槛 ============

def _good_kwargs(**overrides):
    data = dict(
        prompt_text="改善句式结构，保留题材语域",
        prompt_hash="sha256:aaaa1111bbbb2222",
        semantic_fidelity=88.0,
        fact_consistency=96.0,
        information_completeness=82.0,
        over_rewrite_risk="low",
        rewrite_texts=["平静的清晨，少年推开了木门。"],
        blocked_hashes=set(),
        review_available=True,
    )
    data.update(overrides)
    return data


def test_gate_all_pass():
    result = evaluate_offline_gate(**_good_kwargs())
    assert isinstance(result, OfflineGateResult)
    assert result.passed is True
    assert result.failed_gate is None
    assert result.scores["semantic_fidelity"] == 88.0


def test_gate_review_unavailable_blocks():
    result = evaluate_offline_gate(**_good_kwargs(review_available=False))
    assert result.passed is False
    assert result.failed_gate == "review_unavailable"


def test_gate_fidelity_below_threshold():
    result = evaluate_offline_gate(**_good_kwargs(semantic_fidelity=79.9))
    assert result.passed is False
    assert result.failed_gate == "semantic_fidelity"


def test_gate_fact_below_threshold():
    result = evaluate_offline_gate(**_good_kwargs(fact_consistency=89.0))
    assert result.passed is False
    assert result.failed_gate == "fact_consistency"


def test_gate_completeness_below_threshold():
    result = evaluate_offline_gate(**_good_kwargs(information_completeness=74.0))
    assert result.passed is False
    assert result.failed_gate == "information_completeness"


def test_gate_over_rewrite_risk_not_low():
    result = evaluate_offline_gate(**_good_kwargs(over_rewrite_risk="medium"))
    assert result.passed is False
    assert result.failed_gate == "over_rewrite_risk"


def test_gate_prompt_safety_blocks_unsafe():
    result = evaluate_offline_gate(**_good_kwargs(prompt_text="通过改名替换人物姓名来降低AI率"))
    assert result.passed is False
    assert result.failed_gate == "prompt_safety"


def test_gate_forbidden_words_in_rewrite():
    result = evaluate_offline_gate(
        **_good_kwargs(rewrite_texts=["他震惊地看着眼前的一切"])
    )
    assert result.passed is False
    assert result.failed_gate == "forbidden_words"


def test_gate_blocked_failed_variant():
    result = evaluate_offline_gate(
        **_good_kwargs(blocked_hashes={"sha256:aaaa1111bbbb2222"})
    )
    assert result.passed is False
    assert result.failed_gate == "failed_variant"


def test_gate_priority_safety_before_forbidden():
    """多个门槛同时失败时，按 §3.2 顺序返回第一个失败项"""
    result = evaluate_offline_gate(
        **_good_kwargs(
            semantic_fidelity=10.0,
            prompt_text="改名替换人物姓名",
            rewrite_texts=["震惊"],
        )
    )
    # 语义保真是第一道分数门槛，应最先失败
    assert result.failed_gate == "semantic_fidelity"
