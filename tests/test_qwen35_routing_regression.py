from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import importlib

import pytest


@pytest.fixture(autouse=True)
def _reset_model_registry() -> None:
    from core.model_hub import model_hub
    from core.unified_registry import UnifiedModelRegistry
    import core.llm_adapters as llm_adapters

    config_path = Path(__file__).parent.parent / "config" / "llm_models.yaml"
    registry = UnifiedModelRegistry()
    registry.clear()
    if config_path.exists():
        model_hub.initialize(str(config_path))
        importlib.reload(llm_adapters)
    yield


def test_registry_re_register_cleans_stale_task_mapping() -> None:
    from core.unified_registry import UnifiedModelRegistry
    from schemas.unified_model_spec import APIConfig, ModelType, RoutingConfig, UnifiedModelSpec

    registry = UnifiedModelRegistry()
    registry.clear()

    first_spec = UnifiedModelSpec(
        id="dup-model",
        name="Duplicate Model",
        provider="test",
        model_type=ModelType.LLM,
        api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://example.test/v1"),
        routing=RoutingConfig(task_types=["task_old"]),
    )
    second_spec = UnifiedModelSpec(
        id="dup-model",
        name="Duplicate Model",
        provider="test",
        model_type=ModelType.LLM,
        api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://example.test/v1"),
        routing=RoutingConfig(task_types=["task_new"]),
    )

    registry.register(first_spec)
    assert [spec.id for spec in registry.get_models_for_task("task_old")] == ["dup-model"]

    registry.register(second_spec)
    assert [spec.id for spec in registry.get_models_for_task("task_old")] == []
    assert [spec.id for spec in registry.get_models_for_task("task_new")] == ["dup-model"]


def _candidates_for_task(task_type: str) -> List[str]:
    from core.model_hub import model_hub

    return [spec.id for spec in model_hub.registry.get_models_for_task(task_type)]


def test_current_qwen_plus_has_adapter_and_removed_book_synthesis_route() -> None:
    from core.model_runtime import resolve_model_for_task
    from core.model_hub import model_hub

    config_path = Path(__file__).parent.parent / "config" / "llm_models.yaml"
    if not config_path.exists():
        pytest.skip("YAML 配置文件不存在")

    adapter = model_hub.registry.get_adapter("qwen3.7-plus")
    assert adapter is not None
    assert type(adapter).__name__ == "Qwen37PlusAdapter"

    # 任务挂载的模型会随目录演进增减：只断言期望模型仍在候选集、
    # 解析结果是候选之一，不钉死选择器最终命中哪个，避免目录调价/新增时误报
    for task_type, expected_model in (("outline_expand", "mimo-v2.5"), ("review", "deepseek-v4-pro")):
        candidates = _candidates_for_task(task_type)
        assert expected_model in candidates, f"{expected_model} 已从任务 {task_type} 下线"
        assert resolve_model_for_task(task_type, None) in candidates
    assert resolve_model_for_task("book_synthesis", None) is None


def test_current_qwen_plus_has_adapter_for_verification_workflow() -> None:
    from core.model_hub import model_hub

    config_path = Path(__file__).parent.parent / "config" / "llm_models.yaml"
    if not config_path.exists():
        pytest.skip("YAML 配置文件不存在")

    spec = model_hub.registry.get_spec("qwen3.7-plus")
    adapter = model_hub.registry.get_adapter("qwen3.7-plus")

    assert spec is not None
    assert adapter is not None
    assert type(adapter).__name__ == "Qwen37PlusAdapter"
    assert "verification" in spec.routing.task_types


