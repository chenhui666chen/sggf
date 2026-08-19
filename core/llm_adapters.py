# -*- coding: utf-8 -*-
"""
LLM 适配器实现 - 支持阿里云 DashScope 和 DeepSeek 官方 API

提供统一的 LLM 调用接口
"""

from __future__ import annotations

import asyncio
import os
import time
import logging
import inspect
import threading
from typing import Dict, List, Optional, Any, Callable, TYPE_CHECKING

from core.unified_registry import BaseLLMAdapter, register_llm_model

if TYPE_CHECKING:
    from schemas.unified_model_spec import LLMResult, UnifiedModelSpec

logger = logging.getLogger(__name__)


def _is_truthy_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


_SPECIAL_DEFAULT_PARAM_KEYS = {"request_model"}
_DEEPSEEK_THINKING_ENABLED = {"enabled", "on", "true", "1", "yes"}
_DEEPSEEK_THINKING_DISABLED = {"disabled", "off", "false", "0", "no"}


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """
    OpenAI 兼容 API 适配器基类

    适用于所有兼容 OpenAI API 格式的服务
    """

    def __init__(self, spec: "UnifiedModelSpec"):
        super().__init__(spec)
        self._client_pool: Dict[tuple[int, Optional[int]], Any] = {}
        self._client_pool_lock = threading.RLock()
        self._init_client()

    def _build_completion_params(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: Optional[int],
        extra_kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "model": self._resolve_request_model(),
            "messages": messages,
        }

        # OpenAI SDK 标准参数白名单；不在此列的参数统一放入 extra_body 透传给后端
        _OPENAI_STANDARD_KEYS = {
            "temperature", "max_tokens", "top_p", "frequency_penalty",
            "presence_penalty", "stop", "seed", "response_format",
            "tools", "tool_choice", "stream", "n", "logprobs",
            "top_logprobs", "user", "reasoning_effort",
        }
        if self.spec.default_params:
            extra_body = params.get("extra_body") or {}
            for k, v in self.spec.default_params.items():
                if v is None:
                    continue
                if k in _SPECIAL_DEFAULT_PARAM_KEYS:
                    continue
                if k in _OPENAI_STANDARD_KEYS:
                    params[k] = v
                else:
                    extra_body[k] = v
            if extra_body:
                params["extra_body"] = extra_body

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
            "stream",
            "reasoning_effort",
            "extra_body",
        }
        for key in passthrough_keys:
            value = extra_kwargs.get(key)
            if value is not None:
                params[key] = value

        timeout = self._build_request_timeout(extra_kwargs.get("timeout"))
        if timeout is not None:
            params["timeout"] = timeout

        self._apply_deepseek_thinking_policy(params)

        return params

    def _is_deepseek_official_adapter(self) -> bool:
        return self.spec.provider == "deepseek" and self.spec.api_config.base_url.rstrip("/") == "https://api.deepseek.com"

    def _normalize_deepseek_thinking(self, value: Any) -> Optional[Dict[str, str]]:
        if value is None:
            return None

        if isinstance(value, dict):
            raw_type = str(value.get("type", "")).strip().lower()
        elif isinstance(value, bool):
            raw_type = "enabled" if value else "disabled"
        else:
            raw_type = str(value).strip().lower()

        if raw_type in _DEEPSEEK_THINKING_ENABLED:
            return {"type": "enabled"}
        if raw_type in _DEEPSEEK_THINKING_DISABLED:
            return {"type": "disabled"}
        return None

    def _requires_non_thinking_mode(self, params: Dict[str, Any]) -> bool:
        if params.get("stream"):
            return True
        if params.get("tools") or params.get("tool_choice"):
            return True
        response_format = params.get("response_format")
        return isinstance(response_format, dict) and response_format.get("type") == "json_object"

    def _apply_deepseek_thinking_policy(self, params: Dict[str, Any]) -> None:
        if not self._is_deepseek_official_adapter():
            return

        extra_body = dict(params.get("extra_body") or {})
        default_params = self.spec.default_params or {}
        thinking = self._normalize_deepseek_thinking(
            extra_body.get("thinking", default_params.get("thinking"))
        )

        if self._requires_non_thinking_mode(params):
            thinking = {"type": "disabled"}

        if thinking:
            extra_body["thinking"] = thinking

        if thinking and thinking["type"] == "enabled":
            params.pop("temperature", None)
            reasoning_effort = default_params.get("reasoning_effort")
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort
        else:
            params.pop("reasoning_effort", None)
            extra_body.pop("reasoning_effort", None)

        if extra_body:
            params["extra_body"] = extra_body
        else:
            params.pop("extra_body", None)

    def _extract_reasoning_metadata(self, message: Any) -> Dict[str, Any]:
        reasoning_content = getattr(message, "reasoning_content", None)
        if not reasoning_content:
            return {}

        return {
            "has_reasoning_content": True,
            "reasoning_content_len": len(str(reasoning_content)),
        }

    def _resolve_request_model(self) -> str:
        default_params = self.spec.default_params or {}
        request_model = default_params.get("request_model")
        if isinstance(request_model, str) and request_model.strip():
            return request_model.strip()
        return self.spec.id

    def _normalize_requested_max_tokens(self, max_tokens: Optional[int]) -> Optional[int]:
        if max_tokens is None:
            return None

        try:
            normalized = int(max_tokens)
        except (TypeError, ValueError):
            logger.warning("Ignore invalid max_tokens=%r for model %s", max_tokens, self.spec.id)
            return None

        if normalized <= 0:
            return None

        max_output_tokens = int(getattr(self.spec.constraints, "max_output_tokens", 0) or 0)
        if max_output_tokens > 0 and normalized > max_output_tokens:
            logger.warning(
                "Clamp max_tokens for model %s from %s to %s",
                self.spec.id,
                normalized,
                max_output_tokens,
            )
            return max_output_tokens

        return normalized

    def _log_empty_response_diagnostic(
        self,
        message: Any,
        finish_reason: Optional[str],
        usage: Any,
    ) -> None:
        """空响应诊断：HTTP 200 但 content 为空时记录关键字段。

        典型根因：思考模型 adaptive 思考耗尽 max_tokens 总预算
        （finish_reason=length，思考 token 计入 completion 而正文为空）、
        网关内容过滤等。历史上此处只能看到 content=""，属排查盲区。
        """
        reasoning = getattr(message, "reasoning_content", None) or ""
        completion_tokens = getattr(usage, "completion_tokens", None) if usage is not None else None
        logger.warning(
            "⚠️ 空响应诊断 | 模型: %s | finish_reason=%s | reasoning=%d字 | completion_tokens=%s",
            self.spec.id,
            finish_reason,
            len(reasoning),
            completion_tokens,
        )

    def _build_request_timeout(self, timeout_value: Optional[Any]) -> Optional[Any]:
        if timeout_value is None:
            return None

        try:
            normalized = max(1.0, float(timeout_value))
        except (TypeError, ValueError):
            logger.warning("Ignore invalid timeout=%r for model %s", timeout_value, self.spec.id)
            return None

        import httpx

        return httpx.Timeout(
            normalized,
            connect=min(normalized, 30.0),
            write=min(normalized, 60.0),
            pool=min(normalized, 30.0),
        )

    def _get_client_context_key(self) -> tuple[int, Optional[int]]:
        loop_id: Optional[int] = None
        try:
            loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            loop_id = None
        return threading.get_ident(), loop_id

    def _create_client(self, api_key: str) -> Any:
        from openai import AsyncOpenAI
        import httpx

        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                self.spec.api_config.default_timeout,
                connect=30.0
            ),
            trust_env=_is_truthy_env("MODEL_HTTP_TRUST_ENV", default=False),
        )

        return AsyncOpenAI(
            api_key=api_key,
            base_url=self.spec.api_config.base_url,
            timeout=self.spec.api_config.default_timeout,
            max_retries=0,
            http_client=http_client,
        )

    def _get_client_for_current_context(self) -> Any:
        api_key = self.spec.api_config.get_api_key()
        if not api_key:
            logger.warning(f"⚠️ 模型 {self.spec.id} 未配置 API Key")
            self._initialized = False
            return None

        context_key = self._get_client_context_key()
        with self._client_pool_lock:
            client = self._client_pool.get(context_key)
            if client is None:
                client = self._create_client(api_key)
                self._client_pool[context_key] = client
                logger.debug(
                    "✅ 为模型 %s 创建上下文隔离客户端 | thread=%s loop=%s",
                    self.spec.id,
                    context_key[0],
                    context_key[1],
                )

            self._client = client
            self._initialized = True
            return client

    def _close_client_instance(self, client: Any) -> None:
        close_method = getattr(client, "close", None)
        if not callable(close_method):
            return

        try:
            close_result = close_method()
            if inspect.isawaitable(close_result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    asyncio.run(close_result)
                else:
                    loop.create_task(close_result)
        except Exception:
            pass

    def _reset_current_context_client(self, reason: Optional[str] = None) -> None:
        context_key = self._get_client_context_key()
        with self._client_pool_lock:
            client = self._client_pool.pop(context_key, None)
            if self._client is client:
                self._client = next(iter(self._client_pool.values()), None)

        if client is not None:
            self._close_client_instance(client)
            logger.debug(
                "🔄 已重置模型 %s 的上下文客户端 | thread=%s loop=%s reason=%s",
                self.spec.id,
                context_key[0],
                context_key[1],
                reason or "unknown",
            )

    def _init_client(self) -> None:
        """初始化 OpenAI 客户端"""
        try:
            api_key = self.spec.api_config.get_api_key()

            if not api_key:
                logger.warning(f"⚠️ 模型 {self.spec.id} 未配置 API Key")
                return

            self._client = self._get_client_for_current_context()
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

        client = self._get_client_for_current_context()
        if not self._initialized or not client:
            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error="客户端未初始化",
                error_code="client_not_initialized"
            )

        start_time = time.time()
        effective_max_tokens = self._normalize_requested_max_tokens(max_tokens)

        try:

            params = self._build_completion_params(messages, temperature, effective_max_tokens, kwargs)

            if self.spec.constraints.supports_streaming and kwargs.get("stream"):
                return await self._generate_stream_internal(
                    messages,
                    temperature,
                    effective_max_tokens,
                    kwargs.get("on_chunk"),
                    kwargs,
                )

            response = await client.chat.completions.create(**params)

            message = response.choices[0].message
            content = message.content or ""
            if not content.strip():
                # 🔧 空响应诊断：HTTP 200 但 content 为空时记录关键字段，
                #    避免思考模型预算耗尽等根因成为排查盲区
                self._log_empty_response_diagnostic(
                    message=message,
                    finish_reason=response.choices[0].finish_reason,
                    usage=response.usage,
                )
            metadata = self._extract_reasoning_metadata(message)

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
                metadata=metadata,
            )

        except Exception as e:
            latency = time.time() - start_time
            error_code = self._map_error_code(e)
            error_msg = str(e) or f"[{type(e).__name__}] (empty message)"

            if error_code in {"network_error", "timeout"}:
                self._reset_current_context_client(reason=error_code)

            logger.error(
                f"❌ LLM调用失败 | 模型: {self.spec.id} | 错误码: {error_code} | "
                f"异常类型: {type(e).__name__} | 错误: {error_msg}",
                exc_info=True,
            )

            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error=error_msg,
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
            messages,
            temperature,
            self._normalize_requested_max_tokens(max_tokens),
            on_chunk,
            kwargs,
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

        client = self._get_client_for_current_context()
        if not self._initialized or not client:
            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error="客户端未初始化",
                error_code="client_not_initialized"
            )

        start_time = time.time()

        try:
            params = self._build_completion_params(
                messages,
                temperature,
                max_tokens,
                extra_kwargs or {},
            )
            params["stream"] = True

            stream = await client.chat.completions.create(**params)

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
            error_msg = str(e) or f"[{type(e).__name__}] (empty message)"

            if error_code in {"network_error", "timeout"}:
                self._reset_current_context_client(reason=error_code)

            logger.error(
                f"❌ LLM流式调用失败 | 模型: {self.spec.id} | 错误码: {error_code} | "
                f"异常类型: {type(e).__name__} | 错误: {error_msg}",
                exc_info=True,
            )

            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error=error_msg,
                error_code=error_code,
                latency=latency,
            )

    def close(self) -> None:
        with self._client_pool_lock:
            clients = list(self._client_pool.values())
            self._client_pool.clear()
            self._client = None

        for client in clients:
            self._close_client_instance(client)

        self._initialized = False

    def _map_error_code(self, error: Exception) -> str:
        """映射错误码"""
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()

        if any(
            marker in error_str
            for marker in (
                "rate limit",
                "429",
                "too many requests",
                "throttled",
                "capacity limits",
                "serviceunavailable",
            )
        ):
            return "rate_limit"
        if "timeout" in error_str or "timed out" in error_str:
            return "timeout"
        if any(
            marker in error_str
            for marker in (
                "connection error",
                "connect error",
                "connection refused",
                "connection reset",
                "network is unreachable",
                "name or service not known",
                "temporary failure in name resolution",
                "nodename nor servname",
                "dns",
                "ssl",
                "tls",
                "proxyerror",
            )
        ) or any(
            marker in error_type
            for marker in (
                "apiconnectionerror",
                "connecterror",
                "networkerror",
            )
        ):
            return "network_error"
        if "unauthorized" in error_str or "401" in error_str or "invalid api key" in error_str:
            return "auth_error"
        if "quota" in error_str or "insufficient" in error_str:
            return "insufficient_quota"
        if ("content" in error_str and ("safety" in error_str or "blocked" in error_str)) or "inappropriate content" in error_str:
            return "content_safety"
        if "model" in error_str and ("not found" in error_str or "unavailable" in error_str):
            return "model_unavailable"

        return "unknown_error"


