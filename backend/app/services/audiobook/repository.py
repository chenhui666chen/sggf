"""有声书模块相关的 Repository 封装

主要职责：
- 将与 Project / Chapter / AudiobookProject / ChapterAudio / Character 相关的常用查询集中管理
- 为应用服务和 API 提供更稳定的访问接口，避免到处散落 db.query(...)
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.audiobook_delete_audit import AudiobookDeleteAudit
from app.models.audiobook_task import AudiobookTask
from app.models.character import Character
from app.models.project import Chapter, Project
from app.utils.datetime_utils import utc_now


class ProjectRepository:
    """与 Project 相关的查询封装"""

    @staticmethod
    def get_user_project(db: Session, user_id: int, project_id: int) -> Optional[Project]:
        return (
            db.query(Project)
            .filter(Project.id == project_id, Project.user_id == user_id)
            .first()
        )


class ChapterRepository:
    """与 Chapter 相关的查询封装"""

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
            'audiobook_project': {
                'id': audiobook_project.id,
                'project_id': audiobook_project.project_id,
                'status': audiobook_project.status,
                'tts_provider': audiobook_project.tts_provider,
                'voice_mapping': audiobook_project.voice_mapping,
                'enable_cache': audiobook_project.enable_cache,
                'total_chapters': audiobook_project.total_chapters,
                'completed_chapters': audiobook_project.completed_chapters,
                'failed_chapters': audiobook_project.failed_chapters,
                'total_duration': audiobook_project.total_duration,
                'total_size': audiobook_project.total_size,
                'total_cost': audiobook_project.total_cost,
                'created_at': audiobook_project.created_at.isoformat() if audiobook_project.created_at else None,
                'updated_at': audiobook_project.updated_at.isoformat() if audiobook_project.updated_at else None,
                'completed_at': audiobook_project.completed_at.isoformat() if audiobook_project.completed_at else None,
                'deleted_at': audiobook_project.deleted_at.isoformat() if audiobook_project.deleted_at else None,
            },
            'chapter_audios': [
                {
                    'id': audio.id,
                    'audiobook_project_id': audio.audiobook_project_id,
                    'chapter_id': audio.chapter_id,
                    'task_id': audio.task_id,
                    'audio_path': audio.audio_path,
                    'duration': audio.duration,
                    'file_size': audio.file_size,
                    'segment_count': audio.segment_count,
                    'dialogue_count': audio.dialogue_count,
                    'narration_count': audio.narration_count,
                    'generation_time': audio.generation_time,
                    'tts_cost': audio.tts_cost,
                    'cache_hit_rate': audio.cache_hit_rate,
                    'script_status': audio.script_status,
                    'created_at': audio.created_at.isoformat() if audio.created_at else None,
                    'updated_at': audio.updated_at.isoformat() if audio.updated_at else None,
                    'deleted_at': audio.deleted_at.isoformat() if audio.deleted_at else None,
                }
                for audio in chapter_audios
            ],
            'tasks': [
                {
                    'id': task.id,
                    'celery_task_id': task.celery_task_id,
                    'audiobook_project_id': task.audiobook_project_id,
                    'chapter_id': task.chapter_id,
                    'task_type': task.task_type,
                    'status': task.status,
                    'current_stage': task.current_stage,
                    'progress': task.progress,
                    'completed_units': task.completed_units,
                    'total_units': task.total_units,
                    'detail_json': task.detail_json,
                    'error_message': task.error_message,
                    'created_at': task.created_at.isoformat() if task.created_at else None,
                    'updated_at': task.updated_at.isoformat() if task.updated_at else None,
                    'started_at': task.started_at.isoformat() if task.started_at else None,
                    'finished_at': task.finished_at.isoformat() if task.finished_at else None,
                }
                for task in tasks
            ],
        }
        
        # 计算文件数量和总大小
        file_count = len(chapter_audios)
        total_size = sum(audio.file_size or 0 for audio in chapter_audios)
        
        # 软删除有声书项目
        audiobook_project.deleted_at = utc_now()
        
        # 软删除关联的章节音频
        for audio in chapter_audios:
            audio.deleted_at = utc_now()
        
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
            affected_chapters=len(chapter_audios),
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
        
        # 恢复有声书项目
        audiobook_project.deleted_at = None
        
        # 恢复关联的章节音频
        db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.deleted_at.isnot(None)
        ).update({'deleted_at': None})
        
        # 更新审计日志
        audit_log = db.query(AudiobookDeleteAudit).filter(
            AudiobookDeleteAudit.target_id == audiobook_project_id,
            AudiobookDeleteAudit.delete_type == 'project',
            AudiobookDeleteAudit.restored_at.is_(None)
        ).order_by(AudiobookDeleteAudit.deleted_at.desc()).first()
        
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
    def get_by_id(db: Session, chapter_audio_id: int) -> Optional[ChapterAudio]:
        return (
            db.query(ChapterAudio)
            .filter(ChapterAudio.id == chapter_audio_id)
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
            'chapter_audio': {
                'id': chapter_audio.id,
                'audiobook_project_id': chapter_audio.audiobook_project_id,
                'chapter_id': chapter_audio.chapter_id,
                'task_id': chapter_audio.task_id,
                'audio_path': chapter_audio.audio_path,
                'duration': chapter_audio.duration,
                'file_size': chapter_audio.file_size,
                'segment_count': chapter_audio.segment_count,
                'dialogue_count': chapter_audio.dialogue_count,
                'narration_count': chapter_audio.narration_count,
                'generation_time': chapter_audio.generation_time,
                'tts_cost': chapter_audio.tts_cost,
                'cache_hit_rate': chapter_audio.cache_hit_rate,
                'script_status': chapter_audio.script_status,
                'created_at': chapter_audio.created_at.isoformat() if chapter_audio.created_at else None,
                'updated_at': chapter_audio.updated_at.isoformat() if chapter_audio.updated_at else None,
                'deleted_at': chapter_audio.deleted_at.isoformat() if chapter_audio.deleted_at else None,
            },
            'tasks': [
                {
                    'id': task.id,
                    'celery_task_id': task.celery_task_id,
                    'audiobook_project_id': task.audiobook_project_id,
                    'chapter_id': task.chapter_id,
                    'task_type': task.task_type,
                    'status': task.status,
                    'current_stage': task.current_stage,
                    'progress': task.progress,
                    'completed_units': task.completed_units,
                    'total_units': task.total_units,
                    'detail_json': task.detail_json,
                    'error_message': task.error_message,
                    'created_at': task.created_at.isoformat() if task.created_at else None,
                    'updated_at': task.updated_at.isoformat() if task.updated_at else None,
                    'started_at': task.started_at.isoformat() if task.started_at else None,
                    'finished_at': task.finished_at.isoformat() if task.finished_at else None,
                }
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
        task = AudiobookTask(
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            task_type=task_type,
            total_units=total_units,
            status="pending",
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
        db.commit()

    @staticmethod
    def list_tasks_for_user(db: Session, user_id: int, limit: int = 50) -> List[AudiobookTask]:
        return (
            db.query(AudiobookTask)
            .join(AudiobookProject, AudiobookProject.id == AudiobookTask.audiobook_project_id)
            .join(Project, Project.id == AudiobookProject.project_id)
            .filter(Project.user_id == user_id)
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
            )
            .first()
        )

    @staticmethod
    def get_by_id(db: Session, task_id: int) -> Optional[AudiobookTask]:
        return db.query(AudiobookTask).filter(AudiobookTask.id == task_id).first()
