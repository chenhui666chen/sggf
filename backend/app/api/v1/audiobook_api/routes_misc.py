from __future__ import annotations

import json
import logging

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.services.audiobook.sse_progress import sse_tracker
from app.services.audiobook.repository import (
    AudiobookTaskRepository,
)

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

@router.get(
    "/tasks/{task_id}/stream",
    summary="Stream audiobook task progress",
    description="Recommended realtime progress channel for audiobook tasks. Clients should keep polling as a fallback.",
)
async def stream_task_progress(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 实时进度推送端点

    客户端连接后将持续接收任务进度事件
    """
    from fastapi.responses import StreamingResponse

    task = AudiobookTaskRepository.get_task_for_user(db, task_id, current_user.id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )
    # StreamingResponse 可能长时间保持连接，权限校验后不再占用数据库会话。
    db.close()

    async def event_generator():
        try:
            async for event in sse_tracker.stream_events(task_id):
                yield event
        except Exception as exc:
            logger.warning("Audiobook SSE stream failed: task_id=%s error=%s", task_id, exc)
            yield (
                "data: "
                + json.dumps(
                    {
                        "event": "error",
                        "data": {
                            "task_id": task_id,
                            "message": "progress_stream_unavailable",
                            "retryable": True,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
