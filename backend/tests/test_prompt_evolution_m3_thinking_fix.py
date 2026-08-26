"""思考模型改写空响应/超时修复守卫（TDD）。

背景1（M3 空响应）：M3 adaptive 思考在改写任务中消耗巨量输出 token（实测
reasoning 最高 27731 字 / completion 11833），逼近 max_tokens=16384 总预算后
触发 finish_reason=length、content 为空且 HTTP 200，适配器 success=True 掩盖
根因，评估器连续空响应拖垮整个批次。

背景2（seed-evolving 超时）：doubao-seed-evolving 常开思考（thinking.type=
enabled），改写长文本时思考+生成总耗时超过 default_timeout=300s，非流式调用
卡在等待响应头触发 httpx.ReadTimeout，每次改写先白烧 300s 再靠 600s 重试
兜底，批次吞吐腰斩。

守卫三条防线：
1. 进化改写链路对思考模型集合（M3 + seed-evolving）显式关闭思考
   （改写是风格转换任务，不依赖推理），且不影响其他改写模型与默认路由。
2. 适配器对 success=True 但 content 为空的响应记录诊断日志
   （finish_reason / reasoning_content / usage），封死此类盲区复发。
3. 适配器参数构建对 ARK 系模型的 extra_body 覆盖同样无残留。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.prompt_evolution.evaluator import PromptEvaluator

M3_MODEL_ID = "MiniMax/MiniMax-M3"
EVOLVING_MODEL_ID = "doubao-seed-evolving"


@pytest.mark.asyncio
async def test_m3_rewrite_disables_thinking():
    """M3 改写调用必须透传 thinking disabled，覆盖 default_params 的 adaptive。"""
    evaluator = PromptEvaluator()
    evaluator.llm_client = AsyncMock()
    evaluator.llm_client.chat = AsyncMock(return_value="正常的改写结果文本内容")

    await evaluator._rewrite_text("prompt", "原文内容", 0.7, model_id=M3_MODEL_ID)

    kwargs = evaluator.llm_client.chat.await_args.kwargs
    # M3 走百炼端点：thinking.disabled + enable_thinking=False 双参数互保险
    assert kwargs.get("extra_body") == {
        "thinking": {"type": "disabled"}, "enable_thinking": False,
    }


@pytest.mark.asyncio
async def test_seed_evolving_rewrite_disables_thinking():
    """seed-evolving 常开思考导致改写 300s 超时，改写链路必须关闭思考。"""
    evaluator = PromptEvaluator()
    evaluator.llm_client = AsyncMock()
    evaluator.llm_client.chat = AsyncMock(return_value="正常的改写结果文本内容")

    await evaluator._rewrite_text("prompt", "原文内容", 0.7, model_id=EVOLVING_MODEL_ID)

    kwargs = evaluator.llm_client.chat.await_args.kwargs
    assert kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_other_model_rewrite_disables_thinking():
    """全链路禁思考（2026-08-23 用户指令）：doubao 系同样注入 disabled。"""
    evaluator = PromptEvaluator()
    evaluator.llm_client = AsyncMock()
    evaluator.llm_client.chat = AsyncMock(return_value="正常的改写结果文本内容")

    await evaluator._rewrite_text("prompt", "原文内容", 0.7, model_id="doubao-seed-character")

    kwargs = evaluator.llm_client.chat.await_args.kwargs
    # doubao 系拒绝 reasoning_effort+thinking 同传（400 实测），只传 thinking
    assert kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_default_route_rewrite_disables_thinking():
    """全链路禁思考：默认路由（无 model_id）也注入禁思考参数。"""
    evaluator = PromptEvaluator()
    evaluator.llm_client = AsyncMock()
    evaluator.llm_client.chat = AsyncMock(return_value="正常的改写结果文本内容")

    await evaluator._rewrite_text("prompt", "原文内容", 0.7)

    kwargs = evaluator.llm_client.chat.await_args.kwargs
    assert kwargs.get("extra_body") == {
        "thinking": {"type": "disabled"}, "enable_thinking": False,
    }


def test_extra_body_passthrough_overrides_default_thinking():
    """适配器参数构建：调用方 extra_body 完整覆盖 default_params 的思考设置。"""
    from core.llm_adapters import OpenAICompatibleAdapter
    from schemas.unified_model_spec import APIConfig, ModelType, UnifiedModelSpec

    spec = UnifiedModelSpec(
        id="MiniMax/MiniMax-M3",
        name="MiniMax M3",
        provider="minimax",
        model_type=ModelType.LLM,
        api_config=APIConfig(
            api_key_env="DASHSCOPE_API_KEY",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        default_params={
            "temperature": 0.7,
            "max_tokens": 16384,
            "thinking": {"type": "adaptive"},
        },
    )
    adapter = OpenAICompatibleAdapter.__new__(OpenAICompatibleAdapter)
    adapter.spec = spec

    params = adapter._build_completion_params(
        messages=[{"role": "user", "content": "改写"}],
        temperature=0.7,
        max_tokens=None,
        extra_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
    )

    assert params["extra_body"]["thinking"] == {"type": "disabled"}
    # default_params 的 adaptive 不得残留
    assert params["extra_body"] == {"thinking": {"type": "disabled"}}


def test_extra_body_passthrough_overrides_ark_enabled_thinking():
    """ARK 系模型（seed-evolving 常开思考）的 extra_body 覆盖同样无残留。"""
    from core.llm_adapters import OpenAICompatibleAdapter
    from schemas.unified_model_spec import APIConfig, ModelType, UnifiedModelSpec

    spec = UnifiedModelSpec(
        id="doubao-seed-evolving",
        name="Doubao Seed Evolving",
        provider="volcengine",
        model_type=ModelType.LLM,
        api_config=APIConfig(
            api_key_env="DOUBAO_API_KEY",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        ),
        default_params={
            "temperature": 0.7,
            "max_tokens": 16384,
            "thinking": {"type": "enabled"},
        },
    )
    adapter = OpenAICompatibleAdapter.__new__(OpenAICompatibleAdapter)
    adapter.spec = spec

    params = adapter._build_completion_params(
        messages=[{"role": "user", "content": "改写"}],
        temperature=0.7,
        max_tokens=None,
        extra_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
    )

    # default_params 的 enabled 不得残留
    assert params["extra_body"] == {"thinking": {"type": "disabled"}}


def test_empty_content_response_logs_diagnostic(caplog):
    """success=True 但 content 为空时必须记录诊断信息（finish_reason/思考/usage）。"""
    from core.llm_adapters import OpenAICompatibleAdapter

    adapter = OpenAICompatibleAdapter.__new__(OpenAICompatibleAdapter)
    adapter.spec = SimpleNamespace(id="MiniMax/MiniMax-M3")
    message = SimpleNamespace(content="", reasoning_content="思考内容" * 100)
    usage = SimpleNamespace(prompt_tokens=3000, completion_tokens=16384, total_tokens=19384)

    with caplog.at_level("WARNING"):
        adapter._log_empty_response_diagnostic(
            message=message,
            finish_reason="length",
            usage=usage,
        )

    joined = "".join(caplog.messages)
    assert "finish_reason=length" in joined
    assert "16384" in joined
