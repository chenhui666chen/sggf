"""
实验隐私模块测试（设计文档 §10：授权位 / 原文短期载荷加密+TTL+删除 / 日志禁文本）
"""
import json
import logging
from pathlib import Path

import pytest

from app.services.prompt_evolution.experiment_privacy import (
    ExperimentConsentRegistry,
    PayloadVault,
)


SECRET_TEXT = "林昭雪握紧了手中的青铜剑，剑身上的裂纹泛着微光。"
KEY = "unit-test-payload-key"


# ============ 授权位（opt-in） ============

def test_consent_defaults_to_denied(tmp_path):
    registry = ExperimentConsentRegistry(storage_dir=str(tmp_path))
    assert registry.has_consent("user-1") is False


def test_consent_grant_and_revoke(tmp_path):
    registry = ExperimentConsentRegistry(storage_dir=str(tmp_path))
    registry.grant("user-1")
    assert registry.has_consent("user-1") is True
    registry.revoke("user-1")
    assert registry.has_consent("user-1") is False


def test_consent_persists_across_instances(tmp_path):
    ExperimentConsentRegistry(storage_dir=str(tmp_path)).grant("user-1")
    reloaded = ExperimentConsentRegistry(storage_dir=str(tmp_path))
    assert reloaded.has_consent("user-1") is True
    assert reloaded.has_consent("user-2") is False


# ============ 载荷保险库：opaque reference ============

def test_put_returns_opaque_reference(tmp_path):
    vault = PayloadVault(encryption_key=KEY, storage_dir=str(tmp_path))
    ref = vault.put("user-1", SECRET_TEXT)
    # 引用不泄露原文与主体标识
    assert SECRET_TEXT not in ref
    assert "user-1" not in ref
    assert len(ref) >= 16


def test_roundtrip_get_returns_original_text(tmp_path):
    vault = PayloadVault(encryption_key=KEY, storage_dir=str(tmp_path))
    ref = vault.put("user-1", SECRET_TEXT)
    assert vault.get(ref) == SECRET_TEXT


def test_get_unknown_reference_returns_none(tmp_path):
    vault = PayloadVault(encryption_key=KEY, storage_dir=str(tmp_path))
    assert vault.get("nonexistent-ref") is None


# ============ 静态加密：磁盘上不得出现明文 ============

def test_payload_encrypted_at_rest(tmp_path):
    vault = PayloadVault(encryption_key=KEY, storage_dir=str(tmp_path))
    vault.put("user-1", SECRET_TEXT)
    plaintext_bytes = SECRET_TEXT.encode("utf-8")
    for file in Path(tmp_path).rglob("*"):
        if file.is_file():
            assert plaintext_bytes not in file.read_bytes(), f"明文泄露: {file}"


def test_index_does_not_contain_text(tmp_path):
    vault = PayloadVault(encryption_key=KEY, storage_dir=str(tmp_path))
    vault.put("user-1", SECRET_TEXT)
    index_file = Path(tmp_path) / "payload_index.json"
    assert index_file.exists()
    index = json.loads(index_file.read_text(encoding="utf-8"))
    assert SECRET_TEXT not in json.dumps(index, ensure_ascii=False)


# ============ TTL 与删除 ============

def test_expired_payload_returns_none_and_is_removed(tmp_path):
    vault = PayloadVault(encryption_key=KEY, storage_dir=str(tmp_path))
    ref = vault.put("user-1", SECRET_TEXT, ttl_seconds=-1)
    assert vault.get(ref) is None
    # 过期读取即清除，磁盘不残留
    assert vault.get(ref) is None
    remaining = [f for f in Path(tmp_path).glob("*.bin")]
    assert remaining == []


def test_purge_expired_removes_only_expired(tmp_path):
    vault = PayloadVault(encryption_key=KEY, storage_dir=str(tmp_path))
    expired_ref = vault.put("user-1", SECRET_TEXT, ttl_seconds=-1)
    alive_ref = vault.put("user-2", SECRET_TEXT, ttl_seconds=3600)
    removed = vault.purge_expired()
    assert removed == 1
    assert vault.get(expired_ref) is None
    assert vault.get(alive_ref) == SECRET_TEXT


def test_delete_removes_payload(tmp_path):
    vault = PayloadVault(encryption_key=KEY, storage_dir=str(tmp_path))
    ref = vault.put("user-1", SECRET_TEXT)
    assert vault.delete(ref) is True
    assert vault.get(ref) is None
    assert vault.delete(ref) is False


def test_delete_by_subject_removes_only_that_subject(tmp_path):
    vault = PayloadVault(encryption_key=KEY, storage_dir=str(tmp_path))
    r1 = vault.put("user-1", SECRET_TEXT)
    r2 = vault.put("user-1", SECRET_TEXT + "第二段")
    r3 = vault.put("user-2", SECRET_TEXT)
    removed = vault.delete_by_subject("user-1")
    assert removed == 2
    assert vault.get(r1) is None
    assert vault.get(r2) is None
    assert vault.get(r3) == SECRET_TEXT


# ============ 失败关闭与日志纪律 ============

def test_empty_encryption_key_fails_closed(tmp_path):
    with pytest.raises(ValueError):
        PayloadVault(encryption_key="", storage_dir=str(tmp_path))


def test_logs_never_contain_payload_text(tmp_path, caplog):
    with caplog.at_level(logging.DEBUG):
        vault = PayloadVault(encryption_key=KEY, storage_dir=str(tmp_path))
        ref = vault.put("user-1", SECRET_TEXT)
        vault.get(ref)
        vault.delete(ref)
    assert SECRET_TEXT not in caplog.text
