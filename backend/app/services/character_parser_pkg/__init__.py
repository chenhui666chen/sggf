"""
character_parser_pkg - 人物卡文本解析器

解析AI生成的文本格式人物卡，提取结构化字段，
并同步到数据库的characters表中。
"""
from ._constants import (
    CANONICAL_STORY_STANCES,
)
from ._utils import (
    normalize_character_name,
    normalize_story_stance_label,
    extract_story_stance_from_text,
    infer_story_stance_from_text_evidence,
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _merge_parsed_character,
    _build_personality_anchor_text,
)
from ._dataclasses import ParsedCharacter
from ._parser import CharacterTextParser, has_parseable_character_cards
from ._legacy import convert_legacy_grouped_characters_to_cards
from ._sync import (
    sync_parsed_characters_to_db,
    parse_and_sync_characters,
    parse_and_sync_relationships,
)


__all__ = [
    "CANONICAL_STORY_STANCES",
    "normalize_character_name",
    "normalize_story_stance_label",
    "extract_story_stance_from_text",
    "infer_story_stance_from_text_evidence",
    "_build_ability_and_limit_text",
    "_build_mainline_binding_text",
    "_merge_parsed_character",
    "_build_personality_anchor_text",
    "ParsedCharacter",
    "CharacterTextParser",
    "has_parseable_character_cards",
    "convert_legacy_grouped_characters_to_cards",
    "sync_parsed_characters_to_db",
    "parse_and_sync_characters",
    "parse_and_sync_relationships",
]