@register_llm_model(
    model_id="qwen3.7-plus",
    name="Qwen3.7 Plus",
    provider="alibaba",
    capabilities=["creative", "reasoning", "long_context", "multimodal", "web_search", "writing", "agent"],
    task_types=["concept", "outline_expand", "volume_outline", "chapter_batch", "long_writing", "multimodal_analysis", "verification"],
    max_context_tokens=1000000,
    max_output_tokens=65536,
    quality_score=9.2,
    avg_latency_seconds=1.6,
    cost_per_1k_input_tokens=0.002,
    cost_per_1k_output_tokens=0.008,
    api_key_env="DASHSCOPE_API_KEY",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    default_timeout=180,
    supports_function_call=True,
    supports_vision=True,
    priority=1,
    fallback_models=["deepseek-v4-flash"],
    default_params={"temperature": 0.7, "max_tokens": 32768, "enable_thinking": False},
    tags=["creative", "reasoning", "long_context", "multimodal", "web_search", "chinese", "alibaba", "verification", "agent"],
)
class Qwen37PlusAdapter(OpenAICompatibleAdapter):
    """阿里云 Qwen3.7 Plus 适配器。原生支持文本、图像、视频输入，保留视觉理解能力。"""

    pass


@register_llm_model(
    model_id="qwen3.7-flash",
    name="Qwen3.7 Flash",
    provider="alibaba",
    capabilities=["creative", "reasoning", "long_context", "writing"],
    task_types=["concept", "outline_expand", "volume_outline", "chapter_batch", "long_writing", "summarize", "entity_extract"],
    max_context_tokens=1000000,
    max_output_tokens=65536,
    quality_score=8.5,
    avg_latency_seconds=1.2,
    cost_per_1k_input_tokens=0.0002,
    cost_per_1k_output_tokens=0.0008,
    api_key_env="DASHSCOPE_API_KEY",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    default_timeout=180,
    supports_function_call=True,
    supports_vision=False,
    supports_thinking_mode=True,
    priority=3,
    fallback_models=["qwen3.7-plus"],
    default_params={"temperature": 0.7, "max_tokens": 32768, "enable_thinking": False},
    tags=["creative", "long_context", "fast", "low_cost", "chinese", "alibaba"],
)
class Qwen37FlashAdapter(OpenAICompatibleAdapter):
    """阿里云 Qwen3.7 Flash 适配器。轻量高速文本模型，输入0.2元/百万tokens、
    输出0.8元/百万tokens，适合大批量低成本文本任务。视觉能力未经项目验证，暂不开放。"""

    pass


