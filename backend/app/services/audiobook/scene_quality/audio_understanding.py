"""通用音频理解传输层：把本地音频连同提问发给候选模型，只返回原始文本与用量。

不含任何解析与业务判断，供离线评分（omni_audio_scorer）与音色画像打标
（voice_profile_tagging）共用同一条运输链路，避免两份供应商调用代码漂移。
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import httpx

from .audio_score_contract import SCORER_MODELS

_QWEN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
_DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
# 豆包分支一律发这个线名：往 SCORER_MODELS 加第二档豆包（如 doubao-seed-2-1-pro）时必须先改成
# 逐档映射，否则请求仍打到 lite，而台账按新档记——评分结果与上游模型不一致不会有任何报错。
_DOUBAO_MODEL = "doubao-seed-2-1-lite-260915"
_MIME = {"wav": "audio/wav", "mp3": "audio/mpeg"}
_MAX_AUDIO_BYTES = 7_000_000


@dataclass(frozen=True)
class AudioUnderstandingResult:
    model: str
    status: str
    raw: str = ""
    usage: Mapping[str, Any] | None = None
    error_kind: str | None = None
    http_status: int | None = None


def understand_audio(
    *,
    audio_path: str | Path,
    prompt: str,
    model: str,
    api_key: str,
    max_tokens: int = 1024,
    client: httpx.Client | None = None,
) -> AudioUnderstandingResult:
    """发送一次请求，不重试，不输出音频、凭证或供应商原文。"""
    if model not in SCORER_MODELS:
        raise ValueError("unknown understanding model")
    if not prompt.strip() or not api_key.strip():
        raise ValueError("prompt and api_key are required")
    path = Path(audio_path)
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in _MIME:
        raise ValueError("unsupported audio format")
    audio = path.read_bytes()
    if not audio or len(audio) > _MAX_AUDIO_BYTES:
        raise ValueError("audio must be nonempty and under 7 MB")

    encoded = base64.b64encode(audio).decode("ascii")
    qwen = not model.startswith("doubao")
    content = [
        {"type": "text", "text": prompt},
        {"type": "input_audio", "input_audio": {
            "data": f"data:{_MIME[fmt]};base64,{encoded}" if qwen else encoded,
            "format": fmt,
        }},
    ]
    payload: dict[str, Any] = {
        "model": model if qwen else _DOUBAO_MODEL,
        "messages": [{"role": "user", "content": content}],
    }
    if qwen:
        payload.update(modalities=["text"], stream=True, stream_options={"include_usage": True})
    else:
        payload.update(thinking={"type": "disabled"}, max_tokens=max_tokens)

    def request(session: httpx.Client) -> AudioUnderstandingResult:
        try:
            with session.stream(
                "POST", _QWEN_URL if qwen else _DOUBAO_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    return AudioUnderstandingResult(
                        model, "recorded_error", error_kind="provider_error",
                        http_status=response.status_code,
                    )
                if qwen:
                    parts: list[str] = []
                    usage: Mapping[str, Any] | None = None
                    for line in response.iter_lines():
                        if not line.startswith("data:") or line.strip() == "data: [DONE]":
                            continue
                        event = json.loads(line[5:].strip())
                        if not isinstance(event, dict) or event.get("error"):
                            return AudioUnderstandingResult(
                                model, "recorded_error", error_kind="provider_error",
                                http_status=response.status_code,
                            )
                        if isinstance(event.get("usage"), dict):
                            usage = event["usage"]
                        choices = event.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            if isinstance(delta.get("content"), str):
                                parts.append(delta["content"])
                    raw = "".join(parts)
                else:
                    response.read()
                    data = response.json()
                    if not isinstance(data, dict) or data.get("error"):
                        return AudioUnderstandingResult(
                            model, "recorded_error", error_kind="provider_error",
                            http_status=response.status_code,
                        )
                    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
                    raw = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError):
            return AudioUnderstandingResult(model, "recorded_error", error_kind="provider_error")
        return AudioUnderstandingResult(model, "ok", raw=raw, usage=usage, http_status=response.status_code)

    if client is not None:
        return request(client)
    with httpx.Client(timeout=httpx.Timeout(65.0, connect=10.0)) as session:
        return request(session)
