# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
import requests
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import DASHSCOPE_API_KEY, DASHSCOPE_BASE, _encode_image, _env_int, _poll_dashscope_task
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 8g. 视频生成 - 百炼异步API (Kling视频, 使用input.media格式)
# ============================================================

class _KlingVideoAdapter(BaseAdapter):
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
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/video-generation/video-synthesis"
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            media = []
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    media.append({"type": "first_frame", "url": img})

            inp = {"prompt": prompt}
            if media:
                inp["media"] = media

            payload = {
                "model": self.MODEL_ID,
                "input": inp,
                "parameters": kwargs.get("parameters", {"duration": 5, "aspect_ratio": "16:9"}),
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            data = r.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            result = _poll_dashscope_task(task_id, DASHSCOPE_API_KEY, timeout=_env_int("VIDEO_TASK_TIMEOUT", 600))
            urls = []
            video_url = result.get("output", {}).get("video_url", "")
            if video_url:
                urls.append(video_url)
            if not urls:
                outputs = result.get("output", {}).get("results", [])
                urls = [o.get("url", "") for o in outputs if o.get("url")]
            return GenerationResult(
                success=bool(urls), task_id=task_id, model_id=self.spec.id,
                outputs=urls, latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("kling/kling-v3-video-generation")
class KlingV3VideoAdapter(_KlingVideoAdapter):
    MODEL_ID = "kling/kling-v3-video-generation"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="kling/kling-v3-video-generation", name="Kling V3 Video", provider="kling", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_video"], avg_latency_seconds=60.0,
        )


@register_model("kling/kling-v3-omni-video-generation")
class KlingV3OmniVideoAdapter(_KlingVideoAdapter):
    MODEL_ID = "kling/kling-v3-omni-video-generation"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="kling/kling-v3-omni-video-generation", name="Kling V3 Omni Video", provider="kling", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_video", "image_to_video"], avg_latency_seconds=60.0,
        )


