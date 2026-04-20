# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import DASHSCOPE_API_KEY, DASHSCOPE_BASE
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 4. 文本对话 - 百炼OpenAI兼容接口
# ============================================================

class _DashScopeChatAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        import openai
        start = time.time()
        try:
            client = openai.OpenAI(api_key=DASHSCOPE_API_KEY, base_url=f"{DASHSCOPE_BASE}/compatible-mode/v1")
            response = client.chat.completions.create(
                model=self.MODEL_ID,
                messages=[{"role": "user", "content": prompt or "你好"}],
                max_tokens=200,
            )
            content = response.choices[0].message.content or ""
            return GenerationResult(
                success=bool(content), task_id="", model_id=self.spec.id,
                outputs=[content], error=None if content else "Empty response",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("qwen3.5-omni-plus")
class Qwen35OmniPlusAdapter(_DashScopeChatAdapter):
    MODEL_ID = "qwen3.5-omni-plus"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3.5-omni-plus", name="Qwen 3.5 Omni Plus", provider="alibaba", version="v3.5",
            status=ModelStatus.ACTIVE, modality=["text_to_text"], avg_latency_seconds=5.0,
        )


@register_model("qwen3.6-plus")
class Qwen36PlusAdapter(_DashScopeChatAdapter):
    MODEL_ID = "qwen3.6-plus"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3.6-plus", name="Qwen 3.6 Plus", provider="alibaba", version="v3.6",
            status=ModelStatus.ACTIVE, modality=["text_to_text"], avg_latency_seconds=5.0,
        )


