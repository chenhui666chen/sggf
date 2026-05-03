from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.model_resolution import TaskType

from .llm_config import get_audiobook_llm_model


@dataclass(frozen=True)
class AudiobookLLMHealth:
    model: str
    ok: bool
    response_preview: str = ""
    error: str = ""


async def call_audiobook_llm_async(
    llm_client: Any,
    *,
    messages: List[Dict[str, str]],
    task_type: Any = TaskType.AUDIOBOOK_SCRIPT,
    model: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    **kwargs: Any,
) -> str:
    if llm_client is None or not hasattr(llm_client, "chat"):
        raise ValueError("llm_client must provide an async chat method")

    call_kwargs = {key: value for key, value in kwargs.items() if value is not None}
    selected_model = model or get_audiobook_llm_model()

    async def invoke() -> str:
        return await llm_client.chat(
            messages=messages,
            task_type=task_type,
            model=selected_model,
            **call_kwargs,
        )

    if timeout_seconds and timeout_seconds > 0:
        return await asyncio.wait_for(invoke(), timeout=timeout_seconds)
    return await invoke()


def call_audiobook_llm_sync(
    llm_client: Any,
    *,
    messages: List[Dict[str, str]],
    task_type: Any = TaskType.AUDIOBOOK_SCRIPT,
    model: Optional[str] = None,
    timeout_seconds: Optional[float] = 60,
    **kwargs: Any,
) -> str:
    async def invoke() -> str:
        return await call_audiobook_llm_async(
            llm_client,
            messages=messages,
            task_type=task_type,
            model=model,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )

    outer_timeout = timeout_seconds + 1 if timeout_seconds and timeout_seconds > 0 else timeout_seconds
    return run_async_from_sync(invoke, timeout_seconds=outer_timeout)


def run_async_from_sync(coro_factory, *, timeout_seconds: Optional[float] = 60):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        if timeout_seconds and timeout_seconds > 0:
            return asyncio.run(asyncio.wait_for(coro_factory(), timeout=timeout_seconds))
        return asyncio.run(coro_factory())

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(lambda: asyncio.run(coro_factory()))
        return future.result(timeout=timeout_seconds)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


async def check_audiobook_llm_health(
    llm_client: Any,
    *,
    timeout_seconds: float = 20,
) -> AudiobookLLMHealth:
    model = get_audiobook_llm_model()
    try:
        response = await call_audiobook_llm_async(
            llm_client,
            messages=[
                {
                    "role": "user",
                    "content": 'Return exactly this JSON object: {"ok": true}',
                }
            ],
            task_type=TaskType.AUDIOBOOK_SCRIPT,
            model=model,
            max_tokens=20,
            response_format={"type": "json_object"},
            use_cache=False,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return AudiobookLLMHealth(model=model, ok=False, error=str(exc))

    return AudiobookLLMHealth(
        model=model,
        ok=True,
        response_preview=str(response or "")[:200],
    )
