from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Protocol


DEFAULT_PROMPT_AUDIO_ASR_PROVIDER = "mimo"


@dataclass
class PromptAudioAsrResult:
    provider: str
    model: str
    transcript: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class PromptAudioAsrProvider(Protocol):
    name: str
    model: str

    def transcribe(self, audio_path: str, **kwargs: Any) -> PromptAudioAsrResult:
        ...


class PromptAudioAsrProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _env_value(*names: str) -> str:
    for name in names:
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def _infer_audio_mime_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix == ".flac":
        return "audio/flac"
    if suffix == ".ogg":
        return "audio/ogg"
    return "audio/mpeg"


def _safe_json(response: Any) -> Dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise PromptAudioAsrProviderError(
            "asr_provider_invalid_response",
            "ASR provider 返回了非 JSON 响应",
        ) from exc
    if not isinstance(payload, dict):
        raise PromptAudioAsrProviderError(
            "asr_provider_invalid_response",
            "ASR provider 返回结构不是对象",
        )
    return payload


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in (
            "text",
            "transcript",
            "recognized_text",
            "result",
            "content",
        ):
            text = _first_text(value.get(key))
            if text:
                return text
        message = value.get("message")
        if isinstance(message, dict):
            text = _first_text(message)
            if text:
                return text
        output = value.get("output")
        if isinstance(output, dict):
            text = _first_text(output)
            if text:
                return text
    if isinstance(value, list):
        parts = [_first_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    return ""


class MiMoPromptAudioAsrProvider:
    name = "mimo"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 120.0,
    ):
        self.api_key = api_key or _env_value("MIMO_ASR_API_KEY", "MIMO_API_KEY")
        self.base_url = (base_url or os.getenv("MIMO_ASR_BASE_URL") or "https://api.xiaomimimo.com/v1").rstrip("/")
        self.model = model or os.getenv("MIMO_ASR_MODEL") or "mimo-v2.5-asr"
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def transcribe(self, audio_path: str, **kwargs: Any) -> PromptAudioAsrResult:
        if not self.configured:
            raise PromptAudioAsrProviderError("asr_provider_not_configured", "未配置 MIMO_ASR_API_KEY 或 MIMO_API_KEY")

        import httpx

        audio_bytes = Path(audio_path).read_bytes()
        audio_data = base64.b64encode(audio_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_data,
                                "format": Path(audio_path).suffix.lower().lstrip(".") or "mp3",
                                "mime_type": _infer_audio_mime_type(audio_path),
                            },
                        },
                    ],
                }
            ],
        }
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise PromptAudioAsrProviderError(
                "asr_provider_request_failed",
                f"MiMo ASR 请求失败: status={response.status_code}",
            )

        data = _safe_json(response)
        transcript = _first_text(data.get("choices"))
        if not transcript:
            transcript = _first_text(data)
        if not transcript:
            raise PromptAudioAsrProviderError("asr_empty_transcript", "MiMo ASR 未返回转写文本")

        return PromptAudioAsrResult(
            provider=self.name,
            model=self.model,
            transcript=transcript,
            metadata={
                "response_id": data.get("id"),
                "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
            },
        )


class AliyunPromptAudioAsrProvider:
    name = "aliyun"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 300.0,
    ):
        self.api_key = api_key or _env_value("DASHSCOPE_ASR_API_KEY", "DASHSCOPE_API_KEY", "ALIYUN_API_KEY")
        self.model = model or os.getenv("DASHSCOPE_ASR_MODEL") or "paraformer-v2"
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def transcribe(self, audio_path: str, **kwargs: Any) -> PromptAudioAsrResult:
        audio_url = str(kwargs.get("audio_url") or "").strip()
        if not audio_url:
            raise PromptAudioAsrProviderError(
                "asr_audio_url_required",
                "阿里云录音文件识别需要公网可访问 audio_url，当前章节音频是本地文件",
            )
        if not self.configured:
            raise PromptAudioAsrProviderError("asr_provider_not_configured", "未配置 DASHSCOPE_ASR_API_KEY 或 DASHSCOPE_API_KEY")

        import dashscope
        from dashscope.audio.asr import Transcription

        dashscope.api_key = self.api_key
        task = Transcription.async_call(model=self.model, file_urls=[audio_url])
        task_id = getattr(task.output, "task_id", None) if getattr(task, "output", None) else None
        if not task_id:
            raise PromptAudioAsrProviderError("asr_provider_invalid_response", "阿里云 ASR 未返回 task_id")

        deadline = time.time() + float(self.timeout_seconds)
        while time.time() < deadline:
            result = Transcription.fetch(task=task_id)
            status = getattr(getattr(result, "output", None), "task_status", "")
            if status in {"SUCCEEDED", "SUCCESS"}:
                data = result.output if isinstance(result.output, dict) else json.loads(json.dumps(result.output, default=str))
                transcript = _first_text(data)
                if not transcript:
                    raise PromptAudioAsrProviderError("asr_empty_transcript", "阿里云 ASR 未返回转写文本")
                return PromptAudioAsrResult(
                    provider=self.name,
                    model=self.model,
                    transcript=transcript,
                    metadata={"task_id": task_id, "raw_output": data},
                )
            if status in {"FAILED", "CANCELED"}:
                raise PromptAudioAsrProviderError("asr_provider_request_failed", f"阿里云 ASR 任务失败: {status}")
            time.sleep(2.0)

        raise PromptAudioAsrProviderError("asr_provider_timeout", "阿里云 ASR 查询超时")


