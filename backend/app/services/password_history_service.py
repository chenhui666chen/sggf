"""密码历史服务（P2-4.6）。

- 只存 HMAC-SHA256(pepper, password) 十六进制，绝不存 bcrypt/明文；
- pepper（PASSWORD_HISTORY_PEPPER）与登录哈希、openid 密钥完全分离；
- 每用户保留最近 PASSWORD_HISTORY_SIZE 条（含当前密码）：注册/设密/改密/重置
  都追加当前密码，因此"新密码 ≠ 当前密码"由历史检查自然覆盖，无需单独比较；
- 检查在写入新 password_hash 之前；追加与清理与业务同事务（由调用方 commit）。
"""
import hashlib
import hmac

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.password_history import PasswordHistory


def hash_password_for_history(password: str) -> str:
    """密码历史专用 HMAC（与登录 bcrypt 哈希、openid 查找哈希互不复用）。

    评审 #6：空 pepper 的 HMAC 退化为已知 key 哈希（等价 SHA256），任何环境都拒绝。
    """
    pepper = str(settings.PASSWORD_HISTORY_PEPPER or "").strip()
    if not pepper:
        raise ValueError("PASSWORD_HISTORY_PEPPER 未配置：密码历史哈希禁止使用空密钥")
    return hmac.new(pepper.encode("utf-8"), password.encode("utf-8"), hashlib.sha256).hexdigest()


class PasswordHistoryService:
    """历史密码的检查与登记（纯数据库，无 Redis 依赖）。"""

    # 保留最近 N 条（含当前密码）；可经 PASSWORD_HISTORY_SIZE 配置覆盖（评审 #9）
    HISTORY_SIZE = 3

    @property
    def history_size(self) -> int:
        return max(int(settings.PASSWORD_HISTORY_SIZE), 1)

    def recent_hashes(self, db: Session, user_id: int, limit: int | None = None) -> list[str]:
        rows = (
            db.query(PasswordHistory.password_pepper_hash)
            .filter(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.id.desc())
            .limit(limit or self.history_size)
            .all()
        )
        return [row[0] for row in rows]

    def is_reused(self, db: Session, user_id: int, password: str) -> bool:
        """新密码是否命中最近 history_size 条历史（HMAC 确定性，等值比对）。"""
        return hash_password_for_history(password) in self.recent_hashes(db, user_id)

    def record(self, db: Session, user_id: int, password: str) -> None:
        """追加当前密码摘要并清理超出保留数的旧行（不 commit，由调用方统一提交）。"""
        db.add(
            PasswordHistory(
                user_id=user_id,
                password_pepper_hash=hash_password_for_history(password),
            )
        )
        db.flush()  # 取到自增 id，便于按保留数精确清理
        stale_ids = (
            db.query(PasswordHistory.id)
            .filter(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.id.desc())
            .offset(self.history_size)
            .all()
        )
        if stale_ids:
            db.query(PasswordHistory).filter(
                PasswordHistory.id.in_([row[0] for row in stale_ids])
            ).delete(synchronize_session=False)


password_history_service = PasswordHistoryService()
