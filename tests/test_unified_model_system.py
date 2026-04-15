# -*- coding: utf-8 -*-
"""
统一模型调度中心测试套件

测试内容：
1. 模型规格定义测试
2. 模型注册中心测试
3. LLM 适配器测试
4. ModelHub 调度测试
5. 兼容层测试
"""

import pytest
import asyncio
import types
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
import tempfile
import yaml

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestUnifiedModelSpec:
    """测试统一模型规格定义"""

    def test_model_type_enum(self):
        """测试模型类型枚举"""
        from schemas.unified_model_spec import ModelType

        assert ModelType.LLM.value == "llm"
        assert ModelType.IMAGE.value == "image"
        assert ModelType.VIDEO.value == "video"
        assert ModelType.AUDIO.value == "audio"

    def test_dispatch_strategy_enum(self):
        """测试调度策略枚举"""
        from schemas.unified_model_spec import DispatchStrategy

        assert DispatchStrategy.AUTO.value == "auto"
        assert DispatchStrategy.QUALITY.value == "quality"
        assert DispatchStrategy.COST.value == "cost"
        assert DispatchStrategy.SPEED.value == "speed"

    def test_llm_capability_creation(self):
        """测试 LLM 能力创建"""
        from schemas.unified_model_spec import LLMCapability, SupportLevel

        capability = LLMCapability(
            name="creative",
            level=SupportLevel.NATIVE,
            score=0.9,
            description="创意写作能力强"
        )

        assert capability.name == "creative"
        assert capability.level == SupportLevel.NATIVE
        assert capability.score == 0.9

    def test_llm_constraints_creation(self):
        """测试 LLM 约束创建"""
        from schemas.unified_model_spec import LLMConstraints

        constraints = LLMConstraints(
            max_context_tokens=32000,
            max_output_tokens=8192,
            supports_streaming=True,
            supports_function_call=True
        )

        assert constraints.max_context_tokens == 32000
        assert constraints.max_output_tokens == 8192
        assert constraints.supports_streaming is True

    def test_api_config_creation(self):
        """测试 API 配置创建"""
        from schemas.unified_model_spec import APIConfig

        config = APIConfig(
            api_key_env="DASHSCOPE_API_KEY",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_timeout=120
        )

        assert config.api_key_env == "DASHSCOPE_API_KEY"
        assert config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_routing_config_creation(self):
        """测试路由配置创建"""
        from schemas.unified_model_spec import RoutingConfig

        routing = RoutingConfig(
            task_types=["chapter", "dialogue"],
            priority=1,
            fallback_models=["deepseek-chat"],
            weight=1.0,
            enabled=True
        )

        assert "chapter" in routing.task_types
        assert routing.priority == 1
        assert "deepseek-chat" in routing.fallback_models

    def test_performance_profile_creation(self):
        """测试性能配置创建"""
        from schemas.unified_model_spec import PerformanceProfile

        perf = PerformanceProfile(
            quality_score=8.5,
            avg_latency_seconds=2.5,
            cost_per_1k_input_tokens=0.004,
            cost_per_1k_output_tokens=0.012
        )

        assert perf.quality_score == 8.5
        assert perf.avg_latency_seconds == 2.5

    def test_unified_model_spec_creation(self):
        """测试完整模型规格创建"""
        from schemas.unified_model_spec import (
            UnifiedModelSpec, ModelType, ModelStatus,
            LLMCapability, LLMConstraints, APIConfig,
            RoutingConfig, PerformanceProfile, SupportLevel
        )

        spec = UnifiedModelSpec(
            id="test-model",
            name="Test Model",
            provider="test",
            model_type=ModelType.LLM,
            status=ModelStatus.ACTIVE,
            capabilities=[
                LLMCapability(name="creative", level=SupportLevel.NATIVE, score=0.9)
            ],
            constraints=LLMConstraints(max_context_tokens=32000),
            api_config=APIConfig(api_key_env="TEST_API_KEY"),
            routing=RoutingConfig(task_types=["test"]),
            performance=PerformanceProfile(quality_score=8.0)
        )

        assert spec.id == "test-model"
        assert spec.provider == "test"
        assert spec.model_type == ModelType.LLM
        assert len(spec.capabilities) == 1

    def test_unified_model_spec_to_dict(self):
        """测试模型规格序列化"""
        from schemas.unified_model_spec import UnifiedModelSpec, ModelType

        spec = UnifiedModelSpec(
            id="test-model",
            name="Test Model",
            provider="test",
            model_type=ModelType.LLM
        )

        data = spec.to_dict()
        assert data["id"] == "test-model"
        assert data["model_type"] == "llm"

    def test_llm_result_creation(self):
        """测试 LLM 结果创建"""
        from schemas.unified_model_spec import LLMResult

        result = LLMResult(
            success=True,
            content="Hello, World!",
            model_id="test-model",
            usage={"input_tokens": 10, "output_tokens": 5}
        )

        assert result.success is True
        assert result.content == "Hello, World!"
        assert result.model_id == "test-model"


