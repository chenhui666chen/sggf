"""免费档每日配额服务测试（步骤5：Lua 原子占用 + reservation 崩溃恢复）

覆盖：
- A组：占用语义——用户封顶/全局护栏/超限不递增/TTL/用户隔离/并发只放行限额内
- B组：消耗与退款——consumed 后不退、pending 退款幂等、懒清理崩溃恢复
- C组：故障策略——Redis 断连 reserve 抛错 fail closed，标记/退款不抛只告警
"""

import asyncio
import fnmatch
import json
import os
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("DEBUG", "false")

from app.services.free_quota import (  # noqa: E402
    FreeQuotaService,
    QuotaServiceUnavailableError,
    RESERVATION_KEY_PREFIX,
    QUOTA_KEY_TTL_SECONDS,
)


class FakeRedis:
    """按 Lua 脚本语义在 Python 侧原子模拟（asyncio 单线程内每次 eval 整体原子）。"""

    def __init__(self):
        self.store = {}
        self.ttls = {}

    async def ping(self):
        return True

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def delete(self, key):
        if key in self.store:
            del self.store[key]
            self.ttls.pop(key, None)
            return 1
        return 0

    async def ttl(self, key):
        return self.ttls.get(key, -1)

    async def eval(self, script, numkeys, *args):
        keys = list(args[:numkeys])
        argv = list(args[numkeys:])
        if "user_limit" in script:  # _RESERVE_LUA
            user_key, total_key, reservation_key = keys
            user_limit, global_limit = int(argv[0]), int(argv[1])
            quota_ttl, reservation_ttl = int(argv[2]), int(argv[3])
            reservation_json = argv[4]
            if reservation_key in self.store:
                existing = json.loads(self.store[reservation_key])
                return [1, max(0, user_limit - int(self.store.get(user_key, "0"))), existing["status"]]
            user = int(self.store.get(user_key, "0"))
            if user >= user_limit:
                return [0, 0, "user_limit"]
            total = int(self.store.get(total_key, "0"))
            if total >= global_limit:
                return [0, user_limit - user, "global_limit"]
            new_user = user + 1
            self.store[user_key] = str(new_user)
            if new_user == 1:
                self.ttls[user_key] = quota_ttl
            new_total = total + 1
            self.store[total_key] = str(new_total)
            if new_total == 1:
                self.ttls[total_key] = quota_ttl
            self.store[reservation_key] = reservation_json
            self.ttls[reservation_key] = reservation_ttl
            return [1, user_limit - new_user, "ok"]
        if "data.status == 'consumed'" in script:  # _MARK_CONSUMED_LUA
            reservation_key = keys[0]
            raw = self.store.get(reservation_key)
            if not raw:
                return 0
            data = json.loads(raw)
            if data.get("status") == "consumed":
                return 1
            if data.get("status") != "pending":
                return 0
            data["status"] = "consumed"
            self.store[reservation_key] = json.dumps(data)
            return 1
        # _REFUND_LUA
        user_key, total_key, reservation_key = keys
        raw = self.store.get(reservation_key)
        if not raw or json.loads(raw).get("status") != "pending":
            return 0
        await self.delete(reservation_key)
        refunded = 0
        if int(self.store.get(user_key, "0")) > 0:
            self.store[user_key] = str(int(self.store[user_key]) - 1)
            refunded = 1
        if int(self.store.get(total_key, "0")) > 0:
            self.store[total_key] = str(int(self.store[total_key]) - 1)
        return refunded

    async def scan_iter(self, match=None, count=None):
        for key in list(self.store.keys()):
            if match is None or fnmatch.fnmatch(key, match):
                yield key


class _FakeRedisManager:
    """替代 LoopBoundRedis 的测试桩：get() 恒返回注入的假客户端（同 test_auth_routes）。"""

    def __init__(self, client):
        self._client = client

    async def get(self):
        return self._client

    def invalidate(self) -> None:
        pass


def make_service(user_limit=2, global_limit=500) -> FreeQuotaService:
    service = FreeQuotaService(redis_url="redis://fake:6379/0")
    fake = FakeRedis()
    service._redis = _FakeRedisManager(fake)
    service._fake_redis = fake  # 测试断言用（原 _redis_client 已改为按事件循环管理）
    service.user_daily_limit = user_limit
    service.global_daily_limit = global_limit
    return service


