"""公共音色池请求与受控标签定义。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


GenderPresentation = Literal["female", "male", "neutral"]
AgeImpression = Literal["child", "teen", "young_adult", "adult", "mature", "elder"]
RightsBasis = Literal["self_voice", "licensed_voice", "synthetic_source", "synthetic_design"]

VOICE_POOL_GENDER_OPTIONS = ("female", "male", "neutral")
VOICE_POOL_AGE_OPTIONS = ("child", "teen", "young_adult", "adult", "mature", "elder")
VOICE_POOL_STYLE_OPTIONS = (
    "natural",
    "gentle",
    "sweet",
    "bright",
    "restrained",
    "intellectual",
    "powerful",
    "cold",
    "narration",
    "roleplay",
)
VOICE_POOL_TIMBRE_OPTIONS = (
    "clear",
    "warm",
    "bright",
    "deep",
    "magnetic",
    "soft",
    "powerful",
    "slightly_husky",
    "husky",
    "airy",
)
VOICE_POOL_SCENARIO_OPTIONS = (
    "audiobook",
    "dialogue",
    "narration",
    "suspense",
    "romance",
    "historical",
    "fantasy",
    "children",
    "documentary",
    "commercial",
)
VOICE_POOL_EMOTION_OPTIONS = (
    "calm",
    "happy",
    "sad",
    "angry",
    "fearful",
    "tender",
    "tense",
    "surprised",
)


def _normalize_tags(value: list[str], *, field_name: str, allowed: tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for raw in value:
        item = str(raw or "").strip().lower()
        if item and item not in normalized:
            normalized.append(item)
    if not 1 <= len(normalized) <= 5:
        raise ValueError(f"{field_name} must contain between 1 and 5 values")
    invalid = [item for item in normalized if item not in allowed]
    if invalid:
        raise ValueError(f"unsupported {field_name}: {', '.join(invalid)}")
    return normalized


class VoicePoolPublicationCreate(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=500)
    gender_presentation: GenderPresentation
    age_impression: AgeImpression
    primary_style: str
    language: str = Field(min_length=2, max_length=30)
    accent: str = Field(default="", max_length=60)
    timbre_tags: list[str]
    scenario_tags: list[str]
    emotion_tags: list[str] = Field(default_factory=list)
    rights_basis: RightsBasis
    license_version: str = Field(min_length=1, max_length=40)
    consent_at: datetime
    # 仅供发布服务写入可信衍生音频地址，不要求客户端提交。
    public_preview_uri: str = Field(default="", max_length=1000)
    public_reference_uri: str = Field(default="", max_length=1000)

    @field_validator("display_name", "description", "language", "accent", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("primary_style")
    @classmethod
    def validate_primary_style(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in VOICE_POOL_STYLE_OPTIONS:
            raise ValueError("unsupported primary_style")
        return normalized

    @field_validator("timbre_tags")
    @classmethod
    def validate_timbre_tags(cls, value: list[str]) -> list[str]:
        return _normalize_tags(
            value,
            field_name="timbre_tags",
            allowed=VOICE_POOL_TIMBRE_OPTIONS,
        )

    @field_validator("scenario_tags")
    @classmethod
    def validate_scenario_tags(cls, value: list[str]) -> list[str]:
        return _normalize_tags(
            value,
            field_name="scenario_tags",
            allowed=VOICE_POOL_SCENARIO_OPTIONS,
        )

    @field_validator("emotion_tags")
    @classmethod
    def validate_emotion_tags(cls, value: list[str]) -> list[str]:
        if not value:
            return []
        return _normalize_tags(
            value,
            field_name="emotion_tags",
            allowed=VOICE_POOL_EMOTION_OPTIONS,
        )


class VoicePoolReviewRequest(BaseModel):
    approved: bool
    review_note: str = Field(default="", max_length=500)


class VoicePoolRatingRequest(BaseModel):
    score: int = Field(ge=1, le=5)


__all__ = [
    "VOICE_POOL_AGE_OPTIONS",
    "VOICE_POOL_EMOTION_OPTIONS",
    "VOICE_POOL_GENDER_OPTIONS",
    "VOICE_POOL_SCENARIO_OPTIONS",
    "VOICE_POOL_STYLE_OPTIONS",
    "VOICE_POOL_TIMBRE_OPTIONS",
    "VoicePoolPublicationCreate",
    "VoicePoolRatingRequest",
    "VoicePoolReviewRequest",
]
