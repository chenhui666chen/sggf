"""优化调用思考关闭守卫（TDD）。

背景缺陷：optimize_prompt 走 TaskType.REVIEW_CHECK 路由到 deepseek-pro，
其 default_params 为 thinking.enabled + reasoning_effort.high，思考 tokens
会吃掉 max_tokens=8192 预算，触发 finish_reason=length、输出为空（实测日志
"响应中未匹配到 ===IMPROVED_PROMPT=== 完整段，响应长度=0"），优化轮白跑。

守卫：optimize_prompt 的 LLM 调用显式透传 extra_body 关闭思考，覆盖
deepseek-pro 默认，且不影响其他路由与调用路径。
"""
import inspect

import pytest

from app.services.prompt_evolution.meta_optimizer import MetaOptimizer


def test_optimize_prompt_passes_thinking_disabled():
    """optimize_prompt 调用 LLM 必须显式关闭思考（防 deepseek-pro 吃掉预算）。

    三合一参数注入重构后（core.model_resolution.build_thinking_disabled_extra_body
    按模型族分发互斥参数），断言改为检查注入函数调用仍存在。
    """
    source = inspect.getsource(MetaOptimizer.optimize_prompt)

    assert "build_thinking_disabled_extra_body" in source
    assert "extra_body" in source


def test_dsv4_pro_disabled_thinking_overrides_default():
    """deepseek-pro 默认 thinking 开启；调用方 extra_body disabled 必须覆盖
    并清除 reasoning_effort，否则思考仍会吃掉优化输出预算。"""
    from core.llm_adapters import DeepSeekV4ProAdapter
    from core.unified_registry import UnifiedModelRegistry

    spec = UnifiedModelRegistry().get_spec("deepseek-pro")
    adapter = DeepSeekV4ProAdapter.__new__(DeepSeekV4ProAdapter)
    adapter.spec = spec

    params = adapter._build_completion_params(
        messages=[{"role": "user", "content": "x"}],
        temperature=0.7,
        max_tokens=8192,
        extra_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
    )

    assert params["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in params