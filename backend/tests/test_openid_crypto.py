"""openid 确定性查找哈希 + 加密存储测试（P2-4.1）。

设计约束（架构文档 4.1）：
- 查找必须用确定性哈希：Fernet/AES-GCM 带随机 nonce，密文不可做等值查询；
- lookup key 与 encryption key 必须分离：一处泄露不得同时破译索引与密文。
"""
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app.core.crypto as crypto  # noqa: E402
from app.core.crypto import (  # noqa: E402
    OpenIDCrypto,
    OpenIDCryptoNotConfiguredError,
    OpenIDDecryptError,
    get_openid_crypto,
)


def _crypto(lookup_key: str = "lookup-key-a") -> OpenIDCrypto:
    return OpenIDCrypto(lookup_key, Fernet.generate_key().decode())


def test_lookup_hash_is_deterministic_and_hides_openid():
    """同值恒等、异值不同，且哈希中不出现明文（用于 UNIQUE 等值查找）。"""
    crypto_obj = _crypto()
    assert crypto_obj.lookup_hash("2088001") == crypto_obj.lookup_hash("2088001")
    assert crypto_obj.lookup_hash("2088001") != crypto_obj.lookup_hash("2088002")
    assert "2088001" not in crypto_obj.lookup_hash("2088001")


def test_lookup_hash_changes_with_lookup_key():
    """换 lookup key 后索引值全变：轮换必须离线重算全表哈希（故设计为极低频轮换）。"""
    encryption_key = Fernet.generate_key().decode()
    first = OpenIDCrypto("lookup-key-a", encryption_key).lookup_hash("2088001")
    second = OpenIDCrypto("lookup-key-b", encryption_key).lookup_hash("2088001")
    assert first != second


def test_encrypt_is_non_deterministic_so_cannot_be_used_for_lookup():
    """密文带随机 IV：两次加密结果不同，证明不可用于等值查询（必须走 lookup_hash）。"""
    crypto_obj = _crypto()
    assert crypto_obj.encrypt("2088001") != crypto_obj.encrypt("2088001")


def test_decrypt_restores_original_openid():
    crypto_obj = _crypto()
    assert crypto_obj.decrypt(crypto_obj.encrypt("wx-open-1")) == "wx-open-1"


def test_ciphertext_cannot_be_decrypted_with_other_encryption_key():
    """加密密钥隔离：换 key 后旧密文不可解（轮换语义：旧 key 解密、新 key 加密）。"""
    old_crypto = OpenIDCrypto("lookup-key-a", Fernet.generate_key().decode())
    new_crypto = OpenIDCrypto("lookup-key-a", Fernet.generate_key().decode())
    with pytest.raises(OpenIDDecryptError):
        new_crypto.decrypt(old_crypto.encrypt("2088001"))


def test_get_openid_crypto_raises_when_keys_not_configured(monkeypatch):
    """密钥缺失时显式报错（生产/staging 由启动检查前置拦截，此处为纵深防御）。"""
    monkeypatch.setattr(crypto, "openid_crypto", None)
    with pytest.raises(OpenIDCryptoNotConfiguredError):
        get_openid_crypto()


def test_build_openid_crypto_returns_none_without_keys(monkeypatch):
    monkeypatch.setattr(crypto.settings, "OPENID_LOOKUP_KEY", "")
    monkeypatch.setattr(crypto.settings, "OPENID_ENCRYPTION_KEY", "")
    assert crypto.build_openid_crypto() is None


def test_build_openid_crypto_rejects_malformed_encryption_key(monkeypatch):
    """错误格式的加密密钥必须快速失败并给出可操作的提示，不能静默降级为不可用。"""
    monkeypatch.setattr(crypto.settings, "OPENID_LOOKUP_KEY", "lookup-key-a")
    monkeypatch.setattr(crypto.settings, "OPENID_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(ValueError, match="OPENID_ENCRYPTION_KEY"):
        crypto.build_openid_crypto()
