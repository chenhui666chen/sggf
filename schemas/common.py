# -*- coding: utf-8 -*-
"""
Common type definitions for unified model adapter system.
"""

from enum import Enum
from typing import Dict, Any


class Modality(Enum):
    """Generation modality types."""
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    VIDEO_TO_VIDEO = "video_to_video"
    IMAGE_TO_IMAGE_EDIT = "image_to_image_edit"
    TEXT_TO_SPEECH = "text_to_speech"


class ModelStatus(Enum):
    """Model availability status."""
    ACTIVE = "active"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    DEPRECATED = "deprecated"
    TESTING = "testing"


class SupportLevel(Enum):
    """Capability support level."""
    NATIVE = "native"
    EMULATED = "emulated"
    UNSUPPORTED = "unsupported"


class Priority(Enum):
    """Task priority type."""
    QUALITY = "quality"
    COST = "cost"
    LATENCY = "latency"
    BALANCED = "balanced"


class ErrorCode(Enum):
    """Unified error codes."""
    SUCCESS = "success"
    UNKNOWN_ERROR = "unknown_error"
    UNSUPPORTED_TASK = "unsupported_task"
    MAPPING_ERROR = "mapping_error"
    API_ERROR = "api_error"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONTENT_SAFETY = "content_safety"
    INVALID_PARAMETER = "invalid_parameter"
    INSUFFICIENT_QUOTA = "insufficient_quota"
    MODEL_UNAVAILABLE = "model_unavailable"
    NETWORK_ERROR = "network_error"
    AUTH_ERROR = "auth_error"
    INVALID_RESPONSE = "invalid_response"
    NO_OUTPUT = "no_output"
    ADAPTER_MISSING = "adapter_missing"
    TASK_CANCELLED = "task_cancelled"
    DEGRADATION_EXHAUSTED = "degradation_exhausted"
    
    @property
    def is_retryable(self) -> bool:
        """Check if error is retryable."""
        retryable_codes = {
            ErrorCode.RATE_LIMIT,
            ErrorCode.TIMEOUT,
            ErrorCode.MODEL_UNAVAILABLE,
            ErrorCode.NETWORK_ERROR,
        }
        return self in retryable_codes
    
    @property
    def should_fallback(self) -> bool:
        """Check if should fallback to another model."""
        fallback_codes = {
            ErrorCode.RATE_LIMIT,
            ErrorCode.MODEL_UNAVAILABLE,
            ErrorCode.CONTENT_SAFETY,
            ErrorCode.INSUFFICIENT_QUOTA,
        }
        return self in fallback_codes


class ContentType(Enum):
    """Content type for outputs."""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    TEXT = "text"


def ratio_to_dimensions(ratio: str) -> tuple:
    """Convert ratio string to width/height tuple."""
    parts = ratio.split(":")
    if len(parts) != 2:
        return (1, 1)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (1, 1)


def dimensions_to_ratio(width: int, height: int) -> str:
    """Convert dimensions to ratio string."""
    from math import gcd
    g = gcd(width, height)
    return f"{width // g}:{height // g}"
