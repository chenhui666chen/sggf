from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Dict

from fastapi import Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.audiobook import ChapterAudio, ChapterAudioRun
from app.schemas.audiobook import AudiobookDeleteRequest, ChapterAudioDeleteRequest
from app.api.v1.audiobook_api.dependencies import (
    resolve_owned_audiobook_project,
    resolve_owned_chapter_audio,
)
from app.services.audiobook.chapter_segment_assets import (
    delete_chapter_persistent_segment_assets,
)
from app.services.audiobook.temp_segment_janitor import (
    expire_chapter_run_temp_assets,
)
from app.services.audiobook.project_exporter import (
    collect_project_export_output_files,
    resolve_existing_audio_path,
)
from app.services.audiobook.repository import (
    AudiobookDeleteAuditRepository,
    AudiobookProjectRepository,
    ChapterAudioRepository,
    ProjectRepository,
)
from app.utils.datetime_utils import utc_now

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)


def _resolve_audiobook_delete_request(
    request: Optional[AudiobookDeleteRequest],
) -> AudiobookDeleteRequest:
    if isinstance(request, AudiobookDeleteRequest):
        return request
    return AudiobookDeleteRequest()


def _resolve_chapter_audio_delete_request(
    request: Optional[ChapterAudioDeleteRequest],
) -> ChapterAudioDeleteRequest:
    if isinstance(request, ChapterAudioDeleteRequest):
        return request
    return ChapterAudioDeleteRequest()


def _latest_audit_by_target_id(audit_logs):
    audit_map = {}
    for audit_log in audit_logs:
        if audit_log.target_id not in audit_map:
            audit_map[audit_log.target_id] = audit_log
    return audit_map


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


def _delete_chapter_persistent_segments(chapter_audio: ChapterAudio) -> int:
    """删除章节的持久化片段音频（工作台/管线生成），返回删除文件数。

    清理失败不阻断产物删除主流程，仅记录告警。
    """
    try:
        summary = delete_chapter_persistent_segment_assets(chapter_audio)
    except Exception as exc:
        logger.warning(
            "删除章节持久化片段音频失败: chapter_audio_id=%s error=%s",
            getattr(chapter_audio, "id", None),
            exc,
        )
        return 0
    return int((summary or {}).get("removed_files") or 0)


_CHAPTER_OUTPUT_GENERATION_RUN_TYPES = {
    "full",
    "script_only",
    "audio_from_scripts",
    "chapter_remix",
}
_CANCELABLE_GENERATION_RUN_STATUSES = {
    "queued",
    "pending",
    "running",
    "pause_requested",
    "paused",
    "failed",
    "cancelled",
    "canceled",
}
_SEGMENT_CANDIDATE_RUN_TYPE = "segment_candidate"


