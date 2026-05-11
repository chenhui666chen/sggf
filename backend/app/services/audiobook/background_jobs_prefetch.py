from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from sqlalchemy.orm import Session

from app.models.audiobook import ChapterAudio
from app.models.project import Chapter
from app.services.audiobook.repository import ChapterAudioRepository, ChapterRepository


@dataclass
class ChapterGenerationRecords:
    chapter_by_id: Dict[int, Chapter]
    chapter_audio_by_chapter_id: Dict[int, ChapterAudio]


def normalize_chapter_ids(chapter_ids: Iterable[int]) -> List[int]:
    normalized: List[int] = []
    seen: set[int] = set()
    for raw_id in chapter_ids or []:
        if raw_id is None:
            continue
        chapter_id = int(raw_id)
        if chapter_id in seen:
            continue
        seen.add(chapter_id)
        normalized.append(chapter_id)
    return normalized


def prefetch_chapter_generation_records(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_ids: Iterable[int],
) -> ChapterGenerationRecords:
    normalized_chapter_ids = normalize_chapter_ids(chapter_ids)
    chapters = ChapterRepository.list_active_by_ids(db, normalized_chapter_ids)
    chapter_audios = ChapterAudioRepository.list_active_by_project_chapter_ids(
        db,
        audiobook_project_id,
        normalized_chapter_ids,
    )

    return ChapterGenerationRecords(
        chapter_by_id={chapter.id: chapter for chapter in chapters},
        chapter_audio_by_chapter_id={
            chapter_audio.chapter_id: chapter_audio for chapter_audio in chapter_audios
        },
    )
