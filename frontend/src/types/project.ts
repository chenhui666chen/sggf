export interface Project {
  id: number
  display_no: number
  user_id: number
  title: string
  description?: string
  genre?: string
  sub_genre?: string
  planned_length_type?: string
  planned_chapters_min?: number
  planned_chapters_max?: number
  user_outline_plan?: string
  status: string
  word_count: number
  created_at: string
  updated_at: string
}

export interface ProjectCreatePayload {
  title: string
  description?: string
  genre?: string
  sub_genre?: string
  planned_length_type?: string
  planned_chapters_min?: number
  planned_chapters_max?: number
  user_outline_plan?: string
}

export type ProjectUpdatePayload = Partial<ProjectCreatePayload> & Record<string, unknown>

export type ReviewPreset = 'balanced_3' | 'key_chapter_5' | 'deep_7'
export type KeyChapterReviewPreset = 'key_chapter_5' | 'deep_7'
export type AutoReviewScenario = 'first_chapter' | 'key_chapter' | 'final_chapter'
export type ReviewStrategyPreset = ReviewPreset | null

export interface ReviewAutoStrategy {
  regular: ReviewStrategyPreset
  opening: ReviewStrategyPreset
  key: ReviewStrategyPreset
  finale: ReviewStrategyPreset
}

export interface MultiModelReviewConfig {
  enabled: boolean
  preset: ReviewPreset
  auto_scenarios: AutoReviewScenario[]
  manual_depth: ReviewPreset
  key_chapter_depth: KeyChapterReviewPreset
  auto_strategy: ReviewAutoStrategy
  chief_model: string
  custom_panel?: Record<string, unknown> | null
}

export interface ReviewConfigPayload {
  multi_model_review: MultiModelReviewConfig
}

export interface ReviewConfigResponse extends ReviewConfigPayload {
  available_presets: ReviewPreset[]
}

export interface ReviewMetaReport {
  requested_model_id?: string
  resolved_model_id?: string
  model_id?: string
  profile?: string
  status?: string
  input_was_clipped?: boolean
  cost?: number | string | null
  usage_metadata?: Record<string, unknown>
}

export interface ReviewStructuredSummary {
  consensus?: string[]
  divergence?: string[]
  final_suggestions?: string[]
  conclusion?: string
  source_models?: string[]
}

export interface ReviewMeta {
  multi_model?: boolean
  preset?: ReviewPreset | string | null
  chief_model?: string | null
  chief_model_reused_as_reviewer?: boolean
  reviewer_models?: string[]
  reviewer_profiles?: string[]
  per_model_reports?: ReviewMetaReport[]
  fallback_required?: boolean
  fallback_reason?: string | null
  structured_summary?: ReviewStructuredSummary
}

export interface ReviewMetaResponse {
  project_id: number
  review_meta: ReviewMeta
}