@register_llm_model(
    model_id="kimi/kimi-k2.6",
    name="Kimi K2.6",
    provider="moonshot",
    capabilities=["creative", "reasoning", "long_context", "multimodal", "writing"],
    task_types=["concept", "outline_expand", "chapter_batch", "long_writing", "multimodal_analysis"],
    max_context_tokens=131072,
    max_output_tokens=8192,
    quality_score=8.9,
    avg_latency_seconds=2.0,
    cost_per_1k_input_tokens=0.0065,
    cost_per_1k_output_tokens=0.027,
    api_key_env="DASHSCOPE_API_KEY",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    default_timeout=180,
    supports_function_call=True,
    supports_vision=True,
    supports_thinking_mode=True,
    priority=2,
    fallback_models=["qwen3.7-plus"],
    default_params={"temperature": 0.7, "max_tokens": 8192, "enable_thinking": False},
    tags=["creative", "reasoning", "long_context", "multimodal", "chinese", "moonshot", "alibaba"],
)
class KimiK26Adapter(OpenAICompatibleAdapter):
    """月之暗面 Kimi K2.6 适配器。经阿里云百炼 OpenAI 兼容接口接入，
    原生支持文本、图像、视频输入与思考模式（enable_thinking）。"""

    pass


@register_llm_model(
    model_id="glm-5.2",
    name="GLM-5.2",
    provider="zhipu",
    capabilities=["reasoning", "coding", "long_context", "agent", "writing"],
    task_types=["concept", "outline_expand", "chapter_batch", "long_writing", "coding", "agent"],
    max_context_tokens=1000000,
    max_output_tokens=16384,
    quality_score=9.1,
    avg_latency_seconds=2.5,
    cost_per_1k_input_tokens=0.008,
    cost_per_1k_output_tokens=0.028,
    api_key_env="DASHSCOPE_API_KEY",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    default_timeout=300,
    supports_function_call=True,
    supports_thinking_mode=True,
    priority=2,
    fallback_models=["qwen3.7-plus"],
    default_params={"temperature": 0.7, "max_tokens": 16384, "enable_thinking": False},
    tags=["reasoning", "coding", "long_context", "agent", "chinese", "zhipu", "alibaba", "open_source"],
)
class GLM52Adapter(OpenAICompatibleAdapter):
    """智谱 GLM-5.2 适配器。经阿里云百炼 OpenAI 兼容接口接入，
    744B MoE 架构，原生支持100万tokens稳定上下文，主打长程推理与代码工程。
    启用完整上下文需使用 model="glm-5.2[1m]"。"""

    pass


