"""openid 确定性查找哈希 + 加密存储（P2-4.1）。

背景：openid 属于高敏感字段（可关联实名/社交身份），数据库泄露等同于身份泄露。

方案：
- `lookup_hash`：HMAC-SHA256 确定性哈希，落 UNIQUE 索引，用于等值查询。
  不能用 Fernet/AES-GCM 密文做等值查询——密文带随机 IV，每次加密结果都不同。
- `encrypt` / `decrypt`：Fernet（AES-128-CBC + HMAC-SHA256）密文，用于还原原始 openid。

密钥分离：`OPENID_LOOKUP_KEY` 与 `OPENID_ENCRYPTION_KEY` 是两把独立密钥。
lookup key 轮换需离线重算全表哈希（最痛），encryption key 轮换只需"旧 key 解密、新 key 加密"。
"""
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class OpenIDCryptoNotConfiguredError(RuntimeError):
    """未配置 openid 密钥。生产/staging 由启动检查前置拦截，此处为纵深防御。"""


class OpenIDDecryptError(ValueError):
    """openid 密文无法解密（如加密密钥已轮换，票据需重新签发）。"""


class OpenIDCrypto:
    """openid 的确定性查找哈希 + 可逆加密。"""

    def __init__(self, lookup_key: str, encryption_key: str):
        self._lookup_key = lookup_key.encode("utf-8")
        self._cipher = Fernet(encryption_key.encode("utf-8"))

    def lookup_hash(self, openid: str) -> str:
        """确定性查找哈希：同一 openid 恒定同一结果，供 UNIQUE 索引等值查询。"""
        return hmac.new(self._lookup_key, openid.encode("utf-8"), hashlib.sha256).hexdigest()

    def encrypt(self, openid: str) -> str:
        """加密存储（带随机 IV，不可用于查询）。"""
        return self._cipher.encrypt(openid.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """还原原始 openid；密钥不匹配或密文损坏时抛 OpenIDDecryptError。"""
        try:
            return self._cipher.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError) as exc:
            raise OpenIDDecryptError("openid 密文无法解密，请重新发起授权") from exc


def build_openid_crypto() -> OpenIDCrypto | None:
    """按配置构造加密器；未配置时返回 None（未启用第三方登录的环境不阻断启动）。"""
    lookup_key = str(settings.OPENID_LOOKUP_KEY or "").strip()
    encryption_key = str(settings.OPENID_ENCRYPTION_KEY or "").strip()
    if not lookup_key or not encryption_key:
        return None

    try:
        return OpenIDCrypto(lookup_key, encryption_key)
    except (ValueError, TypeError) as exc:
        # 快速失败：格式错误的密钥若静默降级，会等到用户授权登录时才炸，且现象难以定位
        raise ValueError(
            "OPENID_ENCRYPTION_KEY 不是合法的 Fernet 密钥"
            "（32 字节 urlsafe-base64，可用 python -c "
            '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 生成）'
        ) from exc


openid_crypto: OpenIDCrypto | None = build_openid_crypto()


def get_openid_crypto() -> OpenIDCrypto:
    """获取加密器；未配置时抛错，由路由转换为 503。"""
    if openid_crypto is None:
        raise OpenIDCryptoNotConfiguredError(
            "未配置 OPENID_LOOKUP_KEY / OPENID_ENCRYPTION_KEY"
        )
    return openid_crypto
