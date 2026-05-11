import { describe, expect, it } from 'vitest'

import type { TaskStatus } from '../types'
import { createEmptyStageMap } from '../utils'
import {
  applyTaskProgressStreamPatch,
  canStartTaskProgressStream,
  consumeSseEventBuffer,
  hasReadableTaskProgressStreamResponse,
  shouldFallbackPollAfterStreamClose,
  type TaskProgressStreamEvent,
} from '../taskStreamPollingUtils'

const buildTask = (patch: Partial<TaskStatus> = {}): TaskStatus => ({
  task_id: 'task-1',
  audiobook_project_id: 1,
  status: 'pending',
  current_stage: 'queued',
  progress: 10,
  stages: createEmptyStageMap(),
  updated_at: '2026-05-05T00:00:00.000Z',
  ...patch,
})

describe('task stream polling utils', () => {
  it('parses complete SSE data blocks and keeps trailing partial data', () => {
    const events: TaskProgressStreamEvent[] = []
    const rest = consumeSseEventBuffer([
      'data: {"event":"connected","timestamp":"2026-05-05T01:00:00.000Z"}',
      '',
      'event: progress',
      'data: {"event":"progress","data":{"stage":"tts_synthesis","progress":42}}',
      '',
      'data: {"event":"progress"',
    ].join('\n'), (event) => {
      events.push(event)
    })

    expect(events).toEqual([
      {
        event: 'connected',
        data: undefined,
        timestamp: '2026-05-05T01:00:00.000Z',
      },
      {
        event: 'progress',
        data: {
          stage: 'tts_synthesis',
          progress: 42,
        },
        timestamp: undefined,
      },
    ])
    expect(rest).toBe('data: {"event":"progress"')
  })

  it('ignores malformed SSE JSON without dropping later valid events', () => {
    const events: TaskProgressStreamEvent[] = []
    const rest = consumeSseEventBuffer([
      'data: {bad-json}',
      '',
      'data: null',
      '',
      'data: {"event":"heartbeat"}',
      '',
      '',
    ].join('\n'), (event) => {
      events.push(event)
    })

    expect(events).toEqual([{ event: 'heartbeat', data: undefined, timestamp: undefined }])
    expect(rest).toBe('')
  })

  it('normalizes progress patches without moving progress backwards', () => {
    const patched = applyTaskProgressStreamPatch(buildTask(), {
      event: 'progress',
      data: {
        stage: 'tts_synthesis',
        progress: '40',
      },
      timestamp: '2026-05-05T01:00:00.000Z',
    })

    expect(patched).toMatchObject({
      status: 'running',
      current_stage: 'tts_synthesis',
      progress: 40,
      updated_at: '2026-05-05T01:00:00.000Z',
    })

    const monotonic = applyTaskProgressStreamPatch(buildTask({
      status: 'running',
      progress: 55,
    }), {
      event: 'progress',
      data: {
        progress: 20,
      },
    })

    expect(monotonic?.progress).toBe(55)
  })

  it('keeps the previous stage when a progress patch stage is blank', () => {
    const patched = applyTaskProgressStreamPatch(buildTask({
      status: 'running',
      current_stage: 'script_adaptation',
      progress: 30,
    }), {
      event: 'progress',
      data: {
        stage: '   ',
        progress: 31,
      },
      timestamp: '2026-05-05T01:01:00.000Z',
    })

    expect(patched).toMatchObject({
      current_stage: 'script_adaptation',
      progress: 31,
      updated_at: '2026-05-05T01:01:00.000Z',
    })
  })

  it('does not create a task update for irrelevant or empty stream events', () => {
    expect(applyTaskProgressStreamPatch(buildTask(), { event: 'heartbeat' })).toBeNull()
    expect(applyTaskProgressStreamPatch(buildTask(), {
      event: 'progress',
      data: {
        stage: '',
        progress: 'not-a-number',
      },
    })).toBeNull()
    expect(applyTaskProgressStreamPatch(null, {
      event: 'progress',
      data: {
        progress: 50,
      },
    })).toBeNull()
  })

  it('resolves stream fallback decisions from browser capability and response state', () => {
    expect(canStartTaskProgressStream({
      fetchAvailable: false,
      abortControllerAvailable: true,
    })).toBe(false)
    expect(canStartTaskProgressStream({
      fetchAvailable: true,
      abortControllerAvailable: false,
    })).toBe(false)
    expect(canStartTaskProgressStream({
      fetchAvailable: true,
      abortControllerAvailable: true,
    })).toBe(true)

    expect(hasReadableTaskProgressStreamResponse({
      ok: true,
      body: new ReadableStream<Uint8Array>(),
    })).toBe(true)
    expect(hasReadableTaskProgressStreamResponse({ ok: true, body: null })).toBe(false)
    expect(hasReadableTaskProgressStreamResponse({
      ok: false,
      body: new ReadableStream<Uint8Array>(),
    })).toBe(false)

    expect(shouldFallbackPollAfterStreamClose({
      cancelled: false,
      terminalHandled: false,
      hadConnectedStream: true,
    })).toBe(true)
    expect(shouldFallbackPollAfterStreamClose({
      cancelled: true,
      terminalHandled: false,
      hadConnectedStream: true,
    })).toBe(false)
    expect(shouldFallbackPollAfterStreamClose({
      cancelled: false,
      terminalHandled: true,
      hadConnectedStream: true,
    })).toBe(false)
  })
})