@register_llm_model(
    model_id="MiniMax/MiniMax-M3",
    name="MiniMax M3",
    provider="minimax",
    capabilities=["multimodal", "coding", "reasoning", "long_context", "agent", "writing", "chinese"],
    task_types=["concept", "outline_expand", "chapter_batch", "long_writing", "coding", "agent", "vision_analysis"],
    max_context_tokens=1000000,
    max_output_tokens=16384,
    quality_score=9.0,
    avg_latency_seconds=2.2,
    cost_per_1k_input_tokens=0.0042,
    cost_per_1k_output_tokens=0.0168,
    api_key_env="DASHSCOPE_API_KEY",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    default_timeout=300,
    supports_function_call=True,
    supports_thinking_mode=True,
    supports_vision=True,
    priority=2,
    fallback_models=["qwen3.7-plus"],
    default_params={"temperature": 0.7, "max_tokens": 16384, "thinking": {"type": "disabled"}},
    tags=["multimodal", "coding", "reasoning", "long_context", "agent", "chinese", "minimax", "alibaba", "open_source"],
)
class MiniMaxM3Adapter(OpenAICompatibleAdapter):
    """稀宇科技 MiniMax M3 适配器。经阿里云百炼 OpenAI 兼容接口接入，
    MSA 稀疏注意力架构，原生支持100万tokens超长上下文，
    原生多模态（文本/图像/视频输入），混合思考模式（thinking.type: adaptive/disabled）。"""

    pass