class TestUnifiedModelRegistry:
    """测试统一模型注册中心"""

    def test_registry_singleton(self):
        """测试注册中心单例模式"""
        from core.unified_registry import UnifiedModelRegistry

        registry1 = UnifiedModelRegistry()
        registry2 = UnifiedModelRegistry()

        assert registry1 is registry2

    def test_register_llm_model(self):
        """测试注册 LLM 模型"""
        from core.unified_registry import UnifiedModelRegistry
        from schemas.unified_model_spec import UnifiedModelSpec, ModelType

        registry = UnifiedModelRegistry()
        registry.clear()

        spec = UnifiedModelSpec(
            id="test-llm-model",
            name="Test LLM Model",
            provider="test",
            model_type=ModelType.LLM
        )

        registry.register(spec)

        retrieved = registry.get_spec("test-llm-model")
        assert retrieved is not None
        assert retrieved.id == "test-llm-model"

    def test_select_best_model(self):
        """测试选择最佳模型"""
        from core.unified_registry import UnifiedModelRegistry
        from schemas.unified_model_spec import (
            UnifiedModelSpec, ModelType, RoutingConfig, PerformanceProfile
        )

        registry = UnifiedModelRegistry()
        registry.clear()

        spec1 = UnifiedModelSpec(
            id="model-a",
            name="Model A",
            provider="test",
            model_type=ModelType.LLM,
            routing=RoutingConfig(task_types=["chapter"], priority=2),
            performance=PerformanceProfile(quality_score=7.0)
        )

        spec2 = UnifiedModelSpec(
            id="model-b",
            name="Model B",
            provider="test",
            model_type=ModelType.LLM,
            routing=RoutingConfig(task_types=["chapter"], priority=1),
            performance=PerformanceProfile(quality_score=8.5)
        )

        registry.register(spec1)
        registry.register(spec2)

        best = registry.select_best_model("chapter")
        assert best is not None
        assert best.id == "model-b"

    def test_get_all_task_types(self):
        """测试获取所有任务类型"""
        from core.unified_registry import UnifiedModelRegistry
        from schemas.unified_model_spec import UnifiedModelSpec, ModelType, RoutingConfig

        registry = UnifiedModelRegistry()
        registry.clear()

        registry.register(UnifiedModelSpec(
            id="model-1",
            name="Model 1",
            provider="test",
            model_type=ModelType.LLM,
            routing=RoutingConfig(task_types=["chapter", "dialogue"])
        ))

        task_types = registry.get_all_task_types()
        assert "chapter" in task_types
        assert "dialogue" in task_types


