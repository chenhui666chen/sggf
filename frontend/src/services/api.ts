import axios, { AxiosInstance, AxiosError } from 'axios'
import type {
  AudiobookTtsModel,
  DeletedChapterAudio,
  UserAudiobookProjectOverview,
} from '@/types/audiobook'
import type { Project, ProjectCreatePayload, ProjectUpdatePayload } from '@/types/project'
import type {
  SettingCollection,
  SettingCollectionCreatePayload,
  SettingCollectionUpdatePayload,
  SettingItem,
  SettingItemCreatePayload,
  SettingItemsTreeResponse,
  SettingItemUpdatePayload,
  SettingSmartExtractResponse,
  SettingTemplateMetadata,
} from '@/types/settings'
import type {
  StoryExpansionAnalysisResponse,
  StoryExpansionRepairRequestPayload,
  StoryExpansionRepairResponse,
  StoryExpansionRequestPayload,
  StoryExpansionStartResponse,
} from '@/types/storyExpansion'
import type {
  DreamweaverRunAsyncResponse,
  DreamweaverRunSnapshot,
  RunResult,
  TaskStatus,
} from '@/types/dreamweaver'
import { normalizeUserAssetMetadataContract } from '@/contracts/userAssetLocalStorageContract'
import type { UserAssetMetadata } from '@/types/userAsset'

// 在开发环境中直接连接到后端，不使用Vite代理
const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
const DREAMWEAVER_SCHEMA_VERSION = '0.1.0'
const DREAMWEAVER_LIBRARY_REGENERATE_TIMEOUT_MS = Math.max(
  120000,
  Number.parseInt(String(import.meta.env.VITE_DREAMWEAVER_LIBRARY_REGENERATE_TIMEOUT_MS || '600000'), 10) || 600000,
)

type DreamweaverQualityMode = 'quality' | 'cost'

interface DreamweaverRunOptions {
  quality_mode?: DreamweaverQualityMode
  qc_allow_fail?: boolean
  smart_tuning?: boolean
  ab_variant?: string
  video_require_confirmation?: boolean
  prompt_review_required?: boolean
  style_preset?: string
  image_ratio?: string
  image_resolution?: string
  image_model?: string
  video_model?: string
  video_edit_model?: string
  vision_model?: string
  enable_video_edit?: boolean
  enable_vision_review?: boolean
  enable_safety_audit?: boolean
  safety_fail_policy?: 'warn' | 'block'
  schema_version?: string
}

interface DreamweaverProjectLockedGenerationConfig {
  locked: boolean
  style_preset: string
  image_ratio: string
  image_resolution: string
  image_model?: string | null
  video_model?: string | null
  video_edit_model?: string | null
  vision_model?: string | null
  enable_video_edit?: boolean | null
  enable_vision_review?: boolean | null
  enable_safety_audit?: boolean | null
  safety_fail_policy?: 'warn' | 'block' | string | null
  source_run_id?: string | null
}

interface DreamweaverLibraryApproveRequest {
  approve_all?: boolean
  roles?: string[]
  approved?: boolean
}

interface DreamweaverSafetyAuditApproveResponse {
  run_id: string
  status: string
  state?: string | null
  stage?: string | null
  manual_override: boolean
}

interface DreamweaverLibraryRegenerateRequest {
  role: string
  run_id?: string
  prompt?: string
  style_preset?: string
  image_ratio?: string
  image_resolution?: string
  prefer_image_edit?: boolean
  prefer_view_chain_edit_base?: boolean
}

interface DreamweaverLibraryAutoRegenerateRolesRequest {
  run_id?: string
  character_ids?: number[]
}

interface DreamweaverLibraryAutoRegenerateRolesResponse {
  project_id: number
  scoped: boolean
  scope_mode: 'project' | 'run'
  run_id?: string | null
  character_ids: number[]
  regenerate_roles: string[]
  total: number
  character_view_missing_summary: Array<{
    entity_id: number
    entity_name?: string
    required_views: string[]
    missing_views: string[]
    missing_roles: string[]
  }>
  review_missing_roles_count: number
  synced?: { created?: number }
}

interface DreamweaverLibraryAssetProviderRefUpdateRequest {
  provider?: 'kling'
  subject_id?: string | null
  source_asset_uri?: string | null
}

interface DreamweaverLibraryAssetProviderRefUpdateResponse {
  project_id: number
  asset_id: number
  role: string
  provider: string
  subject_id?: string | null
  provider_refs: Record<string, unknown>
}

interface DreamweaverLibraryAssetProviderRefSyncRequest {
  provider?: 'kling'
  include_related_views?: boolean
  timeout_s?: number
  poll_interval_s?: number
}

interface DreamweaverLibraryAssetProviderRefSyncResponse {
  project_id: number
  asset_id: number
  role: string
  provider: string
  subject_id?: string | null
  provider_refs: Record<string, unknown>
}

export type AudiobookGenerationMode = 'full' | 'script_only'
export type AudiobookPreviewType = 'voice' | 'sfx' | 'bgm' | 'mix'
export type AudiobookAudioFxDensity = 'low' | 'medium' | 'high' | 'off'
export interface AudiobookAudioFxConfigPayload {
  enable_sound_effects: boolean
  enable_music: boolean
  sound_effect_density: AudiobookAudioFxDensity
  music_density: AudiobookAudioFxDensity
}

export interface AudiobookProjectAudioCharacterConfigPayload {
  character_id: number
  name: string
  voice_id: string
  volume: number
  speed?: number | null
  pitch?: number | null
  tts_model?: AudiobookTtsModel | null
  voice_type?: string | null
  personality?: string | null
  emotion_tendency?: string | null
  source?: string | null
}

export interface AudiobookProjectAudioConfigPayload {
  characters: AudiobookProjectAudioCharacterConfigPayload[]
  audio_fx?: AudiobookAudioFxConfigPayload | null
}

export interface AudiobookVoiceConfigPayloadItem {
  character_name: string
  voice_id: string
  volume: number
  speed?: number
  pitch?: number
  tts_model?: AudiobookTtsModel | null
  voice_type?: string | null
  personality?: string | null
  emotion_tendency?: string | null
}

export interface CreateAudiobookProjectPayload {
  project_id: number
  chapter_ids: number[]
  tts_provider?: string
  enable_cache?: boolean
  voice_config?: AudiobookVoiceConfigPayloadItem[]
  tts_model?: string
  output_format?: string
  generate_subtitle?: boolean
  generation_mode?: AudiobookGenerationMode
  narration_style?: string
  narration_style_prompt?: string
  force_regenerate_script?: boolean
}

export interface AudiobookScriptSegmentVoiceParamsPayload {
  speaker?: string | null
  speed?: number | null
  rate?: number | null
  pitch?: number | null
  volume?: number | null
  emotion?: string | null
}

export interface AudiobookScriptSegmentSoundEffectPayload {
  id?: string | null
  effect_id?: string | null
  name?: string | null
}

export interface AudiobookScriptSegmentMusicCuePayload {
  style?: string | null
  name?: string | null
}

export interface AudiobookScriptSegmentPayload {
  index?: number | null
  type?: string | null
  speaker?: string | null
  speaker_name?: string | null
  character_name?: string | null
  role_name?: string | null
  emotion?: string | null
  text?: string | null
  performance_notes?: string | null
  original_text?: string | null
  adaptation_reason?: string | null
  pause_before?: number | null
  pause_after?: number | null
  instruct_emotion?: string | null
  instruct_scene?: string | null
  instruct_role?: string | null
  instruct_identity?: string | null
  voice_params?: AudiobookScriptSegmentVoiceParamsPayload | null
  sound_effects_simple?: string[] | null
  sound_effects?: Array<AudiobookScriptSegmentSoundEffectPayload | string> | null
  music_cue_simple?: string | null
  music_cue?: AudiobookScriptSegmentMusicCuePayload | string | null
}

export interface UpdateAudiobookChapterScriptPayload {
  script_segments: AudiobookScriptSegmentPayload[]
  script_status?: 'pending' | 'reviewed' | 'approved'
}

export interface GenerateAudioFromScriptsPayload {
  chapter_ids?: number[]
  tts_model?: string
  narration_style?: string
  narration_style_prompt?: string
  output_format?: string
  generate_subtitle?: boolean
}

export interface PreviewScriptSegmentAudioPayload {
  segment: AudiobookScriptSegmentPayload
  tts_model?: string
  preview_type?: AudiobookPreviewType
}

export interface AudiobookSmartChunkStats {
  total_chunks: number
  total_tokens: number
  avg_tokens_per_chunk: number
  max_tokens_in_chunk: number
  min_tokens_in_chunk: number
}

export interface AudiobookSmartChunkPreviewResponse {
  original_segments: number
  chunked_segments: number
  total_tokens: number
  chunks: AudiobookScriptSegmentPayload[]
  stats: AudiobookSmartChunkStats
}

export interface AudiobookTextTokenEstimateResponse {
  text_length: number
  estimated_tokens: number
  needs_chunking: boolean
  max_tokens: number
}

export interface PreviewTtsPayload {
  text: string
  voice_id: string
  volume?: number
  speed?: number
  pitch?: number
  model?: string
  voice_type?: string | null
}

export interface AudiobookTtsModelCatalogItem {
  id: string
  name?: string
  description?: string
  voice_count?: number
  price_per_10k?: number
  features?: string[]
  cost_level?: string
  quality_level?: string
  catalog_note?: string
  capabilities?: Record<string, unknown>
}

export interface AudiobookTtsModelCatalogResponse {
  models: AudiobookTtsModelCatalogItem[]
}

export interface AudiobookChapterStreamUrlResponse {
  stream_url: string
  expires_at: string
  expires_in_seconds: number
}

export interface AudiobookQueuedTaskResponse {
  success?: boolean
  audiobook_project_id: number
  job_id?: string
  task_id?: string
  task_db_id?: number
  task_type?: string
  status?: string
  message?: string
  download_url?: string
  total_chapters?: number
  chapter_ids?: number[]
}

interface DreamweaverLibraryPromptSuggestRequest {
  role: string
  run_id?: string
  prompt?: string
  style_preset?: string
  image_ratio?: string
  image_resolution?: string
  mode?: 'template' | 'ai'
  prefer_view_chain_seed?: boolean
}

interface DreamweaverLibraryPromptSuggestResponse {
  role: string
  style_preset: string
  image_ratio: string
  prompt: string
  negative_prompt: string
  meta?: Record<string, any>
}

interface DreamweaverProjectGeneratedDeleteResponse {
  project_id: number
  deleted_runs: string[]
  skipped_runs: string[]
  deleted_library_assets: number
  deleted_library_dir: boolean
  deleted_library_anchor_projects: number
  library_skipped: boolean
  library_skip_reason?: string | null
  failed_paths: string[]
  failed_runs: Array<{ run_id: string; error: string }>
}

interface FrontendEventPayload {
  event: string
  module?: string
  action?: string
  labels?: Record<string, string>
  value?: number
  duration_ms?: number
  success?: boolean
}

export type AssetStorageMode = 'temp_cloud' | 'durable_cloud' | 'local_mirror' | 'local_only'

