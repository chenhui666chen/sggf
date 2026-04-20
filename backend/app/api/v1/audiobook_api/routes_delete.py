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
from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

@router.delete("/projects/{audiobook_project_id:int}")
async def delete_audiobook_project(
    audiobook_project_id: int,
    delete_reason: Optional[str] = None,
    delete_files: bool = False,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除有声书项目（支持软删除和硬删除）
    
    工作流：
    1. 验证权限
    2. 执行软删除并记录审计日志
    3. 可选：删除物理文件（delete_files=true时）
    """
    logger.info(f"🗑️ 用户 {current_user.id} 请求删除有声书项目: audiobook_project_id={audiobook_project_id}, delete_files={delete_files}")
    
    if isinstance(payload, dict):
        if payload.get("delete_reason") is not None:
            raw_reason = str(payload.get("delete_reason") or "").strip()
            delete_reason = raw_reason or None
        if payload.get("delete_files") is not None:
            delete_files = bool(payload.get("delete_files"))

    # 1. 验证有声书项目权限
    audiobook_project = db.query(AudiobookProject).filter(AudiobookProject.id == audiobook_project_id).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    # 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限删除此项目"
        )
    
    # 2. 执行软删除并记录审计日志
    audit_log = AudiobookProjectRepository.soft_delete(
        db=db,
        audiobook_project_id=audiobook_project_id,
        user_id=current_user.id,
        user_name=current_user.username,
        delete_reason=delete_reason
    )
    
    if not audit_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在或已被删除"
        )
    
    # 3. 可选：删除物理文件
    deleted_files = 0
    failed_files = []
    
    if delete_files:
        # 获取所有章节音频并删除文件
        chapter_audios = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id
        ).all()
        
        for chapter_audio in chapter_audios:
            if chapter_audio.audio_path and os.path.exists(chapter_audio.audio_path):
                try:
                    os.remove(chapter_audio.audio_path)
                    deleted_files += 1
                    logger.info(f"✅ 删除文件: {chapter_audio.audio_path}")
                except Exception as e:
                    logger.error(f"❌ 删除文件失败: {chapter_audio.audio_path}, 错误: {e}")
                    failed_files.append(chapter_audio.audio_path)
    
    logger.info(f"✅ 有声书项目软删除成功: audiobook_project_id={audiobook_project_id}, audit_id={audit_log.id}")
    
    return {
        "success": True,
        "message": "有声书项目已删除",
        "audit_id": audit_log.id,
        "deleted_files": deleted_files,
        "failed_files": failed_files,
        "affected_chapters": audit_log.affected_chapters,
        "affected_tasks": audit_log.affected_tasks,
        "total_size": audit_log.total_size
    }


@router.delete("/chapter-audios/{chapter_audio_id:int}")
async def delete_chapter_audio(
    chapter_audio_id: int,
    delete_reason: Optional[str] = None,
    delete_file: bool = False,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除章节音频（支持软删除和硬删除）
    
    工作流：
    1. 验证权限
    2. 执行软删除并记录审计日志
    3. 可选：删除物理文件（delete_file=true时）
    """
    logger.info(f"🗑️ 用户 {current_user.id} 请求删除章节音频: chapter_audio_id={chapter_audio_id}, delete_file={delete_file}")
    
    if isinstance(payload, dict):
        if payload.get("delete_reason") is not None:
            raw_reason = str(payload.get("delete_reason") or "").strip()
            delete_reason = raw_reason or None

        raw_delete_file = payload.get("delete_file")
        if raw_delete_file is None:
            raw_delete_file = payload.get("delete_files")
        if raw_delete_file is not None:
            delete_file = bool(raw_delete_file)

    # 1. 获取章节音频
    chapter_audio = ChapterAudioRepository.get_by_id(db, chapter_audio_id)
    
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在"
        )
    
    # 2. 验证权限
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == chapter_audio.audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限删除此章节音频"
        )
    
    # 3. 执行软删除并记录审计日志
    audit_log = ChapterAudioRepository.soft_delete(
        db=db,
        chapter_audio_id=chapter_audio_id,
        user_id=current_user.id,
        user_name=current_user.username,
        delete_reason=delete_reason
    )
    
    if not audit_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在或已被删除"
        )
    
    # 4. 可选：删除物理文件
    deleted_file = False
    failed_file = None
    
    if delete_file and chapter_audio.audio_path:
        if os.path.exists(chapter_audio.audio_path):
            try:
                os.remove(chapter_audio.audio_path)
                deleted_file = True
                logger.info(f"✅ 删除文件: {chapter_audio.audio_path}")
            except Exception as e:
                logger.error(f"❌ 删除文件失败: {chapter_audio.audio_path}, 错误: {e}")
                failed_file = chapter_audio.audio_path
    
    logger.info(f"✅ 章节音频软删除成功: chapter_audio_id={chapter_audio_id}, audit_id={audit_log.id}")
    
    return {
        "success": True,
        "message": "章节音频已删除",
        "audit_id": audit_log.id,
        "deleted_file": deleted_file,
        "failed_file": failed_file,
        "affected_tasks": audit_log.affected_tasks,
        "file_size": audit_log.total_size
    }


