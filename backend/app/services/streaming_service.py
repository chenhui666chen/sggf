"""
流式输出服务 - 支持 AI 生成内容的实时推送
"""
import os
import asyncio
from typing import Optional, Dict, Any, List, Callable, Awaitable
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class StreamingService:
    """
    流式输出服务
    
    将 AI 生成的内容实时推送到前端
    """
    
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        )
        self.default_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    
    async def generate_with_streaming(
        self,
        messages: List[Dict[str, str]],
        on_chunk: Callable[[str, int], Awaitable[None]],
        on_complete: Optional[Callable[[str, int], Awaitable[None]]] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        max_retries: int = 3,
    ) -> str:
        """
        流式生成内容并实时推送（带重试机制）
        
        Args:
            messages: 消息列表
            on_chunk: 每个文本块的回调函数 (chunk_text, chunk_index)
            on_complete: 生成完成时的回调函数 (full_text, total_chars)
            model: 使用的模型
            temperature: 温度参数
            max_tokens: 最大 token 数
            max_retries: 最大重试次数
        
        Returns:
            完整的生成文本
        """
        model = model or self.default_model
        last_error = None
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_time = 2 ** attempt  # 指数退避：2秒、4秒、8秒
                    logger.info(f"🔄 第 {attempt + 1}/{max_retries} 次重试，等待 {wait_time} 秒...")
                    await asyncio.sleep(wait_time)
                
                logger.info(f"🌊 开始流式生成 | 模型: {model} | 尝试: {attempt + 1}/{max_retries}")
                
                stream = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                    timeout=120.0,  # 🔧 添加120秒超时
                )
                
                full_content = ""
                chunk_index = 0
                buffer = ""  # 缓冲区，用于合并小块
                buffer_threshold = 10  # 每10个字符发送一次
                last_activity_time = asyncio.get_event_loop().time()
                
                async for chunk in stream:
                    last_activity_time = asyncio.get_event_loop().time()  # 更新活动时间
                    
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            content_piece = delta.content
                            full_content += content_piece
                            buffer += content_piece
                            
                            # 当缓冲区达到阈值或遇到换行时发送
                            if len(buffer) >= buffer_threshold or '\n' in buffer:
                                try:
                                    await on_chunk(buffer, chunk_index)
                                    chunk_index += 1
                                    buffer = ""
                                except Exception as e:
                                    logger.warning(f"⚠️  推送块失败: {e}")
                
                # 发送剩余的缓冲区内容
                if buffer:
                    try:
                        await on_chunk(buffer, chunk_index)
                    except Exception as e:
                        logger.warning(f"⚠️  推送最后一块失败: {e}")
                
                # 🔧 检查是否生成了足够的内容（至少100字符）
                if len(full_content) < 100:
                    logger.warning(f"⚠️  生成内容过短 ({len(full_content)} 字符)，可能被截断")
                    # 如果内容太短，不抛出异常，但记录警告
                    # 继续执行，返回已生成的内容
                
                # 调用完成回调
                if on_complete:
                    try:
                        await on_complete(full_content, len(full_content))
                    except Exception as e:
                        logger.warning(f"⚠️  完成回调失败: {e}")
                
                logger.info(f"✅ 流式生成完成 | 总字符: {len(full_content)} | 块数: {chunk_index + 1}")
                return full_content
                
            except Exception as e:
                last_error = e
                error_msg = str(e)
                
                # 判断是否是可重试的错误
                is_retryable = (
                    'RemoteProtocolError' in error_msg or
                    'peer closed connection' in error_msg or
                    'incomplete chunked read' in error_msg or
                    'Connection reset' in error_msg or
                    'timeout' in error_msg.lower()
                )
                
                if is_retryable and attempt < max_retries - 1:
                    logger.warning(f"⚠️  流式生成中断（可重试）: {error_msg}")
                    logger.info(f"🔄 将在 {2 ** (attempt + 1)} 秒后重试...")
                    continue  # 继续下一次重试
                else:
                    logger.error(f"❌ 流式生成失败（不可重试或已达最大重试次数）: {error_msg}")
                    raise
        
        # 如果所有重试都失败了
        logger.error(f"❌ 流式生成失败，已重试 {max_retries} 次")
        raise last_error if last_error else Exception("流式生成失败")
    
    async def generate_chapter_streaming(
        self,
        prompt: str,
        system_prompt: str,
        on_chunk: Callable[[str, int], Awaitable[None]],
        on_complete: Optional[Callable[[str, int], Awaitable[None]]] = None,
        temperature: float = 0.7,
    ) -> str:
        """
        流式生成章节内容
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            on_chunk: 块回调
            on_complete: 完成回调
            temperature: 温度
        
        Returns:
            完整的章节内容
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        return await self.generate_with_streaming(
            messages=messages,
            on_chunk=on_chunk,
            on_complete=on_complete,
            temperature=temperature,
        )


# 单例实例
_streaming_service: Optional[StreamingService] = None


def get_streaming_service() -> StreamingService:
    """获取流式输出服务单例"""
    global _streaming_service
    if _streaming_service is None:
        _streaming_service = StreamingService()
    return _streaming_service

