"""
账户注销后匿名化服务（P2-4.3 / 架构文档 5.3）。

冷静期（ACCOUNT_DELETE_COOLING_DAYS）后调用：
- username → deleted_{id}（唯一派生标识，不保留可反推原名的信息）；
- email / phone / full_name / avatar_url / password_hash / openid 哈希与密文全部清空；
- password_history 一并删除（密码类用户数据）；
- 保留：审计日志（脱敏，90 天后清理）、同意记录（合规证明，永久保留）、
  账单记录（7 年法定保留，本服务不触碰账单表）。
"""
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.password_history import PasswordHistory
from app.models.user import User
from app.utils.datetime_utils import utc_now


def anonymize_expired_accounts(
    db: Session,
    cooling_days: int | None = None,
    *,
    apply_write: bool = True,
) -> int:
    """匿名化超过冷静期的已注销账号，返回处理数量。

    apply_write=False 时仅统计（dry-run，不产生任何写入/变更）。
    """
    days = cooling_days if cooling_days is not None else int(settings.ACCOUNT_DELETE_COOLING_DAYS or 30)
    cutoff = utc_now() - timedelta(days=days)

    expired = (
        db.query(User)
        .filter(User.deleted_at.isnot(None), User.deleted_at < cutoff)
        .all()
    )

    if not apply_write:
        return len(expired)

    for user in expired:
        user.username = f"deleted_{user.id}"
        user.email = None
        user.phone = None
        user.full_name = None
        user.avatar_url = None
        user.password_hash = None
        user.email_verified = False
        user.email_verified_at = None
        user.consent_version = None
        user.token_version += 1  # 即使有残留会话也全部失效

        for field in ("alipay", "wechat"):
            setattr(user, f"{field}_openid_hash", None)
            setattr(user, f"{field}_openid_encrypted", None)
        user.wechat_unionid_hash = None
        user.wechat_unionid_encrypted = None

        # 密码历史属用户数据，随匿名化清空（审计日志/同意记录保留）
        db.query(PasswordHistory).filter(PasswordHistory.user_id == user.id).delete(
            synchronize_session=False
        )

    if expired:
        db.commit()
    return len(expired)


def purge_expired_audit_logs(db: Session, retention_days: int | None = None) -> int:
    """清理超期审计日志（90 天，5.3）。与 audit_log_service.cleanup 同语义，供脚本复用。"""
    from app.services.audit_log_service import cleanup_expired_audit_logs

    return cleanup_expired_audit_logs(db, retention_days)