@register_llm_model(
    model_id="step-3.7-flash",
    name="Step 3.7 Flash",
    provider="stepfun",
    capabilities=["multimodal", "reasoning", "agent", "coding", "fast", "long_context", "web_search", "writing", "chinese"],
    task_types=["concept", "outline_expand", "chapter_batch", "long_writing", "coding", "agent", "vision_analysis", "web_search"],
    max_context_tokens=262144,
    max_output_tokens=16384,
    quality_score=8.8,
    avg_latency_seconds=1.2,
    cost_per_1k_input_tokens=0.00135,
    cost_per_1k_output_tokens=0.0081,
    api_key_env="STEP_API_KEY",
    base_url="https://api.stepfun.com/v1",
    default_timeout=300,
    supports_function_call=True,
    supports_thinking_mode=True,
    supports_vision=True,
    priority=3,
    fallback_models=["qwen3.7-plus"],
    default_params={"temperature": 0.7, "max_tokens": 16384, "reasoning_level": "medium"},
    tags=["multimodal", "reasoning", "agent", "coding", "fast", "long_context", "web_search", "chinese", "stepfun", "open_source"],
)
class Step37FlashAdapter(OpenAICompatibleAdapter):
    """阶跃星辰 Step 3.7 Flash 适配器。直接调用 StepFun 官方 OpenAI 兼容接口，
    198B 稀疏 MoE 架构（激活11B），最高生成速度400 tokens/s，
    原生多模态理解，三档推理强度可调（low/medium/high），思考过程通过 reasoning 字段返回。"""

    pass


