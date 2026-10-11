"""冷静期注销账号匿名化定时任务（P2-5.3）。

每日低频扫描超过冷却期（ACCOUNT_DELETE_COOLING_DAYS，默认 30 天）的已注销账号，
执行匿名化：清 PII/密码/openid、username 改为不可反推派生值、删除密码历史，
保留同意记录（合规证明）与审计日志（脱敏）。

幂等：匿名化后再扫描命中无副作用（字段已空、username 已是派生值）。
"""
import logging

from app.celery_app import celery_app
from app.db.base import SessionLocal
from app.services.account_anonymization_service import anonymize_expired_accounts

logger = logging.getLogger(__name__)


@celery_app.task(name="account.anonymize_expired", bind=True, max_retries=0)
def anonymize_expired_accounts_task(self) -> dict:
    """beat 每日入口：匿名化超过冷却期的已注销账号（直接落库，非 dry-run）。"""
    db = SessionLocal()
    try:
        count = anonymize_expired_accounts(db)
        logger.info("已注销账号匿名化完成：%s 个", count)
        return {"anonymized": count}
    except Exception:
        logger.exception("已注销账号匿名化任务失败")
        raise
    finally:
        db.close()
