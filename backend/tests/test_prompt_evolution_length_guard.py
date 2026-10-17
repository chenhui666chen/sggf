"""反缩短守门测试：防止改写大幅缩短换取朱雀盲区0分的进化假象。

背景缺陷：evaluator 仅设 50 字绝对下限，改写缩短到朱雀盲区（约300字以下
返回0分）时被误读为"99→0 完美降分"，平均AI得分=0.0 写入历史成为最佳版本；
同时提示词版本含"删除连接词/空洞表达"指令且无篇幅约束，形成缩短正反馈。

守门三要素：
1. 评估器确定性篇幅守门（改写不得低于 max(600, 原文长度*50%)）；
2. 变体提示词与元优化器指令携带篇幅对齐约束；
3. 预置经验库禁止"以删减篇幅换低AI率"。
"""
from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution import meta_optimizer
from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.meta_optimizer import MetaOptimizer
from app.services.prompt_evolution.novel_rules import (
    PRESET_EFFECTIVE_STRATEGIES,
    PRESET_FORBIDDEN_PATTERNS,
)
from app.services.prompt_evolution.test_samples import TestSample


def _build_evaluator(rewrite_return: str):
    evaluator = PromptEvaluator()
    evaluator._rewrite_text = AsyncMock(return_value=rewrite_return)

    async def detect_by_content(text: str):
        # 改写产物带 rewrite_ 前缀：返回0分模拟朱雀盲区；原始文本返回正常高分
        if text.startswith("rewrite_"):
            return {"success": True, "ai_score": 0}
        return {"success": True, "ai_score": 80}

    evaluator.ai_detector = AsyncMock()
    evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=detect_by_content)
    evaluator.semantic_judge = AsyncMock()
    evaluator.semantic_judge.evaluate = AsyncMock(return_value={
        # 🔧 2026-10-16：评审不可用的样本不再算成功（未测量≠合格），
        # 故这些聚焦长度/并发的用例改用一份**有效且通过**的评审，
        # 避免把评审失效混进被测逻辑里。
        "available": True, "hard_fail": False, "hard_fail_reasons": [],
        "semantic_fidelity": {"score": 90},
        "fact_consistency": {"score": 95},
        "information_completeness": {"score": 85},
        "readability": {"score": 90},
        "writing_naturalness": {"score": 85},
        "genre_consistency": {"score": 88},
        "over_rewrite_risk": "low", "over_rewrite_reason": "", "confidence": 0.9,
    })
    return evaluator


@pytest.mark.asyncio
async def test_severely_shrunk_rewrite_is_rejected_before_detection():
    """3000字样本被缩到1000字（<50%下限）必须判失败，朱雀0分不得被采纳。"""
    original = "剧情文本内容" * 500  # 3000字
    sample = TestSample(sample_id="s1", text=original, genre="玄幻")
    evaluator = _build_evaluator("rewrite_" + "改" * 993)  # 1000字改写

    avg_score, results = await evaluator.evaluate_prompt("prompt", [sample])

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].rewritten_ai_score is None, "朱雀盲区0分不得计入"
    assert "篇幅" in (results[0].error or "")
    # 唯一失败时无成功样本，平均分回退中性值而非0分假象
    assert avg_score == 100.0
    # 守门拦截后不得再对改写文本发起朱雀检测
    for call in evaluator.ai_detector.detect_ai_content.await_args_list:
        assert not call.args[0].startswith("rewrite_")


@pytest.mark.asyncio
async def test_moderately_shortened_rewrite_passes_length_gate():
    """3000字样本缩到1600字（>50%下限1500）应通过守门正常评估。"""
    original = "剧情文本内容" * 500  # 3000字
    sample = TestSample(sample_id="s1", text=original, genre="玄幻")
    evaluator = _build_evaluator("rewrite_" + "改" * 1593)  # 1600字改写

    avg_score, results = await evaluator.evaluate_prompt("prompt", [sample])

    assert results[0].success is True
    assert avg_score == 0.0  # mock检测0分，守门不拦合规改写


@pytest.mark.asyncio
async def test_short_original_is_not_over_constrained():
    """短样本（<1200字）不受绝对下限误伤，仅按原长50%守门。"""
    original = "短文本内容" * 60  # 300字
    sample = TestSample(sample_id="s1", text=original, genre="玄幻")
    evaluator = _build_evaluator("rewrite_" + "改" * 243)  # 250字改写（83%）

    _, results = await evaluator.evaluate_prompt("prompt", [sample])

    assert results[0].success is True


@pytest.mark.asyncio
async def test_variant_prompt_carries_length_alignment_constraint_once():
    """变体提示词必须携带篇幅对齐约束（幂等追加）。"""
    optimizer = MetaOptimizer()
    optimizer._generate_random_exploration_strategies = AsyncMock(
        return_value=["交替句首结构，打破连续相同句法骨架"]
    )
    optimizer._generate_variant_from_strategy = AsyncMock(
        return_value="请交替使用主语开头与状语前置。"
    )

    variants = await optimizer.generate_prompt_variants("安全基础提示词", 1)

    variant_prompt, _ = variants[0]
    assert meta_optimizer.VARIANT_LENGTH_MARKER in variant_prompt
    assert variant_prompt.count(meta_optimizer.VARIANT_LENGTH_MARKER) == 1
    assert "篇幅" in variant_prompt


@pytest.mark.asyncio
async def test_optimizer_instruction_requires_length_alignment():
    """元优化器每轮指令必须包含篇幅对齐要求，引导改进方向不删内容。"""
    optimizer = MetaOptimizer()
    optimizer.experience.effective_strategies = ["原有安全经验"]
    optimizer.llm_client = AsyncMock()
    optimizer.llm_client.chat = AsyncMock(return_value="""
===EFFECTIVE_STRATEGIES===
无
===EFFECTIVE_STRATEGIES_END===
===INEFFECTIVE_STRATEGIES===
无
===INEFFECTIVE_STRATEGIES_END===
===FORBIDDEN_PATTERNS===
无
===FORBIDDEN_PATTERNS_END===
===ANALYSIS===
这是一段足够长的合规分析内容。
===ANALYSIS_END===
===IMPROVED_PROMPT===
保持事实不变，减少模板化连接词。
===IMPROVED_PROMPT_END===
""")

    from app.services.prompt_evolution.models import PromptVersion
    await optimizer.optimize_prompt(
        PromptVersion(prompt_text="原有安全提示词", evaluation_results=[]), 30, []
    )

    sent_messages = optimizer.llm_client.chat.await_args.kwargs["messages"]
    assert any("篇幅" in m["content"] for m in sent_messages)


def test_preset_experiences_forbid_shrinking_for_detection_evasion():
    """预置经验库必须覆盖反缩短方向。"""
    combined = "\n".join(PRESET_EFFECTIVE_STRATEGIES + PRESET_FORBIDDEN_PATTERNS)
    assert "篇幅" in combined
    # 禁止模式明确禁止以删减换低AI率
    assert any("篇幅" in p for p in PRESET_FORBIDDEN_PATTERNS)
    # 有效策略包含篇幅对齐方向
    assert any("篇幅" in s for s in PRESET_EFFECTIVE_STRATEGIES)
