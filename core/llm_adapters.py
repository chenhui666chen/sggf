# -*- coding: utf-8 -*-
"""
LLM 适配器实现 - 支持阿里云 DashScope 和 DeepSeek

提供统一的 LLM 调用接口
"""

from __future__ import annotations

import os
import time
import logging
import inspect
from typing import Dict, List, Optional, Any, Callable, TYPE_CHECKING

from core.unified_registry import BaseLLMAdapter, register_llm_model

if TYPE_CHECKING:
    from schemas.unified_model_spec import LLMResult, UnifiedModelSpec

logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """
    OpenAI 兼容 API 适配器基类

    适用于所有兼容 OpenAI API 格式的服务
    """

    def __init__(self, spec: "UnifiedModelSpec"):
        super().__init__(spec)
        self._init_client()

    def _build_completion_params(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: Optional[int],
        extra_kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "model": self.spec.id,
            "messages": messages,
        }

        if self.spec.default_params:
            params.update({k: v for k, v in self.spec.default_params.items() if v is not None})

        if self.spec.constraints.supports_temperature and temperature is not None:
            params["temperature"] = temperature

        if max_tokens:
            params["max_tokens"] = max_tokens

        passthrough_keys = {
            "response_format",
            "stop",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "seed",
            "tools",
            "tool_choice",
            "extra_body",
        }
        for key in passthrough_keys:
            value = extra_kwargs.get(key)
            if value is not None:
                params[key] = value

        timeout = extra_kwargs.get("timeout")
        if timeout is not None and self.spec.constraints.supports_timeout_param:
            params["timeout"] = timeout

        return params

    def _init_client(self) -> None:
        """初始化 OpenAI 客户端"""
        try:
            from openai import AsyncOpenAI
            import httpx

            api_key = self.spec.api_config.get_api_key()
            base_url = self.spec.api_config.base_url

            if not api_key:
                logger.warning(f"⚠️ 模型 {self.spec.id} 未配置 API Key")
                return

            http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self.spec.api_config.default_timeout,
                    connect=30.0
                ),
                trust_env=False,
            )

            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=self.spec.api_config.default_timeout,
                http_client=http_client,
            )

            self._initialized = True
            logger.debug(f"✅ 初始化客户端: {self.spec.id}")

        except ImportError:
            logger.error("❌ 未安装 openai 库，请运行: pip install openai")
            raise

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> "LLMResult":
        """生成响应"""
        from schemas.unified_model_spec import LLMResult

        if not self._initialized or not self._client:
            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error="客户端未初始化",
                error_code="client_not_initialized"
            )

        start_time = time.time()

        try:
            effective_max_tokens = max_tokens or self.spec.constraints.max_output_tokens

            params = self._build_completion_params(messages, temperature, effective_max_tokens, kwargs)

            if self.spec.constraints.supports_streaming and kwargs.get("stream"):
                return await self._generate_stream_internal(
                    messages,
                    temperature,
                    effective_max_tokens,
                    kwargs.get("on_chunk"),
                    kwargs,
                )

            response = await self._client.chat.completions.create(**params)

            content = response.choices[0].message.content or ""

            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            latency = time.time() - start_time
            cost = self.spec.performance.estimate_cost(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0)
            )

            logger.debug(
                f"✅ LLM调用成功 | 模型: {self.spec.id} | "
                f"延迟: {latency:.2f}s | Tokens: {usage.get('total_tokens', 0)}"
            )

            return LLMResult(
                success=True,
                model_id=self.spec.id,
                content=content,
                usage=usage,
                latency=latency,
                cost=cost,
            )

        except Exception as e:
            latency = time.time() - start_time
            error_code = self._map_error_code(e)

            logger.error(f"❌ LLM调用失败 | 模型: {self.spec.id} | 错误: {e}")

            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error=str(e),
                error_code=error_code,
                latency=latency,
            )

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        on_chunk: Callable[[str], None],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> "LLMResult":
        """流式生成响应"""
        return await self._generate_stream_internal(
            messages, temperature, max_tokens, on_chunk, kwargs
        )

    async def _generate_stream_internal(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: Optional[int],
        on_chunk: Optional[Callable[[str], None]] = None,
        extra_kwargs: Optional[Dict[str, Any]] = None,
    ) -> "LLMResult":
        """内部流式生成实现"""
        from schemas.unified_model_spec import LLMResult

        if not self._initialized or not self._client:
            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error="客户端未初始化",
                error_code="client_not_initialized"
            )

        start_time = time.time()

        try:
            effective_max_tokens = max_tokens or self.spec.constraints.max_output_tokens

            params = self._build_completion_params(
                messages,
                temperature,
                effective_max_tokens,
                extra_kwargs or {},
            )
            params["stream"] = True

            stream = await self._client.chat.completions.create(**params)

            content = ""
            chunk_count = 0

            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        content_piece = delta.content
                        content += content_piece
                        chunk_count += 1

                        if on_chunk:
                            try:
                                callback_result = on_chunk(content_piece)
                                if inspect.isawaitable(callback_result):
                                    await callback_result
                            except Exception as e:
                                logger.warning(f"⚠️ 流式回调失败: {e}")

            latency = time.time() - start_time

            logger.debug(
                f"✅ LLM流式调用成功 | 模型: {self.spec.id} | "
                f"延迟: {latency:.2f}s | 块数: {chunk_count}"
            )

            return LLMResult(
                success=True,
                model_id=self.spec.id,
                content=content,
                latency=latency,
                metadata={"chunk_count": chunk_count},
            )

        except Exception as e:
            latency = time.time() - start_time
            error_code = self._map_error_code(e)

            logger.error(f"❌ LLM流式调用失败 | 模型: {self.spec.id} | 错误: {e}")

            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error=str(e),
                error_code=error_code,
                latency=latency,
            )

    def _map_error_code(self, error: Exception) -> str:
        """映射错误码"""
        error_str = str(error).lower()

        if "rate limit" in error_str or "429" in error_str:
            return "rate_limit"
        if "timeout" in error_str or "timed out" in error_str:
            return "timeout"
        if "unauthorized" in error_str or "401" in error_str or "invalid api key" in error_str:
            return "auth_error"
        if "quota" in error_str or "insufficient" in error_str:
            return "insufficient_quota"
        if "content" in error_str and ("safety" in error_str or "blocked" in error_str):
            return "content_safety"
        if "model" in error_str and ("not found" in error_str or "unavailable" in error_str):
            return "model_unavailable"

        return "unknown_error"