def make_broken_service() -> FreeQuotaService:
    service = FreeQuotaService(redis_url="redis://fake:6379/0")

    async def _always_fail():
        raise ConnectionError("redis down")

    service._get_redis_client = _always_fail  # type: ignore[method-assign]
    return service


# ============ A组：占用语义 ============


def test_concurrent_reserves_only_allow_daily_limit():
    """并发 3 请求只放行 2（验收标准），拒绝原因为 user_limit。"""

    async def run():
        service = make_service(user_limit=2)
        results = await asyncio.gather(
            service.reserve(1, "task-a"),
            service.reserve(1, "task-b"),
            service.reserve(1, "task-c"),
        )
        allowed = [r for r in results if r.allowed]
        denied = [r for r in results if not r.allowed]
        assert len(allowed) == 2
        assert len(denied) == 1
        assert denied[0].reason == "user_limit"
        # remaining 递减：第一次 1，第二次 0
        assert sorted(r.remaining for r in allowed) == [0, 1]

    asyncio.run(run())


def test_denied_does_not_increment_counter():
    """超限拒绝时不递增（防恶意推高计数）。"""

    async def run():
        service = make_service(user_limit=1)
        first = await service.reserve(1, "t1")
        assert first.allowed
        fake = service._fake_redis
        user_key = service._user_key(1, service._today())
        assert fake.store[user_key] == "1"

        for i in range(3):
            denied = await service.reserve(1, f"deny-{i}")
            assert not denied.allowed
        assert fake.store[user_key] == "1"  # 计数未被推高

    asyncio.run(run())


def test_global_guardrail_rejects_across_users():
    """全局发放量护栏：达到阈值后其他用户也被拒。"""

    async def run():
        service = make_service(user_limit=2, global_limit=1)
        first = await service.reserve(1, "t1")
        assert first.allowed
        second = await service.reserve(2, "t2")
        assert not second.allowed
        assert second.reason == "global_limit"

    asyncio.run(run())


def test_quota_keys_have_ttl_and_reservation_pending():
    async def run():
        service = make_service()
        result = await service.reserve(7, "task-7")
        assert result.allowed and result.reason == "ok"
        assert result.reset_at  # 带重置时间

        fake = service._fake_redis
        date = service._today()
        assert fake.ttls[service._user_key(7, date)] == QUOTA_KEY_TTL_SECONDS
        assert fake.ttls[service._total_key(date)] == QUOTA_KEY_TTL_SECONDS

        raw = fake.store[f"{RESERVATION_KEY_PREFIX}task-7"]
        data = json.loads(raw)
        assert data["status"] == "pending"
        assert data["user_id"] == 7

    asyncio.run(run())


def test_reserve_writes_reservation_inside_atomic_script():
    async def run():
        service = make_service()
        fake = service._fake_redis

        async def fail_if_called(*args, **kwargs):
            raise AssertionError("reservation must not be written after the Lua script")

        fake.set = fail_if_called
        result = await service.reserve(7, "atomic-task")

        assert result.allowed
        reservation_key = f"{RESERVATION_KEY_PREFIX}atomic-task"
        assert json.loads(fake.store[reservation_key])["status"] == "pending"

    asyncio.run(run())


def test_duplicate_task_reservation_is_idempotent():
    async def run():
        service = make_service()
        first = await service.reserve(7, "same-task")
        second = await service.reserve(7, "same-task")

        assert first.allowed and second.allowed
        fake = service._fake_redis
        user_key = service._user_key(7, service._today())
        assert fake.store[user_key] == "1"

    asyncio.run(run())


def test_users_are_isolated():
    async def run():
        service = make_service(user_limit=2)
        for i in range(2):
            assert (await service.reserve(1, f"u1-{i}")).allowed
        assert not (await service.reserve(1, "u1-x")).allowed
        # 用户2不受用户1封顶影响
        assert (await service.reserve(2, "u2-0")).allowed

    asyncio.run(run())


