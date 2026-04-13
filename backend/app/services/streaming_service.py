"""
流式输出服务 - 基于统一模型中心的实时推送封装
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable, Dict, List, Optional

from core.model_resolution import normalize_model_id, normalize_task_type
from core.model_runtime import resolve_model_for_task
from core.unified_llm_client import UnifiedLLMClient, get_llm_client

logger = logging.getLogger(__name__)


class StreamingService:
    """
    流式输出服务

    对外保持既有接口，内部统一改走 ModelHub。
    """

    def __init__(self, llm_client: Optional[UnifiedLLMClient] = None):
        self.llm_client = llm_client or get_llm_client(strategy="auto")
        self.default_model = normalize_model_id(os.getenv("DEEPSEEK_MODEL", "qwen3-max")) or "qwen3-max"

    async def generate_with_streaming(
        self,
        messages: List[Dict[str, str]],
        on_chunk: Callable[[str, int], Awaitable[None]],
        on_complete: Optional[Callable[[str, int], Awaitable[None]]] = None,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        max_retries: int = 3,
    ) -> str:
        normalized_task_type = normalize_task_type(task_type)
        explicit_model = normalize_model_id(model)
        selected_model = (
            resolve_model_for_task(normalized_task_type, explicit_model)
            or explicit_model
            or self.default_model
        )
        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            chunk_index = 0
            collected: List[str] = []

            async def relay(chunk_text: str) -> None:
                nonlocal chunk_index
                collected.append(chunk_text)
                await on_chunk(chunk_text, chunk_index)
                chunk_index += 1

            try:
                if attempt > 0:
                    wait_time = 2 ** attempt
                    logger.info(f"流式生成重试中，第 {attempt + 1}/{max_retries} 次，等待 {wait_time} 秒")
                    await asyncio.sleep(wait_time)

                logger.info(f"开始流式生成 | 模型: {selected_model} | 尝试: {attempt + 1}/{max_retries}")
                content = await self.llm_client.chat_stream(
                    messages=messages,
                    on_chunk=relay,
                    task_type=normalized_task_type,
                    model=explicit_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    max_retries=1,
                )

                if on_complete:
                    await on_complete(content, len(content))

                logger.info(f"流式生成完成 | 模型: {selected_model} | 字符数: {len(content)} | 块数: {chunk_index}")
                return content

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                error_text = str(exc).lower()
                retryable = not any(
                    token in error_text
                    for token in ("auth_error", "invalid api key", "model_not_registered", "model_not_found")
                )
                if retryable and attempt < max_retries - 1:
                    logger.warning(f"流式生成失败，准备重试: {exc}")
                    continue

                logger.error(f"流式生成失败: {exc}")
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("流式生成失败")

    async def generate_chapter_streaming(
        self,
        prompt: str,
        system_prompt: str,
        on_chunk: Callable[[str, int], Awaitable[None]],
        on_complete: Optional[Callable[[str, int], Awaitable[None]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        return await self.generate_with_streaming(
            messages=messages,
            on_chunk=on_chunk,
            on_complete=on_complete,
            temperature=temperature,
            model=model,
            task_type=task_type,
        )


_streaming_service: Optional[StreamingService] = None


def get_streaming_service() -> StreamingService:
    global _streaming_service
    if _streaming_service is None:
        _streaming_service = StreamingService()
    return _streaming_service
