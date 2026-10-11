# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import DASHSCOPE_BASE
from adapters.dashscope.chat import _DashScopeChatAdapter, _DashScopeVisionReviewMixin
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 6. 多模态对话 - 百炼OpenAI兼容接口 (qwen3-vl-plus)
# ============================================================

@register_model("qwen3-vl-plus")
class Qwen3VLPlusAdapter(_DashScopeVisionReviewMixin, _DashScopeChatAdapter):
    MODEL_ID = "qwen3-vl-plus"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3-vl-plus", name="Qwen3 VL Plus", provider="alibaba", version="v3",
            status=ModelStatus.ACTIVE, modality=["multimodal_chat", "image_understanding", "video_understanding"],
            avg_latency_seconds=5.0,
        )


