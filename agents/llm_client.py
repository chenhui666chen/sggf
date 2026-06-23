from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional

from core.model_resolution import normalize_model_id
from core.model_runtime import run_async_compat
from core.unified_llm_client import get_llm_client


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

    raw3 = os.getenv("DEEPSEEK_MODEL", "").strip()
    if raw3.startswith("qwen"):
        return raw3

    return default


@dataclass(frozen=True)
class LLMRuntimeConfig:
    api_key: str
    base_url: str
    api_key_env: str
    base_url_env: str


def _is_deepseek_official_model(model: str) -> bool:
    normalized = normalize_model_id(model) or model
    return normalized in {"deepseek-v4-flash", "deepseek-v4-pro"}


def resolve_llm_runtime_config(model: str) -> LLMRuntimeConfig:
    if _is_deepseek_official_model(model):
        return LLMRuntimeConfig(
            api_key=(os.getenv("DEEPSEEK_API_KEY") or "").strip(),
            base_url=(os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com").strip(),
            api_key_env="DEEPSEEK_API_KEY",
            base_url_env="DEEPSEEK_API_BASE",
        )

    return LLMRuntimeConfig(
        api_key=(os.getenv("DASHSCOPE_API_KEY") or "").strip(),
        base_url=(os.getenv("DASHSCOPE_API_BASE") or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip(),
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_API_BASE",
    )


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


async def _chat_once(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    timeout_s: int,
) -> str:
    client = get_llm_client(strategy="auto")
    return await client.chat(
        messages=messages,  # type: ignore[arg-type]
        model=model,
        temperature=temperature,
        timeout=timeout_s,
    )


async def _chat_stream_once(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    timeout_s: int,
    on_chunk: Callable[[str, int], None],
) -> str:
    client = get_llm_client(strategy="auto")
    chunk_index = 0

    async def relay(chunk_text: str) -> None:
        nonlocal chunk_index
        on_chunk(chunk_text, chunk_index)
        chunk_index += 1

    return await client.chat_stream(
        messages=messages,  # type: ignore[arg-type]
        model=model,
        temperature=temperature,
        timeout=timeout_s,
        on_chunk=relay,
    )


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
    del api_key, base_url

    selected_model = normalize_model_id(model) or model
    effective_timeout_s = max(1, int(timeout_s))
    if on_chunk and stream is not False:
        return run_async_compat(
            lambda: _chat_stream_once(
                model=selected_model,
                messages=messages,
                temperature=temperature,
                timeout_s=effective_timeout_s,
                on_chunk=on_chunk,
            )
        )

    content = run_async_compat(
        lambda: _chat_once(
            model=selected_model,
            messages=messages,
            temperature=temperature,
            timeout_s=effective_timeout_s,
        )
    )

    if on_chunk:
        chunk_size = int(os.getenv("LLM_STREAM_SIM_CHUNK_SIZE", "160") or 160)
        _emit_simulated_chunks(content, on_chunk=on_chunk, chunk_size=chunk_size)

    return content
