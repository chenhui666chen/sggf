import { describe, expect, it } from 'vitest'

import {
  buildAudiobookTaskSessionPayload,
  buildIncomingAudiobookTaskSessionUpdate,
  mergePendingTaskStatuses,
  readIncomingAudiobookTaskSession,
  removeStoredAudiobookTaskSession,
  shouldClearAudiobookTaskSession,
  shouldWriteAudiobookTaskSession,
  writeStoredAudiobookTaskSession,
} from '../taskSessionStorageUtils'
import type { Chapter } from '../types'
import { buildPendingTaskStatus } from '../utils'

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

const chapters: Chapter[] = [
  { id: 1, chapter_number: 1, title: '第一章', content: '内容一' },
  { id: 2, chapter_number: 2, title: '第二章', content: '内容二' },
]

describe('audiobook task session storage utils', () => {
  it('decides when the active task session should be cleared', () => {
    expect(shouldClearAudiobookTaskSession({
      selectedProjectId: null,
      currentAudiobookProjectId: null,
      currentTaskId: null,
    })).toBe(true)

    expect(shouldClearAudiobookTaskSession({
      selectedProjectId: 1,
      currentAudiobookProjectId: null,
      currentTaskId: null,
    })).toBe(false)
    expect(shouldClearAudiobookTaskSession({
      selectedProjectId: null,
      currentAudiobookProjectId: 2,
      currentTaskId: null,
    })).toBe(false)
    expect(shouldClearAudiobookTaskSession({
      selectedProjectId: null,
      currentAudiobookProjectId: null,
      currentTaskId: 'task-a',
    })).toBe(false)
  })

  it('builds normalized task session payloads with writer metadata', () => {
    expect(buildAudiobookTaskSessionPayload({
      projectId: 8,
      audiobookProjectId: 18,
      taskId: ' task-a ',
      activeTasks: [
        { taskId: ' task-a ', audiobookProjectId: 18 },
        { taskId: 'task-a', audiobookProjectId: 19 },
      ],
      selectedChapterIds: [2, '1' as never, 2],
      activeStep: 2,
      generating: true,
      ttsModel: 'qwen3-tts-plus' as never,
      updatedAt: '2026-05-02T08:00:00.000Z',
      writerTabId: 'tab-a',
    })).toEqual({
      projectId: 8,
      audiobookProjectId: 18,
      taskId: 'task-a',
      activeTasks: [{ taskId: 'task-a', audiobookProjectId: 18 }],
      selectedChapterIds: [2, 1],
      activeStep: 2,
      generating: true,
      ttsModel: 'qwen-audio-3.1-tts-flash',
      updatedAt: '2026-05-02T08:00:00.000Z',
      writerTabId: 'tab-a',
    })
  })

  it('skips writes when only volatile task session fields changed', () => {
    const storage = new MemoryStorage()
    const storageKey = 'task-session'
    storage.setItem(storageKey, JSON.stringify(buildAudiobookTaskSessionPayload({
      projectId: 8,
      audiobookProjectId: 18,
      taskId: 'task-a',
      activeTasks: [{ taskId: 'task-a', audiobookProjectId: 18 }],
      selectedChapterIds: [1, 2],
      activeStep: 1,
      generating: true,
      ttsModel: 'qwen-audio-3.1-tts-flash',
      updatedAt: '2026-05-02T08:00:00.000Z',
      writerTabId: 'tab-a',
    })))

    expect(shouldWriteAudiobookTaskSession(storage, storageKey, buildAudiobookTaskSessionPayload({
      projectId: 8,
      audiobookProjectId: 18,
      taskId: 'task-a',
      activeTasks: [{ taskId: 'task-a', audiobookProjectId: 18 }],
      selectedChapterIds: [1, 2],
      activeStep: 1,
      generating: true,
      ttsModel: 'qwen-audio-3.1-tts-flash',
      updatedAt: '2026-05-02T09:00:00.000Z',
      writerTabId: 'tab-b',
    }))).toBe(false)
  })

  it('writes changed or malformed task sessions and ignores storage failures', () => {
    const storage = new MemoryStorage()
    const storageKey = 'task-session'
    const payload = buildAudiobookTaskSessionPayload({
      projectId: 8,
      audiobookProjectId: 18,
      taskId: 'task-a',
      activeTasks: [{ taskId: 'task-a', audiobookProjectId: 18 }],
      selectedChapterIds: [1],
      activeStep: 1,
      generating: true,
      ttsModel: 'qwen-audio-3.1-tts-flash',
      updatedAt: '2026-05-02T08:00:00.000Z',
      writerTabId: 'tab-a',
    })

    expect(shouldWriteAudiobookTaskSession(storage, storageKey, payload)).toBe(true)
    expect(writeStoredAudiobookTaskSession(storage, storageKey, payload)).toBe(true)
    expect(JSON.parse(storage.getItem(storageKey) || '{}')).toMatchObject({
      projectId: 8,
      taskId: 'task-a',
    })

    storage.setItem(storageKey, '{bad-json')
    expect(shouldWriteAudiobookTaskSession(storage, storageKey, payload)).toBe(true)

    expect(writeStoredAudiobookTaskSession(new ThrowingStorage(), storageKey, payload)).toBe(false)
    removeStoredAudiobookTaskSession(new ThrowingStorage(), storageKey)
  })

  it('filters incoming task sessions from unrelated, same-tab, old, or malformed updates', () => {
    const latest = '2026-05-02T08:00:00.000Z'
    const older = '2026-05-02T07:00:00.000Z'
    const raw = JSON.stringify({
      projectId: 8,
      taskId: 'task-a',
      updatedAt: latest,
      writerTabId: 'tab-b',
    })

    expect(readIncomingAudiobookTaskSession({
      rawSession: raw,
      selectedProjectId: 8,
      writerTabId: 'tab-a',
      lastSessionTimestamp: Date.parse(older),
    })).toMatchObject({
      incomingSessionTimestamp: Date.parse(latest),
      incomingSession: { taskId: 'task-a' },
    })

    expect(readIncomingAudiobookTaskSession({
      rawSession: null,
      selectedProjectId: 8,
      writerTabId: 'tab-a',
      lastSessionTimestamp: 0,
    })).toBeNull()
    expect(readIncomingAudiobookTaskSession({
      rawSession: '{bad-json',
      selectedProjectId: 8,
      writerTabId: 'tab-a',
      lastSessionTimestamp: 0,
    })).toBeNull()
    expect(readIncomingAudiobookTaskSession({
      rawSession: JSON.stringify({ projectId: 9, updatedAt: latest, writerTabId: 'tab-b' }),
      selectedProjectId: 8,
      writerTabId: 'tab-a',
      lastSessionTimestamp: 0,
    })).toBeNull()
    expect(readIncomingAudiobookTaskSession({
      rawSession: JSON.stringify({ projectId: 8, updatedAt: latest, writerTabId: 'tab-a' }),
      selectedProjectId: 8,
      writerTabId: 'tab-a',
      lastSessionTimestamp: 0,
    })).toBeNull()
    expect(readIncomingAudiobookTaskSession({
      rawSession: JSON.stringify({ projectId: 8, updatedAt: older, writerTabId: 'tab-b' }),
      selectedProjectId: 8,
      writerTabId: 'tab-a',
      lastSessionTimestamp: Date.parse(latest),
    })).toBeNull()
  })

  it('builds incoming task session updates for UI state application', () => {
    expect(buildIncomingAudiobookTaskSessionUpdate({
      chapters,
      incomingSession: {
        selectedChapterIds: [2, 99, '1' as never],
        activeStep: 2,
        activeTasks: [
          { taskId: ' task-a ', audiobookProjectId: 18 },
          { taskId: 'task-a', audiobookProjectId: 18 },
        ],
        ttsModel: 'qwen3-tts-plus' as never,
      },
    })).toMatchObject({
      incomingActiveTasks: [{ taskId: 'task-a', audiobookProjectId: 18 }],
      incomingTaskId: 'task-a',
      incomingAudiobookProjectId: 18,
      normalizedChapterIds: [2, 1],
      hasSelectedChapterIds: true,
      incomingActiveStep: 2,
      incomingGenerating: true,
      incomingTtsModel: 'qwen-audio-3.1-tts-flash',
    })

    expect(buildIncomingAudiobookTaskSessionUpdate({
      chapters,
      incomingSession: {},
    })).toMatchObject({
      incomingActiveTasks: [],
      incomingTaskId: null,
      incomingAudiobookProjectId: null,
      normalizedChapterIds: [1, 2],
      hasSelectedChapterIds: false,
      incomingActiveStep: null,
      incomingGenerating: false,
      incomingTtsModel: null,
    })
  })

  it('merges missing pending task statuses while preserving existing task state', () => {
    const existingTask = buildPendingTaskStatus({
      taskId: 'task-a',
      audiobookProjectId: 18,
    })
    const taskStatuses = { 'task-a': existingTask }

    expect(mergePendingTaskStatuses(taskStatuses, [
      { taskId: 'task-a', audiobookProjectId: 18 },
    ])).toBe(taskStatuses)

    const merged = mergePendingTaskStatuses(taskStatuses, [
      { taskId: 'task-a', audiobookProjectId: 18 },
      { taskId: 'task-b', audiobookProjectId: 19 },
    ])

    expect(merged).not.toBe(taskStatuses)
    expect(merged['task-a']).toBe(existingTask)
    expect(merged['task-b']).toMatchObject({
      task_id: 'task-b',
      audiobook_project_id: 19,
      status: 'pending',
    })
  })
})
