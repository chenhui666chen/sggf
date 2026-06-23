from __future__ import annotations

import logging
from urllib.parse import quote
from typing import List, Optional, Dict, Any

from fastapi import Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project
from app.models.audiobook import ChapterAudio
from app.schemas.audiobook import (
    AudiobookProjectCreate,
    GenerateAudioFromScriptsRequest,
)
from app.celery_app import celery_app
from app.services.audiobook.project_exporter import (
    AudiobookExportError,
    build_project_audacity_export,
    build_project_m4b_export,
    resolve_project_audacity_output_file,
    resolve_project_m4b_output_file,
)
from app.services.audiobook.project_export_jobs import (
    PROJECT_EXPORT_STAGE,
    build_project_export_download_url,
    build_project_export_task_detail,
)
from app.services.audiobook.safe_filename import build_safe_filename
from app.services.audiobook.app_service import AudiobookAppService
from app.services.audiobook.repository import (
    AudiobookProjectRepository,
    ChapterAudioRepository,
    ChapterAudioRunRepository,
    ChapterRepository,
    ProjectRepository,
    AudiobookTaskRepository,
)
from app.services.audiobook.task_support import (
    build_generation_checkpoint_payload as _build_generation_checkpoint_payload,
    build_run_checkpoint_document as _build_run_checkpoint_document,
    enqueue_audiobook_task as _enqueue_audiobook_task,
    ensure_audiobook_points_precheck_passed as _ensure_audiobook_points_precheck_passed,
    safe_record_audiobook_billing_freeze as _safe_record_audiobook_billing_freeze,
)
from app.services.audiobook.task_trace import build_audiobook_trace_context
from app.services.audiobook.tts_model_ids import normalize_audiobook_tts_model
from app.services.points_task_precheck import (
    build_audiobook_task_points_precheck,
)
from app.utils.datetime_utils import utc_now

from app.api.v1.audiobook_api import router
from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_owned_audiobook_project,
    resolve_owned_audiobook_project,
)

logger = logging.getLogger(__name__)


def _attach_resume_checkpoints_to_queued_runs(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_audio_by_id: Dict[int, ChapterAudio],
    resume_payloads_by_chapter: Dict[int, Dict[str, Any]],
    celery_task_id: str,
) -> None:
    for chapter_id, checkpoint_payload in resume_payloads_by_chapter.items():
        latest_run = ChapterAudioRunRepository.get_latest_run(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type="audio_from_scripts",
        )
        if not latest_run or latest_run.celery_task_id != celery_task_id:
            logger.warning(
                "跳过断点来源绑定: chapter_id=%s, expected_task=%s, actual_task=%s",
                chapter_id,
                celery_task_id,
                getattr(latest_run, "celery_task_id", None),
            )
            continue

        resumed_checkpoint_json = _build_run_checkpoint_document(
            db,
            run=latest_run,
            chapter_id=chapter_id,
            audiobook_project_id=audiobook_project_id,
            chapter_audio=chapter_audio_by_id.get(chapter_id),
            status=latest_run.status,
            current_stage=latest_run.current_stage,
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
            checkpoint_json=resumed_checkpoint_json,
        )


