from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


ReviewPreset = Literal["balanced_3", "key_chapter_5", "deep_7"]
KeyChapterReviewPreset = Literal["key_chapter_5", "deep_7"]
AutoReviewScenario = Literal["first_chapter", "key_chapter", "final_chapter"]


class MultiModelReviewConfig(BaseModel):
    enabled: bool = False
    preset: ReviewPreset = "balanced_3"
    auto_scenarios: list[AutoReviewScenario] = Field(default_factory=list)
    manual_depth: ReviewPreset = "balanced_3"
    key_chapter_depth: KeyChapterReviewPreset = "key_chapter_5"
    chief_model: str = "deepseek-v4-pro"
    custom_panel: Optional[dict[str, Any]] = None

    @field_validator("auto_scenarios")
    @classmethod
    def dedupe_auto_scenarios(cls, value: list[AutoReviewScenario]) -> list[AutoReviewScenario]:
        return list(dict.fromkeys(value))


class ReviewConfigUpdate(BaseModel):
    multi_model_review: MultiModelReviewConfig


class ReviewConfigResponse(BaseModel):
    multi_model_review: MultiModelReviewConfig
    system_enabled: bool
    available_presets: list[ReviewPreset]
