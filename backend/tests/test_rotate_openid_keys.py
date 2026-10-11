"""openid 密钥轮换脚本测试（P2-4.1）。

轮换分两种，代价不同：
- 加密密钥：旧 key 解密 + 新 key 加密，可在线轮换；
- 查找哈希密钥：换 key 后索引值全失效，必须逐行重算（借密文列还原明文）。
"""
import hashlib
import hmac
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

SCRIPT_PATH = ROOT_DIR / "scripts" / "rotate_openid_keys.py"


def _load_script():
    spec = spec_from_file_location("rotate_openid_keys_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载轮换脚本")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rotate = _load_script()

ENCRYPTED_COLUMNS = (
    "alipay_openid_encrypted",
    "wechat_openid_encrypted",
    "wechat_unionid_encrypted",
)
HASH_COLUMNS = ("alipay_openid_hash", "wechat_openid_hash", "wechat_unionid_hash")


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    columns = ", ".join(
        f"{column} VARCHAR(255)" for column in (*ENCRYPTED_COLUMNS, *HASH_COLUMNS)
    )
    with engine.begin() as connection:
        connection.execute(
            text(f"CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(255), {columns})")
        )
    return engine


def seed(db, cipher, lookup_key: bytes) -> None:
    rows = [
        (1, "alipay_aaa", {"alipay_openid_encrypted": "2088001"}),
        (2, "wechat_bbb", {"wechat_openid_encrypted": "wx-1", "wechat_unionid_encrypted": "union-1"}),
        (3, "local_user", {}),
    ]
    with db.begin() as connection:
        for user_id, username, values in rows:
            payload = {"id": user_id, "username": username}
            for field, plain in values.items():
                hash_field = field.replace("_encrypted", "_hash")
                payload[field] = cipher.encrypt(plain.encode("utf-8")).decode("ascii")
                payload[hash_field] = hmac.new(
                    lookup_key, plain.encode("utf-8"), hashlib.sha256
                ).hexdigest()
            columns = ", ".join(payload)
            placeholders = ", ".join(f":{key}" for key in payload)
            connection.execute(
                text(f"INSERT INTO users ({columns}) VALUES ({placeholders})"), payload
            )


def fetch(db, user_id: int) -> dict:
    with db.connect() as connection:
        row = connection.execute(
            text("SELECT * FROM users WHERE id = :id"), {"id": user_id}
        ).mappings().first()
    return dict(row)


def test_rotate_encryption_key_dry_run_leaves_rows_untouched(db):
    """默认 dry-run：只统计不写库（写操作必须先预览，避免半成品状态）。"""
    old_cipher = Fernet(Fernet.generate_key())
    new_cipher = Fernet(Fernet.generate_key())
    seed(db, old_cipher, b"lookup-a")
    before = fetch(db, 1)

    with db.connect() as connection:
        updated = rotate.rotate_encryption_key(connection, old_cipher, new_cipher, apply=False)

    assert updated == 2  # 两行有密文，第 3 行为本地用户
    assert fetch(db, 1) == before, "dry-run 不得改动数据"


def test_rotate_encryption_key_rewrites_ciphertext_with_new_key(db):
    """轮换后：新 key 可解、旧 key 不可解，明文不变。"""
    old_cipher = Fernet(Fernet.generate_key())
    new_cipher = Fernet(Fernet.generate_key())
    seed(db, old_cipher, b"lookup-a")

    with db.begin() as connection:
        updated = rotate.rotate_encryption_key(connection, old_cipher, new_cipher, apply=True)
    assert updated == 2

    row = fetch(db, 1)
    assert new_cipher.decrypt(row["alipay_openid_encrypted"].encode("ascii")) == b"2088001"
    with pytest.raises(InvalidToken):
        old_cipher.decrypt(row["alipay_openid_encrypted"].encode("ascii"))

    wechat_row = fetch(db, 2)
    assert new_cipher.decrypt(wechat_row["wechat_unionid_encrypted"].encode("ascii")) == b"union-1"


def test_rotate_lookup_key_recomputes_hashes_and_keeps_username(db):
    """lookup key 轮换重算全部哈希；username 是用户可见标识，不得随之改变。"""
    cipher = Fernet(Fernet.generate_key())
    seed(db, cipher, b"lookup-a")

    with db.begin() as connection:
        updated = rotate.rotate_lookup_key(connection, cipher, b"lookup-b", apply=True)
    assert updated == 2

    row = fetch(db, 1)
    expected = hmac.new(b"lookup-b", b"2088001", hashlib.sha256).hexdigest()
    assert row["alipay_openid_hash"] == expected
    assert row["username"] == "alipay_aaa", "username 不随 lookup key 轮换改变"
    assert cipher.decrypt(row["alipay_openid_encrypted"].encode("ascii")) == b"2088001"

    # 一行同时含 openid 与 unionid：两个哈希都要重算，不能漏字段
    wechat_row = fetch(db, 2)
    assert wechat_row["wechat_openid_hash"] == hmac.new(
        b"lookup-b", b"wx-1", hashlib.sha256
    ).hexdigest()
    assert wechat_row["wechat_unionid_hash"] == hmac.new(
        b"lookup-b", b"union-1", hashlib.sha256
    ).hexdigest()


def test_main_rejects_missing_new_key(monkeypatch, db, capsys):
    """未提供新密钥必须报错退出（非零），不得带着空密钥写库。"""
    monkeypatch.setattr(rotate, "_build_engine", lambda: db)
    exit_code = rotate.main(["--apply"])
    assert exit_code == 2
    assert "新加密密钥" in capsys.readouterr().out
