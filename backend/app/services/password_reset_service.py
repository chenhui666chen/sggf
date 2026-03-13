"""
找回密码验证码服务
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class PasswordResetService:
    """管理找回密码验证码的生成、存储与校验。"""

    def __init__(self, redis_url: str | None = None):
        self.redis_url = str(redis_url or settings.REDIS_URL).strip()
        self._memory_store: dict[str, dict[str, Any]] = {}
        self._redis_client: Any = None
        self._redis_checked = False

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

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

        expires_at = datetime.fromisoformat(expires_at_raw)
        remaining = int((expires_at - self._now()).total_seconds())
        return max(0, remaining)

    async def _get_redis_client(self):
        if self._redis_checked:
            return self._redis_client

        self._redis_checked = True
        try:
            import redis.asyncio as redis

            client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await client.ping()
            self._redis_client = client
            logger.info("找回密码验证码已启用 Redis 存储: %s", self.redis_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("找回密码验证码 Redis 不可用，将回退到进程内存: %s", exc)
            self._redis_client = None

        return self._redis_client

    async def _read_record(self, user_id: int) -> dict[str, Any] | None:
        key = self._cache_key(user_id)
        client = await self._get_redis_client()
        if client is not None:
            try:
                raw = await client.get(key)
                if raw:
                    record = json.loads(raw)
                    if self._remaining_ttl(record) > 0:
                        return record
                    await client.delete(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("读取找回密码验证码 Redis 失败，改用内存: %s", exc)

        record = self._memory_store.get(key)
        if not record:
            return None
        if self._remaining_ttl(record) <= 0:
            self._memory_store.pop(key, None)
            return None
        return record

    async def _write_record(self, user_id: int, record: dict[str, Any], ttl: int) -> None:
        key = self._cache_key(user_id)
        self._memory_store[key] = record

        client = await self._get_redis_client()
        if client is None:
            return

        try:
            await client.setex(key, ttl, json.dumps(record, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            logger.warning("写入找回密码验证码 Redis 失败，已回退到内存: %s", exc)

    async def delete_code(self, user_id: int) -> None:
        key = self._cache_key(user_id)
        self._memory_store.pop(key, None)

        client = await self._get_redis_client()
        if client is None:
            return

        try:
            await client.delete(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除找回密码验证码 Redis 失败: %s", exc)

    async def issue_code(self, user_id: int) -> str | None:
        now = self._now()
        record = await self._read_record(user_id)
        resend_interval = max(0, int(settings.PASSWORD_RESET_RESEND_INTERVAL_SECONDS))
        if record:
            sent_at = datetime.fromisoformat(str(record["sent_at"]))
            if (now - sent_at).total_seconds() < resend_interval:
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
