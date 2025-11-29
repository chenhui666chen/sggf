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
    ) -> str:
        """
        流式生成内容并实时推送
        
        Args:
            messages: 消息列表
            on_chunk: 每个文本块的回调函数 (chunk_text, chunk_index)
            on_complete: 生成完成时的回调函数 (full_text, total_chars)
            model: 使用的模型
            temperature: 温度参数
            max_tokens: 最大 token 数
        
        Returns:
            完整的生成文本
        """
        model = model or self.default_model
        
        try:
            logger.info(f"🌊 开始流式生成 | 模型: {model}")
            
            stream = await self.client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            
            full_content = ""
            chunk_index = 0
            buffer = ""  # 缓冲区，用于合并小块
            buffer_threshold = 10  # 每10个字符发送一次
            
            async for chunk in stream:
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
            
            # 调用完成回调
            if on_complete:
                try:
                    await on_complete(full_content, len(full_content))
                except Exception as e:
                    logger.warning(f"⚠️  完成回调失败: {e}")
            
            logger.info(f"✅ 流式生成完成 | 总字符: {len(full_content)} | 块数: {chunk_index + 1}")
            return full_content
            
        except Exception as e:
            logger.error(f"❌ 流式生成失败: {e}")
            raise
    
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

