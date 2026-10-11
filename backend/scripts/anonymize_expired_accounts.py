"""注销账户匿名化脚本（P2-4.3 / 5.3）。

对超过冷静期（ACCOUNT_DELETE_COOLING_DAYS，默认 30 天）的已注销账号执行匿名化：
- username → deleted_{id}；email/phone/full_name/avatar_url/password_hash/openid 全部清空；
- password_history 一并删除；
- 保留审计日志（脱敏）与同意记录（合规证明）；
- 默认 dry-run（只统计不写库），落库须显式 `--apply`。

用法（backend 目录下）：

    # 预览
    python scripts/anonymize_expired_accounts.py
    # 落库
    python scripts/anonymize_expired_accounts.py --apply
    # 顺带清理超期审计日志（90 天）
    python scripts/anonymize_expired_accounts.py --apply --purge-audit
"""
import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402


def _build_engine():
    return create_engine(settings.DATABASE_URL, pool_pre_ping=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="注销账户匿名化（冷静期后）")
    parser.add_argument("--apply", action="store_true", help="落库（默认 dry-run 只统计）")
    parser.add_argument("--purge-audit", action="store_true", help="顺带清理超期审计日志")
    args = parser.parse_args(argv)

    from app.services.account_anonymization_service import anonymize_expired_accounts

    engine = _build_engine()
    with Session(engine) as db:
        users = anonymize_expired_accounts(db, apply_write=args.apply)
        prefix = "" if args.apply else "[dry-run] "
        print(f"{prefix}注销账户匿名化: {users} 个")

        if args.purge_audit and args.apply:
            from app.services.audit_log_service import cleanup_expired_audit_logs

            purged = cleanup_expired_audit_logs(db)
            print(f"已清理超期审计日志: {purged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
