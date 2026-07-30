from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Any, Dict, List

import requests

from adapters.base import BaseAdapter, GenerationResult
from adapters.registry import register_model
from schemas.common import ModelStatus
from schemas.model_spec import ModelSpec


SEED_AUDIO_10_MODEL = "seed-audio-1.0"
SEED_AUDIO_10_MULTILINGUAL_MODEL = "seed-audio-1.0-multilingual"
SUPPORTED_SEED_AUDIO_MODELS = {
    SEED_AUDIO_10_MODEL,
    SEED_AUDIO_10_MULTILINGUAL_MODEL,
}
SEED_AUDIO_10_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/create"
SEED_AUDIO_MAX_PROMPT_CHARS = 3000
SEED_AUDIO_MAX_REFERENCES = 3
SEED_AUDIO_REFERENCE_FIELDS = ("speaker", "audio_data", "audio_url")
DEFAULT_AUDIO_CONFIG: Dict[str, Any] = {
    "format": "mp3",
    "sample_rate": 48000,
    "pitch_rate": 0,
    "speech_rate": 0,
    "loudness_rate": 0,
    "enable_subtitle": True,
}


@register_model(SEED_AUDIO_10_MODEL)
class DoubaoSeedAudio10Adapter(BaseAdapter):
    """Doubao Seed Audio 1.0 text-to-audio generation adapter."""

    MODEL_ID = SEED_AUDIO_10_MODEL
    MODEL_NAME = "Doubao Seed Audio 1.0"

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
        if len(prompt) > SEED_AUDIO_MAX_PROMPT_CHARS:
            raise ValueError(f"text_prompt must not exceed {SEED_AUDIO_MAX_PROMPT_CHARS} characters")

        model = str(source.get("model") or self.spec.id or self.MODEL_ID).strip()
        if model not in SUPPORTED_SEED_AUDIO_MODELS:
            supported = ", ".join(sorted(SUPPORTED_SEED_AUDIO_MODELS))
            raise ValueError(f"unsupported Seed Audio model: {model}; expected one of {supported}")

        audio_config_value = source.get("audio_config")
        if audio_config_value is not None and not isinstance(audio_config_value, dict):
            raise ValueError("audio_config must be an object")
        audio_config = {**DEFAULT_AUDIO_CONFIG, **dict(audio_config_value or {})}

        payload: Dict[str, Any] = {
            "model": model,
            "text_prompt": prompt,
            "audio_config": audio_config,
        }
        if source.get("references") is not None:
            references = self._validate_references(source["references"])
            if references:
                payload["references"] = references
        if source.get("watermark") is not None:
            payload["watermark"] = source["watermark"]
        return payload

    @staticmethod
    def _validate_references(value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError("references must be an array")
        if len(value) > SEED_AUDIO_MAX_REFERENCES:
            raise ValueError(f"references may contain at most {SEED_AUDIO_MAX_REFERENCES} items")

        normalized: List[Dict[str, Any]] = []
        for index, raw_reference in enumerate(value):
            if not isinstance(raw_reference, dict):
                raise ValueError(f"references[{index}] must be an object")
            populated_fields = [
                field
                for field in SEED_AUDIO_REFERENCE_FIELDS
                if str(raw_reference.get(field) or "").strip()
            ]
            if len(populated_fields) != 1:
                fields = ", ".join(SEED_AUDIO_REFERENCE_FIELDS)
                raise ValueError(f"references[{index}] must set exactly one of {fields}")

            field = populated_fields[0]
            reference = dict(raw_reference)
            reference[field] = str(reference[field]).strip()
            if field == "audio_url" and not reference[field].startswith(("http://", "https://")):
                raise ValueError(f"references[{index}].audio_url must be an HTTP(S) URL")
            normalized.append(reference)
        return normalized

    def _call_api(self, request: Dict[str, Any]) -> Dict[str, Any]:
        api_key = (
            os.getenv("VOLCENGINE_OPEN_SPEECH_API_KEY", "").strip()
            or os.getenv("VOLCENGINE_TTS_API_KEY", "").strip()
            or os.getenv("DOUBAO_TTS_API_KEY", "").strip()
            or os.getenv("SEED_TTS_API_KEY", "").strip()
            or os.getenv("DOUBAO_API_KEY", "").strip()
        )
        if not api_key:
            raise RuntimeError("DOUBAO_API_KEY is not configured")
        response = requests.post(
            SEED_AUDIO_10_ENDPOINT,
            json=request,
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": api_key,
                "X-Api-Request-Id": str(uuid.uuid4()),
            },
            timeout=int(os.getenv("VOLCENGINE_OPEN_SPEECH_TIMEOUT", "300")),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Doubao Seed Audio response must be an object")
        data = dict(data)
        provider_log_id = str((getattr(response, "headers", {}) or {}).get("X-Tt-Logid") or "").strip()
        if provider_log_id:
            data.setdefault("_request_id", provider_log_id)
        return data

    def _parse_response(self, response: Dict[str, Any], task: Any) -> GenerationResult:
        data = response.get("data") if isinstance(response.get("data"), dict) else response

        def _first_value(*keys: str) -> Any:
            for source in (data, response):
                for key in keys:
                    value = source.get(key)
                    if value is not None and value != "":
                        return value
            return None

        url = str(_first_value("audio_url", "url") or "").strip()
        audio_data = str(_first_value("audio", "audio_data", "audio_base64") or "").strip()
        request_id = str(
            _first_value("_request_id", "request_id", "requestId", "log_id") or ""
        ).strip()
        outputs: List[str] = []
        audio_format: str = ""
        if url:
            outputs.append(url)
        if audio_data:
            if audio_data.startswith("data:audio/"):
                outputs.append(audio_data)
            else:
                # 供应商响应常常不回显 format 字段，此时以真实字节头为准，
                # 再回退到显式 format 字段，最后默认 mp3，避免误判 MIME 与落盘后缀。
                explicit_format = str(
                    _first_value("format", "audio_format") or ""
                ).strip().lower()
                audio_format = (
                    self._sniff_audio_format(audio_data) or explicit_format or "mp3"
                )
                mime_type = {
                    "mp3": "audio/mpeg",
                    "wav": "audio/wav",
                    "pcm": "application/octet-stream",
                    "ogg": "audio/ogg",
                    "ogg_opus": "audio/ogg",
                    "flac": "audio/flac",
                }.get(audio_format, "audio/mpeg")
                outputs.append(f"data:{mime_type};base64,{audio_data}")

        if not outputs:
            return GenerationResult(
                success=False,
                task_id=request_id,
                model_id=self.spec.id,
                error="Doubao Seed Audio response did not contain audio_url, url, or audio_data",
                error_code="invalid_response",
                raw_response=response,
            )

        metadata: Dict[str, Any] = {}
        for key in ("duration", "original_duration"):
            value = _first_value(key)
            if value is not None:
                metadata[key] = value
        subtitle_value = _first_value("subtitles", "subtitle", "utterances")
        if isinstance(subtitle_value, str):
            try:
                subtitle_value = json.loads(subtitle_value)
            except json.JSONDecodeError:
                pass
        if subtitle_value is not None:
            metadata["subtitles"] = subtitle_value
        if request_id:
            metadata["request_id"] = request_id
        metadata["has_audio_data"] = bool(audio_data)
        if audio_format:
            metadata["format"] = audio_format

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
            result = self._parse_response(self._call_api(self._map_task_to_request(payload)), None)
        except Exception as exc:
            result = self._build_error_result(exc)
        result.latency = time.time() - started
        return result

    def _build_error_result(self, exc: Exception) -> GenerationResult:
        error_code = "provider_error"
        retryable = False
        retry_after = None
        status_code = None
        provider_code = ""
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
            headers = getattr(response, "headers", {}) or {}
            request_id = str(
                headers.get("X-Request-Id")
                or headers.get("X-Tt-Logid")
                or headers.get("X-Tt-Log-Id")
                or ""
            ).strip()
            retry_after = self._parse_retry_after(headers.get("Retry-After"))

            response_payload: Dict[str, Any] = {}
            try:
                candidate = response.json() if response is not None else {}
                if isinstance(candidate, dict):
                    response_payload = candidate
            except (TypeError, ValueError, requests.RequestException):
                response_payload = {}
            nested_error = (
                response_payload.get("error")
                if isinstance(response_payload.get("error"), dict)
                else {}
            )
            provider_code = str(
                response_payload.get("code")
                or response_payload.get("error_code")
                or nested_error.get("code")
                or ""
            ).strip()
            provider_message = str(
                response_payload.get("message")
                or response_payload.get("error_message")
                or nested_error.get("message")
                or ""
            ).strip()
            if provider_message and provider_message not in error_message:
                error_message = f"{error_message}: {provider_message}"
            if not request_id:
                request_id = str(
                    response_payload.get("request_id")
                    or response_payload.get("requestId")
                    or response_payload.get("log_id")
                    or ""
                ).strip()

            provider_text = f"{provider_code} {provider_message}".lower()
            if (
                provider_code == "40402002"
                or "ttsinvalidtext" in provider_text
                or "readabletextratio" in provider_text
            ):
                # The service may wrap prompt/reference validation in HTTP 500.
                # It is not useful to retry the same scene unchanged.
                error_code = "invalid_request"
                retryable = False
            elif status_code == 429:
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
            retry_after=retry_after,
            trace=trace,
        )

    @staticmethod
    def _sniff_audio_format(audio_data: str) -> str:
        """按 base64 音频前缀的真实字节头识别容器格式。

        供应商响应缺失 format 字段时以此为准；无法识别返回空串，交由上层回退。
        """
        try:
            header = base64.b64decode(audio_data[:32], validate=False)
        except (ValueError, TypeError):
            return ""
        if header.startswith(b"RIFF"):
            return "wav"
        if header.startswith(b"OggS"):
            return "ogg"
        if header.startswith(b"fLaC"):
            return "flac"
        if header.startswith(b"ID3"):
            return "mp3"
        if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
            return "mp3"
        return ""

    @staticmethod
    def _parse_retry_after(value: Any) -> int | None:
        try:
            parsed = int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None
        return max(0, parsed)

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id=cls.MODEL_ID,
            name=cls.MODEL_NAME,
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


@register_model(SEED_AUDIO_10_MULTILINGUAL_MODEL)
class DoubaoSeedAudio10MultilingualAdapter(DoubaoSeedAudio10Adapter):
    """Seed Audio 1.0 variant for multilingual and timeline-aware prompts."""

    MODEL_ID = SEED_AUDIO_10_MULTILINGUAL_MODEL
    MODEL_NAME = "Doubao Seed Audio 1.0 Multilingual"
