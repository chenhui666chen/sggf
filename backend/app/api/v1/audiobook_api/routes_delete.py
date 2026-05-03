from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.audiobook_delete_audit import AudiobookDeleteAudit
from app.services.audiobook.project_exporter import (
    collect_project_export_output_files,
    resolve_existing_audio_path,
)
from app.services.audiobook.repository import (
    AudiobookProjectRepository,
    ChapterAudioRepository,
    ProjectRepository,
)
from app.utils.datetime_utils import utc_now

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)


def _unique_delete_paths(paths: List[Path]) -> List[Path]:
    unique: List[Path] = []
    seen: set[str] = set()
    for path in paths or []:
        resolved = Path(path).resolve(strict=False)
        key = resolved.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def _collect_chapter_audio_artifact_files(chapter_audio: ChapterAudio) -> List[Path]:
    files: List[Path] = []
    audio_path = str(getattr(chapter_audio, "audio_path", "") or "").strip()
    if audio_path:
        resolved_audio = resolve_existing_audio_path(audio_path)
        if resolved_audio:
            files.append(resolved_audio)

    subtitle_path = str(getattr(chapter_audio, "subtitle_path", "") or "").strip()
    if subtitle_path:
        subtitle_candidates = [subtitle_path]
        subtitle_base = Path(subtitle_path)
        for suffix in (".srt", ".vtt", ".ass", ".labels.txt"):
            subtitle_candidates.append(str(subtitle_base.with_suffix(suffix)))
        for candidate in subtitle_candidates:
            resolved_subtitle = resolve_existing_audio_path(candidate)
            if resolved_subtitle:
                files.append(resolved_subtitle)

    return _unique_delete_paths(files)


def _delete_physical_files(paths: List[Path]) -> tuple[int, List[str]]:
    deleted_files = 0
    failed_files: List[str] = []
    for file_path in _unique_delete_paths(paths):
        if not file_path.exists() or not file_path.is_file():
            continue
        try:
            file_path.unlink()
            deleted_files += 1
            logger.info("✅ 删除文件: %s", file_path)
        except Exception as exc:
            logger.error("❌ 删除文件失败: %s, 错误: %s", file_path, exc)
            failed_files.append(file_path.as_posix())
    return deleted_files, failed_files


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

        paths_to_delete: List[Path] = []
        for chapter_audio in chapter_audios:
            paths_to_delete.extend(_collect_chapter_audio_artifact_files(chapter_audio))
        paths_to_delete.extend(
            collect_project_export_output_files(
                project_id=audiobook_project.project_id,
                audiobook_project_id=audiobook_project_id,
            )
        )
        deleted_files, failed_files = _delete_physical_files(paths_to_delete)
    
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
    
    deleted_files = 0
    failed_files: List[str] = []
    if delete_file:
        deleted_files, failed_files = _delete_physical_files(
            _collect_chapter_audio_artifact_files(chapter_audio)
        )
        deleted_file = deleted_files > 0
        failed_file = failed_files[0] if failed_files else None
    
    logger.info(f"✅ 章节音频软删除成功: chapter_audio_id={chapter_audio_id}, audit_id={audit_log.id}")
    
    return {
        "success": True,
        "message": "章节音频已删除",
        "audit_id": audit_log.id,
        "deleted_file": deleted_file,
        "deleted_files": deleted_files,
        "failed_file": failed_file,
        "failed_files": failed_files,
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

