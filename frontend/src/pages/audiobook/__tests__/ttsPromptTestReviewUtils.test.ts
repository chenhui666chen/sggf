import { describe, expect, it } from 'vitest'

import {
  TTS_PROMPT_TEST_REVIEW_STORAGE_KEY,
  buildTtsPromptTestReviewId,
  readTtsPromptTestReviews,
  summarizeTtsPromptTestReviewProgress,
  writeTtsPromptTestReview,
} from '../ttsPromptTestReviewUtils'

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

describe('independent TTS prompt test review storage', () => {
  it('keys a review only by model and case', () => {
    expect(buildTtsPromptTestReviewId('cosyvoice-v3.5-plus', 'compact_emotion_cues')).toBe(
      'cosyvoice-v3.5-plus:compact_emotion_cues',
    )
  })

  it('replaces the review for the same model case', () => {
    const storage = new MemoryStorage()
    const base = {
      model: 'cosyvoice-v3.5-plus',
      caseId: 'compact_emotion_cues',
      score: 2,
      flags: {
        emotionChanged: false,
        pauseHandled: false,
        stressHandled: false,
        noTagLeak: true,
        usable: false,
      },
      notes: 'flat',
      updatedAt: '2026-07-12T10:00:00.000Z',
    }

    writeTtsPromptTestReview(storage, base)
    writeTtsPromptTestReview(storage, {
      ...base,
      score: 4,
      notes: 'usable',
      updatedAt: '2026-07-12T10:05:00.000Z',
    })

    expect(readTtsPromptTestReviews(storage)).toEqual([
      expect.objectContaining({
        id: 'cosyvoice-v3.5-plus:compact_emotion_cues',
        score: 4,
        notes: 'usable',
      }),
    ])
    expect(storage.getItem(TTS_PROMPT_TEST_REVIEW_STORAGE_KEY)).not.toContain('chapterId')
  })

  it('clears malformed data and counts unique reviewed cases', () => {
    const storage = new MemoryStorage()
    storage.setItem(TTS_PROMPT_TEST_REVIEW_STORAGE_KEY, '{bad-json')
    expect(readTtsPromptTestReviews(storage)).toEqual([])
    expect(storage.getItem(TTS_PROMPT_TEST_REVIEW_STORAGE_KEY)).toBeNull()

    expect(summarizeTtsPromptTestReviewProgress([
      { id: 'a:b' },
      { id: 'a:b' },
      { id: 'a:c' },
    ], 4)).toEqual({ reviewed: 2, total: 4, percent: 50 })
  })
})
