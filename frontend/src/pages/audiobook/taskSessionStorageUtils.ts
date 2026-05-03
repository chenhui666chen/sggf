import { parseSessionTimestamp } from './editorSessionUtils'
import {
  buildComparableAudiobookSessionPayload,
  normalizeSelectedChapterIds,
  resolveAudiobookSessionTaskFocus,
  type AudiobookSessionState,
} from './sessionUtils'
import { normalizeTtsModelValue } from './ttsModels'
import type { Chapter, TaskStatus, TtsModel } from './types'
import { buildPendingTaskStatus } from './utils'

type AudiobookTaskSessionStorage = Pick<Storage, 'getItem' | 'removeItem' | 'setItem'>

export interface AudiobookTaskSessionPayloadParams {
  projectId: number | null
  audiobookProjectId: number | null
  taskId: string | null
  activeTasks: AudiobookSessionState['activeTasks']
  selectedChapterIds: number[]
  activeStep: number
  generating: boolean
  ttsModel: TtsModel
  writerTabId: string
  updatedAt?: string
}

export interface IncomingAudiobookTaskSessionUpdate {
  incomingActiveTasks: Array<{ taskId: string; audiobookProjectId: number }>
  incomingTaskId: string | null
  incomingAudiobookProjectId: number | null
  normalizedChapterIds: number[]
  hasSelectedChapterIds: boolean
  incomingActiveStep: number | null
  incomingGenerating: boolean
  incomingTtsModel: TtsModel | null
}

export const shouldClearAudiobookTaskSession = ({
  selectedProjectId,
  currentAudiobookProjectId,
  currentTaskId,
}: {
  selectedProjectId: number | null
  currentAudiobookProjectId: number | null
  currentTaskId: string | null
}): boolean => !selectedProjectId && !currentAudiobookProjectId && !currentTaskId

export const removeStoredAudiobookTaskSession = (
  storage: AudiobookTaskSessionStorage,
  storageKey: string,
) => {
  try {
    storage.removeItem(storageKey)
  } catch {
    // localStorage 不可用时忽略任务会话清理失败。
  }
}

export const buildAudiobookTaskSessionPayload = ({
  writerTabId,
  updatedAt = new Date().toISOString(),
  ...session
}: AudiobookTaskSessionPayloadParams): AudiobookSessionState => ({
  ...buildComparableAudiobookSessionPayload(session),
  updatedAt,
  writerTabId,
})

export const buildStoredComparableAudiobookTaskSessionPayload = (
  storage: AudiobookTaskSessionStorage,
  storageKey: string,
): string | null => {
  let currentStoredPayload: string | null = null
  try {
    currentStoredPayload = storage.getItem(storageKey)
  } catch {
    return null
  }

  if (!currentStoredPayload) {
    return null
  }

  try {
    return JSON.stringify(
      buildComparableAudiobookSessionPayload(
        JSON.parse(currentStoredPayload) as AudiobookSessionState,
      ),
    )
  } catch {
    return null
  }
}

export const shouldWriteAudiobookTaskSession = (
  storage: AudiobookTaskSessionStorage,
  storageKey: string,
  session: Partial<AudiobookSessionState>,
): boolean =>
  buildStoredComparableAudiobookTaskSessionPayload(storage, storageKey)
  !== JSON.stringify(buildComparableAudiobookSessionPayload(session))

export const writeStoredAudiobookTaskSession = (
  storage: AudiobookTaskSessionStorage,
  storageKey: string,
  payload: AudiobookSessionState,
): boolean => {
  try {
    storage.setItem(storageKey, JSON.stringify(payload))
    return true
  } catch {
    return false
  }
}

export const readIncomingAudiobookTaskSession = ({
  rawSession,
  selectedProjectId,
  writerTabId,
  lastSessionTimestamp,
}: {
  rawSession: string | null
  selectedProjectId: number
  writerTabId: string
  lastSessionTimestamp: number
}): { incomingSession: AudiobookSessionState; incomingSessionTimestamp: number } | null => {
  if (!rawSession) {
    return null
  }

  try {
    const incomingSession = JSON.parse(rawSession) as AudiobookSessionState
    if (incomingSession.projectId !== selectedProjectId) {
      return null
    }
    if (incomingSession.writerTabId && incomingSession.writerTabId === writerTabId) {
      return null
    }

    const incomingSessionTimestamp = parseSessionTimestamp(incomingSession.updatedAt)
    if (incomingSessionTimestamp > 0 && incomingSessionTimestamp < lastSessionTimestamp) {
      return null
    }

    return {
      incomingSession,
      incomingSessionTimestamp,
    }
  } catch {
    return null
  }
}

export const buildIncomingAudiobookTaskSessionUpdate = ({
  incomingSession,
  chapters,
}: {
  incomingSession: AudiobookSessionState
  chapters: Chapter[]
}): IncomingAudiobookTaskSessionUpdate => {
  const {
    activeTasks: incomingActiveTasks,
    taskId: incomingTaskId,
    audiobookProjectId: incomingAudiobookProjectId,
  } = resolveAudiobookSessionTaskFocus(incomingSession)
  const chapterIds = chapters.map((chapter) => chapter.id)
  const normalizedChapterIds = normalizeSelectedChapterIds(incomingSession.selectedChapterIds, {
    allowedIds: chapterIds,
    fallbackIds: chapterIds,
  })

  return {
    incomingActiveTasks,
    incomingTaskId,
    incomingAudiobookProjectId,
    normalizedChapterIds,
    hasSelectedChapterIds: Array.isArray(incomingSession.selectedChapterIds),
    incomingActiveStep: typeof incomingSession.activeStep === 'number' ? incomingSession.activeStep : null,
    incomingGenerating:
      incomingTaskId || incomingActiveTasks.length > 0
        ? (incomingSession.generating ?? true)
        : false,
    incomingTtsModel: normalizeTtsModelValue(incomingSession.ttsModel),
  }
}

export const mergePendingTaskStatuses = (
  taskStatuses: Record<string, TaskStatus>,
  incomingActiveTasks: Array<{ taskId: string; audiobookProjectId: number }>,
): Record<string, TaskStatus> => {
  let next: Record<string, TaskStatus> | null = null

  for (const taskRef of incomingActiveTasks) {
    if (taskStatuses[taskRef.taskId]) {
      continue
    }

    next ??= { ...taskStatuses }
    next[taskRef.taskId] = buildPendingTaskStatus({
      taskId: taskRef.taskId,
      audiobookProjectId: taskRef.audiobookProjectId,
    })
  }

  return next ?? taskStatuses
}
