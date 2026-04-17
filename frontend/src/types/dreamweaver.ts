import type { LibraryAssetImageState } from '../utils/dreamweaverLibraryAssetState'
import type { CharacterView } from '../utils/dreamweaverLibraryRole'

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
  artifacts?: DreamweaverTaskArtifacts | null
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
  preflight?: DreamweaverRunPreflight | null
  video_provider_trace?: DreamweaverVideoProviderTrace | null
}

export interface TaskStatus {
  task_id: string
  status: TaskStatusType
  progress: number
  run_id?: string | null
  queue?: string | null
  state?: string | null
  stage?: string | null
  artifacts?: DreamweaverTaskArtifacts | null
  error_type?: string | null
  result?: RunResult | null
  error?: string | null
}

export interface DreamweaverPreflightIssue {
  level: string
  code: string
  message: string
}

export interface DreamweaverRunPreflight {
  allowed: boolean
  errors: DreamweaverPreflightIssue[]
  warnings: DreamweaverPreflightIssue[]
  resolved_video_config?: Record<string, unknown>
}

export interface DreamweaverVideoProviderShotTrace {
  shot_id: string
  requested_provider_mode?: string
  selector_mode?: string
  recommended_provider?: string
  applied_provider?: string
  route?: string
  reason?: string
  shadowed?: boolean
  metadata?: Record<string, unknown>
}

export interface DreamweaverVideoProviderTrace {
  provider_mode?: string
  selector_mode?: string
  allow_kling_omni?: boolean
  enable_kling_video_provider?: boolean
  allow_subject_bridge?: boolean
  shots: DreamweaverVideoProviderShotTrace[]
}

export interface DreamweaverRunAsyncResponse {
  task_id: string
  run_id: string
  status: TaskStatusType
  preflight?: DreamweaverRunPreflight | null
}

export interface DreamweaverRunSnapshot {
  dreamweaver_project_id: number
  run_id: string
  status: string
  state?: string | null
  stage?: string | null
  progress?: number | null
  schema_version?: string | null
  error_type?: string | null
  error_message?: string | null
  contract?: Record<string, unknown> | null
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
  view?: CharacterView | null
  viewRank: number
  asset?: LibraryAsset
  missing?: boolean
  placeholder?: boolean
  hasRenderableImage?: boolean
  imageState?: LibraryAssetImageState | null
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

export interface DreamweaverScriptEntityItem extends Record<string, unknown> {
  name?: string | null
  descriptor?: string | null
  importance?: string | null
}

export interface DreamweaverScriptEntities {
  characters: DreamweaverScriptEntityItem[]
  scenes: DreamweaverScriptEntityItem[]
  props: DreamweaverScriptEntityItem[]
}

export interface DreamweaverTaskStageArtifacts extends Record<string, unknown> {
  camera_tree_mode?: string | null
  camera_count?: number | null
  camera_states_count?: number | null
  camera_scenes_count?: number | null
}

export interface DreamweaverTaskArtifacts extends Record<string, unknown> {
  storyboard_count?: number | null
  keyframes_count?: number | null
  midframes_count?: number | null
  video_clips_count?: number | null
  last_keyframe_path?: string | null
  last_midframe_path?: string | null
  last_video_clip_path?: string | null
  keyframes_tail_paths?: string[] | null
  midframes_tail_paths?: string[] | null
  video_clips_tail_paths?: string[] | null
  rework_reason?: Record<string, unknown> | null
  stage_artifacts?: DreamweaverTaskStageArtifacts | null
}

export interface DreamweaverShotAsset extends Record<string, unknown> {
  role?: string | null
  uri?: string | null
  meta?: Record<string, unknown> | null
}

export interface DreamweaverShotFrame extends Record<string, unknown> {
  path?: string | null
  prompt?: string | null
  meta?: Record<string, unknown> | null
}

export interface DreamweaverShotSchemaMeta extends Record<string, unknown> {
  video_prompt_generated?: string | null
  video_prompt_override?: string | null
}

export interface DreamweaverShotSchema extends Record<string, unknown> {
  meta?: DreamweaverShotSchemaMeta | null
}

export interface DreamweaverShotSnapshot extends Record<string, unknown> {
  shot_key?: string | null
  shot_id?: string | null
  shot_index?: number | null
  scene_id?: string | number | null
  duration_s?: number | null
  desc?: string | null
  head_frame?: DreamweaverShotFrame | null
  tail_frame?: DreamweaverShotFrame | null
  shot_schema_v2?: DreamweaverShotSchema | null
  assets?: DreamweaverShotAsset[] | null
}

export interface DreamweaverVideoClipJob extends Record<string, unknown> {
  shot_id?: string | null
  desc?: string | null
  status?: string | null
  confirmed?: boolean | null
  requires_bridge?: boolean | null
  depends_on_shot_id?: string | null
}

export interface DreamweaverDiagnosticShotFrames {
  head?: Record<string, unknown> | null
  tail?: Record<string, unknown> | null
  mid?: Record<string, unknown> | null
}

export interface DreamweaverDiagnosticShot {
  shot_id: string
  storyboard?: Record<string, unknown> | null
  frames?: DreamweaverDiagnosticShotFrames | null
  video_clip?: Record<string, unknown> | null
}

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
