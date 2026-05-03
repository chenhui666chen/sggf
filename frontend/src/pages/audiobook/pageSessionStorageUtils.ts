import type { AudiobookPageSessionState } from './types'
import {
  buildComparableAudiobookPageSessionPayload,
  normalizeAudiobookPageSessionState,
} from './pageSessionUtils'

type AudiobookPageSessionStorage = Pick<Storage, 'getItem' | 'removeItem' | 'setItem'>

interface StoredAudiobookPageSessionEntry {
  hasStoredPayload: boolean
  session: AudiobookPageSessionState | null
}

export const readStoredAudiobookPageSession = (
  storage: AudiobookPageSessionStorage,
  storageKey: string,
): StoredAudiobookPageSessionEntry => {
  let raw: string | null = null
  try {
    raw = storage.getItem(storageKey)
  } catch {
    return { hasStoredPayload: false, session: null }
  }

  if (!raw) {
    return { hasStoredPayload: false, session: null }
  }

  try {
    return {
      hasStoredPayload: true,
      session: normalizeAudiobookPageSessionState(
        JSON.parse(raw) as AudiobookPageSessionState,
      ),
    }
  } catch {
    removeStoredAudiobookPageSession(storage, storageKey)
    return { hasStoredPayload: true, session: null }
  }
}

export const removeStoredAudiobookPageSession = (
  storage: AudiobookPageSessionStorage,
  storageKey: string,
) => {
  try {
    storage.removeItem(storageKey)
  } catch {
    // sessionStorage 不可用时忽略页面级 UI 状态清理
  }
}

export const buildStoredComparableAudiobookPageSessionPayload = (
  storage: AudiobookPageSessionStorage,
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
      buildComparableAudiobookPageSessionPayload(
        JSON.parse(currentStoredPayload) as AudiobookPageSessionState,
      ),
    )
  } catch {
    return null
  }
}

export const writeStoredAudiobookPageSession = (
  storage: AudiobookPageSessionStorage,
  storageKey: string,
  comparablePayload: ReturnType<typeof buildComparableAudiobookPageSessionPayload>,
  updatedAt = new Date().toISOString(),
) => {
  try {
    storage.setItem(
      storageKey,
      JSON.stringify({
        ...comparablePayload,
        updatedAt,
      } satisfies AudiobookPageSessionState),
    )
  } catch {
    // sessionStorage 不可用或容量不足时忽略页面级 UI 状态持久化
  }
}
