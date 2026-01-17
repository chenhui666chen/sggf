from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Deque, Dict, Optional


@dataclass(frozen=True)
class RateLimitConfig:
    max_requests_per_minute: Optional[int] = None
    max_requests_per_day: Optional[int] = None


class RateLimiter:
    """
    同步版 RateLimiter。

    - 限制每分钟/每天最大请求数
    - 额外保证同一 limiter 的最小请求间隔（由 max_requests_per_minute 推导）
    """

    def __init__(
        self,
        *,
        max_requests_per_minute: Optional[int] = None,
        max_requests_per_day: Optional[int] = None,
        time_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cfg = RateLimitConfig(
            max_requests_per_minute=max_requests_per_minute if (max_requests_per_minute or 0) > 0 else None,
            max_requests_per_day=max_requests_per_day if (max_requests_per_day or 0) > 0 else None,
        )
        self._time = time_fn
        self._sleep = sleep_fn
        self._lock = Lock()
        self._request_times: Deque[float] = deque()

        if self._cfg.max_requests_per_minute:
            self._min_delay = 60.0 / float(self._cfg.max_requests_per_minute)
        else:
            self._min_delay = 0.0

    @property
    def config(self) -> RateLimitConfig:
        return self._cfg

    def acquire(self) -> None:
        if not self._cfg.max_requests_per_minute and not self._cfg.max_requests_per_day:
            return

        with self._lock:
            now = self._time()

            if self._cfg.max_requests_per_day:
                self._cleanup(now, window_s=86400.0)
            elif self._cfg.max_requests_per_minute:
                self._cleanup(now, window_s=60.0)

            if self._cfg.max_requests_per_day:
                self._enforce_limit(now, window_s=86400.0, max_requests=self._cfg.max_requests_per_day)
                now = self._time()

            if self._cfg.max_requests_per_minute:
                self._enforce_limit(now, window_s=60.0, max_requests=self._cfg.max_requests_per_minute)
                now = self._time()

                if self._request_times and self._min_delay > 0:
                    last = self._request_times[-1]
                    elapsed = now - last
                    if elapsed < self._min_delay:
                        self._sleep(self._min_delay - elapsed)
                        now = self._time()

            self._request_times.append(now)

    def _cleanup(self, now: float, *, window_s: float) -> None:
        while self._request_times and (now - self._request_times[0]) >= window_s:
            self._request_times.popleft()

    def _enforce_limit(self, now: float, *, window_s: float, max_requests: int) -> None:
        self._cleanup(now, window_s=window_s)
        if len(self._request_times) < max_requests:
            return
        oldest = self._request_times[0]
        wait_s = window_s - (now - oldest)
        if wait_s > 0:
            self._sleep(wait_s)


_REGISTRY_LOCK = Lock()
_REGISTRY: Dict[str, RateLimiter] = {}


def get_rate_limiter(
    *,
    key: str,
    max_requests_per_minute: Optional[int],
    max_requests_per_day: Optional[int],
) -> Optional[RateLimiter]:
    """
    获取（或创建）共享 limiter：
    - key 建议使用 env_prefix（如 WAN_T2I / WAN_T2V / QWEN_VL_PLUS）
    - 同一 key 在进程内共享限流状态，避免 alias 造成“重复计数失效”
    """
    if not max_requests_per_minute and not max_requests_per_day:
        return None
    if not key:
        key = "__default__"

    cfg = RateLimitConfig(
        max_requests_per_minute=max_requests_per_minute if (max_requests_per_minute or 0) > 0 else None,
        max_requests_per_day=max_requests_per_day if (max_requests_per_day or 0) > 0 else None,
    )

    with _REGISTRY_LOCK:
        existing = _REGISTRY.get(key)
        if existing and existing.config == cfg:
            return existing
        limiter = RateLimiter(
            max_requests_per_minute=cfg.max_requests_per_minute,
            max_requests_per_day=cfg.max_requests_per_day,
        )
        _REGISTRY[key] = limiter
        return limiter
