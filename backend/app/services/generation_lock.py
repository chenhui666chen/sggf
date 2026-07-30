"""项目章节生成锁服务

基于 Redis SET NX + token + TTL 实现跨进程/跨实例的项目级生成互斥，
防止同一项目并发生成拿到相同章节号、重复落库与重复扣额。

故障策略（fail closed 分档）：
- Redis 可用：所有档位走 Redis 锁
- Redis 不可用：标准档回退进程内互斥（尽力而为）并告警；
  免费档由调用方决定拒绝（allow_local_fallback=False 时抛 LockServiceUnavailableError）
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger("uvicorn.error")

LOCK_KEY_PREFIX = "inspiration_ark:chapter_gen_lock:"
DEFAULT_LOCK_TTL_SECONDS = 30 * 60  # 略大于单章生成最长耗时

# 比对 token 后删除，避免误删其他任务续租后的锁
_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""

_RENEW_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
else
    return 0
end
"""


class LockServiceUnavailableError(RuntimeError):
    """Redis 锁服务不可用（免费档 fail closed 场景使用）。"""


@dataclass(frozen=True)
class LockHandle:
    """已获取的项目生成锁句柄，释放时必须原样传回。"""

    project_id: int
    token: str
    backend: str  # "redis" | "local"


class ChapterGenerationLockService:
    """项目章节生成锁（Redis 优先，进程内互斥兜底）。"""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or str(settings.REDIS_URL).strip()
        self._redis_client = None
        # 进程内兜底锁存储：project_id -> (token, 过期时间戳)
        self._local_locks: Dict[int, Tuple[str, float]] = {}
        self._local_mutex = threading.Lock()

    async def _get_redis_client(self):
        """惰性建立 Redis 连接；失败抛出异常由调用方分档处理。"""
        if self._redis_client is not None:
            return self._redis_client
        import redis.asyncio as redis

        client = redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await client.ping()
        self._redis_client = client
        return client

    @staticmethod
    def _lock_key(project_id: int) -> str:
        return f"{LOCK_KEY_PREFIX}{project_id}"

    def _acquire_local(self, project_id: int, ttl_seconds: int) -> Optional[LockHandle]:
        """进程内兜底互斥（标准档 Redis 故障时尽力而为）。"""
        now = time.monotonic()
        with self._local_mutex:
            existing = self._local_locks.get(project_id)
            if existing and existing[1] > now:
                return None
            token = str(uuid.uuid4())
            self._local_locks[project_id] = (token, now + ttl_seconds)
            return LockHandle(project_id=project_id, token=token, backend="local")

    def _release_local(self, handle: LockHandle) -> bool:
        with self._local_mutex:
            existing = self._local_locks.get(handle.project_id)
            if existing and existing[0] == handle.token:
                del self._local_locks[handle.project_id]
                return True
            return False

    async def acquire(
        self,
        project_id: int,
        *,
        allow_local_fallback: bool,
        ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    ) -> Optional[LockHandle]:
        """获取项目生成锁。

        Returns:
            LockHandle: 获取成功
            None: 锁已被其他生成任务持有（调用方返回 409）

        Raises:
            LockServiceUnavailableError: Redis 不可用且不允许本地兜底（免费档 503）
        """
        token = str(uuid.uuid4())
        try:
            client = await self._get_redis_client()
            acquired = await client.set(
                self._lock_key(project_id),
                token,
                nx=True,
                ex=ttl_seconds,
            )
            if acquired:
                return LockHandle(project_id=project_id, token=token, backend="redis")
            return None
        except Exception as exc:
            # Redis 故障：重置连接以便下次重建
            self._redis_client = None
            if not allow_local_fallback:
                logger.error(f"❌ 项目生成锁 Redis 不可用（免费档拒绝生成）: {exc}")
                raise LockServiceUnavailableError(str(exc)) from exc
            logger.warning(f"⚠️ 项目生成锁 Redis 不可用，标准档回退进程内互斥: {exc}")
            return self._acquire_local(project_id, ttl_seconds)

    async def release(self, handle: Optional[LockHandle]) -> bool:
        """按 token 释放锁（幂等，释放失败仅告警，靠 TTL 兜底）。"""
        if handle is None:
            return False

        if handle.backend == "local":
            return self._release_local(handle)
        try:
            client = await self._get_redis_client()
            released = await client.eval(
                _RELEASE_LUA, 1, self._lock_key(handle.project_id), handle.token
            )
            return bool(released)
        except Exception as exc:
            self._redis_client = None
            logger.warning("release project lock failed for %s: %s", handle.project_id, exc)
            return False

    async def renew(
        self,
        handle: Optional[LockHandle],
        *,
        ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    ) -> bool:
        """Extend a lock only while the caller still owns its token."""
        if handle is None:
            return False
        if handle.backend == "local":
            now = time.monotonic()
            with self._local_mutex:
                existing = self._local_locks.get(handle.project_id)
                if not existing or existing[0] != handle.token:
                    return False
                self._local_locks[handle.project_id] = (handle.token, now + ttl_seconds)
                return True
        try:
            client = await self._get_redis_client()
            renewed = await client.eval(
                _RENEW_LUA,
                1,
                self._lock_key(handle.project_id),
                handle.token,
                str(ttl_seconds),
            )
            return bool(renewed)
        except Exception as exc:
            self._redis_client = None
            logger.warning("续租项目 %s 生成锁失败: %s", handle.project_id, exc)
            return False
        if handle.backend == "local":
            return self._release_local(handle)
        try:
            client = await self._get_redis_client()
            released = await client.eval(
                _RELEASE_LUA, 1, self._lock_key(handle.project_id), handle.token
            )
            return bool(released)
        except Exception as exc:
            self._redis_client = None
            logger.warning(
                f"⚠️ 释放项目 {handle.project_id} 生成锁失败（将由 TTL 兜底过期）: {exc}"
            )
            return False


_lock_service: Optional[ChapterGenerationLockService] = None


def get_generation_lock_service() -> ChapterGenerationLockService:
    global _lock_service
    if _lock_service is None:
        _lock_service = ChapterGenerationLockService()
    return _lock_service
