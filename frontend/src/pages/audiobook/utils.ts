import { STAGE_KEYS } from './constants'
import type {
  NavigationType,
  ScriptReviewDetail,
  StageInfo,
  StageKey,
  StageStatus,
  TaskStatus,
} from './types'

export function buildAudiobookChapterDownloadUrl(audiobookProjectId: number, chapterId: number): string {
  return `/api/v1/audiobook/download/${audiobookProjectId}/${chapterId}`
}

export function buildAudiobookChapterAssetUuid(audiobookProjectId: number, chapterId: number): string {
  return `audiobook-${audiobookProjectId}-${chapterId}`
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

export const coerceStageStatus = (value: any): StageStatus => {
  if (value === 'running' || value === 'completed' || value === 'failed' || value === 'pending') {
    return value
  }
  return 'pending'
}

export const normalizeStageEntry = (raw: any): StageInfo => ({
  status: coerceStageStatus(raw?.status),
  progress: typeof raw?.progress === 'number' ? raw.progress : 0,
  start_time: raw?.start_time,
  end_time: raw?.end_time,
  error_message: raw?.error ?? raw?.error_message,
  metrics: raw?.metrics,
  message: raw?.message,
})

export const normalizeTaskStatusResponse = (payload: any): TaskStatus => {
  const detail = payload?.detail ?? {}
  const rawStages = (detail?.stages ?? {}) as Record<string, any>
  const normalizedStages = createEmptyStageMap()

  Object.entries(rawStages).forEach(([key, value]) => {
    const stageKey = key as StageKey
    if (STAGE_KEYS.includes(stageKey)) {
      normalizedStages[stageKey] = normalizeStageEntry(value)
    }
  })

  const currentStage = (payload?.current_stage || detail?.current_stage) as string | undefined
  if (currentStage && normalizedStages[currentStage as StageKey]) {
    const stageInfo = normalizedStages[currentStage as StageKey]
    if (stageInfo.status === 'pending' && payload?.status === 'running') {
      stageInfo.status = 'running'
    }
  }

  const taskId = payload?.celery_task_id || payload?.task_id || String(payload?.id || '')

  return {
    task_id: taskId,
    audiobook_project_id: payload?.audiobook_project_id,
    chapter_id: payload?.chapter_id ?? null,
    status: coerceStageStatus(payload?.status),
    current_stage: currentStage,
    progress: typeof payload?.progress === 'number' ? payload.progress : 0,
    stages: normalizedStages,
    created_at: payload?.created_at,
    updated_at: payload?.updated_at,
    detail,
    overall_progress: typeof detail?.overall_progress === 'number' ? detail.overall_progress : undefined,
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
    const legacyNavigation = (performance as any).navigation
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

export const normalizeScriptReview = (raw: any): ScriptReviewDetail | null => {
  if (!raw || typeof raw !== 'object') return null
  const safeIssues = Array.isArray(raw.issues) ? raw.issues : []
  return {
    overall_score: typeof raw.overall_score === 'number' ? raw.overall_score : undefined,
    overall_grade: raw.overall_grade,
    issues_count:
      typeof raw.issues_count === 'number'
        ? raw.issues_count
        : safeIssues.length,
    script_quality: raw.script_quality,
    audio_balance: raw.audio_balance,
    pacing: raw.pacing,
    revision_suggestions: Array.isArray(raw.revision_suggestions) ? raw.revision_suggestions : [],
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
