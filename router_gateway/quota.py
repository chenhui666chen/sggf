"""调用方级别的提交速率保护。"""
from __future__ import annotations

import math
from typing import Any


class RateLimitExceeded(Exception):
    """调用方提交速率超过令牌桶容量。"""

    def __init__(self, retry_after: int):
        self.retry_after = max(1, int(retry_after))
        super().__init__("client rate limit exceeded")


class RateLimiterUnavailable(Exception):
    """已配置的共享限流存储不可用。"""


class NoopRateLimiter:
    def check(self, *, key: str, rate: int, burst: int) -> None:
        return None


class RedisTokenBucket:
    _SCRIPT = """
local bucket_key = KEYS[1]
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local state = redis.call('HMGET', bucket_key, 'tokens', 'updated_ms')
local tokens = tonumber(state[1])
local updated_ms = tonumber(state[2])
if tokens == nil then
  tokens = capacity
  updated_ms = now_ms
end
tokens = math.min(capacity, tokens + ((now_ms - updated_ms) * rate / 1000))
if tokens < 1 then
  local retry_ms = math.ceil((1 - tokens) * 1000 / rate)
  redis.call('HSET', bucket_key, 'tokens', tokens, 'updated_ms', now_ms)
  redis.call('EXPIRE', bucket_key, math.max(60, math.ceil(capacity / rate) * 2))
  return {0, retry_ms}
end
tokens = tokens - 1
redis.call('HSET', bucket_key, 'tokens', tokens, 'updated_ms', now_ms)
redis.call('EXPIRE', bucket_key, math.max(60, math.ceil(capacity / rate) * 2))
return {1, 0}
"""

    def __init__(self, client: Any, *, prefix: str = "router_gateway:rate"):
        self._client = client
        self._prefix = prefix

    @classmethod
    def from_url(cls, url: str, *, prefix: str = "router_gateway:rate"):
        import redis
        from redis.backoff import NoBackoff
        from redis.retry import Retry

        client = redis.Redis.from_url(
            url,
            decode_responses=False,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            retry=Retry(NoBackoff(), retries=0),
        )
        return cls(client, prefix=prefix)

    def check(self, *, key: str, rate: int, burst: int) -> None:
        safe_rate = max(1, int(rate))
        capacity = max(1, int(burst))
        try:
            result = self._client.eval(
                self._SCRIPT, 1, f"{self._prefix}:{key}",
                safe_rate, capacity)
        except Exception as exc:
            raise RateLimiterUnavailable from exc
        allowed = int(result[0])
        if not allowed:
            retry_ms = max(1, int(result[1]))
            raise RateLimitExceeded(math.ceil(retry_ms / 1000))
