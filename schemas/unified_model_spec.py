# -*- coding: utf-8 -*-
"""
统一模型规格定义 - 支持所有模型类型 (LLM/图像/视频/音频/嵌入)

扩展原有 ModelSpec，增加 LLM 特有属性和统一调度所需字段
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from .common import SupportLevel, ModelStatus

if TYPE_CHECKING:
    from .task_spec import TaskSpec


class ModelType(Enum):
    """模型类型"""
    LLM = "llm"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    EMBEDDING = "embedding"
    TTS = "tts"


class DispatchStrategy(Enum):
    """调度策略"""
    AUTO = "auto"
    QUALITY = "quality"
    COST = "cost"
    SPEED = "speed"
    USER_SPECIFIED = "user_specified"


@dataclass
class LLMCapability:
    """LLM 特有能力"""
    name: str
    level: SupportLevel = SupportLevel.NATIVE
    score: float = 0.0
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "level": self.level.value,
            "score": self.score,
            "description": self.description,
        }


@dataclass
class LLMConstraints:
    """LLM 约束条件"""
    max_context_tokens: int = 4096
    max_output_tokens: int = 4096
    supports_streaming: bool = True
    supports_function_call: bool = False
    supports_vision: bool = False
    supports_json_mode: bool = False
    supports_timeout_param: bool = True
    supports_max_retries: bool = True
    supports_temperature: bool = True
    supports_system_prompt: bool = True
    supports_multi_turn: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_context_tokens": self.max_context_tokens,
            "max_output_tokens": self.max_output_tokens,
            "supports_streaming": self.supports_streaming,
            "supports_function_call": self.supports_function_call,
            "supports_vision": self.supports_vision,
            "supports_json_mode": self.supports_json_mode,
            "supports_timeout_param": self.supports_timeout_param,
            "supports_max_retries": self.supports_max_retries,
            "supports_temperature": self.supports_temperature,
            "supports_system_prompt": self.supports_system_prompt,
            "supports_multi_turn": self.supports_multi_turn,
        }


@dataclass
class APIConfig:
    """API 配置"""
    api_key_env: str = ""
    base_url: str = ""
    api_version: str = ""
    default_timeout: int = 120
    default_max_retries: int = 3
    extra_headers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "api_version": self.api_version,
            "default_timeout": self.default_timeout,
            "default_max_retries": self.default_max_retries,
            "extra_headers": self.extra_headers,
        }

    def get_api_key(self) -> str:
        """从环境变量获取 API Key"""
        import os
        return os.getenv(self.api_key_env, "")


@dataclass
class RoutingConfig:
    """路由配置"""
    task_types: List[str] = field(default_factory=list)
    priority: int = 1
    fallback_models: List[str] = field(default_factory=list)
    weight: float = 1.0
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_types": self.task_types,
            "priority": self.priority,
            "fallback_models": self.fallback_models,
            "weight": self.weight,
            "enabled": self.enabled,
        }


@dataclass
class PerformanceProfile:
    """性能配置"""
    quality_score: float = 7.0
    avg_latency_seconds: float = 2.0
    p95_latency_seconds: float = 5.0
    tokens_per_second: float = 50.0
    cost_per_1k_input_tokens: float = 0.0
    cost_per_1k_output_tokens: float = 0.0
    currency: str = "CNY"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quality_score": self.quality_score,
            "avg_latency_seconds": self.avg_latency_seconds,
            "p95_latency_seconds": self.p95_latency_seconds,
            "tokens_per_second": self.tokens_per_second,
            "cost_per_1k_input_tokens": self.cost_per_1k_input_tokens,
            "cost_per_1k_output_tokens": self.cost_per_1k_output_tokens,
            "currency": self.currency,
        }

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """估算成本"""
        return (
            self.cost_per_1k_input_tokens * input_tokens / 1000 +
            self.cost_per_1k_output_tokens * output_tokens / 1000
        )


@dataclass
class UnifiedModelSpec:
    """
    统一模型规格 - 支持所有模型类型

    整合 LLM、图像、视频、音频等模型的能力描述
    """

    id: str
    name: str
    provider: str
    model_type: ModelType
    version: str = "v1"
    status: ModelStatus = ModelStatus.ACTIVE
    modality: List[str] = field(default_factory=list)

    capabilities: List[LLMCapability] = field(default_factory=list)
    constraints: LLMConstraints = field(default_factory=LLMConstraints)
    api_config: APIConfig = field(default_factory=APIConfig)
    performance: PerformanceProfile = field(default_factory=PerformanceProfile)
    routing: RoutingConfig = field(default_factory=RoutingConfig)

    default_params: Dict[str, Any] = field(default_factory=dict)
    best_practice_tips: List[str] = field(default_factory=list)
    summary: str = ""
    recommended_scenarios: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    integration_notes: List[str] = field(default_factory=list)
    source_urls: List[str] = field(default_factory=list)

    tags: List[str] = field(default_factory=list)
    documentation_url: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def has_capability(self, capability: str) -> bool:
        """检查是否具备某能力"""
        for cap in self.capabilities:
            if cap.name == capability:
                return cap.level != SupportLevel.UNSUPPORTED
        return False

    def get_capability_score(self, capability: str) -> float:
        """获取能力评分"""
        for cap in self.capabilities:
            if cap.name == capability:
                return cap.score
        return 0.0

    def supports_task_type(self, task_type: str) -> bool:
        """检查是否支持某任务类型"""
        return task_type in self.routing.task_types

    def is_available(self) -> bool:
        """检查模型是否可用"""
        return self.status == ModelStatus.ACTIVE and self.routing.enabled

    def get_fallback_model(self) -> Optional[str]:
        """获取回退模型"""
        if self.routing.fallback_models:
            return self.routing.fallback_models[0]
        return None

    def calculate_dispatch_score(self, strategy: DispatchStrategy) -> float:
        """
        计算调度评分

        根据策略计算模型综合得分
        """
        if strategy == DispatchStrategy.QUALITY:
            return self.performance.quality_score / 10.0
        elif strategy == DispatchStrategy.COST:
            cost = (
                self.performance.cost_per_1k_input_tokens +
                self.performance.cost_per_1k_output_tokens
            )
            return 1.0 / (cost + 0.001)
        elif strategy == DispatchStrategy.SPEED:
            return 1.0 / (self.performance.avg_latency_seconds + 0.1)
        else:
            quality = self.performance.quality_score / 10.0
            speed = 1.0 / (self.performance.avg_latency_seconds + 0.1)
            cost = 1.0 / (
                self.performance.cost_per_1k_input_tokens +
                self.performance.cost_per_1k_output_tokens + 0.001
            )
            return quality * 0.4 + speed * 0.3 + cost * 0.3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "model_type": self.model_type.value,
            "version": self.version,
            "status": self.status.value,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "constraints": self.constraints.to_dict(),
            "api_config": self.api_config.to_dict(),
            "performance": self.performance.to_dict(),
            "routing": self.routing.to_dict(),
            "default_params": self.default_params,
            "best_practice_tips": self.best_practice_tips,
            "summary": self.summary,
            "recommended_scenarios": self.recommended_scenarios,
            "limitations": self.limitations,
            "integration_notes": self.integration_notes,
            "source_urls": self.source_urls,
            "tags": self.tags,
            "documentation_url": self.documentation_url,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedModelSpec":
        """从字典创建规格"""
        capabilities = [
            LLMCapability(
                name=cap.get("name", ""),
                level=SupportLevel(cap.get("level", "native")),
                score=cap.get("score", 0.0),
                description=cap.get("description", ""),
            )
            for cap in data.get("capabilities", [])
        ]

        constraints_data = data.get("constraints", {})
        constraints = LLMConstraints(
            max_context_tokens=constraints_data.get("max_context_tokens", 4096),
            max_output_tokens=constraints_data.get("max_output_tokens", 4096),
            supports_streaming=constraints_data.get("supports_streaming", True),
            supports_function_call=constraints_data.get("supports_function_call", False),
            supports_vision=constraints_data.get("supports_vision", False),
            supports_json_mode=constraints_data.get("supports_json_mode", False),
            supports_timeout_param=constraints_data.get("supports_timeout_param", True),
            supports_max_retries=constraints_data.get("supports_max_retries", True),
            supports_temperature=constraints_data.get("supports_temperature", True),
            supports_system_prompt=constraints_data.get("supports_system_prompt", True),
            supports_multi_turn=constraints_data.get("supports_multi_turn", True),
        )

        api_data = data.get("api_config", {})
        api_config = APIConfig(
            api_key_env=api_data.get("api_key_env", ""),
            base_url=api_data.get("base_url", ""),
            api_version=api_data.get("api_version", ""),
            default_timeout=api_data.get("default_timeout", 120),
            default_max_retries=api_data.get("default_max_retries", 3),
            extra_headers=api_data.get("extra_headers", {}),
        )

        perf_data = data.get("performance", {})
        cost_per_1k_input_tokens = perf_data.get("cost_per_1k_input_tokens")
        if cost_per_1k_input_tokens is None and perf_data.get("cost_per_1m_input_tokens") is not None:
            cost_per_1k_input_tokens = perf_data.get("cost_per_1m_input_tokens", 0.0) / 1000

        cost_per_1k_output_tokens = perf_data.get("cost_per_1k_output_tokens")
        if cost_per_1k_output_tokens is None and perf_data.get("cost_per_1m_output_tokens") is not None:
            cost_per_1k_output_tokens = perf_data.get("cost_per_1m_output_tokens", 0.0) / 1000

        performance = PerformanceProfile(
            quality_score=perf_data.get("quality_score", 7.0),
            avg_latency_seconds=perf_data.get("avg_latency_seconds", 2.0),
            p95_latency_seconds=perf_data.get("p95_latency_seconds", 5.0),
            tokens_per_second=perf_data.get("tokens_per_second", 50.0),
            cost_per_1k_input_tokens=cost_per_1k_input_tokens or 0.0,
            cost_per_1k_output_tokens=cost_per_1k_output_tokens or 0.0,
            currency=perf_data.get("currency", "CNY"),
        )

        routing_data = data.get("routing", {})
        routing = RoutingConfig(
            task_types=routing_data.get("task_types", []),
            priority=routing_data.get("priority", 1),
            fallback_models=routing_data.get("fallback_models", []),
            weight=routing_data.get("weight", 1.0),
            enabled=routing_data.get("enabled", True),
        )

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            provider=data.get("provider", ""),
            model_type=ModelType(data.get("model_type", "llm")),
            version=data.get("version", "v1"),
            status=ModelStatus(data.get("status", "active")),
            modality=data.get("modality", []),
            capabilities=capabilities,
            constraints=constraints,
            api_config=api_config,
            performance=performance,
            routing=routing,
            default_params=data.get("default_params", {}),
            best_practice_tips=data.get("best_practice_tips", []),
            summary=data.get("summary", ""),
            recommended_scenarios=data.get("recommended_scenarios", []),
            limitations=data.get("limitations", []),
            integration_notes=data.get("integration_notes", []),
            source_urls=data.get("source_urls", []),
            tags=data.get("tags", []),
            documentation_url=data.get("documentation_url", ""),
        )


@dataclass
class LLMTaskSpec:
    """LLM 任务规格"""

    messages: List[Dict[str, str]] = field(default_factory=list)
    task_type: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    system_prompt: Optional[str] = None
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "messages": self.messages,
            "task_type": self.task_type,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": self.stream,
            "system_prompt": self.system_prompt,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "metadata": self.metadata,
        }


@dataclass
class LLMResult:
    """LLM 调用结果"""

    success: bool
    model_id: str
    content: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    latency: float = 0.0
    cost: float = 0.0
    error: Optional[str] = None
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "model_id": self.model_id,
            "content": self.content,
            "usage": self.usage,
            "latency": self.latency,
            "cost": self.cost,
            "error": self.error,
            "error_code": self.error_code,
            "metadata": self.metadata,
        }
