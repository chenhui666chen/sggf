# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import VOLCENGINE_BASE, require_api_key
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 5. 文本对话 - 火山方舟OpenAI兼容接口 (Doubao Seed)
# ============================================================

class _VolcengineChatAdapter(BaseAdapter):
    MODEL_ID = ""
    # 方舟 Seed 2.1 起深度思考默认开启，思考与正文共用 max_tokens 预算。
    # generate() 只申请 200 tokens：实测开启思考后延迟翻倍（1.7s→3.4s），短提示词仍有正文，
    # 但推理链稍长就会吃光预算而返回空 content，故冒烟调用一律显式关闭思考。
    DISABLE_THINKING = False

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
            client = openai.OpenAI(api_key=require_api_key("VOLCENGINE_API_KEY"), base_url=f"{VOLCENGINE_BASE}")
            create_kwargs: Dict[str, Any] = {
                "model": self.MODEL_ID,
                "messages": [{"role": "user", "content": prompt or "你好"}],
                "max_tokens": 200,
            }
            if self.DISABLE_THINKING:
                create_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            response = client.chat.completions.create(**create_kwargs)
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


@register_model("doubao-seed-2-1-pro")
class DoubaoSeed21ProAdapter(_VolcengineChatAdapter):
    MODEL_ID = "doubao-seed-2-1-pro-260915"
    DISABLE_THINKING = True

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seed-2-1-pro", name="Doubao Seed 2.1 Pro", provider="doubao", version="v2.1",
            status=ModelStatus.ACTIVE, modality=["text_generation", "chat"], avg_latency_seconds=5.0,
        )


@register_model("doubao-seed-2-1-lite")
class DoubaoSeed21LiteAdapter(_VolcengineChatAdapter):
    MODEL_ID = "doubao-seed-2-1-lite-260915"
    DISABLE_THINKING = True

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seed-2-1-lite", name="Doubao Seed 2.1 Lite", provider="doubao", version="v2.1",
            status=ModelStatus.ACTIVE, modality=["text_generation", "chat"], avg_latency_seconds=3.0,
        )
