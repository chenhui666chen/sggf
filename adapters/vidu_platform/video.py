# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import VIDU_API_KEY, _encode_image, _env_int, _poll_vidu_task
from adapters.dashscope.video_t2v import _DashScopeT2VAdapter
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 8f. 视频生成 - 百炼异步API (Vidu, 使用input.media格式)
# ============================================================

class _ViduVideoAdapter(BaseAdapter):
    MODEL_ID = ""
    MIN_IMAGES = 1

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
                    media.append({"type": "image", "url": img})
            if kwargs.get("image_paths"):
                for img_path in kwargs["image_paths"]:
                    img = _encode_image(img_path)
                    if img:
                        media.append({"type": "image", "url": img})
            while len(media) < self.MIN_IMAGES and media:
                media.append(media[-1])

            inp = {"prompt": prompt}
            if media:
                inp["media"] = media

            payload = {
                "model": self.MODEL_ID,
                "input": inp,
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


@register_model("vidu-q3-pro-img2video")
class ViduQ3ProImg2VideoAdapter(_ViduVideoAdapter):
    MODEL_ID = "vidu/viduq3-pro_img2video"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="vidu-q3-pro-img2video", name="Vidu Q3 Pro Img2Video", provider="vidu", version="q3",
            status=ModelStatus.ACTIVE, modality=["image_to_video"], avg_latency_seconds=45.0,
        )


@register_model("vidu-q3-pro-text2video")
class ViduQ3ProText2VideoAdapter(_DashScopeT2VAdapter):
    MODEL_ID = "vidu/viduq3-pro_text2video"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="vidu-q3-pro-text2video", name="Vidu Q3 Pro Text2Video", provider="vidu", version="q3",
            status=ModelStatus.ACTIVE, modality=["text_to_video"], avg_latency_seconds=45.0,
        )


@register_model("vidu-q3-pro-start-end2video")
class ViduQ3ProStartEndAdapter(_ViduVideoAdapter):
    MODEL_ID = "vidu/viduq3-pro_start-end2video"
    MIN_IMAGES = 2

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="vidu-q3-pro-start-end2video", name="Vidu Q3 Pro Start-End", provider="vidu", version="q3",
            status=ModelStatus.ACTIVE, modality=["image_to_video", "start_end_to_video"], avg_latency_seconds=50.0,
        )


