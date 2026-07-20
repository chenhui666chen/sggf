from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


_SOURCE_ORDER = ("summary_data", "dialogue_attribution", "content_match")
_SPEECH_VERBS = "说|道|问|答|喊|叫|喝|吼|叹|喃喃"


@dataclass(frozen=True)
class ChapterCharacterScopeItem:
    character_id: int
    name: str
    confidence: str
    sources: list[str]
    chapter_ids: list[int]


@dataclass(frozen=True)
class ChapterCharacterScope:
    characters: list[ChapterCharacterScopeItem]
    unresolved_names: list[str]


@dataclass
class _MutableMatch:
    chapter_ids: set[int] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)


def _parse_summary_data(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return raw_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        return {}
    try:
        parsed = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_name_pattern(names: Iterable[str]) -> re.Pattern[str] | None:
    ordered_names = sorted(set(names), key=lambda item: (-len(item), item))
    if not ordered_names:
        return None
    return re.compile("|".join(re.escape(name) for name in ordered_names))


def _has_dialogue_attribution(content: str, name: str) -> bool:
    pattern = re.compile(
        rf"{re.escape(name)}[^。！？!?\n]{{0,8}}(?:{_SPEECH_VERBS})"
    )
    return bool(pattern.search(content))


def resolve_chapter_character_scope(
    *,
    chapters: Sequence[Any],
    characters: Sequence[Any],
) -> ChapterCharacterScope:
    character_by_name = {
        str(character.name).strip(): character
        for character in characters
        if str(getattr(character, "name", "") or "").strip()
    }
    name_pattern = _build_name_pattern(character_by_name)
    matches: dict[int, _MutableMatch] = {}
    unresolved_names: list[str] = []
    unresolved_seen: set[str] = set()

    def record(character: Any, chapter_id: int, source: str) -> None:
        match = matches.setdefault(int(character.id), _MutableMatch())
        match.chapter_ids.add(chapter_id)
        match.sources.add(source)

    for chapter in chapters:
        chapter_id = int(chapter.id)
        content = str(getattr(chapter, "content", "") or "")
        summary_data = _parse_summary_data(getattr(chapter, "summary_data", None))
        appearing_characters = summary_data.get("appearing_characters")
        if isinstance(appearing_characters, list):
            for raw_name in appearing_characters:
                name = str(raw_name or "").strip()
                if not name:
                    continue
                character = character_by_name.get(name)
                if character is not None:
                    record(character, chapter_id, "summary_data")
                elif name not in unresolved_seen:
                    unresolved_seen.add(name)
                    unresolved_names.append(name)

        if name_pattern is None or not content:
            continue
        for name_match in name_pattern.finditer(content):
            name = name_match.group(0)
            character = character_by_name[name]
            record(character, chapter_id, "content_match")
            if _has_dialogue_attribution(content, name):
                record(character, chapter_id, "dialogue_attribution")

    scoped_characters: list[ChapterCharacterScopeItem] = []
    for character in characters:
        character_id = int(character.id)
        match = matches.get(character_id)
        if match is None:
            continue
        sources = [source for source in _SOURCE_ORDER if source in match.sources]
        confidence = (
            "required"
            if "dialogue_attribution" in match.sources
            else "likely"
            if "summary_data" in match.sources
            else "mentioned"
        )
        scoped_characters.append(
            ChapterCharacterScopeItem(
                character_id=character_id,
                name=str(character.name).strip(),
                confidence=confidence,
                sources=sources,
                chapter_ids=sorted(match.chapter_ids),
            )
        )

    return ChapterCharacterScope(
        characters=scoped_characters,
        unresolved_names=unresolved_names,
    )


def select_chapter_characters(
    *,
    chapters: Sequence[Any],
    characters: Sequence[Any],
) -> tuple[list[Any], ChapterCharacterScope]:
    scope = resolve_chapter_character_scope(
        chapters=chapters,
        characters=characters,
    )
    scoped_character_ids = {item.character_id for item in scope.characters}
    selected_characters = [
        character
        for character in characters
        if int(character.id) in scoped_character_ids
    ]
    return selected_characters, scope
