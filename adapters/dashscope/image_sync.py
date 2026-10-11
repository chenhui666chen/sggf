# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
import requests
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import DASHSCOPE_BASE, _encode_image, require_api_key
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 1. 图像生成 - 百炼同步API (messages格式)
# ============================================================

class _SyncImageAdapter(BaseAdapter):
    MODEL_ID = ""
    # DashScope 协议的 size 用星号分隔（OpenAI 兼容模式才用字母 x）。
    # 媒体链路不消费 spec.default_params，YAML 里的 default_params 只是文档，
    # 真正决定请求里 size 默认值的是这个类属性。
    DEFAULT_SIZE = "1024*1024"

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
            headers = {"Authorization": f"Bearer {require_api_key('DASHSCOPE_API_KEY')}", "Content-Type": "application/json"}
            content = [{"text": prompt}]
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    content.insert(0, {"image": img})

            payload = {
                "model": self.MODEL_ID,
                "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": {"size": kwargs.get("size") or self.DEFAULT_SIZE, "n": 1},
            }
            negative_prompt = str(kwargs.get("negative_prompt") or "").strip()
            if negative_prompt:
                payload["parameters"]["negative_prompt"] = negative_prompt

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


@register_model("qwen-image-3.0")
class QwenImage30Adapter(_SyncImageAdapter):
    MODEL_ID = "qwen-image-3.0"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-3.0", name="Qwen Image 3.0", provider="alibaba", version="v3.0",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=43.0,
        )


@register_model("qwen-image-3.0-pro")
class QwenImage30ProAdapter(_SyncImageAdapter):
    MODEL_ID = "qwen-image-3.0-pro"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-3.0-pro", name="Qwen Image 3.0 Pro", provider="alibaba", version="v3.0",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=44.0,
        )


@register_model("wan2.7-image-pro")
class Wan27ImageProAdapter(_SyncImageAdapter):
    MODEL_ID = "wan2.7-image-pro"

    # 官方推荐的档位写法；像素值写法要求文生图总像素落在 [768*768, 4096*4096]，
    # 而 4K 仅文生图（无图片输入且非组图）支持，用档位串可以让上游自己兜住这些规则。
    DEFAULT_SIZE = "2K"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.7-image-pro", name="Wan 2.7 Image Pro", provider="alibaba", version="v2.7",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=44.0,
        )


