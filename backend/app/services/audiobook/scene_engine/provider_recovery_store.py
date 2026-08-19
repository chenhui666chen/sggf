"""ProviderRecoveryRecord 持久化载体（指导文档 §12.2）。

为短期恢复记录提供加密文件存储、CAS 状态推进、双键查找和 TTL 清理。
落盘时整个 JSON payload 以 Fernet 加密（at-rest），读取时自动解密。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

from .provider_recovery import (
    ProviderRecoveryRecord,
    RecoveryTransitionError,
    advance_status,
    external_provider_key,
    internal_attempt_key,
)


logger = logging.getLogger(__name__)


ENCRYPTION_KEY_MIN_LENGTH = 16
"""最小加密密钥长度（字节）。短于此长度的密钥拒绝初始化（失败关闭）。"""


class EncryptionKeyError(ValueError):
    """加密密钥不满足安全要求。"""


class ProviderRecoveryStore:
    """文件加密持久化的 ProviderRecoveryRecord 存储层。

    每个记录以 ``{storage_dir}/{internal_attempt_key}.enc`` 存储，
    文件内容为 Fernet 加密的 JSON 字节。内存中维持 attempt_key → record
    与 provider_key → attempt_key 双键索引，启动时从磁盘重建。
    """

    ENCRYPTED_EXTENSION = ".enc"

    def __init__(
        self,
        storage_dir: str,
        encryption_key: str,
        ttl_seconds: int = 86400,
    ) -> None:
        if not encryption_key:
            raise EncryptionKeyError("加密密钥不能为空（失败关闭，禁止明文落盘）")
        if len(encryption_key) < ENCRYPTION_KEY_MIN_LENGTH:
            raise EncryptionKeyError(
                f"加密密钥长度 {len(encryption_key)} < {ENCRYPTION_KEY_MIN_LENGTH}"
            )
        derived = hashlib.sha256(encryption_key.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))

        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

        self._lock = threading.Lock()
        # attempt_key -> record dict
        self._records: Dict[str, dict[str, Any]] = {}
        # (provider_id, scope_hash, request_id) -> attempt_key
        self._provider_index: Dict[Tuple[str, str, str], str] = {}

        self._rebuild_index()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def save(self, record: ProviderRecoveryRecord) -> bool:
        """持久化一条恢复记录。

        同 internal_attempt_key 已存在时返回 False（幂等写入）。
        """
        attempt_key = internal_attempt_key(record)
        with self._lock:
            if attempt_key in self._records:
                return False

            payload = _record_to_dict(record)
            encrypted = self._encrypt_payload(payload)
            path = self._record_path(attempt_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, encrypted)

            self._records[attempt_key] = payload
            self._index_provider_key(record, attempt_key)
        return True

    def get_by_attempt_key(
        self, attempt_key: str
    ) -> Optional[ProviderRecoveryRecord]:
        """通过 internal_attempt_key 查找记录。"""
        with self._lock:
            payload = self._records.get(attempt_key)
            if payload is None:
                return None
            return _dict_to_record(payload)

    def get_by_provider_key(
        self, provider_key: Tuple[str, str, str]
    ) -> Optional[ProviderRecoveryRecord]:
        """通过外部 provider 唯一键查找记录。"""
        with self._lock:
            attempt_key = self._provider_index.get(provider_key)
            if attempt_key is None:
                return None
            payload = self._records.get(attempt_key)
            if payload is None:
                return None
            return _dict_to_record(payload)

    def update_status(
        self,
        attempt_key: str,
        *,
        expected: str,
        target: str,
        now: float,
    ) -> ProviderRecoveryRecord:
        """CAS 状态推进：从磁盘读最新记录，校验后写回。

        Raises:
            KeyError: attempt_key 不存在。
            RecoveryTransitionError: CAS 校验或迁移白名单失败。
        """
        with self._lock:
            payload = self._records.get(attempt_key)
            if payload is None:
                raise KeyError(f"attempt_key not found: {attempt_key}")

            current = _dict_to_record(payload)
            updated = advance_status(current, expected=expected, target=target, now=now)

            new_payload = _record_to_dict(updated)
            encrypted = self._encrypt_payload(new_payload)
            path = self._record_path(attempt_key)
            _atomic_write(path, encrypted)

            self._records[attempt_key] = new_payload
            # provider key might change if provider_request_id appeared
            # (unlikely for CAS but handle safely)
            self._reindex_provider_key(updated, attempt_key)
        return updated

    def cleanup_expired(self, now: float) -> int:
        """删除 expires_at < now 的过期记录，返回清理数量。"""
        with self._lock:
            expired_keys = [
                key
                for key, payload in self._records.items()
                if payload.get("expires_at", 0.0) < now
            ]
            for key in expired_keys:
                self._remove_record(key)
        count = len(expired_keys)
        if count:
            logger.info("ProviderRecoveryStore: cleaned %d expired records", count)
        return count

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _record_path(self, attempt_key: str) -> Path:
        safe = _sanitize_key(attempt_key)
        return self._storage_dir / f"{safe}{self.ENCRYPTED_EXTENSION}"

    def _encrypt_payload(self, payload: dict[str, Any]) -> bytes:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(raw)

    def _decrypt_payload(self, data: bytes) -> dict[str, Any]:
        try:
            decrypted = self._fernet.decrypt(data)
        except InvalidToken as exc:
            raise ValueError("解密失败：密钥不匹配或数据损坏") from exc
        return json.loads(decrypted.decode("utf-8"))

    def _rebuild_index(self) -> None:
        """启动时从磁盘 *.enc 文件重建双键索引。"""
        self._records.clear()
        self._provider_index.clear()
        for child in self._storage_dir.iterdir():
            if child.suffix != self.ENCRYPTED_EXTENSION or not child.is_file():
                continue
            try:
                payload = self._decrypt_payload(child.read_bytes())
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                logger.warning("ProviderRecoveryStore: 跳过损坏文件 %s: %s", child.name, exc)
                continue
            attempt_key = _compute_attempt_key(payload)
            if not attempt_key:
                continue
            self._records[attempt_key] = payload
            # rebuild provider index
            provider_key = _compute_provider_key_from_payload(payload)
            if provider_key:
                self._provider_index[provider_key] = attempt_key

    def _index_provider_key(
        self, record: ProviderRecoveryRecord, attempt_key: str
    ) -> None:
        pkey = external_provider_key(record)
        if pkey:
            self._provider_index[pkey] = attempt_key

    def _reindex_provider_key(
        self, record: ProviderRecoveryRecord, attempt_key: str
    ) -> None:
        # Remove any existing entry for this attempt_key, re-add
        self._provider_index = {
            k: v for k, v in self._provider_index.items() if v != attempt_key
        }
        self._index_provider_key(record, attempt_key)

    def _remove_record(self, attempt_key: str) -> None:
        payload = self._records.pop(attempt_key, None)
        if payload:
            pkey = _compute_provider_key_from_payload(payload)
            if pkey:
                self._provider_index.pop(pkey, None)
        path = self._record_path(attempt_key)
        if path.exists():
            path.unlink(missing_ok=True)


# ------------------------------------------------------------------
# module-level helpers
# ------------------------------------------------------------------


def _record_to_dict(record: ProviderRecoveryRecord) -> dict[str, Any]:
    return asdict(record)


def _dict_to_record(payload: Mapping[str, Any]) -> ProviderRecoveryRecord:
    return ProviderRecoveryRecord(
        provider_id=str(payload.get("provider_id", "")),
        provider_account_scope_hash=str(payload.get("provider_account_scope_hash", "")),
        provider_request_id=str(payload.get("provider_request_id", "")),
        generation_input_hash=str(payload.get("generation_input_hash", "")),
        attempt_number=int(payload.get("attempt_number", 1)),
        encrypted_result_url=str(payload.get("encrypted_result_url", "")),
        expires_at=float(payload.get("expires_at", 0.0)),
        status=str(payload.get("status", "pending")),
        last_checked_at=float(payload.get("last_checked_at", 0.0)),
        check_attempts=int(payload.get("check_attempts", 0)),
        recovery_method=str(payload.get("recovery_method", "request_query")),
    )


def _compute_attempt_key(payload: Mapping[str, Any]) -> str | None:
    gen_hash = payload.get("generation_input_hash", "")
    attempt = payload.get("attempt_number", 0)
    if not gen_hash or not attempt:
        return None
    return f"{gen_hash}:{attempt}"


def _compute_provider_key_from_payload(
    payload: Mapping[str, Any]
) -> Tuple[str, str, str] | None:
    provider_id = payload.get("provider_id", "")
    scope_hash = payload.get("provider_account_scope_hash", "")
    request_id = payload.get("provider_request_id", "")
    if not provider_id or not scope_hash or not request_id:
        return None
    return (provider_id, scope_hash, request_id)


def _sanitize_key(key: str) -> str:
    """将 attempt_key 转义为安全的文件名。"""
    return key.replace(":", "_").replace("/", "_").replace("\\", "_")


def _atomic_write(path: Path, data: bytes) -> None:
    """先写 tmp 再 rename，避免部分写入。"""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        shutil.move(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


__all__ = [
    "ENCRYPTION_KEY_MIN_LENGTH",
    "EncryptionKeyError",
    "ProviderRecoveryStore",
]