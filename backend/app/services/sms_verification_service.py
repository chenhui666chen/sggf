"""
短信验证码服务（手机号申诉绑定/找回密码）。

与 EmailVerificationService 同构（Redis 存哈希码 + 重发间隔 + 尝试上限，
fail-closed）；差异：
- key 含 purpose（takeover/bind/reset）：不同用途的验证码不得互用，
  防止把找回密码码拿去申诉抢占他人手机号；
- 全局日预算熔断：所有真实发送先原子占额，超限拒绝、发送失败退额，
  把最坏情况下的短信成本封顶（配置项，≈月预算上限）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.redis_client import LoopBoundRedis
from app.utils.datetime_utils import parse_datetime_utc, utc_now

logger = logging.getLogger(__name__)


class SmsBudgetExhaustedError(RuntimeError):
    """全局日预算耗尽（成本熔断，路由翻译为 503 统一文案）。"""


class SmsVerificationService:
    """管理短信验证码的生成、存储与校验（Redis 存储，fail-closed）。"""

    def __init__(self, redis_url: str | None = None):
        self.redis_url = str(redis_url or settings.REDIS_URL).strip()
        self._redis = LoopBoundRedis(self.redis_url)

    def _now(self) -> datetime:
        return utc_now()

    def _cache_key(self, purpose: str, phone: str) -> str:
        phone_hash = hashlib.sha256(phone.encode("utf-8")).hexdigest()[:16]
        return f"auth:sms-verify:{purpose}:{phone_hash}"

    def _budget_key(self) -> str:
        return f"sms:global-daily:{self._now().strftime('%Y%m%d')}"

    def _hash_code(self, purpose: str, phone: str, code: str) -> str:
        payload = f"{purpose}:{phone}:{code}:{settings.JWT_SECRET}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _generate_code(self) -> str:
        length = max(4, int(settings.SMS_VERIFY_CODE_LENGTH))
        upper_bound = 10 ** length
        return f"{secrets.randbelow(upper_bound):0{length}d}"

    def _remaining_ttl(self, record: dict[str, Any]) -> int:
        expires_at_raw = str(record.get("expires_at") or "").strip()
        if not expires_at_raw:
            return 0

        expires_at = parse_datetime_utc(expires_at_raw)
        if expires_at is None:
            return 0
        remaining = int((expires_at - self._now()).total_seconds())
        return max(0, remaining)

    async def _get_redis_client(self):
        try:
            return await self._redis.get()
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("短信验证码 Redis 不可用（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def _read_record(self, purpose: str, phone: str) -> dict[str, Any] | None:
        key = self._cache_key(purpose, phone)
        client = await self._get_redis_client()
        try:
            raw = await client.get(key)
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("读取短信验证码 Redis 失败（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

        if not raw:
            return None

        record = json.loads(raw)
        if self._remaining_ttl(record) > 0:
            return record

        await self.delete_code(purpose, phone)
        return None

    async def _write_record(self, purpose: str, phone: str, record: dict[str, Any], ttl: int) -> None:
        key = self._cache_key(purpose, phone)
        client = await self._get_redis_client()
        try:
            await client.setex(key, ttl, json.dumps(record, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("写入短信验证码 Redis 失败（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def delete_code(self, purpose: str, phone: str) -> None:
        key = self._cache_key(purpose, phone)
        client = await self._get_redis_client()
        try:
            await client.delete(key)
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("删除短信验证码 Redis 失败（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def reserve_budget(self) -> None:
        """全局日预算原子占额：超限抛 SmsBudgetExhaustedError（成本熔断）。"""
        budget = max(1, int(settings.SMS_GLOBAL_DAILY_BUDGET))
        client = await self._get_redis_client()
        try:
            count = await client.incr(self._budget_key())
            if int(count) == 1:
                # 首次写入设跨日 TTL（48h：覆盖时区边界，到期自动清理）
                await client.expire(self._budget_key(), 48 * 3600)
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("短信预算计数 Redis 不可用（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

        if int(count) > budget:
            logger.warning("短信全局日预算耗尽（当日第 %s 次请求，预算 %s）", count, budget)
            raise SmsBudgetExhaustedError("短信全局日预算耗尽")

    async def release_budget(self) -> None:
        """发送失败退额（尽力而为：退不掉只是当日预算略保守，不影响正确性）。"""
        try:
            client = await self._get_redis_client()
            await client.decr(self._budget_key())
        except Exception:  # noqa: BLE001
            logger.warning("短信预算退额失败（忽略，当日预算略保守）")

    async def issue_code(self, purpose: str, phone: str) -> str | None:
        """生成验证码；重发间隔内返回 None（由路由统一文案响应）。"""
        now = self._now()
        record = await self._read_record(purpose, phone)
        resend_interval = max(0, int(settings.SMS_VERIFY_RESEND_INTERVAL_SECONDS))
        if record:
            sent_at = parse_datetime_utc(record.get("sent_at"))
            if sent_at and (now - sent_at).total_seconds() < resend_interval:
                return None

        code = self._generate_code()
        ttl = max(60, int(settings.SMS_VERIFY_CODE_TTL_SECONDS))
        expires_at = now + timedelta(seconds=ttl)
        payload = {
            "phone": phone,
            "purpose": purpose,
            "code_hash": self._hash_code(purpose, phone, code),
            "sent_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "attempts": 0,
        }
        await self._write_record(purpose, phone, payload, ttl)
        return code

    async def verify_code(self, purpose: str, phone: str, code: str) -> bool:
        record = await self._read_record(purpose, phone)
        if not record:
            return False

        expected_hash = str(record.get("code_hash") or "")
        provided_hash = self._hash_code(purpose, phone, code)
        if hmac.compare_digest(expected_hash, provided_hash):
            await self.delete_code(purpose, phone)
            return True

        record["attempts"] = int(record.get("attempts") or 0) + 1
        max_attempts = max(1, int(settings.SMS_VERIFY_MAX_ATTEMPTS))
        if int(record["attempts"]) >= max_attempts:
            await self.delete_code(purpose, phone)
            return False

        ttl = self._remaining_ttl(record)
        if ttl <= 0:
            await self.delete_code(purpose, phone)
            return False

        await self._write_record(purpose, phone, record, ttl)
        return False
