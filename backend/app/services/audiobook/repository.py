"""有声书模块相关的 Repository 封装

主要职责：
- 将与 Project / Chapter / AudiobookProject / ChapterAudio / Character 相关的常用查询集中管理
- 为应用服务和 API 提供更稳定的访问接口，避免到处散落 db.query(...)
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional

from sqlalchemy.orm import Session, joinedload

from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from app.models.audiobook_delete_audit import AudiobookDeleteAudit
from app.models.audiobook_task import AudiobookTask
from app.models.character import Character
from app.models.project import Chapter, Project
from app.models.user import User
from app.utils.datetime_utils import utc_now


def _safe_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _serialize_audiobook_project_snapshot(project: AudiobookProject) -> dict:
    return {
        "id": project.id,
        "project_id": project.project_id,
        "status": project.status,
        "tts_provider": project.tts_provider,
        "voice_mapping": project.voice_mapping,
        "enable_cache": project.enable_cache,
        "total_chapters": project.total_chapters,
        "completed_chapters": project.completed_chapters,
        "failed_chapters": project.failed_chapters,
        "total_duration": project.total_duration,
        "total_size": project.total_size,
        "total_cost": project.total_cost,
        "created_at": _safe_iso(project.created_at),
        "updated_at": _safe_iso(project.updated_at),
        "completed_at": _safe_iso(project.completed_at),
        "deleted_at": _safe_iso(project.deleted_at),
    }


def _serialize_chapter_audio_snapshot(audio: ChapterAudio) -> dict:
    return {
        "id": audio.id,
        "audiobook_project_id": audio.audiobook_project_id,
        "chapter_id": audio.chapter_id,
        "audio_path": audio.audio_path,
        "duration": audio.duration,
        "file_size": audio.file_size,
        "segment_count": audio.segment_count,
        "dialogue_count": audio.dialogue_count,
        "narration_count": audio.narration_count,
        "generation_time": audio.generation_time,
        "tts_cost": audio.tts_cost,
        "cache_hit_rate": audio.cache_hit_rate,
        "script_status": audio.script_status,
        "created_at": _safe_iso(audio.created_at),
        "updated_at": _safe_iso(audio.updated_at),
        "deleted_at": _safe_iso(audio.deleted_at),
    }


def _serialize_task_snapshot(task: AudiobookTask) -> dict:
    return {
        "id": task.id,
        "celery_task_id": task.celery_task_id,
        "audiobook_project_id": task.audiobook_project_id,
        "chapter_id": task.chapter_id,
        "task_type": task.task_type,
        "status": task.status,
        "current_stage": task.current_stage,
        "progress": task.progress,
        "completed_units": task.completed_units,
        "total_units": task.total_units,
        "detail_json": task.detail_json,
        "error_message": task.error_message,
        "created_at": _safe_iso(task.created_at),
        "updated_at": _safe_iso(task.updated_at),
        "started_at": _safe_iso(task.started_at),
        "finished_at": _safe_iso(task.finished_at),
    }


class UserRepository:
    """用户查询封装。"""

    @staticmethod
    def get_active_by_id(db: Session, user_id: int) -> Optional[User]:
        return (
            db.query(User)
            .filter(
                User.id == user_id,
                User.is_active.is_(True),
            )
            .first()
        )


class ProjectRepository:
    """与 Project 相关的查询封装"""

    @staticmethod
    def get_user_project(db: Session, user_id: int, project_id: int) -> Optional[Project]:
        return (
            db.query(Project)
            .filter(Project.id == project_id, Project.user_id == user_id)
            .first()
        )

    @staticmethod
    def list_user_projects_by_ids(
        db: Session,
        user_id: int,
        project_ids: Iterable[int],
    ) -> List[Project]:
        ids = list({project_id for project_id in project_ids if project_id is not None})
        if not ids:
            return []

        return (
            db.query(Project)
            .filter(
                Project.id.in_(ids),
                Project.user_id == user_id,
            )
            .all()
        )

    @staticmethod
    def get_title_map_by_ids(
        db: Session,
        project_ids: Iterable[int],
    ) -> dict[int, str]:
        ids = list({project_id for project_id in project_ids if project_id is not None})
        if not ids:
            return {}

        rows = (
            db.query(Project.id, Project.title)
            .filter(Project.id.in_(ids))
            .all()
        )
        return {project_id: title for project_id, title in rows}


class ChapterRepository:
    """与 Chapter 相关的查询封装"""

    @staticmethod
    def get_active_by_id(db: Session, chapter_id: int) -> Optional[Chapter]:
        return (
            db.query(Chapter)
            .filter(
                Chapter.id == chapter_id,
                Chapter.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def get_project_chapters_by_ids(
        db: Session,
        project_id: int,
        chapter_ids: Iterable[int],
    ) -> List[Chapter]:
        ids = list(chapter_ids)
        if not ids:
            return []

        return (
            db.query(Chapter)
            .filter(Chapter.project_id == project_id, Chapter.id.in_(ids))
            .all()
        )

    @staticmethod
    def list_active_by_ids(
        db: Session,
        chapter_ids: Iterable[int],
    ) -> List[Chapter]:
        ids = list({chapter_id for chapter_id in chapter_ids if chapter_id is not None})
        if not ids:
            return []

        return (
            db.query(Chapter)
            .filter(
                Chapter.id.in_(ids),
                Chapter.deleted_at.is_(None),
            )
            .all()
        )

    @staticmethod
    def get_active_project_chapter(
        db: Session,
        project_id: int,
        chapter_id: int,
    ) -> Optional[Chapter]:
        return (
            db.query(Chapter)
            .filter(
                Chapter.id == chapter_id,
                Chapter.project_id == project_id,
                Chapter.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def get_chapter_number_map_by_ids(
        db: Session,
        chapter_ids: Iterable[int],
    ) -> dict[int, int]:
        ids = list({chapter_id for chapter_id in chapter_ids if chapter_id is not None})
        if not ids:
            return {}

        rows = (
            db.query(Chapter.id, Chapter.chapter_number)
            .filter(
                Chapter.id.in_(ids),
                Chapter.deleted_at.is_(None),
            )
            .all()
        )
        return {chapter_id: chapter_number for chapter_id, chapter_number in rows}


class CharacterRepository:
    """与 Character 相关的查询封装"""

    @staticmethod
    def list_by_project(db: Session, project_id: int) -> List[Character]:
        return (
            db.query(Character)
            .filter(Character.project_id == project_id)
            .order_by(Character.id)
            .all()
        )


class AudiobookProjectRepository:
    """与 AudiobookProject 相关的查询封装"""

    @staticmethod
    def get_by_id(db: Session, audiobook_project_id: int) -> Optional[AudiobookProject]:
        return (
            db.query(AudiobookProject)
            .filter(AudiobookProject.id == audiobook_project_id)
            .first()
        )

    @staticmethod
    def get_active_by_id(db: Session, audiobook_project_id: int) -> Optional[AudiobookProject]:
        return (
            db.query(AudiobookProject)
            .filter(
                AudiobookProject.id == audiobook_project_id,
                AudiobookProject.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def list_by_project(db: Session, project_id: int) -> List[AudiobookProject]:
        """获取项目的有声书项目列表
        
        Args:
            project_id: 项目ID
        """
        return (
            db.query(AudiobookProject)
            .filter(
                AudiobookProject.project_id == project_id,
                AudiobookProject.deleted_at.is_(None)  # 排除已删除的项目
            )
            .order_by(AudiobookProject.created_at.desc())
            .all()
        )

    @staticmethod
    def list_by_user(db: Session, user_id: int) -> List[AudiobookProject]:
        """获取用户的所有有声书项目
        
        Args:
            user_id: 用户ID
        """
        return (
            db.query(AudiobookProject)
            .join(Project, Project.id == AudiobookProject.project_id)
            .filter(
                Project.user_id == user_id,
                AudiobookProject.deleted_at.is_(None)  # 排除已删除的项目
            )
            .order_by(AudiobookProject.created_at.desc())
            .all()
        )

    @staticmethod
    def _chapter_audio_ids_active_before_project_delete(
        audit_log: Optional[AudiobookDeleteAudit],
    ) -> Optional[List[int]]:
        """从项目删除快照中读取本次项目删除实际影响的章节音频 ID。

        返回 None 表示缺少可用快照，此时恢复逻辑会走历史兼容回退。
        """
        if not audit_log or not isinstance(audit_log.snapshot_json, dict):
            return None

        snapshot_chapter_audios = audit_log.snapshot_json.get("chapter_audios")
        if not isinstance(snapshot_chapter_audios, list):
            return None

        audio_ids: List[int] = []
        for audio_snapshot in snapshot_chapter_audios:
            if not isinstance(audio_snapshot, dict):
                continue
            if audio_snapshot.get("deleted_at") is not None:
                continue
            audio_id = audio_snapshot.get("id")
            if isinstance(audio_id, int):
                audio_ids.append(audio_id)

        return audio_ids

    @staticmethod
    def soft_delete(
        db: Session,
        audiobook_project_id: int,
        user_id: int,
        user_name: str,
        delete_reason: Optional[str] = None,
    ) -> Optional[AudiobookDeleteAudit]:
        """软删除有声书项目
        
        Args:
            db: 数据库会话
            audiobook_project_id: 有声书项目ID
            user_id: 用户ID
            user_name: 用户名
            delete_reason: 删除原因
            
        Returns:
            审计日志记录
        """
        # 获取项目
        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id
        ).first()
        
        if not audiobook_project:
            return None
        
        # 获取关联的章节音频
        chapter_audios = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id
        ).all()
        
        # 获取关联的任务
        tasks = db.query(AudiobookTask).filter(
            AudiobookTask.audiobook_project_id == audiobook_project_id
        ).all()
        
        # 创建数据快照
        snapshot = {
            "audiobook_project": _serialize_audiobook_project_snapshot(audiobook_project),
            "chapter_audios": [
                _serialize_chapter_audio_snapshot(audio)
                for audio in chapter_audios
            ],
            "tasks": [
                _serialize_task_snapshot(task)
                for task in tasks
            ],
        }
        
        active_chapter_audios = [
            audio for audio in chapter_audios
            if audio.deleted_at is None
        ]

        # 计算本次项目删除实际影响的文件数量和总大小
        file_count = len(active_chapter_audios)
        total_size = sum(audio.file_size or 0 for audio in active_chapter_audios)
        deleted_at = utc_now()
        
        # 软删除有声书项目
        audiobook_project.deleted_at = deleted_at
        
        # 只标记本次项目删除实际影响的章节音频，避免覆盖此前单独删除的记录。
        for audio in active_chapter_audios:
            audio.deleted_at = deleted_at
        
        # 创建审计日志
        audit_log = AudiobookDeleteAudit(
            delete_type='project',
            target_id=audiobook_project_id,
            user_id=user_id,
            user_name=user_name,
            snapshot_json=snapshot,
            delete_reason=delete_reason,
            file_count=file_count,
            total_size=total_size,
            affected_chapters=len(active_chapter_audios),
            affected_tasks=len(tasks),
            deleted_at=deleted_at,
        )
        
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)
        
        return audit_log

    @staticmethod
    def restore(
        db: Session,
        audiobook_project_id: int,
        user_id: int,
    ) -> Optional[AudiobookProject]:
        """恢复已删除的有声书项目
        
        Args:
            db: 数据库会话
            audiobook_project_id: 有声书项目ID
            user_id: 执行恢复的用户ID
            
        Returns:
            恢复的项目
        """
        # 获取项目
        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id,
            AudiobookProject.deleted_at.isnot(None)
        ).first()
        
        if not audiobook_project:
            return None
        
        # 更新审计日志
        audit_log = db.query(AudiobookDeleteAudit).filter(
            AudiobookDeleteAudit.target_id == audiobook_project_id,
            AudiobookDeleteAudit.delete_type == 'project',
            AudiobookDeleteAudit.restored_at.is_(None)
        ).order_by(AudiobookDeleteAudit.deleted_at.desc()).first()

        # 恢复有声书项目
        audiobook_project.deleted_at = None

        restore_chapter_audio_ids = (
            AudiobookProjectRepository._chapter_audio_ids_active_before_project_delete(audit_log)
        )
        restore_query = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.deleted_at.isnot(None),
        )
        if restore_chapter_audio_ids is None:
            restore_query.update({'deleted_at': None})
        elif restore_chapter_audio_ids:
            restore_query.filter(
                ChapterAudio.id.in_(restore_chapter_audio_ids)
            ).update({'deleted_at': None})
        
        if audit_log:
            audit_log.restored_at = utc_now()
            audit_log.restored_by = user_id
        
        db.commit()
        db.refresh(audiobook_project)
        
        return audiobook_project

    @staticmethod
    def list_deleted(db: Session, user_id: int, limit: int = 50) -> List[AudiobookProject]:
        """获取用户已删除的有声书项目列表
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            limit: 返回数量限制
            
        Returns:
            已删除的项目列表
        """
        return (
            db.query(AudiobookProject)
            .join(Project, Project.id == AudiobookProject.project_id)
            .filter(
                Project.user_id == user_id,
                AudiobookProject.deleted_at.isnot(None)
            )
            .order_by(AudiobookProject.deleted_at.desc())
            .limit(limit)
            .all()
        )


class AudiobookDeleteAuditRepository:
    """有声书删除审计查询封装。"""

    @staticmethod
    def list_audits_by_target_ids(
        db: Session,
        target_ids: Iterable[int],
        delete_type: str,
    ) -> List[AudiobookDeleteAudit]:
        ids = list({target_id for target_id in target_ids if target_id is not None})
        if not ids:
            return []

        return (
            db.query(AudiobookDeleteAudit)
            .filter(
                AudiobookDeleteAudit.target_id.in_(ids),
                AudiobookDeleteAudit.delete_type == delete_type,
            )
            .order_by(AudiobookDeleteAudit.deleted_at.desc())
            .all()
        )

    @staticmethod
    def list_project_audits_by_target_ids(
        db: Session,
        target_ids: Iterable[int],
    ) -> List[AudiobookDeleteAudit]:
        return AudiobookDeleteAuditRepository.list_audits_by_target_ids(
            db,
            target_ids,
            "project",
        )

    @staticmethod
    def list_chapter_audio_audits_by_target_ids(
        db: Session,
        target_ids: Iterable[int],
    ) -> List[AudiobookDeleteAudit]:
        return AudiobookDeleteAuditRepository.list_audits_by_target_ids(
            db,
            target_ids,
            "chapter",
        )


class ChapterAudioRepository:
    """与 ChapterAudio 相关的查询封装"""

    @staticmethod
    def list_by_audiobook_project(db: Session, audiobook_project_id: int) -> List[ChapterAudio]:
        return (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id == audiobook_project_id,
                ChapterAudio.deleted_at.is_(None)  # 排除已删除的章节音频
            )
            .all()
        )

    @staticmethod
    def list_active_by_audiobook_projects(
        db: Session,
        audiobook_project_ids: Iterable[int],
    ) -> List[ChapterAudio]:
        ids = list({project_id for project_id in audiobook_project_ids if project_id is not None})
        if not ids:
            return []

        return (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id.in_(ids),
                ChapterAudio.deleted_at.is_(None),
            )
            .all()
        )

    @staticmethod
    def list_active_by_project_chapter_ids(
        db: Session,
        audiobook_project_id: int,
        chapter_ids: Iterable[int],
    ) -> List[ChapterAudio]:
        ids = list({chapter_id for chapter_id in chapter_ids if chapter_id is not None})
        if not ids:
            return []

        return (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id == audiobook_project_id,
                ChapterAudio.chapter_id.in_(ids),
                ChapterAudio.deleted_at.is_(None),
            )
            .all()
        )

    @staticmethod
    def list_active_approved_scripts(
        db: Session,
        audiobook_project_id: int,
    ) -> List[ChapterAudio]:
        return (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id == audiobook_project_id,
                ChapterAudio.script_json.isnot(None),
                ChapterAudio.script_status == "approved",
                ChapterAudio.deleted_at.is_(None),
            )
            .all()
        )

    @staticmethod
    def list_by_audiobook_project_including_deleted(
        db: Session,
        audiobook_project_id: int,
    ) -> List[ChapterAudio]:
        return (
            db.query(ChapterAudio)
            .filter(ChapterAudio.audiobook_project_id == audiobook_project_id)
            .all()
        )

    @staticmethod
    def list_deleted_for_user(
        db: Session,
        user_id: int,
        audiobook_project_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[ChapterAudio]:
        """获取用户已删除的章节音频列表。

        仅返回父级有声书项目仍处于活动状态的章节音频，避免项目级删除在回收站中展开为大量重复章节。
        """
        query = (
            db.query(ChapterAudio)
            .join(AudiobookProject, ChapterAudio.audiobook_project_id == AudiobookProject.id)
            .join(Project, Project.id == AudiobookProject.project_id)
            .options(
                joinedload(ChapterAudio.audiobook_project).joinedload(AudiobookProject.project),
                joinedload(ChapterAudio.chapter),
            )
            .filter(
                Project.user_id == user_id,
                AudiobookProject.deleted_at.is_(None),
                ChapterAudio.deleted_at.isnot(None),
            )
        )
        if audiobook_project_id is not None:
            query = query.filter(ChapterAudio.audiobook_project_id == audiobook_project_id)

        return (
            query
            .order_by(ChapterAudio.deleted_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_by_id(db: Session, chapter_audio_id: int) -> Optional[ChapterAudio]:
        return (
            db.query(ChapterAudio)
            .filter(ChapterAudio.id == chapter_audio_id)
            .first()
        )

    @staticmethod
    def get_active_by_id(db: Session, chapter_audio_id: int) -> Optional[ChapterAudio]:
        return (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.id == chapter_audio_id,
                ChapterAudio.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def get_by_project_chapter(
        db: Session,
        audiobook_project_id: int,
        chapter_id: int,
    ) -> Optional[ChapterAudio]:
        return (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id == audiobook_project_id,
                ChapterAudio.chapter_id == chapter_id,
            )
            .first()
        )

    @staticmethod
    def get_active_by_project_chapter(
        db: Session,
        audiobook_project_id: int,
        chapter_id: int,
    ) -> Optional[ChapterAudio]:
        return (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id == audiobook_project_id,
                ChapterAudio.chapter_id == chapter_id,
                ChapterAudio.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def soft_delete(
        db: Session,
        chapter_audio_id: int,
        user_id: int,
        user_name: str,
        delete_reason: Optional[str] = None,
    ) -> Optional[AudiobookDeleteAudit]:
        """软删除章节音频
        
        Args:
            db: 数据库会话
            chapter_audio_id: 章节音频ID
            user_id: 用户ID
            user_name: 用户名
            delete_reason: 删除原因
            
        Returns:
            审计日志记录
        """
        # 获取章节音频
        chapter_audio = db.query(ChapterAudio).filter(
            ChapterAudio.id == chapter_audio_id
        ).first()
        
        if not chapter_audio:
            return None
        
        # 获取关联的任务
        tasks = db.query(AudiobookTask).filter(
            AudiobookTask.chapter_id == chapter_audio.chapter_id,
            AudiobookTask.audiobook_project_id == chapter_audio.audiobook_project_id
        ).all()
        
        # 创建数据快照
        snapshot = {
            "chapter_audio": _serialize_chapter_audio_snapshot(chapter_audio),
            "tasks": [
                _serialize_task_snapshot(task)
                for task in tasks
            ],
        }
        
        # 计算文件大小
        total_size = chapter_audio.file_size or 0
        
        # 软删除章节音频
        chapter_audio.deleted_at = utc_now()
        
        # 创建审计日志
        audit_log = AudiobookDeleteAudit(
            delete_type='chapter',
            target_id=chapter_audio_id,
            user_id=user_id,
            user_name=user_name,
            snapshot_json=snapshot,
            delete_reason=delete_reason,
            file_count=1,
            total_size=total_size,
            affected_chapters=1,
            affected_tasks=len(tasks),
            deleted_at=utc_now(),
        )
        
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)
        
        return audit_log

    @staticmethod
    def restore(
        db: Session,
        chapter_audio_id: int,
        user_id: int,
    ) -> Optional[ChapterAudio]:
        """恢复已删除的章节音频
        
        Args:
            db: 数据库会话
            chapter_audio_id: 章节音频ID
            user_id: 执行恢复的用户ID
            
        Returns:
            恢复的章节音频
        """
        # 获取章节音频
        chapter_audio = db.query(ChapterAudio).filter(
            ChapterAudio.id == chapter_audio_id,
            ChapterAudio.deleted_at.isnot(None)
        ).first()
        
        if not chapter_audio:
            return None
        
        # 恢复章节音频
        chapter_audio.deleted_at = None
        
        # 更新审计日志
        audit_log = db.query(AudiobookDeleteAudit).filter(
            AudiobookDeleteAudit.target_id == chapter_audio_id,
            AudiobookDeleteAudit.delete_type == 'chapter',
            AudiobookDeleteAudit.restored_at.is_(None)
        ).order_by(AudiobookDeleteAudit.deleted_at.desc()).first()
        
        if audit_log:
            audit_log.restored_at = utc_now()
            audit_log.restored_by = user_id
        
        db.commit()
        db.refresh(chapter_audio)
        
        return chapter_audio


class ChapterAudioRunRepository:
    """ChapterAudioRun related queries and persistence helpers."""

    @staticmethod
    def create_run(
        db: Session,
        *,
        audiobook_project_id: int,
        chapter_id: int,
        run_type: str,
        celery_task_id: Optional[str] = None,
        status: str = "pending",
        current_stage: Optional[str] = None,
        progress: float = 0.0,
        completed_segment_count: int = 0,
        total_segment_count: int = 0,
        tts_model: Optional[str] = None,
        output_format: Optional[str] = None,
        narration_style: Optional[str] = None,
        narration_style_prompt: Optional[str] = None,
        voice_config_hash: Optional[str] = None,
        audio_fx_hash: Optional[str] = None,
        script_hash: Optional[str] = None,
        resumable: bool = True,
        checkpoint_json: Optional[dict] = None,
        temp_asset_prefix: Optional[str] = None,
        expires_at=None,
        error_message: Optional[str] = None,
        started_at=None,
        finished_at=None,
    ) -> ChapterAudioRun:
        run = ChapterAudioRun(
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type=run_type,
            celery_task_id=celery_task_id,
            status=status,
            current_stage=current_stage,
            progress=progress,
            completed_segment_count=completed_segment_count,
            total_segment_count=total_segment_count,
            tts_model=tts_model,
            output_format=output_format,
            narration_style=narration_style,
            narration_style_prompt=narration_style_prompt,
            voice_config_hash=voice_config_hash,
            audio_fx_hash=audio_fx_hash,
            script_hash=script_hash,
            resumable=resumable,
            checkpoint_json=checkpoint_json,
            temp_asset_prefix=temp_asset_prefix,
            expires_at=expires_at,
            error_message=error_message,
            started_at=started_at,
            finished_at=finished_at,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    @staticmethod
    def create_runs(
        db: Session,
        *,
        audiobook_project_id: int,
        chapter_ids: Iterable[int],
        run_type: str,
        celery_task_id: Optional[str] = None,
        status: str = "pending",
        current_stage: Optional[str] = None,
        tts_model: Optional[str] = None,
        output_format: Optional[str] = None,
        narration_style: Optional[str] = None,
        narration_style_prompt: Optional[str] = None,
        resumable: bool = True,
    ) -> List[ChapterAudioRun]:
        runs = [
            ChapterAudioRun(
                audiobook_project_id=audiobook_project_id,
                chapter_id=chapter_id,
                run_type=run_type,
                celery_task_id=celery_task_id,
                status=status,
                current_stage=current_stage,
                progress=0.0,
                completed_segment_count=0,
                total_segment_count=0,
                tts_model=tts_model,
                output_format=output_format,
                narration_style=narration_style,
                narration_style_prompt=narration_style_prompt,
                resumable=resumable,
            )
            for chapter_id in chapter_ids
        ]
        if not runs:
            return []
        db.add_all(runs)
        db.commit()
        return runs

    @staticmethod
    def get_latest_run(
        db: Session,
        *,
        audiobook_project_id: int,
        chapter_id: int,
        run_type: Optional[str] = None,
    ) -> Optional[ChapterAudioRun]:
        query = db.query(ChapterAudioRun).filter(
            ChapterAudioRun.audiobook_project_id == audiobook_project_id,
            ChapterAudioRun.chapter_id == chapter_id,
        )
        if run_type:
            query = query.filter(ChapterAudioRun.run_type == run_type)
        return query.order_by(ChapterAudioRun.created_at.desc(), ChapterAudioRun.id.desc()).first()

    @staticmethod
    def get_latest_completed_run(
        db: Session,
        *,
        audiobook_project_id: int,
        chapter_id: int,
        run_type: Optional[str] = None,
    ) -> Optional[ChapterAudioRun]:
        query = db.query(ChapterAudioRun).filter(
            ChapterAudioRun.audiobook_project_id == audiobook_project_id,
            ChapterAudioRun.chapter_id == chapter_id,
            ChapterAudioRun.status == "completed",
        )
        if run_type:
            query = query.filter(ChapterAudioRun.run_type == run_type)
        return query.order_by(ChapterAudioRun.created_at.desc(), ChapterAudioRun.id.desc()).first()

    @staticmethod
    def list_completed_runs_for_chapter(
        db: Session,
        *,
        audiobook_project_id: int,
        chapter_id: int,
        run_types: Optional[Iterable[str]] = None,
        limit: int = 20,
    ) -> List[ChapterAudioRun]:
        query = db.query(ChapterAudioRun).filter(
            ChapterAudioRun.audiobook_project_id == audiobook_project_id,
            ChapterAudioRun.chapter_id == chapter_id,
            ChapterAudioRun.status == "completed",
        )
        normalized_run_types = [
            str(run_type).strip()
            for run_type in (run_types or [])
            if str(run_type).strip()
        ]
        if normalized_run_types:
            query = query.filter(ChapterAudioRun.run_type.in_(normalized_run_types))
        return (
            query.order_by(ChapterAudioRun.created_at.desc(), ChapterAudioRun.id.desc())
            .limit(max(1, int(limit or 1)))
            .all()
        )

    @staticmethod
    def list_runs_for_chapter(
        db: Session,
        *,
        audiobook_project_id: int,
        chapter_id: int,
        limit: int = 20,
    ) -> List[ChapterAudioRun]:
        return (
            db.query(ChapterAudioRun)
            .filter(
                ChapterAudioRun.audiobook_project_id == audiobook_project_id,
                ChapterAudioRun.chapter_id == chapter_id,
            )
            .order_by(ChapterAudioRun.created_at.desc(), ChapterAudioRun.id.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def list_expired_resumable_runs(
        db: Session,
        *,
        limit: int = 100,
    ) -> List[ChapterAudioRun]:
        return (
            db.query(ChapterAudioRun)
            .filter(
                ChapterAudioRun.expires_at.is_not(None),
                ChapterAudioRun.expires_at <= utc_now(),
                ChapterAudioRun.resumable.is_(True),
            )
            .order_by(ChapterAudioRun.expires_at.asc(), ChapterAudioRun.id.asc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_run_for_user(db: Session, run_id: int, user_id: int) -> Optional[ChapterAudioRun]:
        return (
            db.query(ChapterAudioRun)
            .join(AudiobookProject, AudiobookProject.id == ChapterAudioRun.audiobook_project_id)
            .join(Project, Project.id == AudiobookProject.project_id)
            .filter(
                ChapterAudioRun.id == run_id,
                Project.user_id == user_id,
            )
            .first()
        )

    @staticmethod
    def update_run(db: Session, run: ChapterAudioRun, **changes) -> ChapterAudioRun:
        for key, value in changes.items():
            setattr(run, key, value)
        run.updated_at = utc_now()
        db.add(run)
        db.commit()
        db.refresh(run)
        return run


class AudiobookTaskRepository:
    """与 AudiobookTask 相关的查询与管理."""

    @staticmethod
    def create_task(
        db: Session,
        *,
        audiobook_project_id: int,
        chapter_id: Optional[int],
        task_type: str,
        total_units: int = 0,
    ) -> AudiobookTask:
        now = utc_now()
        task = AudiobookTask(
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            task_type=task_type,
            total_units=total_units,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def attach_celery_id(db: Session, task_id: int, celery_task_id: str) -> None:
        task = db.query(AudiobookTask).filter(AudiobookTask.id == task_id).first()
        if not task:
            return
        task.celery_task_id = celery_task_id
        task.updated_at = utc_now()
        db.commit()

    @staticmethod
    def list_tasks_for_user(db: Session, user_id: int, limit: int = 50) -> List[AudiobookTask]:
        return (
            db.query(AudiobookTask)
            .join(AudiobookProject, AudiobookProject.id == AudiobookTask.audiobook_project_id)
            .join(Project, Project.id == AudiobookProject.project_id)
            .filter(
                Project.user_id == user_id,
                AudiobookProject.deleted_at.is_(None),
            )
            .order_by(AudiobookTask.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_task_for_user(db: Session, celery_task_id: str, user_id: int) -> Optional[AudiobookTask]:
        return (
            db.query(AudiobookTask)
            .join(AudiobookProject, AudiobookProject.id == AudiobookTask.audiobook_project_id)
            .join(Project, Project.id == AudiobookProject.project_id)
            .filter(
                AudiobookTask.celery_task_id == celery_task_id,
                Project.user_id == user_id,
                AudiobookProject.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def get_by_id(db: Session, task_id: int) -> Optional[AudiobookTask]:
        return db.query(AudiobookTask).filter(AudiobookTask.id == task_id).first()