def _cancel_chapter_output_runs(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: Optional[int] = None,
) -> Dict[str, int]:
    """使章节产物删除后的生成 run 与候选登记不可再写入或恢复。

    首次生成可能尚未创建 ``ChapterAudio``，因此删除意图必须写入
    ``ChapterAudioRun``。后台 worker 以该不可恢复墓碑停止结果写回；
    已签发但未应用的片段候选也同时失效，避免删除后继续 apply。
    """
    now = utc_now()
    query = db.query(ChapterAudioRun).filter(
        ChapterAudioRun.audiobook_project_id == audiobook_project_id,
        ChapterAudioRun.run_type.in_(
            tuple(_CHAPTER_OUTPUT_GENERATION_RUN_TYPES | {_SEGMENT_CANDIDATE_RUN_TYPE})
        ),
    )
    if chapter_id is not None:
        query = query.filter(ChapterAudioRun.chapter_id == chapter_id)
    cancelled_generation_runs = 0
    cancelled_remix_runs = 0
    cancelled_candidate_runs = 0
    deleted_candidate_files = 0
    cancelled_runs: List[ChapterAudioRun] = []
    for run in query.all():
        run_type = str(run.run_type or "").strip().lower()
        run_status = str(run.status or "").strip().lower()
        if run_type == _SEGMENT_CANDIDATE_RUN_TYPE:
            should_cancel = bool(run.resumable)
        else:
            should_cancel = (
                run_status in _CANCELABLE_GENERATION_RUN_STATUSES
                and (
                    run_status in {"queued", "pending", "running", "pause_requested"}
                    or bool(run.resumable)
                )
            )
        if not should_cancel:
            continue

        if run_type == _SEGMENT_CANDIDATE_RUN_TYPE:
            try:
                cleanup_summary = expire_chapter_run_temp_assets(run, now=now)
                deleted_candidate_files += int(
                    (cleanup_summary or {}).get("removed_temp_files") or 0
                )
            except Exception as exc:
                logger.warning(
                    "删除章节产物时回收候选文件失败: run_id=%s error=%s",
                    getattr(run, "id", None),
                    exc,
                )

        run.status = "cancelled"
        run.current_stage = "cancelled"
        run.resumable = False
        run.error_message = "chapter_output_deleted"
        run.expires_at = now
        run.finished_at = now
        run.updated_at = now
        db.add(run)
        cancelled_runs.append(run)
        if run_type == _SEGMENT_CANDIDATE_RUN_TYPE:
            cancelled_candidate_runs += 1
        else:
            cancelled_generation_runs += 1
            if run_type == "chapter_remix":
                cancelled_remix_runs += 1
    if cancelled_runs:
        db.commit()
    return {
        "cancelled_generation_runs": cancelled_generation_runs,
        "cancelled_remix_runs": cancelled_remix_runs,
        "cancelled_candidate_runs": cancelled_candidate_runs,
        "deleted_candidate_files": deleted_candidate_files,
    }


