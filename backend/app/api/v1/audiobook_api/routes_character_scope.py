from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.audiobook_api import router
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.schemas.audiobook_character_scope import (
    AudiobookCharacterScopeItem,
    AudiobookCharacterScopeRequest,
    AudiobookCharacterScopeResponse,
)
from app.services.audiobook.chapter_character_scope import resolve_chapter_character_scope
from app.services.audiobook.repository import (
    ChapterRepository,
    CharacterRepository,
    ProjectRepository,
)


@router.post(
    "/source-projects/{project_id:int}/character-scope",
    response_model=AudiobookCharacterScopeResponse,
)
async def resolve_source_project_character_scope(
    project_id: int,
    request: AudiobookCharacterScopeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AudiobookCharacterScopeResponse:
    project = ProjectRepository.get_user_project(
        db,
        user_id=current_user.id,
        project_id=project_id,
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在或无权限",
        )

    chapter_ids = list(dict.fromkeys(request.chapter_ids))
    chapters = ChapterRepository.get_project_chapters_by_ids(
        db,
        project_id=project_id,
        chapter_ids=chapter_ids,
    )
    if len(chapters) != len(chapter_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="部分章节不存在",
        )

    characters = CharacterRepository.list_by_project(db, project_id=project_id)
    scope = resolve_chapter_character_scope(
        chapters=chapters,
        characters=characters,
    )
    return AudiobookCharacterScopeResponse(
        characters=[
            AudiobookCharacterScopeItem(
                character_id=item.character_id,
                name=item.name,
                confidence=item.confidence,
                sources=item.sources,
                chapter_ids=item.chapter_ids,
            )
            for item in scope.characters
        ],
        unresolved_names=scope.unresolved_names,
        selected_chapter_count=len(chapters),
        project_character_count=len(characters),
    )