export interface AssetStudioMediaAsset {
  asset_uuid: string
  media_kind: 'image' | 'video' | 'audio' | string
  storage_mode: AssetStorageMode
  source_uri: string
  preview_uri: string
  download_uri: string
  file_name: string
  mime_type?: string | null
  file_size?: number | null
  expires_at?: string | null
}

export interface AssetStudioGenerateResponse {
  kind: string
  mode: string
  model_id: string
  assets: AssetStudioMediaAsset[]
  primary_asset?: AssetStudioMediaAsset | null
  metadata?: Record<string, any>
}

export interface AssetStudioVisionCriterionScore {
  name: string
  label: string
  score?: number | null
  comment?: string | null
}

export interface AssetStudioVisionReviewResponse {
  kind: string
  mode: string
  model_id: string
  asset_type: string
  overall_score?: number | null
  summary: string
  strengths: string[]
  issues: string[]
  prompt_suggestions: string[]
  revised_prompt: string
  criteria_scores: AssetStudioVisionCriterionScore[]
  metadata?: Record<string, any>
}

export interface AssetStudioModelCatalogOption {
  model_id: string
  catalog_model_key: string
  label: string
  helper: string
  provider: string
  category: string
  status: string
  modalities: string[]
  tags: string[]
  duration_options: number[]
}

export interface AssetStudioModelCatalogResponse {
  catalog_version: string
  defaults: Record<string, string>
  groups: Record<string, AssetStudioModelCatalogOption[]>
}

export interface UserAssetRecord {
  id: number
  user_id: number
  project_id?: number | null
  source_module: string
  asset_kind: string
  asset_class: string
  asset_uuid: string
  storage_mode: AssetStorageMode
  title: string
  description?: string | null
  source_uri?: string | null
  preview_uri?: string | null
  download_uri?: string | null
  mime_type?: string | null
  file_size?: number | null
  checksum?: string | null
  expires_at?: string | null
  model_id?: string | null
  generation_mode?: string | null
  tags: string[]
  metadata_json?: UserAssetMetadata
  source_payload_json?: Record<string, any>
  is_favorite: boolean
  archived_at?: string | null
  created_at: string
  updated_at: string
}

export interface UserAssetListSummary {
  total_assets: number
  active_asset_count: number
  archived_asset_count: number
  favorite_asset_count: number
  reusable_asset_count: number
  deliverable_asset_count: number
}

export interface UserAssetListFilterOptions {
  asset_kinds: string[]
  source_modules: string[]
  tags: string[]
}

export interface UserAssetListResponse {
  total: number
  page: number
  page_size: number
  total_pages: number
  items: UserAssetRecord[]
  summary: UserAssetListSummary
  filter_options: UserAssetListFilterOptions
}

export interface UserAssetRecordCreatePayload {
  project_id?: number | null
  source_module: string
  asset_kind: string
  asset_class?: string
  asset_uuid: string
  storage_mode: AssetStorageMode
  title: string
  description?: string | null
  source_uri?: string | null
  preview_uri?: string | null
  download_uri?: string | null
  mime_type?: string | null
  file_size?: number | null
  checksum?: string | null
  expires_at?: string | null
  model_id?: string | null
  generation_mode?: string | null
  tags?: string[]
  metadata_json?: UserAssetMetadata
  source_payload_json?: Record<string, any>
  is_favorite?: boolean
}

export interface UserAssetRecordUpdatePayload {
  title?: string
  description?: string | null
  asset_class?: string
  tags?: string[]
  is_favorite?: boolean
  archived?: boolean
}

export interface UserAssetRecordBatchUpdatePayload {
  asset_ids: number[]
  updates: UserAssetRecordUpdatePayload
}

export interface UserAssetRecordBatchUpdateResponse {
  updated_count: number
  asset_ids: number[]
  assets: UserAssetRecord[]
}

export interface UserCenterPointsAccount {
  balance?: number | null
  frozen?: number | null
  expiring_soon?: number | null
  status: 'planned' | 'partial'
  connected_source_count: number
  pending_source_count: number
}

export interface UserCenterConnectedOverview {
  project_count: number
  user_asset_count: number
  audiobook_project_count: number
  audiobook_total_cost: number
  dreamweaver_run_count: number
}

export interface UserCenterBenefitItem {
  key: string
  label: string
  summary: string
  status: 'connected' | 'planned'
}

export interface UserCenterLedgerEntry {
  key: string
  module_label: string
  event_label: string
  title: string
  summary: string
  amount: number
  occurred_at?: string | null
  project_label?: string | null
  action_path?: string | null
  action_label?: string | null
}

export interface UserCenterPendingLedgerSignal {
  key: string
  module_label: string
  signal_label: string
  summary: string
  action_path?: string | null
  action_label?: string | null
}

export interface UserCenterPointsRuleOverview {
  reusable_asset_reward: number
  deliverable_asset_reward: number
  audiobook_completion_reward: number
  dreamweaver_completion_reward: number
  running_audiobook_frozen: number
  running_dreamweaver_frozen: number
  reward_ttl_days: number
  expiring_notice_days: number
  source: 'default' | 'admin_log'
  updated_at?: string | null
  updated_by_user_id?: number | null
  updated_by_username?: string | null
}

export interface UserCenterPointsPricingPolicyOverview {
  points_per_yuan: number
  user_price_basis: 'public_list_price' | 'standard_price_table'
  user_price_rate: number
  freeze_buffer_rate: number
  source: 'default' | 'admin_log'
  updated_at?: string | null
  updated_by_user_id?: number | null
  updated_by_username?: string | null
}

export interface UserCenterPointsEntry {
  key: string
  source_key: string
  source_label: string
  title: string
  summary: string
  amount: number
  direction: 'income' | 'expense' | 'hold'
  status: 'active' | 'expired' | 'frozen'
  occurred_at?: string | null
  expires_at?: string | null
  action_path?: string | null
  action_label?: string | null
}

export interface UserCenterTaskBillingItem {
  key: string
  module_key: string
  module_label: string
  title: string
  summary: string
  task_status: 'running' | 'completed'
  pricing_status: 'actual' | 'estimated' | 'pending'
  actual_yuan?: number | null
  actual_points?: number | null
  estimated_yuan?: number | null
  estimated_points?: number | null
  suggested_frozen_points?: number | null
  occurred_at?: string | null
  action_path?: string | null
  action_label?: string | null
}

export interface UserCenterTaskBillingOverview {
  actual_spend_yuan: number
  actual_spend_points: number
  estimated_running_spend_yuan: number
  estimated_running_spend_points: number
  suggested_frozen_points: number
  actual_task_count: number
  estimated_task_count: number
  pending_task_count: number
  items: UserCenterTaskBillingItem[]
}

export interface UserCenterPointsOverviewResponse {
  points_account: UserCenterPointsAccount
  points_rules: UserCenterPointsRuleOverview
  pricing_policy: UserCenterPointsPricingPolicyOverview
  points_entries: UserCenterPointsEntry[]
  connected_overview: UserCenterConnectedOverview
  benefits: {
    connected_items: UserCenterBenefitItem[]
    planned_items: UserCenterBenefitItem[]
  }
  ledger: {
    connected_entries: UserCenterLedgerEntry[]
    pending_signals: UserCenterPendingLedgerSignal[]
  }
  task_billing: UserCenterTaskBillingOverview
}

export interface AdminSystemHealth {
  database: string
  timestamp: string
}

export interface AdminPointsRuleConfig {
  reusable_asset_reward: number
  deliverable_asset_reward: number
  audiobook_completion_reward: number
  dreamweaver_completion_reward: number
  running_audiobook_frozen: number
  running_dreamweaver_frozen: number
  reward_ttl_days: number
  expiring_notice_days: number
  source: 'default' | 'admin_log'
  updated_at?: string | null
  updated_by_user_id?: number | null
  updated_by_username?: string | null
}

export interface AdminPointsRuleUpdatePayload {
  reusable_asset_reward: number
  deliverable_asset_reward: number
  audiobook_completion_reward: number
  dreamweaver_completion_reward: number
  running_audiobook_frozen: number
  running_dreamweaver_frozen: number
  reward_ttl_days: number
  expiring_notice_days: number
}

export interface AdminPointsPricingPolicy {
  points_per_yuan: number
  user_price_basis: 'public_list_price' | 'standard_price_table'
  user_price_rate: number
  provider_discount_capture_rate: number
  freeze_buffer_rate: number
  margin_warning_rate: number
  negative_margin_block_enabled: boolean
  source: 'default' | 'admin_log'
  updated_at?: string | null
  updated_by_user_id?: number | null
  updated_by_username?: string | null
  operating_snapshots?: AdminPointsPricingOperatingSnapshot[]
}

export interface AdminPointsPricingPolicyUpdatePayload {
  points_per_yuan: number
  user_price_basis: 'public_list_price' | 'standard_price_table'
  user_price_rate: number
  provider_discount_capture_rate: number
  freeze_buffer_rate: number
  margin_warning_rate: number
  negative_margin_block_enabled: boolean
}

export interface AdminPointsPricingOperatingSnapshot {
  module_key: string
  module_label: string
  provider_key?: string | null
  user_basis_yuan: number
  user_billed_yuan: number
  supplier_list_price_yuan: number
  supplier_discount_rate: number
  supplier_discount_rate_source: string
  supplier_discounted_cost_yuan: number
  supplier_discount_yuan: number
  captured_discount_yuan: number
  shared_discount_yuan: number
  policy_target_user_billed_yuan: number
  policy_alignment_gap_yuan: number
  platform_gross_profit_yuan: number
  platform_margin_rate?: number | null
  margin_status: 'healthy' | 'warning' | 'negative'
  negative_margin_blocked: boolean
}

export interface AdminPointsBillingEvent {
  id: number
  target_user_id: number
  operator_user_id: number
  operator_username: string
  operation_type: string
  module_key: string
  module_label: string
  event_kind: 'freeze' | 'settle' | 'release'
  event_label: string
  billing_key: string
  title: string
  summary: string
  amount_points: number
  amount_yuan?: number | null
  pricing_status?: string | null
  task_status?: string | null
  project_id?: number | null
  audiobook_project_id?: number | null
  run_id?: string | null
  stage?: string | null
  action_path?: string | null
  action_label?: string | null
  created_at: string
  operating_snapshot?: AdminPointsPricingOperatingSnapshot | null
}

export interface AdminPointsBillingModuleSummary {
  module_key: string
  module_label: string
  settle_event_count: number
  warning_event_count: number
  negative_event_count: number
  total_user_billed_yuan: number
  total_platform_gross_profit_yuan: number
  blended_margin_rate?: number | null
}

export interface AdminPointsBillingSummary {
  recent_7d_settle_count: number
  settle_event_count: number
  warning_event_count: number
  negative_event_count: number
  total_user_billed_yuan: number
  total_platform_gross_profit_yuan: number
  blended_margin_rate?: number | null
  module_summaries: AdminPointsBillingModuleSummary[]
}

export interface AdminPointsBillingEventListResponse {
  total: number
  page: number
  page_size: number
  total_pages: number
  summary: AdminPointsBillingSummary
  items: AdminPointsBillingEvent[]
}

interface DreamweaverScriptUpdateRequest {
  script_text: string
}

interface DreamweaverScriptApproveRequest {
  approved: boolean
}

interface DreamweaverPromptReviewApproveRequest {
  approved: boolean
}

