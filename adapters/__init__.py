# -*- coding: utf-8 -*-
"""
Adapters module - Unified model adapter system.
"""

from .base import (
    BaseAdapter,
    BaseImageAdapter,
    BaseVideoAdapter,
    AdapterConfig,
    GenerationResult,
)
from .registry import (
    ModelRegistry,
    ModelPerformanceStats,
    register_model,
    registry,
)
from .adapter_helpers import (
    SimpleAdapterFactory,
    SimpleAdapter,
    SimpleGenerationResult,
    generate_image,
    generate_video,
    edit_image,
    match_scene,
    analyze_image,
    analyze_video,
    synthesize_speech,
    synthesize_speech_batch,
    factory,
)

__all__ = [
    "BaseAdapter",
    "BaseImageAdapter",
    "BaseVideoAdapter",
    "AdapterConfig",
    "GenerationResult",
    "ModelRegistry",
    "ModelPerformanceStats",
    "register_model",
    "registry",
    "SimpleAdapterFactory",
    "SimpleAdapter",
    "SimpleGenerationResult",
    "generate_image",
    "generate_video",
    "edit_image",
    "match_scene",
    "analyze_image",
    "analyze_video",
    "synthesize_speech",
    "synthesize_speech_batch",
    "factory",
]
