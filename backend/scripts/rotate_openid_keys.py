"""openid 密钥轮换脚本（P2-4.1）。

两把密钥的轮换代价完全不同：

- **加密密钥（OPENID_ENCRYPTION_KEY）**：旧 key 解密 + 新 key 加密，可随时在线轮换。
- **查找哈希密钥（OPENID_LOOKUP_KEY）**：换 key 后所有索引值失效，必须逐行重算。
  借助仍未轮换的密文列还原明文 openid，所以"离线重算"可以在线完成；
  若密文列也不可用（两把密钥同时泄露），就只能拿 openid 明文清单离线重算了。

约束：

- 一次只轮换一把密钥（同时轮换会让中间态无法回滚）；
- 默认 dry-run，写库必须显式 `--apply`；
- 轮换后 Redis 中在途建号票据不可解，`/oauth/confirm` 已按"票据过期"返回 400，
  用户重新授权即可（脚本结束时也会提示）。

用法（在 backend 目录下执行）：

    # 预览（默认 dry-run，不写库）
    python scripts/rotate_openid_keys.py --new-encryption-key <key>
    # 落库
    python scripts/rotate_openid_keys.py --new-encryption-key <key> --apply
    # 轮换查找哈希密钥
    python scripts/rotate_openid_keys.py --rotate-lookup --new-lookup-key <key> --apply

新密钥也可通过环境变量 `OPENID_ENCRYPTION_KEY_NEW` / `OPENID_LOOKUP_KEY_NEW` 传入
（推荐，避免密钥出现在 shell 历史与进程列表里）。
"""
import argparse
import hashlib
import hmac
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

from app.core.config import settings  # noqa: E402


ENCRYPTED_FIELDS = (
    "alipay_openid_encrypted",
    "wechat_openid_encrypted",
    "wechat_unionid_encrypted",
)
HASH_FIELDS = ("alipay_openid_hash", "wechat_openid_hash", "wechat_unionid_hash")


def _select_openid_rows(connection) -> list:
    columns = ", ".join(("id", "username", *ENCRYPTED_FIELDS, *HASH_FIELDS))
    where = " OR ".join(f"{field} IS NOT NULL" for field in ENCRYPTED_FIELDS)
    return (
        connection.execute(sa.text(f"SELECT {columns} FROM users WHERE {where}"))
        .mappings()
        .fetchall()
    )


def _update_row(connection, row, updates: dict) -> None:
    assignments = ", ".join(f"{key} = :{key}" for key in updates)
    connection.execute(
        sa.text(f"UPDATE users SET {assignments} WHERE id = :id"),
        {**updates, "id": row["id"]},
    )


def rotate_encryption_key(connection, old_cipher: Fernet, new_cipher: Fernet, *, apply: bool) -> int:
    """用新加密密钥重写全部 openid 密文，返回处理行数（明文不变）。"""
    updated = 0
    for row in _select_openid_rows(connection):
        updates = {}
        for field in ENCRYPTED_FIELDS:
            ciphertext = row[field]
            if not ciphertext:
                continue
            plaintext = old_cipher.decrypt(str(ciphertext).encode("ascii"))
            updates[field] = new_cipher.encrypt(plaintext).decode("ascii")
        if not updates:
            continue
        if apply:
            _update_row(connection, row, updates)
        updated += 1
    return updated


def rotate_lookup_key(connection, cipher: Fernet, new_lookup_key: bytes, *, apply: bool) -> int:
    """用新查找密钥重算全部 openid 哈希，返回处理行数。

    username 不动：它是用户可见且可自行修改的标识，派生自"建号当时的 lookup key"，
    轮换后新用户按新 key 派生、老用户保持原值，唯一性由索引保证。
    """
    updated = 0
    for row in _select_openid_rows(connection):
        updates = {}
        for encrypted_field, hash_field in zip(ENCRYPTED_FIELDS, HASH_FIELDS):
            ciphertext = row[encrypted_field]
            if not ciphertext:
                continue
            plaintext = cipher.decrypt(str(ciphertext).encode("ascii"))
            updates[hash_field] = hmac.new(
                new_lookup_key, plaintext, hashlib.sha256
            ).hexdigest()
        if not updates:
            continue
        if apply:
            _update_row(connection, row, updates)
        updated += 1
    return updated


def _build_engine():
    return sa.create_engine(settings.DATABASE_URL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="openid 密钥轮换（P2-4.1）")
    parser.add_argument(
        "--rotate-lookup",
        action="store_true",
        help="轮换查找哈希密钥（默认轮换加密密钥）",
    )
    parser.add_argument(
        "--new-encryption-key",
        default=os.getenv("OPENID_ENCRYPTION_KEY_NEW", ""),
        help="新的 Fernet 加密密钥（也可用 OPENID_ENCRYPTION_KEY_NEW 传入）",
    )
    parser.add_argument(
        "--new-lookup-key",
        default=os.getenv("OPENID_LOOKUP_KEY_NEW", ""),
        help="新的查找哈希密钥（也可用 OPENID_LOOKUP_KEY_NEW 传入）",
    )
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run 只统计）")
    args = parser.parse_args(argv)

    mode = "查找哈希密钥" if args.rotate_lookup else "加密密钥"
    new_key = (
        str(args.new_lookup_key).strip() if args.rotate_lookup else str(args.new_encryption_key).strip()
    )
    if not new_key:
        print(
            f"缺少新{mode}：请用 --new-{'lookup' if args.rotate_lookup else 'encryption'}-key "
            f"或环境变量 OPENID_{'LOOKUP' if args.rotate_lookup else 'ENCRYPTION'}_KEY_NEW 提供"
        )
        return 2

    current_encryption_key = str(settings.OPENID_ENCRYPTION_KEY or "").strip()
    if not current_encryption_key:
        print("未配置当前 OPENID_ENCRYPTION_KEY：无法解密现有数据，轮换中止")
        return 2

    cipher = Fernet(current_encryption_key.encode("utf-8"))
    if args.rotate_lookup:
        if new_key == str(settings.OPENID_LOOKUP_KEY or "").strip():
            print("新查找密钥与当前密钥相同，无需轮换")
            return 2
        new_lookup_key = new_key.encode("utf-8")
        new_cipher = None
    else:
        if new_key == current_encryption_key:
            print("新加密密钥与当前密钥相同，无需轮换")
            return 2
        new_cipher = Fernet(new_key.encode("utf-8"))
        new_lookup_key = None

    engine = _build_engine()
    try:
        with engine.connect() as connection:
            with connection.begin():
                if args.rotate_lookup:
                    updated = rotate_lookup_key(
                        connection, cipher, new_lookup_key, apply=args.apply
                    )
                else:
                    updated = rotate_encryption_key(
                        connection, cipher, new_cipher, apply=args.apply
                    )
                if not args.apply:
                    connection.rollback()
    except Exception as exc:  # noqa: BLE001 - 轮换失败必须整体回滚，不留半成品
        print(f"轮换失败（已回滚）：{exc}")
        return 1

    action = "已轮换" if args.apply else "待轮换（dry-run，未写库）"
    print(f"{mode}{action}：影响 {updated} 行")
    if args.apply:
        print(
            "注意：① 需同步更新部署环境的密钥配置并重启服务；"
            "② Redis 中在途建号票据将不可解，用户重新授权即可（/oauth/confirm 返回 400）。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
