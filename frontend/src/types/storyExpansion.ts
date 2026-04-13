export type StoryExpansionStrategy = 'auto' | 'balanced' | 'plot_first' | 'character_first'
export type StoryExpansionIntent = 'auto' | 'outline_led' | 'character_led' | 'balanced'
export type StoryExpansionMode = 'total' | 'epic_framework' | 'volume_detail'
export type StoryPreserveWrittenMode = 'extract_extend' | 'preserve_written' | 'regenerate_all'

export interface StoryExpansionFrameworkMetadata {
  has_framework?: boolean
  metadata?: {
    total_volumes?: number
    expanded_volumes?: number[]
  } | null
  framework_generated_at?: string | null
}

export interface StoryExpansionAnalysis {
  execution_mode?: string
  execution_mode_reason?: string
  recommended_strategy?: StoryExpansionStrategy | string
  effective_strategy?: StoryExpansionStrategy | string
  recommended_intent?: StoryExpansionIntent | string
  effective_intent?: StoryExpansionIntent | string
  intent_reason?: string
  effective_target_chapter_count?: number | null
  effective_target_character_count?: number | null
  requested_target_chapter_count?: number | null
  requested_target_character_count?: number | null
  requested_expansion_mode?: StoryExpansionMode | string
  effective_expansion_mode?: StoryExpansionMode | string
  estimated_rounds?: number
  auto_supplement_applied?: boolean
  analysis_summary?: string
  warnings?: string[]
  epic_config?: {
    total_volumes?: number | null
    chapter_range?: number[] | null
  }
  written_chapter_context?: StoryExpansionWrittenContext
  volume_detail?: {
    target_volume_index?: number | null
    chapter_range?: number[] | null
    character_increment?: number | null
    target_character_count?: number | null
    existing_detail?: boolean
  }
  validation?: StoryExpansionValidationStats
  auto_supplement?: {
    chapter_delta?: number
    character_delta?: number
    reasons?: string[]
    suggested_target_chapters?: number | null
    suggested_target_characters?: number | null
    character_plan?: {
      recommended_min?: number | null
      recommended_max?: number | null
      recommended_range_text?: string | null
      recommended_additional_min?: number | null
      recommended_additional_max?: number | null
      stage_label?: string | null
      suggested_increment?: number | null
      stage_target_characters?: number | null
      task_target_characters?: number | null
      task_target_increment?: number | null
      remaining_to_recommended_min?: number | null
      follow_up_phase?: string | null
      is_phased?: boolean | null
    } | null
  }
  model_plan?: {
    coordinator_planner_model?: string
    coordinator_writer_model?: string
    outline_expansion_model?: string
    character_expansion_model?: string
    estimated_rounds?: number
    notes?: string[]
  }
  mode_suitability?: {
    mode?: string
    request_band?: string
    request_band_label?: string
    request_band_reason?: string
    current_total_chapters?: number
    target_total_chapters?: number
    chapters_needed?: number
    execution_mode?: string
    recommended_total_chapters_max?: number
    caution_total_chapters_min?: number
    caution_total_chapters_max?: number
    framework_preferred_total_from?: number
    epic_auto_switch_total_from?: number
    preferred_iterative_step?: number
    single_round_delta_limit?: number
    summary?: string
    bands?: Array<{
      key?: string
      label?: string
      range_text?: string
      detail?: string
    }>
  }
}

export interface StoryExpansionWrittenContext {
  applied?: boolean
  written_chapter_count?: number
  preserve_written_mode?: StoryPreserveWrittenMode | string
  preview?: string
}

export interface StoryExpansionValidationStats {
  score?: number
  coverage_ratio?: number
  unreferenced_characters?: string[]
  chapter_count?: number
  character_count?: number
}

export interface StoryExpansionOutlineOperation {
  action?: string
  after_chapter?: number | null
  requested_count?: number | null
  generated_count?: number | null
  goal?: string
  generated_titles?: string[]
}

export interface StoryExpansionExecutionRound {
  round?: number
  stage?: string
  strategy?: string
  before_chapter_count?: number
  after_chapter_count?: number
  before_character_count?: number
  after_character_count?: number
  plot?: {
    increment_requested?: number | null
  }
  character?: {
    increment_requested?: number | null
    post_validation_score?: number | null
  }
}

export interface StoryExpansionCharacterSync {
  parsed?: number
  created?: number
  updated?: number
  skipped?: number
  relationships?: {
    parsed?: number
    saved?: number
    characters_updated?: number
  }
}

export interface StoryExpansionResult {
  expanded_outline?: string
  all_characters?: string
  outline_delta?: string
  character_delta?: string
  character_relationships?: string
  outline_ops?: StoryExpansionOutlineOperation[]
  execution_mode?: string
  execution_mode_reason?: string
  execution_rounds?: StoryExpansionExecutionRound[]
  new_characters?: string[]
  alignment_repairs?: string[]
  story_strategy?: StoryExpansionStrategy | string
  story_intent?: StoryExpansionIntent | string
  story_expansion_mode?: StoryExpansionMode | string
  story_preserve_written_mode?: StoryPreserveWrittenMode | string
  written_chapter_context?: StoryExpansionWrittenContext
  volume_index?: number | null
  volume_chapter_range?: number[] | null
  coordination_summary?: string
  current_chapter_count?: number
  target_chapter_count?: number
  current_character_count?: number
  target_character_count?: number
  validation_before?: StoryExpansionValidationStats
  validation_after?: StoryExpansionValidationStats
  alignment_warnings?: string[]
  character_sync?: StoryExpansionCharacterSync
  stop_reasons?: string[]
  expansion_analysis?: StoryExpansionAnalysis
  epic_total_volumes?: number | null
  epic_chapter_range?: number[] | null
  message?: string
}

export interface StoryExpansionRequestPayload {
  project_id: number
  current_outline: string
  world_setting: string
  characters: string
  current_chapter_count: number
  current_character_count: number
  target_total_chapters?: number
  target_total_characters?: number
  strategy: StoryExpansionStrategy | string
  intent: StoryExpansionIntent | string
  enable_auto_supplement: boolean
  expansion_mode: StoryExpansionMode | string
  total_volumes?: number
  total_chapters_min?: number
  total_chapters_max?: number
  target_volume_index?: number
  volume_chapters_min?: number
  volume_chapters_max?: number
  volume_character_increment?: number
  preserve_written_mode: StoryPreserveWrittenMode | string
  reset_epic_framework?: boolean
}

export interface StoryExpansionAnalysisResponse {
  success?: boolean
  analysis?: StoryExpansionAnalysis | null
}

export interface StoryExpansionStartResponse {
  success?: boolean
  task_id?: string | null
  message?: string
}
