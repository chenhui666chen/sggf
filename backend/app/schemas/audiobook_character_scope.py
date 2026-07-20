from typing import List

from pydantic import BaseModel, Field


class AudiobookCharacterScopeRequest(BaseModel):
    chapter_ids: List[int] = Field(min_length=1)


class AudiobookCharacterScopeItem(BaseModel):
    character_id: int
    name: str
    confidence: str
    sources: List[str]
    chapter_ids: List[int]


class AudiobookCharacterScopeResponse(BaseModel):
    characters: List[AudiobookCharacterScopeItem]
    unresolved_names: List[str]
    selected_chapter_count: int
    project_character_count: int
