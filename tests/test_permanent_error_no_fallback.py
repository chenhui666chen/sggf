"""永久错误不重试、不回退的行为锁定。

缺 API Key（`client_not_initialized`）与请求本身非法（`invalid_request`）都属于
"同 prompt 再发一百遍也一样失败"。被当成瞬时故障时，`model_hub` 会烧完重试预算，
再静默换成别家模型并返回 `success=True`（2026-08-23 九模型实测污染、2026-10-09
doubao 文本线缺 key 两次踩坑的真实成因）。

回显文案只抄上游报文，不写上游模型真名——退役门禁把真名在业务层的出现算待改引用。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from schemas.unified_model_spec import (
    APIConfig,
    LLMConstraints,
    LLMResult,
    ModelType,
    RoutingConfig,
    UnifiedModelSpec,
)

# 火山方舟越界回显
ARK_OUT_OF_RANGE_ECHO = (
    "Error code: 400 - {'error': {'code': 'InvalidParameter', 'message': 'The parameter "
    "`max_tokens` specified in the request are not valid: integer above maximum value, "
    "expected a value <= 262144, but got 999999 instead'}}"
)
# 百炼强制思考模型的参数组合拒绝
THINKING_RESTRICTED_ECHO = (
    "Error code: 400 - {'error': {'message': '<400> InternalError.Algo.InvalidParameter: "
    "The value of the enable_thinking parameter is restricted to True.', "
    "'type': 'invalid_request_error', 'code': 'invalid_parameter_error'}}"
)
# 同为 400 但真属限流，必须仍然走退避而不是判永久
RATE_LIMIT_ECHO = (
    "Error code: 400 - {'error': {'code': 'ServiceUnavailable', 'message': "
    "'Too many requests, system is at capacity limits'}}"
)


class _StatusError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


def _map(error: Exception) -> str:
    from core.llm_adapters import OpenAICompatibleAdapter

    return OpenAICompatibleAdapter._map_error_code(None, error)


def test_out_of_range_echo_maps_to_invalid_request():
    assert _map(_StatusError(ARK_OUT_OF_RANGE_ECHO, 400)) == "invalid_request"


def test_restricted_thinking_echo_maps_to_invalid_request():
    assert _map(_StatusError(THINKING_RESTRICTED_ECHO, 400)) == "invalid_request"


def test_bad_request_without_param_marker_stays_unknown():
    """没有参数类文案的 400 仍是未知错误，保守地保留重试与回退。"""
    assert _map(_StatusError("Error code: 400 - something odd happened", 400)) == "unknown_error"


def test_rate_limit_wording_keeps_priority_over_invalid_request():
    """判序必须在限流之后：ServiceUnavailable / capacity limits 也是 400 家族。"""
    assert _map(_StatusError(RATE_LIMIT_ECHO, 400)) == "rate_limit"


def test_connection_error_is_not_invalid_request():
    assert _map(Exception("Connection error.")) == "network_error"


def _missing_key_result(model_id: str) -> LLMResult:
    return LLMResult(
        success=False,
        model_id=model_id,
        error="客户端未初始化",
        error_code="client_not_initialized",
    )


def _invalid_request_result(model_id: str) -> LLMResult:
    return LLMResult(
        success=False,
        model_id=model_id,
        error=ARK_OUT_OF_RANGE_ECHO,
        error_code="invalid_request",
    )


def _transient_result(model_id: str) -> LLMResult:
    return LLMResult(
        success=False,
        model_id=model_id,
        error="Error code: 500 - InternalError",
        error_code="unknown_error",
    )


def _build_hub_registry(failing_result_factory):
    """指名模型给足 3 次重试预算，回退模型成功；返回 (hub, 主适配器, 回退适配器)。"""
    from core.model_hub import model_hub
    from core.unified_registry import UnifiedModelRegistry

    registry = UnifiedModelRegistry()
    registry.clear()
    model_hub.registry = registry

    def spec(model_id: str, name: str, fallbacks: list[str]) -> UnifiedModelSpec:
        return UnifiedModelSpec(
            id=model_id,
            name=name,
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(
                api_key_env="TEST_API_KEY",
                base_url="https://api.test.com/v1",
                default_max_retries=3,
            ),
            constraints=LLMConstraints(supports_max_retries=True),
            routing=RoutingConfig(task_types=["permanent_error_test"], fallback_models=fallbacks),
        )

    registry.register(spec("primary-permanent", "Primary Permanent", ["fallback-permanent"]))
    registry.register(spec("fallback-permanent", "Fallback Permanent", []))

    primary_adapter = Mock()
    primary_adapter.generate = AsyncMock(return_value=failing_result_factory("primary-permanent"))
    fallback_adapter = Mock()
    fallback_adapter.generate = AsyncMock(
        return_value=LLMResult(success=True, model_id="fallback-permanent", content="ok")
    )

    adapters = {"primary-permanent": primary_adapter, "fallback-permanent": fallback_adapter}
    return model_hub, registry, adapters, primary_adapter, fallback_adapter


async def _call_hub(model_hub, registry, adapters):
    with patch.object(registry, "get_adapter", side_effect=lambda mid: adapters.get(mid)):
        return await model_hub._execute_call(
            model_id="primary-permanent",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.7,
            max_tokens=None,
            stream=False,
            on_chunk=None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory",
    [_missing_key_result, _invalid_request_result],
    ids=["client_not_initialized", "invalid_request"],
)
async def test_permanent_errors_never_retry_nor_switch_vendor(restored_llm_registry, factory):
    model_hub, registry, adapters, primary_adapter, fallback_adapter = _build_hub_registry(factory)

    result = await _call_hub(model_hub, registry, adapters)

    assert result.success is False
    assert result.model_id == "primary-permanent", "永久错误不许静默换成别家模型"
    assert primary_adapter.generate.await_count == 1, "永久错误不该烧完重试预算"
    assert fallback_adapter.generate.await_count == 0


@pytest.mark.asyncio
async def test_transient_unknown_error_still_falls_back(restored_llm_registry):
    """反向锁：不能把兜底的 unknown_error 也判永久，否则真瞬时故障失去韧性。"""
    model_hub, registry, adapters, primary_adapter, fallback_adapter = _build_hub_registry(
        _transient_result
    )

    result = await _call_hub(model_hub, registry, adapters)

    assert result.success is True
    assert result.model_id == "fallback-permanent"
    assert primary_adapter.generate.await_count == 3
    assert fallback_adapter.generate.await_count == 1
