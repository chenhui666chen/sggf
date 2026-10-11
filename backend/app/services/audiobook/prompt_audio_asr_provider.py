from __future__ import annotations

import base64
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Tuple
from urllib.parse import urlparse

from app.services.audiobook.timed_subtitles import (
    normalize_timed_subtitle_payload,
)
from app.services.audiobook.prompt_audio_asr_pricing import (
    load_prompt_audio_asr_budget_policy,
)


DEFAULT_PROMPT_AUDIO_ASR_PROVIDER = "qwen_audio_asr_flash"


@dataclass
class PromptAudioAsrResult:
    provider: str
    model: str
    transcript: str
    subtitle_payload: Dict[str, Any] | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class PromptAudioAsrProvider(Protocol):
    name: str
    model: str
    supports_timestamps: bool

    def transcribe(self, audio_path: str, **kwargs: Any) -> PromptAudioAsrResult:
        ...


class PromptAudioAsrProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _new_asr_deadline(timeout_seconds: float) -> float:
    return time.monotonic() + max(0.001, float(timeout_seconds))


def _remaining_asr_timeout(deadline: float, *, cap: float | None = None) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PromptAudioAsrProviderError(
            "asr_provider_timeout",
            "ASR operation timeout budget exhausted",
        )
    return round(min(remaining, cap) if cap is not None else remaining, 6)


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
    if suffix == ".webm":
        return "audio/webm"
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


def _response_header(response: Any, name: str) -> str:
    headers = getattr(response, "headers", {})
    if not isinstance(headers, Mapping):
        return ""
    direct = headers.get(name)
    if direct is not None:
        return str(direct).strip()
    lowered_name = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered_name:
            return str(value).strip()
    return ""


def _provider_error_detail(response: Any) -> str:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = {}
    if not isinstance(payload, Mapping):
        payload = {}
    code = str(
        payload.get("code")
        or payload.get("error_code")
        or payload.get("status_code")
        or _response_header(response, "X-Api-Status-Code")
        or ""
    ).strip()
    message = str(
        payload.get("message")
        or payload.get("error_message")
        or payload.get("error")
        or _response_header(response, "X-Api-Message")
        or ""
    ).strip()[:300]
    log_id = _response_header(response, "X-Tt-Logid")[:120]
    parts = []
    if code:
        parts.append(f"code={code}")
    if message:
        parts.append(f"message={message}")
    if log_id:
        parts.append(f"log_id={log_id}")
    return " ".join(parts)


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


def normalize_asr_subtitle_payload(payload: Any) -> Dict[str, Any] | None:
    """Expose the provider-neutral timed subtitle contract to ASR callers."""
    return normalize_timed_subtitle_payload(payload)


def sanitize_asr_audit_metadata(metadata: Any) -> Dict[str, Any]:
    """只保留计费与请求追踪所需的非敏感 ASR 元数据。"""
    if not isinstance(metadata, Mapping):
        return {}
    sanitized: Dict[str, Any] = {}
    for field_name in ("request_id", "task_id", "response_id"):
        value = str(metadata.get(field_name) or "").strip()
        if value:
            sanitized[field_name] = value
    usage = metadata.get("usage")
    if isinstance(usage, Mapping):
        sanitized["usage"] = dict(usage)
    return sanitized


class MiMoPromptAudioAsrProvider:
    name = "mimo"
    supports_timestamps = False

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
            subtitle_payload=normalize_asr_subtitle_payload(data),
            metadata={
                "response_id": data.get("id"),
                "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
            },
        )


def _aliyun_transcription_url(payload: Mapping[str, Any]) -> str:
    results = payload.get("results")
    if not isinstance(results, list):
        return ""
    for item in results:
        if not isinstance(item, Mapping):
            continue
        status_value = str(item.get("subtask_status") or "").strip().upper()
        if status_value and status_value not in {"SUCCEEDED", "SUCCESS"}:
            continue
        transcription_url = str(item.get("transcription_url") or "").strip()
        if transcription_url.startswith(("http://", "https://")):
            return transcription_url
    return ""


def _aliyun_transcript_text(payload: Mapping[str, Any]) -> str:
    transcripts = payload.get("transcripts")
    if not isinstance(transcripts, list):
        return ""
    return " ".join(
        str(item.get("text") or "").strip()
        for item in transcripts
        if isinstance(item, Mapping) and str(item.get("text") or "").strip()
    ).strip()


