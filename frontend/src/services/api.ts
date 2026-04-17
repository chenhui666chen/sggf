import axios, { AxiosInstance, AxiosError } from 'axios'
import type { UserAudiobookProjectOverview } from '@/types/audiobook'
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
  StoryExpansionRequestPayload,
  StoryExpansionStartResponse,
} from '@/types/storyExpansion'
import type {
  DreamweaverRunAsyncResponse,
  DreamweaverRunSnapshot,
  RunResult,
  TaskStatus,
} from '@/types/dreamweaver'

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
}

interface DreamweaverProjectLockedGenerationConfig {
  locked: boolean
  style_preset: string
  image_ratio: string
  image_resolution: string
  source_run_id?: string | null
}

interface DreamweaverLibraryApproveRequest {
  approve_all?: boolean
  roles?: string[]
  approved?: boolean
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

export interface AssetStudioGenerateResponse {
  kind: string
  mode: string
  model_id: string
  outputs: string[]
  primary_output?: string | null
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

export interface UserAssetRecord {
  id: number
  user_id: number
  project_id?: number | null
  source_module: string
  asset_kind: string
  asset_class: string
  title: string
  description?: string | null
  file_url?: string | null
  preview_url?: string | null
  model_id?: string | null
  generation_mode?: string | null
  tags: string[]
  metadata_json?: Record<string, any>
  source_payload_json?: Record<string, any>
  is_favorite: boolean
  archived_at?: string | null
  created_at: string
  updated_at: string
}

export interface UserAssetRecordCreatePayload {
  project_id?: number | null
  source_module: string
  asset_kind: string
  asset_class?: string
  title: string
  description?: string | null
  file_url: string
  preview_url?: string | null
  model_id?: string | null
  generation_mode?: string | null
  tags?: string[]
  metadata_json?: Record<string, any>
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
  reset_policy?: string
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
  video_clip_jobs?: any[] | null
}

interface DreamweaverVideoJobsRebuildResponse {
  run_id: string
  video_clip_jobs: any[]
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
      const token = localStorage.getItem('access_token')
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

  syncModelCatalog(payload?: {
    force_refresh?: boolean
    model_keys?: string[]
    max_verification_age_hours?: number
  }) {
    return this.client.post('/api/v1/model-catalog/sync', payload ?? { force_refresh: true })
  }

  updateProject(projectId: number, data: ProjectUpdatePayload) {
    return this.client.put<Project>(`/api/v1/projects/${projectId}`, data)
  }

  deleteProject(projectId: number) {
    return this.client.delete(`/api/v1/projects/${projectId}`)
  }

  getProjectAudioConfig(projectId: number, ttsModel?: string) {
    return this.client.get(`/api/v1/projects/${projectId}/audio-config`, {
      params: ttsModel ? { tts_model: ttsModel } : undefined,
    })
  }

  updateProjectAudioConfig(projectId: number, data: any, ttsModel?: string) {
    return this.client.put(`/api/v1/projects/${projectId}/audio-config`, data, {
      params: ttsModel ? { tts_model: ttsModel } : undefined,
    })
  }

  autoAssignProjectAudioVoices(projectId: number, ttsModel?: string) {
    return this.client.post(
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

  previewTTS(payload: { text: string; voice_id: string; volume?: number; speed?: number; pitch?: number; model?: string }) {
    return this.client.post('/api/v1/audiobook/tts/preview', payload, { responseType: 'blob' })
  }

  previewScriptSegmentAudio(
    audiobookProjectId: number,
    chapterId: number,
    payload: { segment: Record<string, any>; tts_model?: string; preview_type?: string }
  ) {
    return this.client.post(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/segments/preview`,
      payload,
      { responseType: 'blob' }
    )
  }

  getTtsVoices(model?: string) {
    return this.client.get('/api/v1/audiobook/tts/voices', {
      params: model ? { model } : undefined,
    })
  }

  createCosyVoiceV3PlusClone(payload: { name: string; url: string }) {
    return this.client.post('/api/v1/audiobook/tts/voices/cosyvoice-v3-plus/clones', payload)
  }

  deleteCosyVoiceV3PlusClone(voiceId: string) {
    return this.client.delete(
      `/api/v1/audiobook/tts/voices/cosyvoice-v3-plus/clones/${encodeURIComponent(voiceId)}`
    )
  }

  uploadCosyVoiceV3PlusCloneSample(file: File) {
    const form = new FormData()
    form.append('file', file)
    return this.client.post('/api/v1/audiobook/tts/voices/cosyvoice-v3-plus/clones/upload', form, {
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

  createAudiobookProject(payload: {
    project_id: number
    chapter_ids: number[]
    tts_provider?: string
    enable_cache?: boolean
    voice_config?: any[]
    tts_model?: string
    generation_mode?: 'full' | 'script_only'
  }) {
    return this.client.post('/api/v1/audiobook/projects', payload)
  }

  getAudiobookChapterScript(audiobookProjectId: number, chapterId: number) {
    return this.client.get(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/script`
    )
  }

  updateAudiobookChapterScript(audiobookProjectId: number, chapterId: number, payload: any) {
    return this.client.put(
      `/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/script`,
      payload
    )
  }

  generateAudioFromScripts(audiobookProjectId: number, payload: any) {
    return this.client.post(
      `/api/v1/audiobook/projects/${audiobookProjectId}/generate-audio-from-scripts`,
      payload
    )
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
    favorites_only?: boolean
    include_archived?: boolean
    limit?: number
  }) {
    return this.client.get<UserAssetRecord[]>('/api/v1/user-assets', { params })
  }

  createUserAsset(payload: UserAssetRecordCreatePayload) {
    return this.client.post<UserAssetRecord>('/api/v1/user-assets', payload)
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

  // AI生成任务API（异步）
  executeStageAsync(projectId: number, stage: string, requirement?: string) {
    return this.client.post(`/api/v1/workflow/execute-stage-async`, {
      project_id: projectId,
      stage: stage,
      requirement: requirement,
    }, {
      timeout: 5000 // 提交任务快速返回
    })
  }

  getTaskStatus(taskId: string) {
    return this.client.get(`/api/v1/workflow/task/${taskId}`, {
      timeout: 5000
    })
  }

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
    return this.client.delete(`/api/v1/dreamweaver/runs/${encodeURIComponent(runId)}`, {
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
}

export const apiClient = new ApiClient()

