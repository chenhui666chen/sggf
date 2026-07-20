type ReviewStorage = Pick<Storage, 'getItem' | 'removeItem' | 'setItem'>

export interface TtsPromptTestReviewFlags {
  emotionChanged: boolean | null
  pauseHandled: boolean | null
  stressHandled: boolean | null
  noTagLeak: boolean | null
  usable: boolean | null
}

export interface TtsPromptTestReviewRecord {
  id?: string
  model: string
  caseId: string
  score: number | null
  flags: TtsPromptTestReviewFlags
  notes: string
  updatedAt: string
}

export interface StoredTtsPromptTestReviewRecord extends TtsPromptTestReviewRecord {
  id: string
}

export const TTS_PROMPT_TEST_REVIEW_STORAGE_KEY = 'audiobook_tts_prompt_test_review_v1'

export const buildTtsPromptTestReviewId = (model: string, caseId: string) => `${model}:${caseId}`

const normalizeRecord = (record: TtsPromptTestReviewRecord): StoredTtsPromptTestReviewRecord => ({
  ...record,
  id: record.id || buildTtsPromptTestReviewId(record.model, record.caseId),
})

export const readTtsPromptTestReviews = (storage: ReviewStorage): StoredTtsPromptTestReviewRecord[] => {
  let raw: string | null = null
  try {
    raw = storage.getItem(TTS_PROMPT_TEST_REVIEW_STORAGE_KEY)
  } catch {
    return []
  }
  if (!raw) return []

  try {
    const parsed = JSON.parse(raw) as { records?: unknown }
    if (!Array.isArray(parsed.records)) return []
    return parsed.records.flatMap((item): StoredTtsPromptTestReviewRecord[] => {
      if (!item || typeof item !== 'object') return []
      const record = item as TtsPromptTestReviewRecord
      if (typeof record.model !== 'string' || typeof record.caseId !== 'string') return []
      return [normalizeRecord(record)]
    })
  } catch {
    try {
      storage.removeItem(TTS_PROMPT_TEST_REVIEW_STORAGE_KEY)
    } catch {
      // Ignore unavailable local storage; the current review still remains in component state.
    }
    return []
  }
}

export const writeTtsPromptTestReview = (
  storage: ReviewStorage,
  record: TtsPromptTestReviewRecord,
) => {
  const normalized = normalizeRecord(record)
  const records = readTtsPromptTestReviews(storage)
  try {
    storage.setItem(TTS_PROMPT_TEST_REVIEW_STORAGE_KEY, JSON.stringify({
      schemaVersion: 1,
      records: [...records.filter((item) => item.id !== normalized.id), normalized],
    }))
  } catch {
    // Ignore unavailable or full local storage.
  }
}

export const summarizeTtsPromptTestReviewProgress = (
  records: readonly Pick<StoredTtsPromptTestReviewRecord, 'id'>[],
  total: number,
) => {
  const safeTotal = Math.max(0, total)
  const reviewed = new Set(records.map((record) => record.id)).size
  return {
    reviewed,
    total: safeTotal,
    percent: safeTotal > 0 ? Math.round((reviewed / safeTotal) * 100) : 0,
  }
}
