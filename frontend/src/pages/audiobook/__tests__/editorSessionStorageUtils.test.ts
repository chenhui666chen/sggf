import { describe, expect, it } from 'vitest'

import type { AudiobookEditorSessionState } from '../types'
import {
  readStoredAudiobookEditorSession,
  readStoredAudiobookEditorSyncEntries,
  removeStoredAudiobookEditorSession,
  shouldPersistStoredAudiobookEditorSession,
  writeStoredAudiobookEditorSession,
  writeStoredAudiobookEditorSyncEntries,
} from '../editorSessionStorageUtils'

class MemoryStorage implements Pick<Storage, 'getItem' | 'removeItem' | 'setItem'> {
  private readonly values = new Map<string, string>()

  getItem(key: string) {
    return this.values.get(key) ?? null
  }

  removeItem(key: string) {
    this.values.delete(key)
  }

  setItem(key: string, value: string) {
    this.values.set(key, value)
  }
}

class ThrowingStorage implements Pick<Storage, 'getItem' | 'removeItem' | 'setItem'> {
  getItem(_key: string): string | null {
    throw new Error('storage unavailable')
  }

  removeItem(_key: string): void {
    throw new Error('storage unavailable')
  }

  setItem(_key: string, _value: string): void {
    throw new Error('storage unavailable')
  }
}

const buildEditorSession = (
  patch: Partial<AudiobookEditorSessionState> = {},
): AudiobookEditorSessionState => ({
  projectId: 1,
  audiobookProjectId: 2,
  chapterId: 3,
  reviewMode: false,
  openSegmentDetailIndices: [],
  segmentReviews: {},
  data: {
    scriptStatus: 'generated',
    scriptSegments: [{ text: '旁白文本' }],
    scriptReview: null,
  },
  writerTabId: 'tab-a',
  updatedAt: new Date().toISOString(),
  ...patch,
})

describe('audiobook editor session storage utils', () => {
  it('reads normalized editor session drafts and clears invalid payloads', () => {
    const storage = new MemoryStorage()
    storage.setItem('session', JSON.stringify(buildEditorSession({
      projectId: '1' as never,
      audiobookProjectId: '2' as never,
      chapterId: '3' as never,
    })))

    expect(readStoredAudiobookEditorSession(storage, 'session')).toMatchObject({
      hasStoredPayload: true,
      session: {
        projectId: 1,
        audiobookProjectId: 2,
        chapterId: 3,
      },
    })

    storage.setItem('session', '{bad-json')
    expect(readStoredAudiobookEditorSession(storage, 'session')).toEqual({
      hasStoredPayload: true,
      session: null,
    })
    expect(storage.getItem('session')).toBeNull()

    storage.setItem('session', 'null')
    expect(readStoredAudiobookEditorSession(storage, 'session')).toEqual({
      hasStoredPayload: true,
      session: null,
    })
    expect(storage.getItem('session')).toBeNull()

    expect(readStoredAudiobookEditorSession(new ThrowingStorage(), 'session')).toEqual({
      hasStoredPayload: false,
      session: null,
    })
  })

  it('writes and reads pruned editor sync entries', () => {
    const storage = new MemoryStorage()
    const fresh = buildEditorSession({ writerTabId: 'fresh-tab' })
    const stale = buildEditorSession({
      writerTabId: 'stale-tab',
      updatedAt: '2000-01-01T00:00:00.000Z',
    })

    writeStoredAudiobookEditorSyncEntries(storage, 'sync', {
      fresh: fresh,
      stale: stale,
    })

    const result = readStoredAudiobookEditorSyncEntries(storage, 'sync')

    expect(Object.keys(result.entries)).toEqual(['fresh'])
    expect(result.pruned).toBe(false)
    expect(result.entries.fresh.writerTabId).toBe('fresh-tab')
  })

  it('detects pruned sync entries when reading an existing registry', () => {
    const storage = new MemoryStorage()
    storage.setItem('sync', JSON.stringify({
      entries: {
        stale: buildEditorSession({
          writerTabId: 'stale-tab',
          updatedAt: '2000-01-01T00:00:00.000Z',
        }),
      },
    }))

    const result = readStoredAudiobookEditorSyncEntries(storage, 'sync')

    expect(result.entries).toEqual({})
    expect(result.pruned).toBe(true)
  })

  it('removes the sync registry when no valid entries remain', () => {
    const storage = new MemoryStorage()

    writeStoredAudiobookEditorSyncEntries(storage, 'sync', {})

    expect(storage.getItem('sync')).toBeNull()
  })

  it('decides whether editor sessions need persistence by comparable fields', () => {
    const storage = new MemoryStorage()
    const payload = buildEditorSession({
      updatedAt: undefined,
      writerTabId: undefined,
    })

    expect(shouldPersistStoredAudiobookEditorSession(storage, 'session', payload)).toBe(true)

    storage.setItem('session', JSON.stringify({
      ...payload,
      updatedAt: '2026-05-01T00:00:00.000Z',
      writerTabId: 'other-tab',
    }))

    expect(shouldPersistStoredAudiobookEditorSession(storage, 'session', payload)).toBe(false)
    expect(shouldPersistStoredAudiobookEditorSession(storage, 'session', {
      ...payload,
      reviewMode: true,
    })).toBe(true)
  })

  it('writes and removes editor session drafts', () => {
    const storage = new MemoryStorage()
    const payload = buildEditorSession({
      updatedAt: undefined,
      writerTabId: undefined,
    })

    writeStoredAudiobookEditorSession(storage, 'session', payload, '2026-05-01T00:00:00.000Z')

    expect(JSON.parse(storage.getItem('session') || '{}')).toMatchObject({
      projectId: 1,
      audiobookProjectId: 2,
      chapterId: 3,
      updatedAt: '2026-05-01T00:00:00.000Z',
    })

    removeStoredAudiobookEditorSession(storage, 'session')
    expect(storage.getItem('session')).toBeNull()
  })
})
