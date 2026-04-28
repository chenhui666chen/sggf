"""根据当前接入配置重建模型中心基础卡片。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.base import SessionLocal
from app.services.model_catalog_bootstrap import build_model_catalog_card_payloads
from app.services.model_catalog_sync import sync_model_catalog_entries


def bootstrap_model_catalog_cards(*, prune_stale: bool = False) -> dict[str, int | bool | list[str]]:
    """将当前已接入模型写入模型中心。"""

    payloads = build_model_catalog_card_payloads()
    db: Session = SessionLocal()
    now = datetime.now(timezone.utc)

    try:
        result = sync_model_catalog_entries(
            db,
            payloads,
            prune_stale=prune_stale,
            now=now,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="同步模型中心基础卡片")
    parser.add_argument(
        "--prune-stale",
        action="store_true",
        help="删除数据库中已不在当前集成模型列表里的历史卡片",
    )
    args = parser.parse_args()

    result = bootstrap_model_catalog_cards(prune_stale=args.prune_stale)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