class DoubaoPromptAudioAsrProvider:
    name = "doubao"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        app_key: Optional[str] = None,
        resource_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout_seconds: float = 300.0,
    ):
        self.api_key = api_key or _env_value("VOLCENGINE_ASR_API_KEY", "DOUBAO_ASR_API_KEY", "VOLCENGINE_SPEECH_API_KEY", "DOUBAO_SPEECH_API_KEY")
        self.app_key = app_key or _env_value("VOLCENGINE_ASR_APP_KEY", "DOUBAO_ASR_APP_KEY")
        self.resource_id = resource_id or os.getenv("VOLCENGINE_ASR_RESOURCE_ID") or os.getenv("DOUBAO_ASR_RESOURCE_ID") or "volc.bigasr.auc"
        self.endpoint = (endpoint or os.getenv("VOLCENGINE_ASR_ENDPOINT") or "https://openspeech.bytedance.com/api/v3/auc/bigmodel").rstrip("/")
        self.model = self.resource_id
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def transcribe(self, audio_path: str, **kwargs: Any) -> PromptAudioAsrResult:
        audio_url = str(kwargs.get("audio_url") or "").strip()
        if not audio_url:
            raise PromptAudioAsrProviderError(
                "asr_audio_url_required",
                "豆包录音文件识别需要公网可访问 audio_url，当前章节音频是本地文件",
            )
        if not self.configured:
            raise PromptAudioAsrProviderError("asr_provider_not_configured", "未配置 VOLCENGINE_ASR_API_KEY 或 DOUBAO_ASR_API_KEY")

        import httpx

        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "Content-Type": "application/json",
        }
        if self.app_key:
            headers["X-Api-App-Key"] = self.app_key

        with httpx.Client(timeout=30.0) as client:
            submit_response = client.post(
                f"{self.endpoint}/submit",
                headers=headers,
                json={"url": audio_url},
            )
            if submit_response.status_code >= 400:
                raise PromptAudioAsrProviderError(
                    "asr_provider_request_failed",
                    f"豆包 ASR 提交失败: status={submit_response.status_code}",
                )
            submit_data = _safe_json(submit_response)
            task_id = str(
                submit_data.get("task_id")
                or submit_data.get("id")
                or submit_data.get("result", {}).get("task_id")
                or ""
            ).strip()
            if not task_id:
                raise PromptAudioAsrProviderError("asr_provider_invalid_response", "豆包 ASR 未返回 task_id")

            deadline = time.time() + float(self.timeout_seconds)
            while time.time() < deadline:
                query_response = client.post(
                    f"{self.endpoint}/query",
                    headers=headers,
                    json={"task_id": task_id},
                )
                if query_response.status_code >= 400:
                    raise PromptAudioAsrProviderError(
                        "asr_provider_request_failed",
                        f"豆包 ASR 查询失败: status={query_response.status_code}",
                    )
                query_data = _safe_json(query_response)
                status_value = str(
                    query_data.get("status")
                    or query_data.get("task_status")
                    or query_data.get("result", {}).get("status")
                    or ""
                ).lower()
                if status_value in {"success", "succeeded", "done", "completed"}:
                    transcript = _first_text(query_data)
                    if not transcript:
                        raise PromptAudioAsrProviderError("asr_empty_transcript", "豆包 ASR 未返回转写文本")
                    return PromptAudioAsrResult(
                        provider=self.name,
                        model=self.model,
                        transcript=transcript,
                        metadata={"task_id": task_id, "raw_output": query_data},
                    )
                if status_value in {"failed", "error", "canceled", "cancelled"}:
                    raise PromptAudioAsrProviderError("asr_provider_request_failed", f"豆包 ASR 任务失败: {status_value}")
                time.sleep(2.0)

        raise PromptAudioAsrProviderError("asr_provider_timeout", "豆包 ASR 查询超时")


def create_prompt_audio_asr_provider(provider: Optional[str] = None) -> Optional[PromptAudioAsrProvider]:
    normalized = str(provider or os.getenv("PROMPT_AUDIO_ASR_PROVIDER") or DEFAULT_PROMPT_AUDIO_ASR_PROVIDER).strip().lower()
    if not normalized:
        return None
    if normalized in {"mimo", "xiaomi", "小米"}:
        service = MiMoPromptAudioAsrProvider()
    elif normalized in {"aliyun", "dashscope", "ali", "阿里"}:
        service = AliyunPromptAudioAsrProvider()
    elif normalized in {"doubao", "volcengine", "volc", "豆包", "火山"}:
        service = DoubaoPromptAudioAsrProvider()
    else:
        raise PromptAudioAsrProviderError("asr_provider_unsupported", f"不支持的 ASR provider: {normalized}")
    if not getattr(service, "configured", False):
        return None
    return service
