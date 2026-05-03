import type {
  AudiobookEditorSessionState,
  AudiobookEditorSyncRegistry,
} from './types'
import {
  areAudiobookEditorSessionsEquivalent,
  normalizeAudiobookEditorSessionState,
  normalizeAudiobookEditorSyncRegistry,
  pruneAudiobookEditorSyncEntries,
} from './editorSessionUtils'

type AudiobookEditorSessionStorage = Pick<Storage, 'getItem' | 'removeItem' | 'setItem'>

interface StoredAudiobookEditorSessionEntry {
  hasStoredPayload: boolean
  session: AudiobookEditorSessionState | null
}

export const readStoredAudiobookEditorSession = (
  storage: AudiobookEditorSessionStorage,
  storageKey: string,
): StoredAudiobookEditorSessionEntry => {
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
    const session = normalizeAudiobookEditorSessionState(
      JSON.parse(raw) as AudiobookEditorSessionState,
    )
    if (!session) {
      removeStoredAudiobookEditorSession(storage, storageKey)
    }

    return {
      hasStoredPayload: true,
      session,
    }
  } catch {
    removeStoredAudiobookEditorSession(storage, storageKey)
    return { hasStoredPayload: true, session: null }
  }
}

export const writeStoredAudiobookEditorSyncEntries = (
  storage: AudiobookEditorSessionStorage,
  storageKey: string,
  entries: Record<string, AudiobookEditorSessionState>,
) => {
  const nextEntries = pruneAudiobookEditorSyncEntries(entries)
  if (Object.keys(nextEntries).length === 0) {
    storage.removeItem(storageKey)
    return nextEntries
  }

  storage.setItem(
    storageKey,
    JSON.stringify({ entries: nextEntries } satisfies AudiobookEditorSyncRegistry),
  )
  return nextEntries
}

export const readStoredAudiobookEditorSyncEntries = (
  storage: AudiobookEditorSessionStorage,
  storageKey: string,
  rawRegistry?: string | null,
) => {
  const serializedRegistry = rawRegistry ?? storage.getItem(storageKey)
  if (!serializedRegistry) {
    return {
      entries: {},
      pruned: false,
    }
  }

  const currentEntries = normalizeAudiobookEditorSyncRegistry(
    JSON.parse(serializedRegistry) as AudiobookEditorSyncRegistry,
  )
  const entries = pruneAudiobookEditorSyncEntries(currentEntries)

  return {
    entries,
    pruned: Object.keys(entries).length !== Object.keys(currentEntries).length,
  }
}

export const removeStoredAudiobookEditorSession = (
  storage: AudiobookEditorSessionStorage,
  storageKey: string,
) => {
  try {
    storage.removeItem(storageKey)
  } catch {
    // sessionStorage 不可用时忽略编辑器草稿清理失败。
  }
}

export const shouldPersistStoredAudiobookEditorSession = (
  storage: AudiobookEditorSessionStorage,
  storageKey: string,
  editorSessionPayload: AudiobookEditorSessionState,
): boolean => {
  const currentStoredPayload = storage.getItem(storageKey)
  if (!currentStoredPayload) {
    return true
  }

  try {
    return !areAudiobookEditorSessionsEquivalent(
      JSON.parse(currentStoredPayload) as AudiobookEditorSessionState,
      editorSessionPayload,
    )
  } catch {
    return true
  }
}

export const writeStoredAudiobookEditorSession = (
  storage: AudiobookEditorSessionStorage,
  storageKey: string,
  editorSessionPayload: AudiobookEditorSessionState,
  updatedAt = new Date().toISOString(),
) => {
  storage.setItem(
    storageKey,
    JSON.stringify({
      ...editorSessionPayload,
      updatedAt,
    } satisfies AudiobookEditorSessionState),
  )
}