@register_llm_model(
    model_id="qwen3-max",
    name="Qwen3 Max",
    provider="alibaba",
    capabilities=["creative", "dialogue", "reasoning", "writing"],
    task_types=["concept", "chapter", "dialogue", "creative", "writing"],
    max_context_tokens=32000,
    max_output_tokens=8192,
    quality_score=8.5,
    avg_latency_seconds=2.5,
    cost_per_1k_input_tokens=0.004,
    cost_per_1k_output_tokens=0.012,
    api_key_env="DASHSCOPE_API_KEY",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    priority=1,
    fallback_models=["deepseek-chat"],
    tags=["creative", "dialogue", "chinese"],
)
class QwenMaxAdapter(OpenAICompatibleAdapter):
    """阿里云 Qwen3 Max 适配器"""

    pass


@register_llm_model(
    model_id="qwen-long",
    name="Qwen Long",
    provider="alibaba",
    capabilities=["long_context", "summarization", "analysis"],
    task_types=["outline_expand", "book_synthesis", "long_context"],
    max_context_tokens=10000000,
    max_output_tokens=8192,
    quality_score=8.0,
    avg_latency_seconds=5.0,
    cost_per_1k_input_tokens=0.0005,
    cost_per_1k_output_tokens=0.002,
    api_key_env="DASHSCOPE_API_KEY",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    priority=1,
    tags=["long_context", "chinese"],
)
class QwenLongAdapter(OpenAICompatibleAdapter):
    """阿里云 Qwen Long 适配器 - 支持超长上下文"""

    pass


