from __future__ import annotations

from typing import Any, Dict

from adapters.base import BaseAdapter, GenerationResult
from adapters.registry import register_model
from schemas.common import ModelStatus
from schemas.model_spec import ModelSpec


@register_model("seed-tts-2.0-expressive")
class SeedTTS20ExpressiveAdapter(BaseAdapter):
    """Runtime registration for Doubao Seed-TTS 2.0 audiobook synthesis."""

    def _map_task_to_request(self, task: Any) -> Dict[str, Any]:
        return {"text": task.prompt}

    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def _parse_response(self, response: Dict[str, Any], task: Any) -> GenerationResult:
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs: Any) -> GenerationResult:
        return GenerationResult(
            success=False,
            task_id="",
            model_id=self.spec.id,
            error="Doubao Seed-TTS synthesis is handled by the audiobook TTSEngine runtime",
            error_code="adapter_missing",
        )

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="seed-tts-2.0-expressive",
            name="Doubao Seed-TTS 2.0 Expressive",
            provider="volcengine",
            version="2.0-expressive",
            status=ModelStatus.ACTIVE,
            modality=["text_to_speech"],
            avg_latency_seconds=3.0,
            endpoint="https://openspeech.bytedance.com/api/v3/tts/unidirectional",
            auth_method="x_api_key",
            requires_external_network=True,
            summary=(
                "Doubao Seed-TTS 2.0 Expressive audiobook runtime registration; "
                "actual synthesis is performed by audiobook TTSEngine."
            ),
            tags=["audio", "tts", "doubao", "seed-tts", "volcengine", "audiobook"],
        )
