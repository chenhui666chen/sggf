import { describe, expect, it } from 'vitest'

import { buildComparableAudiobookPageSessionPayload } from '../pageSessionUtils'
import {
  buildStoredComparableAudiobookPageSessionPayload,
  readStoredAudiobookPageSession,
  removeStoredAudiobookPageSession,
  writeStoredAudiobookPageSession,
} from '../pageSessionStorageUtils'

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

describe('audiobook page session storage utils', () => {
  it('reads normalized page session entries from storage', () => {
    const storage = new MemoryStorage()
    storage.setItem('page', JSON.stringify({
      projectId: '12',
      showHistory: true,
      designPreviewText: '自定义试听',
    }))

    const entry = readStoredAudiobookPageSession(storage, 'page')

    expect(entry.hasStoredPayload).toBe(true)
    expect(entry.session).toMatchObject({
      projectId: 12,
      showHistory: true,
      designPreviewText: '自定义试听',
    })
  })

  it('distinguishes missing payloads from malformed stored payloads', () => {
    const storage = new MemoryStorage()

    expect(readStoredAudiobookPageSession(storage, 'page')).toEqual({
      hasStoredPayload: false,
      session: null,
    })

    storage.setItem('page', '{bad-json')
    expect(readStoredAudiobookPageSession(storage, 'page')).toEqual({
      hasStoredPayload: true,
      session: null,
    })
    expect(storage.getItem('page')).toBeNull()
  })

  it('builds comparable stored payloads without volatile fields', () => {
    const storage = new MemoryStorage()
    storage.setItem('page', JSON.stringify({
      projectId: 7,
      showHistory: true,
      updatedAt: '2026-05-01T01:00:00.000Z',
    }))

    expect(buildStoredComparableAudiobookPageSessionPayload(storage, 'page')).toBe(
      JSON.stringify(buildComparableAudiobookPageSessionPayload({
        projectId: 7,
        showHistory: true,
      })),
    )
  })

  it('writes and removes stored page sessions safely', () => {
    const storage = new MemoryStorage()
    const payload = buildComparableAudiobookPageSessionPayload({
      projectId: 7,
      showHistory: true,
    })

    writeStoredAudiobookPageSession(storage, 'page', payload, '2026-05-01T01:00:00.000Z')

    expect(JSON.parse(storage.getItem('page') || '{}')).toMatchObject({
      projectId: 7,
      showHistory: true,
      updatedAt: '2026-05-01T01:00:00.000Z',
    })

    removeStoredAudiobookPageSession(storage, 'page')
    expect(storage.getItem('page')).toBeNull()
  })
})
