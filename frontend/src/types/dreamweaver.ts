export type QualityMode = 'quality' | 'cost'
export type TaskStatusType = 'queued' | 'running' | 'completed' | 'failed' | 'waiting'
export type AssetPlanStatus = 'planned' | 'done' | 'processing'
export type AssetPlanKind = 'image' | 'video'
export type LibraryEntityGroup = 'character' | 'scene' | 'prop' | 'other'

export interface PersistedDreamWeaverRun {
  project_id: number
  run_id: string
  task_id?: string | null
  status?: string | null
  quality_mode?: QualityMode
  qc_allow_fail?: boolean
  smart_tuning?: boolean
  video_require_confirmation?: boolean
  prompt_review_required?: boolean
  style_preset?: string
  image_ratio?: string
  image_resolution?: string
  video_fps?: number
  selected_chapter_ids?: number[]
  updated_at: number
}

export interface Project {
  id: number
  display_no?: number
  title: string
  description?: string
}

export interface Chapter {
  id: number
  chapter_number: number
  title: string
  content: string
}

export interface RunResult {
  run_id: string
  state: string
  stage?: string | null
  progress?: number | null
  artifacts?: Record<string, unknown> | null
  source_chapter_count: number
  plan?: Record<string, unknown>
  storyboard?: unknown[]
  camera_tree_generation?: Record<string, unknown> | null
  camera_tree?: unknown[] | null
  camera_states?: unknown[] | null
  camera_scenes?: unknown[] | null
  keyframes?: unknown[]
  midframes?: unknown[]
  video_clips?: unknown[]
  merged_video?: string | null
  audit?: Record<string, unknown>
  autoqc?: Record<string, unknown>
  qc_warning?: Record<string, unknown>
}

export interface TaskStatus {
  task_id: string
  status: TaskStatusType
  progress: number
  run_id?: string | null
  queue?: string | null
  state?: string | null
  stage?: string | null
  artifacts?: Record<string, unknown> | null
  error_type?: string | null
  result?: RunResult | null
  error?: string | null
}

export interface LibraryAsset {
  id: number
  role: string
  uri: string
  meta?: Record<string, unknown>
}

export interface LibraryPayload {
  project_id: number
  spec: Record<string, unknown>
  review: Record<string, unknown>
  assets: LibraryAsset[]
}

export interface CollectFeedback {
  type: 'success' | 'error'
  text: string
}

export interface DreamweaverEventRecord {
  event_id: number
  run_id: string
  project_id: number
  stage?: string | null
  event_type: string
  payload?: Record<string, unknown>
  created_at?: string | null
}

export interface DreamweaverAssetPlanItem {
  id: string
  shot_id?: string | null
  scene_id?: string | null
  cam_idx?: number | null
  role?: string | null
  kind?: AssetPlanKind
  label?: string
  status?: AssetPlanStatus
  optional?: boolean
  uri?: string | null
}

export interface DreamweaverLibraryPlanItem {
  id: string
  role: string
  entity_type?: string | null
  entity_id?: number | null
  entity_name?: string | null
  label?: string
  view?: string | null
  status?: AssetPlanStatus
  kind?: 'image'
  uri?: string | null
  asset_id?: number | null
  approved?: boolean | null
}

export interface LibraryDisplayItem {
  key: string
  role: string
  title: string
  preview: string
  aspectRatio: string
  approved: boolean
  status: AssetPlanStatus
  group: LibraryEntityGroup
  view?: string | null
  viewRank: number
  asset?: LibraryAsset
  missing?: boolean
  placeholder?: boolean
  hasRenderableImage?: boolean
  imageState?: string | null
  safety_blocked?: boolean
  safety_error?: string | null
}

export interface DreamweaverRunSummary {
  run_id: string
  status: string
  state?: string | null
  stage?: string | null
  progress?: number | null
  schema_version?: string | null
  error_type?: string | null
  error_message?: string | null
  created_at?: string | null
  updated_at?: string | null
  camera_tree_mode?: string | null
  camera_count?: number | null
  camera_states_count?: number | null
  camera_scenes_count?: number | null
}

export interface DreamweaverProjectLockedGenerationConfig {
  locked: boolean
  style_preset?: string | null
  image_ratio?: string | null
  image_resolution?: string | null
  video_fps?: number | null
  quality_mode?: QualityMode | null
  smart_tuning?: boolean | null
  video_require_confirmation?: boolean | null
  prompt_review_required?: boolean | null
  source_run_id?: string | null
}

export type CharacterView = 'front' | 'side' | 'back' | 'half_front' | 'half_3_4' | 'half_side'

export interface ParsedLibraryRole {
  entityType: 'character' | 'scene' | 'prop' | 'unknown'
  entityId: number | null
  view: CharacterView | null
}

export interface ScriptGeneration {
  mode?: string
  model?: string | null
  error?: string | null
}

export interface VideoDiagnostics {
  clipCount: number
  viaSummary: string
  fallbackCount: number
  errorCount: number
}

export interface BulkDeleteProgress {
  current: number
  total: number
}

export interface BulkDeleteResult {
  deleted: number
  skipped: number
  failed: number
  errors: string[]
}

export interface StreamSnapshots {
  plan?: string
  script?: string
  scriptEnhance?: string
  characterProfiles?: string
  audioMarkers?: string
  storyboard?: string
  cameraTree?: string
}