@register_llm_model(
    model_id="qwen-turbo",
    name="Qwen Turbo",
    provider="alibaba",
    capabilities=["fast", "simple", "extraction"],
    task_types=["entity_extract", "summarize", "simple"],
    max_context_tokens=8192,
    max_output_tokens=4096,
    quality_score=7.0,
    avg_latency_seconds=1.0,
    cost_per_1k_input_tokens=0.0008,
    cost_per_1k_output_tokens=0.002,
    api_key_env="DASHSCOPE_API_KEY",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    priority=2,
    tags=["fast", "chinese"],
)
class QwenTurboAdapter(OpenAICompatibleAdapter):
    """阿里云 Qwen Turbo 适配器 - 快速响应"""

    pass


@register_llm_model(
    model_id="deepseek-reasoner",
    name="DeepSeek R1",
    provider="deepseek",
    capabilities=["reasoning", "logic", "analysis", "planning"],
    task_types=["worldview", "character", "structure_plot", "review", "reasoning"],
    max_context_tokens=64000,
    max_output_tokens=8192,
    quality_score=9.0,
    avg_latency_seconds=15.0,
    cost_per_1k_input_tokens=0.014,
    cost_per_1k_output_tokens=0.014,
    api_key_env="DEEPSEEK_API_KEY",
    base_url="https://api.deepseek.com/v1",
    supports_streaming=False,
    supports_timeout_param=False,
    supports_max_retries=False,
    priority=1,
    fallback_models=["qwen3-max"],
    tags=["reasoning", "logic"],
)
class DeepSeekReasonerAdapter(OpenAICompatibleAdapter):
    """DeepSeek R1 适配器 - 深度推理模型"""

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> "LLMResult":
        """生成响应 - R1 特殊处理"""
        from schemas.unified_model_spec import LLMResult

        if not self._initialized or not self._client:
            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error="客户端未初始化",
                error_code="client_not_initialized"
            )

        start_time = time.time()

        try:
            effective_max_tokens = max_tokens or self.spec.constraints.max_output_tokens

            params = self._build_completion_params(messages, temperature, effective_max_tokens, kwargs)
            params.pop("temperature", None)

            response = await self._client.chat.completions.create(**params)

            content = response.choices[0].message.content or ""

            if "<think" in content and "</think" in content:
                import re
                content = re.sub(r'<think[^>]*>.*?</think\s*>', '', content, flags=re.DOTALL).strip()

            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            latency = time.time() - start_time
            cost = self.spec.performance.estimate_cost(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0)
            )

            logger.debug(
                f"✅ DeepSeek R1调用成功 | 延迟: {latency:.2f}s | Tokens: {usage.get('total_tokens', 0)}"
            )

            return LLMResult(
                success=True,
                model_id=self.spec.id,
                content=content,
                usage=usage,
                latency=latency,
                cost=cost,
            )

        except Exception as e:
            latency = time.time() - start_time
            error_code = self._map_error_code(e)

            logger.error(f"❌ DeepSeek R1调用失败 | 错误: {e}")

            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error=str(e),
                error_code=error_code,
                latency=latency,
            )


@register_llm_model(
    model_id="deepseek-chat",
    name="DeepSeek Chat",
    provider="deepseek",
    capabilities=["chat", "writing", "fast"],
    task_types=["chat", "rewrite", "fast"],
    max_context_tokens=64000,
    max_output_tokens=8192,
    quality_score=8.0,
    avg_latency_seconds=2.0,
    cost_per_1k_input_tokens=0.001,
    cost_per_1k_output_tokens=0.002,
    api_key_env="DEEPSEEK_API_KEY",
    base_url="https://api.deepseek.com/v1",
    priority=2,
    fallback_models=["qwen3-max"],
    tags=["chat", "fast"],
)
class DeepSeekChatAdapter(OpenAICompatibleAdapter):
    """DeepSeek Chat 适配器"""

    pass
