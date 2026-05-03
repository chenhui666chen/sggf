from __future__ import annotations

from typing import List

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.schemas.audiobook import (
    AudiobookTaskStatus,
)
from app.services.audiobook.repository import AudiobookTaskRepository
from app.services.audiobook.task_support import (
    build_task_status_response,
)
from app.api.v1.audiobook_api import router

@router.get("/tasks/{task_id}/status", response_model=AudiobookTaskStatus)
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询指定任务的持久化队列状态。"""
    task = AudiobookTaskRepository.get_task_for_user(db, task_id, current_user.id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )
    return build_task_status_response(task)


@router.get("/tasks", response_model=List[AudiobookTaskStatus])
async def list_all_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户最近的有声书后台任务。"""
    tasks = AudiobookTaskRepository.list_tasks_for_user(db, current_user.id)
    return [build_task_status_response(task) for task in tasks]

