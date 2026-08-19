from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

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

    # §1.5（GUIDE 验收 8/19）：恢复输入改以 run_input_snapshot（方案 A 自包含
    # 正文）为输入——不读取项目当前活跃引擎与实时配置；无快照回退 run 列/实时。
    source_run = _resolve_resume_source_run(
        db,
        task.celery_task_id,
        remaining_chapter_ids,
        task_db_id=task.id,
    )
    snapshot_payload = _parse_run_input_snapshot(
        getattr(source_run, "run_input_snapshot", None)
    ) if source_run else None
    signed = (snapshot_payload or {}).get("signed_payload", {})
    run_options = signed.get("run_options") if isinstance(signed, dict) else None
    engine_payload = (
        signed.get("engine_config_payload")
        if isinstance(signed, dict)
        else None
    )
    resolved_engine_mode = (
        str(engine_payload.get("engine_mode") or "").strip()
        if isinstance(engine_payload, dict)
        else ""
    )

    tts_model = normalize_audiobook_tts_model(
        ((run_options or {}).get("tts_model") if run_options else None)
        or (source_run.tts_model if source_run else None)
        or detail.get("tts_model")
    )
    output_format = (
        (run_options or {}).get("output_format")
        if run_options and (run_options or {}).get("output_format")
        else (source_run.output_format if source_run else None)
    )
    narration_style = (
        (run_options or {}).get("narration_style")
        if run_options and (run_options or {}).get("narration_style")
        else (source_run.narration_style if source_run else None)
    )
    narration_style_prompt = (
        (run_options or {}).get("narration_style_prompt")
        if run_options and (run_options or {}).get("narration_style_prompt")
        else (source_run.narration_style_prompt if source_run else None)
    )
    generate_subtitle = (
        bool((run_options or {}).get("generate_subtitle", True))
        if run_options and "generate_subtitle" in run_options
        else (
            bool((source_run.checkpoint_json or {}).get("generate_subtitle", True))
            if source_run
            else True
        )
    )

    # 引擎模式从快照冻结值获取（冻结事实优先，无快照回退实时解析）
    if resolved_engine_mode:
        audio_engine_mode = resolved_engine_mode
    else:
        audio_engine_mode = resolve_audiobook_billing_pricing_context(
            project=project,
            tts_pricing_key=tts_model,
        ).audio_engine_mode
    # 计费键跟随引擎模式（seed_scene → seed 模型键；legacy → tts 模型键）
    from app.services.audiobook.scene_engine.scene_billing import SEED_AUDIO_MODEL

    effective_pricing_key = (
        SEED_AUDIO_MODEL if audio_engine_mode == "seed_scene" else tts_model
    )
    precheck = build_audiobook_task_points_precheck(
        db=db,
        user_id=current_user.id,
        project_id=project.id,
        project_title=project.title,
        chapter_ids=remaining_chapter_ids,
        tts_provider=tts_model,
        audio_engine_mode=audio_engine_mode,
    )
    ensure_audiobook_points_precheck_passed(precheck)

    # R11/P0-2：入队 + 冻结同事务（账户锁 → enqueue → freeze → 统一 commit）
    from app.services.audiobook.task_support import lock_billing_account as _lock_billing_account

    _lock_billing_account(db, current_user.id)
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
        commit_result=False,
    )

    safe_record_audiobook_billing_freeze(
        db=db,
        current_user=current_user,
        audiobook_project_id=task.audiobook_project_id,
        chapter_ids=remaining_chapter_ids,
        raw_request=raw_request,
        tts_pricing_key=effective_pricing_key,
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
        raise_on_error=True,
    )
    # 统一提交（R11/P0-2 同事务冻结）
    db.commit()
    # 提交后即时派发（best-effort；失败由 dispatcher beat 兜底，R11/P0-1）
    try:
        from app.services.audiobook.task_support import (
            dispatch_pending_runs as _dispatch_pending_runs,
        )

        _dispatch_pending_runs(db, async_result.runs)
    except Exception as _exc:
        logger.warning("提交后派发失败（dispatcher 兜底）: %s", _exc)

    return {
        "success": True,
        "audiobook_project_id": task.audiobook_project_id,
        "job_id": async_result.id,
        "task_type": task.task_type,
        "message": "任务已恢复，剩余章节已进入队列",
        "total_chapters": len(remaining_chapter_ids),
        "chapter_ids": remaining_chapter_ids,
    }


def _parse_run_input_snapshot(raw: Optional[str]) -> Optional[dict]:
    """解析 run_input_snapshot JSON；缺失/损坏返回 None（回退实时解析）。"""
    import json

    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("signed_payload") else None


def _resolve_resume_source_run(
    db: Session,
    celery_task_id: Optional[str],
    remaining_chapter_ids: List[int],
    task_db_id: Optional[int] = None,
) -> Optional[ChapterAudioRun]:
    """选取用于恢复生成配置的原始章节运行记录。

    R13/P1-a（验收 66 展示投影）：优先按 ``AudiobookTaskDispatch`` 父子关系
    （task_id → run 列表）定位——纯 DB 投影、不做 broker 关联；历史 run
    （``legacy-`` 前缀 celery_task_id，无 TaskDispatch 记录）回退按
    celery_task_id 查询（展示投影兼容）。
    优先选择属于剩余章节的运行记录，其次任选一条原任务的运行记录。
    """
    runs: List[ChapterAudioRun] = []
    if task_db_id is not None:
        from app.models.audiobook import AudiobookTaskDispatch

        run_ids = (
            db.query(AudiobookTaskDispatch.run_id)
            .filter(AudiobookTaskDispatch.task_id == task_db_id)
            .order_by(AudiobookTaskDispatch.id.asc())
            .all()
        )
        run_ids = [row[0] for row in run_ids]
        if run_ids:
            runs = (
                db.query(ChapterAudioRun)
                .filter(ChapterAudioRun.id.in_(run_ids))
                .order_by(ChapterAudioRun.created_at.desc(), ChapterAudioRun.id.desc())
                .all()
            )
    if not runs and celery_task_id:
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

