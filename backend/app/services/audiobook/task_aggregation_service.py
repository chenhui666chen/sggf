"""父任务聚合服务（GUIDE §1.1 父任务聚合规则，R13/P0-a，R15/P1-1/R15/P1-3，R17/P1-2）。

核心职责：
- ``normalize_run_status``：SQL CASE 投影将数据库原始值归一化为规范化值。
- ``aggregate_parent_task_status``：基于规范化值的互斥矩阵判定父任务状态。
- ``refresh_parent_task_aggregation``：刷新父任务聚合状态并持久化。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookTaskDispatch, ChapterAudioRun
from app.models.audiobook_task import AudiobookTask
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 规范化值域
NORMALIZED_STATUSES = frozenset({
    "queued", "running", "paused", "pause_requested",
    "succeeded", "failed", "cancelled", "unknown",
})


def normalize_run_status(raw_status: Optional[str]) -> str:
    """SQL CASE 投影：数据库原始值 → 规范化值。

    与 GUIDE §1.1 ``normalize_run_status`` 同一事实源。
    ``completed`` 保持原值（是合法数据库态，投影映射 ``succeeded`` 在聚合中使用）。
    """
    status = str(raw_status or "").strip().lower()
    if status in ("pending", "queued"):
        return "queued"
    if status == "running":
        return "running"
    if status == "paused":
        return "paused"
    if status == "pause_requested":
        return "pause_requested"
    if status == "completed":
        return "succeeded"
    if status == "expired":
        return "cancelled"  # R15/P0-1：expired 归入 cancelled
    if status == "failed":
        return "failed"
    if status in ("canceled", "cancelled"):
        return "cancelled"
    return "unknown"


def aggregate_parent_task_status(
    db: Session,
    *,
    task_id: int,
) -> Dict[str, Any]:
    """基于规范化值的互斥矩阵判定父任务状态。

    聚合输入为 run 状态（经子派发 JOIN ChapterAudioRun 获得）。
    优先级自上而下，同一时刻只命中一条。

    返回 ``{"status": str, "detail": dict, "run_count": int}``。
    """
    # 获取该 task 的全部子派发 run 的规范化状态
    rows = (
        db.query(ChapterAudioRun.status)
        .join(
            AudiobookTaskDispatch,
            AudiobookTaskDispatch.run_id == ChapterAudioRun.id,
        )
        .filter(AudiobookTaskDispatch.task_id == task_id)
        .all()
    )

    if not rows:
        return {"status": None, "detail": {"run_count": 0}, "run_count": 0}

    normalized = [normalize_run_status(r.status) for r in rows]
    run_count = len(normalized)

    # 计数
    counts: Dict[str, int] = {}
    for s in normalized:
        counts[s] = counts.get(s, 0) + 1

    unknown_count = counts.get("unknown", 0)
    running_count = counts.get("running", 0) + counts.get("queued", 0) + counts.get("pause_requested", 0) + counts.get("paused", 0)
    succeeded_count = counts.get("succeeded", 0)
    cancelled_count = counts.get("cancelled", 0)
    failed_count = counts.get("failed", 0)

    # 互斥矩阵（R17/P1-2 穷尽规则）
    detail = {
        "run_count": run_count,
        "counts": counts,
        "normalized_statuses": normalized,
    }

    # ① 任一 unknown → fail-closed
    if unknown_count > 0:
        detail["error"] = "aggregation_unknown_status"
        return {"status": "failed", "detail": detail, "run_count": run_count}

    # ② 任一 running/queued/pause_requested/paused → running
    if running_count > 0:
        return {"status": "running", "detail": detail, "run_count": run_count}

    # ③ 全部 succeeded → completed
    if succeeded_count == run_count and run_count > 0:
        return {"status": "completed", "detail": detail, "run_count": run_count}

    # ④ 全部 cancelled → cancelled
    if cancelled_count == run_count and run_count > 0:
        return {"status": "cancelled", "detail": detail, "run_count": run_count}

    # ⑤ 至少一个 succeeded 且存在 failed/cancelled → completed_with_partial_failure
    if succeeded_count > 0 and (failed_count > 0 or cancelled_count > 0):
        return {"status": "completed_with_partial_failure", "detail": detail, "run_count": run_count}

    # ⑥ 无 succeeded 且至少一个 failed → failed
    if succeeded_count == 0 and failed_count > 0:
        return {"status": "failed", "detail": detail, "run_count": run_count}

    # 兜底（不应到达）
    logger.warning("父任务聚合未命中任何规则 task_id=%s counts=%s", task_id, counts)
    return {"status": "failed", "detail": detail, "run_count": run_count}


def refresh_parent_task_aggregation(
    db: Session,
    *,
    task_id: int,
) -> Dict[str, Any]:
    """刷新父任务聚合状态并持久化到 AudiobookTask。

    返回聚合结果。
    """
    result = aggregate_parent_task_status(db, task_id=task_id)

    if result["status"] is None:
        return result

    task = db.query(AudiobookTask).filter(AudiobookTask.id == task_id).first()
    if task is None:
        return result

    task.status = result["status"]
    task.detail_json = result.get("detail", {})

    # 进度 = Σ run.progress 加权（按 run 数）
    if result["run_count"] > 0:
        from sqlalchemy import func as sa_func
        avg_progress = (
            db.query(sa_func.avg(ChapterAudioRun.progress))
            .join(
                AudiobookTaskDispatch,
                AudiobookTaskDispatch.run_id == ChapterAudioRun.id,
            )
            .filter(AudiobookTaskDispatch.task_id == task_id)
            .scalar()
        )
        if avg_progress is not None:
            task.progress = round(float(avg_progress), 4)

    db.flush()
    return result


# 父任务状态值域（CHECK 两阶段收窄后的最终值域）
PARENT_TASK_STATUS_DOMAIN = (
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "completed_with_partial_failure",
)


__all__ = [
    "NORMALIZED_STATUSES",
    "PARENT_TASK_STATUS_DOMAIN",
    "aggregate_parent_task_status",
    "normalize_run_status",
    "refresh_parent_task_aggregation",
]
