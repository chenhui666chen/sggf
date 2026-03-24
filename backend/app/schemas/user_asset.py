"""
用户资产记录 Schema
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


ALLOWED_ASSET_KINDS = {"image", "video", "audio", "voice", "template", "document"}
ALLOWED_ASSET_CLASSES = {"reusable", "deliverable"}


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


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


class UserAssetRecordCreate(BaseModel):
    project_id: int | None = None
    source_module: str
    asset_kind: str
    asset_class: str = "reusable"
    title: str
    description: str | None = None
    file_url: str
    preview_url: str | None = None
    model_id: str | None = None
    generation_mode: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
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

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("title 不能为空")
        return normalized[:255]

    @field_validator("description", "preview_url", "model_id", "generation_mode")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("file_url")
    @classmethod
    def validate_file_url(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("file_url 不能为空")
        return normalized[:1000]

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        return _normalize_tags(value)


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
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("title 不能为空")
        return normalized[:255]

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
    title: str
    description: str | None = None
    file_url: str | None = None
    preview_url: str | None = None
    model_id: str | None = None
    generation_mode: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    source_payload_json: dict[str, Any] = Field(default_factory=dict)
    is_favorite: bool = False
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