def _queue_project_export_task(
    db: Session,
    *,
    audiobook_project_id: int,
    export_type: str,
    metadata: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> dict:
    task_type = "export_m4b" if export_type == "m4b" else "export_audacity"
    celery_task_name = "audiobook.export_m4b" if export_type == "m4b" else "audiobook.export_audacity"
    queued_message = "整本 M4B 导出任务已进入队列" if export_type == "m4b" else "Audacity ZIP 导出任务已进入队列"
    download_url = build_project_export_download_url(audiobook_project_id, export_type)

    task_record = AudiobookTaskRepository.create_task(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=None,
        task_type=task_type,
        total_units=1,
    )
    task_record.current_stage = PROJECT_EXPORT_STAGE
    task_record.detail_json = build_project_export_task_detail(
        audiobook_project_id=audiobook_project_id,
        export_type=export_type,
        status="pending",
        progress=0.0,
        message=queued_message,
        force=force,
        metadata=metadata,
    )
    db.add(task_record)
    db.commit()
    db.refresh(task_record)

    args: list[Any]
    if export_type == "m4b":
        args = [task_record.id, audiobook_project_id, metadata or {}, force]
    else:
        args = [task_record.id, audiobook_project_id, force]
    async_result = celery_app.signature(celery_task_name, args=args).delay()
    AudiobookTaskRepository.attach_celery_id(db, task_record.id, async_result.id)

    return {
        "success": True,
        "audiobook_project_id": audiobook_project_id,
        "job_id": async_result.id,
        "task_id": async_result.id,
        "task_db_id": task_record.id,
        "task_type": task_type,
        "status": "pending",
        "message": queued_message,
        "download_url": download_url,
    }


@router.post("/projects", response_model=dict)
async def create_audiobook_project(
    request: AudiobookProjectCreate,
    raw_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建有声书项目并启动生成任务。

    工作流：
    1. 通过应用服务校验项目与章节，并创建有声书项目记录
    2. 根据 generation_mode 启动对应的后台生成任务
    """
    service = AudiobookAppService(db=db, current_user=current_user)
    # 4. 后台启动生成任务（通过 Celery 队列）
    job_type = "script_only" if getattr(request, "generation_mode", "full") == "script_only" else "full"
    prepared_request = service.prepare_audiobook_project_creation(request)
    tts_model = normalize_audiobook_tts_model(request.tts_model)
    if job_type != "script_only":
        precheck = build_audiobook_task_points_precheck(
            db=db,
            user_id=current_user.id,
            project_id=prepared_request.project.id,
            project_title=prepared_request.project.title,
            chapter_ids=list(request.chapter_ids or []),
            tts_provider=tts_model,
        )
        _ensure_audiobook_points_precheck_passed(precheck)

    audiobook_project = service.create_audiobook_project(request, prepared=prepared_request)
    _, async_result = _enqueue_audiobook_task(
        db,
        audiobook_project_id=audiobook_project.id,
        chapter_ids=list(request.chapter_ids or []),
        job_type=job_type,
        tts_model=tts_model,
        output_format=request.output_format,
        narration_style=request.narration_style,
        narration_style_prompt=request.narration_style_prompt,
        generate_subtitle=request.generate_subtitle,
        force_regenerate_script=request.force_regenerate_script,
    )

    if job_type != "script_only":
        _safe_record_audiobook_billing_freeze(
            db=db,
            current_user=current_user,
            audiobook_project_id=audiobook_project.id,
            chapter_ids=list(request.chapter_ids or []),
            raw_request=raw_request,
            tts_pricing_key=tts_model,
            trace_context=build_audiobook_trace_context(
                celery_task_id=str(async_result.id),
                task_type=job_type,
                audiobook_project_id=audiobook_project.id,
                status="queued",
                progress=0.0,
                tts_model=tts_model,
                cost_precheck_id=precheck.cost_precheck_id,
            ),
        )

    return {
        "success": True,
        "audiobook_project_id": audiobook_project.id,
        "job_id": async_result.id,
        "task_type": job_type,
        "message": "有声书生成任务已进入队列",
        "total_chapters": len(request.chapter_ids),
    }


@router.post("/projects/{audiobook_project_id:int}/generate-audio-from-scripts", response_model=dict)
async def generate_audio_from_scripts(
    audiobook_project_id: int,
    request: GenerateAudioFromScriptsRequest,
    raw_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """为指定有声书项目按已存在剧本排队生成章节音频。"""
    owned = resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
    )
    project = owned.project

    requested_chapter_ids = [chapter_id for chapter_id in dict.fromkeys(request.chapter_ids or []) if chapter_id is not None]
    if not requested_chapter_ids:
        requested_chapter_ids = [
            chapter_audio.chapter_id
            for chapter_audio in ChapterAudioRepository.list_active_approved_scripts(
                db,
                audiobook_project_id,
            )
        ]

    if not requested_chapter_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="没有可生成音频的已审批剧本章节",
        )

    chapter_audio_rows = ChapterAudioRepository.list_active_by_project_chapter_ids(
        db,
        audiobook_project_id,
        requested_chapter_ids,
    )
    approved_chapter_ids = {
        chapter_audio.chapter_id
        for chapter_audio in chapter_audio_rows
        if chapter_audio.script_json and str(chapter_audio.script_status or "").strip().lower() == "approved"
    }
    invalid_chapter_ids = [chapter_id for chapter_id in requested_chapter_ids if chapter_id not in approved_chapter_ids]
    if invalid_chapter_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"以下章节缺少已审批剧本，无法直接生成音频: {invalid_chapter_ids}",
        )

    chapter_audio_by_id = {
        chapter_audio.chapter_id: chapter_audio
        for chapter_audio in chapter_audio_rows
    }
    resume_payloads_by_chapter: Dict[int, Dict[str, Any]] = {}
    if request.resume_from_checkpoint is not False:
        for resume_chapter_id in requested_chapter_ids:
            checkpoint_payload = _build_generation_checkpoint_payload(
                chapter_id=resume_chapter_id,
                chapter_audio=chapter_audio_by_id.get(resume_chapter_id),
                run_type="audio_from_scripts",
                db=db,
                audiobook_project_id=audiobook_project_id,
            )
            if checkpoint_payload.get("can_resume"):
                resume_payloads_by_chapter[resume_chapter_id] = checkpoint_payload

    tts_model = normalize_audiobook_tts_model(request.tts_model)
    precheck = build_audiobook_task_points_precheck(
        db=db,
        user_id=current_user.id,
        project_id=project.id,
        project_title=project.title,
        chapter_ids=requested_chapter_ids,
        tts_provider=tts_model,
    )
    _ensure_audiobook_points_precheck_passed(precheck)

    def bind_resume_checkpoints_before_dispatch(_task_record: Any, celery_task_id: str) -> None:
        if not resume_payloads_by_chapter:
            return
        _attach_resume_checkpoints_to_queued_runs(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_audio_by_id=chapter_audio_by_id,
            resume_payloads_by_chapter=resume_payloads_by_chapter,
            celery_task_id=celery_task_id,
        )

    timeline_edits_by_chapter: Dict[int, Dict[str, Dict[str, float]]] = {}
    if request.timeline_edits and len(requested_chapter_ids) == 1:
        timeline_edits_by_chapter[requested_chapter_ids[0]] = request.timeline_edits

    _, async_result = _enqueue_audiobook_task(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=requested_chapter_ids,
        job_type="audio_from_scripts",
        tts_model=tts_model,
        output_format=request.output_format,
        narration_style=request.narration_style,
        narration_style_prompt=request.narration_style_prompt,
        generate_subtitle=request.generate_subtitle,
        timeline_edits_by_chapter=timeline_edits_by_chapter or None,
        before_dispatch=bind_resume_checkpoints_before_dispatch,
    )

    _safe_record_audiobook_billing_freeze(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=requested_chapter_ids,
        raw_request=raw_request,
        tts_pricing_key=tts_model,
        trace_context=build_audiobook_trace_context(
            celery_task_id=str(async_result.id),
            task_type="audio_from_scripts",
            audiobook_project_id=audiobook_project_id,
            status="queued",
            progress=0.0,
            tts_model=tts_model,
            cost_precheck_id=precheck.cost_precheck_id,
        ),
    )

    return {
        "success": True,
        "audiobook_project_id": audiobook_project_id,
        "job_id": async_result.id,
        "task_type": "audio_from_scripts",
        "message": "章节音频生成任务已进入队列",
        "total_chapters": len(requested_chapter_ids),
        "chapter_ids": requested_chapter_ids,
    }


@router.post("/projects/{audiobook_project_id:int}/exports/m4b", response_model=dict)
async def export_audiobook_project_m4b(
    audiobook_project_id: int,
    metadata: Optional[Dict[str, Any]] = Body(default=None),
    force: bool = Query(False, description="是否强制重新生成导出文件"),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """导出整本有声书 M4B，包含按章节写入的 chapter markers。"""
    try:
        export_result = build_project_m4b_export(
            owned.db,
            audiobook_project=owned.audiobook_project,
            project=owned.project,
            metadata=metadata or {},
            force=force,
        )
    except AudiobookExportError as exc:
        status_code = status.HTTP_400_BAD_REQUEST
        if exc.code == "ffmpeg_unavailable":
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    return {
        **export_result,
        "download_url": f"/api/v1/audiobook/projects/{audiobook_project_id}/exports/m4b/download",
    }


@router.post("/projects/{audiobook_project_id:int}/exports/m4b/queue", response_model=dict)
async def queue_audiobook_project_m4b_export(
    audiobook_project_id: int,
    metadata: Optional[Dict[str, Any]] = Body(default=None),
    force: bool = Query(False, description="是否强制重新生成导出文件"),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """将整本 M4B 导出放入后台队列，状态通过 /tasks/{job_id}/status 查询。"""
    return _queue_project_export_task(
        owned.db,
        audiobook_project_id=audiobook_project_id,
        export_type="m4b",
        metadata=metadata or {},
        force=force,
    )


@router.get("/projects/{audiobook_project_id:int}/exports/m4b/download")
async def download_audiobook_project_m4b(
    audiobook_project_id: int,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """下载已生成的整本 M4B 文件。"""
    file_path = resolve_project_m4b_output_file(
        project_id=owned.project.id,
        audiobook_project_id=audiobook_project_id,
    )
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="M4B 文件不存在，请先导出")

    filename = build_safe_filename(owned.project.title or "audiobook", ".m4b", fallback="audiobook")
    encoded_filename = quote(filename)
    return FileResponse(
        path=str(file_path),
        media_type="audio/mp4",
        filename=filename,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.post("/projects/{audiobook_project_id:int}/exports/audacity", response_model=dict)
async def export_audiobook_project_audacity(
    audiobook_project_id: int,
    force: bool = Query(False, description="是否强制重新生成导出文件"),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """导出 Audacity ZIP，包含 project.lof、labels.txt 与按章节拆分的 WAV track。"""
    try:
        export_result = build_project_audacity_export(
            owned.db,
            audiobook_project=owned.audiobook_project,
            project=owned.project,
            force=force,
        )
    except AudiobookExportError as exc:
        status_code = status.HTTP_400_BAD_REQUEST
        if exc.code == "ffmpeg_unavailable":
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    return {
        **export_result,
        "download_url": f"/api/v1/audiobook/projects/{audiobook_project_id}/exports/audacity/download",
    }


@router.post("/projects/{audiobook_project_id:int}/exports/audacity/queue", response_model=dict)
async def queue_audiobook_project_audacity_export(
    audiobook_project_id: int,
    force: bool = Query(False, description="是否强制重新生成导出文件"),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """将 Audacity ZIP 导出放入后台队列，状态通过 /tasks/{job_id}/status 查询。"""
    return _queue_project_export_task(
        owned.db,
        audiobook_project_id=audiobook_project_id,
        export_type="audacity",
        force=force,
    )


@router.get("/projects/{audiobook_project_id:int}/exports/audacity/download")
async def download_audiobook_project_audacity(
    audiobook_project_id: int,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """下载已生成的 Audacity ZIP 文件。"""
    file_path = resolve_project_audacity_output_file(
        project_id=owned.project.id,
        audiobook_project_id=audiobook_project_id,
    )
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audacity ZIP 文件不存在，请先导出")

    filename = build_safe_filename(
        f"{owned.project.title or 'audiobook'}_audacity",
        ".zip",
        fallback="audiobook",
    )
    encoded_filename = quote(filename)
    return FileResponse(
        path=str(file_path),
        media_type="application/zip",
        filename=filename,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/projects/{audiobook_project_id:int}", response_model=dict)
async def get_audiobook_project(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取有声书项目详情"""
    owned = resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
    )
    audiobook_project = owned.audiobook_project

    # 获取章节音频列表
    chapter_audios = ChapterAudioRepository.list_by_audiobook_project(db, audiobook_project_id)

    # 取章节编号，用于前端“按章节编号跨记录合并音频”
    chapter_ids = [ca.chapter_id for ca in chapter_audios]
    chapter_number_by_id = ChapterRepository.get_chapter_number_map_by_ids(db, chapter_ids)

    return {
        "id": audiobook_project.id,
        "project_id": audiobook_project.project_id,
        "status": audiobook_project.status,
        "total_chapters": audiobook_project.total_chapters,
        "completed_chapters": audiobook_project.completed_chapters,
        "failed_chapters": audiobook_project.failed_chapters,
        "total_duration": audiobook_project.total_duration,
        "total_cost": audiobook_project.total_cost,
        "created_at": audiobook_project.created_at.isoformat() if audiobook_project.created_at else None,
	        "chapter_audios": [
	            {
	                "id": ca.id,
	                "chapter_id": ca.chapter_id,
	                "chapter_number": chapter_number_by_id.get(ca.chapter_id),
	                "audio_path": ca.audio_path,
	                "duration": ca.duration,
	                "file_size": ca.file_size,
                "script_status": ca.script_status or "pending",
                "has_script": bool(ca.script_json),
                "has_review": bool(ca.script_review_json),
            }
            for ca in chapter_audios
        ],
    }


@router.get("/projects/by-project/{project_id:int}")
async def list_audiobook_projects(
    project_id: int,
    include_chapter_audios: bool = Query(False, description="是否包含章节音频列表"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取项目的所有有声书项目"""
    # 验证权限
    project = ProjectRepository.get_user_project(db, current_user.id, project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在或无权限",
        )

    audiobook_projects = AudiobookProjectRepository.list_by_project(db, project_id)

    if not include_chapter_audios:
        return [
            {
                "id": ap.id,
                "status": ap.status,
                "total_chapters": ap.total_chapters,
                "completed_chapters": ap.completed_chapters,
                "total_duration": ap.total_duration,
                "created_at": ap.created_at.isoformat() if ap.created_at else None,
            }
            for ap in audiobook_projects
        ]

    audiobook_project_ids = [ap.id for ap in audiobook_projects]
    chapter_audios: List[ChapterAudio] = ChapterAudioRepository.list_active_by_audiobook_projects(
        db,
        audiobook_project_ids,
    )

    audios_by_project: Dict[int, List[ChapterAudio]] = {}
    chapter_ids: List[int] = []
    for ca in chapter_audios:
        audios_by_project.setdefault(ca.audiobook_project_id, []).append(ca)
        chapter_ids.append(ca.chapter_id)

    chapter_number_by_id: Dict[int, int] = ChapterRepository.get_chapter_number_map_by_ids(db, chapter_ids)

    results: List[Dict[str, Any]] = []
    for ap in audiobook_projects:
        audios = audios_by_project.get(ap.id, [])
        audios.sort(key=lambda ca: chapter_number_by_id.get(ca.chapter_id) or 0)

        results.append(
            {
                "id": ap.id,
                "status": ap.status,
                "total_chapters": ap.total_chapters,
                "completed_chapters": ap.completed_chapters,
                "total_duration": ap.total_duration,
                "created_at": ap.created_at.isoformat() if ap.created_at else None,
                "chapter_audios": [
                    {
                        "id": ca.id,
                        "chapter_id": ca.chapter_id,
                        "chapter_number": chapter_number_by_id.get(ca.chapter_id),
                        "audio_path": ca.audio_path,
                        "duration": ca.duration,
                        "file_size": ca.file_size,
                        "script_status": ca.script_status or "pending",
                        "has_script": bool(ca.script_json),
                        "has_review": bool(ca.script_review_json),
                    }
                    for ca in audios
                ],
            }
        )

    return results


@router.get("/projects")
async def list_user_audiobook_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取用户的所有有声书项目（用于有声小说仪表盘）"""
    audiobook_projects = AudiobookProjectRepository.list_by_user(db, current_user.id)

    project_ids = list({ap.project_id for ap in audiobook_projects})
    project_map: Dict[int, Project] = {}
    if project_ids:
        projects = ProjectRepository.list_user_projects_by_ids(
            db,
            current_user.id,
            project_ids,
        )
        project_map = {project.id: project for project in projects}

    result = []
    for ap in audiobook_projects:
        project = project_map.get(ap.project_id)
        if project:
            result.append({
                "id": ap.id,
                "project_id": ap.project_id,
                "project_title": project.title,
                "project_description": project.description,
                "status": ap.status,
                "total_chapters": ap.total_chapters,
                "completed_chapters": ap.completed_chapters,
                "failed_chapters": ap.failed_chapters,
                "total_duration": ap.total_duration,
                "total_cost": ap.total_cost,
                "created_at": ap.created_at.isoformat() if ap.created_at else None,
                "updated_at": ap.updated_at.isoformat() if ap.updated_at else None,
            })
    
    return result

