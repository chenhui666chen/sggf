import { EXPORT_STAGE_CONFIG, GENERATION_STAGE_CONFIG, STAGE_KEYS } from './constants'
export { buildAudiobookChapterAssetUuid } from '../../utils/audiobookAssetIds'
import type {
  NavigationType,
  ScriptReviewDetail,
  StageConfig,
  StageInfo,
  StageKey,
  StageStatus,
  TaskStatus,
} from './types'

type ApiRecord = Record<string, unknown>

type LegacyPerformanceNavigation = {
  type: number
  TYPE_RELOAD: number
  TYPE_BACK_FORWARD: number
}

const isRecord = (value: unknown): value is ApiRecord =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

const getNumberValue = (record: ApiRecord, key: string): number | undefined => {
  const value = record[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

const getStringValue = (record: ApiRecord, key: string): string | undefined => {
  const value = record[key]
  return typeof value === 'string' ? value : undefined
}

const getStringArrayValue = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []

export function buildAudiobookChapterDownloadUrl(audiobookProjectId: number, chapterId: number): string {
  return `/api/v1/audiobook/download/${audiobookProjectId}/${chapterId}`
}

export function extractDownloadFilename(contentDisposition: string | null | undefined, fallback: string): string {
  const header = String(contentDisposition || '').trim()
  if (!header) return fallback

  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }

  const asciiMatch = header.match(/filename="?([^";]+)"?/i)
  return asciiMatch?.[1]?.trim() || fallback
}

export const createEmptyStageMap = (): Record<StageKey, StageInfo> =>
  STAGE_KEYS.reduce((acc, key) => {
    acc[key] = {
      status: 'pending',
      progress: 0,
      start_time: undefined,
      end_time: undefined,
      error_message: undefined,
      metrics: undefined,
      message: undefined,
    }
    return acc
  }, {} as Record<StageKey, StageInfo>)

export const coerceStageStatus = (value: unknown): StageStatus => {
  if (value === 'running' || value === 'completed' || value === 'failed' || value === 'pending') {
    return value
  }
  return 'pending'
}

export const isProjectExportTask = (task: Pick<TaskStatus, 'task_type'> | null | undefined) =>
  task?.task_type === 'export_m4b' || task?.task_type === 'export_audacity'

export const getStageConfigForTask = (task: Pick<TaskStatus, 'task_type'>): readonly StageConfig[] =>
  isProjectExportTask(task) ? EXPORT_STAGE_CONFIG : GENERATION_STAGE_CONFIG

export const normalizeStageEntry = (raw: unknown): StageInfo => {
  const entry = isRecord(raw) ? raw : {}
  const errorMessage = entry.error_message ?? entry.error

  return {
    status: coerceStageStatus(entry.status),
    progress: getNumberValue(entry, 'progress') ?? 0,
    start_time: getStringValue(entry, 'start_time'),
    end_time: getStringValue(entry, 'end_time'),
    error_message: typeof errorMessage === 'string' ? errorMessage : undefined,
    metrics: isRecord(entry.metrics) ? entry.metrics : undefined,
    message: getStringValue(entry, 'message'),
  }
}

export const normalizeTaskStatusResponse = (payload: unknown): TaskStatus => {
  const task = isRecord(payload) ? payload : {}
  const detail = isRecord(task.detail) ? task.detail : {}
  const rawStages = isRecord(detail.stages) ? detail.stages : {}
  const normalizedStages = createEmptyStageMap()

  Object.entries(rawStages).forEach(([key, value]) => {
    const stageKey = key as StageKey
    if (STAGE_KEYS.includes(stageKey)) {
      normalizedStages[stageKey] = normalizeStageEntry(value)
    }
  })

  const currentStageValue = task.current_stage || detail.current_stage
  const currentStage = typeof currentStageValue === 'string' ? currentStageValue : undefined
  if (currentStage && normalizedStages[currentStage as StageKey]) {
    const stageInfo = normalizedStages[currentStage as StageKey]
    if (stageInfo.status === 'pending' && task.status === 'running') {
      stageInfo.status = 'running'
    }
  }

  const rawTaskId = task.celery_task_id || task.task_id || task.id
  const taskId = typeof rawTaskId === 'string'
    ? rawTaskId
    : rawTaskId == null
      ? ''
      : String(rawTaskId)

  return {
    task_id: taskId,
    audiobook_project_id: getNumberValue(task, 'audiobook_project_id') ?? 0,
    chapter_id: getNumberValue(task, 'chapter_id') ?? null,
    task_type: typeof task.task_type === 'string' ? task.task_type : null,
    status: coerceStageStatus(task.status),
    current_stage: currentStage,
    progress: getNumberValue(task, 'progress') ?? 0,
    stages: normalizedStages,
    created_at: getStringValue(task, 'created_at'),
    updated_at: getStringValue(task, 'updated_at'),
    detail,
    overall_progress: getNumberValue(detail, 'overall_progress'),
  }
}