def _aliyun_usage(payload: Mapping[str, Any]) -> Dict[str, Any]:
    properties = payload.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    raw_duration_ms = properties.get("original_duration_in_milliseconds")
    try:
        duration_s = float(raw_duration_ms) / 1000.0
    except (TypeError, ValueError):
        return {}
    return {"duration": duration_s} if duration_s > 0 else {}


class AliyunPromptAudioAsrProvider:
    name = "aliyun"
    supports_timestamps = True

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
        deadline = _new_asr_deadline(self.timeout_seconds)
        task = Transcription.async_call(model=self.model, file_urls=[audio_url])
        task_id = getattr(task.output, "task_id", None) if getattr(task, "output", None) else None
        if not task_id:
            raise PromptAudioAsrProviderError("asr_provider_invalid_response", "阿里云 ASR 未返回 task_id")

        while True:
            _remaining_asr_timeout(deadline)
            result = Transcription.fetch(task=task_id)
            status = getattr(getattr(result, "output", None), "task_status", "")
            if status in {"SUCCEEDED", "SUCCESS"}:
                data = result.output if isinstance(result.output, dict) else json.loads(json.dumps(result.output, default=str))
                transcription_data = data
                transcription_url = _aliyun_transcription_url(data)
                if transcription_url:
                    import httpx

                    response = httpx.get(
                        transcription_url,
                        timeout=_remaining_asr_timeout(deadline, cap=30.0),
                        follow_redirects=True,
                    )
                    if response.status_code >= 400:
                        raise PromptAudioAsrProviderError(
                            "asr_provider_request_failed",
                            f"阿里云 ASR 结果下载失败: status={response.status_code}",
                        )
                    transcription_data = _safe_json(response)
                transcript = _aliyun_transcript_text(transcription_data)
                if not transcript:
                    transcript = _first_text(transcription_data)
                if not transcript:
                    raise PromptAudioAsrProviderError("asr_empty_transcript", "阿里云 ASR 未返回转写文本")
                usage = _aliyun_usage(transcription_data)
                return PromptAudioAsrResult(
                    provider=self.name,
                    model=self.model,
                    transcript=transcript,
                    subtitle_payload=normalize_asr_subtitle_payload(
                        transcription_data.get("transcripts")
                        if isinstance(transcription_data.get("transcripts"), list)
                        else transcription_data
                    ),
                    metadata={
                        "task_id": task_id,
                        **({"usage": usage} if usage else {}),
                    },
                )
            if status in {"FAILED", "CANCELED"}:
                raise PromptAudioAsrProviderError("asr_provider_request_failed", f"阿里云 ASR 任务失败: {status}")
            time.sleep(min(2.0, _remaining_asr_timeout(deadline)))


_DOUBAO_ASR_SUCCESS_CODE = "20000000"
_DOUBAO_ASR_PENDING_CODES = frozenset({"20000001", "20000002"})
_DOUBAO_ASR_FORMATS = frozenset({"raw", "wav", "mp3", "ogg"})


def _doubao_asr_audio_format(audio_path: str, audio_url: str) -> str:
    candidates = (urlparse(audio_url).path, audio_path)
    for candidate in candidates:
        suffix = Path(candidate).suffix.lower().lstrip(".")
        if suffix in _DOUBAO_ASR_FORMATS:
            return suffix
    raise PromptAudioAsrProviderError(
        "asr_audio_format_unsupported",
        "豆包录音文件识别仅支持 raw、wav、mp3 或 ogg 音频",
    )


def _doubao_asr_usage(payload: Mapping[str, Any]) -> Dict[str, Any]:
    audio_info = payload.get("audio_info")
    if not isinstance(audio_info, Mapping):
        return {}
    try:
        duration_s = float(audio_info.get("duration")) / 1000.0
    except (TypeError, ValueError):
        return {}
    return {"duration": duration_s} if duration_s > 0 else {}


