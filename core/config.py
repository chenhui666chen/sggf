# -*- coding: utf-8 -*-
"""
Configuration constants for model adapter system.
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class RouterConfig:
    """Router configuration constants."""
    MAX_REASONABLE_COST: float = 1.0
    MAX_REASONABLE_LATENCY: float = 120.0
    DEFAULT_MAX_FALLBACKS: int = 2
    
    QUALITY_WEIGHT: float = 0.35
    COST_WEIGHT: float = 0.25
    LATENCY_WEIGHT: float = 0.20
    RELIABILITY_WEIGHT: float = 0.20


@dataclass
class FallbackConfig:
    """Fallback manager configuration constants."""
    MAX_ATTEMPTS: int = 5
    MAX_CHAINS: int = 1000
    DEFAULT_MAX_FALLBACKS: int = 2


@dataclass
class ExecutionConfig:
    """Execution engine configuration constants."""
    DEFAULT_TIMEOUT: float = 300.0
    DEFAULT_BATCH_TIMEOUT: float = 600.0
    MAX_WORKERS: int = 4
    THREAD_NAME_PREFIX: str = "model_exec_"


@dataclass
class RegistryConfig:
    """Registry configuration constants."""
    MAX_ADAPTER_INSTANCES: int = 100
    IDLE_ADAPTER_TIMEOUT: float = 300.0


@dataclass
class AdapterConfig:
    """Adapter configuration constants."""
    DEFAULT_TIMEOUT: int = 120
    DEFAULT_MAX_RETRIES: int = 3


@dataclass
class TaskSpecConfig:
    """TaskSpec validation constants."""
    MIN_DIMENSION: int = 256
    MAX_DIMENSION: int = 4096
    MAX_DURATION: float = 60.0
    MIN_OUTPUTS: int = 1
    MAX_OUTPUTS: int = 10
    MAX_PROMPT_LENGTH: int = 10000


@dataclass
class ModelAdapterConfig:
    """Combined configuration for the model adapter system."""
    router: RouterConfig = None
    fallback: FallbackConfig = None
    execution: ExecutionConfig = None
    registry: RegistryConfig = None
    adapter: AdapterConfig = None
    task_spec: TaskSpecConfig = None
    
    def __post_init__(self):
        if self.router is None:
            self.router = RouterConfig()
        if self.fallback is None:
            self.fallback = FallbackConfig()
        if self.execution is None:
            self.execution = ExecutionConfig()
        if self.registry is None:
            self.registry = RegistryConfig()
        if self.adapter is None:
            self.adapter = AdapterConfig()
        if self.task_spec is None:
            self.task_spec = TaskSpecConfig()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "router": {
                "max_reasonable_cost": self.router.MAX_REASONABLE_COST,
                "max_reasonable_latency": self.router.MAX_REASONABLE_LATENCY,
                "default_max_fallbacks": self.router.DEFAULT_MAX_FALLBACKS,
            },
            "fallback": {
                "max_attempts": self.fallback.MAX_ATTEMPTS,
                "max_chains": self.fallback.MAX_CHAINS,
            },
            "execution": {
                "default_timeout": self.execution.DEFAULT_TIMEOUT,
                "default_batch_timeout": self.execution.DEFAULT_BATCH_TIMEOUT,
                "max_workers": self.execution.MAX_WORKERS,
            },
            "registry": {
                "max_adapter_instances": self.registry.MAX_ADAPTER_INSTANCES,
                "idle_adapter_timeout": self.registry.IDLE_ADAPTER_TIMEOUT,
            },
            "adapter": {
                "default_timeout": self.adapter.DEFAULT_TIMEOUT,
                "default_max_retries": self.adapter.DEFAULT_MAX_RETRIES,
            },
            "task_spec": {
                "min_dimension": self.task_spec.MIN_DIMENSION,
                "max_dimension": self.task_spec.MAX_DIMENSION,
                "max_duration": self.task_spec.MAX_DURATION,
                "min_outputs": self.task_spec.MIN_OUTPUTS,
                "max_outputs": self.task_spec.MAX_OUTPUTS,
            },
        }


config = ModelAdapterConfig()
