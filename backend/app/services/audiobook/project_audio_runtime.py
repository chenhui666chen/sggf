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
    parse_engine_config_snapshot,
    parse_project_audio_config,
    resolve_engine_mode,
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


# 配乐基准音量当前默认值（继续压低以确保人声清晰）；旧版 Pydantic 默认 -36dB 过低
BASE_BGM_VOLUME_DB_DEFAULT = -27.0

# 历史上注入过的系统默认值；前端未开放该配置项，命中即视为旧默认可被抬升
LEGACY_BASE_BGM_VOLUME_DEFAULTS = (-36.0, -18.0, -21.0, -24.0)


def heal_legacy_base_bgm_volume(audio_fx: Dict[str, Any]) -> Dict[str, Any]:
    """将历史持久化的过低配乐基准音量抬升到当前默认值，保证存量项目配乐可听。

    前端未开放该配置项，库中取值均来自旧版默认注入，因此抬升不会覆盖用户显式意图。
    """
    raw_value = audio_fx.get("base_bgm_volume")
    if raw_value is None:
        return audio_fx
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return audio_fx
    if value < BASE_BGM_VOLUME_DB_DEFAULT or value in LEGACY_BASE_BGM_VOLUME_DEFAULTS:
        audio_fx["base_bgm_volume"] = BASE_BGM_VOLUME_DB_DEFAULT
    return audio_fx


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


def apply_runtime_voice_mapping(
    *,
    voice_manager: Any,
    voice_mapping: Dict[str, Dict[str, Any]],
    character_profiles: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """把项目级角色音配置应用到引擎的 voice_manager。

    2026-10-11 收口：共享层不再用 ``try/except Exception → logger.warning`` 包住这次
    调用。音色解析失败（``VoiceMappingResolutionError``）必须传到任务失败或接口 400，
    否则越界角色会落到 ``assign_voice()`` 自动分配，用户指定的声线被静默替换而任务仍显示成功。
    """
    if not voice_mapping:
        return

    if character_profiles is None:
        voice_manager.apply_project_voice_mapping(voice_mapping)
    else:
        voice_manager.apply_project_voice_mapping(
            voice_mapping,
            character_profiles=character_profiles,
        )


def resolve_project_audio_runtime_config(
    project: Optional[Project],
    *,
    tts_model: str,
    base_voice_mapping: Any = None,
    engine_mode: Optional[str] = None,
) -> ProjectAudioRuntimeConfig:
    """从项目实时配置解析运行时配置。

    engine_mode 为 None 时自动 resolve（从 config 判定）。
    """
    raw_config = (
        parse_project_audio_config(project.audio_config or "")
        if project and project.audio_config
        else {}
    )
    resolved_mode = engine_mode or get_audio_engine_mode(raw_config)
    character_items = get_characters_for_model(raw_config, tts_model, engine_mode=resolved_mode)

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

    audio_fx = heal_legacy_base_bgm_volume(dict(get_audio_fx(raw_config, engine_mode=resolved_mode) or {}))

    return ProjectAudioRuntimeConfig(
        voice_mapping=voice_mapping,
        audio_fx=dict(audio_fx),
        audio_engine_mode=resolved_mode,
        seed_audio_model=get_seed_audio_model(raw_config),
        raw_config=dict(raw_config),
        character_items=list(character_items),
    )


def resolve_from_snapshot(snapshot: Dict[str, Any], *, tts_model: str) -> ProjectAudioRuntimeConfig:
    """从 engine_config_snapshot 解析运行时配置（不含 billing/run 上下文）。"""
    engine_branch = snapshot.get("engine_branch_config", {})
    engine_mode = snapshot.get("engine_mode", "legacy_stems")
    # 快照的 engine_branch_config 是分支体（无 engines 嵌套，GUIDE §2.1），
    # 包装成分支结构以复用 §2.2 读取优先级，否则 seed_scene 角色音色/音效配置全部丢失。
    branch_config = {"engines": {engine_mode: engine_branch}}
    character_items = get_characters_for_model(branch_config, tts_model, engine_mode=engine_mode)

    voice_mapping: Dict[str, Dict[str, Any]] = {}
    for item in character_items:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not name:
            continue
        voice_mapping[str(name)] = build_character_voice_mapping_item(item, tts_model=tts_model)

    audio_fx = heal_legacy_base_bgm_volume(dict(get_audio_fx(branch_config, engine_mode=engine_mode) or {}))

    return ProjectAudioRuntimeConfig(
        voice_mapping=voice_mapping,
        audio_fx=dict(audio_fx),
        audio_engine_mode=engine_mode,
        seed_audio_model=get_seed_audio_model(engine_branch),
        raw_config=dict(snapshot),
        character_items=list(character_items),
    )


def resolve_from_run_input(run_input_snapshot: Dict[str, Any], *, tts_model: str) -> ProjectAudioRuntimeConfig:
    """从 run_input_snapshot 解析运行时配置（运行期消费，不读实时配置）。"""
    engine_payload = run_input_snapshot.get("signed_payload", {}).get("engine_config_payload", {})
    return resolve_from_snapshot(
        {"engine_mode": engine_payload.get("engine_mode", "legacy_stems"), "engine_branch_config": engine_payload},
        tts_model=tts_model,
    )
