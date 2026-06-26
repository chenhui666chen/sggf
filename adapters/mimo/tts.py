from __future__ import annotations

from typing import Any, Dict

from adapters.base import BaseAdapter, GenerationResult
from adapters.registry import register_model
from schemas.common import ModelStatus
from schemas.model_spec import ModelSpec


class _MiMoV25TTSRuntimeSpecAdapter(BaseAdapter):
    MODEL_ID = ""
    MODEL_NAME = ""
    VERSION = "v2.5"
    AVG_LATENCY_SECONDS = 3.0

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
            error="MiMo TTS synthesis is handled by the audiobook TTSEngine runtime",
            error_code="adapter_missing",
        )

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id=cls.MODEL_ID,
            name=cls.MODEL_NAME,
            provider="mimo",
            version=cls.VERSION,
            status=ModelStatus.ACTIVE,
            modality=["text_to_speech"],
            avg_latency_seconds=cls.AVG_LATENCY_SECONDS,
            endpoint="https://api.xiaomimimo.com/v1/chat/completions",
            auth_method="api_key",
            requires_external_network=True,
            summary="小米 MiMo-V2.5-TTS 系列有声小说运行时注册；真实合成由 audiobook TTSEngine 调用 MiMo OpenAI 兼容接口。",
            tags=["audio", "tts", "mimo", "audiobook"],
        )


@register_model("mimo-v2.5-tts")
class MiMoV25TTSAdapter(_MiMoV25TTSRuntimeSpecAdapter):
    MODEL_ID = "mimo-v2.5-tts"
    MODEL_NAME = "MiMo V2.5 TTS"
    VERSION = "v2.5"
    AVG_LATENCY_SECONDS = 3.0


@register_model("mimo-v2.5-tts-voicedesign")
class MiMoV25TTSVoiceDesignAdapter(_MiMoV25TTSRuntimeSpecAdapter):
    MODEL_ID = "mimo-v2.5-tts-voicedesign"
    MODEL_NAME = "MiMo V2.5 TTS Voice Design"
    VERSION = "v2.5-voicedesign"
    AVG_LATENCY_SECONDS = 4.0


@register_model("mimo-v2.5-tts-voiceclone")
class MiMoV25TTSVoiceCloneAdapter(_MiMoV25TTSRuntimeSpecAdapter):
    MODEL_ID = "mimo-v2.5-tts-voiceclone"
    MODEL_NAME = "MiMo V2.5 TTS Voice Clone"
    VERSION = "v2.5-voiceclone"
    AVG_LATENCY_SECONDS = 4.0
