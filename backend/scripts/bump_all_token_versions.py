"""应急脚本：批量递增所有用户 token_version（P1-2.5 / 架构文档 5.5 安全事件响应）。

适用场景（见架构文档 5.5 预案表）：
- JWT_SECRET 泄露 / 被提交到版本控制；
- OAuth 配置错误（app_secret 泄露等）；
- XSS 导致 token 泄露；
- 其他需要"强制全量重登"的安全事件。

递增 tv 后，所有已签发 access / refresh 立即失效（全设备下线），用户需重新登录。

默认 dry-run（只统计不写库），落库须显式 `--apply`。

用法（backend 目录下）：
    # 预览
    python scripts/bump_all_token_versions.py
    # 落库
    python scripts/bump_all_token_versions.py --apply
"""
import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, func  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.user import User  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="批量递增用户 token_version（安全事件应急）")
    parser.add_argument("--apply", action="store_true", help="落库（默认 dry-run 只统计）")
    args = parser.parse_args(argv)

    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    with Session(engine) as db:
        total = db.query(func.count(User.id)).scalar() or 0
        if not args.apply:
            print(f"[dry-run] 将递增 {total} 个用户的 token_version（加 --apply 落库）")
            return 0

        db.query(User).update({User.token_version: User.token_version + 1})
        db.commit()
        print(f"已递增 {total} 个用户的 token_version：全部已签发 access/refresh 立即失效（强制全量重登）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
