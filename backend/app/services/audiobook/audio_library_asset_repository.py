"""共享音频素材库数据库索引仓储。"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.audio_library_asset import AudioLibraryAsset
from app.services.audiobook.audio_library_source_policy import (
    ALLOWED_SFX_SOURCES,
    normalize_sfx_record_source,
)


_COMMON_RECORD_FIELDS = (
    "source_id",
    "source_url",
    "author",
    "author_url",
    "license",
    "license_url",
    "license_version",
    "attribution_text",
    "quality_grade",
    "quality_status",
    "cloud_uri",
    "public_url",
    "object_key",
    "local_cache_path",
    "sha256",
    "content_type",
    "retrieved_at",
    "license_checked_at",
    "prompt",
    "tempo",
    "mood",
    "bucket",
    "style",
    "category",
    "description",
)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _optional_text(value: Any) -> str | None:
    normalized = _text(value)
    return normalized or None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = _text(value).lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def _list_value(value: Any) -> list:
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    if isinstance(value, tuple):
        return [item for item in value if item not in (None, "")]
    return []


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _asset_key_from_record(record: dict[str, Any]) -> str:
    key = _text(record.get("id") or record.get("asset_key") or record.get("source_id"))
    if not key:
        raise ValueError("audio library asset record must include id, asset_key, or source_id")
    return key[:160]


def normalize_library_type(value: str) -> str:
    normalized = _text(value).lower().replace("\\", "/").strip("/")
    if normalized in {"sfx", "sound_effect", "sound_effects"}:
        return "sfx"
    if normalized in {"music", "bgm"}:
        return "music"
    raise ValueError("library_type must be sfx or music")


def _apply_record_to_asset(asset: AudioLibraryAsset, library_type: str, record: dict[str, Any]) -> None:
    asset.library_type = library_type
    asset.asset_scope = _text(record.get("asset_scope"), "shared_library") or "shared_library"
    asset.asset_key = _asset_key_from_record(record)
    asset.name = _text(record.get("name") or record.get("style") or record.get("prompt") or asset.asset_key)[:255]
    asset.file_path = _text(record.get("file_path") or record.get("file"))
    if not asset.file_path:
        raise ValueError("audio library asset record must include file_path or file")

    asset.storage_mode = _text(record.get("storage_mode"), "local_cache") or "local_cache"
    asset.storage_driver = _text(record.get("storage_driver"), "local_fs") or "local_fs"
    asset.source = _text(record.get("source"))

    for field in _COMMON_RECORD_FIELDS:
        setattr(asset, field, _optional_text(record.get(field)))

    asset.license_commercial = _optional_bool(record.get("license_commercial"))
    asset.attribution_required = _optional_bool(record.get("attribution_required"))
    asset.quality_score = _optional_float(record.get("quality_score"))
    asset.duration = _optional_float(record.get("duration"))
    asset.variant = _optional_int(record.get("variant"))
    asset.file_size = _optional_int(record.get("file_size"))
    asset.tags = _list_value(record.get("tags"))
    asset.scenes = _list_value(record.get("scenes"))
    asset.metadata_json = _dict_value(record.get("metadata_json"))
    asset.source_payload_json = _dict_value(record.get("source_payload_json"))


def upsert_audio_library_asset(
    db: Session,
    library_type: str,
    record: dict[str, Any],
) -> AudioLibraryAsset:
    normalized_type = normalize_library_type(library_type)
    if normalized_type == "sfx":
        record = normalize_sfx_record_source(record)
    asset_key = _asset_key_from_record(record)
    asset = (
        db.query(AudioLibraryAsset)
        .filter(
            AudioLibraryAsset.library_type == normalized_type,
            AudioLibraryAsset.asset_key == asset_key,
        )
        .first()
    )
    if asset is None:
        asset = AudioLibraryAsset(library_type=normalized_type, asset_key=asset_key)
        db.add(asset)
    _apply_record_to_asset(asset, normalized_type, record)
    return asset


def audio_library_asset_to_record(asset: AudioLibraryAsset) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": asset.asset_key,
        "name": asset.name,
        "file_path": asset.file_path,
        "source": asset.source,
        "tags": list(asset.tags or []),
        "storage_mode": asset.storage_mode,
        "storage_driver": asset.storage_driver,
        "asset_scope": asset.asset_scope,
    }

    for field in _COMMON_RECORD_FIELDS:
        value = getattr(asset, field)
        if value not in (None, ""):
            record[field] = value

    optional_values = {
        "license_commercial": asset.license_commercial,
        "attribution_required": asset.attribution_required,
        "quality_score": asset.quality_score,
        "duration": asset.duration,
        "variant": asset.variant,
        "file_size": asset.file_size,
    }
    for key, value in optional_values.items():
        if value is not None:
            record[key] = value

    if asset.scenes:
        record["scenes"] = list(asset.scenes)
    if asset.metadata_json:
        record["metadata_json"] = dict(asset.metadata_json)
    if asset.source_payload_json:
        record["source_payload_json"] = dict(asset.source_payload_json)

    return record


def list_audio_library_asset_records(
    db: Session,
    library_type: str,
    *,
    include_disallowed_sfx_sources: bool = False,
) -> list[dict[str, Any]]:
    normalized_type = normalize_library_type(library_type)
    query = db.query(AudioLibraryAsset).filter(AudioLibraryAsset.library_type == normalized_type)
    if normalized_type == "sfx" and not include_disallowed_sfx_sources:
        query = query.filter(AudioLibraryAsset.source.in_(ALLOWED_SFX_SOURCES))
    assets: Iterable[AudioLibraryAsset] = query.order_by(AudioLibraryAsset.asset_key.asc()).all()
    return [audio_library_asset_to_record(asset) for asset in assets]


def replace_audio_library_asset_records(
    db: Session,
    library_type: str,
    records: Iterable[dict[str, Any]],
) -> None:
    normalized_type = normalize_library_type(library_type)
    existing_assets = (
        db.query(AudioLibraryAsset)
        .filter(AudioLibraryAsset.library_type == normalized_type)
        .all()
    )
    existing_by_key = {asset.asset_key: asset for asset in existing_assets}
    retained_keys: set[str] = set()

    for record in records:
        if normalized_type == "sfx":
            record = normalize_sfx_record_source(record)
        asset_key = _asset_key_from_record(record)
        asset = existing_by_key.get(asset_key)
        if asset is None:
            asset = AudioLibraryAsset(library_type=normalized_type, asset_key=asset_key)
            db.add(asset)
        _apply_record_to_asset(asset, normalized_type, record)
        retained_keys.add(asset_key)

    for asset in existing_assets:
        if asset.asset_key not in retained_keys:
            db.delete(asset)


__all__ = [
    "audio_library_asset_to_record",
    "list_audio_library_asset_records",
    "normalize_library_type",
    "replace_audio_library_asset_records",
    "upsert_audio_library_asset",
]
