"""
找回密码验证码服务
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


class PasswordResetService:
    """管理找回密码验证码的生成、存储与校验（Redis 存储，fail-closed）。

    Redis 不可用时直接返回 503，不回退进程内存：多实例部署下内存验证码不一致，
    且静默降级会把"存储失败"误报为发送成功。
    """

    def __init__(self, redis_url: str | None = None):
        self.redis_url = str(redis_url or settings.REDIS_URL).strip()
        self._redis = LoopBoundRedis(self.redis_url)

    def _now(self) -> datetime:
        return utc_now()

    def _cache_key(self, user_id: int) -> str:
        return f"auth:password-reset:{user_id}"

    def _hash_code(self, user_id: int, code: str) -> str:
        payload = f"{user_id}:{code}:{settings.JWT_SECRET}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _generate_code(self) -> str:
        length = max(4, int(settings.PASSWORD_RESET_CODE_LENGTH))
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
            logger.error("找回密码验证码 Redis 不可用（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def _read_record(self, user_id: int) -> dict[str, Any] | None:
        key = self._cache_key(user_id)
        client = await self._get_redis_client()
        try:
            raw = await client.get(key)
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("读取找回密码验证码 Redis 失败（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

        if not raw:
            return None

        record = json.loads(raw)
        if self._remaining_ttl(record) > 0:
            return record

        await self.delete_code(user_id)
        return None

    async def _write_record(self, user_id: int, record: dict[str, Any], ttl: int) -> None:
        key = self._cache_key(user_id)
        client = await self._get_redis_client()
        try:
            await client.setex(key, ttl, json.dumps(record, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("写入找回密码验证码 Redis 失败（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def delete_code(self, user_id: int) -> None:
        key = self._cache_key(user_id)
        client = await self._get_redis_client()
        try:
            await client.delete(key)
        except Exception as exc:  # noqa: BLE001
            self._redis.invalidate()
            logger.error("删除找回密码验证码 Redis 失败（fail-closed）: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="认证服务暂时不可用",
            ) from exc

    async def issue_code(self, user_id: int) -> str | None:
        now = self._now()
        record = await self._read_record(user_id)
        resend_interval = max(0, int(settings.PASSWORD_RESET_RESEND_INTERVAL_SECONDS))
        if record:
            sent_at = parse_datetime_utc(record.get("sent_at"))
            if sent_at and (now - sent_at).total_seconds() < resend_interval:
                return None

        code = self._generate_code()
        ttl = max(60, int(settings.PASSWORD_RESET_CODE_TTL_SECONDS))
        expires_at = now + timedelta(seconds=ttl)
        payload = {
            "user_id": user_id,
            "code_hash": self._hash_code(user_id, code),
            "sent_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "attempts": 0,
        }
        await self._write_record(user_id, payload, ttl)
        return code

    async def verify_code(self, user_id: int, code: str) -> bool:
        record = await self._read_record(user_id)
        if not record:
            return False

        expected_hash = str(record.get("code_hash") or "")
        provided_hash = self._hash_code(user_id, code)
        if hmac.compare_digest(expected_hash, provided_hash):
            await self.delete_code(user_id)
            return True

        record["attempts"] = int(record.get("attempts") or 0) + 1
        max_attempts = max(1, int(settings.PASSWORD_RESET_MAX_ATTEMPTS))
        if int(record["attempts"]) >= max_attempts:
            await self.delete_code(user_id)
            return False

        ttl = self._remaining_ttl(record)
        if ttl <= 0:
            await self.delete_code(user_id)
            return False

        await self._write_record(user_id, record, ttl)
        return False