@register_llm_model(
    model_id="mimo-v2.5-pro",
    name="MiMo V2.5 Pro",
    provider="xiaomi",
    capabilities=["reasoning", "agent", "coding", "long_context", "writing", "instruction_following", "chinese"],
    task_types=["concept", "outline_expand", "chapter_batch", "long_writing", "coding", "agent"],
    max_context_tokens=1000000,
    max_output_tokens=131072,
    quality_score=9.3,
    avg_latency_seconds=2.0,
    cost_per_1k_input_tokens=0.003,
    cost_per_1k_output_tokens=0.006,
    api_key_env="MIMO_API_KEY",
    base_url="https://api.xiaomimimo.com/v1",
    default_timeout=600,
    supports_function_call=True,
    supports_thinking_mode=True,
    supports_web_search=True,
    priority=1,
    fallback_models=["qwen3.7-plus"],
    default_params={"temperature": 0.7, "max_completion_tokens": 16384, "thinking": {"type": "disabled"}},
    tags=["reasoning", "agent", "coding", "long_context", "instruction_following", "chinese", "xiaomi", "flagship"],
)
class MiMoV25ProAdapter(OpenAICompatibleAdapter):
    """小米 MiMo V2.5 Pro 适配器。直接调用小米 MiMo 官方 OpenAI 兼容接口，
    万亿参数旗舰基座模型，原生支持1M tokens上下文与128K输出，
    主打极致Agent能力（SWE-bench/TAU-bench全面领先）与长程代码开发，
    可稳定完成近千轮工具调用的长程任务。纯文本输入输出。"""

    pass


