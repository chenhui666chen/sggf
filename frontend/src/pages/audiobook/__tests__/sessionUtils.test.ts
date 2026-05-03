import { describe, expect, it } from 'vitest'

import {
  buildComparableAudiobookSessionPayload,
  createEphemeralAudiobookSessionId,
  dedupeSessionTaskRefs,
  getOrCreateAudiobookSessionTabId,
  normalizeSelectedChapterIds,
  resolveAudiobookSessionTaskFocus,
} from '../sessionUtils'
import type { TtsModel } from '../types'

describe('audiobook active session utils', () => {
  it('creates a usable tab id outside browser session storage', () => {
    expect(createEphemeralAudiobookSessionId().length).toBeGreaterThan(0)
    expect(getOrCreateAudiobookSessionTabId().length).toBeGreaterThan(0)
  })

  it('dedupes task refs and filters invalid values', () => {
    expect(dedupeSessionTaskRefs([
      { taskId: ' task-a ', audiobookProjectId: 2 },
      { taskId: 'task-a', audiobookProjectId: 3 },
      { taskId: '', audiobookProjectId: 4 },
      { taskId: 'task-b', audiobookProjectId: 0 },
      { taskId: 'task-c', audiobookProjectId: 5 },
    ])).toEqual([
      { taskId: 'task-a', audiobookProjectId: 2 },
      { taskId: 'task-c', audiobookProjectId: 5 },
    ])
  })

  it('normalizes selected chapter ids with optional allow list and fallback', () => {
    expect(normalizeSelectedChapterIds([3, '2', 3, 0, 'bad'], {
      allowedIds: [2, 4],
      fallbackIds: [9],
    })).toEqual([2])

    expect(normalizeSelectedChapterIds(['bad'], {
      allowedIds: [2],
      fallbackIds: [9],
    })).toEqual([9])
  })

  it('resolves focused task and audiobook project from active task refs', () => {
    expect(resolveAudiobookSessionTaskFocus({
      taskId: 'task-b',
      activeTasks: [
        { taskId: 'task-a', audiobookProjectId: 1 },
        { taskId: 'task-b', audiobookProjectId: 2 },
      ],
    })).toEqual({
      activeTasks: [
        { taskId: 'task-a', audiobookProjectId: 1 },
        { taskId: 'task-b', audiobookProjectId: 2 },
      ],
      taskId: 'task-b',
      audiobookProjectId: 2,
    })

    expect(resolveAudiobookSessionTaskFocus({
      audiobookProjectId: 8,
      activeTasks: [{ taskId: 'task-a', audiobookProjectId: 1 }],
    })).toMatchObject({
      taskId: 'task-a',
      audiobookProjectId: 8,
    })
  })

  it('builds comparable active session payloads without volatile fields', () => {
    expect(buildComparableAudiobookSessionPayload({
      projectId: '11' as unknown as number,
      audiobookProjectId: 22,
      taskId: ' task-a ',
      activeTasks: [
        { taskId: ' task-a ', audiobookProjectId: 22 },
        { taskId: 'task-a', audiobookProjectId: 22 },
        { taskId: 'task-b', audiobookProjectId: 23 },
      ],
      selectedChapterIds: [3, '2', 3] as unknown as number[],
      activeStep: 1,
      generating: true,
      ttsModel: 'qwen3-tts' as TtsModel,
      updatedAt: '2026-04-30T12:00:00.000Z',
      writerTabId: 'tab-a',
    })).toEqual({
      projectId: 11,
      audiobookProjectId: 22,
      taskId: 'task-a',
      activeTasks: [
        { taskId: 'task-a', audiobookProjectId: 22 },
        { taskId: 'task-b', audiobookProjectId: 23 },
      ],
      selectedChapterIds: [3, 2],
      activeStep: 1,
      generating: true,
      ttsModel: 'qwen3-tts-instruct-flash',
    })
  })
})
