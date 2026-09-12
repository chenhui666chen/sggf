"""项目章节生成锁测试（步骤4：Redis SET NX + token + TTL）

覆盖：
- A组：Redis 路径——互斥、token 校验释放、并发只放行一个、不同项目互不影响
- B组：故障策略——免费档 fail closed 抛错、标准档回退进程内互斥、本地锁过期与释放
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("DEBUG", "false")

from app.services.generation_lock import (  # noqa: E402
    ChapterGenerationLockService,
    LockHandle,
    LockServiceUnavailableError,
)


class FakeRedis:
    """最小化模拟 SET NX / EVAL(compare-del) / EVAL(ttl-check-del) 语义。"""

    def __init__(self):
        self.store = {}
        self.ttls = {}

    async def ping(self):
        return True

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def eval(self, script, numkeys, key, token, *args):
        # 强制释放：无条件删除
        if "DEL" in script and "TTL" not in script and "GET" not in script:
            if key in self.store:
                del self.store[key]
                self.ttls.pop(key, None)
                return 1
            return 0
        # 残留锁回收脚本：TTL 处于 (0, threshold) 才删除
        if "TTL" in script and "DEL" in script:
            ttl = self.ttls.get(key)
            if key in self.store and ttl is not None and 0 < ttl < int(token):
                del self.store[key]
                return 1
            return 0
        if self.store.get(key) == token:
            if "EXPIRE" in script:
                self.ttls[key] = int(args[0])
                return 1
            del self.store[key]
            return 1
        return 0


class _FakeRedisManager:
    """替代 LoopBoundRedis 的测试桩：get() 恒返回注入的假客户端（同 test_auth_routes）。"""

    def __init__(self, client):
        self._client = client

    async def get(self):
        return self._client

    def invalidate(self) -> None:
        pass


def make_redis_service() -> ChapterGenerationLockService:
    service = ChapterGenerationLockService(redis_url="redis://fake:6379/0")
    fake = FakeRedis()
    service._redis = _FakeRedisManager(fake)
    service._fake_redis = fake
    return service


def make_broken_service() -> ChapterGenerationLockService:
    service = ChapterGenerationLockService(redis_url="redis://fake:6379/0")

    async def _always_fail():
        raise ConnectionError("redis down")

    service._get_redis_client = _always_fail  # type: ignore[method-assign]
    return service


# ============ A组：Redis 路径 ============


def test_acquire_and_mutual_exclusion():
    """同项目二次获取被拒；释放后可重新获取。"""

    async def run():
        service = make_redis_service()
        handle = await service.acquire(1, allow_local_fallback=True)
        assert isinstance(handle, LockHandle)
        assert handle.backend == "redis"

        # 同项目再取 → None（互斥）
        second = await service.acquire(1, allow_local_fallback=True)
        assert second is None

        # 释放后可重新获取
        assert await service.release(handle) is True
        third = await service.acquire(1, allow_local_fallback=True)
        assert third is not None

    asyncio.run(run())


def test_release_requires_matching_token():
    """token 不匹配不得误删他人持有的锁。"""

    async def run():
        service = make_redis_service()
        handle = await service.acquire(7, allow_local_fallback=True)
        assert handle is not None

        fake_handle = LockHandle(project_id=7, token="wrong-token", backend="redis")
        assert await service.release(fake_handle) is False
        # 锁仍被持有
        assert await service.acquire(7, allow_local_fallback=True) is None
        # 正确 token 可释放
        assert await service.release(handle) is True

    asyncio.run(run())


def test_concurrent_acquire_only_one_wins():
    """并发 2 个请求同项目只放行 1 个（验收标准）。"""

    async def run():
        service = make_redis_service()
        r1, r2 = await asyncio.gather(
            service.acquire(3, allow_local_fallback=True),
            service.acquire(3, allow_local_fallback=True),
        )
        results = [r1, r2]
        assert sum(1 for r in results if r is not None) == 1
        assert sum(1 for r in results if r is None) == 1

    asyncio.run(run())


def test_cross_worker_mutual_exclusion():
    """跨 worker 互斥（上线门槛第3条）：两个独立 service 实例共享同一 Redis，
    模拟不同 uvicorn worker 进程，互斥必须依赖 Redis 而非进程内状态。"""

    async def run():
        shared_redis = FakeRedis()
        worker_a = ChapterGenerationLockService(redis_url="redis://fake:6379/0")
        worker_a._redis = _FakeRedisManager(shared_redis)
        worker_b = ChapterGenerationLockService(redis_url="redis://fake:6379/0")
        worker_b._redis = _FakeRedisManager(shared_redis)

        # worker A 持锁期间，worker B 获取同项目锁被拒
        handle_a = await worker_a.acquire(9, allow_local_fallback=True)
        assert handle_a is not None and handle_a.backend == "redis"
        assert await worker_b.acquire(9, allow_local_fallback=True) is None

        # 两个 worker 并发抢不同实例，仍只放行一个
        r1, r2 = await asyncio.gather(
            worker_a.acquire(10, allow_local_fallback=True),
            worker_b.acquire(10, allow_local_fallback=True),
        )
        assert sum(1 for r in (r1, r2) if r is not None) == 1

        # worker A 释放后，worker B 可获取
        assert await worker_a.release(handle_a) is True
        handle_b = await worker_b.acquire(9, allow_local_fallback=True)
        assert handle_b is not None

    asyncio.run(run())


def test_different_projects_do_not_block_each_other():
    async def run():
        service = make_redis_service()
        h1 = await service.acquire(1, allow_local_fallback=True)
        h2 = await service.acquire(2, allow_local_fallback=True)
        assert h1 is not None and h2 is not None

    asyncio.run(run())


def test_lock_key_has_ttl():
    """锁必须带 TTL，防止进程被杀后永久死锁。"""

    async def run():
        service = make_redis_service()
        handle = await service.acquire(9, allow_local_fallback=True, ttl_seconds=1800)
        assert handle is not None
        fake = service._fake_redis
        key = f"inspiration_ark:chapter_gen_lock:9"
        assert fake.ttls.get(key) == 1800

    asyncio.run(run())


def test_release_none_handle_is_noop():
    async def run():
        service = make_redis_service()
        assert await service.release(None) is False

    asyncio.run(run())


def test_renew_extends_only_matching_redis_lock():
    async def run():
        service = make_redis_service()
        handle = await service.acquire(12, allow_local_fallback=False, ttl_seconds=30)
        assert handle is not None
        assert await service.renew(handle, ttl_seconds=90) is True
        key = "inspiration_ark:chapter_gen_lock:12"
        assert service._fake_redis.ttls[key] == 90

        wrong = LockHandle(project_id=12, token="wrong", backend="redis")
        assert await service.renew(wrong, ttl_seconds=120) is False
        assert service._fake_redis.ttls[key] == 90

    asyncio.run(run())


# ============ B组：故障策略 ============


def test_redis_down_free_tier_fail_closed():
    """Redis 不可用且不允许本地兜底（免费档）→ 抛 LockServiceUnavailableError。"""

    async def run():
        service = make_broken_service()
        with pytest.raises(LockServiceUnavailableError):
            await service.acquire(1, allow_local_fallback=False)

    asyncio.run(run())


def test_redis_down_standard_tier_local_fallback():
    """Redis 不可用时标准档回退进程内互斥，语义仍正确。"""

    async def run():
        service = make_broken_service()
        handle = await service.acquire(5, allow_local_fallback=True)
        assert handle is not None
        assert handle.backend == "local"

        # 同项目二次获取被拒
        second = await service.acquire(5, allow_local_fallback=True)
        assert second is None

        # token 不匹配不能释放
        fake_handle = LockHandle(project_id=5, token="wrong", backend="local")
        assert await service.release(fake_handle) is False
        assert await service.acquire(5, allow_local_fallback=True) is None

        # 正确释放后可重新获取
        assert await service.release(handle) is True
        third = await service.acquire(5, allow_local_fallback=True)
        assert third is not None

    asyncio.run(run())


def test_local_lock_expires_by_ttl():
    """本地兜底锁过期后可被重新获取（TTL 兜底语义）。"""

    async def run():
        service = make_broken_service()
        handle = await service.acquire(8, allow_local_fallback=True)
        assert handle is not None and handle.backend == "local"

        # 人为将过期时间调到过去
        token, _ = service._local_locks[8]
        service._local_locks[8] = (token, 0.0)

        second = await service.acquire(8, allow_local_fallback=True)
        assert second is not None

    asyncio.run(run())


# ============ C组：残留锁回收（后端重启后"无可见任务却持续409"） ============


def test_force_release_stale_recovers_stale_lock():
    """锁剩余 TTL 低于阈值（持有任务已死）→ 回收成功，可重新获取。"""

    async def run():
        service = make_redis_service()
        # 模拟：任务获取锁后进程被杀，TTL 从 1800 自然衰减到 900（错过两个心跳周期）
        handle = await service.acquire(21, allow_local_fallback=True, ttl_seconds=1800)
        assert handle is not None
        key = "inspiration_ark:chapter_gen_lock:21"
        service._fake_redis.ttls[key] = 900  # 模拟时间流逝后的剩余 TTL

        assert await service.force_release_stale(21) is True
        # 回收后新任务可获取
        new_handle = await service.acquire(21, allow_local_fallback=True)
        assert new_handle is not None

    asyncio.run(run())


def test_force_release_stale_keeps_live_lock():
    """存活任务（TTL 新鲜，心跳正常续租）的锁不得被回收。"""

    async def run():
        service = make_redis_service()
        handle = await service.acquire(22, allow_local_fallback=True, ttl_seconds=1800)
        assert handle is not None
        # 心跳刚续租过，剩余 TTL 仍接近满值
        key = "inspiration_ark:chapter_gen_lock:22"
        service._fake_redis.ttls[key] = 1700

        assert await service.force_release_stale(22) is False
        # 锁仍被持有，新任务仍被拒
        assert await service.acquire(22, allow_local_fallback=True) is None

    asyncio.run(run())


def test_force_release_stale_no_lock_is_noop():
    """锁不存在（从未持有/已过期）→ 回收返回 False 不报错。"""

    async def run():
        service = make_redis_service()
        assert await service.force_release_stale(23) is False

    asyncio.run(run())


def test_force_release_stale_local_fallback():
    """Redis 故障（本地兜底锁）时同语义回收：剩余时间过短即删除。"""

    async def run():
        import time as _time

        service = make_broken_service()
        handle = await service.acquire(24, allow_local_fallback=True)
        assert handle is not None and handle.backend == "local"

        # 模拟：剩余时间只剩 900s（低于阈值 1200）→ 视为持有任务已死
        token, _ = service._local_locks[24]
        service._local_locks[24] = (token, _time.monotonic() + 900)
        assert await service.force_release_stale(24) is True
        assert await service.acquire(24, allow_local_fallback=True) is not None

        # 新锁剩余时间充足 → 不回收
        token2, _ = service._local_locks[24]
        service._local_locks[24] = (token2, _time.monotonic() + 1800)
        assert await service.force_release_stale(24) is False

    asyncio.run(run())



def test_force_release_clears_fresh_orphan_lock():
    async def run():
        service = make_redis_service()
        handle = await service.acquire(25, allow_local_fallback=True, ttl_seconds=1800)
        assert handle is not None
        key = "inspiration_ark:chapter_gen_lock:25"
        service._fake_redis.ttls[key] = 1700

        assert await service.force_release_stale(25) is False
        assert await service.force_release(25) is True
        new_handle = await service.acquire(25, allow_local_fallback=True)
        assert new_handle is not None

    asyncio.run(run())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
