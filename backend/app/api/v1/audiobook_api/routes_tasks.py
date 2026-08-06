from __future__ import annotations

from typing import List, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.audiobook import ChapterAudioRun
from app.models.user import User
from app.schemas.audiobook import (
    AudiobookTaskStatus,
)
from app.services.audiobook.job_tracker import (
    PAUSED_STATUS,
    PAUSE_REQUESTED_STATUS,
)
from app.services.audiobook.repository import AudiobookTaskRepository
from app.services.audiobook.task_support import (
    build_task_status_response,
    enqueue_audiobook_task,
    ensure_audiobook_points_precheck_passed,
    resolve_audiobook_billing_pricing_context,
    safe_record_audiobook_billing_freeze,
)
from app.services.audiobook.task_trace import build_audiobook_trace_context
from app.services.audiobook.tts_model_ids import normalize_audiobook_tts_model
from app.services.points_task_precheck import build_audiobook_task_points_precheck
from app.utils.datetime_utils import utc_now
from app.api.v1.audiobook_api import router
from app.api.v1.audiobook_api.dependencies import resolve_owned_audiobook_project

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


@router.post("/tasks/{task_id}/pause", response_model=AudiobookTaskStatus)
async def pause_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """请求暂停一个运行中的有声书生成任务。

    暂停为协作式：API 仅将任务状态置为 pause_requested，
    Worker 会在下一个章节边界检测到后真正停止并落库为 paused，
    因此暂停可能在当前章节处理完后才生效。
    """
    task = AudiobookTaskRepository.get_task_for_user(db, task_id, current_user.id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )

    current_status = str(task.status or "").strip().lower()
    if current_status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前任务状态为 {task.status or '未知'}，仅运行中的任务可以暂停",
        )

    task.status = PAUSE_REQUESTED_STATUS
    task.updated_at = utc_now()
    db.commit()
    db.refresh(task)
    return build_task_status_response(task)


@router.post("/tasks/{task_id}/resume", response_model=dict)
async def resume_task(
    task_id: str,
    raw_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """继续一个已暂停或正在暂停的有声书生成任务。

    对 ``pause_requested`` 状态撤销暂停请求，原 Worker 会继续当前任务；
    对 ``paused`` 状态从暂停时记录的剩余章节断点重新入队一个新任务，
    并沿用原任务的 TTS/叙事等生成配置，同时重新进行积分预检与冻结。
    """
    task = AudiobookTaskRepository.get_task_for_user(db, task_id, current_user.id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )

    current_status = str(task.status or "").strip().lower()
    if current_status == PAUSE_REQUESTED_STATUS:
        task.status = "running"
        task.updated_at = utc_now()
        db.commit()
        db.refresh(task)
        return {
            "success": True,
            "audiobook_project_id": task.audiobook_project_id,
            "job_id": None,
            "task_type": task.task_type,
            "message": "已继续当前生成任务",
        }

    if current_status != PAUSED_STATUS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前任务状态为 {task.status or '未知'}，仅已暂停或正在暂停的任务可以继续",
        )

    detail = task.detail_json or {}
    remaining_chapter_ids = [
        int(chapter_id)
        for chapter_id in (detail.get("remaining_chapter_ids") or detail.get("chapter_ids") or [])
        if chapter_id is not None
    ]
    if not remaining_chapter_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="没有可恢复的章节",
        )

    owned = resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=task.audiobook_project_id,
    )
    project = owned.project

    # 从原任务的章节运行记录中恢复生成配置，保证恢复后沿用相同参数。
    source_run = _resolve_resume_source_run(db, task.celery_task_id, remaining_chapter_ids)
    tts_model = normalize_audiobook_tts_model(
        (source_run.tts_model if source_run else None) or detail.get("tts_model")
    )
    output_format = source_run.output_format if source_run else None
    narration_style = source_run.narration_style if source_run else None
    narration_style_prompt = source_run.narration_style_prompt if source_run else None
    generate_subtitle = (
        bool((source_run.checkpoint_json or {}).get("generate_subtitle", True))
        if source_run
        else True
    )

    billing_context = resolve_audiobook_billing_pricing_context(
        project=project,
        tts_pricing_key=tts_model,
    )
    precheck = build_audiobook_task_points_precheck(
        db=db,
        user_id=current_user.id,
        project_id=project.id,
        project_title=project.title,
        chapter_ids=remaining_chapter_ids,
        tts_provider=tts_model,
        audio_engine_mode=billing_context.audio_engine_mode,
    )
    ensure_audiobook_points_precheck_passed(precheck)

    _, async_result = enqueue_audiobook_task(
        db,
        audiobook_project_id=task.audiobook_project_id,
        chapter_ids=remaining_chapter_ids,
        job_type=task.task_type,
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
        generate_subtitle=generate_subtitle,
    )

    safe_record_audiobook_billing_freeze(
        db=db,
        current_user=current_user,
        audiobook_project_id=task.audiobook_project_id,
        chapter_ids=remaining_chapter_ids,
        raw_request=raw_request,
        tts_pricing_key=billing_context.pricing_key,
        estimated_yuan_override=precheck.estimated_yuan,
        trace_context=build_audiobook_trace_context(
            celery_task_id=str(async_result.id),
            task_type=task.task_type,
            audiobook_project_id=task.audiobook_project_id,
            status="queued",
            progress=0.0,
            tts_model=tts_model,
            cost_precheck_id=precheck.cost_precheck_id,
        ),
    )

    return {
        "success": True,
        "audiobook_project_id": task.audiobook_project_id,
        "job_id": async_result.id,
        "task_type": task.task_type,
        "message": "任务已恢复，剩余章节已进入队列",
        "total_chapters": len(remaining_chapter_ids),
        "chapter_ids": remaining_chapter_ids,
    }


def _resolve_resume_source_run(
    db: Session,
    celery_task_id: Optional[str],
    remaining_chapter_ids: List[int],
) -> Optional[ChapterAudioRun]:
    """选取用于恢复生成配置的原始章节运行记录。

    优先选择属于剩余章节的运行记录，其次任选一条原任务的运行记录。
    """
    if not celery_task_id:
        return None
    runs = (
        db.query(ChapterAudioRun)
        .filter(ChapterAudioRun.celery_task_id == celery_task_id)
        .order_by(ChapterAudioRun.created_at.desc(), ChapterAudioRun.id.desc())
        .all()
    )
    if not runs:
        return None
    remaining_set = set(remaining_chapter_ids)
    for run in runs:
        if run.chapter_id in remaining_set:
            return run
    return runs[0]

