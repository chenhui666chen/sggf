"""有声书模块相关的 Repository 封装

主要职责：
- 将与 Project / Chapter / AudiobookProject / ChapterAudio / Character 相关的常用查询集中管理
- 为应用服务和 API 提供更稳定的访问接口，避免到处散落 db.query(...)
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.audiobook_task import AudiobookTask
from app.models.character import Character
from app.models.project import Chapter, Project


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
        return (
            db.query(AudiobookProject)
            .filter(AudiobookProject.project_id == project_id)
            .order_by(AudiobookProject.created_at.desc())
            .all()
        )


class ChapterAudioRepository:
    """与 ChapterAudio 相关的查询封装"""

    @staticmethod
    def list_by_audiobook_project(db: Session, audiobook_project_id: int) -> List[ChapterAudio]:
        return (
            db.query(ChapterAudio)
            .filter(ChapterAudio.audiobook_project_id == audiobook_project_id)
            .all()
        )


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
