from __future__ import annotations

import os
import time
from typing import Any, Dict

import requests

from adapters.base import BaseAdapter, GenerationResult
from adapters.registry import register_model
from schemas.common import ModelStatus
from schemas.model_spec import ModelSpec


SEED_AUDIO_10_MODEL = "seed-audio-1.0"
SEED_AUDIO_10_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/create"


@register_model(SEED_AUDIO_10_MODEL)
class DoubaoSeedAudio10Adapter(BaseAdapter):
    """Doubao Seed Audio 1.0 text-to-audio generation adapter."""

    def _map_task_to_request(self, task: Any) -> Dict[str, Any]:
        if isinstance(task, dict):
            source = task
        else:
            source = getattr(task, "extra", {}) or {}
        prompt = str(source.get("text_prompt") or source.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("text_prompt is required")
        payload: Dict[str, Any] = {"model": SEED_AUDIO_10_MODEL, "text_prompt": prompt}
        for key in ("references", "audio_config", "watermark"):
            if source.get(key) is not None:
                payload[key] = source[key]
        return payload

    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        api_key = (
            os.getenv("VOLCENGINE_OPEN_SPEECH_API_KEY", "").strip()
            or os.getenv("DOUBAO_API_KEY", "").strip()
        )
        if not api_key:
            raise RuntimeError("DOUBAO_API_KEY is not configured")
        response = requests.post(
            SEED_AUDIO_10_ENDPOINT,
            json=request,
            headers={"Content-Type": "application/json", "X-Api-Key": api_key},
            timeout=int(os.getenv("VOLCENGINE_OPEN_SPEECH_TIMEOUT", "300")),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Doubao Seed Audio response must be an object")
        return data

    def _parse_response(self, response: Dict[str, Any], task: Any) -> GenerationResult:
        url = str(response.get("url") or "").strip()
        if not url:
            return GenerationResult(
                success=False,
                task_id="",
                model_id=self.spec.id,
                error="Doubao Seed Audio response did not contain url",
                error_code="invalid_response",
                raw_response=response,
            )
        metadata = {key: response[key] for key in ("duration", "original_duration") if key in response}
        return GenerationResult(
            success=True,
            task_id="",
            model_id=self.spec.id,
            outputs=[url],
            metadata=metadata,
            raw_response=response,
        )

    def generate(self, prompt: str = "", **kwargs: Any) -> GenerationResult:
        started = time.time()
        payload = dict(kwargs)
        payload.setdefault("text_prompt", prompt)
        try:
            result = self._parse_response(self._call_api(self._map_task_to_request(payload)), None)
        except Exception as exc:
            result = GenerationResult(
                success=False,
                task_id="",
                model_id=self.spec.id,
                error=str(exc),
                error_code="provider_error",
            )
        result.latency = time.time() - started
        return result

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id=SEED_AUDIO_10_MODEL,
            name="Doubao Seed Audio 1.0",
            provider="volcengine",
            version="1.0",
            status=ModelStatus.ACTIVE,
            modality=["text_to_audio"],
            avg_latency_seconds=30.0,
            endpoint=SEED_AUDIO_10_ENDPOINT,
            auth_method="x_api_key",
            requires_external_network=True,
            summary="Doubao audio generation with dialogue, sound effects and music from a text prompt.",
            tags=["audio", "audio-generation", "doubao", "volcengine", "seed-audio"],
        )
