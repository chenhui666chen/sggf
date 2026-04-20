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
# 11. 图像编辑 - 百炼API
# ============================================================

class _ImageEditAdapter(BaseAdapter):
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
            content = [{"text": prompt or "请编辑这张图片"}]
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    content.insert(0, {"image": img})
            else:
                test_img = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog_and_girl.jpeg"
                content.insert(0, {"image": test_img})

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


@register_model("qwen-image-edit-plus")
class QwenImageEditPlusAdapter(_ImageEditAdapter):
    MODEL_ID = "qwen-image-edit-plus"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-edit-plus", name="Qwen Image Edit Plus", provider="alibaba", version="v1",
            status=ModelStatus.ACTIVE, modality=["image_to_image_edit", "image_edit"], avg_latency_seconds=15.0,
        )


@register_model("qwen-image-edit-max")
class QwenImageEditMaxAdapter(_ImageEditAdapter):
    MODEL_ID = "qwen-image-edit-max"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-edit-max", name="Qwen Image Edit Max", provider="alibaba", version="v1",
            status=ModelStatus.ACTIVE, modality=["image_to_image_edit", "image_edit"], avg_latency_seconds=15.0,
        )


