import { describe, expect, it } from 'vitest'

import {
  SEED_SCENE_TEST_REVIEW_STORAGE_KEY,
  buildSeedSceneTestReviewId,
  buildSeedSceneTestReviewExport,
  buildSeedSceneBlindAssignments,
  buildSeedSceneBlindAnswerKey,
  readSeedSceneTestReviews,
  summarizeSeedSceneTestReviewProgress,
  writeSeedSceneTestReview,
} from '../seedSceneTestReviewUtils'

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

describe('independent Seed scene test review storage', () => {
  it('uses a new review namespace for native speaker and prompt revisions', () => {
    expect(SEED_SCENE_TEST_REVIEW_STORAGE_KEY).toBe('audiobook_seed_scene_test_review_v3')
  })

  it('keys each blind variant and repeat independently', () => {
    expect(buildSeedSceneTestReviewId('phone_confrontation', 'described_voices', 1)).toBe(
      'phone_confrontation:described_voices:r1',
    )
    expect(buildSeedSceneTestReviewId('phone_confrontation', 'reference_voices', 3)).toBe(
      'phone_confrontation:reference_voices:r3',
    )
  })

  it('persists review dimensions without project or chapter identity', () => {
    const storage = new MemoryStorage()
    writeSeedSceneTestReview(storage, {
      caseId: 'phone_confrontation',
      variant: 'reference_voices',
      sampleIndex: 2,
      score: 4.5,
      flags: {
        dialogueComplete: true,
        plotUnderstandable: true,
        voicesDistinct: true,
        voiceConsistent: true,
        emotionNatural: true,
        effectsTimed: false,
        musicAppropriate: true,
        mixClear: true,
        usable: true,
      },
      generation: {
        sampleId: 'blind-sample-1',
        durationS: 27.5,
        latencyS: 31.2,
        costYuan: 0.4583,
        requestId: 'provider-request-1',
        qualityPassed: true,
        fallbackReason: null,
      },
      notes: '刹车声稍早',
      updatedAt: '2026-07-20T12:00:00.000Z',
    })

    expect(readSeedSceneTestReviews(storage)).toEqual([
      expect.objectContaining({
        id: 'phone_confrontation:reference_voices:r2',
        score: 4.5,
        notes: '刹车声稍早',
        generation: expect.objectContaining({ costYuan: 0.4583 }),
      }),
    ])
    const raw = storage.getItem(SEED_SCENE_TEST_REVIEW_STORAGE_KEY) ?? ''
    expect(raw).not.toContain('projectId')
    expect(raw).not.toContain('chapterId')
  })

  it('clears malformed data and summarizes unique variants', () => {
    const storage = new MemoryStorage()
    storage.setItem(SEED_SCENE_TEST_REVIEW_STORAGE_KEY, '{bad-json')

    expect(readSeedSceneTestReviews(storage)).toEqual([])
    expect(storage.getItem(SEED_SCENE_TEST_REVIEW_STORAGE_KEY)).toBeNull()
    expect(summarizeSeedSceneTestReviewProgress([
      { id: 'a:described_voices:r1' },
      { id: 'a:described_voices:r1' },
      { id: 'a:reference_voices:r3' },
    ], 30)).toEqual({ reviewed: 2, total: 30, percent: 7 })
  })

  it('exports reviews in stable order with a versioned evidence schema', () => {
    const records = [
      {
        id: 'b:reference_voices:r2',
        caseId: 'b', variant: 'reference_voices', sampleIndex: 2, score: 4,
        flags: { dialogueComplete: true, plotUnderstandable: true, voicesDistinct: true, voiceConsistent: true, emotionNatural: true, effectsTimed: true, musicAppropriate: true, mixClear: true, usable: true },
        generation: { sampleId: 'sample-b', durationS: 10, latencyS: 12, costYuan: 0.2, requestId: 'request-b', qualityPassed: true, fallbackReason: null },
        notes: '', updatedAt: '2026-07-25T02:00:00.000Z',
      },
      {
        id: 'a:described_voices:r1',
        caseId: 'a', variant: 'described_voices', sampleIndex: 1, score: 3,
        flags: { dialogueComplete: true, plotUnderstandable: true, voicesDistinct: null, voiceConsistent: null, emotionNatural: true, effectsTimed: false, musicAppropriate: true, mixClear: true, usable: true },
        generation: { sampleId: 'sample-a', durationS: 8, latencyS: 9, costYuan: 0.1, requestId: null, qualityPassed: false, fallbackReason: 'quality' },
        notes: 'review', updatedAt: '2026-07-25T01:00:00.000Z',
      },
    ] as const

    const exported = buildSeedSceneTestReviewExport(
      records,
      '2026-07-25T03:00:00.000Z',
    )

    expect(exported.schemaVersion).toBe('seed-scene-review-export-v1')
    expect(exported.recordCount).toBe(2)
    expect(exported.records.map((record) => record.id)).toEqual([
      'a:described_voices:r1',
      'b:reference_voices:r2',
    ])
    expect(JSON.stringify(exported)).not.toContain('audio_data')
    expect(JSON.stringify(exported)).not.toContain('audio_url')
  })

  it('builds reproducible blind assignments without variant details', () => {
    const variants = ['described_voices', 'reference_voices']
    const first = buildSeedSceneBlindAssignments('batch-20260725', 'case-a', variants, 2)
    const second = buildSeedSceneBlindAssignments('batch-20260725', 'case-a', variants, 2)

    expect(first).toEqual(second)
    expect(first).toHaveLength(4)
    expect(first.map((item) => item.blindLabel).sort()).toEqual(['A1', 'A2', 'B1', 'B2'])
    expect(first.every((item) => !('variant' in item))).toBe(true)
    expect(first.every((item) => item.anonymousId.startsWith('blind_'))).toBe(true)

    const answerKey = buildSeedSceneBlindAnswerKey(
      'batch-20260725', 'case-a', variants, 2,
    )
    expect(answerKey.schemaVersion).toBe('seed-scene-blind-answer-key-v1')
    expect(answerKey.entries).toHaveLength(4)
    expect(answerKey.entries.map((item) => item.anonymousId).sort()).toEqual(
      first.map((item) => item.anonymousId).sort(),
    )
    expect(answerKey.entries.map((item) => item.variant).sort()).toEqual([
      'described_voices', 'described_voices', 'reference_voices', 'reference_voices',
    ])
  })
})
