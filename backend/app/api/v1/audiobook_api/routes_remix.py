from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import BackgroundTasks, Body, Depends, HTTPException

from app.api.v1.audiobook_api import router
from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_active_chapter_audio_for_project,
    get_owned_audiobook_project,
)
from app.schemas.audiobook import RemixChapterRequest
from app.services.audiobook.background_jobs_remix import (
    CHAPTER_REMIX_RUN_TYPE,
    collect_chapter_remix_missing_segments,
    run_chapter_remix_background,
)
from app.services.audiobook.chapter_segment_assets import (
    repair_legacy_segment_signatures,
)
from app.services.audiobook.repository import ChapterAudioRunRepository
from app.services.audiobook.task_support import (
    update_chapter_run_state as _update_chapter_run_state,
)

logger = logging.getLogger(__name__)


@router.post("/projects/{audiobook_project_id}/chapters/{chapter_id}/remix")
async def remix_chapter(
    audiobook_project_id: int,
    chapter_id: int,
    request: RemixChapterRequest = Body(default_factory=RemixChapterRequest),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """手动触发整章重新混音。

    - 片段有缺失且未确认（force=False）时返回缺失列表，不触发混音；
    - 用户确认后（force=True）跳过缺失片段，后台用最新片段重新混合整章。
    """
    db = owned.db
    chapter_audio = get_active_chapter_audio_for_project(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    # 同章节互斥：存在进行中的重混任务时拒绝重复提交，避免串写状态
    active_run = ChapterAudioRunRepository.get_latest_run(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=CHAPTER_REMIX_RUN_TYPE,
    )
    if active_run is not None and str(active_run.status or "") in {"pending", "running"}:
        raise HTTPException(status_code=409, detail="该章节已有进行中的重新混音任务，请等待完成后再试")

    # 存量自愈：旧版不可复现的片段签名重写为当前格式，
    # 避免历史管线片段被误报为 stale_audio 缺失
    if repair_legacy_segment_signatures(
        chapter_audio,
        owner_user_id=getattr(getattr(owned, "current_user", None), "id", None),
    ):
        db.commit()

    missing_segments = collect_chapter_remix_missing_segments(chapter_audio)
    force = bool(request.force)

    if missing_segments and not force:
        return {
            "success": False,
            "requires_confirmation": True,
            "missing_segments": missing_segments,
        }

    _update_chapter_run_state(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=CHAPTER_REMIX_RUN_TYPE,
        status="running",
        current_stage="remixing",
        progress=0.0,
        checkpoint_patch={"missing_segments": missing_segments},
    )
    db.commit()

    # 捕获本次创建的 run ID，worker 按该 ID 定向更新状态
    remix_run = ChapterAudioRunRepository.get_latest_run(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=CHAPTER_REMIX_RUN_TYPE,
    )
    remix_run_id = remix_run.id if remix_run is not None else None

    background_tasks.add_task(
        run_chapter_remix_background,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        force=force,
        output_format=str(request.output_format or "mp3"),
        generate_subtitle=bool(request.generate_subtitle),
        run_id=remix_run_id,
    )

    return {
        "success": True,
        "status": "remix_queued",
        "force": force,
        "run_id": remix_run_id,
        "missing_segments": missing_segments,
    }


@router.get("/projects/{audiobook_project_id}/chapters/{chapter_id}/remix-status")
async def get_chapter_remix_status(
    audiobook_project_id: int,
    chapter_id: int,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """查询章节最近一次整章重新混音的状态与产物信息。"""
    db = owned.db
    run = ChapterAudioRunRepository.get_latest_run(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=CHAPTER_REMIX_RUN_TYPE,
    )
    if run is None:
        return {"success": True, "remix_status": "idle"}

    checkpoint: Dict[str, Any] = {}
    raw_checkpoint = getattr(run, "checkpoint_json", None)
    if isinstance(raw_checkpoint, str):
        try:
            checkpoint = json.loads(raw_checkpoint)
        except (json.JSONDecodeError, TypeError):
            checkpoint = {}
    elif isinstance(raw_checkpoint, dict):
        checkpoint = raw_checkpoint

    return {
        "success": True,
        "remix_status": str(getattr(run, "status", "") or ""),
        "current_stage": getattr(run, "current_stage", None),
        "progress": float(getattr(run, "progress", 0.0) or 0.0),
        "error_message": getattr(run, "error_message", None),
        "output_path": checkpoint.get("output_path"),
        "duration": checkpoint.get("duration"),
        "segment_timings": checkpoint.get("segment_timings") or [],
        "missing_segments": checkpoint.get("missing_segments") or [],
        "updated_at": getattr(run, "updated_at", None),
    }