class DoubaoPromptAudioAsrProvider:
    name = "doubao"
    supports_timestamps = True

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        app_key: Optional[str] = None,
        access_key: Optional[str] = None,
        resource_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout_seconds: float = 300.0,
    ):
        self.api_key = api_key or _env_value(
            "VOLCENGINE_ASR_API_KEY",
            "DOUBAO_ASR_API_KEY",
            "VOLCENGINE_OPEN_SPEECH_API_KEY",
            "VOLCENGINE_SPEECH_API_KEY",
            "DOUBAO_SPEECH_API_KEY",
        )
        self.app_key = app_key or _env_value("VOLCENGINE_ASR_APP_KEY", "DOUBAO_ASR_APP_KEY")
        self.access_key = access_key or _env_value(
            "VOLCENGINE_ASR_ACCESS_KEY",
            "DOUBAO_ASR_ACCESS_KEY",
        )
        self.resource_id = (
            resource_id
            or os.getenv("VOLCENGINE_ASR_RESOURCE_ID")
            or os.getenv("DOUBAO_ASR_RESOURCE_ID")
            or "volc.bigasr.auc"
        )
        self.endpoint = (
            endpoint
            or os.getenv("VOLCENGINE_ASR_ENDPOINT")
            or "https://openspeech.bytedance.com/api/v3/auc/bigmodel"
        ).rstrip("/")
        self.model = self.resource_id
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key or (self.app_key and self.access_key))

    def _request_headers(self, request_id: str, *, submit: bool) -> Dict[str, str]:
        headers = {
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        else:
            assert self.app_key and self.access_key
            headers["X-Api-App-Key"] = self.app_key
            headers["X-Api-Access-Key"] = self.access_key
        if submit:
            headers["X-Api-Sequence"] = "-1"
        return headers

    def transcribe(self, audio_path: str, **kwargs: Any) -> PromptAudioAsrResult:
        audio_url = str(kwargs.get("audio_url") or "").strip()
        if not audio_url:
            raise PromptAudioAsrProviderError(
                "asr_audio_url_required",
                "豆包录音文件识别需要公网可访问 audio_url，当前章节音频是本地文件",
            )
        if not self.configured:
            raise PromptAudioAsrProviderError(
                "asr_provider_not_configured",
                "未配置豆包 ASR 新版 API Key，或旧版 App Key + Access Key",
            )

        import httpx

        request_id = str(uuid.uuid4())
        audio_format = _doubao_asr_audio_format(audio_path, audio_url)
        submit_headers = self._request_headers(request_id, submit=True)
        query_headers = self._request_headers(request_id, submit=False)

        deadline = _new_asr_deadline(self.timeout_seconds)
        with httpx.Client(timeout=_remaining_asr_timeout(deadline, cap=30.0)) as client:
            submit_response = client.post(
                f"{self.endpoint}/submit",
                headers=submit_headers,
                json={
                    "audio": {
                        "format": audio_format,
                        "url": audio_url,
                    },
                    "request": {
                        "model_name": "bigmodel",
                        "enable_itn": True,
                        "enable_punc": True,
                        "show_utterances": True,
                    },
                },
                timeout=_remaining_asr_timeout(deadline, cap=30.0),
            )
            if submit_response.status_code >= 400:
                detail = _provider_error_detail(submit_response)
                raise PromptAudioAsrProviderError(
                    "asr_provider_request_failed",
                    f"豆包 ASR 提交失败: status={submit_response.status_code}"
                    f"{f' {detail}' if detail else ''}",
                )
            submit_status = _response_header(submit_response, "X-Api-Status-Code")
            if submit_status != _DOUBAO_ASR_SUCCESS_CODE:
                detail = _provider_error_detail(submit_response)
                raise PromptAudioAsrProviderError(
                    "asr_provider_request_failed",
                    "豆包 ASR 提交失败"
                    f"{f': {detail}' if detail else ': 缺少成功状态码'}",
                )

            while True:
                query_response = client.post(
                    f"{self.endpoint}/query",
                    headers=query_headers,
                    json={},
                    timeout=_remaining_asr_timeout(deadline, cap=30.0),
                )
                if query_response.status_code >= 400:
                    detail = _provider_error_detail(query_response)
                    raise PromptAudioAsrProviderError(
                        "asr_provider_request_failed",
                        f"豆包 ASR 查询失败: status={query_response.status_code}"
                        f"{f' {detail}' if detail else ''}",
                    )
                status_code = _response_header(query_response, "X-Api-Status-Code")
                if status_code == _DOUBAO_ASR_SUCCESS_CODE:
                    query_data = _safe_json(query_response)
                    transcript = _first_text(query_data.get("result"))
                    if not transcript:
                        raise PromptAudioAsrProviderError("asr_empty_transcript", "豆包 ASR 未返回转写文本")
                    usage = _doubao_asr_usage(query_data)
                    return PromptAudioAsrResult(
                        provider=self.name,
                        model=self.model,
                        transcript=transcript,
                        subtitle_payload=normalize_asr_subtitle_payload(query_data),
                        metadata={
                            "request_id": request_id,
                            **({"usage": usage} if usage else {}),
                        },
                    )
                if status_code not in _DOUBAO_ASR_PENDING_CODES:
                    detail = _provider_error_detail(query_response)
                    raise PromptAudioAsrProviderError(
                        "asr_provider_request_failed",
                        "豆包 ASR 查询失败"
                        f"{f': {detail}' if detail else ': 缺少任务状态码'}",
                    )
                time.sleep(min(2.0, _remaining_asr_timeout(deadline)))


_ASR_FLASH_SEGMENT_PUNCTUATION = frozenset(
    {"。", "！", "？", "；", "，", "、", ".", "!", "?", ";", ","}
)


def _detect_wav_sample_rate(path: str) -> Optional[int]:
    if Path(path).suffix.lower() != ".wav":
        return None
    try:
        import wave

        with wave.open(path, "rb") as handle:
            return handle.getframerate()
    except Exception:  # noqa: BLE001
        return None


def _asr_flash_sentence_from_event(event: Any) -> Optional[Dict[str, Any]]:
    """Extract the sentence object from an ASR-Flash result event.

    Qwen-Audio-3.x-ASR-Flash 走 DashScope multimodal-generation 端点，
    但结果嵌套形态非标准：结果可能在 ``output.output.sentence``，
    也可能在 ``output.sentence``，这里优先取内层再回退外层。
    """
    if not isinstance(event, dict):
        return None
    output = event.get("output")
    if not isinstance(output, dict):
        return None
    inner = output.get("output") if isinstance(output.get("output"), dict) else output
    sentence = inner.get("sentence")
    if not isinstance(sentence, dict):
        sentence = output.get("sentence")
    return sentence if isinstance(sentence, dict) else None


def _asr_flash_event_usage(event: Dict[str, Any]) -> Dict[str, Any]:
    """从事件里取 usage：ASR-Flash 把它放在事件层，部分形态放在 output 层。"""
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    inner = output.get("output") if isinstance(output.get("output"), dict) else output
    for source in (event, inner):
        usage = source.get("usage") if isinstance(source, dict) else None
        if isinstance(usage, dict) and usage:
            return usage
    return {}


def _asr_flash_request_id(event: Dict[str, Any]) -> str:
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    inner = output.get("output") if isinstance(output.get("output"), dict) else output
    return str(event.get("request_id") or inner.get("request_id") or "").strip()


def _asr_flash_collect_sentences(
    lines: Iterable[Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Parse ASR-Flash SSE 行，累积所有已完成（sentence_end）的句子。"""
    sentences: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {}
    for raw in lines:
        payload = _asr_flash_event_from_line(raw)
        if payload is None:
            continue
        request_id = _asr_flash_request_id(payload)
        if request_id:
            meta["request_id"] = request_id
        usage = _asr_flash_event_usage(payload)
        if usage:
            meta["usage"] = usage
        sentence = _asr_flash_sentence_from_event(payload)
        if sentence and sentence.get("sentence_end"):
            sentences.append(sentence)
    return sentences, meta


def _asr_flash_event_from_line(raw: Any) -> Optional[Dict[str, Any]]:
    """解析一行响应：只接受 ``data:`` 帧里的 JSON，SSE 的 id/event/注释行直接跳过。"""
    line = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw or "")
    line = line.strip()
    if not line.startswith("data:"):
        return None
    body = line[len("data:"):].strip()
    if not body:
        return None
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def _asr_flash_payload_from_lines(lines: Iterable[Any]) -> Optional[Dict[str, Any]]:
    """把响应行还原成单个结果对象：SSE 取最后一条 ``data``，非流式取整个响应体。"""
    payload_text: List[str] = []
    last_event: Optional[Dict[str, Any]] = None
    for raw in lines:
        event = _asr_flash_event_from_line(raw)
        if event is not None:
            last_event = event
            continue
        line = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw or "")
        if line.strip():
            payload_text.append(line.strip())
    if last_event is not None:
        return last_event
    if not payload_text:
        return None
    try:
        payload = json.loads("\n".join(payload_text))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _asr_flash_result_from_payload(
    payload: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """非 SSE 形态兜底：短音频一次性返回时按行解析拿不到句子。

    官方契约里 SSE 中间结果只在音频不少于 1 分钟时才分多次返回，短音频可能
    直接以单条 JSON 响应体返回。此时优先取 ``output.sentence``（带词级时间戳），
    退化到 ``output.text``（只有累积文本，字幕时间轴降级为空，转写仍可用于保真比对）。
    """
    meta: Dict[str, Any] = {}
    request_id = _asr_flash_request_id(payload)
    if request_id:
        meta["request_id"] = request_id
    usage = _asr_flash_event_usage(payload)
    if usage:
        meta["usage"] = usage

    sentence = _asr_flash_sentence_from_event(payload)
    if sentence and str(sentence.get("text") or "").strip():
        return [sentence], meta

    output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
    inner = output.get("output") if isinstance(output.get("output"), dict) else output
    accumulated = str(inner.get("text") or output.get("text") or payload.get("text") or "").strip()
    if accumulated:
        return [{"text": accumulated, "sentence_end": True}], meta
    return [], meta


def _asr_flash_segment_from_words(words: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    text = "".join(
        f"{str(word.get('text') or '')}{str(word.get('punctuation') or '')}"
        for word in words
    ).strip()
    begin = words[0].get("begin_time") if words else None
    end = words[-1].get("end_time") if words else None
    if not text or begin is None or end is None:
        return None
    return {"text": text, "begin_time": begin, "end_time": end}


def _asr_flash_subtitle_payload(
    sentences: List[Dict[str, Any]],
    split_punctuation: Iterable[str] = _ASR_FLASH_SEGMENT_PUNCTUATION,
) -> Dict[str, Any]:
    """把逐字时间戳按标点重切成分段，产出 normalize 可识别的 sentences 列表。"""
    punctuation = frozenset(split_punctuation)
    segments: List[Dict[str, Any]] = []
    for sentence in sentences:
        words = sentence.get("words")
        if isinstance(words, list) and words:
            current: List[Dict[str, Any]] = []
            for word in words:
                if not isinstance(word, dict):
                    continue
                current.append(word)
                if str(word.get("punctuation") or "") in punctuation:
                    segment = _asr_flash_segment_from_words(current)
                    if segment:
                        segments.append(segment)
                    current = []
            if current:
                segment = _asr_flash_segment_from_words(current)
                if segment:
                    segments.append(segment)
        else:
            text = str(sentence.get("text") or "").strip()
            begin = sentence.get("begin_time")
            end = sentence.get("end_time")
            if text and begin is not None and end is not None:
                segments.append({"text": text, "begin_time": begin, "end_time": end})
    return {"sentences": segments}


class QwenAudioAsrFlashPromptAudioAsrProvider:
    """Qwen-Audio-3.1-ASR-Flash：逐字转写 + 词级时间戳，支持本地音频 Base64 直传。

    请求走 DashScope multimodal-generation 端点，响应形态为 ASR-Flash 系列的非标准嵌套；
    计价按输入/输出 Token 走（usage 里除 ``duration`` 外还返回 ``input_tokens`` /
    ``output_tokens`` / ``total_tokens``），因此成本闸门用派生等效秒价（见
    prompt_audio_asr_pricing）。`keep_dialect` 官方默认 false，即方言按普通话转写，
    正是逐字保真比对需要的形态，故不显式下发该参数。
    """

    name = "qwen_audio_asr_flash"
    supports_timestamps = True

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 180.0,
    ):
        self.api_key = api_key or _env_value(
            "DASHSCOPE_ASR_API_KEY", "DASHSCOPE_API_KEY", "ALIYUN_API_KEY"
        )
        base = (
            base_url
            or os.getenv("DASHSCOPE_ASR_BASE_URL")
            or "https://dashscope.aliyuncs.com"
        ).rstrip("/")
        self.base_url = base
        self.endpoint = f"{base}/api/v1/services/aigc/multimodal-generation/generation"
        self.model = (
            model or os.getenv("QWEN_AUDIO_ASR_MODEL") or "qwen-audio-3.1-asr-flash"
        )
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def transcribe(self, audio_path: str, **kwargs: Any) -> PromptAudioAsrResult:
        if not self.configured:
            raise PromptAudioAsrProviderError(
                "asr_provider_not_configured",
                "未配置 DASHSCOPE_ASR_API_KEY 或 DASHSCOPE_API_KEY",
            )

        import httpx

        audio_bytes = Path(audio_path).read_bytes()
        audio_data = base64.b64encode(audio_bytes).decode("ascii")
        mime_type = _infer_audio_mime_type(audio_path)
        fmt = Path(audio_path).suffix.lower().lstrip(".") or "wav"
        parameters: Dict[str, Any] = {"format": fmt}
        sample_rate = kwargs.get("sample_rate") or _detect_wav_sample_rate(audio_path)
        if sample_rate:
            parameters["sample_rate"] = str(sample_rate)

        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": f"data:{mime_type};base64,{audio_data}",
                                },
                            }
                        ],
                    }
                ]
            },
            "parameters": parameters,
        }

        with httpx.stream(
            "POST",
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-DashScope-SSE": "enable",
                "Accept": "text/event-stream",
            },
            json=payload,
            timeout=self.timeout_seconds,
        ) as response:
            if response.status_code >= 400:
                response.read()
                raise PromptAudioAsrProviderError(
                    "asr_provider_request_failed",
                    f"qwen-audio ASR 请求失败: status={response.status_code}",
                )
            lines = list(response.iter_lines())

        sentences, meta = _asr_flash_collect_sentences(lines)
        if not sentences:
            # SSE 帧里没有已完成的句子时，按一次性 JSON 响应形态再解析一次
            flash_payload = _asr_flash_payload_from_lines(lines)
            if flash_payload is not None:
                fallback_sentences, fallback_meta = _asr_flash_result_from_payload(
                    flash_payload
                )
                sentences = fallback_sentences
                for key in ("request_id", "usage"):
                    if key not in meta and key in fallback_meta:
                        meta[key] = fallback_meta[key]

        transcript = "".join(str(item.get("text") or "") for item in sentences).strip()
        if not transcript:
            raise PromptAudioAsrProviderError(
                "asr_empty_transcript", "qwen-audio ASR 未返回转写文本"
            )

        subtitle_payload = normalize_asr_subtitle_payload(
            _asr_flash_subtitle_payload(sentences)
        )
        metadata: Dict[str, Any] = {"sentence_count": len(sentences)}
        if meta.get("request_id"):
            metadata["request_id"] = meta["request_id"]
        if isinstance(meta.get("usage"), dict):
            metadata["usage"] = meta["usage"]
        return PromptAudioAsrResult(
            provider=self.name,
            model=self.model,
            transcript=transcript,
            subtitle_payload=subtitle_payload,
            metadata=metadata,
        )


_QWEN_OMNI_DIRECTION_INSTRUCTION = (
    "这是一段针对有声书片段朗读的口述要求录音。请完成两部分输出："
    "第一部分逐字转写录音中说出的内容；"
    "第二部分若录音包含朗读示范，只用简洁中文描述其语速、语势、强弱、情绪、"
    "重音、停顿、断句、呼吸与句尾处理；若仅为口述要求则总结其中提到的表演要求。"
    "不得推断或描述性别、年龄感、基础声线或音色身份；不得输出童声、老人声、男声、"
    "女声、变声、换声、模仿对象或永久音色质感。生病、受伤等特殊状态下的沙哑只能"
    "描述为在原音色基础上的轻微短暂状态。直接输出结果，不要附加解释。"
)


class QwenOmniPromptAudioAsrProvider:
    """用 qwen3.5-omni 音频理解能力转写口述要求并描述朗读示范的表演特征。"""

    name = "qwen_omni"
    supports_timestamps = False

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 180.0,
    ):
        self.api_key = api_key or _env_value(
            "QWEN_OMNI_DIRECTION_API_KEY",
            "DASHSCOPE_ASR_API_KEY",
            "DASHSCOPE_API_KEY",
            "ALIYUN_API_KEY",
        )
        base = (
            base_url
            or os.getenv("QWEN_OMNI_DIRECTION_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/")
        self.base_url = base
        self.endpoint = f"{base}/chat/completions"
        self.model = model or os.getenv("QWEN_OMNI_DIRECTION_MODEL") or "qwen3.5-omni-flash"
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def transcribe(self, audio_path: str, instruction: Optional[str] = None, **kwargs: Any) -> PromptAudioAsrResult:
        if not self.configured:
            raise PromptAudioAsrProviderError(
                "asr_provider_not_configured",
                "未配置 QWEN_OMNI_DIRECTION_API_KEY 或 DASHSCOPE_API_KEY",
            )

        import httpx

        audio_bytes = Path(audio_path).read_bytes()
        audio_data = base64.b64encode(audio_bytes).decode("ascii")
        mime_type = _infer_audio_mime_type(audio_path)
        fmt = Path(audio_path).suffix.lower().lstrip(".") or "mp3"
        payload = {
            "model": self.model,
            "modalities": ["text"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:{mime_type};base64,{audio_data}",
                                "format": fmt,
                            },
                        },
                        {"type": "text", "text": str(instruction) if instruction else _QWEN_OMNI_DIRECTION_INSTRUCTION},
                    ],
                }
            ],
        }
        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            detail = _provider_error_detail(response)
            raise PromptAudioAsrProviderError(
                "asr_provider_request_failed",
                f"qwen-omni 音频理解请求失败: status={response.status_code}"
                f"{f' {detail}' if detail else ''}",
            )

        data = _safe_json(response)
        transcript = _first_text(data.get("choices"))
        if not transcript:
            transcript = _first_text(data)
        if not transcript:
            raise PromptAudioAsrProviderError("asr_empty_transcript", "qwen-omni 未返回转写文本")

        metadata: Dict[str, Any] = {"analysis_mode": "audio_understanding"}
        response_id = data.get("id")
        if response_id:
            metadata["response_id"] = response_id
        usage = data.get("usage")
        if isinstance(usage, dict):
            metadata["usage"] = usage
        return PromptAudioAsrResult(
            provider=self.name,
            model=self.model,
            transcript=transcript,
            subtitle_payload=None,
            metadata=metadata,
        )


def create_prompt_audio_asr_provider(provider: Optional[str] = None) -> Optional[PromptAudioAsrProvider]:
    normalized = str(provider or os.getenv("PROMPT_AUDIO_ASR_PROVIDER") or DEFAULT_PROMPT_AUDIO_ASR_PROVIDER).strip().lower()
    timeout_seconds = load_prompt_audio_asr_budget_policy().timeout_seconds
    if not normalized:
        return None
    if normalized in {"mimo", "xiaomi", "小米"}:
        service = MiMoPromptAudioAsrProvider(timeout_seconds=timeout_seconds)
    elif normalized in {"aliyun", "dashscope", "ali", "阿里"}:
        service = AliyunPromptAudioAsrProvider(timeout_seconds=timeout_seconds)
    elif normalized in {"doubao", "volcengine", "volc", "豆包", "火山"}:
        service = DoubaoPromptAudioAsrProvider(timeout_seconds=timeout_seconds)
    elif normalized in {
        "qwen_audio_asr_flash",
        "qwen-audio-asr-flash",
        "qwen_audio_asr",
        "qwen-audio-asr",
        "qwen-audio-3.1-asr-flash",
        "qwen-audio-3.1-asr",
    }:
        service = QwenAudioAsrFlashPromptAudioAsrProvider(timeout_seconds=timeout_seconds)
    elif normalized in {"qwen_omni", "qwen-omni", "qwenomni", "qwen3.5-omni", "qwen3.5-omni-flash", "omni"}:
        service = QwenOmniPromptAudioAsrProvider(timeout_seconds=timeout_seconds)
    else:
        raise PromptAudioAsrProviderError("asr_provider_unsupported", f"不支持的 ASR provider: {normalized}")
    if not getattr(service, "configured", False):
        return None
    return service