interface DreamweaverShotVideoPromptUpdateRequest {
  prompt?: string | null
}

interface DreamweaverRestartRequest {
  start_state: string
  reset_policy?: 'downstream' | 'none'
  qc_allow_fail?: boolean
  smart_tuning?: boolean
  shot_ids?: string[]
  cam_idxs?: number[]
  asset_roles?: string[]
  auto_asset_roles_from_missing_views?: boolean
  auto_asset_character_ids?: number[]
}

interface DreamweaverVideoJobConfirmAsyncResponse {
  run_id: string
  status: 'queued' | 'blocked' | 'noop'
  task_id?: string | null
  message?: string | null
  video_clip_jobs?: Record<string, unknown>[] | null
}

interface DreamweaverVideoJobsRebuildResponse {
  run_id: string
  video_clip_jobs: Record<string, unknown>[]
}

interface DreamweaverRunDeleteResponse {
  run_id: string
  deleted_generation_history: number
  deleted_assets: number
  deleted_shots: number
  deleted_episodes: number
  deleted_project: boolean
  deleted_run_dir: boolean
  failed_paths: string[]
}

interface OAuthAuthUrlRequest {
  redirect_uri: string
  state?: string
}

interface PasswordResetCodeRequest {
  account: string
}

interface PasswordResetRequest {
  account: string
  code: string
  new_password: string
}

export interface TaskPointsPrecheckOperatingSnapshot {
  margin_status?: string | null
  negative_margin_blocked?: boolean
  platform_gross_profit_yuan?: number | null
}

export interface TaskPointsPrecheckErrorDetail {
  message: string
  module_key?: string | null
  module_label?: string | null
  allowed?: boolean
  failure_code?: string | null
  estimated_yuan?: number | null
  estimated_points?: number | null
  required_frozen_points?: number | null
  existing_frozen_points?: number | null
  additional_frozen_points?: number | null
  balance_points?: number | null
  frozen_points?: number | null
  available_points?: number | null
  effective_available_points?: number | null
  reclaimed_running_frozen_points?: number | null
  estimated_shot_count?: number | null
  operating_snapshot?: TaskPointsPrecheckOperatingSnapshot | null
}

const AUTH_PUBLIC_ENDPOINTS = new Set([
  '/api/v1/auth/login',
  '/api/v1/auth/register',
  '/api/v1/auth/reset-password/request-code',
  '/api/v1/auth/reset-password',
  '/api/v1/auth/alipay/callback',
  '/api/v1/auth/wechat/callback',
])

function normalizeRequestPath(url?: string): string {
  if (!url) return ''

  try {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      return new URL(url).pathname
    }
  } catch {
    return url
  }

  return url
}

function shouldRedirectToLogin(error: AxiosError): boolean {
  if (error.response?.status !== 401) {
    return false
  }

  const requestPath = normalizeRequestPath(error.config?.url)
  if (AUTH_PUBLIC_ENDPOINTS.has(requestPath)) {
    return false
  }

  const currentPath = typeof window !== 'undefined' ? window.location.pathname : ''
  return currentPath !== '/login' && currentPath !== '/register'
}

function getStoredAccessToken(): string | null {
  if (typeof localStorage === 'undefined') {
    return null
  }
  return localStorage.getItem('access_token')
}

function buildApiUrl(baseURL: string | undefined, path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const normalizedBase = String(baseURL || '').replace(/\/$/, '')
  return normalizedBase ? `${normalizedBase}${normalizedPath}` : normalizedPath
}

function extractDetailMessage(detail: any): string | null {
  if (!detail) return null
  if (typeof detail === 'string') return detail.trim() || null
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as any
    if (first && typeof first === 'object') {
      const msg = typeof first.msg === 'string' ? first.msg : typeof first.message === 'string' ? first.message : null
      return msg?.trim() || null
    }
    return null
  }
  if (typeof detail === 'object') {
    if (typeof (detail as any).message === 'string') {
      const message = String((detail as any).message || '').trim()
      const modelErrorRaw = (detail as any).model_error
      if (typeof modelErrorRaw === 'string') {
        const modelError = modelErrorRaw.trim()
        if (modelError) {
          // 限制长度，避免将超长供应商报文直接塞满 UI
          const clipped = modelError.length > 240 ? `${modelError.slice(0, 240)}...` : modelError
          return `${message}（详情：${clipped}）`
        }
      }
      return message || null
    }
    if (typeof (detail as any).error === 'string') return String((detail as any).error || '').trim() || null
  }
  return null
}

function extractErrorMessageFromResponseData(data: any): string | null {
  if (!data) return null
  if (typeof data === 'string') return data.trim() || null
  if (typeof data === 'object') {
    const detailMsg = extractDetailMessage((data as any).detail)
    if (detailMsg) return detailMsg
    if (typeof (data as any).message === 'string') return String((data as any).message || '').trim() || null
    if (typeof (data as any).error === 'string') return String((data as any).error || '').trim() || null
  }
  return null
}

function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function formatAmount(value: number | null | undefined): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return value.toFixed(2)
}

function extractApiErrorMessageFromUnknown(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const responseData = (error as AxiosError).response?.data as any
    return extractErrorMessageFromResponseData(responseData) || (error as AxiosError).message || fallback
  }

  if (typeof error === 'string') return error.trim() || fallback
  if (error && typeof error === 'object' && typeof (error as any).message === 'string') {
    return String((error as any).message || '').trim() || fallback
  }

  return fallback
}

function extractTaskPointsPrecheckErrorDetailFromResponseData(data: any): TaskPointsPrecheckErrorDetail | null {
  if (!data || typeof data !== 'object') return null
  const detail = (data as any).detail
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null

  const failureCode =
    typeof (detail as any).failure_code === 'string' ? String((detail as any).failure_code || '').trim() : ''
  const moduleKey =
    typeof (detail as any).module_key === 'string' ? String((detail as any).module_key || '').trim() : ''
  const message = extractDetailMessage(detail)

  if (!failureCode || !moduleKey || !message) return null

  const operatingSnapshotRaw = (detail as any).operating_snapshot
  const operatingSnapshot =
    operatingSnapshotRaw && typeof operatingSnapshotRaw === 'object' && !Array.isArray(operatingSnapshotRaw)
      ? {
          margin_status:
            typeof operatingSnapshotRaw.margin_status === 'string'
              ? String(operatingSnapshotRaw.margin_status || '').trim() || null
              : null,
          negative_margin_blocked:
            typeof operatingSnapshotRaw.negative_margin_blocked === 'boolean'
              ? operatingSnapshotRaw.negative_margin_blocked
              : undefined,
          platform_gross_profit_yuan: toFiniteNumber(operatingSnapshotRaw.platform_gross_profit_yuan),
        }
      : null

  return {
    message,
    module_key: moduleKey,
    module_label:
      typeof (detail as any).module_label === 'string' ? String((detail as any).module_label || '').trim() || null : null,
    allowed: typeof (detail as any).allowed === 'boolean' ? (detail as any).allowed : undefined,
    failure_code: failureCode,
    estimated_yuan: toFiniteNumber((detail as any).estimated_yuan),
    estimated_points: toFiniteNumber((detail as any).estimated_points),
    required_frozen_points: toFiniteNumber((detail as any).required_frozen_points),
    existing_frozen_points: toFiniteNumber((detail as any).existing_frozen_points),
    additional_frozen_points: toFiniteNumber((detail as any).additional_frozen_points),
    balance_points: toFiniteNumber((detail as any).balance_points),
    frozen_points: toFiniteNumber((detail as any).frozen_points),
    available_points: toFiniteNumber((detail as any).available_points),
    effective_available_points: toFiniteNumber((detail as any).effective_available_points),
    reclaimed_running_frozen_points: toFiniteNumber((detail as any).reclaimed_running_frozen_points),
    estimated_shot_count: toFiniteNumber((detail as any).estimated_shot_count),
    operating_snapshot: operatingSnapshot,
  }
}

function buildTaskPointsPrecheckErrorMessage(detail: TaskPointsPrecheckErrorDetail | null): string | null {
  if (!detail) return null

  const baseMessage = detail.message
  const moduleKey = String(detail.module_key || '').trim().toLowerCase()

  if (detail.failure_code === 'insufficient_available_points') {
    const available =
      typeof detail.effective_available_points === 'number' ? detail.effective_available_points : detail.available_points
    const target =
      typeof detail.additional_frozen_points === 'number' && detail.additional_frozen_points > 0
        ? detail.additional_frozen_points
        : detail.required_frozen_points

    const gap =
      typeof available === 'number' && typeof target === 'number'
        ? Math.max(target - available, 0)
        : null
    const gapText = formatAmount(gap)

    if (moduleKey === 'dreamweaver') {
      const shotCount =
        typeof detail.estimated_shot_count === 'number' && Number.isFinite(detail.estimated_shot_count)
          ? Math.max(Math.round(detail.estimated_shot_count), 0)
          : null
      const shotHint = shotCount && shotCount > 0 ? `当前按约 ${shotCount} 个镜头估算，` : ''
      const gapHint = gapText ? `还差 ${gapText} 积分，` : ''
      return `${baseMessage} ${shotHint}${gapHint}可减少章节范围、切换成本模式，或先补充积分后再试。`.trim()
    }

    if (moduleKey === 'audiobook') {
      const existingFrozen = formatAmount(detail.existing_frozen_points)
      const frozenHint = existingFrozen && Number(existingFrozen) > 0 ? ` 当前已有 ${existingFrozen} 积分处于正式冻结状态。` : ''
      const gapHint = gapText ? `还差 ${gapText} 积分，` : ''
      return `${baseMessage} ${gapHint}可减少本次生成章节，或先补充积分后再试。${frozenHint}`.trim()
    }

    return baseMessage
  }

  if (detail.failure_code === 'negative_margin_blocked') {
    if (moduleKey === 'dreamweaver') {
      return `${baseMessage} 可尝试减少章节范围或切换成本模式；若仍失败，需要管理员调整积分定价策略。`
    }
    if (moduleKey === 'audiobook') {
      return `${baseMessage} 可尝试减少生成章节、先仅生成剧本，或联系管理员调整积分定价策略。`
    }
    return `${baseMessage} 当前被积分定价策略拦截，如需继续请联系管理员检查定价配置。`
  }

  return baseMessage
}

export function describeTaskPointsPrecheckErrorDetail(detail: TaskPointsPrecheckErrorDetail | null): string | null {
  return buildTaskPointsPrecheckErrorMessage(detail)
}

async function extractApiErrorResponseData(error: unknown): Promise<any | null> {
  if (!axios.isAxiosError(error)) return null
  const responseData = (error as AxiosError).response?.data as any
  if (responseData instanceof Blob) {
    try {
      const text = await responseData.text()
      if (text && text.trim()) {
        try {
          return JSON.parse(text)
        } catch {
          return text.trim()
        }
      }
    } catch {
      return null
    }
    return null
  }
  return responseData
}

export async function extractTaskPointsPrecheckErrorDetail(error: unknown): Promise<TaskPointsPrecheckErrorDetail | null> {
  try {
    const responseData = await extractApiErrorResponseData(error)
    return extractTaskPointsPrecheckErrorDetailFromResponseData(responseData)
  } catch {
    return null
  }
}

