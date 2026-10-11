import { describe, expect, it } from 'vitest'

import {
  buildRestoredAudiobookRouteSessionState,
  clearAudiobookRouteSessionStorage,
  readMatchingAudiobookSession,
  removeStoredSessionWhenProjectMismatch,
  removeStoredTaskSessionForAudiobookProject,
  shouldRestoreAudiobookRouteSession,
} from '../routeProjectSessionUtils'
import { AUDIOBOOK_SESSION_STORAGE_KEY } from '../utils'

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

describe('audiobook route project session utils', () => {
  it('decides whether route session state should be restored', () => {
    expect(shouldRestoreAudiobookRouteSession({
      navigationType: 'reload',
      samePathReferrer: false,
    })).toBe(true)
    expect(shouldRestoreAudiobookRouteSession({
      navigationType: 'back_forward',
      samePathReferrer: false,
    })).toBe(true)
    expect(shouldRestoreAudiobookRouteSession({
      navigationType: 'navigate',
      samePathReferrer: true,
    })).toBe(true)
    expect(shouldRestoreAudiobookRouteSession({
      navigationType: 'navigate',
      samePathReferrer: false,
    })).toBe(false)
  })

  it('reads only matching active audiobook sessions', () => {
    const storage = new MemoryStorage()
    storage.setItem(AUDIOBOOK_SESSION_STORAGE_KEY, JSON.stringify({
      projectId: 8,
      taskId: 'task-a',
    }))

    expect(readMatchingAudiobookSession({
      storage,
      routeProjectId: 8,
    })).toMatchObject({
      projectId: 8,
      taskId: 'task-a',
    })

    expect(readMatchingAudiobookSession({
      storage,
      routeProjectId: 9,
    })).toBeNull()
    expect(storage.getItem(AUDIOBOOK_SESSION_STORAGE_KEY)).toBeNull()
  })

  it('removes malformed or mismatched editor/page sessions', () => {
    const storage = new MemoryStorage()
    storage.setItem('editor', JSON.stringify({ projectId: 3 }))
    storage.setItem('page', '{bad-json')

    removeStoredSessionWhenProjectMismatch({
      storage,
      storageKey: 'editor',
      routeProjectId: 4,
    })
    removeStoredSessionWhenProjectMismatch({
      storage,
      storageKey: 'page',
      routeProjectId: 4,
    })

    expect(storage.getItem('editor')).toBeNull()
    expect(storage.getItem('page')).toBeNull()
  })

  it('clears all route-scoped session stores', () => {
    const local = new MemoryStorage()
    const session = new MemoryStorage()
    local.setItem(AUDIOBOOK_SESSION_STORAGE_KEY, '{}')
    session.setItem('editor', '{}')
    session.setItem('page', '{}')

    clearAudiobookRouteSessionStorage({
      localStorageRef: local,
      sessionStorageRef: session,
      editorSessionStorageKey: 'editor',
      pageSessionStorageKey: 'page',
    })

    expect(local.getItem(AUDIOBOOK_SESSION_STORAGE_KEY)).toBeNull()
    expect(session.getItem('editor')).toBeNull()
    expect(session.getItem('page')).toBeNull()
  })

  it('builds restored route session state from the saved session', () => {
    const restored = buildRestoredAudiobookRouteSessionState({
      fallbackTtsModel: 'cosyvoice-v3.5-plus',
      savedSession: {
        ttsModel: 'qwen3-tts-plus' as never,
        selectedChapterIds: [3, '2' as never, 3],
        activeTasks: [
          { taskId: ' task-a ', audiobookProjectId: 10 },
          { taskId: 'task-a', audiobookProjectId: 10 },
          { taskId: 'task-b', audiobookProjectId: 11 },
        ],
        taskId: 'task-b',
        updatedAt: '2026-05-01T08:00:00.000Z',
      },
    })

    expect(restored).toMatchObject({
      restoredTtsModel: 'qwen-audio-3.1-tts-flash',
      restoredSelectedChapterIds: [3, 2],
      restoredActiveTasks: [
        { taskId: 'task-a', audiobookProjectId: 10 },
        { taskId: 'task-b', audiobookProjectId: 11 },
      ],
      restoredTaskId: 'task-b',
      restoredAudiobookProjectId: 11,
      lastSessionTimestamp: Date.parse('2026-05-01T08:00:00.000Z'),
    })
  })

  it('removes the stored task session when it references the deleted audiobook project', () => {
    const storage = new MemoryStorage()
    storage.setItem(AUDIOBOOK_SESSION_STORAGE_KEY, JSON.stringify({
      projectId: 8,
      audiobookProjectId: 25,
      activeStep: 3,
    }))

    removeStoredTaskSessionForAudiobookProject({ storage, audiobookProjectId: 25 })

    expect(storage.getItem(AUDIOBOOK_SESSION_STORAGE_KEY)).toBeNull()
  })

  it('removes the stored task session when an active task references the deleted audiobook project', () => {
    const storage = new MemoryStorage()
    storage.setItem(AUDIOBOOK_SESSION_STORAGE_KEY, JSON.stringify({
      projectId: 8,
      audiobookProjectId: 30,
      activeStep: 2,
      activeTasks: [{ taskId: 'task-x', audiobookProjectId: 25 }],
    }))

    removeStoredTaskSessionForAudiobookProject({ storage, audiobookProjectId: 25 })

    expect(storage.getItem(AUDIOBOOK_SESSION_STORAGE_KEY)).toBeNull()
  })

  it('keeps the stored task session when it does not reference the deleted audiobook project', () => {
    const storage = new MemoryStorage()
    const payload = JSON.stringify({
      projectId: 8,
      audiobookProjectId: 30,
      activeStep: 2,
    })
    storage.setItem(AUDIOBOOK_SESSION_STORAGE_KEY, payload)

    removeStoredTaskSessionForAudiobookProject({ storage, audiobookProjectId: 25 })

    expect(storage.getItem(AUDIOBOOK_SESSION_STORAGE_KEY)).toBe(payload)
  })
})
