import { AUDIOBOOK_SESSION_STORAGE_KEY } from './utils'
import { parseSessionTimestamp } from './editorSessionUtils'
import {
  normalizeSelectedChapterIds,
  resolveAudiobookSessionTaskFocus,
  type AudiobookSessionState,
} from './sessionUtils'
import { normalizeTtsModelValue } from './ttsModels'
import type { AudiobookEditorSessionState, AudiobookPageSessionState, NavigationType, TtsModel } from './types'

type RouteSessionStorage = Pick<Storage, 'getItem' | 'removeItem'>

export interface RestoredAudiobookRouteSessionState {
  savedSession: AudiobookSessionState | null
  restoredTtsModel: TtsModel
  restoredSelectedChapterIds: number[]
  restoredActiveTasks: Array<{ taskId: string; audiobookProjectId: number }>
  restoredTaskId: string | null
  restoredAudiobookProjectId: number | null
  lastSessionTimestamp: number
}

const readJsonRecord = <TValue,>(
  storage: RouteSessionStorage,
  storageKey: string,
): TValue | null => {
  let raw: string | null = null
  try {
    raw = storage.getItem(storageKey)
  } catch {
    return null
  }

  if (!raw) {
    return null
  }

  try {
    return JSON.parse(raw) as TValue
  } catch {
    try {
      storage.removeItem(storageKey)
    } catch {
      // 忽略不可用 storage 的清理失败
    }
    return null
  }
}

const removeStoredRouteSession = (
  storage: RouteSessionStorage,
  storageKey: string,
) => {
  try {
    storage.removeItem(storageKey)
  } catch {
    // 忽略不可用 storage 的清理失败
  }
}

export const shouldRestoreAudiobookRouteSession = ({
  navigationType,
  samePathReferrer,
}: {
  navigationType: NavigationType
  samePathReferrer: boolean
}): boolean =>
  navigationType === 'reload' || navigationType === 'back_forward' || samePathReferrer

export const readMatchingAudiobookSession = ({
  storage,
  routeProjectId,
  storageKey = AUDIOBOOK_SESSION_STORAGE_KEY,
}: {
  storage: RouteSessionStorage
  routeProjectId: number
  storageKey?: string
}): AudiobookSessionState | null => {
  const saved = readJsonRecord<AudiobookSessionState>(storage, storageKey)
  if (!saved) {
    return null
  }

  if (saved.projectId !== routeProjectId) {
    removeStoredRouteSession(storage, storageKey)
    return null
  }

  return saved
}

export const removeStoredSessionWhenProjectMismatch = ({
  storage,
  storageKey,
  routeProjectId,
}: {
  storage: RouteSessionStorage
  storageKey: string
  routeProjectId: number
}): void => {
  const saved = readJsonRecord<AudiobookEditorSessionState | AudiobookPageSessionState>(storage, storageKey)
  if (saved && saved.projectId !== routeProjectId) {
    removeStoredRouteSession(storage, storageKey)
  }
}

export const removeStoredTaskSessionForAudiobookProject = ({
  storage,
  audiobookProjectId,
  storageKey = AUDIOBOOK_SESSION_STORAGE_KEY,
}: {
  storage: RouteSessionStorage
  audiobookProjectId: number
  storageKey?: string
}): void => {
  const saved = readJsonRecord<AudiobookSessionState>(storage, storageKey)
  if (!saved) {
    return
  }

  const referencesDeletedProject = (
    saved.audiobookProjectId === audiobookProjectId
    || (saved.activeTasks || []).some((task) => task.audiobookProjectId === audiobookProjectId)
  )
  if (referencesDeletedProject) {
    removeStoredRouteSession(storage, storageKey)
  }
}

export const clearAudiobookRouteSessionStorage = ({
  localStorageRef,
  sessionStorageRef,
  editorSessionStorageKey,
  pageSessionStorageKey,
}: {
  localStorageRef: RouteSessionStorage
  sessionStorageRef: RouteSessionStorage
  editorSessionStorageKey: string
  pageSessionStorageKey: string
}) => {
  removeStoredRouteSession(localStorageRef, AUDIOBOOK_SESSION_STORAGE_KEY)
  removeStoredRouteSession(sessionStorageRef, editorSessionStorageKey)
  removeStoredRouteSession(sessionStorageRef, pageSessionStorageKey)
}

export const buildRestoredAudiobookRouteSessionState = ({
  savedSession,
  fallbackTtsModel,
}: {
  savedSession: AudiobookSessionState | null
  fallbackTtsModel: TtsModel
}): RestoredAudiobookRouteSessionState => {
  const restoredTtsModel = normalizeTtsModelValue(savedSession?.ttsModel) || fallbackTtsModel
  const restoredSelectedChapterIds = normalizeSelectedChapterIds(savedSession?.selectedChapterIds)
  const {
    activeTasks: restoredActiveTasks,
    taskId: restoredTaskId,
    audiobookProjectId: restoredAudiobookProjectId,
  } = resolveAudiobookSessionTaskFocus(savedSession)

  return {
    savedSession,
    restoredTtsModel,
    restoredSelectedChapterIds,
    restoredActiveTasks,
    restoredTaskId,
    restoredAudiobookProjectId,
    lastSessionTimestamp: parseSessionTimestamp(savedSession?.updatedAt),
  }
}
