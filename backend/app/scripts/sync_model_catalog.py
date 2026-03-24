"""手动同步模型档案中心数据。"""

from __future__ import annotations

import json

from app.db.base import SessionLocal
from app.services.model_catalog_sync import get_model_catalog_sync_service


def main() -> int:
    """执行一次模型档案同步并打印摘要。"""

    db = SessionLocal()
    try:
        service = get_model_catalog_sync_service()
        result = service.sync_catalog(db, force_refresh=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"模型档案同步失败: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
