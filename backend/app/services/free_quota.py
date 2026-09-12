"""免费档每日配额服务

用户日额度 + 全局免费发放量护栏在**一个 Lua 脚本内原子完成**
检查、占用与 TTL 设置；超限不递增不回滚（脚本内封顶，防恶意推高计数）。

额度消耗语义（崩溃恢复用轻量 reservation 状态键）：
- 占额成功写入 reservation=pending（TTL 2h）
- 首次正文产出时置 consumed（此后失败不退额，防主动断连刷生成）
- 异常路径：reservation 仍为 pending 则退额并删除键（DEL 原子竞争防双重退款）
- 懒清理：用户下次请求配额时扫描过期未 consumed 的 reservation 并退回，
  覆盖 worker 被杀、OOM、重启等进程内 try/except 无法覆盖的场景

故障策略（fail closed）：Redis 不可用时抛 QuotaServiceUnavailableError，
调用方对免费档返回 503，绝不降级放行；标准档不经过本服务。
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.core.redis_client import LoopBoundRedis

logger = logging.getLogger("uvicorn.error")

# 业务时区固定 Asia/Shanghai（无夏令时，固定 UTC+8 偏移等价且零依赖）
BUSINESS_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

USER_QUOTA_KEY_TEMPLATE = "inspiration_ark:free_chapter_quota:{user_id}:{date}"
GLOBAL_TOTAL_KEY_TEMPLATE = "inspiration_ark:free_daily_total:{date}"
RESERVATION_KEY_PREFIX = "inspiration_ark:free_quota_reservation:"

QUOTA_KEY_TTL_SECONDS = 48 * 3600       # 日界线由键名保证，TTL 仅作兜底清理
RESERVATION_TTL_SECONDS = 2 * 3600
STALE_RESERVATION_SECONDS = 30 * 60     # 超过项目锁 TTL 仍 pending 视为进程已死

# 单脚本原子完成：用户封顶 → 全局封顶 → 双 INCR → 首次创建设 TTL
_RESERVE_LUA = """
local user_limit = tonumber(ARGV[1])
local global_limit = tonumber(ARGV[2])
local quota_ttl = tonumber(ARGV[3])
local reservation_ttl = tonumber(ARGV[4])
local reservation_json = ARGV[5]
local existing = redis.call('GET', KEYS[3])
if existing then
    local data = cjson.decode(existing)
    return {1, math.max(0, user_limit - tonumber(redis.call('GET', KEYS[1]) or '0')), data.status}
end
local user_count = tonumber(redis.call('GET', KEYS[1]) or '0')
if user_count >= user_limit then
    return {0, 0, 'user_limit'}
end
local total = tonumber(redis.call('GET', KEYS[2]) or '0')
if total >= global_limit then
    return {0, user_limit - user_count, 'global_limit'}
end
local new_user = redis.call('INCR', KEYS[1])
if new_user == 1 then
    redis.call('EXPIRE', KEYS[1], quota_ttl)
end
local new_total = redis.call('INCR', KEYS[2])
if new_total == 1 then
    redis.call('EXPIRE', KEYS[2], quota_ttl)
end
redis.call('SET', KEYS[3], reservation_json, 'EX', reservation_ttl)
return {1, user_limit - new_user, 'ok'}
"""

_MARK_CONSUMED_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end
local data = cjson.decode(raw)
if data.status == 'consumed' then
    return 1
end
if data.status ~= 'pending' then
    return 0
end
data.status = 'consumed'
local ttl = redis.call('TTL', KEYS[1])
if ttl <= 0 then
    ttl = tonumber(ARGV[1])
end
redis.call('SET', KEYS[1], cjson.encode(data), 'EX', ttl)
return 1
"""

# 退款防降为负数（键过期后退款为 no-op）
_REFUND_LUA = """
local raw = redis.call('GET', KEYS[3])
if not raw then
    return 0
end
local data = cjson.decode(raw)
if data.status ~= 'pending' then
    return 0
end
redis.call('DEL', KEYS[3])
local refunded = 0
if tonumber(redis.call('GET', KEYS[1]) or '0') > 0 then
    redis.call('DECR', KEYS[1])
    refunded = 1
end
if tonumber(redis.call('GET', KEYS[2]) or '0') > 0 then
    redis.call('DECR', KEYS[2])
end
return refunded
"""


class QuotaServiceUnavailableError(RuntimeError):
    """Redis 配额服务不可用（免费档 fail closed，端点返回 503）。"""


@dataclass(frozen=True)
class QuotaReservationResult:
    allowed: bool
    remaining: int      # 本次占用后的剩余额度
    reset_at: str       # 业务时区次日 0 点（ISO 格式）
    reason: str         # "ok" | "user_limit" | "global_limit"


@dataclass(frozen=True)
class FreeQuotaStatus:
    daily_limit: int
    used: int
    remaining: int
    reset_at: str
    global_available: bool


