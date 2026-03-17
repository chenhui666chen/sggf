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
