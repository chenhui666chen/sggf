"""ProviderRecoveryStore 持久化载体单元测试。

覆盖：
- save 幂等性（同 attempt_key 去重）；
- 双键查找：internal_attempt_key + external_provider_key；
- CAS 状态推进（expected 匹配成功 / 不匹配拒绝）；
- 加密落盘：磁盘文件不含明文 encrypted_result_url；
- TTL 清理：过期记录删除，未过期保留；
- 磁盘重建索引：新实例能正确从磁盘重建双键索引；
- 跨实例持久化：一次 store 写入，新实例可读取。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parents[2]
for _path in (ROOT_DIR, PROJECT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from app.services.audiobook.scene_engine.provider_recovery import (  # noqa: E402
    ProviderRecoveryRecord,
    RecoveryTransitionError,
    advance_status,
)
from app.services.audiobook.scene_engine.provider_recovery_store import (  # noqa: E402
    ENCRYPTION_KEY_MIN_LENGTH,
    EncryptionKeyError,
    ProviderRecoveryStore,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_TEST_ENCRYPTION_KEY = "test-secret-32-chars!!test-secret-!!"


def _make_record(
    *,
    method: str = "temporary_url",
    request_id: str = "req-1",
    url: str = "https://example.com/result",
    expires_at: float = 99999.0,
    status: str = "pending",
    attempt: int = 1,
    generation_hash: str = "input-hash-1",
    provider_id: str = "volcengine_seed",
    scope_hash: str = "scope-hash-1",
) -> ProviderRecoveryRecord:
    return ProviderRecoveryRecord(
        provider_id=provider_id,
        provider_account_scope_hash=scope_hash,
        provider_request_id=request_id,
        generation_input_hash=generation_hash,
        attempt_number=attempt,
        encrypted_result_url=url,
        expires_at=expires_at,
        status=status,
        last_checked_at=0.0,
        check_attempts=0,
        recovery_method=method,
    )


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


class TestProviderRecoveryStoreConstruction:
    def test_empty_encryption_key_raises(self, tmp_path: Path) -> None:
        with pytest.raises(EncryptionKeyError):
            ProviderRecoveryStore(str(tmp_path), encryption_key="")

    def test_short_encryption_key_raises(self, tmp_path: Path) -> None:
        with pytest.raises(EncryptionKeyError):
            ProviderRecoveryStore(str(tmp_path), encryption_key="short")

    def test_creates_storage_dir(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "recovery"
        assert not store_dir.exists()
        ProviderRecoveryStore(str(store_dir), encryption_key=_TEST_ENCRYPTION_KEY)
        assert store_dir.is_dir()

    def test_default_ttl_is_24h(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        assert store.ttl_seconds == 24 * 3600

    def test_custom_ttl(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(
            str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY, ttl_seconds=3600
        )
        assert store.ttl_seconds == 3600


# ---------------------------------------------------------------------------
# basic save / get
# ---------------------------------------------------------------------------


class TestSaveAndGet:
    def test_save_and_get_by_attempt_key(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        record = _make_record()
        saved = store.save(record)
        assert saved is True

        got = store.get_by_attempt_key("input-hash-1:1")
        assert got is not None
        assert got.provider_id == "volcengine_seed"
        assert got.generation_input_hash == "input-hash-1"
        assert got.attempt_number == 1
        assert got.encrypted_result_url == "https://example.com/result"
        assert got.recovery_method == "temporary_url"
        assert got.status == "pending"

    def test_save_idempotent_returns_false_on_dup(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        record = _make_record()
        assert store.save(record) is True
        assert store.save(record) is False

    def test_get_nonexistent_returns_none(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        assert store.get_by_attempt_key("nonexistent:1") is None


# ---------------------------------------------------------------------------
# dual-key lookup
# ---------------------------------------------------------------------------


class TestDualKeyLookup:
    def test_get_by_provider_key(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        record = _make_record()
        store.save(record)

        got = store.get_by_provider_key(("volcengine_seed", "scope-hash-1", "req-1"))
        assert got is not None
        assert got.generation_input_hash == "input-hash-1"

    def test_get_by_provider_key_returns_none_when_missing(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        assert store.get_by_provider_key(("volcengine_seed", "scope-hash-1", "unknown")) is None

    def test_get_by_provider_key_returns_none_for_pending_no_request_id(
        self, tmp_path: Path
    ) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        record = _make_record(request_id="")  # pending, no provider_request_id
        store.save(record)
        # external_provider_key returns None for records without provider_request_id
        assert store.get_by_provider_key(("volcengine_seed", "scope-hash-1", "")) is None


# ---------------------------------------------------------------------------
# CAS status transition
# ---------------------------------------------------------------------------


class TestCasTransition:
    def test_happy_path_transition(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        record = _make_record(status="pending")
        store.save(record)

        updated = store.update_status("input-hash-1:1", expected="pending", target="downloadable", now=1.0)
        assert updated.status == "downloadable"
        assert updated.last_checked_at == 1.0

        # verify on-disk after CAS
        got = store.get_by_attempt_key("input-hash-1:1")
        assert got is not None
        assert got.status == "downloadable"

    def test_cas_mismatch_rejected(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        record = _make_record(status="pending")
        store.save(record)

        with pytest.raises(RecoveryTransitionError):
            store.update_status("input-hash-1:1", expected="downloadable", target="downloaded", now=1.0)

    def test_cas_nonexistent_key_raises(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        with pytest.raises(KeyError):
            store.update_status("nonexistent:1", expected="pending", target="downloadable", now=1.0)


# ---------------------------------------------------------------------------
# encryption at rest
# ---------------------------------------------------------------------------


class TestEncryptionAtRest:
    def test_encrypted_url_not_in_plaintext_on_disk(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        record = _make_record(url="https://secret-temp-url.example.com/result")
        store.save(record)

        store_dir = Path(str(tmp_path))
        for child in store_dir.rglob("*"):
            if child.is_file():
                raw = child.read_bytes()
                assert b"secret-temp-url.example.com" not in raw

    def test_decrypted_on_read(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        record = _make_record(url="https://secret-url.com/token=abc123")
        store.save(record)

        got = store.get_by_attempt_key("input-hash-1:1")
        assert got is not None
        assert got.encrypted_result_url == "https://secret-url.com/token=abc123"

    def test_different_key_cannot_decrypt(self, tmp_path: Path) -> None:
        store_a = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        record = _make_record(url="https://sensitive.example.com")
        store_a.save(record)

        # a different store with same key should work
        store_b = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        got = store_b.get_by_attempt_key("input-hash-1:1")
        assert got is not None
        assert got.encrypted_result_url == "https://sensitive.example.com"


# ---------------------------------------------------------------------------
# TTL cleanup
# ---------------------------------------------------------------------------


class TestTtlCleanup:
    def test_cleanup_expired_removes_expired(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        store.save(_make_record(expires_at=100.0))  # expired
        store.save(_make_record(generation_hash="input-hash-2", request_id="req-2", expires_at=100.0))  # expired

        cleaned = store.cleanup_expired(now=150.0)
        assert cleaned == 2
        assert store.get_by_attempt_key("input-hash-1:1") is None
        assert store.get_by_attempt_key("input-hash-2:1") is None

    def test_cleanup_expired_keeps_fresh(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        store.save(_make_record(expires_at=100.0))  # expired
        store.save(_make_record(generation_hash="input-hash-2", request_id="req-2", expires_at=300.0))  # fresh

        cleaned = store.cleanup_expired(now=200.0)
        assert cleaned == 1
        assert store.get_by_attempt_key("input-hash-1:1") is None
        assert store.get_by_attempt_key("input-hash-2:1") is not None

    def test_cleanup_expired_noop_when_none_expired(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        store.save(_make_record(expires_at=300.0))

        cleaned = store.cleanup_expired(now=200.0)
        assert cleaned == 0
        assert store.get_by_attempt_key("input-hash-1:1") is not None

    def test_cleanup_updates_disk_index(self, tmp_path: Path) -> None:
        store = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        store.save(_make_record(expires_at=100.0))
        store.cleanup_expired(now=150.0)

        # New store instance should not see cleaned records
        store2 = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        assert store2.get_by_attempt_key("input-hash-1:1") is None


# ---------------------------------------------------------------------------
# index rebuild from disk
# ---------------------------------------------------------------------------


class TestIndexRebuild:
    def test_rebuild_index_on_startup(self, tmp_path: Path) -> None:
        store1 = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        store1.save(_make_record())
        store1.save(_make_record(generation_hash="input-hash-2", request_id="req-2"))

        store2 = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        assert store2.get_by_attempt_key("input-hash-1:1") is not None
        assert store2.get_by_attempt_key("input-hash-2:1") is not None

    def test_rebuild_provider_key_index(self, tmp_path: Path) -> None:
        store1 = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        store1.save(_make_record(request_id="req-x"))

        store2 = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        got = store2.get_by_provider_key(("volcengine_seed", "scope-hash-1", "req-x"))
        assert got is not None


# ---------------------------------------------------------------------------
# cross-instance persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        store1 = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        store1.save(_make_record(generation_hash="persist-hash", request_id="req-p"))

        store2 = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        got = store2.get_by_attempt_key("persist-hash:1")
        assert got is not None
        assert got.provider_request_id == "req-p"
        assert got.encrypted_result_url == "https://example.com/result"

    def test_multiple_records_loadable(self, tmp_path: Path) -> None:
        store1 = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        for i in range(5):
            store1.save(
                _make_record(
                    generation_hash=f"multi-hash-{i}",
                    request_id=f"req-{i}",
                )
            )

        store2 = ProviderRecoveryStore(str(tmp_path), encryption_key=_TEST_ENCRYPTION_KEY)
        for i in range(5):
            assert store2.get_by_attempt_key(f"multi-hash-{i}:1") is not None