from __future__ import annotations

import asyncio
import logging
import os
import json
import math
from pathlib import Path
from urllib.parse import quote
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status, Response, Query, UploadFile, File, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.audiobook_delete_audit import AudiobookDeleteAudit
from app.models.character import Character
from app.models.audiobook_task import AudiobookTask
from app.schemas.audiobook import (
    AudiobookProjectCreate,
    GenerateAudioFromScriptsRequest,
    ChapterScriptUpdateRequest,
    AudiobookProjectResponse,
    ChapterAudioResponse,
    CharacterVoiceConfig,
    TTSPreviewRequest,
    ScriptSegmentPreviewRequest,
    SegmentRegenerateRequest,
    SegmentReviewRequest,
    AudiobookTaskStatus,
    CosyVoiceCloneCreateRequest,
    ChapterReviewStatus,
    NarrationStylePreset,
    SubtitleDownloadResponse,
    GenerationCheckpointResponse,
    SmartChunkConfig,
    ChunkStats,
    ChunkPreviewResponse,
    VoiceTypePresetResponse,
    VoiceTypeRecommendationRequest,
    VoiceTypeRecommendationResponse,
)
from app.celery_app import celery_app
from app.services.audiobook import AudiobookEngine
from app.services.audiobook.audio_mixer import AudioMixer
from app.services.audiobook.agents import SoundEffectDesigner
from app.services.audiobook.tts_engine import RetryConfig
from app.services.audiobook.voice_manager import VoiceManager
from app.services.audiobook.voice_manager_factory import create_voice_manager
from app.services.audiobook.voice_catalog import get_voice_entry, load_voice_catalog_for_model
from app.services.audiobook.project_audio_config import (
    parse_project_audio_config,
    get_characters_for_model,
    get_audio_fx,
)
from app.services.audiobook.cosyvoice_clone_client import (
    CosyVoiceCloneError,
    create_cosyvoice_v3_plus_clone,
    delete_cosyvoice_clone,
    get_clone_display_name,
    list_cosyvoice_v3_plus_clones,
    save_clone_display_name,
    upload_cosyvoice_v3_plus_clone_sample,
)
from app.services.audiobook.narration_styles import get_all_narration_styles, get_narration_style_preset, apply_narration_style_to_tts_params
from app.services.audiobook.subtitle_generator import SubtitleGenerator, SubtitleEntry
from app.services.audiobook.smart_chunker import SmartChunker, TextChunk
from app.services.audiobook.voice_types import (
    get_all_voice_types,
    get_voice_type_preset,
    recommend_voice_type,
    apply_voice_type_to_tts_params,
    create_character_voice_profile,
)
from app.services.audiobook.sse_progress import sse_tracker, create_progress_handler
from app.services.audiobook.smart_retrier import SmartRetrier, RetryConfig, retry_tts_call
from app.services.audiobook.preview_generator import PreviewGenerator, default_preview_generator
from app.services.audiobook.app_service import AudiobookAppService
from app.services.audiobook.repository import (
    AudiobookProjectRepository,
    ChapterAudioRepository,
    ProjectRepository,
    AudiobookTaskRepository,
)
from app.services.audiobook.task_support import (
    build_generation_checkpoint_payload as _build_generation_checkpoint_payload,
    build_task_status_response,
    enqueue_audiobook_task as _enqueue_audiobook_task,
    enqueue_chapter_runs as _enqueue_chapter_runs,
    ensure_audiobook_points_precheck_passed as _ensure_audiobook_points_precheck_passed,
)
from app.services.points_task_precheck import (
    build_audiobook_task_points_precheck,
)
from app.services.user_center_points_events import (
    record_audiobook_billing_freeze,
)
from app.utils.datetime_utils import utc_now
from core.model_resolution import normalize_model_id
from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

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
    if job_type != "script_only":
        precheck = build_audiobook_task_points_precheck(
            db=db,
            user_id=current_user.id,
            project_id=prepared_request.project.id,
            project_title=prepared_request.project.title,
            chapter_ids=list(request.chapter_ids or []),
            tts_provider=request.tts_provider,
        )
        _ensure_audiobook_points_precheck_passed(precheck)

    audiobook_project = service.create_audiobook_project(request, prepared=prepared_request)
    tts_model = normalize_model_id(request.tts_model or "qwen3-tts-instruct-flash") or "qwen3-tts-instruct-flash"
    _, async_result = _enqueue_audiobook_task(
        db,
        audiobook_project_id=audiobook_project.id,
        chapter_ids=list(request.chapter_ids or []),
        job_type=job_type,
        tts_model=tts_model,
        output_format=request.output_format,
        narration_style=request.narration_style,
        narration_style_prompt=request.narration_style_prompt,
        force_regenerate_script=request.force_regenerate_script,
    )

    if job_type != "script_only":
        try:
            record_audiobook_billing_freeze(
                db=db,
                actor_user_id=current_user.id,
                actor_username=current_user.username,
                audiobook_project_id=audiobook_project.id,
                chapter_ids=list(request.chapter_ids or []),
                request_context=raw_request,
            )
        except Exception as exc:
            logger.warning("记录有声书积分冻结失败 audiobook_project_id=%s: %s", audiobook_project.id, exc)

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
    audiobook_project = AudiobookProjectRepository.get_by_id(db, audiobook_project_id)
    if not audiobook_project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="有声书项目不存在")

    project = ProjectRepository.get_user_project(db, current_user.id, audiobook_project.project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")

    requested_chapter_ids = [chapter_id for chapter_id in dict.fromkeys(request.chapter_ids or []) if chapter_id is not None]
    if not requested_chapter_ids:
        requested_chapter_ids = [
            chapter_audio.chapter_id
            for chapter_audio in db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id == audiobook_project_id,
                ChapterAudio.script_json.isnot(None),
                ChapterAudio.script_status == "approved",
                ChapterAudio.deleted_at.is_(None),
            )
            .all()
        ]

    if not requested_chapter_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="没有可生成音频的已审批剧本章节",
        )

    chapter_audio_rows = (
        db.query(ChapterAudio)
        .filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.chapter_id.in_(requested_chapter_ids),
            ChapterAudio.deleted_at.is_(None),
        )
        .all()
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

    tts_model = normalize_model_id(request.tts_model or "qwen3-tts-instruct-flash") or "qwen3-tts-instruct-flash"
    precheck = build_audiobook_task_points_precheck(
        db=db,
        user_id=current_user.id,
        project_id=project.id,
        project_title=project.title,
        chapter_ids=requested_chapter_ids,
        tts_provider=audiobook_project.tts_provider or "aliyun",
    )
    _ensure_audiobook_points_precheck_passed(precheck)

    _, async_result = _enqueue_audiobook_task(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=requested_chapter_ids,
        job_type="audio_from_scripts",
        tts_model=tts_model,
        output_format=request.output_format,
        narration_style=request.narration_style,
        narration_style_prompt=request.narration_style_prompt,
    )

    try:
        record_audiobook_billing_freeze(
            db=db,
            actor_user_id=current_user.id,
            actor_username=current_user.username,
            audiobook_project_id=audiobook_project_id,
            chapter_ids=requested_chapter_ids,
            request_context=raw_request,
        )
    except Exception as exc:
        logger.warning("记录有声书积分冻结失败 audiobook_project_id=%s: %s", audiobook_project_id, exc)

    return {
        "success": True,
        "audiobook_project_id": audiobook_project_id,
        "job_id": async_result.id,
        "task_type": "audio_from_scripts",
        "message": "章节音频生成任务已进入队列",
        "total_chapters": len(requested_chapter_ids),
        "chapter_ids": requested_chapter_ids,
    }


