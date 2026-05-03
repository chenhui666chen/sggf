from __future__ import annotations

import logging
import os
import json
from pathlib import Path

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.schemas.audiobook import (
    GenerationCheckpointResponse,
)
from app.services.audiobook.safe_filename import build_safe_filename
from app.services.audiobook.repository import (
    ChapterAudioRunRepository,
)
from app.services.audiobook.task_support import (
    build_generation_checkpoint_payload as _build_generation_checkpoint_payload,
    build_run_checkpoint_document as _build_run_checkpoint_document,
    enqueue_audiobook_task as _enqueue_audiobook_task,
    ensure_audiobook_points_precheck_passed as _ensure_audiobook_points_precheck_passed,
)
from app.services.audiobook.tts_model_ids import normalize_audiobook_tts_model
from app.services.points_task_precheck import (
    build_audiobook_task_points_precheck,
)
from app.services.user_center_points_events import (
    record_audiobook_billing_freeze,
)
from app.utils.datetime_utils import utc_now

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/subtitle")
async def get_chapter_subtitle(
    audiobook_project_id: int,
    chapter_id: int,
    format: str = Query("srt", pattern="^(srt|vtt|ass|labels|audacity)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取章节字幕文件"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="有声书项目不存在")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="无权限访问")
    
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    if not chapter_audio:
        raise HTTPException(status_code=404, detail="章节音频记录不存在")
    
    if not chapter_audio.subtitle_path:
        raise HTTPException(status_code=404, detail="字幕文件不存在")
    
    subtitle_file = chapter_audio.subtitle_path
    if format == "vtt":
        subtitle_file = str(Path(subtitle_file).with_suffix(".vtt"))
    elif format == "ass":
        subtitle_file = str(Path(subtitle_file).with_suffix(".ass"))
    elif format in {"labels", "audacity"}:
        subtitle_file = str(Path(subtitle_file).with_suffix(".labels.txt"))
    
    if not os.path.exists(subtitle_file):
        raise HTTPException(status_code=404, detail="字幕文件不存在")
    
    download_extension = ".labels.txt" if format in {"labels", "audacity"} else f".{format}"
    download_filename = build_safe_filename(
        f"chapter_{chapter_id}",
        download_extension,
        fallback="chapter",
    )

    return FileResponse(
        subtitle_file,
        media_type="text/plain",
        filename=download_filename,
    )


