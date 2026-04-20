# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import DASHSCOPE_API_KEY, DASHSCOPE_BASE, _encode_image
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 1. 图像生成 - 百炼同步API (messages格式)
# ============================================================

class _SyncImageAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/multimodal-generation/generation"
            headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
            content = [{"text": prompt}]
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    content.insert(0, {"image": img})

            payload = {
                "model": self.MODEL_ID,
                "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": {"size": kwargs.get("size", "1024*1024"), "n": 1},
            }

            r = requests.post(url, json=payload, headers=headers, timeout=120)
            data = r.json()

            choices = data.get("output", {}).get("choices", [])
            urls = []
            for choice in choices:
                for item in choice.get("message", {}).get("content", []):
                    if "image" in item:
                        urls.append(item["image"])

            return GenerationResult(
                success=bool(urls), task_id="", model_id=self.spec.id,
                outputs=urls, error=None if urls else f"No image URLs: {str(data)[:200]}",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("qwen-image-2.0")
class QwenImage20Adapter(_SyncImageAdapter):
    MODEL_ID = "qwen-image-2.0"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-2.0", name="Qwen Image 2.0", provider="alibaba", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_to_image"], avg_latency_seconds=15.0,
        )


@register_model("qwen-image-2.0-pro")
class QwenImage20ProAdapter(_SyncImageAdapter):
    MODEL_ID = "qwen-image-2.0-pro"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-2.0-pro", name="Qwen Image 2.0 Pro", provider="alibaba", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_to_image"], avg_latency_seconds=15.0,
        )


@register_model("wan2.7-image")
class Wan27ImageAdapter(_SyncImageAdapter):
    MODEL_ID = "wan2.7-image"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.7-image", name="Wan 2.7 Image", provider="alibaba", version="v2.7",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=15.0,
        )


@register_model("wan2.6-t2i")
class Wan26T2IAdapter(_SyncImageAdapter):
    MODEL_ID = "wan2.6-t2i"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.6-t2i", name="Wan 2.6 T2I", provider="alibaba", version="v2.6",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=15.0,
        )


