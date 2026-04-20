# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import DASHSCOPE_API_KEY, DASHSCOPE_BASE, _encode_image, _env_int, _poll_dashscope_task
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 2. 图像生成 - 百炼异步API (Kling)
# ============================================================

class _AsyncImageAdapter(BaseAdapter):
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
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/image-generation/generation"
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            content = [{"text": prompt}]
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    content.insert(0, {"image": img})

            payload = {
                "model": self.MODEL_ID,
                "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": kwargs.get("parameters", {"n": 1}),
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"HTTP {r.status_code}: {r.text[:200]}",
                    latency=time.time() - start,
                )
            data = r.json()

            # Check for API-level error
            if "code" in data and data["code"] != "":
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"API error [{data.get('code')}]: {data.get('message', 'Unknown')[:150]}",
                    latency=time.time() - start,
                )

            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:300]}",
                    latency=time.time() - start,
                )

            result = _poll_dashscope_task(task_id, DASHSCOPE_API_KEY, timeout=_env_int("IMAGE_TASK_TIMEOUT", 180))
            # Kling uses choices[].message.content[].image format
            choices = result.get("output", {}).get("choices", [])
            urls = []
            for choice in choices:
                for item in choice.get("message", {}).get("content", []):
                    if "image" in item:
                        urls.append(item["image"])
            # Fallback: some models use results[].url format
            if not urls:
                results = result.get("output", {}).get("results", [])
                for item in results:
                    if "url" in item:
                        urls.append(item["url"])
                    elif "image" in item:
                        urls.append(item["image"])

            return GenerationResult(
                success=bool(urls), task_id=task_id, model_id=self.spec.id,
                outputs=urls, latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("kling/kling-v3-image-generation")
class KlingV3ImageAdapter(_AsyncImageAdapter):
    MODEL_ID = "kling/kling-v3-image-generation"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="kling/kling-v3-image-generation", name="Kling V3 Image", provider="kling", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_image"], avg_latency_seconds=45.0,
        )


@register_model("kling/kling-v3-omni-image-generation")
class KlingV3OmniImageAdapter(_AsyncImageAdapter):
    MODEL_ID = "kling/kling-v3-omni-image-generation"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="kling/kling-v3-omni-image-generation", name="Kling V3 Omni Image", provider="kling", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=50.0,
        )