@router.get(
    "/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/checkpoint",
    response_model=GenerationCheckpointResponse,
)
async def get_generation_checkpoint(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取生成断点信息（用于断点续传）"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="有声书项目不存在")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="无权限访问")
    
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    return _build_generation_checkpoint_payload(
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        run_type=None,
        db=db,
        audiobook_project_id=audiobook_project_id,
    )


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/resume-generation")
async def resume_chapter_generation(
    audiobook_project_id: int,
    chapter_id: int,
    raw_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从断点继续生成章节音频"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="有声书项目不存在")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="无权限访问")
    
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    if not chapter_audio:
        raise HTTPException(status_code=404, detail="章节音频记录不存在")
    
    checkpoint_payload = _build_generation_checkpoint_payload(
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        run_type=None,
        db=db,
        audiobook_project_id=audiobook_project_id,
    )
    if not checkpoint_payload["can_resume"]:
        blockers = checkpoint_payload.get("resume_blockers") or []
        detail = "没有可恢复的生成进度"
        if blockers:
            detail = f"当前不可恢复: {', '.join(blockers)}"
        raise HTTPException(status_code=400, detail=detail)

    resume_task_type = str(checkpoint_payload.get("resume_task_type") or "full").strip().lower()
    tts_model = normalize_audiobook_tts_model(checkpoint_payload.get("tts_model"))
    output_format = checkpoint_payload.get("output_format")
    narration_style = checkpoint_payload.get("narration_style")
    narration_style_prompt = checkpoint_payload.get("narration_style_prompt")
    generate_subtitle = checkpoint_payload.get("generate_subtitle", True) is not False

    if resume_task_type != "script_only":
        precheck = build_audiobook_task_points_precheck(
            db=db,
            user_id=current_user.id,
            project_id=project.id,
            project_title=project.title,
            chapter_ids=[chapter_id],
            tts_provider=tts_model,
        )
        _ensure_audiobook_points_precheck_passed(precheck)

    def bind_resume_checkpoint_before_dispatch(_task_record, celery_task_id: str) -> None:
        latest_run = ChapterAudioRunRepository.get_latest_run(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type=resume_task_type,
        )
        if not latest_run or latest_run.celery_task_id != celery_task_id:
            logger.warning(
                "跳过断点恢复绑定: chapter_id=%s, expected_task=%s, actual_task=%s",
                chapter_id,
                celery_task_id,
                getattr(latest_run, "celery_task_id", None),
            )
            return

        resumed_checkpoint_json = _build_run_checkpoint_document(
            db,
            run=latest_run,
            chapter_id=chapter_id,
            audiobook_project_id=audiobook_project_id,
            chapter_audio=chapter_audio,
            status=latest_run.status,
            current_stage="resume_requested",
            checkpoint_patch={
                "resumed_from_run_id": checkpoint_payload.get("run_id"),
                "resume_requested_at": utc_now().isoformat(),
                "resume_validation_mode": checkpoint_payload.get("resume_validation_mode"),
                "resume_blockers": checkpoint_payload.get("resume_blockers") or [],
                "source_checkpoint": checkpoint_payload.get("checkpoint_document") or {},
                "source_checkpoint_source": checkpoint_payload.get("checkpoint_source"),
                "source_run_status": checkpoint_payload.get("run_status"),
                "source_current_stage": checkpoint_payload.get("current_stage"),
                "source_completed_segments": checkpoint_payload.get("completed_segments"),
                "source_total_segments": checkpoint_payload.get("total_segments"),
                "completed_segment_indices": checkpoint_payload.get("completed_segment_indices") or [],
                "cached_audio_paths": checkpoint_payload.get("cached_audio_paths") or {},
            },
        )
        ChapterAudioRunRepository.update_run(
            db,
            latest_run,
            current_stage="resume_requested",
            checkpoint_json=resumed_checkpoint_json,
        )

    _, async_result = _enqueue_audiobook_task(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=[chapter_id],
        job_type=resume_task_type,
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
        generate_subtitle=generate_subtitle,
        before_dispatch=bind_resume_checkpoint_before_dispatch,
    )

    if resume_task_type != "script_only":
        try:
            record_audiobook_billing_freeze(
                db=db,
                actor_user_id=current_user.id,
                actor_username=current_user.username,
                audiobook_project_id=audiobook_project_id,
                chapter_ids=[chapter_id],
                request_context=raw_request,
                tts_pricing_key=tts_model,
            )
        except Exception as exc:
            logger.warning(
                "记录有声书积分冻结失败 audiobook_project_id=%s chapter_id=%s: %s",
                audiobook_project_id,
                chapter_id,
                exc,
            )

    logger.info(
        "Resume queued for audiobook_project_id=%s chapter_id=%s source_run_id=%s new_job_id=%s completed=%s/%s task_type=%s",
        audiobook_project_id,
        chapter_id,
        checkpoint_payload.get("run_id"),
        async_result.id,
        checkpoint_payload.get("completed_segments"),
        checkpoint_payload.get("total_segments"),
        resume_task_type,
    )

    return {
        "message": "恢复任务已进入队列",
        "job_id": async_result.id,
        "task_type": resume_task_type,
        "resumed_from_run_id": checkpoint_payload.get("run_id"),
        "source_run_status": checkpoint_payload.get("run_status"),
        "source_current_stage": checkpoint_payload.get("current_stage"),
        "completed_segments": checkpoint_payload.get("completed_segments"),
        "total_segments": checkpoint_payload.get("total_segments"),
        "completed_segment_indices": checkpoint_payload.get("completed_segment_indices"),
        "cached_audio_paths": checkpoint_payload.get("cached_audio_paths"),
        "checkpoint_source": checkpoint_payload.get("checkpoint_source"),
        "resume_validation_mode": checkpoint_payload.get("resume_validation_mode"),
        "resume_blockers": checkpoint_payload.get("resume_blockers") or [],
    }


@router.get("/projects/{audiobook_project_id:int}/browser-player")
async def get_browser_player_data(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取浏览器播放器所需数据（章节列表、音频URL、字幕URL）"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="有声书项目不存在")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="无权限访问")
    
    chapters_data = []
    for chapter_audio in audiobook_project.chapter_audios:
        chapter = db.query(Chapter).filter(Chapter.id == chapter_audio.chapter_id).first()
        if not chapter:
            continue
        
        chapter_info = {
            "chapter_id": chapter_audio.chapter_id,
            "chapter_number": chapter.chapter_number,
            "chapter_title": chapter.title,
            "audio_url": f"/api/v1/audiobook/download/{audiobook_project_id}/{chapter_audio.chapter_id}",
            "duration": chapter_audio.duration,
            "has_subtitle": bool(chapter_audio.subtitle_path and os.path.exists(chapter_audio.subtitle_path)),
            "subtitle_url": f"/api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_audio.chapter_id}/subtitle" if chapter_audio.subtitle_path else None,
            "audacity_labels_url": f"/api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_audio.chapter_id}/subtitle?format=labels" if chapter_audio.subtitle_path else None,
        }
        
        if chapter_audio.script_json:
            try:
                chapter_info["segments"] = json.loads(chapter_audio.script_json)
            except:
                chapter_info["segments"] = []
        
        chapters_data.append(chapter_info)
    
    return {
        "project_id": audiobook_project_id,
        "project_title": project.title,
        "chapters": chapters_data,
        "total_duration": audiobook_project.total_duration,
    }


