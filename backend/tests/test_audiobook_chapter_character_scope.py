from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.chapter_character_scope import (
    resolve_chapter_character_scope,
    select_chapter_characters,
)


def _character(character_id: int, name: str):
    return SimpleNamespace(
        id=character_id,
        name=name,
        gender=None,
        role=None,
        role_position=None,
        importance_level=None,
    )


def _chapter(
    chapter_id: int,
    content: str,
    appearing_characters: list[str] | None = None,
):
    summary_data = {}
    if appearing_characters is not None:
        summary_data["appearing_characters"] = appearing_characters
    return SimpleNamespace(
        id=chapter_id,
        content=content,
        summary_data=json.dumps(summary_data, ensure_ascii=False),
    )


def test_resolves_chinese_names_next_to_chinese_text_and_marks_dialogue_speakers_required():
    scope = resolve_chapter_character_scope(
        chapters=[_chapter(10, "裴世清低声道：\"现在就走。\"苏念慈看向门外。")],
        characters=[
            _character(1, "裴世清"),
            _character(2, "苏念慈"),
            _character(3, "青萝"),
        ],
    )

    assert [item.character_id for item in scope.characters] == [1, 2]
    assert scope.characters[0].confidence == "required"
    assert scope.characters[0].sources == ["dialogue_attribution", "content_match"]
    assert scope.characters[1].confidence == "mentioned"


def test_prefers_longest_overlapping_character_name_for_the_same_text_span():
    scope = resolve_chapter_character_scope(
        chapters=[_chapter(10, "柳如瑟转过身。")],
        characters=[
            _character(1, "如瑟"),
            _character(2, "柳如瑟"),
        ],
    )

    assert [item.name for item in scope.characters] == ["柳如瑟"]


def test_uses_only_selected_chapter_objects_and_merges_summary_sources():
    scope = resolve_chapter_character_scope(
        chapters=[
            _chapter(10, "裴世清走进大殿。", ["裴世清", "李大人"]),
        ],
        characters=[
            _character(1, "裴世清"),
            _character(2, "苏念慈"),
        ],
    )

    assert [item.character_id for item in scope.characters] == [1]
    assert scope.characters[0].sources == ["summary_data", "content_match"]
    assert scope.characters[0].chapter_ids == [10]
    assert scope.unresolved_names == ["李大人"]


def test_returns_empty_scope_when_no_chapters_are_selected():
    scope = resolve_chapter_character_scope(
        chapters=[],
        characters=[_character(1, "裴世清")],
    )

    assert scope.characters == []
    assert scope.unresolved_names == []


def test_select_chapter_characters_returns_records_in_project_order():
    characters = [
        _character(1, "裴世清"),
        _character(2, "苏念慈"),
        _character(3, "青萝"),
    ]

    selected, scope = select_chapter_characters(
        chapters=[_chapter(10, "青萝走进屋内，裴世清转过身。")],
        characters=characters,
    )

    assert [character.id for character in selected] == [1, 3]
    assert [item.character_id for item in scope.characters] == [1, 3]
