"""运行时数据库兼容性补丁。

说明：
- 正式环境仍应以 Alembic 迁移为准。
- 这里仅处理开发/测试环境中常见的“模型已更新，但本地库遗漏某个新增列”的场景，
  以避免应用在启动后被单个缺列问题直接阻断。
"""

from __future__ import annotations

import logging
from threading import Lock

from sqlalchemy import inspect, text

from app.db.base import engine


logger = logging.getLogger(__name__)

_schema_compat_lock = Lock()
_schema_compat_checked = False


def ensure_runtime_schema_compatibility() -> None:
    """补齐少量幂等、无损的运行时列兼容。

    当前处理：
    - characters.genre_fields_json
    - projects.review_config
    """

    global _schema_compat_checked

    if _schema_compat_checked:
        return

    with _schema_compat_lock:
        if _schema_compat_checked:
            return

        try:
            inspector = inspect(engine)
            if inspector.has_table("characters"):
                existing_columns = {
                    column["name"] for column in inspector.get_columns("characters")
                }
                if "genre_fields_json" not in existing_columns:
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                """
                                ALTER TABLE characters
                                ADD COLUMN IF NOT EXISTS genre_fields_json TEXT
                                """
                            )
                        )
                    logger.warning(
                        "检测到 characters.genre_fields_json 缺失，已在运行时自动补齐。"
                        "正式环境仍建议执行 Alembic 迁移以保持版本链一致。"
                    )
            if inspector.has_table("projects"):
                existing_columns = {
                    column["name"] for column in inspector.get_columns("projects")
                }
                if "review_config" not in existing_columns:
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                """
                                ALTER TABLE projects
                                ADD COLUMN IF NOT EXISTS review_config TEXT
                                """
                            )
                        )
                    logger.warning(
                        "检测到 projects.review_config 缺失，已在运行时自动补齐。"
                        "正式环境仍建议执行 Alembic 迁移以保持版本链一致。"
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("运行时数据库兼容性补丁执行失败: %s", exc)
        finally:
            _schema_compat_checked = True
