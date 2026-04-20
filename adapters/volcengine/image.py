# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import VOLCENGINE_API_KEY, VOLCENGINE_BASE, _encode_image, _poll_volcengine_task
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 3. 图像生成 - 火山方舟 (Doubao Seedream)
# ============================================================

class _SeedreamImageAdapter(BaseAdapter):
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
            url = f"{VOLCENGINE_BASE}/images/generations"
            headers = {"Authorization": f"Bearer {VOLCENGINE_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": self.MODEL_ID,
                "prompt": prompt or "一朵花",
                "size": kwargs.get("size", "2048x2048"),
                "n": 1,
                "response_format": "url",
            }
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    payload["image"] = img

            r = requests.post(url, json=payload, headers=headers, timeout=120)
            data = r.json()

            if "error" in data:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"API error: {json.dumps(data['error'], ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            image_data = data.get("data", [])
            urls = []
            for item in image_data:
                if "url" in item:
                    urls.append(item["url"])
                elif "b64_json" in item:
                    urls.append(f"data:image/png;base64,{item['b64_json']}")

            return GenerationResult(
                success=bool(urls), task_id="", model_id=self.spec.id,
                outputs=urls, error=None if urls else f"No image data: {str(data)[:200]}",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("doubao-seedream-4-5")
class DoubaoSeedream45Adapter(_SeedreamImageAdapter):
    MODEL_ID = "doubao-seedream-4-5-251128"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedream-4-5", name="Doubao Seedream 4.5", provider="doubao", version="v4.5",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=15.0,
        )


@register_model("doubao-seedream-5-0")
class DoubaoSeedream50Adapter(_SeedreamImageAdapter):
    MODEL_ID = "doubao-seedream-5-0-260128"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedream-5-0", name="Doubao Seedream 5.0", provider="doubao", version="v5.0",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=15.0,
        )


