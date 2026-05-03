import type { TtsModel } from './types'
import { normalizePositiveId } from './editorSessionUtils'
import { normalizeTtsModelValue } from './ttsModels'

export const AUDIOBOOK_SESSION_TAB_ID_KEY = 'audiobook_session_tab_id_v1'

export const createEphemeralAudiobookSessionId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `tab_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
}

export const getOrCreateAudiobookSessionTabId = (): string => {
  if (typeof window === 'undefined' || typeof sessionStorage === 'undefined') {
    return createEphemeralAudiobookSessionId()
  }

  try {
    const existing = sessionStorage.getItem(AUDIOBOOK_SESSION_TAB_ID_KEY)
    if (existing) {
      return existing
    }

    const nextId = createEphemeralAudiobookSessionId()
    sessionStorage.setItem(AUDIOBOOK_SESSION_TAB_ID_KEY, nextId)
    return nextId
  } catch {
    return createEphemeralAudiobookSessionId()
  }
}

export interface AudiobookSessionState {
  projectId?: number | null
  audiobookProjectId?: number | null
  taskId?: string | null
  activeTasks?: Array<{
    taskId: string
    audiobookProjectId: number
  }>
  selectedChapterIds?: number[]
  activeStep?: number
  generating?: boolean
  ttsModel?: TtsModel
  updatedAt?: string
  writerTabId?: string
}

export interface AudiobookSessionTaskFocus {
  activeTasks: Array<{ taskId: string; audiobookProjectId: number }>
  taskId: string | null
  audiobookProjectId: number | null
}

export const dedupeSessionTaskRefs = (
  taskRefs: AudiobookSessionState['activeTasks'],
): Array<{ taskId: string; audiobookProjectId: number }> => {
  const seen = new Set<string>()
  const normalized: Array<{ taskId: string; audiobookProjectId: number }> = []

  for (const item of taskRefs || []) {
    const taskId = typeof item?.taskId === 'string' ? item.taskId.trim() : ''
    const audiobookProjectId = Number(item?.audiobookProjectId)
    if (!taskId || !Number.isFinite(audiobookProjectId) || audiobookProjectId <= 0) {
      continue
    }
    if (seen.has(taskId)) {
      continue
    }
    seen.add(taskId)
    normalized.push({
      taskId,
      audiobookProjectId,
    })
  }

  return normalized
}

export const normalizeSelectedChapterIds = (
  chapterIds: unknown,
  options?: {
    allowedIds?: number[]
    fallbackIds?: number[]
  },
): number[] => {
  const allowedIdSet = Array.isArray(options?.allowedIds)
    ? new Set(
        options.allowedIds
          .map((item) => Number(item))
          .filter((item) => Number.isFinite(item) && item > 0),
      )
    : null

  const normalized = Array.isArray(chapterIds)
    ? Array.from(
        new Set(
          chapterIds
            .map((item) => Number(item))
            .filter((item) => Number.isFinite(item) && item > 0)
            .filter((item) => !allowedIdSet || allowedIdSet.has(item)),
        ),
      )
    : []

  if (normalized.length > 0) {
    return normalized
  }

  return Array.isArray(options?.fallbackIds) ? options.fallbackIds : []
}

export const resolveAudiobookSessionTaskFocus = (
  session: Partial<AudiobookSessionState> | null | undefined,
): AudiobookSessionTaskFocus => {
  const activeTasks = dedupeSessionTaskRefs(session?.activeTasks)
  const taskId = session?.taskId || activeTasks[0]?.taskId || null
  const audiobookProjectId = session?.audiobookProjectId
    || activeTasks.find((item) => item.taskId === taskId)?.audiobookProjectId
    || activeTasks[0]?.audiobookProjectId
    || null

  return {
    activeTasks,
    taskId,
    audiobookProjectId,
  }
}

export const buildComparableAudiobookSessionPayload = (
  session: Partial<AudiobookSessionState> | null | undefined,
) => ({
  projectId: normalizePositiveId(session?.projectId),
  audiobookProjectId: normalizePositiveId(session?.audiobookProjectId),
  taskId: typeof session?.taskId === 'string' && session.taskId.trim() ? session.taskId.trim() : null,
  activeTasks: dedupeSessionTaskRefs(session?.activeTasks),
  selectedChapterIds: normalizeSelectedChapterIds(session?.selectedChapterIds),
  activeStep: typeof session?.activeStep === 'number' ? session.activeStep : undefined,
  generating: Boolean(session?.generating),
  ttsModel: normalizeTtsModelValue(session?.ttsModel) || undefined,
})
