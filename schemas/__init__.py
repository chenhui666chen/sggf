# -*- coding: utf-8 -*-
"""
Schema definitions for unified model adapter system.
"""

from .common import (
    Modality,
    ModelStatus,
    SupportLevel,
    Priority,
)
from .task_spec import (
    TaskSpec,
    ReferenceSpec,
    AudioSpec,
    PriorityProfile,
    TaskSpecBuilder,
)
from .model_spec import (
    ModelSpec,
    ConstraintSpec,
    QualityMetrics,
    CostProfile,
    RateLimitConfig,
    ParameterSpec,
    CapabilityFeature,
    BestPractice,
    FallbackStrategy,
)

__all__ = [
    "Modality",
    "ModelStatus",
    "SupportLevel",
    "Priority",
    "TaskSpec",
    "ReferenceSpec",
    "AudioSpec",
    "PriorityProfile",
    "TaskSpecBuilder",
    "ModelSpec",
    "ConstraintSpec",
    "QualityMetrics",
    "CostProfile",
    "RateLimitConfig",
    "ParameterSpec",
    "CapabilityFeature",
    "BestPractice",
    "FallbackStrategy",
]