@register_llm_model(
    model_id="mimo-v2.5",
    name="MiMo V2.5",
    provider="xiaomi",
    capabilities=["multimodal", "reasoning", "agent", "long_context", "web_search", "fast", "writing", "chinese"],
    task_types=["concept", "outline_expand", "chapter_batch", "long_writing", "coding", "agent", "vision_analysis", "audio_analysis", "web_search"],
    max_context_tokens=1000000,
    max_output_tokens=131072,
    quality_score=9.0,
    avg_latency_seconds=1.5,
    cost_per_1k_input_tokens=0.001,
    cost_per_1k_output_tokens=0.002,
    api_key_env="MIMO_API_KEY",
    base_url="https://api.xiaomimimo.com/v1",
    default_timeout=600,
    supports_function_call=True,
    supports_thinking_mode=True,
    supports_vision=True,
    supports_video_input=True,
    supports_audio_input=True,
    supports_web_search=True,
    priority=2,
    fallback_models=["qwen3.7-plus"],
    default_params={"temperature": 0.7, "max_completion_tokens": 16384, "thinking": {"type": "disabled"}},
    tags=["multimodal", "reasoning", "agent", "long_context", "fast", "web_search", "chinese", "xiaomi"],
)
class MiMoV25Adapter(OpenAICompatibleAdapter):
    """小米 MiMo V2.5 适配器。直接调用小米 MiMo 官方 OpenAI 兼容接口，
    原生全模态感知模型，支持图像、视频、音频、文本联合理解，
    原生支持1M tokens上下文与128K输出，具备强大的全模态Agent能力，
    位于性能与效率的Pareto前沿。仅支持文本输出。"""

    pass


@register_llm_model(
    model_id="doubao-seed-evolving",
    name="Doubao Seed Evolving",
    provider="volcengine",
    capabilities=["reasoning", "agent", "coding", "long_context", "writing", "chinese"],
    task_types=["concept", "outline_expand", "chapter_batch", "long_writing", "coding", "agent", "reasoning"],
    max_context_tokens=262144,
    max_output_tokens=16384,
    quality_score=9.3,
    avg_latency_seconds=2.5,
    cost_per_1k_input_tokens=0.006,
    cost_per_1k_output_tokens=0.03,
    api_key_env="DOUBAO_API_KEY",
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    default_timeout=300,
    supports_function_call=True,
    supports_thinking_mode=True,
    priority=2,
    fallback_models=["qwen3.7-plus"],
    default_params={"temperature": 0.7, "max_tokens": 16384, "thinking": {"type": "enabled"}},
    tags=["reasoning", "agent", "coding", "long_context", "writing", "chinese", "volcengine", "doubao", "evolving"],
)
class DoubaoSeedEvolvingAdapter(OpenAICompatibleAdapter):
    """火山引擎豆包 Seed Evolving 适配器。直接调用火山方舟 OpenAI 兼容接口，
    面向 Agent 与 Coding 场景设计的 Seed 系列深度思考模型，
    具备复杂任务编排、长程规划、代码生成与工具调用核心能力，
    采用动态迭代机制（每周至少一个版本更新），通过统一 Model ID 始终获取最新版本。"""

    pass


@register_llm_model(
    model_id="doubao-seed-character",
    name="Doubao Seed Character",
    provider="volcengine",
    capabilities=["roleplay", "dialogue", "multimodal", "reasoning", "instruction_following", "chinese"],
    task_types=["dialogue", "character", "character_expand", "chapter", "creative", "roleplay"],
    max_context_tokens=131072,
    max_output_tokens=32768,
    quality_score=8.8,
    avg_latency_seconds=1.5,
    cost_per_1k_input_tokens=0.0012,
    cost_per_1k_output_tokens=0.006,
    api_key_env="DOUBAO_API_KEY",
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    default_timeout=300,
    supports_function_call=True,
    supports_thinking_mode=True,
    supports_vision=True,
    priority=2,
    fallback_models=["qwen3.7-plus"],
    default_params={"request_model": "doubao-seed-character-260628", "temperature": 0.85, "max_tokens": 8192, "thinking": {"type": "disabled"}},
    tags=["roleplay", "dialogue", "multimodal", "reasoning", "instruction_following", "chinese", "volcengine", "doubao", "character"],
)
class DoubaoSeedCharacterAdapter(OpenAICompatibleAdapter):
    """火山引擎豆包 Seed Character 适配器。直接调用火山方舟 OpenAI 兼容接口，
    面向新一代虚拟陪伴与泛娱乐场景的角色扮演模型，
    角色扮演的剧情推理、对话节奏与情感递进能力显著增强，
    新增 Human-like 自然聊天、thinking 与 VLM 多模态理解（视频/图片/表情包）能力，
    可主动激活对话并贴合语境回复。"""

    pass


