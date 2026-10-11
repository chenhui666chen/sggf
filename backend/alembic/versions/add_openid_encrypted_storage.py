"""users openid 加密存储（P2 批次 A：4.1）

- 新增 6 列：支付宝 openid、微信 openid、微信 unionid 各自对应
  `{field}_hash`（HMAC-SHA256 确定性查找哈希，UNIQUE）与 `{field}_encrypted`（Fernet 密文）；
- 存量明文回填后删除 3 个明文字段列（无存量真实用户，硬切换，无兼容窗口）；
- 存量 OAuth 用户的 `username` 一并重算：旧格式 `alipay_{openid后12位}` 含明文片段，
  而 username 随 UserResponse 下发前端，等于把 openid 大部分泄露出去；
  改为 `alipay_{lookup_hash(openid)前12位}`，不可反推。
- downgrade 反向执行：先解密回明文列，再按明文后 12 位恢复旧 username，最后删除新列。

回填依赖 OPENID_LOOKUP_KEY / OPENID_ENCRYPTION_KEY，未配置时直接中止迁移，
避免在库里留下"半加密"状态（那比明文更难恢复）。

Revision ID: add_openid_encrypted_storage
Revises: add_email_verification_nullable_email
Create Date: 2026-08-31
"""
import hashlib
import hmac

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet

from app.core.config import settings


revision = "add_openid_encrypted_storage"
down_revision = "add_email_verification_nullable_email"
branch_labels = None
depends_on = None


OPENID_FIELDS = ("alipay_openid", "wechat_openid", "wechat_unionid")
USERNAME_SUFFIX_LENGTH = 12


def _load_keys() -> tuple[bytes, Fernet]:
    lookup_key = str(settings.OPENID_LOOKUP_KEY or "").strip()
    encryption_key = str(settings.OPENID_ENCRYPTION_KEY or "").strip()
    if not lookup_key or not encryption_key:
        raise RuntimeError(
            "迁移 add_openid_encrypted_storage 需要配置 OPENID_LOOKUP_KEY 与 OPENID_ENCRYPTION_KEY"
        )
    return lookup_key.encode("utf-8"), Fernet(encryption_key.encode("utf-8"))


def _lookup_hash(lookup_key: bytes, openid: str) -> str:
    return hmac.new(lookup_key, openid.encode("utf-8"), hashlib.sha256).hexdigest()


def _provider_and_openid(row) -> tuple[str, str] | None:
    """按字段优先级还原"建号时用于派生 username 的 openid"。

    与 OAuthService._allocate_username 的调用口径一致：微信优先用 openid（不是 unionid）。
    """
    if row.get("alipay_openid"):
        return "alipay", str(row["alipay_openid"]).strip()
    if row.get("wechat_openid"):
        return "wechat", str(row["wechat_openid"]).strip()
    if row.get("wechat_unionid"):
        return "wechat", str(row["wechat_unionid"]).strip()
    return None


def _unique_username(base: str, taken: set[str]) -> str:
    """冲突时按 _allocate_username 的同款 _N 递增口径。"""
    candidate = base
    index = 1
    while candidate in taken:
        index += 1
        candidate = f"{base}_{index}"
    taken.add(candidate)
    return candidate


