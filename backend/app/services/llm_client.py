"""
LLM 客户端 - 集成模型优化器
支持流式响应 (Streaming)
"""
import os
import hashlib
import json
from typing import Optional, List, Dict, Any, AsyncGenerator, Callable, Awaitable
import logging
import httpx
from openai import AsyncOpenAI

from app.services.model_optimizer import get_model_optimizer, TaskType

logger = logging.getLogger(__name__)

# 🛡️ 全局禁用代理配置 - 确保直连API
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    if proxy_var in os.environ:
        del os.environ[proxy_var]

# 流式输出回调类型定义
StreamCallback = Callable[[str], Awaitable[None]]

# 🚀 方案3：导入缓存系统
get_cache_system = None  # 提前声明，避免可能未绑定的变量错误
try:
    from app.services.cache_system import get_cache_system
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    logger.warning("⚠️ 缓存系统不可用")


class OptimizedLLMClient:
    """
    优化的 LLM 客户端
    
    自动根据任务类型选择最优模型
    """
    
    def __init__(self, strategy: str = "conservative", enable_cache: bool = True):
        """
        初始化客户端
        
        Args:
            strategy: 优化策略（conservative/aggressive/dynamic/default）
            enable_cache: 是否启用缓存
        """
        # 🛡️ 创建禁用代理的httpx客户端
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=30.0),
            trust_env=False  # 不读取环境变量中的代理配置
        )
        
        self.client = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
            timeout=120.0,
            http_client=http_client  # 🛡️ 使用禁用代理的客户端
        )
        
        self.optimizer = get_model_optimizer(strategy)
        self.default_model = os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner")
        
        # 🚀 方案3：初始化缓存系统
        self.cache_enabled = enable_cache and CACHE_AVAILABLE
        if self.cache_enabled and get_cache_system is not None:
            self.cache = get_cache_system(enable_memory=True, enable_redis=False)
            logger.info("✅ LLM 响应缓存已启用")
        else:
            self.cache = None
        
        logger.info(f"✅ LLM 客户端已初始化，优化策略: {strategy}")
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        task_type: Optional[TaskType] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        use_cache: bool = True,
        **kwargs
    ) -> str:
        """
        调用 LLM API（支持缓存）
        
        Args:
            messages: 消息列表
            task_type: 任务类型（用于自动选择模型）
            model: 指定模型（优先级高于自动选择）
            temperature: 温度参数
            max_tokens: 最大token数
            use_cache: 是否使用缓存（默认True）
            **kwargs: 其他参数
        
        Returns:
            生成的文本
        """
        # 选择模型
        if model is None:
            if task_type is not None:
                model = self.optimizer.select_model(task_type)
                logger.info(f"🎯 任务 {task_type.value} 使用模型: {model}")
            else:
                model = self.default_model
                logger.warning("⚠️  未指定任务类型，使用默认模型")
        
        # 🚀 方案3：尝试从缓存获取
        cache_key = None
        if self.cache_enabled and use_cache and temperature < 0.3:
            # 只缓存低温度的请求（确定性较强）
            cache_key = json.dumps({
                "model": model,
                "messages": messages,
                "temperature": temperature
            }, sort_keys=True)
            
            cached = await self.cache.get("llm_response", cache_key)  # type: ignore[union-attr]
            if cached:
                logger.info("⚡ LLM 响应缓存命中")
                return cached
        
        try:
            # 调用 API
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            
            content = response.choices[0].message.content
            
            # 🚀 方案3：缓存响应
            if cache_key and self.cache_enabled and use_cache:
                await self.cache.set("llm_response", cache_key, content, ttl=600)  # type: ignore[union-attr]
            
            # 日志
            logger.info(
                f"✅ LLM调用成功 | 模型: {model} | "
                f"输入: {len(str(messages))} chars | "
                f"输出: {len(content)} chars"
            )

            return content

        except Exception as e:
            logger.error(f"❌ LLM调用失败: {e}")
            raise

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        on_chunk: Optional[StreamCallback] = None,
        task_type: Optional[TaskType] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        🆕 流式调用 LLM API（支持实时回调）

        Args:
            messages: 消息列表
            on_chunk: 每个文本块的回调函数
            task_type: 任务类型（用于自动选择模型）
            model: 指定模型（优先级高于自动选择）
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Returns:
            完整的生成文本
        """
        # 选择模型
        if model is None:
            if task_type is not None:
                model = self.optimizer.select_model(task_type)
                logger.info(f"🎯 任务 {task_type.value} 使用模型: {model}")
            else:
                model = self.default_model

        try:
            # 🔥 关键：启用流式响应
            stream = await self.client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,  # 启用流式输出
                **kwargs
            )

            full_content = ""
            chunk_count = 0

            # 逐块处理响应
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        content_piece = delta.content
                        full_content += content_piece
                        chunk_count += 1

                        # 调用回调函数推送内容块
                        if on_chunk:
                            try:
                                await on_chunk(content_piece)
                            except Exception as e:
                                logger.warning(f"⚠️  流式回调失败: {e}")

            logger.info(
                f"✅ LLM流式调用成功 | 模型: {model} | "
                f"块数: {chunk_count} | "
                f"输出: {len(full_content)} chars"
            )

            return full_content

        except Exception as e:
            logger.error(f"❌ LLM流式调用失败: {e}")
            raise

    async def chat_stream_generator(
        self,
        messages: List[Dict[str, str]],
        task_type: Optional[TaskType] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        🆕 流式生成器版本（返回 AsyncGenerator）

        用于需要更细粒度控制的场景

        Yields:
            每个文本块
        """
        # 选择模型
        if model is None:
            if task_type is not None:
                model = self.optimizer.select_model(task_type)
            else:
                model = self.default_model

        try:
            stream = await self.client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **kwargs
            )

            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content

        except Exception as e:
            logger.error(f"❌ LLM流式生成器调用失败: {e}")
            raise


# 全局客户端实例
_client: Optional[OptimizedLLMClient] = None


def get_llm_client(strategy: str = "conservative") -> OptimizedLLMClient:
    """
    获取 LLM 客户端单例

    Args:
        strategy: 优化策略

    Returns:
        OptimizedLLMClient实例
    """
    global _client
    if _client is None:
        _client = OptimizedLLMClient(strategy=strategy)
    return _client