@router.delete("/projects/{audiobook_project_id:int}")
async def delete_audiobook_project(
    audiobook_project_id: int,
    request: Optional[AudiobookDeleteRequest] = Body(default=None),
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
    delete_request = _resolve_audiobook_delete_request(request)
    delete_reason = delete_request.delete_reason
    delete_files = delete_request.delete_files
    logger.info(f"🗑️ 用户 {current_user.id} 请求删除有声书项目: audiobook_project_id={audiobook_project_id}, delete_files={delete_files}")

    owned = resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        forbidden_detail="无权限删除此项目",
    )
    audiobook_project = owned.audiobook_project

    # 项目删除会清理其全部章节产物，先让后台生成与候选登记停止写盘。
    cancelled_runs = _cancel_chapter_output_runs(
        db,
        audiobook_project_id=audiobook_project_id,
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
        chapter_audios = ChapterAudioRepository.list_by_audiobook_project_including_deleted(
            db,
            audiobook_project_id,
        )

        paths_to_delete: List[Path] = []
        persistent_deleted = 0
        for chapter_audio in chapter_audios:
            paths_to_delete.extend(_collect_chapter_audio_artifact_files(chapter_audio))
            persistent_deleted += _delete_chapter_persistent_segments(chapter_audio)
        paths_to_delete.extend(
            collect_project_export_output_files(
                project_id=audiobook_project.project_id,
                audiobook_project_id=audiobook_project_id,
            )
        )
        deleted_files, failed_files = _delete_physical_files(paths_to_delete)
        deleted_files += persistent_deleted
    
    logger.info(f"✅ 有声书项目软删除成功: audiobook_project_id={audiobook_project_id}, audit_id={audit_log.id}")
    
    return {
        "success": True,
        "message": "有声书项目已删除",
        "audit_id": audit_log.id,
        "deleted_files": deleted_files,
        "failed_files": failed_files,
        "affected_chapters": audit_log.affected_chapters,
        "affected_tasks": audit_log.affected_tasks,
        **cancelled_runs,
        "total_size": audit_log.total_size
    }


@router.delete("/chapter-audios/{chapter_audio_id:int}")
async def delete_chapter_audio(
    chapter_audio_id: int,
    request: Optional[ChapterAudioDeleteRequest] = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除章节音频（支持软删除和硬删除）
    
    工作流：
    1. 验证权限
    2. 执行软删除并记录审计日志
    3. 可选：删除物理文件（delete_files=true时）
    """
    delete_request = _resolve_chapter_audio_delete_request(request)
    delete_reason = delete_request.delete_reason
    delete_files = delete_request.delete_files
    logger.info(f"🗑️ 用户 {current_user.id} 请求删除章节音频: chapter_audio_id={chapter_audio_id}, delete_files={delete_files}")

    owned_audio = resolve_owned_chapter_audio(
        db=db,
        current_user=current_user,
        chapter_audio_id=chapter_audio_id,
        forbidden_detail="无权限删除此章节音频",
    )
    chapter_audio = owned_audio.chapter_audio

    cancelled_runs = _cancel_chapter_output_runs(
        db,
        audiobook_project_id=chapter_audio.audiobook_project_id,
        chapter_id=chapter_audio.chapter_id,
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
    if delete_files:
        deleted_files, failed_files = _delete_physical_files(
            _collect_chapter_audio_artifact_files(chapter_audio)
        )
        deleted_files += _delete_chapter_persistent_segments(chapter_audio)
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
        **cancelled_runs,
        "affected_tasks": audit_log.affected_tasks,
        "file_size": audit_log.total_size
    }


@router.delete("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/output")
async def delete_chapter_audiobook_output(
    audiobook_project_id: int,
    chapter_id: int,
    request: Optional[ChapterAudioDeleteRequest] = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除章节的有声书产出（剧本、音频、任务），保留原始章节内容不受影响。

    工作流：
    1. 根据 chapter_id 查找关联的 ChapterAudio 记录
    2. 验证权限
    3. 软删除并记录审计日志
    4. 强制清理全部产物文件（物理文件与持久化/候选片段音频）
    """
    delete_request = _resolve_chapter_audio_delete_request(request)
    delete_reason = delete_request.delete_reason
    delete_files = delete_request.delete_files
    logger.info(
        "🗑️ 用户 %s 请求删除章节有声书产出: audiobook_project_id=%s, chapter_id=%s, delete_files=%s",
        current_user.id, audiobook_project_id, chapter_id, delete_files,
    )

    resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        forbidden_detail="无权限删除此章节的有声书产出",
    )

    # 先写入不可恢复的 run 墓碑。首次 full/script_only 运行尚未创建
    # ChapterAudio 时，这仍能表达“删除且不允许后台稍后写回”的意图。
    cancelled_runs = _cancel_chapter_output_runs(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    # 仅查找当前有声书项目中该章节关联的活跃 ChapterAudio 记录。
    chapter_audios = (
        db.query(ChapterAudio)
        .filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.chapter_id == chapter_id,
            ChapterAudio.deleted_at.is_(None),
        )
        .all()
    )

    if not chapter_audios and not any(cancelled_runs.values()):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该章节没有已生成的有声书产出"
        )
    deleted_count = 0
    total_deleted_files = 0
    all_failed_files: List[str] = []
    audit_ids: List[int] = []

    for chapter_audio in chapter_audios:
        # 软删除
        audit_log = ChapterAudioRepository.soft_delete(
            db=db,
            chapter_audio_id=chapter_audio.id,
            user_id=current_user.id,
            user_name=current_user.username,
            delete_reason=delete_reason,
        )
        if audit_log:
            deleted_count += 1
            audit_ids.append(audit_log.id)

        # 本接口语义为“删除章节有声书产出”：无条件清理全部产物
        # （物理文件 + 工作台/管线持久化片段 + 候选资产），
        # delete_files 仅为兼容旧客户端保留，不再改变清理行为；
        # 避免默认确认删除后整章音频与片段残留
        files_deleted, files_failed = _delete_physical_files(
            _collect_chapter_audio_artifact_files(chapter_audio)
        )
        total_deleted_files += files_deleted
        total_deleted_files += _delete_chapter_persistent_segments(chapter_audio)
        all_failed_files.extend(files_failed)

    logger.info(
        "✅ 章节有声书产出删除完成: chapter_id=%s, deleted_audios=%s, deleted_files=%s",
        chapter_id, deleted_count, total_deleted_files,
    )

    return {
        "success": True,
        "message": "章节有声书产出已删除，原始章节内容未受影响",
        "chapter_id": chapter_id,
        "deleted_audios": deleted_count,
        "audit_ids": audit_ids,
        **cancelled_runs,
        "deleted_files": total_deleted_files,
        "failed_files": all_failed_files,
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
    
    resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        include_deleted=True,
        forbidden_detail="无权限恢复此项目",
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
    
    resolve_owned_chapter_audio(
        db=db,
        current_user=current_user,
        chapter_audio_id=chapter_audio_id,
        include_deleted=True,
        include_deleted_project=True,
        forbidden_detail="无权限恢复此章节音频",
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


@router.get("/chapter-audios/deleted")
async def list_deleted_chapter_audios(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    audiobook_project_id: Optional[int] = None,
    limit: int = 50,
):
    """
    获取用户已删除的章节音频列表（回收站）

    返回父级有声书项目仍可访问的章节音频记录，项目级删除由项目回收站统一恢复。
    """
    logger.info(
        "📋 用户 %s 查询已删除章节音频列表: audiobook_project_id=%s",
        current_user.id,
        audiobook_project_id,
    )

    if audiobook_project_id is not None:
        resolve_owned_audiobook_project(
            db=db,
            current_user=current_user,
            audiobook_project_id=audiobook_project_id,
            forbidden_detail="无权限查看此有声书项目的回收站",
        )

    normalized_limit = min(max(limit, 1), 200)
    deleted_chapter_audios = ChapterAudioRepository.list_deleted_for_user(
        db=db,
        user_id=current_user.id,
        audiobook_project_id=audiobook_project_id,
        limit=normalized_limit,
    )

    chapter_audio_ids = [audio.id for audio in deleted_chapter_audios]
    audit_logs = AudiobookDeleteAuditRepository.list_chapter_audio_audits_by_target_ids(
        db,
        chapter_audio_ids,
    )
    audit_map = _latest_audit_by_target_id(audit_logs)

    result = []
    for chapter_audio in deleted_chapter_audios:
        audiobook_project = chapter_audio.audiobook_project
        project = audiobook_project.project if audiobook_project else None
        chapter = chapter_audio.chapter
        audit = audit_map.get(chapter_audio.id)

        result.append({
            "id": chapter_audio.id,
            "chapter_audio_id": chapter_audio.id,
            "audiobook_project_id": chapter_audio.audiobook_project_id,
            "project_id": audiobook_project.project_id if audiobook_project else None,
            "project_title": project.title if project else None,
            "chapter_id": chapter_audio.chapter_id,
            "chapter_number": chapter.chapter_number if chapter else None,
            "chapter_title": chapter.title if chapter else None,
            "duration": chapter_audio.duration,
            "file_size": chapter_audio.file_size,
            "deleted_at": chapter_audio.deleted_at.isoformat() if chapter_audio.deleted_at else None,
            "created_at": chapter_audio.created_at.isoformat() if chapter_audio.created_at else None,
            "audit_id": audit.id if audit else None,
            "delete_reason": audit.delete_reason if audit else None,
            "affected_tasks": audit.affected_tasks if audit else 0,
            "total_size": audit.total_size if audit else (chapter_audio.file_size or 0),
            "restored_at": audit.restored_at.isoformat() if audit and audit.restored_at else None,
        })

    logger.info("✅ 查询到 %s 个已删除章节音频", len(result))

    return {
        "success": True,
        "count": len(result),
        "chapter_audios": result,
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
    audit_logs = AudiobookDeleteAuditRepository.list_project_audits_by_target_ids(
        db,
        project_ids,
    )
    
    # 构建审计日志映射
    audit_map = _latest_audit_by_target_id(audit_logs)
    
    # 构建响应
    result = []
    source_project_ids = list({p.project_id for p in deleted_projects})
    source_title_by_id: Dict[int, str] = ProjectRepository.get_title_map_by_ids(
        db,
        source_project_ids,
    )

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

