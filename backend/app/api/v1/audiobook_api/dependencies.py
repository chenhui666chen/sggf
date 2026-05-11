from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.project import Project
from app.models.user import User
from app.services.audiobook.repository import (
    AudiobookProjectRepository,
    ChapterAudioRepository,
    ProjectRepository,
)


@dataclass(frozen=True)
class OwnedAudiobookProject:
    audiobook_project: AudiobookProject
    project: Project
    current_user: User
    db: Session


@dataclass(frozen=True)
class OwnedChapterAudio:
    chapter_audio: ChapterAudio
    audiobook_project: AudiobookProject
    project: Project
    current_user: User
    db: Session


def resolve_owned_audiobook_project(
    *,
    db: Session,
    current_user: User,
    audiobook_project_id: int,
    include_deleted: bool = False,
    not_found_detail: str = "有声书项目不存在",
    forbidden_detail: str = "无权限访问",
) -> OwnedAudiobookProject:
    repository_getter = (
        AudiobookProjectRepository.get_by_id
        if include_deleted
        else AudiobookProjectRepository.get_active_by_id
    )
    audiobook_project = repository_getter(db, audiobook_project_id)
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )

    project = ProjectRepository.get_user_project(db, current_user.id, audiobook_project.project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=forbidden_detail,
        )

    return OwnedAudiobookProject(
        audiobook_project=audiobook_project,
        project=project,
        current_user=current_user,
        db=db,
    )


def resolve_owned_chapter_audio(
    *,
    db: Session,
    current_user: User,
    chapter_audio_id: int,
    include_deleted: bool = False,
    include_deleted_project: bool = False,
    not_found_detail: str = "章节音频不存在",
    project_not_found_detail: str = "有声书项目不存在",
    forbidden_detail: str = "无权限访问",
) -> OwnedChapterAudio:
    repository_getter = (
        ChapterAudioRepository.get_by_id
        if include_deleted
        else ChapterAudioRepository.get_active_by_id
    )
    chapter_audio = repository_getter(db, chapter_audio_id)
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )

    owned_project = resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=chapter_audio.audiobook_project_id,
        include_deleted=include_deleted_project,
        not_found_detail=project_not_found_detail,
        forbidden_detail=forbidden_detail,
    )

    return OwnedChapterAudio(
        chapter_audio=chapter_audio,
        audiobook_project=owned_project.audiobook_project,
        project=owned_project.project,
        current_user=current_user,
        db=db,
    )


async def get_owned_audiobook_project(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OwnedAudiobookProject:
    return resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        include_deleted=False,
    )


async def get_owned_audiobook_project_including_deleted(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OwnedAudiobookProject:
    return resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=audiobook_project_id,
        include_deleted=True,
    )


def get_active_chapter_audio_for_project(
    *,
    db: Session,
    audiobook_project_id: int,
    chapter_id: int,
) -> ChapterAudio:
    chapter_audio = ChapterAudioRepository.get_active_by_project_chapter(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频记录不存在",
        )
    return chapter_audio
