"""角色参考音色资产仓储。

把运行时物化的参考音色（Seed 系统/复刻 ``speaker`` 与其它来源的授权音频）
落库为稳定的 ``VoiceReferenceAsset``，供场景引擎按 ``asset_id`` 复用，避免把
Base64 长期写入项目 JSON。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.models.voice_reference_asset import VoiceReferenceAsset

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注
    from app.services.audiobook.scene_engine.preview_reference_asset import (
        PreviewReferenceAsset,
    )


_SPEAKER_KINDS = frozenset({"system_voice", "voice_clone"})
_OWNER_SCOPED_KINDS = frozenset(
    {"user_recording", "provider_preview", "user_generated_voice"}
)
_VALID_KINDS = _SPEAKER_KINDS | _OWNER_SCOPED_KINDS

_SOURCE_TYPE_BY_KIND = {
    "system_voice": "seed_system",
    "voice_clone": "seed_clone",
    "user_recording": "user_upload",
    "provider_preview": "provider_preview",
    "user_generated_voice": "user_generated",
}
_AUTH_SCOPE_BY_KIND = {
    "system_voice": "account",
    "voice_clone": "account",
    "user_recording": "user_uploaded",
    "provider_preview": "provider_preview",
    "user_generated_voice": "user_generated",
}
_ASSET_ID_PREFIX = {
    "system_voice": "sv",
    "voice_clone": "vc",
    "user_recording": "ur",
    "provider_preview": "pp",
    "user_generated_voice": "ug",
}


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


def _list_value(value: Any) -> list:
    if isinstance(value, (list, tuple)):
        return [item for item in value if item not in (None, "")]
    return []


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def normalize_reference_kind(value: str) -> str:
    normalized = _text(value).lower()
    if normalized not in _VALID_KINDS:
        raise ValueError(
            "reference_kind must be one of "
            "system_voice/voice_clone/user_recording/provider_preview/"
            "user_generated_voice"
        )
    return normalized


def build_voice_reference_asset_id(
    *,
    reference_kind: str,
    source_model: str | None = None,
    source_voice_id: str | None = None,
    speaker: str | None = None,
    sha256: str | None = None,
    authorization_version: str | None = None,
    owner_user_id: int | None = None,
) -> str:
    """按声音来源计算稳定的 ``asset_id`` 身份签名。

    - ``system_voice``/``voice_clone``：模型 + speaker/voice_id。
    - 用户私有音频：所有者 + 来源身份 + 音频 SHA-256 + 授权版本。
    """
    kind = normalize_reference_kind(reference_kind)
    if kind in _SPEAKER_KINDS:
        parts = [kind, _text(source_model), _text(speaker or source_voice_id)]
    else:
        parts = [
            kind,
            _text(owner_user_id),
            _text(source_model),
            _text(source_voice_id),
            _text(sha256),
            _text(authorization_version),
        ]
    signature = "|".join(parts)
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:40]
    return f"{_ASSET_ID_PREFIX[kind]}_{digest}"


def _apply_record_to_asset(asset: VoiceReferenceAsset, record: dict[str, Any]) -> None:
    kind = normalize_reference_kind(record.get("reference_kind"))
    asset.owner_user_id = _optional_int(record.get("owner_user_id"))
    asset.reference_kind = kind
    asset.reference_field = (
        _text(record.get("reference_field"))
        or ("speaker" if kind in _SPEAKER_KINDS else "audio_data")
    )
    asset.provider = _optional_text(record.get("provider"))
    asset.source_type = _text(record.get("source_type")) or _SOURCE_TYPE_BY_KIND[kind]
    asset.source_model = _optional_text(record.get("source_model"))
    asset.source_voice_id = _optional_text(record.get("source_voice_id"))
    asset.speaker = _optional_text(record.get("speaker"))
    asset.source_preview_cache_key = _optional_text(record.get("source_preview_cache_key"))
    asset.storage_uri = _optional_text(record.get("storage_uri"))
    asset.source_url = _optional_text(record.get("source_url"))
    asset.sha256 = _optional_text(record.get("sha256"))
    asset.duration_s = _optional_float(record.get("duration_s"))
    asset.content_type = _optional_text(record.get("content_type"))
    asset.file_size = _optional_int(record.get("file_size"))
    asset.authorization_scope = (
        _text(record.get("authorization_scope")) or _AUTH_SCOPE_BY_KIND[kind]
    )
    asset.authorization_version = _optional_text(record.get("authorization_version"))
    asset.authorization_basis = _optional_text(record.get("authorization_basis"))
    asset.authorized_by_user_id = _optional_int(record.get("authorized_by_user_id"))
    if "authorized_at" in record and isinstance(record["authorized_at"], datetime):
        asset.authorized_at = record["authorized_at"]
    if "revoked_at" in record and isinstance(record["revoked_at"], datetime):
        asset.revoked_at = record["revoked_at"]
    asset.revoked_by_user_id = _optional_int(record.get("revoked_by_user_id"))
    asset.revoke_reason = _optional_text(record.get("revoke_reason"))
    asset.cleanup_status = _text(record.get("cleanup_status"), "not_requested")
    if "cleanup_requested_at" in record and isinstance(
        record["cleanup_requested_at"], datetime
    ):
        asset.cleanup_requested_at = record["cleanup_requested_at"]
    if "deleted_at" in record and isinstance(record["deleted_at"], datetime):
        asset.deleted_at = record["deleted_at"]
    asset.cleanup_error = _optional_text(record.get("cleanup_error"))
    asset.tags = _list_value(record.get("tags"))
    asset.metadata_json = _dict_value(record.get("metadata_json"))
    asset.source_payload_json = _dict_value(record.get("source_payload_json"))


def _resolve_asset_id(record: dict[str, Any]) -> str:
    explicit = _text(record.get("asset_id"))
    if explicit:
        return explicit[:160]
    return build_voice_reference_asset_id(
        reference_kind=record.get("reference_kind"),
        source_model=record.get("source_model"),
        source_voice_id=record.get("source_voice_id"),
        speaker=record.get("speaker"),
        sha256=record.get("sha256"),
        authorization_version=record.get("authorization_version"),
        owner_user_id=_optional_int(record.get("owner_user_id")),
    )


def _validate_owner_authorization(record: dict[str, Any]) -> None:
    kind = normalize_reference_kind(record.get("reference_kind"))
    if kind not in _OWNER_SCOPED_KINDS:
        return

    required_values = {
        "owner_user_id": _optional_int(record.get("owner_user_id")),
        "authorized_by_user_id": _optional_int(record.get("authorized_by_user_id")),
        "authorization_scope": _optional_text(record.get("authorization_scope")),
        "authorization_basis": _optional_text(record.get("authorization_basis")),
        "authorization_version": _optional_text(record.get("authorization_version")),
        "authorized_at": record.get("authorized_at")
        if isinstance(record.get("authorized_at"), datetime)
        else None,
    }
    missing = [name for name, value in required_values.items() if value is None]
    if missing:
        raise ValueError(
            f"{kind} requires complete owner authorization: {', '.join(missing)}"
        )


def upsert_voice_reference_asset(
    db: Session,
    record: dict[str, Any],
) -> VoiceReferenceAsset:
    """按 ``asset_id`` 幂等落库参考音色资产。"""
    _validate_owner_authorization(record)
    asset_id = _resolve_asset_id(record)
    asset = (
        db.query(VoiceReferenceAsset)
        .filter(VoiceReferenceAsset.asset_id == asset_id)
        .first()
    )
    if asset is None:
        asset = VoiceReferenceAsset(asset_id=asset_id)
        db.add(asset)
    _apply_record_to_asset(asset, record)
    return asset


def persist_speaker_reference(
    db: Session,
    *,
    provider: str,
    source_model: str,
    speaker: str,
    reference_kind: str = "system_voice",
    source_voice_id: str | None = None,
    authorization_scope: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> VoiceReferenceAsset:
    """落库 Seed 系统/复刻 ``speaker`` 直传型参考音色。"""
    kind = normalize_reference_kind(reference_kind)
    if kind not in _SPEAKER_KINDS:
        raise ValueError("persist_speaker_reference only accepts system_voice/voice_clone")
    speaker_value = _text(speaker)
    if not speaker_value:
        raise ValueError("speaker is required for speaker-direct reference")
    record = {
        "reference_kind": kind,
        "reference_field": "speaker",
        "provider": provider,
        "source_model": source_model,
        "source_voice_id": source_voice_id or speaker_value,
        "speaker": speaker_value,
        "authorization_scope": authorization_scope,
        "metadata_json": metadata or {},
    }
    return upsert_voice_reference_asset(db, record)


def persist_materialized_reference(
    db: Session,
    asset: "PreviewReferenceAsset",
    *,
    provider: str | None = None,
    reference_kind: str = "provider_preview",
    authorization_scope: str | None = None,
    authorization_version: str | None = None,
    owner_user_id: int | None = None,
    authorized_by_user_id: int | None = None,
    authorization_basis: str | None = None,
    authorized_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> VoiceReferenceAsset:
    """把运行时物化的试听/授权音频落库为稳定资产。"""
    kind = normalize_reference_kind(reference_kind)
    if kind in _SPEAKER_KINDS:
        raise ValueError("persist_materialized_reference is for audio-based references")
    record = {
        "reference_kind": kind,
        "reference_field": "audio_data",
        "provider": provider,
        "source_model": asset.source_model,
        "source_voice_id": asset.source_voice_id,
        "source_preview_cache_key": asset.source_preview_cache_key,
        "storage_uri": str(asset.storage_path),
        "source_url": asset.source_url,
        "sha256": asset.sha256,
        "duration_s": asset.duration_s,
        "content_type": asset.content_type,
        "authorization_scope": authorization_scope,
        "authorization_version": authorization_version,
        "owner_user_id": owner_user_id,
        "authorized_by_user_id": authorized_by_user_id,
        "authorization_basis": authorization_basis,
        "authorized_at": authorized_at,
        "metadata_json": metadata or {},
    }
    return upsert_voice_reference_asset(db, record)


def persist_user_generated_voice_reference(
    db: Session,
    *,
    owner_user_id: int,
    provider: str,
    source_model: str,
    source_voice_id: str,
    authorization_basis: str,
    storage_uri: str | None = None,
    source_url: str | None = None,
    sha256: str | None = None,
    content_type: str | None = None,
    duration_s: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> VoiceReferenceAsset:
    """登记用户自己的设计/复刻音色，并写入完整的私有授权快照。"""
    now = datetime.now(timezone.utc)
    return upsert_voice_reference_asset(
        db,
        {
            "reference_kind": "user_generated_voice",
            "reference_field": "audio_data",
            "owner_user_id": owner_user_id,
            "authorized_by_user_id": owner_user_id,
            "authorization_scope": "user_generated",
            "authorization_basis": authorization_basis,
            "authorization_version": "voice-reference-consent-v1",
            "authorized_at": now,
            "provider": provider,
            "source_model": source_model,
            "source_voice_id": source_voice_id,
            "storage_uri": storage_uri,
            "source_url": source_url,
            "sha256": sha256,
            "content_type": content_type,
            "duration_s": duration_s,
            "metadata_json": metadata or {},
        },
    )


def get_voice_reference_asset(db: Session, asset_id: str) -> VoiceReferenceAsset | None:
    normalized = _text(asset_id)
    if not normalized:
        return None
    return (
        db.query(VoiceReferenceAsset)
        .filter(VoiceReferenceAsset.asset_id == normalized)
        .first()
    )


def get_active_voice_reference_asset(
    db: Session,
    *,
    asset_id: str,
    owner_user_id: int | None = None,
) -> VoiceReferenceAsset | None:
    """获取未撤销、未删除且属于指定用户的参考音色。"""
    normalized = _text(asset_id)
    if not normalized:
        return None
    query = db.query(VoiceReferenceAsset).filter(
        VoiceReferenceAsset.asset_id == normalized,
        VoiceReferenceAsset.revoked_at.is_(None),
        VoiceReferenceAsset.deleted_at.is_(None),
    )
    if owner_user_id is not None:
        query = query.filter(VoiceReferenceAsset.owner_user_id == owner_user_id)
    return query.first()


def revoke_voice_reference_asset(
    db: Session,
    *,
    asset_id: str,
    owner_user_id: int,
    revoked_by_user_id: int,
    reason: str = "",
) -> VoiceReferenceAsset | None:
    """幂等软撤销用户自己的参考音色，阻止后续物化和复用。"""
    asset = (
        db.query(VoiceReferenceAsset)
        .filter(
            VoiceReferenceAsset.asset_id == _text(asset_id),
            VoiceReferenceAsset.owner_user_id == owner_user_id,
        )
        .first()
    )
    if asset is None:
        return None
    if asset.revoked_at is None:
        asset.revoked_at = datetime.now(timezone.utc)
        asset.revoked_by_user_id = revoked_by_user_id
        asset.revoke_reason = _optional_text(reason)
        db.flush()
    return asset


def voice_reference_asset_to_record(asset: VoiceReferenceAsset) -> dict[str, Any]:
    record: dict[str, Any] = {
        "asset_id": asset.asset_id,
        "reference_kind": asset.reference_kind,
        "reference_field": asset.reference_field,
        "source_type": asset.source_type,
        "authorization_scope": asset.authorization_scope,
        "cleanup_status": asset.cleanup_status,
    }
    optional_text = {
        "provider": asset.provider,
        "source_model": asset.source_model,
        "source_voice_id": asset.source_voice_id,
        "speaker": asset.speaker,
        "source_preview_cache_key": asset.source_preview_cache_key,
        "storage_uri": asset.storage_uri,
        "source_url": asset.source_url,
        "sha256": asset.sha256,
        "content_type": asset.content_type,
        "authorization_version": asset.authorization_version,
        "authorization_basis": asset.authorization_basis,
        "revoke_reason": asset.revoke_reason,
        "cleanup_error": asset.cleanup_error,
    }
    for key, value in optional_text.items():
        if value not in (None, ""):
            record[key] = value
    if asset.duration_s is not None:
        record["duration_s"] = asset.duration_s
    optional_int = {
        "owner_user_id": asset.owner_user_id,
        "authorized_by_user_id": asset.authorized_by_user_id,
        "revoked_by_user_id": asset.revoked_by_user_id,
    }
    for key, value in optional_int.items():
        if value is not None:
            record[key] = value
    optional_datetime = {
        "authorized_at": asset.authorized_at,
        "revoked_at": asset.revoked_at,
        "cleanup_requested_at": asset.cleanup_requested_at,
        "deleted_at": asset.deleted_at,
    }
    for key, value in optional_datetime.items():
        if value is not None:
            record[key] = value.isoformat()
    if asset.file_size is not None:
        record["file_size"] = asset.file_size
    if asset.tags:
        record["tags"] = list(asset.tags)
    if asset.metadata_json:
        record["metadata_json"] = dict(asset.metadata_json)
    if asset.source_payload_json:
        record["source_payload_json"] = dict(asset.source_payload_json)
    return record


__all__ = [
    "build_voice_reference_asset_id",
    "get_active_voice_reference_asset",
    "get_voice_reference_asset",
    "normalize_reference_kind",
    "persist_materialized_reference",
    "persist_user_generated_voice_reference",
    "persist_speaker_reference",
    "revoke_voice_reference_asset",
    "upsert_voice_reference_asset",
    "voice_reference_asset_to_record",
]
