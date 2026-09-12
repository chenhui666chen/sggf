"""事件循环绑定的 Redis 异步客户端管理器。

背景：`redis.asyncio` 客户端在首次使用时会绑定到**当前事件循环**。
若把客户端缓存在模块级单例里（原各 service 的 `self._redis_client`），
在"每请求新建事件循环"的测试环境（及任何多事件循环环境）中，第二个请求
在新循环里复用旧客户端会抛 `RuntimeError: Event loop is closed`，
被 fail-closed 逻辑翻译成 503（认证服务暂时不可用）。

方案：按事件循环弱引用缓存（WeakKeyDictionary keyed by loop）。
- 生产（uvicorn 单事件循环）：每次请求 loop 相同 → 命中同一客户端，行为不变；
- 测试（每请求新循环）：每个循环独立客户端，旧循环及其连接随 GC 释放。
"""
from __future__ import annotations

import asyncio
import weakref
from typing import Any

import redis.asyncio as redis


class LoopBoundRedis:
    def __init__(self, url: str):
        self._url = url
        self._clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any] = (
            weakref.WeakKeyDictionary()
        )

    async def get(self) -> Any:
        """返回绑定当前事件循环的客户端；不存在则创建并缓存。"""
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is not None:
            return client
        client = redis.from_url(
            self._url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1.0,
        )
        await client.ping()
        self._clients[loop] = client
        return client

    def invalidate(self) -> None:
        """使当前事件循环的客户端失效（fail-closed 后下次调用按新连接重建）。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._clients.pop(loop, None)
