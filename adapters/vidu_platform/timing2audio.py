# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
import requests
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import VIDU_API_KEY, _poll_vidu_task
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 10. 音效生成 - Vidu平台 (timing2audio)
# ============================================================

@register_model("vidu-timing2audio")
class ViduTiming2AudioAdapter(BaseAdapter):
    MODEL_ID = "audio1.0"

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{VIDU_BASE}/ent/v2/timing2audio"
            headers = {
                "Authorization": f"Token {VIDU_API_KEY}",
                "Content-Type": "application/json",
            }
            timing_prompts = [{"prompt": prompt or "thunder sound effect", "from": 0, "to": kwargs.get("duration", 5)}]
            payload = {
                "model": self.MODEL_ID,
                "duration": kwargs.get("duration", 5),
                "timing_prompts": timing_prompts,
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"HTTP {r.status_code}: {r.text[:200]}",
                    latency=time.time() - start,
                )
            try:
                text = r.text.strip()
                if text.startswith("data:"):
                    lines = [l for l in text.split("\n") if l.startswith("data:") and not l.endswith("[DONE]")]
                    if lines:
                        data = json.loads(lines[0][5:].strip())
                    else:
                        data = {}
                else:
                    data = json.loads(text)
            except Exception as parse_err:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"JSON parse error: {parse_err}, raw: {r.text[:200]}",
                    latency=time.time() - start,
                )

            task_id = data.get("task_id", "")
            state = data.get("state", "")
            if not task_id or state == "failed":
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"Vidu API error: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            result = _poll_vidu_task(task_id, VIDU_API_KEY, timeout=_env_int("AUDIO_TASK_TIMEOUT", 120))

            audio_url = ""
            creations = result.get("creations", [])
            for c in creations:
                if "url" in c:
                    audio_url = c["url"]
                    break
            if not audio_url:
                audio_url = result.get("data", {}).get("audio_url", "") or result.get("audio_url", "")
            return GenerationResult(
                success=bool(audio_url), task_id=task_id, model_id=self.spec.id,
                outputs=[audio_url] if audio_url else [],
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
            id="vidu-timing2audio", name="Vidu Timing2Audio", provider="vidu", version="v1",
            status=ModelStatus.ACTIVE, modality=["text_to_audio", "timing_audio"], avg_latency_seconds=15.0,
        )