export async function extractTaskPointsPrecheckErrorMessage(
  error: unknown,
  fallback: string = '请求失败',
): Promise<string | null> {
  const detail = await extractTaskPointsPrecheckErrorDetail(error)
  if (detail) {
    return describeTaskPointsPrecheckErrorDetail(detail)
  }
  return extractApiErrorMessage(error, fallback)
}

export async function extractApiErrorMessage(error: unknown, fallback: string = '请求失败'): Promise<string> {
  try {
    if (axios.isAxiosError(error)) {
      const responseData = await extractApiErrorResponseData(error)
      if (responseData instanceof Blob) {
        try {
          const text = await responseData.text()
          if (text && text.trim()) {
            try {
              const parsed = JSON.parse(text)
              return extractErrorMessageFromResponseData(parsed) || text.trim() || fallback
            } catch {
              return text.trim() || fallback
            }
          }
        } catch {
          // ignore
        }
        return fallback
      }
      return extractErrorMessageFromResponseData(responseData) || (error as AxiosError).message || fallback
    }

    return extractApiErrorMessageFromUnknown(error, fallback)
  } catch {
    return extractApiErrorMessageFromUnknown(error, fallback)
  }
}

class ApiClient {
  public client: AxiosInstance

  constructor() {
    // 使用环境变量或默认值
    // 如果 API_URL 是 /api，则设置为空字符串，因为 API 路径已经包含了 /api
    let baseURL = API_URL
    if (baseURL === '/api') {
      baseURL = ''
    }

    this.client = axios.create({
      baseURL: baseURL,
      timeout: 120000, // ✅ 增加到120秒，防止大数据传输超时
      headers: {
        'Content-Type': 'application/json',
      },
      // ✅ 禁用自动重试，避免重复请求
      maxRedirects: 0,
    })

    // 请求拦截器
    this.client.interceptors.request.use((config) => {
      const token = getStoredAccessToken()
      if (token) {
        // 确保headers对象存在
        if (!config.headers) {
          config.headers = {} as any
        }
        // 设置Authorization头
        config.headers['Authorization'] = `Bearer ${token}`
      }
      return config
    })

    // 响应拦截器
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (shouldRedirectToLogin(error)) {
          localStorage.removeItem('access_token')
          localStorage.removeItem('user')
          window.location.href = '/login'
        }
        return Promise.reject(error)
      }
    )
  }

  // 认证API
  register(data: { username: string; email: string; password: string; phone?: string; full_name?: string }) {
    return this.client.post('/api/v1/auth/register', data)
  }

  login(data: { username: string; password: string }) {
    return this.client.post('/api/v1/auth/login', data)
  }

  logout() {
    return this.client.post('/api/v1/auth/logout')
  }

  getCurrentUser() {
    return this.client.get('/api/v1/auth/me')
  }

  changePassword(data: { old_password: string; new_password: string }) {
    return this.client.post('/api/v1/auth/change-password', data)
  }

  requestPasswordResetCode(data: PasswordResetCodeRequest) {
    return this.client.post('/api/v1/auth/reset-password/request-code', data)
  }

  resetPassword(data: PasswordResetRequest) {
    return this.client.post('/api/v1/auth/reset-password', data)
  }

  getAlipayAuthUrl(data: OAuthAuthUrlRequest) {
    return this.client.post('/api/v1/auth/alipay/auth-url', data)
  }

  alipayCallback(code: string) {
    return this.client.post('/api/v1/auth/alipay/callback', { code })
  }

  getWechatAuthUrl(data: OAuthAuthUrlRequest) {
    return this.client.post('/api/v1/auth/wechat/auth-url', data)
  }

  wechatCallback(code: string) {
    return this.client.post('/api/v1/auth/wechat/callback', { code })
  }

  // 项目API
  getProjects() {
    return this.client.get<Project[]>('/api/v1/projects')
  }

  createProject(data: ProjectCreatePayload) {
    return this.client.post<Project>('/api/v1/projects', data)
  }

  getProject(projectId: number) {
    return this.client.get<Project>(`/api/v1/projects/${projectId}`)
  }

  getModelCatalogOverview(params?: {
    category?: string
    provider?: string
    verification_status?: string
  }) {
    return this.client.get('/api/v1/model-catalog/overview', { params })
  }

  getModelCatalogEntries(params?: {
    category?: string
    provider?: string
    verification_status?: string
    keyword?: string
  }) {
    return this.client.get('/api/v1/model-catalog/entries', { params })
  }

  getModelCatalogEntry(modelKey: string) {
    return this.client.get(`/api/v1/model-catalog/entries/${encodeURIComponent(modelKey)}`)
  }

  updateProject(projectId: number, data: ProjectUpdatePayload) {
    return this.client.put<Project>(`/api/v1/projects/${projectId}`, data)
  }

  deleteProject(projectId: number) {
    return this.client.delete(`/api/v1/projects/${projectId}`)
  }

  getProjectAudioConfig(projectId: number, ttsModel?: AudiobookTtsModel) {
    return this.client.get<AudiobookProjectAudioConfigPayload>(`/api/v1/projects/${projectId}/audio-config`, {
      params: ttsModel ? { tts_model: ttsModel } : undefined,
    })
  }

  updateProjectAudioConfig(
    projectId: number,
    data: AudiobookProjectAudioConfigPayload,
    ttsModel?: AudiobookTtsModel,
  ) {
    return this.client.put(`/api/v1/projects/${projectId}/audio-config`, data, {
      params: ttsModel ? { tts_model: ttsModel } : undefined,
    })
  }

  autoAssignProjectAudioVoices(projectId: number, ttsModel?: AudiobookTtsModel) {
    return this.client.post<AudiobookProjectAudioConfigPayload>(
      `/api/v1/projects/${projectId}/audio-config/auto-voices`,
      null,
      {
        params: ttsModel ? { tts_model: ttsModel } : undefined,
      },
    )
  }

  // 章节API
  getChapters(projectId: number, sortOrder: 'asc' | 'desc' = 'asc') {
    return this.client.get(`/api/v1/projects/${projectId}/chapters?sort_order=${sortOrder}`)
  }

  createChapter(projectId: number, data: any) {
    // 使用正确的端点格式：/api/v1/projects/{projectId}/chapters
    return this.client.post(`/api/v1/projects/${projectId}/chapters`, data)
  }

  getChapter(chapterId: number) {
    return this.client.get(`/api/v1/chapters/${chapterId}`)
  }

  updateChapter(chapterId: number, data: any) {
    return this.client.put(`/api/v1/chapters/${chapterId}`, data)
  }

  autoSaveChapter(chapterId: number, data: any) {
    return this.client.post(`/api/v1/chapters/${chapterId}/auto-save`, data)
  }

  deleteChapter(chapterId: number, data?: { delete_reason?: string; delete_files?: boolean }) {
    return this.client.delete(`/api/v1/chapters/${chapterId}`, { data })
  }

  restoreChapter(chapterId: number) {
    return this.client.post(`/api/v1/chapters/${chapterId}/restore`)
  }

  async getDeletedChapters(projectId: number) {
    const response = await this.client.get(`/api/v1/chapters/deleted`, { params: { project_id: projectId } })
    const normalizedData = Array.isArray(response.data)
      ? response.data
      : Array.isArray(response.data?.deleted_chapters)
        ? response.data.deleted_chapters
        : []

    return {
      ...response,
      data: normalizedData,
    }
  }

  // 设定管理API
  getSettingCollections(projectId: number) {
    return this.client.get<SettingCollection[]>(`/api/v1/projects/${projectId}/setting-collections`)
  }

  createSettingCollection(projectId: number, data: SettingCollectionCreatePayload) {
    return this.client.post<SettingCollection>(`/api/v1/projects/${projectId}/setting-collections`, data)
  }

  updateSettingCollection(collectionId: number, data: SettingCollectionUpdatePayload) {
    return this.client.put<SettingCollection>(`/api/v1/setting-collections/${collectionId}`, data)
  }

  deleteSettingCollection(collectionId: number) {
    return this.client.delete(`/api/v1/setting-collections/${collectionId}`)
  }

  getSettingItems(collectionId: number) {
    return this.client.get<SettingItem[]>(`/api/v1/setting-collections/${collectionId}/items`)
  }

  getSettingItem(itemId: number) {
    return this.client.get<SettingItem>(`/api/v1/setting-items/${itemId}`)
  }

  createSettingItem(collectionId: number, data: SettingItemCreatePayload) {
    return this.client.post<SettingItem>(`/api/v1/setting-collections/${collectionId}/items`, data)
  }

  updateSettingItem(itemId: number, data: SettingItemUpdatePayload) {
    return this.client.put<SettingItem>(`/api/v1/setting-items/${itemId}`, data)
  }

  moveSettingItem(itemId: number, targetCollectionId: number) {
    return this.client.post(`/api/v1/setting-items/${itemId}/move`, { target_collection_id: targetCollectionId })
  }

  deleteSettingItem(itemId: number) {
    return this.client.delete(`/api/v1/setting-items/${itemId}`)
  }

  reorderSettingItems(collectionId: number, items: { id: number; order: number }[]) {
    return this.client.patch(`/api/v1/setting-collections/${collectionId}/items/reorder`, {
      items,
    })
  }

  getSettingItemsByPath(collectionId: number, prefix?: string, maxDepth?: number) {
    const params: any = {}
    if (prefix) params.prefix = prefix
    if (maxDepth != null) params.max_depth = maxDepth
    return this.client.get<SettingItem[]>(`/api/v1/setting-collections/${collectionId}/items/by-path`, { params })
  }

  getSettingItemsTree(collectionId: number) {
    return this.client.get<SettingItemsTreeResponse>(`/api/v1/setting-collections/${collectionId}/items/tree`)
  }

  getGraphEdgesForItem(itemId: number, direction: 'both' | 'out' | 'in' = 'both') {
    return this.client.get(`/api/v1/setting-items/${itemId}/graph-edges`, { params: { direction } })
  }

  createGraphEdge(payload: { source_item_id: number; target_item_id: number; relation_type: string; confidence?: number; auto_extracted?: boolean }) {
    return this.client.post(`/api/v1/graph-edges`, payload)
  }

  deleteGraphEdge(edgeId: number) {
    return this.client.delete(`/api/v1/graph-edges/${edgeId}`)
  }

  bulkMoveSettingItems(collectionId: number, payload: { item_ids: number[]; target_collection_id?: number; new_parent_path?: string }) {
    return this.client.post(`/api/v1/setting-collections/${collectionId}/items/bulk-move`, payload)
  }

  setParentForItem(itemId: number, newParentPath: string) {
    return this.client.post(`/api/v1/setting-items/${itemId}/set-parent`, { new_parent_path: newParentPath })
  }

  reorderUnderParent(collectionId: number, parentPath: string, orderedIds: number[]) {
    return this.client.patch(`/api/v1/setting-collections/${collectionId}/items/reorder-under-parent`, {
      parent_path: parentPath,
      ordered_ids: orderedIds,
    })
  }

  // 设定模板与摘要
  getSettingTemplates() {
    return this.client.get<SettingTemplateMetadata[]>('/api/v1/setting-templates')
  }

  applySettingTemplate(projectId: number, payload: { template_key: string; clear_existing?: boolean }) {
    return this.client.post(`/api/v1/projects/${projectId}/setting-templates/apply`, payload)
  }

  getSettingItemSmartExtract(itemId: number) {
    return this.client.get<SettingSmartExtractResponse>(`/api/v1/setting-items/${itemId}/smart-extract`)
  }

  getSettingsSummary(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/settings-summary`)
  }

  syncSettingsToWorkflow(projectId: number) {
    return this.client.post(`/api/v1/projects/${projectId}/sync-settings-to-workflow`)
  }

  // 设定自动合并与冲突检测
  autoMergeSettings(projectId: number, chapterPlan: string = '', chapterContent: string = '') {
    return this.client.post(`/api/v1/projects/${projectId}/auto-merge-settings`, {
      chapter_plan: chapterPlan,
      chapter_content: chapterContent,
    })
  }

  llmReclassifyCandidates(projectId: number) {
    return this.client.post(`/api/v1/projects/${projectId}/llm-reclassify-candidates`)
  }

  detectConflicts(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/detect-conflicts`)
  }

  getSettingRecommendations(projectId: number, category?: string, limit: number = 10) {
    const params: any = { limit }
    if (category) params.category = category
    return this.client.get(`/api/v1/projects/${projectId}/setting-recommendations`, { params })
  }

  rollbackSettingItem(itemId: number, snapshotIndex: number) {
    return this.client.post(`/api/v1/setting-items/${itemId}/rollback`, { snapshot_index: snapshotIndex })
  }

  // 评审API
  createReview(chapterId: number, data: any) {
    return this.client.post(`/api/v1/chapters/${chapterId}/review`, data)
  }

  getReview(chapterId: number) {
    return this.client.get(`/api/v1/chapters/${chapterId}/review`)
  }

  updateReview(chapterId: number, data: any) {
    return this.client.put(`/api/v1/chapters/${chapterId}/review`, data)
  }

  deleteReview(chapterId: number) {
    return this.client.delete(`/api/v1/chapters/${chapterId}/review`)
  }

  previewTTS(payload: PreviewTtsPayload) {
    return this.client.post<Blob>('/api/v1/audiobook/tts/preview', payload, { responseType: 'blob' })
  }

  previewTTSWithTimestamps(payload: {
    text: string
    voice_id: string
    volume?: number
    speed?: number
    pitch?: number
    model?: string
    instruction?: string
    word_timestamp_enabled?: boolean
    phoneme_timestamp_enabled?: boolean
  }) {
    return this.client.post('/api/v1/audiobook/tts/preview-with-timestamps', payload)
  }

  previewScriptSegmentAudio(
    audiobookProjectId: number,
    chapterId: number,
    payload: PreviewScriptSegmentAudioPayload,
  ) {
    return this.client.post<Blob>(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/segments/preview`,
      payload,
      { responseType: 'blob' }
    )
  }

  getTtsModels() {
    return this.client.get<AudiobookTtsModelCatalogResponse>('/api/v1/audiobook/tts/models')
  }

  getTtsVoices(model?: string) {
    return this.client.get('/api/v1/audiobook/tts/voices', {
      params: model ? { model } : undefined,
    })
  }

  createCosyVoiceV3PlusClone(payload: { name: string; url: string }) {
    return this.client.post('/api/v1/audiobook/tts/voices/cosyvoice-v3.5-plus/clones', payload)
  }

  listCosyVoiceClones(prefix?: string) {
    return this.client.get<{
      meta: Record<string, unknown>
      voices: Array<{
        voice_id: string
        status: string
        gmt_create: string
        gmt_modified: string
        custom_type: string
        voice_prompt: string
        preview_text: string
        preview_audio: string
        display_name: string
      }>
    }>('/api/v1/audiobook/tts/voices/cosyvoice-v3.5-plus/clones', {
      params: prefix ? { prefix } : undefined,
    })
  }

  createCosyVoiceV3PlusDesign(payload: {
    name: string
    voice_prompt: string
    preview_text: string
    sample_rate?: number
    response_format?: string
  }) {
    return this.client.post('/api/v1/audiobook/tts/voices/cosyvoice-v3.5-plus/designs', payload)
  }

  deleteCosyVoiceV3PlusClone(voiceId: string) {
    return this.client.delete(
      `/api/v1/audiobook/tts/voices/cosyvoice-v3.5-plus/clones/${encodeURIComponent(voiceId)}`
    )
  }

  uploadCosyVoiceV3PlusCloneSample(file: File) {
    const form = new FormData()
    form.append('file', file)
    return this.client.post('/api/v1/audiobook/tts/voices/cosyvoice-v3.5-plus/clones/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  }

  // 角色管理API
  getCharacters(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/characters`)
  }

  createCharacter(projectId: number, data: any) {
    return this.client.post(`/api/v1/projects/${projectId}/characters`, data)
  }

  getCharacter(characterId: number) {
    return this.client.get(`/api/v1/characters/${characterId}`)
  }

  updateCharacter(characterId: number, data: any) {
    return this.client.put(`/api/v1/characters/${characterId}`, data)
  }

  deleteCharacter(characterId: number) {
    return this.client.delete(`/api/v1/characters/${characterId}`)
  }

  // 角色功法管理API
  getCharacterTechniques(characterId: number) {
    return this.client.get(`/api/v1/characters/${characterId}/techniques`)
  }

  updateCharacterTechniques(characterId: number, data: any) {
    return this.client.put(`/api/v1/characters/${characterId}/techniques`, data)
  }

  getProjectTechniques(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/techniques`)
  }

  getCharacterAutoTrackedRelations(characterId: number) {
    return this.client.get(`/api/v1/characters/${characterId}/auto-tracked-relations`)
  }

  getCharacterAppearanceTimeline(characterId: number) {
    return this.client.get(`/api/v1/characters/${characterId}/appearance-timeline`)
  }

  syncCharactersToWorkflow(projectId: number) {
    return this.client.post(`/api/v1/projects/${projectId}/sync-characters-to-workflow`)
  }

  getCharactersTextPreview(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/characters-text-preview`)
  }

  getCharacterRelationshipGraph(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/character-relationship-graph`)
  }

  // 有声书 API
  getAudiobookProjectsByProject(projectId: number, params?: { include_chapter_audios?: boolean }) {
    return this.client.get(`/api/v1/audiobook/projects/by-project/${projectId}`, { params })
  }

  listUserAudiobookProjects() {
    return this.client.get<UserAudiobookProjectOverview[]>('/api/v1/audiobook/projects')
  }

  getAudiobookProject(audiobookProjectId: number) {
    return this.client.get(`/api/v1/audiobook/projects/${audiobookProjectId}`)
  }

  getAudiobookChapterAudioFile(audiobookProjectId: number, chapterId: number) {
    return this.client.get<Blob>(`/api/v1/audiobook/download/${audiobookProjectId}/${chapterId}`, {
      responseType: 'blob',
      timeout: 60000,
      params: { _ts: Date.now() },
      headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
    })
  }

  getAudiobookChapterAudioStreamFile(audiobookProjectId: number, chapterId: number) {
    return this.client.get<Blob>(`/api/v1/audiobook/stream/${audiobookProjectId}/${chapterId}`, {
      responseType: 'blob',
      timeout: 60000,
      params: { _ts: Date.now() },
      headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
    })
  }

  async getAudiobookChapterAudioSignedStreamUrl(audiobookProjectId: number, chapterId: number): Promise<string> {
    const response = await this.client.get<AudiobookChapterStreamUrlResponse>(
      `/api/v1/audiobook/stream-url/${audiobookProjectId}/${chapterId}`,
      {
        params: { _ts: Date.now() },
        headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
      },
    )
    return buildApiUrl(this.client.defaults.baseURL, response.data.stream_url)
  }

  exportAudiobookProjectM4b(audiobookProjectId: number, metadata?: Record<string, unknown>) {
    return this.client.post<Record<string, unknown>>(
      `/api/v1/audiobook/projects/${audiobookProjectId}/exports/m4b`,
      metadata ?? {},
      { timeout: 1800000 },
    )
  }

  queueAudiobookProjectM4bExport(audiobookProjectId: number, metadata?: Record<string, unknown>, force = false) {
    return this.client.post<AudiobookQueuedTaskResponse>(
      `/api/v1/audiobook/projects/${audiobookProjectId}/exports/m4b/queue`,
      metadata ?? {},
      {
        params: { force },
        timeout: 60000,
      },
    )
  }

  downloadAudiobookProjectM4b(audiobookProjectId: number) {
    return this.client.get<Blob>(`/api/v1/audiobook/projects/${audiobookProjectId}/exports/m4b/download`, {
      responseType: 'blob',
      timeout: 60000,
      params: { _ts: Date.now() },
    })
  }

  exportAudiobookProjectAudacity(audiobookProjectId: number) {
    return this.client.post<Record<string, unknown>>(`/api/v1/audiobook/projects/${audiobookProjectId}/exports/audacity`, {}, {
      timeout: 1800000,
    })
  }

  queueAudiobookProjectAudacityExport(audiobookProjectId: number, force = false) {
    return this.client.post<AudiobookQueuedTaskResponse>(
      `/api/v1/audiobook/projects/${audiobookProjectId}/exports/audacity/queue`,
      {},
      {
        params: { force },
        timeout: 60000,
      },
    )
  }

  downloadAudiobookProjectAudacity(audiobookProjectId: number) {
    return this.client.get<Blob>(`/api/v1/audiobook/projects/${audiobookProjectId}/exports/audacity/download`, {
      responseType: 'blob',
      timeout: 60000,
      params: { _ts: Date.now() },
    })
  }

  deleteAudiobookProject(audiobookProjectId: number, data?: { delete_reason?: string; delete_files?: boolean }) {
    return this.client.delete(`/api/v1/audiobook/projects/${audiobookProjectId}`, { data })
  }

  deleteChapterAudio(chapterAudioId: number, data?: { delete_reason?: string; delete_files?: boolean }) {
    return this.client.delete(`/api/v1/audiobook/chapter-audios/${chapterAudioId}`, { data })
  }

  restoreAudiobookProject(audiobookProjectId: number) {
    return this.client.post(`/api/v1/audiobook/projects/${audiobookProjectId}/restore`)
  }

  restoreChapterAudio(chapterAudioId: number) {
    return this.client.post(`/api/v1/audiobook/chapter-audios/${chapterAudioId}/restore`)
  }

  listDeletedProjects() {
    return this.client.get('/api/v1/audiobook/projects/deleted')
  }

  listDeletedChapterAudios(params?: { audiobook_project_id?: number; limit?: number }) {
    return this.client.get<{
      success: boolean
      count: number
      chapter_audios: DeletedChapterAudio[]
    }>('/api/v1/audiobook/chapter-audios/deleted', { params })
  }

  createAudiobookProject(payload: CreateAudiobookProjectPayload) {
    return this.client.post<AudiobookQueuedTaskResponse>('/api/v1/audiobook/projects', payload)
  }

  getAudiobookChapterScript(audiobookProjectId: number, chapterId: number) {
    return this.client.get(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/script`
    )
  }

  updateAudiobookChapterScript(
    audiobookProjectId: number,
    chapterId: number,
    payload: UpdateAudiobookChapterScriptPayload,
  ) {
    return this.client.put(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/script`,
      payload
    )
  }

  generateAudioFromScripts(audiobookProjectId: number, payload: GenerateAudioFromScriptsPayload) {
    return this.client.post<AudiobookQueuedTaskResponse>(
      `/api/v1/audiobook/projects/${audiobookProjectId}/generate-audio-from-scripts`,
      payload
    )
  }

  // 片段重新生成 API
  regenerateSegment(
    audiobookProjectId: number,
    chapterId: number,
    segmentIndex: number,
    payload: { reason?: string; tts_model?: string; voice_id?: string; emotion?: string }
  ) {
    return this.client.post(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/segments/${segmentIndex}/regenerate`,
      payload
    )
  }

  // 片段审查/评分 API
  reviewSegment(
    audiobookProjectId: number,
    chapterId: number,
    segmentIndex: number,
    payload: { quality_score?: number; notes?: string; needs_regenerate?: boolean }
  ) {
    return this.client.post(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/segments/${segmentIndex}/review`,
      payload
    )
  }

  // 获取章节审查状态 API
  getChapterReviewStatus(audiobookProjectId: number, chapterId: number) {
    return this.client.get(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/review-status`
    )
  }

  // 获取叙事风格预设列表 API
  getNarrationStyles() {
    return this.client.get('/api/v1/audiobook/narration-styles')
  }

  // 获取叙事风格预设详情 API
  getNarrationStyle(styleId: string) {
    return this.client.get(`/api/v1/audiobook/narration-styles/${styleId}`)
  }

  // 获取生成断点信息 API
  getGenerationCheckpoint(audiobookProjectId: number, chapterId: number) {
    return this.client.get(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/checkpoint`
    )
  }

  // 从断点继续生成 API
  resumeChapterGeneration(audiobookProjectId: number, chapterId: number) {
    return this.client.post(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/resume-generation`
    )
  }

  // 获取章节字幕文件 API
  getChapterSubtitle(audiobookProjectId: number, chapterId: number, format: string = 'srt') {
    return this.client.get<Blob>(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/subtitle?format=${format}`,
      {
        responseType: 'blob',
        timeout: 30000,
      },
    )
  }

  // 获取浏览器播放器数据 API
  getBrowserPlayerData(audiobookProjectId: number) {
    return this.client.get(
      `/api/v1/audiobook/projects/${audiobookProjectId}/browser-player`
    )
  }

  listAudiobookTasks() {
    return this.client.get('/api/v1/audiobook/tasks', {
      timeout: 15000,
      validateStatus: () => true,
    })
  }

  getAudiobookTaskStatus(taskId: string) {
    return this.client.get(`/api/v1/audiobook/tasks/${taskId}/status`, {
      timeout: 15000,
      validateStatus: () => true,
    })
  }

  // 智能分块预览 API
  previewSmartChunking(
    segments: AudiobookScriptSegmentPayload[],
    maxTokens: number = 1800,
    minTokens: number = 50,
  ) {
    return this.client.post<AudiobookSmartChunkPreviewResponse>(
      `/api/v1/audiobook/smart-chunk/preview?max_tokens=${maxTokens}&min_tokens=${minTokens}`,
      segments
    )
  }

  // 估算文本 token 数量 API
  estimateTextTokens(text: string) {
    return this.client.post<AudiobookTextTokenEstimateResponse>('/api/v1/audiobook/smart-chunk/estimate', { text })
  }

  // 获取声音类型预设列表 API
  getVoiceTypes() {
    return this.client.get('/api/v1/audiobook/voice-types')
  }

  // 获取声音类型详情 API
  getVoiceType(voiceType: string) {
    return this.client.get(`/api/v1/audiobook/voice-types/${voiceType}`)
  }

  // 推荐声音类型 API
  recommendVoiceType(personality?: string, gender?: string, ageRange?: string) {
    return this.client.post('/api/v1/audiobook/voice-types/recommend', {
      personality,
      gender,
      age_range: ageRange,
    })
  }

  // 创建 SSE 连接 URL
  getSSEStreamUrl(taskId: string): string {
    return buildApiUrl(
      this.client.defaults.baseURL,
      `/api/v1/audiobook/tasks/${encodeURIComponent(taskId)}/stream`,
    )
  }

  getSSEStreamHeaders(): HeadersInit {
    const token = getStoredAccessToken()
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  // 章节逻辑检查API
  checkChapterLogic(chapterId: number, projectId: number) {
    return this.client.post('/api/v1/ai/check-chapter-logic', {
      chapter_id: chapterId,
      project_id: projectId,
    })
  }

  listUserAssets(params?: {
    asset_kind?: string
    asset_class?: string
    source_module?: string
    tag?: string
    favorites_only?: boolean
    include_archived?: boolean
    archive_filter?: 'active' | 'archived' | 'all'
    page?: number
    page_size?: number
    limit?: number
  }) {
    return this.client.get<UserAssetListResponse>('/api/v1/user-assets', { params })
  }

  createUserAsset(payload: UserAssetRecordCreatePayload) {
    const normalizedPayload =
      payload.metadata_json === undefined
        ? payload
        : {
            ...payload,
            metadata_json: normalizeUserAssetMetadataContract(payload.metadata_json),
          }
    return this.client.post<UserAssetRecord>('/api/v1/user-assets', normalizedPayload)
  }

  updateUserAsset(assetId: number, payload: UserAssetRecordUpdatePayload) {
    return this.client.patch<UserAssetRecord>(`/api/v1/user-assets/${assetId}`, payload)
  }

  // 通用API方法
  batchUpdateUserAssets(payload: UserAssetRecordBatchUpdatePayload) {
    return this.client.patch<UserAssetRecordBatchUpdateResponse>('/api/v1/user-assets/batch', payload)
  }

  getUserCenterPointsOverview() {
    return this.client.get<UserCenterPointsOverviewResponse>('/api/v1/user-center/points-overview')
  }

  getAdminSystemHealth() {
    return this.client.get<AdminSystemHealth>('/api/v1/admin/stats/system/health')
  }

  getAdminPointsRules() {
    return this.client.get<AdminPointsRuleConfig>('/api/v1/admin/system/points-rules')
  }

  updateAdminPointsRules(payload: AdminPointsRuleUpdatePayload) {
    return this.client.put<AdminPointsRuleConfig>('/api/v1/admin/system/points-rules', payload)
  }

  getAdminPointsPricingPolicy() {
    return this.client.get<AdminPointsPricingPolicy>('/api/v1/admin/system/points-pricing-policy')
  }

  updateAdminPointsPricingPolicy(payload: AdminPointsPricingPolicyUpdatePayload) {
    return this.client.put<AdminPointsPricingPolicy>('/api/v1/admin/system/points-pricing-policy', payload)
  }

  getAdminPointsBillingEvents(params?: {
    page?: number
    page_size?: number
    user_id?: number
    module_key?: string
    event_kind?: string
    margin_status?: string
    keyword?: string
  }) {
    return this.client.get<AdminPointsBillingEventListResponse>('/api/v1/admin/billing/points-events', { params })
  }

  get(url: string, config?: any) {
    return this.client.get(url, config)
  }

  post(url: string, data?: any, config?: any) {
    return this.client.post(url, data, config)
  }

  getLatestProjectMemory(projectId: number) {
    return this.client.get(`/api/v1/projects/${projectId}/memories/latest`, {
      timeout: 15000,
      validateStatus: () => true,
    })
  }

  saveProjectMemorySnapshot(projectId: number, payload: {
    messages: any[]
    current_chapter: number | null
    current_scene: string
    active_characters: any[]
    writing_goal: string
  }) {
    return this.client.post(`/api/v1/projects/${projectId}/memories/auto-save`, payload, {
      timeout: 15000,
      validateStatus: () => true,
    })
  }

  postWorkflowStageAsync(payload: {
    projectId: number
    stage: string
    requirement?: string
    enableStreaming?: boolean
    regenerate?: boolean
    targets?: string[]
    feedback?: string
  }) {
    return this.client.post('/api/v1/workflow/execute-stage-async', {
      project_id: payload.projectId,
      stage: payload.stage,
      requirement: payload.requirement,
      enable_streaming: payload.enableStreaming,
      regenerate: payload.regenerate,
      targets: payload.targets,
      feedback: payload.feedback,
    }, {
      timeout: 5000,
      validateStatus: () => true,
    })
  }

  getWorkflowTaskStatus(taskId: string) {
    return this.client.get(`/api/v1/workflow/task/${taskId}`, {
      timeout: 5000,
      validateStatus: () => true,
    })
  }

  getWorkflowAllStagesContent(projectId: number) {
    return this.client.get(`/api/v1/workflow/${projectId}/all-stages-content`, {
      timeout: 15000,
      validateStatus: () => true,
    })
  }

  getWorkflowRunningTasks(projectId: number) {
    return this.client.get(`/api/v1/workflow/project/${projectId}/running-tasks`, {
      timeout: 15000,
      validateStatus: () => true,
    })
  }

  getWorkflowStageStatus(projectId: number) {
    return this.client.get(`/api/v1/workflow/${projectId}/stage-status`, {
      timeout: 15000,
      validateStatus: () => true,
    })
  }

  getWorkflowStageContent(projectId: number, stage: string) {
    return this.client.get(`/api/v1/workflow/${projectId}/stage/${stage}/content`, {
      timeout: 15000,
      validateStatus: () => true,
    })
  }

  updateWorkflowStageContent(
    projectId: number,
    stage: string,
    payload: { content: string; continue_workflow: boolean }
  ) {
    return this.client.put(`/api/v1/workflow/${projectId}/stage/${stage}/content`, payload, {
      timeout: 15000,
      validateStatus: () => true,
    })
  }

  generateNextWorkflowChapter(projectId: number) {
    return this.client.post(`/api/v1/workflow/${projectId}/generate-next-chapter`, undefined, {
      timeout: 15000,
      validateStatus: () => true,
    })
  }

  put(url: string, data?: any, config?: any) {
    return this.client.put(url, data, config)
  }

  patch(url: string, data?: any, config?: any) {
    return this.client.patch(url, data, config)
  }

  delete(url: string, config?: any) {
    return this.client.delete(url, config)
  }

  generateAssetStudioImage(payload: FormData) {
    return this.client.post<AssetStudioGenerateResponse>('/api/v1/asset-studio/image', payload, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    })
  }

  generateAssetStudioVideo(payload: FormData) {
    return this.client.post<AssetStudioGenerateResponse>('/api/v1/asset-studio/video', payload, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    })
  }

  generateAssetStudioMotion(payload: FormData) {
    return this.client.post<AssetStudioGenerateResponse>('/api/v1/asset-studio/motion', payload, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    })
  }

  generateAssetStudioAudio(payload: FormData) {
    return this.client.post<AssetStudioGenerateResponse>('/api/v1/asset-studio/audio', payload, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    })
  }

  generateAssetStudioVideoEdit(payload: FormData) {
    return this.client.post<AssetStudioGenerateResponse>('/api/v1/asset-studio/video-edit', payload, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
    })
  }

  reviewAssetStudioVision(payload: FormData) {
    return this.client.post<AssetStudioVisionReviewResponse>('/api/v1/asset-studio/vision-review', payload, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    })
  }

  getAssetStudioModelCatalog() {
    return this.client.get<AssetStudioModelCatalogResponse>('/api/v1/asset-studio/model-catalog')
  }

  // AI生成任务API（异步）

  // 织梦映心流程（短剧生成）
  runDreamweaver(projectId: number, chapterIds: number[], options?: DreamweaverRunOptions) {
    return this.client.post<RunResult>('/api/v1/dreamweaver/run', {
      project_id: projectId,
      chapter_ids: chapterIds,
      schema_version: DREAMWEAVER_SCHEMA_VERSION,
      ...(options?.quality_mode ? { quality_mode: options.quality_mode } : {}),
      ...(typeof options?.qc_allow_fail === 'boolean' ? { qc_allow_fail: options.qc_allow_fail } : {}),
      ...(typeof options?.smart_tuning === 'boolean' ? { smart_tuning: options.smart_tuning } : {}),
      ...(options?.ab_variant ? { ab_variant: options.ab_variant } : {}),
      ...(typeof options?.video_require_confirmation === 'boolean'
        ? { video_require_confirmation: options.video_require_confirmation }
        : {}),
      ...(typeof options?.prompt_review_required === 'boolean'
        ? { prompt_review_required: options.prompt_review_required }
        : {}),
      ...(options?.style_preset ? { style_preset: options.style_preset } : {}),
      ...(options?.image_ratio ? { image_ratio: options.image_ratio } : {}),
      ...(options?.image_resolution ? { image_resolution: options.image_resolution } : {}),
      ...(options?.image_model ? { image_model: options.image_model } : {}),
      ...(options?.video_model ? { video_model: options.video_model } : {}),
      ...(options?.video_edit_model ? { video_edit_model: options.video_edit_model } : {}),
      ...(options?.vision_model ? { vision_model: options.vision_model } : {}),
      ...(typeof options?.enable_video_edit === 'boolean'
        ? { enable_video_edit: options.enable_video_edit }
        : {}),
      ...(typeof options?.enable_vision_review === 'boolean'
        ? { enable_vision_review: options.enable_vision_review }
        : {}),
      ...(typeof options?.enable_safety_audit === 'boolean'
        ? { enable_safety_audit: options.enable_safety_audit }
        : {}),
      ...(options?.safety_fail_policy ? { safety_fail_policy: options.safety_fail_policy } : {}),
    })
  }

  runDreamweaverAsync(projectId: number, chapterIds: number[], options?: DreamweaverRunOptions) {
    return this.client.post<DreamweaverRunAsyncResponse>('/api/v1/dreamweaver/run-async', {
      project_id: projectId,
      chapter_ids: chapterIds,
      schema_version: DREAMWEAVER_SCHEMA_VERSION,
      ...(options?.quality_mode ? { quality_mode: options.quality_mode } : {}),
      ...(typeof options?.qc_allow_fail === 'boolean' ? { qc_allow_fail: options.qc_allow_fail } : {}),
      ...(typeof options?.smart_tuning === 'boolean' ? { smart_tuning: options.smart_tuning } : {}),
      ...(options?.ab_variant ? { ab_variant: options.ab_variant } : {}),
      ...(typeof options?.video_require_confirmation === 'boolean'
        ? { video_require_confirmation: options.video_require_confirmation }
        : {}),
      ...(typeof options?.prompt_review_required === 'boolean'
        ? { prompt_review_required: options.prompt_review_required }
        : {}),
      ...(options?.style_preset ? { style_preset: options.style_preset } : {}),
      ...(options?.image_ratio ? { image_ratio: options.image_ratio } : {}),
      ...(options?.image_resolution ? { image_resolution: options.image_resolution } : {}),
      ...(options?.image_model ? { image_model: options.image_model } : {}),
      ...(options?.video_model ? { video_model: options.video_model } : {}),
      ...(options?.video_edit_model ? { video_edit_model: options.video_edit_model } : {}),
      ...(options?.vision_model ? { vision_model: options.vision_model } : {}),
      ...(typeof options?.enable_video_edit === 'boolean'
        ? { enable_video_edit: options.enable_video_edit }
        : {}),
      ...(typeof options?.enable_vision_review === 'boolean'
        ? { enable_vision_review: options.enable_vision_review }
        : {}),
      ...(typeof options?.enable_safety_audit === 'boolean'
        ? { enable_safety_audit: options.enable_safety_audit }
        : {}),
      ...(options?.safety_fail_policy ? { safety_fail_policy: options.safety_fail_policy } : {}),
    })
  }

  getDreamweaverTask(taskId: string) {
    return this.client.get<TaskStatus>(`/api/v1/dreamweaver/task/${taskId}`, {
      timeout: 15000,
    })
  }

  getDreamweaverLibrary(projectId: number, options?: { run_id?: string }) {
    return this.client.get(`/api/v1/dreamweaver/library/${projectId}`, {
      params: options?.run_id ? { run_id: options.run_id } : undefined,
      timeout: 15000,
    })
  }

  getDreamweaverProjectLockedConfig(projectId: number) {
    return this.client.get<DreamweaverProjectLockedGenerationConfig>(`/api/v1/dreamweaver/projects/${projectId}/locked-config`, {
      timeout: 15000,
    })
  }

  approveDreamweaverLibrary(projectId: number, payload: DreamweaverLibraryApproveRequest) {
    return this.client.post(`/api/v1/dreamweaver/library/${projectId}/approve`, payload, {
      timeout: 15000,
    })
  }

  regenerateDreamweaverLibraryAsset(projectId: number, payload: DreamweaverLibraryRegenerateRequest) {
    return this.client.post(`/api/v1/dreamweaver/library/${projectId}/regenerate`, payload, {
      timeout: DREAMWEAVER_LIBRARY_REGENERATE_TIMEOUT_MS,
    })
  }

  suggestDreamweaverLibraryRegenerateRoles(
    projectId: number,
    payload: DreamweaverLibraryAutoRegenerateRolesRequest,
  ) {
    return this.client.post<DreamweaverLibraryAutoRegenerateRolesResponse>(
      `/api/v1/dreamweaver/library/${projectId}/regenerate-roles`,
      payload,
      { timeout: 15000 },
    )
  }

  suggestDreamweaverLibraryPrompt(projectId: number, payload: DreamweaverLibraryPromptSuggestRequest) {
    return this.client.post<DreamweaverLibraryPromptSuggestResponse>(`/api/v1/dreamweaver/library/${projectId}/prompt-suggest`, payload, {
      timeout: 60000,
    })
  }

  getDreamweaverLibraryAssetFile(assetId: number) {
    return this.client.get(`/api/v1/dreamweaver/library/assets/${assetId}/file`, {
      responseType: 'blob',
      timeout: 30000,
      params: { _ts: Date.now() },
      headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
    })
  }

  uploadDreamweaverLibraryAssetFile(assetId: number, file: File) {
    const form = new FormData()
    form.append('file', file)
    return this.client.post(`/api/v1/dreamweaver/library/assets/${assetId}/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  }

  updateDreamweaverLibraryAssetProviderRef(assetId: number, payload: DreamweaverLibraryAssetProviderRefUpdateRequest) {
    return this.client.post<DreamweaverLibraryAssetProviderRefUpdateResponse>(`/api/v1/dreamweaver/library/assets/${assetId}/provider-ref`, payload, {
      timeout: 15000,
    })
  }

  syncDreamweaverLibraryAssetProviderRef(assetId: number, payload: DreamweaverLibraryAssetProviderRefSyncRequest = {}) {
    return this.client.post<DreamweaverLibraryAssetProviderRefSyncResponse>(`/api/v1/dreamweaver/library/assets/${assetId}/provider-ref/sync`, payload, {
      timeout: 120000,
    })
  }

  uploadDreamweaverRunShotAssetFile(runId: string, shotId: string, role: string, file: File) {
    const form = new FormData()
    form.append('file', file)
    return this.client.post(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/shots/${encodeURIComponent(shotId)}/assets/${encodeURIComponent(role)}/upload`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  }

  updateDreamweaverRunShotFramePrompt(runId: string, shotId: string, frame: 'head' | 'tail', prompt: string) {
    return this.client.post(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/shots/${encodeURIComponent(shotId)}/frames/${encodeURIComponent(frame)}/prompt`, { prompt }, {
      timeout: 15000,
    })
  }

  updateDreamweaverRunShotVideoPrompt(runId: string, shotId: string, prompt?: string | null) {
    const payload: DreamweaverShotVideoPromptUpdateRequest = { prompt: prompt ?? '' }
    return this.client.post(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/shots/${encodeURIComponent(shotId)}/video-prompt`, payload, {
      timeout: 15000,
    })
  }

  resumeDreamweaverAsync(runId: string) {
    return this.client.post(`/api/v1/dreamweaver/runs/${runId}/resume-async`, null, {
      timeout: 15000,
    })
  }

  restartDreamweaverAsync(runId: string, payload: DreamweaverRestartRequest) {
    return this.client.post(`/api/v1/dreamweaver/runs/${runId}/restart-async`, payload, {
      timeout: 15000,
    })
  }

  confirmDreamweaverVideoJobAsync(runId: string, shotId: string) {
    return this.client.post<DreamweaverVideoJobConfirmAsyncResponse>(
      `/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/video-jobs/${encodeURIComponent(shotId)}/confirm-async`,
      null,
      { timeout: 15000 },
    )
  }

  rebuildDreamweaverVideoJobs(runId: string) {
    return this.client.post<DreamweaverVideoJobsRebuildResponse>(
      `/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/video-jobs/rebuild`,
      null,
      { timeout: 15000 },
    )
  }

  getDreamweaverRunScript(runId: string) {
    return this.client.get(`/api/v1/dreamweaver/runs/${runId}/script`, {
      timeout: 15000,
    })
  }

  updateDreamweaverRunScript(runId: string, payload: DreamweaverScriptUpdateRequest) {
    return this.client.post(`/api/v1/dreamweaver/runs/${runId}/script`, payload, {
      timeout: 15000,
    })
  }

  approveDreamweaverRunScript(runId: string, payload: DreamweaverScriptApproveRequest) {
    return this.client.post(`/api/v1/dreamweaver/runs/${runId}/script/approve`, payload, {
      timeout: 15000,
    })
  }

  approveDreamweaverPromptReview(runId: string, payload: DreamweaverPromptReviewApproveRequest) {
    return this.client.post(`/api/v1/dreamweaver/runs/${runId}/prompt-review/approve`, payload, {
      timeout: 15000,
    })
  }

  approveDreamweaverSafetyAudit(runId: string) {
    return this.client.post<DreamweaverSafetyAuditApproveResponse>(`/api/v1/dreamweaver/runs/${runId}/safety-audit/approve`, null, {
      timeout: 15000,
    })
  }

  getDreamweaverRun(runId: string) {
    return this.client.get<DreamweaverRunSnapshot>(`/api/v1/dreamweaver/runs/${runId}`, {
      timeout: 15000,
    })
  }

  getDreamweaverRunEvents(runId: string, params?: { after_id?: number; limit?: number }) {
    return this.client.get(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/events`, {
      params,
      timeout: 15000,
    })
  }

  getDreamweaverMergedVideoFile(runId: string) {
    return this.client.get(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/merged-video/file`, {
      responseType: 'blob',
      timeout: 60000,
    })
  }

  getDreamweaverRunAssetFile(runId: string, uri: string) {
    return this.client.get(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}/assets/file`, {
      params: { uri },
      responseType: 'blob',
      timeout: 60000,
    })
  }

  listDreamweaverRuns(projectId: number, limit: number = 50) {
    return this.client.get(`/api/v1/dreamweaver/projects/${projectId}/runs`, {
      params: { limit },
      timeout: 15000,
    })
  }

  deleteDreamweaverProjectGenerated(projectId: number) {
    return this.client.delete<DreamweaverProjectGeneratedDeleteResponse>(`/api/v1/dreamweaver/projects/${projectId}/generated`, {
      timeout: 120000,
    })
  }

  deleteDreamweaverRun(runId: string, deleteFiles: boolean = true) {
    return this.client.delete<DreamweaverRunDeleteResponse>(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}`, {
      params: { delete_files: deleteFiles },
      timeout: 15000,
    })
  }

  trackFrontendEvent(payload: FrontendEventPayload) {
    return this.client.post('/api/v1/monitoring/frontend-event', payload, {
      timeout: 5000,
    })
  }

  // 🌟 长篇框架状态检测API
  getEpicFrameworkState(projectId: number) {
    return this.client.get(`/api/v1/workflow/epic-framework-state/${projectId}`)
  }

  analyzeExpandStory(payload: StoryExpansionRequestPayload) {
    return this.client.post<StoryExpansionAnalysisResponse>('/api/v1/workflow/expand-story/analysis', payload)
  }

  expandStory(payload: StoryExpansionRequestPayload) {
    return this.client.post<StoryExpansionStartResponse>('/api/v1/workflow/expand-story', payload)
  }

  repairExpandStoryScore(payload: StoryExpansionRepairRequestPayload) {
    return this.client.post<StoryExpansionRepairResponse>('/api/v1/workflow/expand-story/repair-score', payload)
  }

  getAudioLibraryStats() {
    return this.client.get<{
      sfx_count: number
      sfx_categories: string[]
      sfx_scenes?: string[]
      music_count: number
      music_styles: string[]
      music_moods: string[]
    }>('/api/v1/audiobook/audio-library/stats')
  }

  browseSoundEffects(params?: { category?: string; tag?: string; scene?: string; search?: string }) {
    const query = new URLSearchParams()
    if (params?.category) query.set('category', params.category)
    if (params?.tag) query.set('tag', params.tag)
    if (params?.scene) query.set('scene', params.scene)
    if (params?.search) query.set('search', params.search)
    const qs = query.toString()
    return this.client.get<Array<{
      id: string
      name: string
      category: string
      style?: string
      file_path: string
      description: string
      tags: string[]
      scenes?: string[]
      source: string
      source_id?: string
      source_url?: string
      author?: string
      author_url?: string
      license?: string
      license_url?: string
      license_version?: string
      license_commercial?: boolean
      attribution_required?: boolean
      attribution_text?: string
      quality_score?: number
      quality_grade?: string
      quality_status?: string
      retrieved_at?: string
      license_checked_at?: string
    }>>(`/api/v1/audiobook/audio-library/sound-effects${qs ? '?' + qs : ''}`)
  }

  browseMusic(params?: { style?: string; mood?: string; search?: string }) {
    const query = new URLSearchParams()
    if (params?.style) query.set('style', params.style)
    if (params?.mood) query.set('mood', params.mood)
    if (params?.search) query.set('search', params.search)
    const qs = query.toString()
    return this.client.get<Array<{
      id: string
      style: string
      duration: number
      tempo: string
      mood: string
      bucket: string
      file_path: string
      source: string
      variant: number | null
      source_id?: string
      source_url?: string
      author?: string
      author_url?: string
      license?: string
      license_url?: string
      license_version?: string
      license_commercial?: boolean
      attribution_required?: boolean
      attribution_text?: string
      quality_score?: number
      quality_grade?: string
      quality_status?: string
      retrieved_at?: string
      license_checked_at?: string
    }>>(`/api/v1/audiobook/audio-library/music${qs ? '?' + qs : ''}`)
  }

  getAudioLibraryPreviewUrl(fileType: 'sfx' | 'music', fileId: string) {
    return `/api/v1/audiobook/audio-library/preview/${fileType}/${fileId}`
  }

  listSfxCandidates(params?: { status?: string }) {
    const query = new URLSearchParams()
    if (params?.status) query.set('status', params.status)
    const qs = query.toString()
    return this.client.get<{
      total: number
      invalid_rows: number
      items: Array<{
        source: string
        source_id: string
        name: string
        description: string
        source_url: string
        file_url: string
        preview_url: string
        license: string
        license_url: string
        license_version: string
        license_commercial: boolean
        attribution_required: boolean
        attribution_text: string
        author: string
        author_url: string
        duration: number
        mime_type: string
        tags: string[]
        query: string
        discovered_at: string
        license_checked_at: string
        requires_manual_review: boolean
        status: string
        review_notes: string
      }>
    }>(`/api/v1/audiobook/audio-library/sound-effects/candidates${qs ? '?' + qs : ''}`)
  }

  buildSfxCandidateManifestDraft(payload: {
    source_dir?: string
    output_path?: string
    items: Array<{
      source: string
      source_id: string
      review_status: 'approved' | 'rejected' | 'needs_info'
      license_verified?: boolean
      local_file?: string
      category?: string
      style?: string
      notes?: string
    }>
  }) {
    return this.client.post<{
      success: boolean
      manifest_path: string
      source_dir: string
      stats: { approved: number; rejected: number; skipped: number }
      items: Array<Record<string, unknown>>
    }>('/api/v1/audiobook/audio-library/sound-effects/candidates/manifest-draft', payload)
  }

  importSfxManifest(payload: {
    manifest_path?: string
    source_dir?: string
    dry_run?: boolean
    confirm?: boolean
    overwrite?: boolean
  }) {
    return this.client.post<{
      success: boolean
      dry_run: boolean
      manifest_path: string
      source_dir: string
      stats: {
        candidates: number
        imported: number
        rejected_license: number
        rejected_file: number
        rejected_quality: number
        skipped_existing: number
      }
      records: Array<Record<string, unknown>>
    }>('/api/v1/audiobook/audio-library/sound-effects/import-manifest', payload)
  }

  submitUserRating(payload: {
    model_id: string
    task_type: string
    rating: number
    comment?: string
    prompt_text?: string
    output_urls?: string[]
    project_id?: number
  }) {
    return this.client.post<{ success: boolean; feedback_id?: number }>(
      '/api/v1/feedback/user-rating',
      payload,
    )
  }

  getModelFeedbackStats(modelId: string, params?: { task_type?: string; days?: number }) {
    const query = new URLSearchParams()
    if (params?.task_type) query.set('task_type', params.task_type)
    if (params?.days) query.set('days', String(params.days))
    const qs = query.toString()
    return this.client.get<{
      success: boolean
      stats: Record<string, unknown> | null
    }>(`/api/v1/feedback/model-stats/${encodeURIComponent(modelId)}${qs ? '?' + qs : ''}`)
  }

  cleanupAudioLibrary(payload: {
    library_type: string
    remove_orphaned?: boolean
    remove_missing_files?: boolean
    remove_low_quality?: boolean
    min_quality_score?: number
    dry_run?: boolean
    confirm?: boolean
  }) {
    return this.client.post<{
      success: boolean
      dry_run: boolean
      stats: {
        removed_orphaned: number
        removed_missing: number
        removed_low_quality: number
        freed_bytes: number
      }
      details: {
        missing_entries: Array<{ library_type: string; id: string; name: string; file_path: string; reason: string; size: number }>
        low_quality_entries: Array<{ library_type: string; id: string; name: string; file_path: string; reason: string; size: number }>
        orphaned_files: Array<{ library_type: string; id: string; name: string; file_path: string; reason: string; size: number }>
      }
    }>('/api/v1/audiobook/audio-library/cleanup', payload)
  }

  deleteAudioLibraryAsset(
    libraryType: 'sfx' | 'music',
    assetId: string,
    payload: {
      dry_run?: boolean
      confirm?: boolean
      delete_cloud_object?: boolean
      delete_local_file?: boolean
    },
  ) {
    return this.client.post<{
      success: boolean
      dry_run: boolean
      asset: { library_type: string; id: string; name: string; file_path: string; reason: string; size: number }
      stats: { index_removed: number; local_deleted: number; cloud_deleted: number }
      details: Record<string, unknown>
    }>(
      `/api/v1/audiobook/audio-library/assets/${libraryType}/${encodeURIComponent(assetId)}/delete`,
      payload,
    )
  }

  getScriptReviewReport(audiobookProjectId: number, chapterId: number) {
    return this.client.get<{
      success: boolean
      chapter_id: number
      audiobook_project_id: number
      script_status: string
      quality_report: {
        script_quality: Record<string, unknown>
        audio_balance: Record<string, unknown>
        pacing: Record<string, unknown>
        issues: Array<{
          location: string
          severity: string
          category: string
          description: string
          suggestion: string
        }>
        overall_grade: string
        overall_score: number
        revision_suggestions: string[]
      }
    }>(`/api/v1/script-review/report/${audiobookProjectId}/${chapterId}`)
  }

  submitScriptReviewFeedback(payload: {
    audiobook_project_id: number
    chapter_id: number
    feedback: string
  }) {
    const params = new URLSearchParams()
    params.append('audiobook_project_id', String(payload.audiobook_project_id))
    params.append('chapter_id', String(payload.chapter_id))
    params.append('feedback', payload.feedback)
    return this.client.post<{
      success: boolean
      message: string
    }>('/api/v1/script-review/feedback', params)
  }

  checkConsistency(payload: {
    world_settings: Array<{ type?: string; name?: string; content?: string }>
    new_content: string
    project_id?: number
  }) {
    return this.client.post<{
      status: string
      is_consistent: boolean
      consistency_check: {
        raw_result: string
        settings_checked: number
        consistency_score: number
        analysis_summary: string
        checked_at: string
      }
    }>('/api/v1/ai/check-consistency', payload)
  }

  smartDispatch(payload: {
    user_input: string
    context?: Record<string, unknown>
    strategy?: string
    use_fallback?: boolean
    dry_run?: boolean
  }) {
    return this.client.post<{
      success: boolean
      intent?: Record<string, unknown>
      routing?: Record<string, unknown>
      execution?: Record<string, unknown>
      trace?: Record<string, unknown>
      error?: string
    }>('/api/v1/smart-dispatch/dispatch', payload)
  }

  recommendModels(payload: {
    user_input: string
    context?: Record<string, unknown>
    strategy?: string
  }) {
    return this.client.post<{
      success: boolean
      intent: Record<string, unknown>
      candidates: Array<{
        model_id: string
        name: string
        provider: string
        score: number
        modality: string
        quality_score: number
        avg_latency: number
        cost: number
        recommended_scenarios: string[]
        tags: string[]
      }>
      recommended?: {
        model_id: string
        name: string
        provider: string
        score: number
        modality: string
        quality_score: number
        avg_latency: number
        cost: number
        recommended_scenarios: string[]
        tags: string[]
      }
      reasons: string[]
    }>('/api/v1/smart-dispatch/recommend-models', payload)
  }
}

export const apiClient = new ApiClient()