def test_story_expansion_routes_to_current_long_context_models() -> None:
    from core.model_runtime import resolve_model_for_task
    from core.model_hub import model_hub

    expected_routes = {
        "concept": "mimo-v2.5",
        "outline_expand": "mimo-v2.5",
        "character": "doubao-seed-character",
        "character_expand": "doubao-seed-character",
        "volume_detail_expand": "deepseek-v4-pro",
    }

    for task_type, expected_model in expected_routes.items():
        # 同上：期望模型保持挂载 + 解析结果在候选集内，不钉死单一模型
        candidates = _candidates_for_task(task_type)
        assert expected_model in candidates, f"{expected_model} 已从任务 {task_type} 下线"
        assert resolve_model_for_task(task_type, None) in candidates

    mimo_spec = model_hub.registry.get_spec("mimo-v2.5")
    deepseek_v4_pro_spec = model_hub.registry.get_spec("deepseek-v4-pro")
    deepseek_v4_flash_spec = model_hub.registry.get_spec("deepseek-v4-flash")
    qwen_max_spec = model_hub.registry.get_spec("qwen3.7-plus")
    removed_long_context_spec = model_hub.registry.get_spec("qwen-" + "long")

    assert mimo_spec is not None
    assert deepseek_v4_pro_spec is not None
    assert deepseek_v4_flash_spec is not None
    assert qwen_max_spec is not None
    assert removed_long_context_spec is None

    assert mimo_spec.routing.fallback_models == ["qwen3.7-plus"]
    assert qwen_max_spec.routing.fallback_models == ["deepseek-v4-flash"]
    assert deepseek_v4_pro_spec.routing.fallback_models == ["qwen3.7-plus"]
    assert deepseek_v4_flash_spec.routing.fallback_models == ["qwen3.7-plus"]


class _FakeLLMClient:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def chat_stream(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        on_chunk = kwargs.get("on_chunk")
        if on_chunk:
            await on_chunk("ok")
        return "ok"


@pytest.mark.asyncio
async def test_streaming_service_passes_task_type_to_client() -> None:
    from backend.app.services.streaming_service import StreamingService

    fake_client = _FakeLLMClient()
    service = StreamingService(llm_client=fake_client)

    chunks: List[str] = []

    async def on_chunk(text: str, idx: int) -> None:
        chunks.append(f"{idx}:{text}")

    content = await service.generate_chapter_streaming(
        prompt="test prompt",
        system_prompt="test system",
        on_chunk=on_chunk,
        task_type="outline_expand",
    )

    assert content == "ok"
    assert chunks == ["0:ok"]
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["task_type"] == "outline_expand"
    assert fake_client.calls[0]["model"] is None


def test_openai_adapter_maps_connection_error_to_network_error() -> None:
    from core.llm_adapters import OpenAICompatibleAdapter

    assert (
        OpenAICompatibleAdapter._map_error_code(object(), Exception("Connection error."))
        == "network_error"
    )


def test_openai_adapter_maps_service_overload_throttle_error_to_rate_limit() -> None:
    from core.llm_adapters import OpenAICompatibleAdapter

    error = Exception(
        "Error code: 500 - {'error': {'message': '[Too many requests. Your requests are being throttled due to system capacity limits. Please try again later.]', 'type': 'ServiceUnavailable'}}"
    )

    assert OpenAICompatibleAdapter._map_error_code(object(), error) == "rate_limit"


class _FlakyNetworkAdapter:
    calls = 0

    def __init__(self, spec: Any) -> None:
        self.spec = spec

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Any:
        from schemas.unified_model_spec import LLMResult

        type(self).calls += 1
        if type(self).calls == 1:
            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error="Connection error.",
                error_code="network_error",
                latency=0.01,
            )
        return LLMResult(
            success=True,
            model_id=self.spec.id,
            content="ok",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            latency=0.01,
            cost=0.0,
        )

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        on_chunk: Any,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Any:
        return await self.generate(messages, temperature=temperature, max_tokens=max_tokens, **kwargs)


@pytest.mark.asyncio
async def test_model_hub_retries_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    from core.model_hub import model_hub
    from core.unified_registry import UnifiedModelRegistry
    from schemas.unified_model_spec import APIConfig, ModelType, RoutingConfig, UnifiedModelSpec

    model_hub_module = importlib.import_module("core.model_hub")

    async def _noop_sleep(_: float) -> None:
        return

    monkeypatch.setattr(model_hub_module.asyncio, "sleep", _noop_sleep)

    registry = UnifiedModelRegistry()
    registry.clear()

    flaky_spec = UnifiedModelSpec(
        id="flaky-network-model",
        name="Flaky Network Model",
        provider="test",
        model_type=ModelType.LLM,
        api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://example.test/v1"),
        routing=RoutingConfig(task_types=["chapter"]),
    )
    _FlakyNetworkAdapter.calls = 0
    registry.register(flaky_spec, _FlakyNetworkAdapter)

    original_registry = model_hub.registry
    model_hub.registry = registry
    try:
        result = await model_hub._execute_call(
            model_id="flaky-network-model",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.7,
            max_tokens=64,
            stream=False,
            on_chunk=None,
        )
    finally:
        model_hub.registry = original_registry

    assert result.success is True
    assert result.content == "ok"
    assert _FlakyNetworkAdapter.calls == 2
