from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from app.models.project import Project
from app.models.voice_pool_publication import VoicePoolPublication
from app.services.audiobook.project_audio_config import (
    get_audio_fx,
    get_audio_engine_mode,
    get_seed_audio_model,
    get_characters_for_model,
    parse_project_audio_config,
)
from app.services.audiobook.voice_reference_asset_repository import (
    get_active_voice_reference_asset,
)


@dataclass(frozen=True)
class ProjectAudioRuntimeConfig:
    voice_mapping: Dict[str, Dict[str, Any]]
    audio_fx: Dict[str, Any]
    audio_engine_mode: str
    seed_audio_model: str
    raw_config: Dict[str, Any]
    character_items: List[dict]


def apply_scene_audio_runtime_to_engine(
    *,
    engine: Any,
    runtime_config: ProjectAudioRuntimeConfig,
) -> None:
    engine.apply_scene_audio_runtime_config(
        audio_engine_mode=runtime_config.audio_engine_mode,
        seed_audio_model=get_seed_audio_model(
            {
                "seed_audio_model": getattr(
                    runtime_config,
                    "seed_audio_model",
                    "",
                )
            }
        ),
        voice_mapping=runtime_config.voice_mapping,
    )


def build_character_voice_mapping_item(
    item: Mapping[str, Any],
    *,
    tts_model: str,
) -> Dict[str, Any]:
    result = {
        "voice_id": item.get("voice_id"),
        "tts_model": item.get("tts_model", tts_model),
    }

    for key in (
        "voice_clone_data_url",
        "voice_design_prompt",
        "mimo_voice_asset_id",
        "stepaudio_voice_asset_id",
        "reference_source",
        "reference_audio_url",
        "voice_reference_asset_id",
        "voice_pool_publication_id",
        "voice_reference_owner_user_id",
    ):
        value = item.get(key)
        if value is not None:
            result[key] = value

    return result


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


def validate_project_voice_references(
    db: Any,
    *,
    owner_user_id: int,
    voice_mapping: Dict[str, Dict[str, Any]],
) -> None:
    """重新校验并刷新私有/公共参考 URI，阻断撤销或跨用户资产。"""
    for character_name, config in voice_mapping.items():
        reference_source = str(config.get("reference_source") or "").strip().lower()
        if reference_source == "user_private":
            asset = get_active_voice_reference_asset(
                db,
                asset_id=str(config.get("voice_reference_asset_id") or ""),
                owner_user_id=owner_user_id,
            )
            if asset is None:
                raise PermissionError(f"角色 {character_name} 的私有参考音色无权访问或已撤销")
            reference_url = str(asset.source_url or asset.storage_uri or "").strip()
            if not reference_url.startswith(("http://", "https://")):
                raise ValueError(f"角色 {character_name} 的参考试听尚未上传 OSS")
            config.update(
                {
                    "reference_source": "user_private",
                    "reference_audio_url": reference_url,
                    "voice_reference_asset_id": asset.asset_id,
                    "voice_reference_owner_user_id": owner_user_id,
                    "voice_id": str(asset.source_voice_id or config.get("voice_id") or ""),
                    "tts_model": str(asset.source_model or config.get("tts_model") or ""),
                }
            )
        elif reference_source == "public_pool":
            publication = (
                db.query(VoicePoolPublication)
                .filter(
                    VoicePoolPublication.publication_id
                    == str(config.get("voice_pool_publication_id") or ""),
                    VoicePoolPublication.status == "published",
                )
                .first()
            )
            if publication is None:
                raise ValueError(f"角色 {character_name} 的公共音色不存在或已下架")
            config.update(
                {
                    "reference_source": "public_pool",
                    "reference_audio_url": publication.public_reference_uri,
                    "voice_pool_publication_id": publication.publication_id,
                    "voice_id": f"voice_pool:{publication.publication_id}",
                    "tts_model": str(publication.source_model or config.get("tts_model") or ""),
                }
            )


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
        audio_engine_mode=get_audio_engine_mode(raw_config),
        seed_audio_model=get_seed_audio_model(raw_config),
        raw_config=dict(raw_config),
        character_items=list(character_items),
    )
