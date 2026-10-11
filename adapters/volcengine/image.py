# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
import requests
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import VOLCENGINE_BASE, _encode_image, _poll_volcengine_task, require_api_key
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 3. 图像生成 - 火山方舟 (Doubao Seedream)
# ============================================================

class _SeedreamImageAdapter(BaseAdapter):
    MODEL_ID = ""
    DEFAULT_SIZE = "2048x2048"
    MIN_AREA = 0
    MAX_AREA = 0

    def _resolve_size(self, raw: Any) -> str:
        """把上游下发的尺寸翻译成方舟接受的 WIDTHxHEIGHT，越界或无法解析时回退默认档。

        UnifiedMediaRuntime 的 legacy 通道按百炼约定拼 ``f"{width}*{height}"``，
        方舟只认 ``WIDTHxHEIGHT``，星号会直接 400 InvalidParameter。
        方舟还校验总面积下限（Pro 为 921600 px），runtime 的默认 1024x576 会被拒，
        故这里按 MIN_AREA/MAX_AREA 兜底回退到 DEFAULT_SIZE。
        """
        size = str(raw or "").strip().replace("*", "x")
        try:
            width, height = (int(part) for part in size.split("x", 1))
        except ValueError:
            return self.DEFAULT_SIZE
        area = width * height
        if self.MIN_AREA and area < self.MIN_AREA:
            return self.DEFAULT_SIZE
        if self.MAX_AREA and area > self.MAX_AREA:
            return self.DEFAULT_SIZE
        return f"{width}x{height}"

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            api_key = require_api_key("VOLCENGINE_API_KEY")
            url = f"{VOLCENGINE_BASE}/images/generations"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": self.MODEL_ID,
                "prompt": prompt or "一朵花",
                "size": self._resolve_size(kwargs.get("size")),
                "response_format": "url",
                # 方舟侧默认带"AI生成"水印，与视频线一致地显式关闭
                "watermark": False,
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


@register_model("doubao-seedream-5-0-pro")
class DoubaoSeedream50ProAdapter(_SeedreamImageAdapter):
    MODEL_ID = "doubao-seedream-5-0-pro-260628"
    # 1.5K 档：1536x1536 = 2359296 px，落在 ≤2610000 px 的 0.30 元/张计费带内。
    # 方舟默认档为 2K（0.60 元/张），这里显式降到 1.5K 以控制成本。
    DEFAULT_SIZE = "1536x1536"
    # 下限 921600 px 为 2026-10-08 实测（100x100 被拒并回显该数值）；
    # 上限 4624220 px 来自官方文档（约 2K，无 4K 档），未实测——越界只会回退默认档，不会失败。
    MIN_AREA = 921600
    MAX_AREA = 4624220

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedream-5-0-pro", name="Doubao Seedream 5.0 Pro", provider="doubao", version="v5.0-pro",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=20.0,
        )


@register_model("doubao-seedream-5-0")
class DoubaoSeedream50Adapter(_SeedreamImageAdapter):
    MODEL_ID = "doubao-seedream-5-0-260128"
    # 2026-10-08 实测：1024x576 被拒并回显 image size must be at least 3686400 pixels。
    # 上限未实测，留 0 表示不做高位兜底，由 constraints 的单边上限把关。
    MIN_AREA = 3686400

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedream-5-0", name="Doubao Seedream 5.0", provider="doubao", version="v5.0",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=15.0,
        )


