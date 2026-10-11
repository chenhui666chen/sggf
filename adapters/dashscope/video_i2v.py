# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
import requests
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import DASHSCOPE_BASE, _encode_image, _env_int, _poll_dashscope_task, require_api_key
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 8b. 视频生成 - 百炼异步API (PixVerse, 使用input.media + parameters.size)
# ============================================================

class _PixverseVideoAdapter(BaseAdapter):
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
            api_key = require_api_key("DASHSCOPE_API_KEY")
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/video-generation/video-synthesis"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            media = []
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    media.append({"type": "image_url", "url": img})

            inp = {"prompt": prompt}
            if media:
                inp["media"] = media

            payload = {
                "model": self.MODEL_ID,
                "input": inp,
                "parameters": kwargs.get("parameters", {"size": "1280*720", "duration": 5}),
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

            result = _poll_dashscope_task(task_id, api_key, timeout=_env_int("VIDEO_TASK_TIMEOUT", 600))
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


@register_model("pixverse-c1-r2v")
class PixverseC1R2VAdapter(_PixverseVideoAdapter):
    MODEL_ID = "pixverse/pixverse-c1-r2v"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="pixverse-c1-r2v", name="PixVerse C1 R2V", provider="pixverse", version="v1",
            status=ModelStatus.ACTIVE, modality=["image_to_video", "reference_to_video"], avg_latency_seconds=45.0,
        )


@register_model("pixverse-v6-t2v")
class PixverseV6T2VAdapter(_PixverseVideoAdapter):
    MODEL_ID = "pixverse/pixverse-v6-t2v"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="pixverse-v6-t2v", name="PixVerse V6 T2V", provider="pixverse", version="v6",
            status=ModelStatus.ACTIVE, modality=["text_to_video"], avg_latency_seconds=45.0,
        )


