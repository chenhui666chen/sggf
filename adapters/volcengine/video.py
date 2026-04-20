# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import VOLCENGINE_API_KEY, VOLCENGINE_BASE, _encode_image, _env_int, _poll_volcengine_task
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 9. 视频生成 - 火山方舟 (Doubao Seedance)
# ============================================================

class _SeedanceVideoAdapter(BaseAdapter):
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
            url = f"{VOLCENGINE_BASE}/contents/generations/tasks"
            headers = {"Authorization": f"Bearer {VOLCENGINE_API_KEY}", "Content-Type": "application/json"}

            content = [{"type": "text", "text": prompt or "一只猫在奔跑"}]
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    content.append({"type": "image_url", "image_url": {"url": img}, "role": kwargs.get("image_role", "reference_image")})
            if kwargs.get("video_path"):
                vid = kwargs["video_path"]
                if vid:
                    content.append({"type": "video_url", "video_url": {"url": vid}, "role": kwargs.get("video_role", "reference_video")})
            if kwargs.get("audio_path"):
                aud = kwargs["audio_path"]
                if aud:
                    content.append({"type": "audio_url", "audio_url": {"url": aud}, "role": kwargs.get("audio_role", "reference_audio")})

            payload = {
                "model": self.MODEL_ID,
                "content": content,
                "ratio": kwargs.get("ratio", "16:9"),
                "duration": kwargs.get("duration", 5),
                "watermark": False,
            }
            if kwargs.get("generate_audio"):
                payload["generate_audio"] = True

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"HTTP {r.status_code}: {r.text[:200]}",
                    latency=time.time() - start,
                )
            data = r.json()

            if "error" in data:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"API error: {json.dumps(data['error'], ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            task_id = data.get("id", "")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            # Poll for result
            poll_start = time.time()
            while time.time() - poll_start < _env_int("VIDEO_TASK_TIMEOUT", 600):
                time.sleep(5)
                pr = requests.get(
                    f"{VOLCENGINE_BASE}/contents/generations/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {VOLCENGINE_API_KEY}"},
                    timeout=10,
                )
                if pr.status_code != 200:
                    continue
                pdata = pr.json()
                status = pdata.get("status", "")
                if status == "succeeded":
                    video_url = ""
                    # Format 1: content.video_url (Seedance 1.5/2.0)
                    content_data = pdata.get("content", {})
                    if isinstance(content_data, dict):
                        video_url = content_data.get("video_url", "")
                    # Format 2: video_url directly
                    if not video_url:
                        video_url = pdata.get("video_url", "")
                    # Format 3: video_result[].url
                    if not video_url:
                        videos = pdata.get("video_result", [])
                        for v in videos:
                            if "url" in v:
                                video_url = v["url"]
                                break
                    return GenerationResult(
                        success=bool(video_url), task_id=task_id, model_id=self.spec.id,
                        outputs=[video_url] if video_url else [],
                        latency=time.time() - start,
                    )
                elif status in ("failed", "cancelled", "expired"):
                    return GenerationResult(
                        success=False, task_id=task_id, model_id=self.spec.id,
                        error=f"Task {status}: {json.dumps(pdata, ensure_ascii=False)[:200]}",
                        latency=time.time() - start,
                    )

            return GenerationResult(
                success=False, task_id=task_id, model_id=self.spec.id,
                error=f"Task timed out after 600s",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("doubao-seedance-2-0")
class DoubaoSeedance20Adapter(_SeedanceVideoAdapter):
    MODEL_ID = "doubao-seedance-2-0-260128"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedance-2-0", name="Doubao Seedance 2.0", provider="doubao", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_to_video", "image_to_video", "audio_to_video", "video_to_video"],
            avg_latency_seconds=60.0,
        )


@register_model("doubao-seedance-2-0-fast")
class DoubaoSeedance20FastAdapter(_SeedanceVideoAdapter):
    MODEL_ID = "doubao-seedance-2-0-fast-260128"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedance-2-0-fast", name="Doubao Seedance 2.0 Fast", provider="doubao", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_to_video", "image_to_video"],
            avg_latency_seconds=45.0,
        )


@register_model("doubao-seedance-1-5-pro")
class DoubaoSeedance15ProAdapter(_SeedanceVideoAdapter):
    MODEL_ID = "doubao-seedance-1-5-pro-251215"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedance-1-5-pro", name="Doubao Seedance 1.5 Pro", provider="doubao", version="v1.5",
            status=ModelStatus.ACTIVE, modality=["text_to_video", "image_to_video"], avg_latency_seconds=60.0,
        )


