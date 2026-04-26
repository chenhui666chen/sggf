"""
用户资产记录 Schema
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.user_asset_local_storage_contract_generated import (
    USER_ASSET_ACTIVE_LOCAL_PERSIST_LEVELS,
    USER_ASSET_ACTIVE_LOCAL_STORAGE_DRIVERS,
    USER_ASSET_EXTERNAL_RELATIVE_PATH_DESCRIPTION,
    USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH,
    USER_ASSET_LOCAL_PERSIST_LEVELS,
    USER_ASSET_LOCAL_PERSIST_LEVEL_DESCRIPTION,
    USER_ASSET_LOCAL_STORAGE_DRIVERS,
    USER_ASSET_LOCAL_STORAGE_DRIVER_DESCRIPTION,
    USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH,
    USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_ID,
    USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_OWNER,
    USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_PATH,
    USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_VERSION,
    USER_ASSET_LOCAL_STORAGE_PATH_DESCRIPTION,
    USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH,
    USER_ASSET_RESERVED_LOCAL_PERSIST_LEVELS,
    USER_ASSET_RESERVED_LOCAL_STORAGE_DRIVERS,
    UserAssetActiveLocalPersistLevel,
    UserAssetActiveLocalStorageDriver,
)


ALLOWED_ASSET_KINDS = {"image", "video", "audio", "voice", "template", "document"}
ALLOWED_ASSET_CLASSES = {"reusable", "deliverable"}
ALLOWED_STORAGE_MODES = {"temp_cloud", "durable_cloud", "local_mirror", "local_only"}
RESERVED_STORAGE_MODES = {"local_only"}
ALLOWED_LOCAL_STORAGE_DRIVERS = set(USER_ASSET_LOCAL_STORAGE_DRIVERS)
ALLOWED_LOCAL_PERSIST_LEVELS = set(USER_ASSET_LOCAL_PERSIST_LEVELS)
ACTIVE_LOCAL_STORAGE_DRIVERS = set(USER_ASSET_ACTIVE_LOCAL_STORAGE_DRIVERS)
ACTIVE_LOCAL_PERSIST_LEVELS = set(USER_ASSET_ACTIVE_LOCAL_PERSIST_LEVELS)
RESERVED_LOCAL_STORAGE_DRIVERS = set(USER_ASSET_RESERVED_LOCAL_STORAGE_DRIVERS)
RESERVED_LOCAL_PERSIST_LEVELS = set(USER_ASSET_RESERVED_LOCAL_PERSIST_LEVELS)


def _normalize_optional_text(value: str | None, *, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if max_length is not None:
        return normalized[:max_length]
    return normalized


def _normalize_required_text(value: str, *, field_name: str, max_length: int | None = None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空")
    if max_length is not None:
        return normalized[:max_length]
    return normalized


def _normalize_strict_optional_text(
    value: Any, *, field_name: str, max_length: int
) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(
            f"{field_name} 长度 {len(normalized)} 超出上限 {max_length}"
        )
    return normalized


def _normalize_tags(value: list[str] | None) -> list[str]:
    if not value:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized[:30])
    return result[:12]


def _normalize_optional_uri(value: str | None, *, field_name: str = "uri") -> str | None:
    return _normalize_strict_optional_text(value, field_name=field_name, max_length=1000)


def _normalize_json_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} 必须是对象")
    return dict(value)


def _normalize_optional_enum_text(
    value: Any,
    *,
    field_name: str,
    allowed_values: set[str],
    reserved_values: set[str] | None = None,
) -> str | None:
    normalized = _normalize_optional_text(str(value) if value is not None else None)
    if normalized is None:
        return None
    normalized = normalized.lower()
    if normalized not in allowed_values:
        raise ValueError(f"{field_name} 必须是 {sorted(allowed_values)} 之一")
    if reserved_values and normalized in reserved_values:
        raise ValueError(
            f"{field_name} = {normalized!r} 为 reserved 取值，运行时尚未实现，禁止写入"
        )
    return normalized


def _normalize_metadata_json(value: Any) -> dict[str, Any]:
    metadata = _normalize_json_object(value, field_name="metadata_json")

    if "local_storage_driver" in metadata:
        metadata["local_storage_driver"] = _normalize_optional_enum_text(
            metadata.get("local_storage_driver"),
            field_name="metadata_json.local_storage_driver",
            allowed_values=ALLOWED_LOCAL_STORAGE_DRIVERS,
            reserved_values=RESERVED_LOCAL_STORAGE_DRIVERS,
        )

    if "local_persist_level" in metadata:
        metadata["local_persist_level"] = _normalize_optional_enum_text(
            metadata.get("local_persist_level"),
            field_name="metadata_json.local_persist_level",
            allowed_values=ALLOWED_LOCAL_PERSIST_LEVELS,
            reserved_values=RESERVED_LOCAL_PERSIST_LEVELS,
        )

    if "local_storage_path" in metadata:
        metadata["local_storage_path"] = _normalize_strict_optional_text(
            metadata.get("local_storage_path"),
            field_name="metadata_json.local_storage_path",
            max_length=USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH,
        )

    if "external_relative_path" in metadata:
        metadata["external_relative_path"] = _normalize_strict_optional_text(
            metadata.get("external_relative_path"),
            field_name="metadata_json.external_relative_path",
            max_length=USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH,
        )

    return metadata


class UserAssetMetadata(BaseModel):
    local_storage_driver: UserAssetActiveLocalStorageDriver | None = Field(
        default=None,
        description=USER_ASSET_LOCAL_STORAGE_DRIVER_DESCRIPTION,
    )
    local_storage_path: str | None = Field(
        default=None,
        max_length=USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH,
        description=USER_ASSET_LOCAL_STORAGE_PATH_DESCRIPTION,
    )
    local_persist_level: UserAssetActiveLocalPersistLevel | None = Field(
        default=None,
        description=USER_ASSET_LOCAL_PERSIST_LEVEL_DESCRIPTION,
    )
    external_relative_path: str | None = Field(
        default=None,
        max_length=USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH,
        description=USER_ASSET_EXTERNAL_RELATIVE_PATH_DESCRIPTION,
    )

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "$id": USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_ID,
            "x-contract-path": USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_PATH,
            "x-contract-version": USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_VERSION,
            "x-contract-doc": USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH,
            "x-contract-owner": USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_OWNER,
        },
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_contract_fields(cls, value: Any) -> dict[str, Any]:
        return _normalize_metadata_json(value)


def _dump_user_asset_metadata(value: UserAssetMetadata | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, UserAssetMetadata):
        return value.model_dump(mode="python")
    return UserAssetMetadata.model_validate(value).model_dump(mode="python")


class UserAssetRecordCreate(BaseModel):
    project_id: int | None = None
    source_module: str
    asset_kind: str
    asset_class: str = "reusable"
    asset_uuid: str
    storage_mode: str
    title: str
    description: str | None = None
    source_uri: str | None = None
    preview_uri: str | None = None
    download_uri: str | None = None
    mime_type: str | None = None
    file_size: int | None = Field(default=None, ge=0)
    checksum: str | None = None
    expires_at: datetime | None = None
    model_id: str | None = None
    generation_mode: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata_json: UserAssetMetadata = Field(default_factory=UserAssetMetadata)
    source_payload_json: dict[str, Any] = Field(default_factory=dict)
    is_favorite: bool = False

    @field_validator("source_module")
    @classmethod
    def validate_source_module(cls, value: str) -> str:
        normalized = str(value or "").strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("source_module 不能为空")
        return normalized[:50]

    @field_validator("asset_kind")
    @classmethod
    def validate_asset_kind(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in ALLOWED_ASSET_KINDS:
            raise ValueError(f"asset_kind 必须是 {sorted(ALLOWED_ASSET_KINDS)} 之一")
        return normalized

    @field_validator("asset_class")
    @classmethod
    def validate_asset_class(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in ALLOWED_ASSET_CLASSES:
            raise ValueError(f"asset_class 必须是 {sorted(ALLOWED_ASSET_CLASSES)} 之一")
        return normalized

    @field_validator("asset_uuid")
    @classmethod
    def validate_asset_uuid(cls, value: str) -> str:
        return _normalize_required_text(value, field_name="asset_uuid", max_length=120)

    @field_validator("storage_mode")
    @classmethod
    def validate_storage_mode(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in ALLOWED_STORAGE_MODES:
            raise ValueError(f"storage_mode 必须是 {sorted(ALLOWED_STORAGE_MODES)} 之一")
        if normalized in RESERVED_STORAGE_MODES:
            raise ValueError(
                f"storage_mode = {normalized!r} 为 reserved 取值，运行时尚未实现，禁止写入"
            )
        return normalized

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _normalize_required_text(value, field_name="title", max_length=255)

    @field_validator(
        "description",
        "source_uri",
        "preview_uri",
        "download_uri",
        "mime_type",
        "checksum",
        "model_id",
        "generation_mode",
    )
    @classmethod
    def validate_optional_text(cls, value: str | None, info) -> str | None:
        if info.field_name in {"source_uri", "preview_uri", "download_uri"}:
            return _normalize_optional_uri(value, field_name=info.field_name)
        max_lengths = {
            "mime_type": 120,
            "checksum": 128,
            "model_id": 120,
            "generation_mode": 80,
        }
        return _normalize_optional_text(value, max_length=max_lengths.get(info.field_name))

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        return _normalize_tags(value)

    @field_validator("source_payload_json", mode="before")
    @classmethod
    def validate_source_payload_json(cls, value: Any) -> dict[str, Any]:
        return _normalize_json_object(value, field_name="source_payload_json")


class UserAssetRecordUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    asset_class: str | None = None
    tags: list[str] | None = None
    is_favorite: bool | None = None
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_required_text(value, field_name="title", max_length=255)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("asset_class")
    @classmethod
    def validate_asset_class(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized not in ALLOWED_ASSET_CLASSES:
            raise ValueError(f"asset_class 必须是 {sorted(ALLOWED_ASSET_CLASSES)} 之一")
        return normalized

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_tags(value)


class UserAssetRecordBatchUpdateRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=100)
    updates: UserAssetRecordUpdate

    @field_validator("asset_ids")
    @classmethod
    def validate_asset_ids(cls, value: list[int]) -> list[int]:
        normalized_ids: list[int] = []
        seen: set[int] = set()

        for item in value:
            asset_id = int(item)
            if asset_id <= 0:
                raise ValueError("asset_ids 必须是正整数")
            if asset_id in seen:
                continue
            seen.add(asset_id)
            normalized_ids.append(asset_id)

        if not normalized_ids:
            raise ValueError("asset_ids 不能为空")
        return normalized_ids


class UserAssetRecordBatchUpdateResponse(BaseModel):
    updated_count: int
    asset_ids: list[int] = Field(default_factory=list)
    assets: list["UserAssetRecordResponse"] = Field(default_factory=list)


class UserAssetRecordResponse(BaseModel):
    id: int
    user_id: int
    project_id: int | None = None
    source_module: str
    asset_kind: str
    asset_class: str
    asset_uuid: str
    storage_mode: str
    title: str
    description: str | None = None
    source_uri: str | None = None
    preview_uri: str | None = None
    download_uri: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    checksum: str | None = None
    expires_at: datetime | None = None
    model_id: str | None = None
    generation_mode: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata_json: UserAssetMetadata = Field(default_factory=UserAssetMetadata)
    source_payload_json: dict[str, Any] = Field(default_factory=dict)
    is_favorite: bool = False
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserAssetListSummaryResponse(BaseModel):
    total_assets: int = 0
    active_asset_count: int = 0
    archived_asset_count: int = 0
    favorite_asset_count: int = 0
    reusable_asset_count: int = 0
    deliverable_asset_count: int = 0


class UserAssetListFilterOptionsResponse(BaseModel):
    asset_kinds: list[str] = Field(default_factory=list)
    source_modules: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class UserAssetRecordListResponse(BaseModel):
    total: int = 0
    page: int = 1
    page_size: int = 0
    total_pages: int = 0
    items: list[UserAssetRecordResponse] = Field(default_factory=list)
    summary: UserAssetListSummaryResponse = Field(default_factory=UserAssetListSummaryResponse)
    filter_options: UserAssetListFilterOptionsResponse = Field(default_factory=UserAssetListFilterOptionsResponse)
