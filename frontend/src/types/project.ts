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

export interface MultiModelReviewConfig {
  enabled: boolean
  preset: ReviewPreset
  auto_scenarios: AutoReviewScenario[]
  manual_depth: ReviewPreset
  key_chapter_depth: KeyChapterReviewPreset
  chief_model: string
  custom_panel?: Record<string, unknown> | null
}

export interface ReviewConfigPayload {
  multi_model_review: MultiModelReviewConfig
}

export interface ReviewConfigResponse extends ReviewConfigPayload {
  system_enabled: boolean
  available_presets: ReviewPreset[]
}
