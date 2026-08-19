"""提示词进化评估器样本级并行评估测试。

验证 evaluate_prompt 并行化后的三项不变式：
1. 样本确实并发执行且受信号量限流（不超过 EVALUATION_CONCURRENCY）；
2. 返回结果顺序与输入样本顺序一致；
3. 单样本异常不中断其他样本评估。
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution.evaluator import PromptEvaluator
from app.services.prompt_evolution.test_samples import TestSample


def _build_evaluator(rewrite_side_effect):
    """构造隔离真实 LLM/检测依赖的评估器。"""
    evaluator = PromptEvaluator()
    evaluator._rewrite_text = AsyncMock(side_effect=rewrite_side_effect)

    async def detect_by_content(text: str):
        # 改写产物带 rewrite_ 前缀，用于区分原始/改写检测
        if text.startswith("rewrite_"):
            return {"success": True, "ai_score": 30}
        return {"success": True, "ai_score": 80}

    evaluator.ai_detector = AsyncMock()
    evaluator.ai_detector.detect_ai_content = AsyncMock(side_effect=detect_by_content)
    evaluator.semantic_judge = AsyncMock()
    evaluator.semantic_judge.evaluate = AsyncMock(return_value={
        "available": False, "hard_fail": False, "hard_fail_reasons": [], "error": "mock",
    })
    return evaluator


def _make_samples(count: int):
    return [
        TestSample(sample_id=f"sample_{i}", text=f"原始文本片段{i}" * 50, genre="玄幻")
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_evaluate_prompt_runs_samples_concurrently_within_limit():
    """样本应并发评估，且最大并发不超过 EVALUATION_CONCURRENCY。"""
    active = 0
    max_active = 0
    order_lock = asyncio.Lock()

    async def rewrite(prompt, text, temperature, model_id=None, targeted_hint=""):
        nonlocal active, max_active
        async with order_lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        async with order_lock:
            active -= 1
        # 长度需过篇幅守门（原文400字→下限200字）
        return "rewrite_改写结果" * 30

    evaluator = _build_evaluator(rewrite)
    samples = _make_samples(6)

    avg_score, results = await evaluator.evaluate_prompt("prompt", samples)

    assert max_active >= 2, "样本未并发执行"
    assert max_active <= PromptEvaluator.EVALUATION_CONCURRENCY
    assert avg_score == 30.0
    assert len(results) == 6


@pytest.mark.asyncio
async def test_evaluate_prompt_preserves_sample_order():
    """并行执行下结果顺序必须与输入样本顺序一致。"""

    async def rewrite(prompt, text, temperature, model_id=None, targeted_hint=""):
        # 首个样本最慢完成，验证顺序不被完成顺序打乱
        if "片段0" in text:
            await asyncio.sleep(0.2)
        else:
            await asyncio.sleep(0.01)
        # 长度需过篇幅守门（原文400字→下限200字）
        return "rewrite_改写结果" * 30

    evaluator = _build_evaluator(rewrite)
    samples = _make_samples(4)

    _, results = await evaluator.evaluate_prompt("prompt", samples)

    assert [r.sample_id for r in results] == [s.sample_id for s in samples]


@pytest.mark.asyncio
async def test_evaluate_prompt_isolates_single_sample_failure():
    """单样本改写异常只影响该样本，其余样本正常产出结果。"""

    async def rewrite(prompt, text, temperature, model_id=None, targeted_hint=""):
        if "片段1" in text:
            raise RuntimeError("改写服务异常")
        # 长度需过篇幅守门（原文400字→下限200字）
        return "rewrite_改写结果" * 30

    evaluator = _build_evaluator(rewrite)
    samples = _make_samples(3)

    avg_score, results = await evaluator.evaluate_prompt("prompt", samples)

    assert [r.sample_id for r in results] == ["sample_0", "sample_1", "sample_2"]
    assert results[1].success is False
    assert "改写服务异常" in (results[1].error or "")
    assert results[0].success is True
    assert results[2].success is True
    assert avg_score == 30.0
