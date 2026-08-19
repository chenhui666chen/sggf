from __future__ import annotations

import sys
import time
import logging
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

for candidate in (str(ROOT), str(BACKEND_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


import app.services.audiobook.sse_progress as sse_progress
from app.services.audiobook.sse_progress import SSEProgressTracker


class FakeRedisClient:
    """同时支持异步 ping 与同步 publish 的假 Redis 客户端。"""

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.published: list[tuple[str, str]] = []
        self.closed = False

    async def ping(self):
        if self.fail:
            raise ConnectionError("simulated redis down")
        return True

    def publish(self, channel: str, message: str):
        if self.fail:
            raise ConnectionError("simulated redis down")
        self.published.append((channel, message))
        return 1

    def close(self):
        self.closed = True


def _patch_redis(monkeypatch, fail: bool = False, calls: list | None = None):
    monkeypatch.setattr(sse_progress.settings, "REDIS_URL", "redis://localhost:6380/0")

    def fake_build(redis_url: str, *, async_client: bool = False):
        if calls is not None:
            calls.append(async_client)
        return FakeRedisClient(fail=fail)

    monkeypatch.setattr(sse_progress, "_build_redis_client", fake_build)
    return fake_build


def test_socket_timeout_is_not_too_short():
    """Redis 连接/读写超时必须 >= 1s，本地 Redis 偶发慢响应不应导致 SSE 事件全部丢失。"""
    assert sse_progress.REDIS_SOCKET_TIMEOUT_SECONDS >= 1.0


def test_sync_publish_success_publishes_to_channel(monkeypatch):
    client = FakeRedisClient()
    monkeypatch.setattr(sse_progress.settings, "REDIS_URL", "redis://localhost:6380/0")
    monkeypatch.setattr(
        sse_progress,
        "_build_redis_client",
        lambda redis_url, *, async_client=False: client,
    )

    tracker = SSEProgressTracker()
    tracker._publish_event_to_redis_sync("task_1", {"event": "progress", "data": {"stage": "start"}})

    assert tracker._redis_available is True
    assert tracker._redis_failed_at is None
    assert client.published[0][0] == "audiobook:sse:task:task_1"
    assert "progress" in client.published[0][1]


def test_sync_publish_retries_after_cooldown(monkeypatch):
    """Redis 失败后进入冷却期：冷却期内不再创建连接；冷却期过后重新探测，而非永久禁用。"""
    calls: list[bool] = []
    _patch_redis(monkeypatch, fail=True, calls=calls)
    monkeypatch.setattr(sse_progress, "REDIS_RETRY_COOLDOWN_SECONDS", 0.05)

    tracker = SSEProgressTracker()
    tracker._publish_event_to_redis_sync("task_1", {"event": "progress"})
    assert tracker._redis_available is False
    assert len(calls) == 1

    # 冷却期内：跳过，不创建连接
    tracker._publish_event_to_redis_sync("task_1", {"event": "progress"})
    assert len(calls) == 1

    # 冷却期过后：重新探测并再次发布
    time.sleep(0.07)
    tracker._publish_event_to_redis_sync("task_1", {"event": "progress"})
    assert len(calls) == 2


def test_sync_publish_recovers_when_redis_returns(monkeypatch):
    """Redis 恢复后，冷却期结束即可恢复发布（可用状态不再被永久禁用）。"""
    state = {"fail": True}
    monkeypatch.setattr(sse_progress.settings, "REDIS_URL", "redis://localhost:6380/0")
    monkeypatch.setattr(
        sse_progress,
        "_build_redis_client",
        lambda redis_url, *, async_client=False: FakeRedisClient(fail=state["fail"]),
    )
    monkeypatch.setattr(sse_progress, "REDIS_RETRY_COOLDOWN_SECONDS", 0.0)

    tracker = SSEProgressTracker()
    tracker._publish_event_to_redis_sync("task_1", {"event": "progress"})
    assert tracker._redis_available is False

    state["fail"] = False
    tracker._publish_event_to_redis_sync("task_1", {"event": "progress"})
    assert tracker._redis_available is True
    assert tracker._redis_failed_at is None


def test_async_publish_client_retries_after_cooldown(monkeypatch):
    """异步发布客户端同样遵循冷却期重试，失败后不会永久禁用。"""
    calls: list[bool] = []
    _patch_redis(monkeypatch, fail=True, calls=calls)
    monkeypatch.setattr(sse_progress, "REDIS_RETRY_COOLDOWN_SECONDS", 0.05)

    tracker = SSEProgressTracker()

    async def scenario():
        assert await tracker._get_redis_publish_client() is None
        assert tracker._redis_available is False
        assert len(calls) == 1

        # 冷却期内：直接返回 None，不创建连接
        assert await tracker._get_redis_publish_client() is None
        assert len(calls) == 1

        time.sleep(0.07)
        assert await tracker._get_redis_publish_client() is None
        assert len(calls) == 2

    import asyncio

    asyncio.run(scenario())


def test_async_redis_success_log_redacts_credentials(monkeypatch, caplog):
    secret = "redis-secret-password"
    monkeypatch.setattr(
        sse_progress.settings,
        "REDIS_URL",
        f"redis://worker:{secret}@localhost:6380/0?token=private-token",
    )
    monkeypatch.setattr(
        sse_progress,
        "_build_redis_client",
        lambda redis_url, *, async_client=False: FakeRedisClient(),
    )
    tracker = SSEProgressTracker()

    async def scenario():
        with caplog.at_level(logging.INFO, logger=sse_progress.__name__):
            assert await tracker._get_redis_publish_client() is not None

    import asyncio

    asyncio.run(scenario())

    logged = caplog.text
    assert "Audiobook SSE Redis pub/sub enabled" in logged
    assert "localhost:6380/0" in logged
    assert secret not in logged
    assert "worker" not in logged
    assert "private-token" not in logged