def test_get_status_reports_remaining_without_consuming_quota():
    async def run():
        service = make_service(user_limit=2, global_limit=10)
        initial = await service.get_status(3)
        assert initial.remaining == 2
        assert initial.used == 0
        assert initial.global_available is True

        await service.reserve(3, "status-task")
        current = await service.get_status(3)
        assert current.used == 1
        assert current.remaining == 1

        fake = service._fake_redis
        user_key = service._user_key(3, service._today())
        assert fake.store[user_key] == "1"

    asyncio.run(run())


# ============ B组：消耗与退款 ============


def test_consumed_reservation_is_not_refunded():
    """已产出正文（consumed）后失败不退额。"""

    async def run():
        service = make_service()
        await service.reserve(1, "task-x")
        assert await service.mark_consumed("task-x") is True

        fake = service._fake_redis
        user_key = service._user_key(1, service._today())
        assert fake.store[user_key] == "1"

        # consumed 后退款为 no-op
        assert await service.refund_if_pending("task-x") is False
        assert fake.store[user_key] == "1"

    asyncio.run(run())


def test_refund_pending_is_idempotent():
    """pending 退款成功且幂等；额度可被重新占用。"""

    async def run():
        service = make_service(user_limit=1)
        await service.reserve(1, "task-y")
        fake = service._fake_redis
        user_key = service._user_key(1, service._today())
        assert fake.store[user_key] == "1"

        assert await service.refund_if_pending("task-y") is True
        assert fake.store[user_key] == "0"
        assert f"{RESERVATION_KEY_PREFIX}task-y" not in fake.store
        # 二次退款幂等
        assert await service.refund_if_pending("task-y") is False
        assert fake.store[user_key] == "0"

        # 退款后可重新占用
        assert (await service.reserve(1, "task-z")).allowed

    asyncio.run(run())


def test_refund_unknown_task_is_noop():
    async def run():
        service = make_service()
        assert await service.refund_if_pending("no-such-task") is False

    asyncio.run(run())


def test_lazy_cleanup_recovers_quota_after_crash():
    """进程被杀（reservation 长期 pending）→ 下次请求配额时懒清理退回额度。"""

    async def run():
        service = make_service(user_limit=1)
        await service.reserve(1, "dead-task")
        assert not (await service.reserve(1, "blocked")).allowed  # 额度已满

        # 模拟崩溃残留：created_at 提前到 31 分钟前
        fake = service._fake_redis
        key = f"{RESERVATION_KEY_PREFIX}dead-task"
        data = json.loads(fake.store[key])
        data["created_at"] = time.time() - 31 * 60
        fake.store[key] = json.dumps(data)

        # 下次 reserve 触发懒清理 → 退回额度 → 占用成功
        result = await service.reserve(1, "recovered-task")
        assert result.allowed
        assert key not in fake.store  # 残留 reservation 已清除

    asyncio.run(run())


def test_lazy_cleanup_skips_fresh_and_consumed():
    """懒清理不误伤：进行中的（新鲜 pending）与已消耗的 reservation 不动。"""

    async def run():
        service = make_service(user_limit=3)
        await service.reserve(1, "fresh-task")
        await service.reserve(1, "done-task")
        await service.mark_consumed("done-task")

        await service.reserve(1, "trigger")  # 触发懒清理

        fake = service._fake_redis
        assert f"{RESERVATION_KEY_PREFIX}fresh-task" in fake.store
        assert f"{RESERVATION_KEY_PREFIX}done-task" in fake.store
        user_key = service._user_key(1, service._today())
        assert fake.store[user_key] == "3"

    asyncio.run(run())


# ============ C组：故障策略（fail closed） ============


def test_redis_down_reserve_fail_closed():
    async def run():
        service = make_broken_service()
        with pytest.raises(QuotaServiceUnavailableError):
            await service.reserve(1, "task-1")

    asyncio.run(run())


def test_redis_down_mark_and_refund_do_not_raise():
    """生成链路中的标记/退款失败只告警，不中断任务流程。"""

    async def run():
        service = make_broken_service()
        assert await service.mark_consumed("task-1") is False
        assert await service.refund_if_pending("task-1") is False

    asyncio.run(run())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