class FreeQuotaService:
    """免费档配额（Lua 原子占用 + reservation 崩溃恢复）。"""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or str(settings.REDIS_URL).strip()
        self._redis = LoopBoundRedis(self.redis_url)
        self.user_daily_limit = int(getattr(settings, "FREE_TIER_DAILY_CHAPTER_LIMIT", 2))
        self.global_daily_limit = int(getattr(settings, "FREE_TIER_GLOBAL_DAILY_LIMIT", 500))

    async def _get_redis_client(self):
        return await self._redis.get()

    # ---------- 键与时间 ----------

    @staticmethod
    def _today() -> str:
        return datetime.now(BUSINESS_TZ).strftime("%Y%m%d")

    @staticmethod
    def _next_reset_iso() -> str:
        now = datetime.now(BUSINESS_TZ)
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return next_midnight.isoformat()

    @staticmethod
    def _user_key(user_id: int, date: str) -> str:
        return USER_QUOTA_KEY_TEMPLATE.format(user_id=user_id, date=date)

    @staticmethod
    def _total_key(date: str) -> str:
        return GLOBAL_TOTAL_KEY_TEMPLATE.format(date=date)

    @staticmethod
    def _reservation_key(task_id: str) -> str:
        return f"{RESERVATION_KEY_PREFIX}{task_id}"

    # ---------- 核心操作 ----------

    async def get_status(self, user_id: int) -> FreeQuotaStatus:
        """Return the current daily allowance without consuming quota."""
        try:
            client = await self._get_redis_client()
            date = self._today()
            values = await client.mget(
                self._user_key(user_id, date),
                self._total_key(date),
            ) if hasattr(client, "mget") else [
                await client.get(self._user_key(user_id, date)),
                await client.get(self._total_key(date)),
            ]
            used = max(0, int(values[0] or 0))
            global_used = max(0, int(values[1] or 0))
            return FreeQuotaStatus(
                daily_limit=self.user_daily_limit,
                used=used,
                remaining=max(0, self.user_daily_limit - used),
                reset_at=self._next_reset_iso(),
                global_available=global_used < self.global_daily_limit,
            )
        except Exception as exc:
            self._redis.invalidate()
            raise QuotaServiceUnavailableError(str(exc)) from exc

    async def reserve(self, user_id: int, task_id: str) -> QuotaReservationResult:
        """原子占用一次免费额度并写入 reservation=pending。

        Raises:
            QuotaServiceUnavailableError: Redis 不可用（免费档 503）
        """
        try:
            client = await self._get_redis_client()
            # 懒清理：先回收该用户过期未 consumed 的 reservation（best effort）
            await self._lazy_cleanup(client, user_id)

            date = self._today()
            reservation = {
                "user_id": user_id,
                "date": date,
                "status": "pending",
                "created_at": time.time(),
            }
            result = await client.eval(
                _RESERVE_LUA,
                3,
                self._user_key(user_id, date),
                self._total_key(date),
                self._reservation_key(task_id),
                str(self.user_daily_limit),
                str(self.global_daily_limit),
                str(QUOTA_KEY_TTL_SECONDS),
                str(RESERVATION_TTL_SECONDS),
                json.dumps(reservation, ensure_ascii=False),
            )
            allowed = int(result[0]) == 1
            remaining = max(0, int(result[1]))
            reason = str(result[2])

            return QuotaReservationResult(
                allowed=allowed,
                remaining=remaining,
                reset_at=self._next_reset_iso(),
                reason=reason,
            )
        except Exception as exc:
            self._redis.invalidate()
            logger.error(f"❌ 免费额度服务不可用（fail closed）: {exc}")
            raise QuotaServiceUnavailableError(str(exc)) from exc

    async def mark_consumed(self, task_id: str) -> bool:
        """首次正文产出时调用：pending → consumed（此后失败不退额）。

        幂等；标记失败仅告警，不中断生成流程。
        """
        try:
            client = await self._get_redis_client()
            result = await client.eval(
                _MARK_CONSUMED_LUA,
                1,
                self._reservation_key(task_id),
                str(RESERVATION_TTL_SECONDS),
            )
            return int(result) == 1
        except Exception as exc:
            self._redis.invalidate()
            logger.warning(f"⚠️ 标记额度已消耗失败（任务 {task_id}）: {exc}")
            return False

    async def refund_if_pending(self, task_id: str) -> bool:
        """异常路径退款：reservation 仍为 pending 时退还额度并删除键。

        用 DEL 原子竞争防止任务异常路径与懒清理并发双重退款；幂等。
        """
        try:
            client = await self._get_redis_client()
            key = self._reservation_key(task_id)
            raw = await client.get(key)
            if not raw:
                return False
            data = json.loads(raw)
            if data.get("status") != "pending":
                return False
            date = str(data.get("date") or self._today())
            user_id = data.get("user_id")
            refunded = await client.eval(
                _REFUND_LUA,
                3,
                self._user_key(user_id, date),
                self._total_key(date),
                key,
            )
            if int(refunded) != 1:
                return False
            logger.info(f"   💰 已退回免费额度（任务 {task_id}, 用户 {user_id}）")
            return True
        except Exception as exc:
            self._redis.invalidate()
            logger.warning(f"⚠️ 退回免费额度失败（任务 {task_id}）: {exc}")
            return False

    async def _lazy_cleanup(self, client, user_id: int) -> None:
        """回收该用户超时仍 pending 的 reservation（覆盖进程被杀等场景）。"""
        try:
            now = time.time()
            async for key in client.scan_iter(match=f"{RESERVATION_KEY_PREFIX}*", count=100):
                raw = await client.get(key)
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if data.get("user_id") != user_id:
                    continue
                if data.get("status") != "pending":
                    continue
                if now - float(data.get("created_at") or 0) < STALE_RESERVATION_SECONDS:
                    continue
                stale_task_id = str(key).rsplit(":", 1)[-1]
                await self.refund_if_pending(stale_task_id)
        except Exception as exc:
            # 懒清理失败不阻塞占额主流程
            logger.warning(f"⚠️ 懒清理过期额度预占失败（用户 {user_id}）: {exc}")


_quota_service: Optional[FreeQuotaService] = None


def get_free_quota_service() -> FreeQuotaService:
    global _quota_service
    if _quota_service is None:
        _quota_service = FreeQuotaService()
    return _quota_service
