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
from typing import Dict, Set, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SSEProgressTracker:
    """SSE 进度追踪器"""

    def __init__(self):
        self._clients: Dict[str, Set[asyncio.Queue]] = {}
        self._heartbeats: Dict[str, float] = {}

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

    async def broadcast_progress(self, task_id: str, data: dict):
        """广播进度到所有监听该任务的客户端"""
        if task_id not in self._clients:
            return

        event = {
            "event": "progress",
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

        message = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        disconnected = set()
        for queue in self._clients[task_id]:
            try:
                await queue.put(message)
            except Exception as e:
                logger.error(f"❌ SSE 推送失败: {e}")
                disconnected.add(queue)

        # 清理断开连接的客户端
        for queue in disconnected:
            self._clients[task_id].discard(queue)

    async def send_heartbeat(self, task_id: str):
        """发送心跳"""
        if task_id not in self._clients:
            return

        event = {
            "event": "heartbeat",
            "data": {"timestamp": datetime.now().isoformat()},
        }
        message = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        for queue in self._clients.get(task_id, set()):
            try:
                await queue.put(message)
            except:
                pass

    async def stream_events(self, task_id: str):
        """生成 SSE 事件流"""
        queue = self.register_client(task_id)

        try:
            # 发送初始连接事件
            yield f"data: {json.dumps({'event': 'connected', 'data': {'task_id': task_id}}, ensure_ascii=False)}\n\n"

            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30)
                    yield message
                except asyncio.TimeoutError:
                    # 发送心跳
                    await self.send_heartbeat(task_id)
                    yield f"data: {json.dumps({'event': 'heartbeat', 'data': {}}, ensure_ascii=False)}\n\n"
        finally:
            self.unregister_client(task_id, queue)


# 全局实例
sse_tracker = SSEProgressTracker()


def create_progress_handler(task_id: str):
    """创建兼容现有系统的进度回调处理函数"""
    import asyncio

    def sync_progress_handler(stage: str, progress: float, detail: Optional[dict] = None):
        """同步进度处理器（用于 Celery 任务）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    sse_tracker.broadcast_progress(task_id, {
                        "stage": stage,
                        "progress": progress,
                        "detail": detail or {},
                    })
                )
            else:
                # 如果没有运行中的事件循环，创建一个
                loop.run_until_complete(
                    sse_tracker.broadcast_progress(task_id, {
                        "stage": stage,
                        "progress": progress,
                        "detail": detail or {},
                    })
                )
        except Exception as e:
            logger.error(f"❌ 进度推送异常: {e}")

    return sync_progress_handler
