"""
审计日志服务（P2-4.4，脱敏）。

- IP / User-Agent 只存 HMAC-SHA256 哈希（独立 AUDIT_LOG_PEPPER）；
- 绝不记录：验证码、token、openid、email、phone、密码；
- failure_reason 只存非敏感类别（not_found / invalid_password / locked / disabled），
  不携带任何账号信息；
- 保留 AUDIT_LOG_RETENTION_DAYS（默认 90）天，超期由 cleanup 删除（懒清理 + 脚本）。
"""
import hashlib
import hmac
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.utils.datetime_utils import utc_now

# 事件类型常量（入库前统一拼写，便于检索）
EVENT_LOGIN = "login"
EVENT_LOGIN_FAILED = "login_failed"
EVENT_LOGOUT = "logout"
EVENT_REGISTER = "register"
EVENT_REFRESH = "refresh"
EVENT_REFRESH_FAILED = "refresh_failed"
EVENT_OAUTH_LOGIN = "oauth_login"
EVENT_OAUTH_REGISTER = "oauth_register"
EVENT_BIND = "bind"
EVENT_UNBIND = "unbind"
EVENT_PASSWORD_CHANGE = "password_change"
EVENT_PASSWORD_SET = "password_set"
EVENT_PASSWORD_RESET = "password_reset"
EVENT_PHONE_BIND = "phone_bind"
EVENT_PHONE_TAKEOVER = "phone_takeover"
EVENT_ACCOUNT_DELETE = "account_delete"
EVENT_DATA_EXPORT = "data_export"

# 失败原因类别（不含账号信息，防侧信道）
FAILURE_NOT_FOUND = "not_found"
FAILURE_INVALID_PASSWORD = "invalid_password"
FAILURE_LOCKED = "locked"
FAILURE_DISABLED = "disabled"
FAILURE_INVALID_REFRESH = "invalid_refresh"
FAILURE_OAUTH_ERROR = "oauth_error"


def audit_pepper() -> str:
    pepper = str(settings.AUDIT_LOG_PEPPER or "").strip()
    if not pepper:
        raise ValueError("AUDIT_LOG_PEPPER 未配置：审计日志哈希退化为已知 key，禁止记录")
    return pepper


def audit_hash(value: str) -> str:
    """确定性脱敏哈希（HMAC-SHA256）。空 pepper 直接拒绝（fail-closed）。"""
    return hmac.new(audit_pepper().encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def audit_ip_hash(ip: Optional[str]) -> Optional[str]:
    if not ip:
        return None
    return audit_hash(str(ip).strip())


def audit_user_agent_hash(user_agent: Optional[str]) -> Optional[str]:
    if not user_agent:
        return None
    return audit_hash(str(user_agent).strip())


def record_audit(
    db: Session,
    *,
    event_type: str,
    user_id: Optional[int] = None,
    provider: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True,
    failure_reason: Optional[str] = None,
) -> AuditLog:
    """记录一条审计日志。

    独立 commit：调用方（登录失败等）随后可能 raise，不能把审计写入拖进被回滚的事务。
    """
    log = AuditLog(
        event_type=event_type,
        user_id=user_id,
        provider=(provider or None),
        ip_hash=audit_ip_hash(ip),
        user_agent_hash=audit_user_agent_hash(user_agent),
        success=success,
        failure_reason=failure_reason,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def cleanup_expired_audit_logs(db: Session, retention_days: Optional[int] = None) -> int:
    """删除超过保留期的审计日志（懒清理/脚本共用），返回删除条数。"""
    days = retention_days if retention_days is not None else int(settings.AUDIT_LOG_RETENTION_DAYS or 90)
    cutoff = utc_now() - timedelta(days=days)
    result = db.query(AuditLog).filter(AuditLog.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return int(result)
