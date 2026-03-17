from __future__ import annotations

import inspect
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional

from core.model_resolution import normalize_model_id, normalize_task_type
from core.model_runtime import ensure_model_hub_initialized

StreamCallback = Callable[[str], Awaitable[None] | None]


async def _invoke_callback(callback: Optional[StreamCallback], chunk: str) -> None:
    if callback is None:
        return

    result = callback(chunk)
    if inspect.isawaitable(result):
        await result


class UnifiedLLMClient:
    """基于 ModelHub 的统一 LLM 客户端。"""

    def __init__(self, strategy: str = "auto"):
        self.strategy = strategy
        ensure_model_hub_initialized()

    async def chat(
        self,
        messages: List[Dict[str, str]],
        task_type: Optional[Any] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        from core.model_hub import model_hub

        ensure_model_hub_initialized()

        result = await model_hub.call(
            messages=messages,
            task_type=normalize_task_type(task_type),
            model=normalize_model_id(model),
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        if not result.success:
            raise RuntimeError(
                f"统一模型调用失败: model={result.model_id or normalize_model_id(model) or 'auto'} "
                f"task_type={normalize_task_type(task_type) or 'default'} "
                f"error={result.error or result.error_code or 'unknown'}"
            )

        return result.content

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        on_chunk: Optional[StreamCallback] = None,
        task_type: Optional[Any] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        async def relay(chunk: str) -> None:
            await _invoke_callback(on_chunk, chunk)

        return await self.chat(
            messages=messages,
            task_type=task_type,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            on_chunk=relay,
            **kwargs,
        )

    async def chat_stream_generator(
        self,
        messages: List[Dict[str, str]],
        task_type: Optional[Any] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        chunks: List[str] = []

        async def collect(chunk: str) -> None:
            chunks.append(chunk)

        await self.chat(
            messages=messages,
            task_type=task_type,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            on_chunk=collect,
            **kwargs,
        )

        for chunk in chunks:
            yield chunk


_client: Optional[UnifiedLLMClient] = None


def get_llm_client(strategy: str = "auto") -> UnifiedLLMClient:
    global _client
    if _client is None or _client.strategy != strategy:
        _client = UnifiedLLMClient(strategy=strategy)
    return _client
