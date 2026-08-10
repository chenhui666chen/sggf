"""改写空响应重试测试：LLM 返回空/异常短内容时必须重试，不得直接判硬失败。

背景缺陷：_rewrite_text 对空响应无重试，改写模型偶发返回空串即导致样本
硬失败；历史题材评估中 3/4 样本空改写接连发生，变体与基线被批量取消资格。
"""
from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution.evaluator import PromptEvaluator


@pytest.mark.asyncio
async def test_empty_rewrite_is_retried_until_success():
    """首次空响应、第二次正常返回：应重试并拿到有效改写。"""
    evaluator = PromptEvaluator()
    evaluator.llm_client = AsyncMock()
    evaluator.llm_client.chat = AsyncMock(side_effect=["", "   ", "正常的改写结果文本内容"])

    result = await evaluator._rewrite_text("prompt", "原文内容", 0.7, model_id="model-x")

    assert "正常的改写结果文本内容" in result
    assert evaluator.llm_client.chat.await_count == 3


@pytest.mark.asyncio
async def test_persistent_empty_rewrite_exhausts_retries():
    """持续空响应：重试上限耗尽后返回空（由调用方判过短失败），不抛异常。"""
    evaluator = PromptEvaluator()
    evaluator.llm_client = AsyncMock()
    evaluator.llm_client.chat = AsyncMock(return_value="")

    result = await evaluator._rewrite_text("prompt", "原文内容", 0.7, model_id="model-x")

    assert result.strip() == ""
    assert evaluator.llm_client.chat.await_count == PromptEvaluator.REWRITE_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_normal_rewrite_is_not_retried():
    """正常响应只调用一次，不浪费改写调用。"""
    evaluator = PromptEvaluator()
    evaluator.llm_client = AsyncMock()
    evaluator.llm_client.chat = AsyncMock(return_value="一次成功的改写结果")

    result = await evaluator._rewrite_text("prompt", "原文内容", 0.7)

    assert "一次成功的改写结果" in result
    assert evaluator.llm_client.chat.await_count == 1
