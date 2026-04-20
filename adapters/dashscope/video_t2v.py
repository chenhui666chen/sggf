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
# 8. 视频生成 - 百炼异步API (文生视频: wan2.7-t2v, wan2.6-t2v)
# ============================================================

class _DashScopeT2VAdapter(BaseAdapter):
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
            payload = {
                "model": self.MODEL_ID,
                "input": {"prompt": prompt},
                "parameters": kwargs.get("parameters", {"duration": 5, "resolution": "720P"}),
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


@register_model("wan2.7-t2v")
class Wan27T2VAdapter(_DashScopeT2VAdapter):
    MODEL_ID = "wan2.7-t2v"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.7-t2v", name="Wan 2.7 T2V", provider="alibaba", version="v2.7",
            status=ModelStatus.ACTIVE, modality=["text_to_video", "image_to_video"], avg_latency_seconds=60.0,
        )


@register_model("wan2.6-t2v-fast")
class Wan26T2VFashAdapter(_DashScopeT2VAdapter):
    MODEL_ID = "wan2.6-t2v"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.6-t2v-fast", name="Wan 2.6 T2V Fast", provider="alibaba", version="v2.6",
            status=ModelStatus.ACTIVE, modality=["text_to_video"], avg_latency_seconds=45.0,
        )


