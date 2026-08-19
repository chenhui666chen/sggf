"""
协同扩展协议 Schema
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoryExpansionWrittenContextResponse(_StrictModel):
    applied: Optional[bool] = None
    written_chapter_count: Optional[int] = None
    preserve_written_mode: Optional[str] = None
    preview: Optional[str] = None


class StoryExpansionValidationStatsResponse(_StrictModel):
    score: Optional[float] = None
    coverage_ratio: Optional[float] = None
    unreferenced_characters: list[str] = Field(default_factory=list)
    referenced_characters: list[str] = Field(default_factory=list)
    chapter_count: Optional[int] = None
    character_count: Optional[int] = None
    suggestions: list[str] = Field(default_factory=list)
    validation_stage: Optional[str] = None


class StoryExpansionModelPlanResponse(_StrictModel):
    coordinator_planner_model: Optional[str] = None
    coordinator_writer_model: Optional[str] = None
    coordinator_planner_max_tokens: Optional[int] = None
    coordinator_writer_max_tokens: Optional[int] = None
    coordinator_planner_timeout_seconds: Optional[int] = None
    coordinator_writer_timeout_seconds: Optional[int] = None
    coordinator_planner_estimated_output_tokens: Optional[int] = None
    coordinator_writer_estimated_output_tokens: Optional[int] = None
    outline_expansion_model: Optional[str] = None
    character_expansion_model: Optional[str] = None
    estimated_rounds: Optional[int] = None
    selection_reason: Optional[str] = None
    selection_quality_guard: Optional[str] = None
    selection_cost_hint: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class StoryExpansionModeSuitabilityBandResponse(_StrictModel):
    key: Optional[str] = None
    label: Optional[str] = None
    range_text: Optional[str] = None
    detail: Optional[str] = None


class StoryExpansionModeSuitabilityResponse(_StrictModel):
    mode: Optional[str] = None
    request_band: Optional[str] = None
    request_band_label: Optional[str] = None
    request_band_reason: Optional[str] = None
    current_total_chapters: Optional[int] = None
    target_total_chapters: Optional[int] = None
    chapters_needed: Optional[int] = None
    execution_mode: Optional[str] = None
    recommended_total_chapters_max: Optional[int] = None
    caution_total_chapters_min: Optional[int] = None
    caution_total_chapters_max: Optional[int] = None
    framework_preferred_total_from: Optional[int] = None
    epic_auto_switch_total_from: Optional[int] = None
    preferred_iterative_step: Optional[int] = None
    single_round_delta_limit: Optional[int] = None
    summary: Optional[str] = None
    bands: list[StoryExpansionModeSuitabilityBandResponse] = Field(default_factory=list)


class StoryExpansionEpicConfigResponse(_StrictModel):
    total_volumes: Optional[int] = None
    chapter_range: Optional[list[int]] = None


class StoryExpansionVolumeDetailAnalysisResponse(_StrictModel):
    target_volume_index: Optional[int] = None
    chapter_range: Optional[list[int]] = None
    character_increment: Optional[int] = None
    target_character_count: Optional[int] = None
    existing_detail: Optional[bool] = None


class StoryExpansionAutoSupplementCharacterPlanResponse(_StrictModel):
    recommended_min: Optional[int] = None
    recommended_max: Optional[int] = None
    recommended_range_text: Optional[str] = None
    recommended_additional_min: Optional[int] = None
    recommended_additional_max: Optional[int] = None
    stage_label: Optional[str] = None
    suggested_increment: Optional[int] = None
    stage_target_characters: Optional[int] = None
    task_target_characters: Optional[int] = None
    task_target_increment: Optional[int] = None
    remaining_to_recommended_min: Optional[int] = None
    follow_up_phase: Optional[str] = None
    is_phased: Optional[bool] = None


class StoryExpansionAutoSupplementResponse(_StrictModel):
    chapter_delta: Optional[int] = None
    character_delta: Optional[int] = None
    reasons: list[str] = Field(default_factory=list)
    suggested_target_chapters: Optional[int] = None
    suggested_target_characters: Optional[int] = None
    character_plan: Optional[StoryExpansionAutoSupplementCharacterPlanResponse] = None


class StoryExpansionAnalysisPayload(_StrictModel):
    execution_mode: Optional[str] = None
    execution_mode_reason: Optional[str] = None
    recommended_strategy: Optional[str] = None
    effective_strategy: Optional[str] = None
    recommended_intent: Optional[str] = None
    effective_intent: Optional[str] = None
    intent_reason: Optional[str] = None
    effective_target_chapter_count: Optional[int] = None
    effective_target_character_count: Optional[int] = None
    requested_target_chapter_count: Optional[int] = None
    requested_target_character_count: Optional[int] = None
    requested_volume_character_increment: Optional[int] = None
    effective_volume_character_increment: Optional[int] = None
    requested_expansion_mode: Optional[str] = None
    effective_expansion_mode: Optional[str] = None
    estimated_rounds: Optional[int] = None
    estimated_duration_minutes_min: Optional[int] = None
    estimated_duration_minutes_max: Optional[int] = None
    duration_estimate_base_minutes_min: Optional[int] = None
    duration_estimate_base_minutes_max: Optional[int] = None
    duration_estimate_source: Optional[str] = None
    duration_estimate_confidence: Optional[str] = None
    duration_estimate_sample_count: Optional[int] = None
    duration_estimate_calibration_ratio: Optional[float] = None
    duration_estimate_reason: Optional[str] = None
    auto_supplement_applied: Optional[bool] = None
    analysis_summary: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    epic_config: Optional[StoryExpansionEpicConfigResponse] = None
    volume_detail: Optional[StoryExpansionVolumeDetailAnalysisResponse] = None
    validation: Optional[StoryExpansionValidationStatsResponse] = None
    auto_supplement: Optional[StoryExpansionAutoSupplementResponse] = None
    model_plan: Optional[StoryExpansionModelPlanResponse] = None
    mode_suitability: Optional[StoryExpansionModeSuitabilityResponse] = None
    written_chapter_context: Optional[StoryExpansionWrittenContextResponse] = None

    model_config = ConfigDict(extra="ignore")


class StoryExpansionAnalysisRouteResponse(_StrictModel):
    success: bool
    analysis: StoryExpansionAnalysisPayload


class StoryExpansionStartResponse(_StrictModel):
    success: bool
    task_id: str
    message: str


class StoryExpansionRepairRequest(_StrictModel):
    project_id: int
    story_expansion_mode: Optional[str] = None
    volume_index: Optional[int] = None


class StoryExpansionRepairResponse(_StrictModel):
    success: bool
    result: "StoryExpansionTaskResultResponse"
    message: str


class StoryExpansionOutlineOperationResponse(_StrictModel):
    action: Optional[str] = None
    after_chapter: Optional[int] = None
    requested_count: Optional[int] = None
    generated_count: Optional[int] = None
    goal: Optional[str] = None
    generated_titles: list[str] = Field(default_factory=list)


class StoryExpansionExecutionRoundResponse(BaseModel):
    round: Optional[int] = None
    stage: Optional[str] = None
    mode: Optional[str] = None
    strategy: Optional[str] = None
    before_chapter_count: Optional[int] = None
    after_chapter_count: Optional[int] = None
    before_character_count: Optional[int] = None
    after_character_count: Optional[int] = None
    chapters_generated: Optional[int] = None
    characters_generated: Optional[int] = None
    volume_index: Optional[int] = None
    chapter_range: Optional[list[int]] = None
    target_chapter_range: Optional[list[int]] = None
    estimated_chapters: Optional[int] = None
    volumes: Optional[int] = None
    plot: Optional[dict[str, Any]] = None
    character: Optional[dict[str, Any]] = None
    validation: Optional[dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")


class StoryExpansionCharacterSyncRelationshipsResponse(_StrictModel):
    parsed: Optional[int] = None
    saved: Optional[int] = None
    characters_updated: Optional[int] = None


class StoryExpansionCharacterSyncResponse(_StrictModel):
    parsed: Optional[int] = None
    created: Optional[int] = None
    updated: Optional[int] = None
    skipped: Optional[int] = None
    relationships: Optional[StoryExpansionCharacterSyncRelationshipsResponse] = None


class StoryExpansionCharacterArchiveResponse(_StrictModel):
    archived: int = 0
    names: list[str] = Field(default_factory=list)


class StoryExpansionAlignmentCompactResponse(_StrictModel):
    score: int = 0
    redundant_characters: list[str] = Field(default_factory=list)
    missing_characters: list[str] = Field(default_factory=list)
    relationship_issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class StoryExpansionTaskResultResponse(_StrictModel):
    expanded_outline: str
    all_characters: str
    outline_delta: str = ""
    character_delta: str = ""
    character_relationships: str = ""
    outline_ops: list[StoryExpansionOutlineOperationResponse] = Field(default_factory=list)
    execution_mode: Optional[str] = None
    execution_mode_reason: Optional[str] = None
    execution_rounds: list[StoryExpansionExecutionRoundResponse] = Field(default_factory=list)
    new_characters: list[str] = Field(default_factory=list)
    alignment_repairs: list[str] = Field(default_factory=list)
    alignment_gate_status: Optional[str] = None
    alignment_gate_retry: Optional[dict[str, Any]] = None
    alignment_structural_debt: Optional[str] = None
    character_plot_alignment: Optional[StoryExpansionAlignmentCompactResponse] = None
    story_strategy: Optional[str] = None
    story_intent: Optional[str] = None
    story_expansion_mode: Optional[str] = None
    story_preserve_written_mode: Optional[str] = None
    written_chapter_context: Optional[StoryExpansionWrittenContextResponse] = None
    volume_index: Optional[int] = None
    volume_chapter_range: Optional[list[int]] = None
    coordination_summary: Optional[str] = None
    current_chapter_count: Optional[int] = None
    target_chapter_count: Optional[int] = None
    current_character_count: Optional[int] = None
    target_character_count: Optional[int] = None
    validation_before: Optional[StoryExpansionValidationStatsResponse] = None
    validation_after: Optional[StoryExpansionValidationStatsResponse] = None
    alignment_warnings: list[str] = Field(default_factory=list)
    character_sync: Optional[StoryExpansionCharacterSyncResponse] = None
    character_archive: Optional[StoryExpansionCharacterArchiveResponse] = None
    stop_reasons: list[str] = Field(default_factory=list)
    expansion_analysis: Optional[StoryExpansionAnalysisPayload] = None
    epic_total_volumes: Optional[int] = None
    epic_chapter_range: Optional[list[int]] = None
    completion_status: Optional[str] = None
    goal_reached: Optional[bool] = None
    message: str


StoryExpansionRepairResponse.model_rebuild()
