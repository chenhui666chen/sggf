# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import MUREKA_API_KEY, MUREKA_API_URL
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 12. 音乐生成 - Mureka平台
# ============================================================

@register_model("mureka-o1-instrumental")
class MurekaO1InstrumentalAdapter(BaseAdapter):
    MODEL_ID = "mureka-o1-instrumental"

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{MUREKA_API_URL}/v1/instrumental/generate"
            headers = {"Authorization": f"Bearer {MUREKA_API_KEY}", "Content-Type": "application/json"}
            payload = {"prompt": prompt or "epic cinematic music", "model": "auto", "duration": 30}
            r = requests.post(url, json=payload, headers=headers, timeout=120)
            if r.status_code != 200:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"HTTP {r.status_code}: {r.text[:200]}",
                    latency=time.time() - start,
                )
            data = r.json()
            # Mureka returns async task with status
            task_id = data.get("id", "")
            status = data.get("status", "")
            audio_url = data.get("url", "") or data.get("audio_url", "")
            if audio_url:
                return GenerationResult(
                    success=True, task_id=task_id, model_id=self.spec.id,
                    outputs=[audio_url], latency=time.time() - start,
                )
            if task_id and status in ("preparing", "processing", "queued"):
                # Poll for result
                poll_start = time.time()
                while time.time() - poll_start < 300:
                    time.sleep(5)
                    pr = requests.get(
                        f"{MUREKA_API_URL}/v1/instrumental/query/{task_id}",
                        headers={"Authorization": f"Bearer {MUREKA_API_KEY}"},
                        timeout=30,
                    )
                    if pr.status_code == 200:
                        pdata = pr.json()
                        pstatus = pdata.get("status", "")
                        purl = pdata.get("url", "") or pdata.get("audio_url", "")
                        # Check choices array for audio URLs
                        if not purl:
                            choices = pdata.get("choices", [])
                            for c in choices:
                                if "url" in c:
                                    purl = c["url"]
                                    break
                        if purl and pstatus in ("succeeded", "completed", "success"):
                            return GenerationResult(
                                success=True, task_id=task_id, model_id=self.spec.id,
                                outputs=[purl], latency=time.time() - start,
                            )
                        if pstatus in ("failed", "error"):
                            return GenerationResult(
                                success=False, task_id=task_id, model_id=self.spec.id,
                                error=f"Mureka task failed: {json.dumps(pdata, ensure_ascii=False)[:200]}",
                                latency=time.time() - start,
                            )
                return GenerationResult(
                    success=False, task_id=task_id, model_id=self.spec.id,
                    error=f"Mureka task timed out after 180s",
                    latency=time.time() - start,
                )
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=f"Unexpected: {json.dumps(data, ensure_ascii=False)[:200]}",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="mureka-o1-instrumental", name="Mureka O1 Instrumental", provider="mureka", version="v1",
            status=ModelStatus.ACTIVE, modality=["text_to_audio"], avg_latency_seconds=30.0,
        )
