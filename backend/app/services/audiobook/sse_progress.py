"""
SSE (Server-Sent Events) 进度推送服务

替代传统的 Celery 轮询方式，提供实时进度更新。
参考 TextAudio 的 SSE 实现。

功能：
1. 注册/注销客户端连接
2. 广播进度事件
3. 心跳保活
"""
import asyncio
import json
import logging
import uuid
from contextlib import suppress
from datetime import datetime
from typing import Any, Dict, Optional, Set

from app.core.config import settings

logger = logging.getLogger(__name__)

REDIS_CHANNEL_PREFIX = "audiobook:sse:task:"


def _format_sse_message(event: Dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


class SSEProgressTracker:
    """SSE 进度追踪器"""

    def __init__(self):
        self._clients: Dict[str, Set[asyncio.Queue]] = {}
        self._heartbeats: Dict[str, float] = {}
        self._origin_id = uuid.uuid4().hex
        self._redis_publish_client = None
        self._redis_checked = False
        self._redis_available = False

    def register_client(self, task_id: str) -> asyncio.Queue:
        """注册客户端到指定任务"""
        if task_id not in self._clients:
            self._clients[task_id] = set()

        queue: asyncio.Queue = asyncio.Queue()
        self._clients[task_id].add(queue)
        self._heartbeats[task_id] = datetime.now().timestamp()

        logger.info(f"📡 SSE 客户端注册: task_id={task_id}")
        return queue

    def unregister_client(self, task_id: str, queue: asyncio.Queue):
        """注销客户端"""
        if task_id in self._clients:
            self._clients[task_id].discard(queue)
            if not self._clients[task_id]:
                del self._clients[task_id]
                if task_id in self._heartbeats:
                    del self._heartbeats[task_id]

        logger.info(f"📡 SSE 客户端注销: task_id={task_id}")

    @staticmethod
    def _redis_channel(task_id: str) -> str:
        return f"{REDIS_CHANNEL_PREFIX}{task_id}"

    def _build_progress_event(self, data: dict) -> Dict[str, Any]:
        return {
            "event": "progress",
            "data": data,
            "timestamp": datetime.now().isoformat(),
            "origin": self._origin_id,
        }

    async def _get_redis_publish_client(self):
        if self._redis_checked and not self._redis_available:
            return None
        if self._redis_checked and self._redis_publish_client is not None:
            return self._redis_publish_client

        self._redis_checked = True
        redis_url = str(getattr(settings, "REDIS_URL", "") or "").strip()
        if not redis_url:
            return None

        try:
            import redis.asyncio as redis

            client = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
            await client.ping()
            self._redis_publish_client = client
            self._redis_available = True
            logger.info("Audiobook SSE Redis pub/sub enabled: %s", redis_url)
        except Exception as exc:  # noqa: BLE001
            self._redis_publish_client = None
            self._redis_available = False
            logger.warning("Audiobook SSE Redis unavailable, using process-local queues: %s", exc)

        return self._redis_publish_client

    def _publish_event_to_redis_sync(self, task_id: str, event: Dict[str, Any]) -> None:
        if self._redis_checked and not self._redis_available:
            return

        redis_url = str(getattr(settings, "REDIS_URL", "") or "").strip()
        if not redis_url:
            self._redis_checked = True
            self._redis_available = False
            return

        client = None
        try:
            import redis

            client = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
            client.publish(self._redis_channel(task_id), json.dumps(event, ensure_ascii=False))
            self._redis_checked = True
            self._redis_available = True
        except Exception as exc:  # noqa: BLE001
            self._redis_checked = True
            self._redis_available = False
            logger.warning("Audiobook SSE Redis sync publish unavailable: %s", exc)
        finally:
            if client is not None:
                with suppress(Exception):
                    client.close()

    async def _create_redis_subscriber(self):
        redis_url = str(getattr(settings, "REDIS_URL", "") or "").strip()
        if not redis_url:
            return None

        try:
            import redis.asyncio as redis

            client = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
            await client.ping()
            return client
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audiobook SSE Redis subscriber unavailable: %s", exc)
            return None

    async def _broadcast_event_to_local_clients(self, task_id: str, event: Dict[str, Any]) -> None:
        if task_id not in self._clients:
            return

        message = _format_sse_message(event)
        disconnected = set()
        for queue in list(self._clients.get(task_id, set())):
            try:
                await queue.put(message)
            except Exception as e:
                logger.error(f"❌ SSE 推送失败: {e}")
                disconnected.add(queue)

        # 清理断开连接的客户端
        for queue in disconnected:
            self._clients[task_id].discard(queue)

    async def _publish_event_to_redis(self, task_id: str, event: Dict[str, Any]) -> None:
        client = await self._get_redis_publish_client()
        if client is None:
            return

        try:
            await client.publish(self._redis_channel(task_id), json.dumps(event, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audiobook SSE Redis publish failed: %s", exc)

    async def _forward_redis_events(self, task_id: str, queue: asyncio.Queue) -> None:
        client = await self._create_redis_subscriber()
        if client is None:
            return

        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(self._redis_channel(task_id))
            async for raw_message in pubsub.listen():
                if raw_message.get("type") != "message":
                    continue
                try:
                    event = json.loads(raw_message.get("data") or "{}")
                except Exception:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("origin") == self._origin_id:
                    continue
                await queue.put(_format_sse_message(event))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audiobook SSE Redis subscribe failed: %s", exc)
        finally:
            with suppress(Exception):
                await pubsub.unsubscribe(self._redis_channel(task_id))
            with suppress(Exception):
                await pubsub.close()
            with suppress(Exception):
                await client.close()

    async def broadcast_progress(self, task_id: str, data: dict):
        """广播进度到所有监听该任务的客户端"""
        event = self._build_progress_event(data)

        await self._broadcast_event_to_local_clients(task_id, event)
        await self._publish_event_to_redis(task_id, event)

    def emit_progress(self, task_id: Optional[str], data: dict):
        """从同步任务代码中安全触发 SSE 进度事件。"""
        if not task_id:
            return
        event = self._build_progress_event(data)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._publish_event_to_redis_sync(task_id, event)
            return

        async def emit_event() -> None:
            await self._broadcast_event_to_local_clients(task_id, event)
            await self._publish_event_to_redis(task_id, event)

        loop.create_task(emit_event())

    async def send_heartbeat(self, task_id: str):
        """发送心跳"""
        if task_id not in self._clients:
            return

        event = {
            "event": "heartbeat",
            "data": {"timestamp": datetime.now().isoformat()},
            "timestamp": datetime.now().isoformat(),
            "origin": self._origin_id,
        }
        await self._broadcast_event_to_local_clients(task_id, event)

    async def stream_events(self, task_id: str):
        """生成 SSE 事件流"""
        queue = self.register_client(task_id)
        redis_task = asyncio.create_task(self._forward_redis_events(task_id, queue))

        try:
            # 发送初始连接事件
            yield _format_sse_message({'event': 'connected', 'data': {'task_id': task_id}})

            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30)
                    yield message
                except asyncio.TimeoutError:
                    # 发送心跳
                    event = {
                        "event": "heartbeat",
                        "data": {"timestamp": datetime.now().isoformat()},
                        "timestamp": datetime.now().isoformat(),
                        "origin": self._origin_id,
                    }
                    yield _format_sse_message(event)
        finally:
            redis_task.cancel()
            with suppress(asyncio.CancelledError):
                await redis_task
            self.unregister_client(task_id, queue)


# 全局实例
sse_tracker = SSEProgressTracker()


def create_progress_handler(task_id: str):
    """创建兼容现有系统的进度回调处理函数"""
    def sync_progress_handler(stage: str, progress: float, detail: Optional[dict] = None):
        """同步进度处理器（用于 Celery 任务）"""
        sse_tracker.emit_progress(
            task_id,
            {
                "stage": stage,
                "progress": progress,
                "detail": detail or {},
            },
        )

    return sync_progress_handler
