from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from app.models.project import Project
from app.services.audiobook.project_audio_config import (
    get_audio_fx,
    get_characters_for_model,
    parse_project_audio_config,
)


@dataclass(frozen=True)
class ProjectAudioRuntimeConfig:
    voice_mapping: Dict[str, Dict[str, Any]]
    audio_fx: Dict[str, Any]
    raw_config: Dict[str, Any]
    character_items: List[dict]


def build_character_voice_mapping_item(
    item: Mapping[str, Any],
    *,
    tts_model: str,
) -> Dict[str, Any]:
    return {
        "voice_id": item.get("voice_id"),
        "volume": item.get("volume", 50),
        "speed": item.get("speed"),
        "pitch": item.get("pitch"),
        "tts_model": item.get("tts_model", tts_model),
        "voice_type": item.get("voice_type"),
        "personality": item.get("personality"),
        "emotion_tendency": item.get("emotion_tendency"),
    }


def normalize_base_voice_mapping(base_voice_mapping: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(base_voice_mapping, str):
        try:
            base_voice_mapping = json.loads(base_voice_mapping)
        except (json.JSONDecodeError, TypeError):
            base_voice_mapping = {}

    if not isinstance(base_voice_mapping, Mapping):
        return {}

    return {
        str(name): dict(config)
        for name, config in base_voice_mapping.items()
        if name is not None and isinstance(config, Mapping)
    }


def resolve_project_audio_runtime_config(
    project: Optional[Project],
    *,
    tts_model: str,
    base_voice_mapping: Any = None,
) -> ProjectAudioRuntimeConfig:
    raw_config = (
        parse_project_audio_config(project.audio_config or "")
        if project and project.audio_config
        else {}
    )
    character_items = get_characters_for_model(raw_config, tts_model)

    voice_mapping = normalize_base_voice_mapping(base_voice_mapping)
    for item in character_items:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not name:
            continue
        voice_mapping[str(name)] = build_character_voice_mapping_item(
            item,
            tts_model=tts_model,
        )

    audio_fx = get_audio_fx(raw_config) or {}

    return ProjectAudioRuntimeConfig(
        voice_mapping=voice_mapping,
        audio_fx=dict(audio_fx),
        raw_config=dict(raw_config),
        character_items=list(character_items),
    )