@register_llm_model(
    model_id="deepseek-v4-pro",
    name="DeepSeek V4 Pro",
    provider="deepseek",
    capabilities=["reasoning", "logic", "analysis", "planning"],
    task_types=["worldview", "character", "character_expand", "volume_detail_expand", "structure_plot", "review", "reasoning"],
    max_context_tokens=1000000,
    max_output_tokens=384000,
    quality_score=9.5,
    avg_latency_seconds=15.0,
    cost_per_1k_input_tokens=0.003,
    cost_per_1k_output_tokens=0.006,
    api_key_env="DEEPSEEK_API_KEY",
    base_url="https://api.deepseek.com",
    supports_streaming=False,
    supports_timeout_param=False,
    supports_max_retries=False,
    priority=1,
    fallback_models=["qwen3.7-plus"],
    default_params={
        "request_model": "deepseek-v4-pro",
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    },
    tags=["reasoning", "logic"],
)
class DeepSeekV4ProAdapter(OpenAICompatibleAdapter):
    """DeepSeek V4 Pro 适配器 - 深度推理模型"""

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> "LLMResult":
        """生成响应 - V4 Pro 特殊处理"""
        from schemas.unified_model_spec import LLMResult

        client = self._get_client_for_current_context()
        if not self._initialized or not client:
            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error="客户端未初始化",
                error_code="client_not_initialized"
            )

        start_time = time.time()

        try:
            effective_max_tokens = self._normalize_requested_max_tokens(max_tokens)

            params = self._build_completion_params(messages, temperature, effective_max_tokens, kwargs)
            params.pop("temperature", None)

            response = await client.chat.completions.create(**params)

            message = response.choices[0].message
            content = message.content or ""
            metadata = self._extract_reasoning_metadata(message)

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
                f"✅ DeepSeek V4 Pro调用成功 | 延迟: {latency:.2f}s | Tokens: {usage.get('total_tokens', 0)}"
            )

            return LLMResult(
                success=True,
                model_id=self.spec.id,
                content=content,
                usage=usage,
                latency=latency,
                cost=cost,
                metadata=metadata,
            )

        except Exception as e:
            latency = time.time() - start_time
            error_code = self._map_error_code(e)

            if error_code in {"network_error", "timeout"}:
                self._reset_current_context_client(reason=error_code)

            logger.error(f"❌ DeepSeek V4 Pro调用失败 | 错误码: {error_code} | 错误: {e}")

            logger.error(
                "DeepSeek V4 Pro调用失败补充信息 | 错误码: %s | 耗时: %.2fs | requested_max_tokens=%s | normalized_max_tokens=%s",
                error_code,
                latency,
                max_tokens,
                effective_max_tokens,
            )

            return LLMResult(
                success=False,
                model_id=self.spec.id,
                error=str(e),
                error_code=error_code,
                latency=latency,
            )


@register_llm_model(
    model_id="deepseek-v4-flash",
    name="DeepSeek V4 Flash",
    provider="deepseek",
    capabilities=["reasoning", "chat", "fast"],
    task_types=["chat", "rewrite", "fast", "ai_trace", "simple"],
    max_context_tokens=1000000,
    max_output_tokens=65536,
    quality_score=8.5,
    avg_latency_seconds=2.0,
    cost_per_1k_input_tokens=0.001,
    cost_per_1k_output_tokens=0.002,
    api_key_env="DEEPSEEK_API_KEY",
    base_url="https://api.deepseek.com",
    supports_streaming=True,
    supports_timeout_param=True,
    supports_max_retries=True,
    priority=2,
    fallback_models=["qwen3.7-plus"],
    default_params={
        "request_model": "deepseek-v4-flash",
        "thinking": {"type": "disabled"},
    },
    tags=["reasoning", "fast"],
)
class DeepSeekV4FlashAdapter(OpenAICompatibleAdapter):
    """DeepSeek V4 Flash 适配器 - 轻量快速推理模型"""

    pass
