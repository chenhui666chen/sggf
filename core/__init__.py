# -*- coding: utf-8 -*-
"""
统一模型调度中心 (ModelHub)

提供统一的模型调用入口，支持：
- 自动模型选择
- 用户指定模型
- 熔断降级
- 重试机制
- 成本追踪
"""

from .unified_registry import (
    UnifiedModelRegistry,
    BaseLLMAdapter,
    register_llm_model,
    registry,
)

from .llm_adapters import (
    OpenAICompatibleAdapter,
    DeepSeekV4ProAdapter,
)

from .model_hub import (
    ModelHub,
    model_hub,
    get_model_hub,
    call_llm,
)
from .model_resolution import (
    TaskType,
    normalize_model_id,
    normalize_task_type,
)
from .unified_llm_client import (
    UnifiedLLMClient,
    get_llm_client,
)
from .langchain_bridge import (
    ModelHubChatModel,
    create_task_llm,
    create_model_llm,
    get_task_llm,
)

__all__ = [
    "UnifiedModelRegistry",
    "BaseLLMAdapter",
    "register_llm_model",
    "registry",
    "OpenAICompatibleAdapter",
    "DeepSeekV4ProAdapter",
    "ModelHub",
    "model_hub",
    "get_model_hub",
    "call_llm",
    "TaskType",
    "normalize_model_id",
    "normalize_task_type",
    "UnifiedLLMClient",
    "get_llm_client",
    "ModelHubChatModel",
    "create_task_llm",
    "create_model_llm",
    "get_task_llm",
]
