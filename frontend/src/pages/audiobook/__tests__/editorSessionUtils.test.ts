import { describe, expect, it } from 'vitest'

import {
  AUDIOBOOK_EDITOR_SYNC_TTL_MS,
  areAudiobookEditorSessionsEquivalent,
  buildAudiobookEditorConflictPreview,
  buildAudiobookEditorConflictSignature,
  buildAudiobookEditorSessionPayload,
  buildComparableAudiobookEditorSessionPayload,
  buildSegmentDetailsOpenState,
  extractOpenSegmentDetailIndices,
  normalizeAudiobookEditorSessionState,
  normalizeAudiobookEditorSyncRegistry,
  parseSessionTimestamp,
  pruneAudiobookEditorSyncEntries,
  selectLatestIncomingAudiobookEditorSyncEntry,
  shouldRefreshAudiobookEditorSyncHeartbeat,
} from '../editorSessionUtils'

describe('audiobook editor session utils', () => {
  it('normalizes editor session state defensively', () => {
    const normalized = normalizeAudiobookEditorSessionState({
      projectId: '11',
      audiobookProjectId: 22,
      chapterId: '33',
      reviewMode: 1,
      openSegmentDetailIndices: [3, '1', 3, -1, 'bad'],
      segmentReviews: {
        2: { quality_score: 8.5, needs_regenerate: true },
        invalid: { quality_score: 7 },
        4: { quality_score: Number.NaN, needs_regenerate: 'yes' },
      },
      timelineEdits: {
        'sfx-0-0': { startUnit: '12', durationUnits: 48 },
        'music-1-2': { startUnit: 24, durationUnits: '96' },
        invalidNegative: { startUnit: -1, durationUnits: 20 },
        invalidDuration: { startUnit: 10, durationUnits: 0 },
        invalidMissing: { startUnit: 10 },
      },
      data: {
        scriptStatus: '',
        scriptSegments: [{ text: '旁白文本' }],
        scriptReview: { overall_score: 9, issues: [] },
      },
      updatedAt: '2026-04-30T12:00:00.000Z',
      writerTabId: ' tab-a ',
    })

    expect(normalized).toMatchObject({
      projectId: 11,
      audiobookProjectId: 22,
      chapterId: 33,
      reviewMode: true,
      openSegmentDetailIndices: [1, 3],
      segmentReviews: {
        2: { quality_score: 8.5, needs_regenerate: true },
      },
      timelineEdits: {
        'sfx-0-0': { startUnit: 12, durationUnits: 48 },
        'music-1-2': { startUnit: 24, durationUnits: 96 },
      },
      data: {
        scriptStatus: 'pending',
        scriptSegments: [{ text: '旁白文本' }],
        scriptReview: { overall_score: 9, issues_count: 0 },
      },
      updatedAt: '2026-04-30T12:00:00.000Z',
      writerTabId: 'tab-a',
    })
  })

  it('normalizes and prunes editor sync registry entries', () => {
    const now = Date.parse('2026-04-30T12:10:00.000Z')
    const freshUpdatedAt = '2026-04-30T12:05:00.000Z'
    const staleUpdatedAt = new Date(now - AUDIOBOOK_EDITOR_SYNC_TTL_MS - 1).toISOString()

    const registry = normalizeAudiobookEditorSyncRegistry({
      entries: {
        fresh: {
          projectId: 1,
          audiobookProjectId: 2,
          chapterId: 3,
          writerTabId: 'fresh-tab',
          updatedAt: freshUpdatedAt,
          data: { scriptSegments: [] },
        },
        stale: {
          writerTabId: 'stale-tab',
          updatedAt: staleUpdatedAt,
          data: { scriptSegments: [] },
        },
        missingWriter: {
          updatedAt: freshUpdatedAt,
          data: { scriptSegments: [] },
        },
        '': {
          writerTabId: 'empty-key-tab',
          updatedAt: freshUpdatedAt,
        },
      },
    })

    expect(Object.keys(registry).sort()).toEqual(['fresh', 'stale'])
    expect(pruneAudiobookEditorSyncEntries(registry, now)).toEqual({
      fresh: registry.fresh,
    })
    expect(parseSessionTimestamp('not-a-date')).toBe(0)
  })

  it('builds stable open segment index state', () => {
    const state = buildSegmentDetailsOpenState([2, 4])

    expect(state).toEqual({ 2: true, 4: true })
    expect(extractOpenSegmentDetailIndices({ 3: true, 1: false, 5: true })).toEqual([3, 5])
  })

  it('builds comparable editor session payloads without volatile fields', () => {
    const comparable = buildComparableAudiobookEditorSessionPayload({
      projectId: '1' as unknown as number,
      audiobookProjectId: 2,
      chapterId: 3,
      writerTabId: 'tab-a',
      updatedAt: '2026-04-30T12:00:00.000Z',
      openSegmentDetailIndices: ['2', 0] as unknown as number[],
      timelineEdits: {
        'sfx-0-0': { startUnit: 12, durationUnits: 48 },
      },
      data: {
        scriptStatus: 'reviewed',
        scriptSegments: [{ text: 'A' }],
        scriptReview: null,
      },
    })

    expect(comparable).toEqual({
      projectId: 1,
      audiobookProjectId: 2,
      chapterId: 3,
      reviewMode: false,
      openSegmentDetailIndices: [0, 2],
      segmentReviews: {},
      timelineEdits: {
        'sfx-0-0': { startUnit: 12, durationUnits: 48 },
      },
      data: {
        scriptStatus: 'reviewed',
        scriptSegments: [{ text: 'A' }],
        chapterAudioAvailable: false,
        chapterAudioUrl: '',
        segmentTimings: [],
        scriptReview: null,
      },
    })
  })

  it('builds editor session payloads and compares by stable fields', () => {
    const base = buildAudiobookEditorSessionPayload({
      projectId: 1,
      audiobookProjectId: 2,
      chapterId: 3,
      reviewMode: true,
      segmentDetailsOpen: { 2: true, 1: false, 0: true },
      segmentReviews: { 0: { quality_score: 8 } },
      timelineEdits: {
        'sfx-0-0': { startUnit: 12, durationUnits: 48 },
      },
      data: {
        scriptStatus: 'generated',
        scriptSegments: [{ text: 'A' }],
        scriptReview: null,
      },
      updatedAt: '2026-04-30T12:00:00.000Z',
      writerTabId: 'tab-a',
    })
    const sameDraft = {
      ...base,
      updatedAt: '2026-04-30T12:10:00.000Z',
      writerTabId: 'tab-b',
    }

    expect(base.openSegmentDetailIndices).toEqual([0, 2])
    expect(base.timelineEdits).toEqual({
      'sfx-0-0': { startUnit: 12, durationUnits: 48 },
    })
    expect(areAudiobookEditorSessionsEquivalent(base, sameDraft)).toBe(true)
    expect(areAudiobookEditorSessionsEquivalent(base, {
      ...sameDraft,
      reviewMode: false,
    })).toBe(false)
    expect(areAudiobookEditorSessionsEquivalent(base, {
      ...sameDraft,
      timelineEdits: {
        'sfx-0-0': { startUnit: 18, durationUnits: 48 },
      },
    })).toBe(false)
  })

  it('selects latest incoming sync entry for the same chapter', () => {
    const currentTabEntry = {
      projectId: 1,
      audiobookProjectId: 2,
      chapterId: 3,
      writerTabId: 'tab-a',
      updatedAt: '2026-04-30T12:10:00.000Z',
      data: { scriptStatus: 'generated', scriptSegments: [], scriptReview: null },
    }
    const olderIncoming = {
      ...currentTabEntry,
      writerTabId: 'tab-b',
      updatedAt: '2026-04-30T12:05:00.000Z',
    }
    const newerIncoming = {
      ...currentTabEntry,
      writerTabId: 'tab-c',
      updatedAt: '2026-04-30T12:15:00.000Z',
    }
    const otherChapter = {
      ...newerIncoming,
      writerTabId: 'tab-d',
      chapterId: 4,
    }

    expect(selectLatestIncomingAudiobookEditorSyncEntry({
      current: currentTabEntry,
      older: olderIncoming,
      newer: newerIncoming,
      otherChapter,
    }, {
      writerTabId: 'tab-a',
      projectId: 1,
      audiobookProjectId: 2,
      chapterId: 3,
    })?.writerTabId).toBe('tab-c')
  })

  it('decides whether sync heartbeat should refresh', () => {
    const nowMs = Date.parse('2026-04-30T12:01:00.000Z')

    expect(shouldRefreshAudiobookEditorSyncHeartbeat({
      existingUpdatedAt: '2026-04-30T12:00:40.000Z',
      nowMs,
    })).toBe(false)
    expect(shouldRefreshAudiobookEditorSyncHeartbeat({
      existingUpdatedAt: '2026-04-30T12:00:29.000Z',
      nowMs,
    })).toBe(true)
    expect(shouldRefreshAudiobookEditorSyncHeartbeat({
      existingUpdatedAt: 'invalid',
      nowMs,
    })).toBe(true)
    expect(shouldRefreshAudiobookEditorSyncHeartbeat({
      existingUpdatedAt: '2026-04-30T12:00:59.000Z',
      nowMs,
      forceTouch: true,
    })).toBe(true)
  })

  it('builds conflict signatures and previews editor draft differences', () => {
    const localSession = {
      writerTabId: 'local-tab',
      updatedAt: '2026-04-30T12:00:00.000Z',
      reviewMode: false,
      openSegmentDetailIndices: [1],
      segmentReviews: { 0: { quality_score: 7 } },
      timelineEdits: {
        'sfx-0-0': { startUnit: 12, durationUnits: 48 },
      },
      data: {
        scriptStatus: 'generated',
        scriptSegments: [
          {
            speaker: '旁白',
            text: '旧文本',
            performance_notes: '平稳',
          },
        ],
        scriptReview: null,
      },
    }
    const incomingSession = {
      writerTabId: 'incoming-tab',
      updatedAt: '2026-04-30T12:01:00.000Z',
      reviewMode: true,
      openSegmentDetailIndices: [1, 2],
      segmentReviews: { 0: { quality_score: 9, needs_regenerate: true } },
      timelineEdits: {
        'sfx-0-0': { startUnit: 18, durationUnits: 64 },
      },
      data: {
        scriptStatus: 'reviewed',
        scriptSegments: [
          {
            speaker: '角色甲',
            text: '新文本',
            performance_notes: '紧张',
          },
          {
            speaker: '角色乙',
            text: '新增对白',
          },
        ],
        scriptReview: null,
      },
    }

    expect(buildAudiobookEditorConflictSignature(incomingSession)).toBe(
      'incoming-tab:2026-04-30T12:01:00.000Z',
    )

    const preview = buildAudiobookEditorConflictPreview(localSession, incomingSession)

    expect(preview?.fieldDiffs.map((field) => field.key)).toEqual([
      'scriptStatus',
      'reviewMode',
      'openSegmentDetailIndices',
      'segmentReviews',
      'timelineEdits',
    ])
    expect(preview?.segmentDiffs).toHaveLength(2)
    expect(preview?.segmentDiffs[0]).toMatchObject({
      index: 0,
      speaker: '角色甲',
      changeType: 'modified',
    })
    expect(preview?.segmentDiffs[0].fieldDiffs.map((field) => field.key)).toEqual([
      'text',
      'performance_notes',
    ])
    expect(preview?.segmentDiffs[1]).toMatchObject({
      index: 1,
      speaker: '角色乙',
      changeType: 'added',
    })
  })

  it('returns null when editor drafts are equivalent', () => {
    const session = {
      data: {
        scriptStatus: 'generated',
        scriptSegments: [{ text: '相同文本' }],
        scriptReview: null,
      },
    }

    expect(buildAudiobookEditorConflictPreview(session, session)).toBeNull()
  })
})
