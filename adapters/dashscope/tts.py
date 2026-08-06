# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Any, Dict, Tuple

from adapters import adapter_helpers
from adapters.base import BaseAdapter, GenerationResult
from adapters.registry import register_model
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus
from schemas.task_spec import TaskSpec

# ============================================================
# 7. TTS/语音 - 百炼模型的统一运行时适配
# ============================================================

class _DashScopeTTSAdapter(BaseAdapter):
    MODEL_ID = ""
    VOICE_ID = "longxiaochun"

    _DISPATCH_ONLY_FIELDS = {"agent_type", "strategy"}

    def _map_task_to_request(self, task: TaskSpec) -> Dict[str, Any]:
        text, voice_params, emotion, _ = self._normalize_runtime_request(task, {})
        return {
            "text": text,
            "voice_params": voice_params,
            "emotion": emotion,
        }

    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError("TTS adapters must use the unified TTS runtime")

    def _parse_response(self, response: Dict[str, Any], task: TaskSpec) -> GenerationResult:
        raise RuntimeError("TTS adapters must use the unified TTS runtime")

    def _normalize_runtime_request(
        self,
        task_or_prompt: Any,
        kwargs: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any], str, str]:
        direct_kwargs = dict(kwargs or {})
        if isinstance(task_or_prompt, TaskSpec):
            text = str(task_or_prompt.prompt or "")
            task_id = str(task_or_prompt.task_id or "")
            extra = dict(task_or_prompt.extra or {})
        else:
            prompt = task_or_prompt
            if prompt is None:
                prompt = direct_kwargs.pop("prompt", direct_kwargs.pop("text", ""))
            text = str(prompt or "")
            task_id = str(direct_kwargs.pop("task_id", "") or "")
            extra = direct_kwargs

        nested_params = extra.pop("voice_params", {})
        voice_params = dict(nested_params) if isinstance(nested_params, dict) else {}
        for key, value in extra.items():
            if key in self._DISPATCH_ONLY_FIELDS:
                continue
            voice_params.setdefault(key, value)

        selected_voice = (
            extra.get("voice_id")
            or extra.get("speaker")
            or voice_params.get("speaker")
            or voice_params.get("voice_id")
            or self.VOICE_ID
        )
        if str(selected_voice or "").strip():
            voice_params["speaker"] = str(selected_voice).strip()

        for model_field in ("model_id", "resolved_tts_model", "tts_model"):
            voice_params.pop(model_field, None)
        voice_params["tts_model"] = self.MODEL_ID

        emotion = str(
            voice_params.get("instruct_emotion")
            or voice_params.get("emotion")
            or "neutral"
        ).strip() or "neutral"
        return text, voice_params, emotion, task_id

    def generate(self, task: Any = None, **kwargs: Any) -> GenerationResult:
        start = time.time()
        try:
            if task is None and "prompt" in kwargs:
                task = kwargs.pop("prompt")
            text, voice_params, emotion, task_id = self._normalize_runtime_request(
                task,
                kwargs,
            )
            result = adapter_helpers.synthesize_speech_sync(
                text=text,
                voice_params=voice_params,
                emotion=emotion,
                model_id=self.MODEL_ID,
            )

            metadata = dict(getattr(result, "metadata", {}) or {})
            data = getattr(result, "data", {})
            audio_bytes = getattr(result, "binary", None)
            if not isinstance(audio_bytes, (bytes, bytearray)) and isinstance(data, dict):
                audio_bytes = data.get("audio_bytes")
            if isinstance(audio_bytes, bytearray):
                audio_bytes = bytes(audio_bytes)
            if isinstance(audio_bytes, bytes):
                metadata["audio_bytes"] = audio_bytes

            outputs = list(getattr(result, "outputs", []) or [])
            if isinstance(audio_bytes, bytes) and not outputs:
                outputs = [f"audio:{len(audio_bytes)} bytes"]

            return GenerationResult(
                success=bool(getattr(result, "success", False)),
                task_id=task_id,
                model_id=self.spec.id,
                outputs=outputs,
                metadata=metadata,
                error=getattr(result, "error", None),
                error_code=getattr(result, "error_code", None),
                cost=float(getattr(result, "cost", 0.0) or 0.0),
                latency=float(getattr(result, "latency", 0.0) or (time.time() - start)),
                trace={"runtime_boundary": "unified_tts_engine"},
            )
        except Exception as exc:
            return GenerationResult(
                success=False,
                task_id=str(getattr(task, "task_id", "") or ""),
                model_id=self.spec.id,
                error=str(exc),
                error_code="execution_error",
                latency=time.time() - start,
                trace={"runtime_boundary": "unified_tts_engine"},
            )


@register_model("MiniMax/speech-2.8-turbo")
class MiniMaxSpeechTurboAdapter(_DashScopeTTSAdapter):
    MODEL_ID = "MiniMax/speech-2.8-turbo"
    VOICE_ID = "male-qn-qingse"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="MiniMax/speech-2.8-turbo", name="MiniMax Speech 2.8 Turbo", provider="minimax", version="v2.8",
            status=ModelStatus.ACTIVE, modality=["text_to_speech"], avg_latency_seconds=5.0,
        )


@register_model("MiniMax/speech-2.8-hd")
class MiniMaxSpeechHDAdapter(MiniMaxSpeechTurboAdapter):
    MODEL_ID = "MiniMax/speech-2.8-hd"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="MiniMax/speech-2.8-hd", name="MiniMax Speech 2.8 HD", provider="minimax", version="v2.8",
            status=ModelStatus.ACTIVE, modality=["text_to_speech"], avg_latency_seconds=8.0,
        )


@register_model("qwen3-tts-instruct-flash")
class Qwen3TTSInstructFlashAdapter(_DashScopeTTSAdapter):
    MODEL_ID = "qwen3-tts-instruct-flash"
    VOICE_ID = "Cherry"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3-tts-instruct-flash", name="Qwen3 TTS Instruct Flash", provider="alibaba", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_speech"], avg_latency_seconds=3.0,
        )


@register_model("cosyvoice-v3.5-plus")
class CosyVoiceV35PlusAdapter(_DashScopeTTSAdapter):
    MODEL_ID = "cosyvoice-v3.5-plus"
    VOICE_ID = ""

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="cosyvoice-v3.5-plus", name="CosyVoice V3.5 Plus", provider="alibaba", version="v3.5",
            status=ModelStatus.ACTIVE, modality=["text_to_speech"], avg_latency_seconds=3.0,
        )
