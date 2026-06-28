from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


ReviewPreset = Literal["balanced_3", "key_chapter_5", "deep_7"]
ReviewStrategyPreset = Optional[ReviewPreset]
KeyChapterReviewPreset = Literal["key_chapter_5", "deep_7"]
AutoReviewScenario = Literal["first_chapter", "key_chapter", "final_chapter"]


class ReviewAutoStrategy(BaseModel):
    regular: ReviewStrategyPreset = None
    opening: ReviewStrategyPreset = "key_chapter_5"
    key: ReviewStrategyPreset = "key_chapter_5"
    finale: ReviewStrategyPreset = "deep_7"


class MultiModelReviewConfig(BaseModel):
    enabled: bool = False
    preset: ReviewPreset = "balanced_3"
    auto_scenarios: list[AutoReviewScenario] = Field(default_factory=list)
    manual_depth: ReviewPreset = "balanced_3"
    key_chapter_depth: KeyChapterReviewPreset = "key_chapter_5"
    auto_strategy: ReviewAutoStrategy = Field(default_factory=ReviewAutoStrategy)
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
    available_presets: list[ReviewPreset]