def upgrade() -> None:
    lookup_key, cipher = _load_keys()

    for field in OPENID_FIELDS:
        op.add_column("users", sa.Column(f"{field}_hash", sa.String(length=64), nullable=True))
        op.add_column("users", sa.Column(f"{field}_encrypted", sa.Text(), nullable=True))

    connection = op.get_bind()
    legacy_columns = ", ".join(OPENID_FIELDS)
    rows = connection.execute(
        sa.text(
            f"SELECT id, username, {legacy_columns} FROM users "
            f"WHERE {' OR '.join(f'{field} IS NOT NULL' for field in OPENID_FIELDS)}"
        )
    ).mappings().fetchall()

    taken_usernames = {
        row[0] for row in connection.execute(sa.text("SELECT username FROM users")).fetchall()
    }

    for row in rows:
        updates = {}
        for field in OPENID_FIELDS:
            value = str(row[field] or "").strip()
            if not value:
                continue
            updates[f"{field}_hash"] = _lookup_hash(lookup_key, value)
            updates[f"{field}_encrypted"] = cipher.encrypt(value.encode("utf-8")).decode("ascii")

        derived = _provider_and_openid(row)
        if derived:
            provider, openid = derived
            if openid:
                # 自身旧 username 不参与冲突判定（否则同值会被误判为占用并加后缀）
                taken_usernames.discard(row["username"])
                new_username = _unique_username(
                    f"{provider}_{_lookup_hash(lookup_key, openid)[:USERNAME_SUFFIX_LENGTH]}".lower(),
                    taken_usernames,
                )
                if new_username != row["username"]:
                    updates["username"] = new_username

        if not updates:
            continue
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        connection.execute(
            sa.text(f"UPDATE users SET {assignments} WHERE id = :id"),
            {**updates, "id": row["id"]},
        )

    # UNIQUE 索引：并发建号时防止同一 openid 落两行（明文列原本只是普通索引）
    for field in OPENID_FIELDS:
        op.create_index(op.f(f"ix_users_{field}_hash"), "users", [f"{field}_hash"], unique=True)

    for field in OPENID_FIELDS:
        op.drop_column("users", field)


def downgrade() -> None:
    _, cipher = _load_keys()

    for field in OPENID_FIELDS:
        op.add_column("users", sa.Column(field, sa.String(length=255), nullable=True))

    connection = op.get_bind()
    encrypted_columns = ", ".join(f"{field}_encrypted" for field in OPENID_FIELDS)
    rows = connection.execute(
        sa.text(
            f"SELECT id, {encrypted_columns} FROM users "
            f"WHERE {' OR '.join(f'{field}_encrypted IS NOT NULL' for field in OPENID_FIELDS)}"
        )
    ).mappings().fetchall()

    for row in rows:
        updates = {}
        for field in OPENID_FIELDS:
            ciphertext = row[f"{field}_encrypted"]
            if not ciphertext:
                continue
            updates[field] = cipher.decrypt(str(ciphertext).encode("ascii")).decode("utf-8")
        if not updates:
            continue
        assignments = ", ".join(f"{key} = :{key}" for key in updates)
        connection.execute(
            sa.text(f"UPDATE users SET {assignments} WHERE id = :id"),
            {**updates, "id": row["id"]},
        )

    # 恢复旧格式 username（明文后 12 位口径）：此时明文列已回填，可直接重算
    legacy_columns = ", ".join(OPENID_FIELDS)
    rows = connection.execute(
        sa.text(
            f"SELECT id, username, {legacy_columns} FROM users "
            f"WHERE {' OR '.join(f'{field} IS NOT NULL' for field in OPENID_FIELDS)}"
        )
    ).mappings().fetchall()
    taken_usernames = {
        row[0] for row in connection.execute(sa.text("SELECT username FROM users")).fetchall()
    }
    for row in rows:
        derived = _provider_and_openid(row)
        if not derived:
            continue
        provider, openid = derived
        taken_usernames.discard(row["username"])
        old_username = _unique_username(
            f"{provider}_{openid[-USERNAME_SUFFIX_LENGTH:]}".lower(), taken_usernames
        )
        if old_username == row["username"]:
            continue
        connection.execute(
            sa.text("UPDATE users SET username = :username WHERE id = :id"),
            {"username": old_username, "id": row["id"]},
        )

    for field in OPENID_FIELDS:
        op.drop_index(op.f(f"ix_users_{field}_hash"), table_name="users")
        op.drop_column("users", f"{field}_hash")
        op.drop_column("users", f"{field}_encrypted")
        op.create_index(op.f(f"ix_users_{field}"), "users", [field], unique=False)
