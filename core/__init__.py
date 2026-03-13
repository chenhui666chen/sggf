# -*- coding: utf-8 -*-
"""
Core module - Task parsing, routing, and execution.
"""

from .task_parser import (
    TaskParser,
    TaskSpecBuilder,
    parse_generation_request,
)
from .validators import (
    TaskValidator,
    ValidationResult,
)
from .router import (
    SmartRouter,
    RoutingResult,
    CapabilityFilter,
    ModelScorer,
    LoadBalancer,
    router,
)
from .fallback_manager import (
    FallbackManager,
    FallbackChain,
    FallbackAttempt,
    TaskDegradationStrategy,
    fallback_manager,
)
from .execution_engine import (
    ExecutionEngine,
    ExecutionResult,
    engine,
)

__all__ = [
    "TaskParser",
    "TaskSpecBuilder",
    "parse_generation_request",
    "TaskValidator",
    "ValidationResult",
    "SmartRouter",
    "RoutingResult",
    "CapabilityFilter",
    "ModelScorer",
    "LoadBalancer",
    "router",
    "FallbackManager",
    "FallbackChain",
    "FallbackAttempt",
    "TaskDegradationStrategy",
    "fallback_manager",
    "ExecutionEngine",
    "ExecutionResult",
    "engine",
]
