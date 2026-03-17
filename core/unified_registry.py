# -*- coding: utf-8 -*-
"""
统一模型注册中心 - 支持所有模型类型的注册和管理

整合 LLM、图像、视频、音频等模型的注册、发现和调度
"""

from __future__ import annotations

import os
import json
import yaml
import logging
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Type, Any, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from schemas.unified_model_spec import (
    UnifiedModelSpec, LLMTaskSpec, LLMResult, DispatchStrategy,
    ModelType, ModelStatus, LLMCapability, LLMConstraints,
    APIConfig, RoutingConfig, PerformanceProfile, SupportLevel
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class ModelPerformanceStats:
    """模型运行时性能统计"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency: float = 0.0
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    last_success_time: Optional[datetime] = None
    last_failure_time: Optional[datetime] = None
    error_counts: Dict[str, int] = field(default_factory=dict)
    consecutive_failures: int = 0

    def record_success(
        self,
        latency: float,
        cost: float,
        input_tokens: int = 0,
        output_tokens: int = 0
    ) -> None:
        self.total_requests += 1
        self.successful_requests += 1
        self.total_latency += latency
        self.total_cost += cost
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.last_success_time = datetime.now()
        self.consecutive_failures = 0

    def record_failure(self, error_code: str) -> None:
        self.total_requests += 1
        self.failed_requests += 1
        self.last_failure_time = datetime.now()
        self.error_counts[error_code] = self.error_counts.get(error_code, 0) + 1
        self.consecutive_failures += 1

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    @property
    def avg_latency(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency / self.successful_requests

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": round(self.success_rate, 4),
            "avg_latency": round(self.avg_latency, 2),
            "total_cost": round(self.total_cost, 4),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "error_counts": self.error_counts,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass
class CircuitBreakerState:
    """熔断器状态"""
    is_open: bool = False
    failure_count: int = 0
    last_failure_time: Optional[datetime] = None
    half_open: bool = False

    FAILURE_THRESHOLD: int = 5
    RECOVERY_TIMEOUT_SECONDS: int = 60

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        if self.failure_count >= self.FAILURE_THRESHOLD:
            self.is_open = True
            self.half_open = False

    def record_success(self) -> None:
        self.failure_count = 0
        self.is_open = False
        self.half_open = False

    def can_attempt(self) -> bool:
        if not self.is_open:
            return True
        if self.last_failure_time is None:
            return True
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        if elapsed >= self.RECOVERY_TIMEOUT_SECONDS:
            self.half_open = True
            return True
        return False


class BaseLLMAdapter(ABC):
    """LLM 适配器基类"""

    def __init__(self, spec: "UnifiedModelSpec"):
        self.spec = spec
        self._client = None
        self._initialized = False

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> "LLMResult":
        """生成响应"""
        pass

    @abstractmethod
    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        on_chunk: Callable[[str], None],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> "LLMResult":
        """流式生成响应"""
        pass

    def has_capability(self, capability: str) -> bool:
        """检查是否具备某能力"""
        return self.spec.has_capability(capability)

    def supports_streaming(self) -> bool:
        """检查是否支持流式输出"""
        return self.spec.constraints.supports_streaming

    def close(self) -> None:
        """释放资源"""
        if self._client and hasattr(self._client, 'close'):
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None


class UnifiedModelRegistry:
    """
    统一模型注册中心

    单例模式，管理所有模型类型的注册、发现和实例化
    """

    _instance: Optional["UnifiedModelRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "UnifiedModelRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._specs: Dict[str, "UnifiedModelSpec"] = {}
        self._adapters: Dict[str, Type[BaseLLMAdapter]] = {}
        self._adapter_instances: Dict[str, BaseLLMAdapter] = {}
        self._performance_stats: Dict[str, ModelPerformanceStats] = {}
        self._circuit_breakers: Dict[str, CircuitBreakerState] = {}
        self._task_type_mapping: Dict[str, List[str]] = {}
        self._state_lock = threading.RLock()
        self._yaml_loaded = False

    def register(
        self,
        spec: "UnifiedModelSpec",
        adapter_class: Optional[Type[BaseLLMAdapter]] = None
    ) -> None:
        """
        注册模型

        Args:
            spec: 模型规格
            adapter_class: 适配器类（可选）
        """
        with self._state_lock:
            self._specs[spec.id] = spec
            self._performance_stats[spec.id] = ModelPerformanceStats()
            self._circuit_breakers[spec.id] = CircuitBreakerState()

            if adapter_class:
                self._adapters[spec.id] = adapter_class

            for task_type in spec.routing.task_types:
                if task_type not in self._task_type_mapping:
                    self._task_type_mapping[task_type] = []
                if spec.id not in self._task_type_mapping[task_type]:
                    self._task_type_mapping[task_type].append(spec.id)

            logger.info(f"✅ 注册模型: {spec.name} ({spec.id}) | 类型: {spec.model_type.value} | 任务: {spec.routing.task_types}")

    def unregister(self, model_id: str) -> bool:
        """注销模型"""
        with self._state_lock:
            removed = False

            if model_id in self._specs:
                spec = self._specs[model_id]
                for task_type in spec.routing.task_types:
                    if task_type in self._task_type_mapping:
                        self._task_type_mapping[task_type] = [
                            m for m in self._task_type_mapping[task_type] if m != model_id
                        ]
                del self._specs[model_id]
                removed = True

            if model_id in self._adapters:
                del self._adapters[model_id]

            if model_id in self._adapter_instances:
                adapter = self._adapter_instances[model_id]
                if adapter:
                    adapter.close()
                del self._adapter_instances[model_id]

            if model_id in self._performance_stats:
                del self._performance_stats[model_id]

            if model_id in self._circuit_breakers:
                del self._circuit_breakers[model_id]

            return removed

    def get_spec(self, model_id: str) -> Optional["UnifiedModelSpec"]:
        """获取模型规格"""
        return self._specs.get(model_id)

    def get_adapter(self, model_id: str) -> Optional[BaseLLMAdapter]:
        """获取或创建适配器实例"""
        if model_id not in self._specs:
            return None

        if model_id in self._adapter_instances:
            return self._adapter_instances[model_id]

        if model_id in self._adapters:
            adapter_class = self._adapters[model_id]
            spec = self._specs[model_id]
            adapter = adapter_class(spec)
            self._adapter_instances[model_id] = adapter
            return adapter

        return None

    def get_all_specs(self) -> List["UnifiedModelSpec"]:
        """获取所有模型规格"""
        return list(self._specs.values())

    def get_specs_by_type(self, model_type: str) -> List["UnifiedModelSpec"]:
        """按类型获取模型规格"""
        from schemas.unified_model_spec import ModelType
        try:
            mt = ModelType(model_type)
            return [s for s in self._specs.values() if s.model_type == mt]
        except ValueError:
            return []

    def get_specs_by_provider(self, provider: str) -> List["UnifiedModelSpec"]:
        """按提供商获取模型规格"""
        return [s for s in self._specs.values() if s.provider == provider]

    def get_models_for_task(self, task_type: str) -> List["UnifiedModelSpec"]:
        """获取支持某任务类型的所有模型"""
        model_ids = self._task_type_mapping.get(task_type, [])
        return [self._specs[mid] for mid in model_ids if mid in self._specs]

    def get_all_task_types(self) -> List[str]:
        """获取所有已注册的任务类型"""
        return list(self._task_type_mapping.keys())

    def find_capable_models(
        self,
        capability: str,
        model_type: Optional[str] = None
    ) -> List["UnifiedModelSpec"]:
        """查找具备某能力的模型"""
        candidates = []
        for spec in self._specs.values():
            if spec.has_capability(capability):
                if model_type is None or spec.model_type.value == model_type:
                    candidates.append(spec)
        return candidates

    def select_best_model(
        self,
        task_type: str,
        strategy: "DispatchStrategy" = None
    ) -> Optional["UnifiedModelSpec"]:
        """
        为任务选择最佳模型

        Args:
            task_type: 任务类型
            strategy: 调度策略

        Returns:
            最佳模型规格，如果没有则返回 None
        """
        from schemas.unified_model_spec import DispatchStrategy

        if strategy is None:
            strategy = DispatchStrategy.AUTO

        candidates = self.get_models_for_task(task_type)

        if not candidates:
            logger.warning(f"⚠️ 没有找到支持任务类型 '{task_type}' 的模型")
            return None

        available = [
            spec for spec in candidates
            if self._is_available(spec.id)
        ]

        if not available:
            logger.warning(f"⚠️ 任务类型 '{task_type}' 的所有模型都不可用，尝试回退")
            for spec in candidates:
                fallback_id = spec.get_fallback_model()
                if fallback_id and self._is_available(fallback_id):
                    return self._specs.get(fallback_id)
            return None

        scored = [
            (spec, spec.calculate_dispatch_score(strategy))
            for spec in available
        ]

        scored.sort(key=lambda x: (-x[1], x[0].routing.priority))

        best = scored[0][0]
        logger.info(f"🎯 任务 '{task_type}' 选择模型: {best.name} ({best.id})")
        return best

    def _is_available(self, model_id: str) -> bool:
        """检查模型是否可用"""
        spec = self._specs.get(model_id)
        if not spec:
            return False

        if not spec.is_available():
            return False

        breaker = self._circuit_breakers.get(model_id)
        if breaker and not breaker.can_attempt():
            return False

        return True

    def record_success(
        self,
        model_id: str,
        latency: float,
        cost: float,
        input_tokens: int = 0,
        output_tokens: int = 0
    ) -> None:
        """记录成功调用"""
        if model_id in self._performance_stats:
            self._performance_stats[model_id].record_success(
                latency, cost, input_tokens, output_tokens
            )

        if model_id in self._circuit_breakers:
            self._circuit_breakers[model_id].record_success()

    def record_failure(self, model_id: str, error_code: str) -> None:
        """记录失败调用"""
        if model_id in self._performance_stats:
            self._performance_stats[model_id].record_failure(error_code)

        if model_id in self._circuit_breakers:
            self._circuit_breakers[model_id].record_failure()

    def get_performance_stats(self, model_id: str) -> Optional[ModelPerformanceStats]:
        """获取模型性能统计"""
        return self._performance_stats.get(model_id)

    def get_all_performance_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有模型性能统计"""
        return {
            model_id: stats.to_dict()
            for model_id, stats in self._performance_stats.items()
        }

    def load_from_yaml(self, yaml_path: str) -> int:
        """从 YAML 文件加载模型配置"""
        path = Path(yaml_path)
        if not path.exists():
            logger.warning(f"⚠️ YAML 文件不存在: {yaml_path}")
            return 0

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return 0

        loaded_count = 0

        for section in ["llm_models", "image_models", "video_models", "audio_models", "embedding_models"]:
            if section not in data:
                continue

            for model_data in data[section]:
                try:
                    from schemas.unified_model_spec import UnifiedModelSpec

                    spec = UnifiedModelSpec.from_dict(model_data)
                    self.register(spec)
                    loaded_count += 1

                except Exception as e:
                    logger.error(f"❌ 加载模型失败: {e}")

        self._yaml_loaded = True
        logger.info(f"✅ 从 YAML 加载了 {loaded_count} 个模型")
        return loaded_count

    def save_to_yaml(self, yaml_path: str) -> bool:
        """保存模型配置到 YAML 文件"""
        path = Path(yaml_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "llm_models": [],
            "image_models": [],
            "video_models": [],
            "audio_models": [],
            "embedding_models": [],
        }

        type_mapping = {
            "llm": "llm_models",
            "image": "image_models",
            "video": "video_models",
            "audio": "audio_models",
            "embedding": "embedding_models",
            "tts": "audio_models",
        }

        for spec in self._specs.values():
            section = type_mapping.get(spec.model_type.value, "llm_models")
            data[section].append(spec.to_dict())

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        return True

    def clear(self) -> None:
        """清空所有注册"""
        with self._state_lock:
            for adapter in self._adapter_instances.values():
                if adapter:
                    adapter.close()

            self._specs.clear()
            self._adapters.clear()
            self._adapter_instances.clear()
            self._performance_stats.clear()
            self._circuit_breakers.clear()
            self._task_type_mapping.clear()
            self._yaml_loaded = False

    def get_registry_status(self) -> Dict[str, Any]:
        """获取注册中心状态"""
        return {
            "total_models": len(self._specs),
            "by_type": {
                model_type: len([s for s in self._specs.values() if s.model_type.value == model_type])
                for model_type in ["llm", "image", "video", "audio", "embedding"]
            },
            "by_provider": {
                provider: len([s for s in self._specs.values() if s.provider == provider])
                for provider in set(s.provider for s in self._specs.values())
            },
            "task_types": list(self._task_type_mapping.keys()),
            "yaml_loaded": self._yaml_loaded,
        }


def register_llm_model(
    model_id: str,
    name: str,
    provider: str,
    capabilities: List[str],
    task_types: List[str],
    **kwargs
) -> Callable[[Type[BaseLLMAdapter]], Type[BaseLLMAdapter]]:
    """
    LLM 模型注册装饰器

    使用示例:
        @register_llm_model(
            model_id="qwen3-max",
            name="Qwen3 Max",
            provider="alibaba",
            capabilities=["creative", "dialogue", "reasoning"],
            task_types=["concept", "chapter", "dialogue"],
            max_context_tokens=32000,
            quality_score=8.5
        )
        class QwenMaxAdapter(BaseLLMAdapter):
            pass
    """
    def decorator(adapter_class: Type[BaseLLMAdapter]) -> Type[BaseLLMAdapter]:
        from schemas.unified_model_spec import (
            UnifiedModelSpec, LLMCapability, LLMConstraints,
            APIConfig, PerformanceProfile, RoutingConfig, SupportLevel
        )

        capability_objs = [
            LLMCapability(name=cap, level=SupportLevel.NATIVE, score=0.8)
            for cap in capabilities
        ]

        constraints = LLMConstraints(
            max_context_tokens=kwargs.get("max_context_tokens", 4096),
            max_output_tokens=kwargs.get("max_output_tokens", 4096),
            supports_streaming=kwargs.get("supports_streaming", True),
            supports_function_call=kwargs.get("supports_function_call", False),
            supports_vision=kwargs.get("supports_vision", False),
            supports_timeout_param=kwargs.get("supports_timeout_param", True),
            supports_max_retries=kwargs.get("supports_max_retries", True),
        )

        api_config = APIConfig(
            api_key_env=kwargs.get("api_key_env", f"{provider.upper()}_API_KEY"),
            base_url=kwargs.get("base_url", ""),
            default_timeout=kwargs.get("default_timeout", 120),
        )

        performance = PerformanceProfile(
            quality_score=kwargs.get("quality_score", 7.0),
            avg_latency_seconds=kwargs.get("avg_latency_seconds", 2.0),
            cost_per_1k_input_tokens=kwargs.get("cost_per_1k_input_tokens", 0.0),
            cost_per_1k_output_tokens=kwargs.get("cost_per_1k_output_tokens", 0.0),
        )

        routing = RoutingConfig(
            task_types=task_types,
            priority=kwargs.get("priority", 1),
            fallback_models=kwargs.get("fallback_models", []),
        )

        spec = UnifiedModelSpec(
            id=model_id,
            name=name,
            provider=provider,
            model_type=ModelType.LLM,
            capabilities=capability_objs,
            constraints=constraints,
            api_config=api_config,
            performance=performance,
            routing=routing,
            default_params=kwargs.get("default_params", {}),
            tags=kwargs.get("tags", []),
        )

        registry = UnifiedModelRegistry()
        registry.register(spec, adapter_class)

        return adapter_class

    return decorator


registry = UnifiedModelRegistry()
