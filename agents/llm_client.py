from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional

import requests


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def pick_model(*, primary_env: str, fallback_env: str, default: str = "qwen-plus") -> str:
    raw = os.getenv(primary_env, "").strip()
    if raw:
        return raw

    raw2 = os.getenv(fallback_env, "").strip()
    if raw2:
        return raw2

    # 兼容历史：若使用方把 DEEPSEEK_MODEL 指向 qwen-*，则复用该值。
    raw3 = os.getenv("DEEPSEEK_MODEL", "").strip()
    if raw3.startswith("qwen"):
        return raw3

    return default


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not isinstance(text, str) or not text.strip():
        return None

    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001
            pass

    # 兼容模型输出带解释文字；扫描并抽取第一个“括号平衡”的 JSON 对象。
    start = text.find("{")
    while start >= 0:
        depth = 0
        in_str = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_str:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_str = False
                continue

            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : idx + 1]
                    try:
                        obj = json.loads(candidate)
                        return obj if isinstance(obj, dict) else None
                    except Exception:  # noqa: BLE001
                        break
        start = text.find("{", start + 1)

    return None


def extract_json_array(text: str) -> Optional[List[Any]]:
    if not isinstance(text, str) or not text.strip():
        return None

    fenced = re.search(r"```json\s*(\[[\s\S]*?\])\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, list) else None
        except Exception:  # noqa: BLE001
            pass

    # 扫描并抽取第一个“方括号平衡”的 JSON 数组
    start = text.find("[")
    while start >= 0:
        depth = 0
        in_str = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_str:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_str = False
                continue

            if ch == '"':
                in_str = True
                continue
            if ch == "[":
                depth += 1
                continue
            if ch == "]":
                depth -= 1
                if depth == 0:
                    candidate = text[start : idx + 1]
                    try:
                        obj = json.loads(candidate)
                        return obj if isinstance(obj, list) else None
                    except Exception:  # noqa: BLE001
                        break
        start = text.find("[", start + 1)

    return None


def _raise_for_status(resp: requests.Response) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:  # noqa: BLE001
        detail: str = ""
        try:
            data = resp.json()
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict) and err:
                    code = err.get("code")
                    message = err.get("message")
                    detail = f"{code}: {message}" if code or message else json.dumps(err, ensure_ascii=False)
                else:
                    detail = json.dumps(data, ensure_ascii=False)
            else:
                detail = json.dumps(data, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            detail = (resp.text or "").strip()
        detail = re.sub(r"\s+", " ", detail).strip()
        if len(detail) > 240:
            detail = detail[:240] + "..."
        raise RuntimeError(f"LLM request failed (HTTP {resp.status_code}): {detail}") from exc


def _chat_completions_stream(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Dict[str, Any]],
    timeout_s: int,
    temperature: float,
    on_chunk: Callable[[str, int], None],
) -> str:
    base = (base_url or "").rstrip("/")
    url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "stream": True,
    }
    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=max(10, int(timeout_s)),
        stream=True,
    )
    _raise_for_status(resp)

    full_content = ""
    chunk_index = 0
    for raw_line in resp.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:") :].strip()
        if data_str == "[DONE]":
            break
        try:
            data = json.loads(data_str)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice0 = choices[0] if isinstance(choices[0], dict) else None
        if not isinstance(choice0, dict):
            continue
        delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else None
        content_piece = None
        if delta and isinstance(delta.get("content"), str):
            content_piece = delta.get("content")
        elif isinstance(choice0.get("text"), str):
            content_piece = choice0.get("text")
        if not content_piece:
            continue
        full_content += content_piece
        try:
            on_chunk(content_piece, chunk_index)
        except Exception:  # noqa: BLE001
            pass
        chunk_index += 1

    return full_content


def _emit_simulated_chunks(
    content: str,
    *,
    on_chunk: Callable[[str, int], None],
    chunk_size: int = 160,
) -> None:
    if not content:
        return
    size = max(40, int(chunk_size))
    idx = 0
    for start in range(0, len(content), size):
        piece = content[start : start + size]
        if not piece:
            continue
        try:
            on_chunk(piece, idx)
        except Exception:  # noqa: BLE001
            pass
        idx += 1


@contextmanager
def llm_stream_context(ctx: Any, *, stage: str, stream_key: str) -> Iterator[Optional[Callable[[str, int], None]]]:
    emitter = getattr(ctx, "event_emitter", None)
    if not emitter:
        yield None
        return
    try:
        emitter.stream_start(stage=stage, stream_key=stream_key)
        yield emitter.build_stream_callback(stage=stage, stream_key=stream_key)
    finally:
        try:
            emitter.stream_end(stage=stage, stream_key=stream_key)
        except Exception:  # noqa: BLE001
            pass


def chat_completions(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: List[Dict[str, Any]],
    timeout_s: int,
    temperature: float = 0.2,
    on_chunk: Optional[Callable[[str, int], None]] = None,
    stream: Optional[bool] = None,
) -> str:
    base = (base_url or "").rstrip("/")
    # 兼容两种配置习惯：
    # - base_url=".../v1"      -> /chat/completions
    # - base_url="... (无/v1)" -> /v1/chat/completions
    url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
    }
    if on_chunk and (stream is None or stream):
        try:
            return _chat_completions_stream(
                api_key=api_key,
                base_url=base_url,
                model=model,
                messages=messages,
                timeout_s=timeout_s,
                temperature=temperature,
                on_chunk=on_chunk,
            )
        except Exception:  # noqa: BLE001
            pass
    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=max(10, int(timeout_s)),
    )
    _raise_for_status(resp)
    data = resp.json()
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            choice0 = choices[0] if isinstance(choices[0], dict) else None
            message = choice0.get("message") if isinstance(choice0, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                if on_chunk:
                    chunk_size = int(os.getenv("LLM_STREAM_SIM_CHUNK_SIZE", "160") or 160)
                    _emit_simulated_chunks(content, on_chunk=on_chunk, chunk_size=chunk_size)
                return content
    raise RuntimeError("invalid LLM response: missing choices[0].message.content")
