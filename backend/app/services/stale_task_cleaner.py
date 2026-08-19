"""stale 任务自愈：后端启动时清理残留的 running/pending 任务。

任务以进程内 asyncio 协程执行，DB 中的 running 状态无法跨进程存活；
后端重启后这些行会永远卡住（前端轮询永无结果）。
启动时将其置为 failed 并注明原因；若误伤极小竞态窗口内的新任务，
任务完成时的状态覆盖写会自动纠正（见 dreamweaver_tasks_pkg._db）。
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_STALE_ERROR_MESSAGE = "服务重启，任务中断，请重新发起"


def cleanup_stale_generation_tasks(session: Session) -> int:
    """将残留 running/pending 的 generation_history 行标记为 failed。

    Returns:
        本次清理的行数。
    """
    result = session.execute(
        text(
            "UPDATE generation_history "
            "SET status = 'failed', error_message = :msg, updated_at = CURRENT_TIMESTAMP "
            "WHERE status IN ('running', 'pending')"
        ),
        {"msg": _STALE_ERROR_MESSAGE},
    )
    session.commit()
    cleaned = int(result.rowcount or 0)
    if cleaned:
        logger.warning("启动自愈：清理 %d 条残留 running/pending 任务 -> failed", cleaned)
    return cleaned