@router.post("/projects/{audiobook_project_id:int}/restore")
async def restore_audiobook_project(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    恢复已删除的有声书项目
    
    工作流：
    1. 验证权限
    2. 恢复项目及关联的章节音频
    3. 更新审计日志
    """
    logger.info(f"♻️ 用户 {current_user.id} 请求恢复有声书项目: audiobook_project_id={audiobook_project_id}")
    
    # 1. 验证有声书项目是否存在
    audiobook_project = AudiobookProjectRepository.get_by_id(db, audiobook_project_id)
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )

    # 2. 验证原始项目权限
    project = ProjectRepository.get_user_project(db, current_user.id, audiobook_project.project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限恢复此项目"
        )

    # 3. 恢复项目
    restored_project = AudiobookProjectRepository.restore(
        db=db,
        audiobook_project_id=audiobook_project_id,
        user_id=current_user.id
    )
    
    if not restored_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在或未被删除"
        )
    
    logger.info(f"✅ 有声书项目恢复成功: audiobook_project_id={audiobook_project_id}")
    
    return {
        "success": True,
        "message": "有声书项目已恢复",
        "project_id": restored_project.id,
        "restored_at": utc_now().isoformat()
    }


@router.post("/chapter-audios/{chapter_audio_id:int}/restore")
async def restore_chapter_audio(
    chapter_audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    恢复已删除的章节音频
    
    工作流：
    1. 验证权限
    2. 恢复章节音频
    3. 更新审计日志
    """
    logger.info(f"♻️ 用户 {current_user.id} 请求恢复章节音频: chapter_audio_id={chapter_audio_id}")
    
    # 1. 获取章节音频
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.id == chapter_audio_id
    ).first()
    
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在"
        )
    
    # 2. 验证权限
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == chapter_audio.audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限恢复此章节音频"
        )
    
    # 3. 恢复章节音频
    restored_audio = ChapterAudioRepository.restore(
        db=db,
        chapter_audio_id=chapter_audio_id,
        user_id=current_user.id
    )
    
    if not restored_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在或未被删除"
        )
    
    logger.info(f"✅ 章节音频恢复成功: chapter_audio_id={chapter_audio_id}")
    
    return {
        "success": True,
        "message": "章节音频已恢复",
        "chapter_audio_id": restored_audio.id,
        "restored_at": utc_now().isoformat()
    }


@router.get("/projects/deleted")
async def list_deleted_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 50
):
    """
    获取用户已删除的有声书项目列表（回收站）
    
    返回：已删除的项目列表，包含审计信息
    """
    logger.info(f"📋 用户 {current_user.id} 查询已删除项目列表")
    
    # 获取已删除的项目
    deleted_projects = AudiobookProjectRepository.list_deleted(
        db=db,
        user_id=current_user.id,
        limit=limit
    )
    
    # 获取审计日志
    project_ids = [p.id for p in deleted_projects]
    audit_logs = db.query(AudiobookDeleteAudit).filter(
        AudiobookDeleteAudit.target_id.in_(project_ids),
        AudiobookDeleteAudit.delete_type == 'project'
    ).all()
    
    # 构建审计日志映射
    audit_map = {log.target_id: log for log in audit_logs}
    
    # 构建响应
    result = []
    source_project_ids = list({p.project_id for p in deleted_projects})
    source_title_by_id: Dict[int, str] = {}
    if source_project_ids:
        rows = (
            db.query(Project.id, Project.title)
            .filter(Project.id.in_(source_project_ids))
            .all()
        )
        source_title_by_id = {pid: title for pid, title in rows}

    for project in deleted_projects:
        audit = audit_map.get(project.id)
        result.append({
            "id": project.id,
            "project_id": project.project_id,
            "project_title": source_title_by_id.get(project.project_id),
            "status": project.status,
            "total_chapters": project.total_chapters,
            "completed_chapters": project.completed_chapters,
            "total_duration": project.total_duration,
            "deleted_at": project.deleted_at.isoformat() if project.deleted_at else None,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "audit_id": audit.id if audit else None,
            "delete_reason": audit.delete_reason if audit else None,
            "affected_chapters": audit.affected_chapters if audit else 0,
            "affected_tasks": audit.affected_tasks if audit else 0,
            "total_size": audit.total_size if audit else 0,
            "restored_at": audit.restored_at.isoformat() if audit and audit.restored_at else None,
        })
    
    logger.info(f"✅ 查询到 {len(result)} 个已删除项目")
    
    return {
        "success": True,
        "count": len(result),
        "projects": result
    }