export const buildPendingTaskStatus = ({
  taskId,
  audiobookProjectId,
  taskType,
  chapterId = null,
}: {
  taskId: string
  audiobookProjectId: number
  taskType?: string | null
  chapterId?: number | null
}): TaskStatus => {
  const now = new Date().toISOString()
  return {
    task_id: taskId,
    audiobook_project_id: audiobookProjectId,
    chapter_id: chapterId,
    task_type: taskType || null,
    status: 'pending',
    current_stage: null,
    progress: 0,
    stages: createEmptyStageMap(),
    created_at: now,
    updated_at: now,
    detail: {},
    overall_progress: 0,
  }
}

export const AUDIOBOOK_SESSION_STORAGE_KEY = 'audiobook_active_session_v1'

export const detectNavigationType = (): NavigationType => {
  if (typeof window === 'undefined' || typeof performance === 'undefined') {
    return 'navigate'
  }
  try {
    if (typeof performance.getEntriesByType === 'function') {
      const entries = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[]
      if (entries.length > 0) {
        return entries[0].type
      }
    }
    const legacyNavigation = (
      performance as Performance & { navigation?: LegacyPerformanceNavigation }
    ).navigation
    if (legacyNavigation) {
      switch (legacyNavigation.type) {
        case legacyNavigation.TYPE_RELOAD:
          return 'reload'
        case legacyNavigation.TYPE_BACK_FORWARD:
          return 'back_forward'
        default:
          return 'navigate'
      }
    }
  } catch {
    // 忽略导航类型检测失败
  }
  return 'navigate'
}

export const ISSUE_DISPLAY_LIMIT = 20

export const isSamePathReferrer = () => {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return false
  }
  try {
    if (!document.referrer) return false
    const refUrl = new URL(document.referrer)
    return refUrl.origin === window.location.origin && refUrl.pathname === window.location.pathname
  } catch {
    return false
  }
}

export const severityColorMap: Record<string, 'default' | 'error' | 'warning' | 'info'> = {
  critical: 'error',
  major: 'warning',
  minor: 'info',
}

export const severityLabelMap: Record<string, string> = {
  critical: '严重',
  major: '重要',
  minor: '提示',
}

export const categoryLabelMap: Record<string, string> = {
  script: '剧本',
  audio: '音频',
  pacing: '节奏',
}

const normalizeScriptQualityMetrics = (
  value: unknown,
): ScriptReviewDetail['script_quality'] | undefined => {
  if (!isRecord(value)) return undefined
  return {
    naturalness_score: getNumberValue(value, 'naturalness_score'),
    clarity_score: getNumberValue(value, 'clarity_score'),
    engagement_score: getNumberValue(value, 'engagement_score'),
    total_segments: getNumberValue(value, 'total_segments'),
    average_segment_length: getNumberValue(value, 'average_segment_length'),
  }
}

const normalizeScriptAudioBalanceMetrics = (
  value: unknown,
): ScriptReviewDetail['audio_balance'] | undefined => {
  if (!isRecord(value)) return undefined
  return {
    sound_effects: getStringValue(value, 'sound_effects'),
    music: getStringValue(value, 'music'),
    voice_differentiation: getStringValue(value, 'voice_differentiation'),
    total_effects: getNumberValue(value, 'total_effects'),
    total_music_cues: getNumberValue(value, 'total_music_cues'),
    effects_per_minute: getNumberValue(value, 'effects_per_minute'),
  }
}

const normalizeScriptPacingMetrics = (
  value: unknown,
): ScriptReviewDetail['pacing'] | undefined => {
  if (!isRecord(value)) return undefined
  return {
    estimated_duration: getStringValue(value, 'estimated_duration'),
    pacing_issues: getStringArrayValue(value.pacing_issues),
    average_segment_duration: getStringValue(value, 'average_segment_duration'),
    total_segments: getNumberValue(value, 'total_segments'),
  }
}

const normalizeScriptReviewIssues = (value: unknown): NonNullable<ScriptReviewDetail['issues']> =>
  Array.isArray(value)
    ? value
        .filter(isRecord)
        .map((issue) => ({
          location: getStringValue(issue, 'location'),
          severity: getStringValue(issue, 'severity'),
          category: getStringValue(issue, 'category'),
          description: getStringValue(issue, 'description'),
          suggestion: getStringValue(issue, 'suggestion'),
        }))
    : []

export const normalizeScriptReview = (raw: unknown): ScriptReviewDetail | null => {
  if (!isRecord(raw)) return null
  const safeIssues = normalizeScriptReviewIssues(raw.issues)
  return {
    overall_score: getNumberValue(raw, 'overall_score'),
    overall_grade: getStringValue(raw, 'overall_grade'),
    issues_count:
      typeof raw.issues_count === 'number' && Number.isFinite(raw.issues_count)
        ? raw.issues_count
        : safeIssues.length,
    script_quality: normalizeScriptQualityMetrics(raw.script_quality),
    audio_balance: normalizeScriptAudioBalanceMetrics(raw.audio_balance),
    pacing: normalizeScriptPacingMetrics(raw.pacing),
    revision_suggestions: getStringArrayValue(raw.revision_suggestions),
    issues: safeIssues,
  }
}

export const formatTenScale = (value?: number) => {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return value.toFixed(1)
}

export const formatOneDecimal = (value?: number) => {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return value.toFixed(1)
}