class TestLLMAdapters:
    """测试 LLM 适配器"""

    def test_openai_compatible_adapter_creation(self):
        """测试 OpenAI 兼容适配器创建"""
        from core.llm_adapters import OpenAICompatibleAdapter
        from schemas.unified_model_spec import UnifiedModelSpec, ModelType, APIConfig

        spec = UnifiedModelSpec(
            id="test-adapter",
            name="Test Adapter",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(
                api_key_env="TEST_API_KEY",
                base_url="https://api.test.com/v1"
            )
        )

        with patch.dict('os.environ', {'TEST_API_KEY': 'test-key'}):
            adapter = OpenAICompatibleAdapter(spec)
            assert adapter.spec.id == "test-adapter"

    def test_adapter_capability_check(self):
        """测试能力检查"""
        from core.llm_adapters import OpenAICompatibleAdapter
        from schemas.unified_model_spec import (
            UnifiedModelSpec, ModelType, LLMCapability, SupportLevel, APIConfig
        )

        spec = UnifiedModelSpec(
            id="test-adapter",
            name="Test Adapter",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://api.test.com/v1"),
            capabilities=[
                LLMCapability(name="creative", level=SupportLevel.NATIVE, score=0.9),
                LLMCapability(name="reasoning", level=SupportLevel.EMULATED, score=0.5)
            ]
        )

        with patch.dict('os.environ', {'TEST_API_KEY': 'test-key'}):
            adapter = OpenAICompatibleAdapter(spec)

            assert adapter.has_capability("creative") is True
            assert adapter.has_capability("reasoning") is True
            assert adapter.has_capability("vision") is False

    def test_adapter_supports_streaming(self):
        """测试流式支持检查"""
        from core.llm_adapters import OpenAICompatibleAdapter
        from schemas.unified_model_spec import UnifiedModelSpec, ModelType, LLMConstraints, APIConfig

        spec_with_streaming = UnifiedModelSpec(
            id="streaming-model",
            name="Streaming Model",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://api.test.com/v1"),
            constraints=LLMConstraints(supports_streaming=True)
        )

        spec_without_streaming = UnifiedModelSpec(
            id="no-streaming-model",
            name="No Streaming Model",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://api.test.com/v1"),
            constraints=LLMConstraints(supports_streaming=False)
        )

        with patch.dict('os.environ', {'TEST_API_KEY': 'test-key'}):
            adapter_with = OpenAICompatibleAdapter(spec_with_streaming)
            adapter_without = OpenAICompatibleAdapter(spec_without_streaming)

            assert adapter_with.supports_streaming() is True
            assert adapter_without.supports_streaming() is False

    def test_adapter_disables_sdk_retry(self):
        """测试 OpenAI 兼容适配器关闭 SDK 内置重试。"""
        from core.llm_adapters import OpenAICompatibleAdapter
        from schemas.unified_model_spec import UnifiedModelSpec, ModelType, APIConfig

        captured_client_kwargs = {}

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                captured_client_kwargs.update(kwargs)

        class FakeTimeout:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class FakeAsyncClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_openai = types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)
        fake_httpx = types.SimpleNamespace(AsyncClient=FakeAsyncClient, Timeout=FakeTimeout)

        spec = UnifiedModelSpec(
            id="test-adapter",
            name="Test Adapter",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(
                api_key_env="TEST_API_KEY",
                base_url="https://api.test.com/v1",
                default_timeout=45,
            ),
        )

        with patch.dict('os.environ', {'TEST_API_KEY': 'test-key'}):
            with patch.dict('sys.modules', {'openai': fake_openai, 'httpx': fake_httpx}):
                OpenAICompatibleAdapter(spec)

        assert captured_client_kwargs["max_retries"] == 0

    @pytest.mark.asyncio
    async def test_adapter_omits_max_tokens_when_not_explicitly_requested(self):
        from core.llm_adapters import OpenAICompatibleAdapter
        from schemas.unified_model_spec import UnifiedModelSpec, ModelType, APIConfig, LLMConstraints

        captured_request_kwargs = {}

        class FakeCompletions:
            async def create(self, **kwargs):
                captured_request_kwargs.update(kwargs)
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"))],
                    usage=None,
                )

        class FakeChat:
            def __init__(self):
                self.completions = FakeCompletions()

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.chat = FakeChat()

        class FakeTimeout:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class FakeAsyncClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_openai = types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)
        fake_httpx = types.SimpleNamespace(AsyncClient=FakeAsyncClient, Timeout=FakeTimeout)

        spec = UnifiedModelSpec(
            id="test-adapter",
            name="Test Adapter",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(
                api_key_env="TEST_API_KEY",
                base_url="https://api.test.com/v1",
            ),
            constraints=LLMConstraints(max_output_tokens=65536),
        )

        with patch.dict('os.environ', {'TEST_API_KEY': 'test-key'}):
            with patch.dict('sys.modules', {'openai': fake_openai, 'httpx': fake_httpx}):
                adapter = OpenAICompatibleAdapter(spec)
                result = await adapter.generate(
                    messages=[{"role": "user", "content": "hello"}],
                    temperature=0.7,
                )

        assert result.success is True
        assert "max_tokens" not in captured_request_kwargs

    @pytest.mark.asyncio
    async def test_adapter_uses_request_model_override(self):
        from core.llm_adapters import OpenAICompatibleAdapter
        from schemas.unified_model_spec import UnifiedModelSpec, ModelType, APIConfig

        captured_request_kwargs = {}

        class FakeCompletions:
            async def create(self, **kwargs):
                captured_request_kwargs.update(kwargs)
                return types.SimpleNamespace(
                    choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"))],
                    usage=None,
                )

        class FakeChat:
            def __init__(self):
                self.completions = FakeCompletions()

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.chat = FakeChat()

        class FakeTimeout:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class FakeAsyncClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_openai = types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)
        fake_httpx = types.SimpleNamespace(AsyncClient=FakeAsyncClient, Timeout=FakeTimeout)

        spec = UnifiedModelSpec(
            id="deepseek-reasoner",
            name="DeepSeek R1",
            provider="deepseek",
            model_type=ModelType.LLM,
            api_config=APIConfig(
                api_key_env="TEST_API_KEY",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            default_params={"request_model": "deepseek-r1"},
        )

        with patch.dict('os.environ', {'TEST_API_KEY': 'test-key'}):
            with patch.dict('sys.modules', {'openai': fake_openai, 'httpx': fake_httpx}):
                adapter = OpenAICompatibleAdapter(spec)
                result = await adapter.generate(
                    messages=[{"role": "user", "content": "hello"}],
                    temperature=0.7,
                )

        assert result.success is True
        assert captured_request_kwargs["model"] == "deepseek-r1"
        assert "request_model" not in captured_request_kwargs.get("extra_body", {})


class TestModelHub:
    """测试 ModelHub"""

    def test_model_hub_singleton(self):
        """测试 ModelHub 单例模式"""
        from core.model_hub import ModelHub

        hub1 = ModelHub()
        hub2 = ModelHub()

        assert hub1 is hub2

    def test_model_hub_initialize(self):
        """测试 ModelHub 初始化"""
        from core.model_hub import model_hub
        from core.unified_registry import UnifiedModelRegistry

        registry = UnifiedModelRegistry()
        registry.clear()

        config_content = {
            "llm_models": [
                {
                    "id": "test-hub-model",
                    "name": "Test Hub Model",
                    "provider": "test",
                    "model_type": "llm",
                    "routing": {
                        "task_types": ["test_task"],
                        "priority": 1
                    }
                }
            ]
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_content, f)
            config_path = f.name

        try:
            model_hub.initialize(config_path)

            spec = model_hub.select_model("test_task")
            assert spec is not None
            assert spec.id == "test-hub-model"
        finally:
            Path(config_path).unlink()

    @pytest.mark.asyncio
    async def test_model_hub_uses_spec_default_max_retries(self):
        """测试 ModelHub 默认按模型配置中的 default_max_retries 重试。"""
        from core.model_hub import model_hub
        from core.unified_registry import UnifiedModelRegistry
        from schemas.unified_model_spec import (
            UnifiedModelSpec,
            ModelType,
            APIConfig,
            RoutingConfig,
            LLMConstraints,
            LLMResult,
        )

        registry = UnifiedModelRegistry()
        registry.clear()
        model_hub.registry = registry

        spec = UnifiedModelSpec(
            id="retry-test-model",
            name="Retry Test Model",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(
                api_key_env="TEST_API_KEY",
                base_url="https://api.test.com/v1",
                default_max_retries=2,
            ),
            constraints=LLMConstraints(supports_max_retries=True),
            routing=RoutingConfig(task_types=["retry_test"]),
        )
        registry.register(spec)

        adapter = Mock()
        adapter.generate = AsyncMock(
            return_value=LLMResult(
                success=False,
                model_id="retry-test-model",
                error="Request timed out.",
                error_code="timeout",
            )
        )

        with patch.object(registry, "get_adapter", return_value=adapter):
            result = await model_hub._execute_call(
                model_id="retry-test-model",
                messages=[{"role": "user", "content": "hello"}],
                temperature=0.7,
                max_tokens=None,
                stream=False,
                on_chunk=None,
            )

        assert result.success is False
        assert adapter.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_model_hub_increases_timeout_budget_after_timeout(self, monkeypatch: pytest.MonkeyPatch):
        import importlib
        from core.model_hub import model_hub
        from core.unified_registry import UnifiedModelRegistry
        from schemas.unified_model_spec import (
            UnifiedModelSpec,
            ModelType,
            APIConfig,
            RoutingConfig,
            LLMConstraints,
            LLMResult,
        )

        model_hub_module = importlib.import_module("core.model_hub")

        async def _noop_sleep(_: float) -> None:
            return

        monkeypatch.setattr(model_hub_module.asyncio, "sleep", _noop_sleep)

        registry = UnifiedModelRegistry()
        registry.clear()

        spec = UnifiedModelSpec(
            id="retry-timeout-model",
            name="Retry Timeout Model",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(
                api_key_env="TEST_API_KEY",
                base_url="https://api.test.com/v1",
                default_timeout=120,
                default_max_retries=2,
            ),
            constraints=LLMConstraints(
                supports_max_retries=True,
                supports_timeout_param=True,
                max_output_tokens=65536,
            ),
            routing=RoutingConfig(task_types=["retry_timeout_test"]),
        )
        registry.register(spec)

        call_timeouts = []

        async def _generate(**kwargs):
            call_timeouts.append(kwargs.get("timeout"))
            if len(call_timeouts) == 1:
                return LLMResult(
                    success=False,
                    model_id="retry-timeout-model",
                    error="Request timed out.",
                    error_code="timeout",
                )
            return LLMResult(
                success=True,
                model_id="retry-timeout-model",
                content="ok",
                usage={},
                latency=0.0,
                cost=0.0,
            )

        adapter = Mock()
        adapter.generate = AsyncMock(side_effect=_generate)

        original_registry = model_hub.registry
        model_hub.registry = registry
        try:
            with patch.object(registry, "get_adapter", return_value=adapter):
                result = await model_hub._execute_call(
                    model_id="retry-timeout-model",
                    messages=[{"role": "user", "content": "hello"}],
                    temperature=0.7,
                    max_tokens=20000,
                    stream=False,
                    on_chunk=None,
                )
        finally:
            model_hub.registry = original_registry

        assert result.success is True
        assert call_timeouts == [None, 240]

    @pytest.mark.asyncio
    async def test_model_hub_increases_explicit_timeout_budget_after_timeout(self, monkeypatch: pytest.MonkeyPatch):
        import importlib
        from core.model_hub import model_hub
        from core.unified_registry import UnifiedModelRegistry
        from schemas.unified_model_spec import (
            UnifiedModelSpec,
            ModelType,
            APIConfig,
            RoutingConfig,
            LLMConstraints,
            LLMResult,
        )

        model_hub_module = importlib.import_module("core.model_hub")

        async def _noop_sleep(_: float) -> None:
            return

        monkeypatch.setattr(model_hub_module.asyncio, "sleep", _noop_sleep)

        registry = UnifiedModelRegistry()
        registry.clear()

        spec = UnifiedModelSpec(
            id="retry-explicit-timeout-model",
            name="Retry Explicit Timeout Model",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(
                api_key_env="TEST_API_KEY",
                base_url="https://api.test.com/v1",
                default_timeout=120,
                default_max_retries=2,
            ),
            constraints=LLMConstraints(
                supports_max_retries=True,
                supports_timeout_param=True,
                max_output_tokens=65536,
            ),
            routing=RoutingConfig(task_types=["retry_explicit_timeout_test"]),
            default_params={"max_tokens": 32768},
        )
        registry.register(spec)

        call_timeouts = []

        async def _generate(**kwargs):
            call_timeouts.append(kwargs.get("timeout"))
            if len(call_timeouts) == 1:
                return LLMResult(
                    success=False,
                    model_id="retry-explicit-timeout-model",
                    error="Request timed out.",
                    error_code="timeout",
                )
            return LLMResult(
                success=True,
                model_id="retry-explicit-timeout-model",
                content="ok",
                usage={},
                latency=0.0,
                cost=0.0,
            )

        adapter = Mock()
        adapter.generate = AsyncMock(side_effect=_generate)

        original_registry = model_hub.registry
        model_hub.registry = registry
        try:
            with patch.object(registry, "get_adapter", return_value=adapter):
                result = await model_hub._execute_call(
                    model_id="retry-explicit-timeout-model",
                    messages=[{"role": "user", "content": "hello"}],
                    temperature=0.7,
                    max_tokens=None,
                    stream=False,
                    on_chunk=None,
                    timeout=120,
                )
        finally:
            model_hub.registry = original_registry

        assert result.success is True
        assert call_timeouts == [120, 240]

    @pytest.mark.asyncio
    async def test_model_hub_disables_retry_for_models_without_retry_support(self):
        """测试不支持重试的模型仅尝试一次后立即回退。"""
        from core.model_hub import model_hub
        from core.unified_registry import UnifiedModelRegistry
        from schemas.unified_model_spec import (
            UnifiedModelSpec,
            ModelType,
            APIConfig,
            RoutingConfig,
            LLMConstraints,
            LLMResult,
        )

        registry = UnifiedModelRegistry()
        registry.clear()
        model_hub.registry = registry

        primary_spec = UnifiedModelSpec(
            id="primary-no-retry",
            name="Primary No Retry",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(
                api_key_env="TEST_API_KEY",
                base_url="https://api.test.com/v1",
                default_max_retries=5,
            ),
            constraints=LLMConstraints(supports_max_retries=False),
            routing=RoutingConfig(task_types=["fallback_test"], fallback_models=["fallback-model"]),
        )
        fallback_spec = UnifiedModelSpec(
            id="fallback-model",
            name="Fallback Model",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(
                api_key_env="TEST_API_KEY",
                base_url="https://api.test.com/v1",
                default_max_retries=2,
            ),
            constraints=LLMConstraints(supports_max_retries=True),
            routing=RoutingConfig(task_types=["fallback_test"]),
        )
        registry.register(primary_spec)
        registry.register(fallback_spec)

        primary_adapter = Mock()
        primary_adapter.generate = AsyncMock(
            return_value=LLMResult(
                success=False,
                model_id="primary-no-retry",
                error="Connection error.",
                error_code="unknown_error",
            )
        )
        fallback_adapter = Mock()
        fallback_adapter.generate = AsyncMock(
            return_value=LLMResult(
                success=True,
                model_id="fallback-model",
                content="ok",
            )
        )

        def get_adapter(model_id: str):
            if model_id == "primary-no-retry":
                return primary_adapter
            if model_id == "fallback-model":
                return fallback_adapter
            return None

        with patch.object(registry, "get_adapter", side_effect=get_adapter):
            result = await model_hub._execute_call(
                model_id="primary-no-retry",
                messages=[{"role": "user", "content": "hello"}],
                temperature=0.7,
                max_tokens=None,
                stream=False,
                on_chunk=None,
            )

        assert result.success is True
        assert result.model_id == "fallback-model"
        assert primary_adapter.generate.await_count == 1
        assert fallback_adapter.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_model_hub_reroutes_failed_catalog_model_when_healthier_candidate_exists(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """测试模型档案快照标记失败时，ModelHub 会优先切到同任务的健康候选。"""
        from core.model_hub import model_hub
        from core.unified_registry import UnifiedModelRegistry
        from schemas.unified_model_spec import (
            UnifiedModelSpec,
            ModelType,
            APIConfig,
            RoutingConfig,
            LLMResult,
        )

        recent_verified_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        snapshot_path = tmp_path / "model_catalog_runtime.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "failed-model": {
                            "verification_status": "failed",
                            "last_verified_at": recent_verified_at,
                        },
                        "healthy-model": {
                            "verification_status": "verified",
                            "last_verified_at": recent_verified_at,
                        },
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

        registry = UnifiedModelRegistry()
        registry.clear()
        model_hub.registry = registry

        failed_spec = UnifiedModelSpec(
            id="failed-model",
            name="Failed Model",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://api.test.com/v1"),
            routing=RoutingConfig(task_types=["chapter"], fallback_models=["healthy-model"]),
        )
        healthy_spec = UnifiedModelSpec(
            id="healthy-model",
            name="Healthy Model",
            provider="test",
            model_type=ModelType.LLM,
            api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://api.test.com/v1"),
            routing=RoutingConfig(task_types=["chapter"]),
        )
        registry.register(failed_spec)
        registry.register(healthy_spec)

        captured: dict[str, str] = {}

        async def fake_execute_call(*, model_id, **kwargs):
            captured["model_id"] = model_id
            return LLMResult(success=True, model_id=model_id, content="ok")

        monkeypatch.setattr(model_hub, "_execute_call", fake_execute_call)

        result = await model_hub.call(
            messages=[{"role": "user", "content": "hello"}],
            task_type="chapter",
            model="failed-model",
        )

        assert result.success is True
        assert result.model_id == "healthy-model"
        assert captured["model_id"] == "healthy-model"
        assert result.metadata["requested_model_id"] == "failed-model"
        assert result.metadata["resolved_model_id"] == "healthy-model"
        assert result.metadata["rerouted"] is True
        assert result.metadata["routing_reason"] == "catalog_verification_failed_recent"

    def test_model_hub_get_model_info_exposes_catalog_routing_signal(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        """测试 ModelHub 模型详情会附带模型档案路由信号。"""
        from core.model_hub import model_hub
        from core.unified_registry import UnifiedModelRegistry
        from schemas.unified_model_spec import UnifiedModelSpec, ModelType, APIConfig, RoutingConfig

        snapshot_path = tmp_path / "model_catalog_runtime.json"
        recent_verified_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        snapshot_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "info-model": {
                            "verification_status": "verified",
                            "last_verified_at": recent_verified_at,
                        }
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

        registry = UnifiedModelRegistry()
        registry.clear()
        model_hub.registry = registry
        registry.register(
            UnifiedModelSpec(
                id="info-model",
                name="Info Model",
                provider="test",
                model_type=ModelType.LLM,
                api_config=APIConfig(api_key_env="TEST_API_KEY", base_url="https://api.test.com/v1"),
                routing=RoutingConfig(task_types=["chapter"]),
            )
        )

        info = model_hub.get_model_info("info-model")

        assert info is not None
        assert info["catalog_routing"]["verification_status"] == "verified"
        assert info["catalog_routing"]["blocked"] is False


class TestCompatibility:
    """测试统一运行时兼容能力"""

    def test_task_type_enum_and_normalization(self):
        """测试任务类型枚举和值归一化。"""
        from core.model_resolution import TaskType, normalize_task_type

        assert TaskType.CONTENT_DRAFT.value == "content_draft"
        assert TaskType.AUDIOBOOK_SCRIPT.value == "audiobook_script"
        assert normalize_task_type(TaskType.CONTENT_DRAFT) == "chapter"
        assert normalize_task_type("concept_world") == "concept"
        assert normalize_task_type("outline") == "outline_expand"

    def test_model_alias_normalization(self):
        """测试历史模型别名映射。"""
        from core.model_resolution import normalize_model_id

        assert normalize_model_id("deepseek-r1") == "deepseek-reasoner"
        assert normalize_model_id("qwen-plus") == "qwen-long"
        assert normalize_model_id("qwen-max") == "qwen3-max"

    def test_deleted_legacy_files_are_removed(self):
        """测试旧兼容链路文件已删除。"""
        project_root = Path(__file__).parent.parent

        assert not (project_root / "backend/app/services/llm_client.py").exists()
        assert not (project_root / "backend/app/services/model_optimizer.py").exists()
        assert not (project_root / "backend/app/services/agents/llm_singleton.py").exists()
        assert not (project_root / "core/compatibility.py").exists()


class TestYAMLConfiguration:
    """测试 YAML 配置"""

    def test_yaml_config_loading(self):
        """测试 YAML 配置加载"""
        from core.unified_registry import UnifiedModelRegistry
        from core.model_hub import model_hub

        config_path = Path(__file__).parent.parent / "config" / "llm_models.yaml"

        if not config_path.exists():
            pytest.skip("YAML 配置文件不存在")

        registry = UnifiedModelRegistry()
        registry.clear()
        model_hub.initialize(str(config_path))

        qwen_spec = registry.get_spec("qwen3-max")
        assert qwen_spec is not None
        assert qwen_spec.provider == "alibaba"

        deepseek_spec = registry.get_spec("deepseek-reasoner")
        assert deepseek_spec is not None
        assert deepseek_spec.provider == "deepseek"
        assert deepseek_spec.api_config.api_key_env == "DASHSCOPE_API_KEY"
        assert deepseek_spec.api_config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert deepseek_spec.default_params["request_model"] == "deepseek-r1"

        deepseek_chat_spec = registry.get_spec("deepseek-chat")
        assert deepseek_chat_spec is not None
        assert deepseek_chat_spec.api_config.api_key_env == "DASHSCOPE_API_KEY"
        assert deepseek_chat_spec.api_config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert deepseek_chat_spec.default_params["request_model"] == "deepseek-v3"

    def test_yaml_audio_model_loading(self):
        """测试音乐音效模型已纳入统一模型注册中心。"""
        from core.unified_registry import UnifiedModelRegistry
        from core.model_hub import model_hub
        from schemas.unified_model_spec import ModelType

        config_path = Path(__file__).parent.parent / "config" / "llm_models.yaml"

        if not config_path.exists():
            pytest.skip("YAML 配置文件不存在")

        registry = UnifiedModelRegistry()
        registry.clear()
        model_hub.initialize(str(config_path))

        music_spec = registry.get_spec("mureka-o1-instrumental")
        assert music_spec is not None
        assert music_spec.model_type == ModelType.AUDIO
        assert "asset_music" in music_spec.routing.task_types

        sfx_spec = registry.get_spec("kling-v1-text-to-audio")
        assert sfx_spec is not None
        assert sfx_spec.model_type == ModelType.AUDIO
        assert sfx_spec.get_fallback_model() == "mureka-o1-instrumental"

        video_audio_spec = registry.get_spec("kling-v1-video-to-audio")
        assert video_audio_spec is not None
        assert video_audio_spec.model_type == ModelType.AUDIO

        audio_specs = registry.get_specs_by_type("audio")
        audio_ids = {spec.id for spec in audio_specs}
        assert {"mureka-o1-instrumental", "kling-v1-text-to-audio", "kling-v1-video-to-audio"} <= audio_ids

        assert registry.select_best_model("asset_music").id == "mureka-o1-instrumental"
        assert registry.select_best_model("asset_sfx").id == "kling-v1-text-to-audio"

    def test_yaml_task_type_mapping(self):
        """测试 YAML 任务类型映射"""
        from core.unified_registry import UnifiedModelRegistry
        from core.model_hub import model_hub

        config_path = Path(__file__).parent.parent / "config" / "llm_models.yaml"

        if not config_path.exists():
            pytest.skip("YAML 配置文件不存在")

        registry = UnifiedModelRegistry()
        registry.clear()
        model_hub.initialize(str(config_path))

        chapter_model = registry.select_best_model("chapter")
        assert chapter_model is not None

        worldview_model = registry.select_best_model("worldview")
        assert worldview_model is not None


def run_tests():
    """运行测试"""
    pytest.main([__file__, "-v", "--tb=short"])


if __name__ == "__main__":
    run_tests()
