# -*- coding: utf-8 -*-
"""百炼统一音频生成（Audiogen）适配器。

与常规 TTS 的区别：本模型不吃 `text` + `voice`，而是吃一段 `text_prompt`
（可含 @voiceN 参考音频引用），一次产出包含人声、音效、环境声、配乐的完整音频。
契约全部来自 2026-10-10 真实调用，见 config/models.yaml 同 ID 档案与
docs/MODEL_INTEGRATION_REFERENCE.md §11.8。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import requests

from adapters._shared import DASHSCOPE_BASE, _env_int, require_api_key
from adapters.base import BaseAdapter, GenerationResult
from adapters.registry import register_model
from schemas.common import ModelStatus
from schemas.model_spec import ModelSpec

QWEN_AUDIO_31_TTS_NEXT_MODEL = "qwen-audio-3.1-tts-next"
QWEN_AUDIO_31_TTS_NEXT_ENDPOINT = "/api/v1/services/audio/tts/SpeechSynthesizer"

# 常量全部带模型前缀：adapters/dashscope/__init__.py 用 import * 暴露子模块，
# 不带前缀的通用名（如 DEFAULT_AUDIO_CONFIG）会和豆包 Seed Audio 的同名常量互相覆盖。
QWEN_AUDIO_NEXT_MAX_PROMPT_CHARS = 3000
QWEN_AUDIO_NEXT_MAX_REFERENCES = 3
QWEN_AUDIO_NEXT_SUPPORTED_FORMATS = frozenset({"wav", "mp3", "pcm"})
QWEN_AUDIO_NEXT_SUPPORTED_SAMPLE_RATES = frozenset({8000, 16000, 24000, 44100, 48000})
QWEN_AUDIO_NEXT_SUPPORTED_CHANNELS = frozenset({1, 2})
QWEN_AUDIO_NEXT_MIN_RATE = 0.5
QWEN_AUDIO_NEXT_MAX_RATE = 2.0
QWEN_AUDIO_NEXT_MIN_VOLUME = 0
QWEN_AUDIO_NEXT_MAX_VOLUME = 100
QWEN_AUDIO_NEXT_REFERENCE_FIELDS = ("audio_url", "audio_data")

# 请求体白名单：路由层会把豆包 Seed Audio 的 audio_config（pitch_rate / enable_subtitle 等）
# 原样传进来，未知字段必须在此丢弃，否则上游 400。
QWEN_AUDIO_NEXT_INPUT_PARAMS = (
    "format",
    "sample_rate",
    "channels",
    "volume",
    "rate",
    "seed",
    "enable_cbr",
    "bit_rate",
    "quality",
    "enable_aigc_tag",
)

QWEN_AUDIO_NEXT_DEFAULT_CONFIG: Dict[str, Any] = {
    "format": "wav",
    "sample_rate": 48000,
    "channels": 2,
}


@register_model(QWEN_AUDIO_31_TTS_NEXT_MODEL)
class QwenAudio31TtsNextAdapter(BaseAdapter):
    """Qwen-Audio 3.1 TTS Next（Audiogen）文本→完整音频生成适配器。"""

    MODEL_ID = QWEN_AUDIO_31_TTS_NEXT_MODEL
    MODEL_NAME = "Qwen-Audio 3.1 TTS Next"

    def _map_task_to_request(self, task: Any) -> Dict[str, Any]:
        if isinstance(task, dict):
            source = dict(task)
        else:
            source = dict(getattr(task, "extra", {}) or {})
            if not source.get("text_prompt") and not source.get("prompt"):
                source["text_prompt"] = getattr(task, "prompt", "")

        prompt = str(source.get("text_prompt") or source.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("text_prompt is required")
        if len(prompt) > QWEN_AUDIO_NEXT_MAX_PROMPT_CHARS:
            raise ValueError(
                f"text_prompt must not exceed {QWEN_AUDIO_NEXT_MAX_PROMPT_CHARS} characters"
            )

        audio_config_value = source.get("audio_config")
        if audio_config_value is not None and not isinstance(audio_config_value, dict):
            raise ValueError("audio_config must be an object")
        audio_config = {**QWEN_AUDIO_NEXT_DEFAULT_CONFIG, **dict(audio_config_value or {})}

        payload_input: Dict[str, Any] = {"text_prompt": prompt}
        dropped_params: List[str] = []
        for key, value in audio_config.items():
            if key in QWEN_AUDIO_NEXT_INPUT_PARAMS:
                payload_input[key] = value
            else:
                # 含 text_prompt / references：提示词与参考音频只认顶层入参，不接受 audio_config 覆盖。
                dropped_params.append(str(key))

        self._validate_audio_params(payload_input)

        if source.get("references") is not None:
            references = self._validate_references(source["references"])
            if references:
                payload_input["references"] = references

        watermark = source.get("watermark")
        if isinstance(watermark, dict) and watermark:
            # 本模型只有“加 AIGC 标识”的 enable_aigc_tag，没有豆包那种 watermark 对象；
            # 非空 watermark 请求必须留痕，不能装作已生效。
            dropped_params.append("watermark")

        return {
            "model": str(source.get("model") or self.spec.id or self.MODEL_ID).strip() or self.MODEL_ID,
            "input": payload_input,
            "_dropped_params": dropped_params,
        }

    @staticmethod
    def _validate_audio_params(payload_input: Dict[str, Any]) -> None:
        """按服务端实测口径先校验，越界直接本地报错，不带注定 400 的请求出门。"""
        audio_format = str(payload_input.get("format") or "").strip().lower()
        if audio_format and audio_format not in QWEN_AUDIO_NEXT_SUPPORTED_FORMATS:
            supported = ", ".join(sorted(QWEN_AUDIO_NEXT_SUPPORTED_FORMATS))
            raise ValueError(f"unsupported format: {audio_format}; expected one of {supported}")

        if "sample_rate" in payload_input:
            try:
                sample_rate = int(payload_input["sample_rate"])
            except (TypeError, ValueError):
                raise ValueError("sample_rate must be an integer")
            if sample_rate not in QWEN_AUDIO_NEXT_SUPPORTED_SAMPLE_RATES:
                supported = ", ".join(
                    str(value) for value in sorted(QWEN_AUDIO_NEXT_SUPPORTED_SAMPLE_RATES)
                )
                raise ValueError(f"unsupported sample_rate: {sample_rate}; expected one of {supported}")
            payload_input["sample_rate"] = sample_rate

        if "channels" in payload_input:
            try:
                channels = int(payload_input["channels"])
            except (TypeError, ValueError):
                raise ValueError("channels must be an integer")
            if channels not in QWEN_AUDIO_NEXT_SUPPORTED_CHANNELS:
                raise ValueError("channels must be either 1 or 2")
            payload_input["channels"] = channels

        if "rate" in payload_input:
            try:
                rate = float(payload_input["rate"])
            except (TypeError, ValueError):
                raise ValueError("rate must be a number")
            if not QWEN_AUDIO_NEXT_MIN_RATE <= rate <= QWEN_AUDIO_NEXT_MAX_RATE:
                raise ValueError(
                    f"rate must be within [{QWEN_AUDIO_NEXT_MIN_RATE}, {QWEN_AUDIO_NEXT_MAX_RATE}]"
                )
            payload_input["rate"] = rate

        if "volume" in payload_input:
            try:
                volume = int(payload_input["volume"])
            except (TypeError, ValueError):
                raise ValueError("volume must be an integer")
            if not QWEN_AUDIO_NEXT_MIN_VOLUME <= volume <= QWEN_AUDIO_NEXT_MAX_VOLUME:
                raise ValueError(
                    f"volume must be within [{QWEN_AUDIO_NEXT_MIN_VOLUME}, {QWEN_AUDIO_NEXT_MAX_VOLUME}]"
                )
            payload_input["volume"] = volume

    @staticmethod
    def _validate_references(value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError("references must be an array")
        if len(value) > QWEN_AUDIO_NEXT_MAX_REFERENCES:
            raise ValueError(f"references must not exceed {QWEN_AUDIO_NEXT_MAX_REFERENCES} items")

        normalized: List[Dict[str, Any]] = []
        for index, raw_reference in enumerate(value):
            if not isinstance(raw_reference, dict):
                raise ValueError(f"references[{index}] must be an object")
            if "speaker" in raw_reference and not any(
                str(raw_reference.get(field) or "").strip()
                for field in QWEN_AUDIO_NEXT_REFERENCE_FIELDS
            ):
                # 豆包 Seed Audio 用 speaker 音色 ID，本模型只认参考音频本身。
                raise ValueError(
                    f"references[{index}]: {QWEN_AUDIO_31_TTS_NEXT_MODEL} does not accept speaker "
                    "voice IDs; provide audio_url or audio_data instead"
                )
            populated = [
                field
                for field in QWEN_AUDIO_NEXT_REFERENCE_FIELDS
                if str(raw_reference.get(field) or "").strip()
            ]
            if len(populated) != 1:
                fields = " or ".join(QWEN_AUDIO_NEXT_REFERENCE_FIELDS)
                raise ValueError(f"references[{index}] must specify exactly one of {fields}")

            reference = dict(raw_reference)
            field = populated[0]
            reference[field] = str(reference[field]).strip()
            reference.pop("speaker", None)
            if field == "audio_url" and not reference[field].startswith(("http://", "https://")):
                raise ValueError(f"references[{index}].audio_url must be an HTTP(S) URL")
            normalized.append(reference)
        return normalized

    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        api_key = require_api_key("DASHSCOPE_API_KEY")
        payload = {key: value for key, value in request.items() if not key.startswith("_")}
        response = requests.post(
            f"{DASHSCOPE_BASE}{QWEN_AUDIO_31_TTS_NEXT_ENDPOINT}",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=_env_int("DASHSCOPE_AUDIO_GENERATION_TIMEOUT", 300),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Qwen audio generation response must be an object")
        return data

    def _parse_response(self, response: Dict[str, Any], task: Any) -> GenerationResult:
        output = response.get("output") if isinstance(response.get("output"), dict) else {}
        audio = output.get("audio") if isinstance(output.get("audio"), dict) else {}
        request_id = str(response.get("request_id") or "").strip()

        outputs: List[str] = []
        audio_url = str(audio.get("url") or "").strip()
        audio_data = str(audio.get("data") or "").strip()
        if audio_url:
            outputs.append(audio_url)
        if audio_data:
            outputs.append(
                audio_data
                if audio_data.startswith("data:audio/")
                else "data:audio/{format};base64,{data}".format(
                    format=str(audio.get("format") or "wav").strip().lower(), data=audio_data
                )
            )
        if not outputs:
            return GenerationResult(
                success=False,
                task_id=request_id,
                model_id=self.spec.id,
                error="Qwen audio generation response did not contain output.audio.url or output.audio.data",
                error_code="invalid_response",
                raw_response=response,
            )

        metadata: Dict[str, Any] = {}
        duration = audio.get("duration")
        if isinstance(duration, (int, float)):
            # 结算链路按 metadata.duration 取实际时长结算。
            metadata["duration"] = float(duration)
        if audio.get("id"):
            metadata["audio_id"] = str(audio["id"])
        if audio.get("expires_at"):
            metadata["audio_expires_at"] = audio.get("expires_at")
        if output.get("finish_reason"):
            metadata["finish_reason"] = str(output["finish_reason"])
        usage = response.get("usage")
        if isinstance(usage, dict):
            # 本模型按 token 计费，供应商回传 input/output tokens 才能核对成本。
            metadata["usage"] = dict(usage)
        if request_id:
            metadata["request_id"] = request_id
        return GenerationResult(
            success=True,
            task_id=request_id,
            model_id=self.spec.id,
            outputs=outputs,
            metadata=metadata,
            raw_response=response,
        )

    def generate(self, prompt: str = "", **kwargs: Any) -> GenerationResult:
        started = time.time()
        payload = dict(kwargs)
        payload.setdefault("text_prompt", prompt)
        try:
            request = self._map_task_to_request(payload)
            dropped_params = list(request.get("_dropped_params") or [])
            result = self._parse_response(self._call_api(request), None)
            if dropped_params and result.success:
                # 丢弃的上游不认识的参数要留痕，否则排查“参数没生效”时无从下手。
                result.metadata = {**dict(result.metadata or {}), "dropped_params": dropped_params}
        except Exception as exc:
            result = self._build_error_result(exc)
        result.latency = time.time() - started
        return result

    def _build_error_result(self, exc: Exception) -> GenerationResult:
        error_code = "provider_error"
        retryable = False
        status_code = None
        provider_code = ""
        provider_message = ""
        request_id = ""
        error_message = str(exc)

        if isinstance(exc, ValueError):
            error_code = "invalid_request"
        elif isinstance(exc, requests.Timeout):
            error_code = "provider_timeout"
            retryable = True
        elif isinstance(exc, requests.ConnectionError):
            error_code = "provider_connection_error"
            retryable = True
        elif isinstance(exc, requests.HTTPError):
            response = exc.response
            status_code = getattr(response, "status_code", None)
            try:
                candidate = response.json() if response is not None else {}
            except (TypeError, ValueError, requests.RequestException):
                candidate = {}
            if isinstance(candidate, dict):
                provider_code = str(candidate.get("code") or "").strip()
                provider_message = str(candidate.get("message") or "").strip()
                request_id = str(candidate.get("request_id") or "").strip()
            if provider_message and provider_message not in error_message:
                error_message = f"{error_message}: {provider_message}"

            if status_code == 429:
                error_code = "rate_limited"
                retryable = True
            elif status_code in {408, 504}:
                error_code = "provider_timeout"
                retryable = True
            elif isinstance(status_code, int) and status_code >= 500:
                error_code = "provider_unavailable"
                retryable = True
            elif status_code in {401, 403}:
                error_code = "authentication_error"
            elif isinstance(status_code, int) and 400 <= status_code < 500:
                error_code = "invalid_request"

        trace: Dict[str, Any] = {"retryable": retryable}
        if status_code is not None:
            trace["status_code"] = status_code
        if provider_code:
            trace["provider_code"] = provider_code
        return GenerationResult(
            success=False,
            task_id=request_id,
            model_id=self.spec.id,
            error=error_message,
            error_code=error_code,
            trace=trace,
        )

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id=cls.MODEL_ID,
            name=cls.MODEL_NAME,
            provider="dashscope",
            version="3.1",
            status=ModelStatus.ACTIVE,
            modality=["text_to_audio"],
            avg_latency_seconds=20.0,
            endpoint=f"{DASHSCOPE_BASE}{QWEN_AUDIO_31_TTS_NEXT_ENDPOINT}",
            auth_method="bearer",
            requires_external_network=True,
            summary=(
                "Unified Audiogen model: one text prompt (optionally with @voiceN reference clips) "
                "produces speech, dialogue, ambience, sound effects and music in a single audio file."
            ),
            tags=["audio", "audio-generation", "qwen", "dashscope", "sound-effect", "multi-speaker"],
        )
