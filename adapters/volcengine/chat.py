# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import VOLCENGINE_API_KEY, VOLCENGINE_BASE
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 5. 文本对话 - 火山方舟OpenAI兼容接口 (Doubao Seed)
# ============================================================

class _VolcengineChatAdapter(BaseAdapter):
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
            client = openai.OpenAI(api_key=VOLCENGINE_API_KEY, base_url=f"{VOLCENGINE_BASE}")
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


@register_model("doubao-seed-2-0-pro")
class DoubaoSeed20ProAdapter(_VolcengineChatAdapter):
    MODEL_ID = "doubao-seed-2-0-pro-260215"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seed-2-0-pro", name="Doubao Seed 2.0 Pro", provider="doubao", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_generation", "chat"], avg_latency_seconds=5.0,
        )


@register_model("doubao-seed-2-0-lite")
class DoubaoSeed20LiteAdapter(_VolcengineChatAdapter):
    MODEL_ID = "doubao-seed-2-0-lite-260215"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seed-2-0-lite", name="Doubao Seed 2.0 Lite", provider="doubao", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_generation", "chat"], avg_latency_seconds=3.0,
        )