@router.get("/projects/{audiobook_project_id:int}", response_model=dict)
async def get_audiobook_project(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取有声书项目详情"""
    audiobook_project = AudiobookProjectRepository.get_by_id(db, audiobook_project_id)

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在",
        )

    # 验证权限
    project = ProjectRepository.get_user_project(db, current_user.id, audiobook_project.project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问",
        )

    # 获取章节音频列表
    chapter_audios = ChapterAudioRepository.list_by_audiobook_project(db, audiobook_project_id)

    # 取章节编号，用于前端“按章节编号跨记录合并音频”
    chapter_ids = [ca.chapter_id for ca in chapter_audios]
    chapter_number_by_id = {}
    if chapter_ids:
        from app.models.project import Chapter  # 避免顶层循环依赖

        rows = (
            db.query(Chapter.id, Chapter.chapter_number)
            .filter(Chapter.id.in_(chapter_ids))
            .all()
        )
        chapter_number_by_id = {cid: cnum for cid, cnum in rows}

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
    chapter_audios: List[ChapterAudio] = []
    if audiobook_project_ids:
        chapter_audios = (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id.in_(audiobook_project_ids),
                ChapterAudio.deleted_at.is_(None),
            )
            .all()
        )

    audios_by_project: Dict[int, List[ChapterAudio]] = {}
    chapter_ids: List[int] = []
    for ca in chapter_audios:
        audios_by_project.setdefault(ca.audiobook_project_id, []).append(ca)
        chapter_ids.append(ca.chapter_id)

    chapter_number_by_id: Dict[int, int] = {}
    if chapter_ids:
        rows = (
            db.query(Chapter.id, Chapter.chapter_number)
            .filter(Chapter.id.in_(list(set(chapter_ids))))
            .all()
        )
        chapter_number_by_id = {cid: cnum for cid, cnum in rows}

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
    
    # 获取项目详细信息
    result = []
    for ap in audiobook_projects:
        project = ProjectRepository.get_user_project(db, current_user.id, ap.project_id)
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

