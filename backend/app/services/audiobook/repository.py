"""有声书模块相关的 Repository 封装

主要职责：
- 将与 Project / Chapter / AudiobookProject / ChapterAudio / Character 相关的常用查询集中管理
- 为应用服务和 API 提供更稳定的访问接口，避免到处散落 db.query(...)
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject, ChapterAudio
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
