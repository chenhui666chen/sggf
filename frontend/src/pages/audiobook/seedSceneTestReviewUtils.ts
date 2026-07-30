type ReviewStorage = Pick<Storage, 'getItem' | 'removeItem' | 'setItem'>

export interface SeedSceneTestReviewFlags {
  dialogueComplete: boolean | null
  plotUnderstandable: boolean | null
  voicesDistinct: boolean | null
  voiceConsistent: boolean | null
  emotionNatural: boolean | null
  effectsTimed: boolean | null
  musicAppropriate: boolean | null
  mixClear: boolean | null
  usable: boolean | null
}

export interface SeedSceneTestGenerationSnapshot {
  sampleId: string
  durationS: number | null
  latencyS: number | null
  costYuan: number | null
  requestId: string | null
  qualityPassed: boolean | null
  fallbackReason: string | null
}

export interface SeedSceneTestReviewRecord {
  id?: string
  caseId: string
  variant: string
  sampleIndex: number
  score: number | null
  flags: SeedSceneTestReviewFlags
  generation: SeedSceneTestGenerationSnapshot
  notes: string
  updatedAt: string
}

export interface StoredSeedSceneTestReviewRecord extends SeedSceneTestReviewRecord {
  id: string
}

export const SEED_SCENE_TEST_REVIEW_STORAGE_KEY = 'audiobook_seed_scene_test_review_v3'

export const buildSeedSceneTestReviewId = (
  caseId: string,
  variant: string,
  sampleIndex: number,
) => `${caseId}:${variant}:r${sampleIndex}`

const normalizeRecord = (record: SeedSceneTestReviewRecord): StoredSeedSceneTestReviewRecord => ({
  ...record,
  id: record.id || buildSeedSceneTestReviewId(record.caseId, record.variant, record.sampleIndex),
})

export const readSeedSceneTestReviews = (storage: ReviewStorage): StoredSeedSceneTestReviewRecord[] => {
  let raw: string | null = null
  try {
    raw = storage.getItem(SEED_SCENE_TEST_REVIEW_STORAGE_KEY)
  } catch {
    return []
  }
  if (!raw) return []

  try {
    const parsed = JSON.parse(raw) as { records?: unknown }
    if (!Array.isArray(parsed.records)) return []
    return parsed.records.flatMap((item): StoredSeedSceneTestReviewRecord[] => {
      if (!item || typeof item !== 'object') return []
      const record = item as SeedSceneTestReviewRecord
      if (typeof record.caseId !== 'string' || typeof record.variant !== 'string') return []
      if (!Number.isInteger(record.sampleIndex) || record.sampleIndex < 1 || record.sampleIndex > 3) return []
      if (!record.generation || typeof record.generation.sampleId !== 'string') return []
      return [normalizeRecord(record)]
    })
  } catch {
    try {
      storage.removeItem(SEED_SCENE_TEST_REVIEW_STORAGE_KEY)
    } catch {
      // The current review remains usable even when local storage is unavailable.
    }
    return []
  }
}

export const writeSeedSceneTestReview = (
  storage: ReviewStorage,
  record: SeedSceneTestReviewRecord,
) => {
  const normalized = normalizeRecord(record)
  const records = readSeedSceneTestReviews(storage)
  try {
    storage.setItem(SEED_SCENE_TEST_REVIEW_STORAGE_KEY, JSON.stringify({
      schemaVersion: 1,
      records: [...records.filter((item) => item.id !== normalized.id), normalized],
    }))
  } catch {
    // Ignore unavailable or full local storage.
  }
}

export const summarizeSeedSceneTestReviewProgress = (
  records: readonly Pick<StoredSeedSceneTestReviewRecord, 'id'>[],
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

export const buildSeedSceneTestReviewExport = (
  records: readonly StoredSeedSceneTestReviewRecord[],
  exportedAt = new Date().toISOString(),
) => {
  const sortedRecords = [...records].sort((left, right) =>
    left.id.localeCompare(right.id, 'en')
  )
  return {
    schemaVersion: 'seed-scene-review-export-v1' as const,
    exportedAt,
    recordCount: sortedRecords.length,
    records: sortedRecords,
  }
}

const stableHash = (value: string) => {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

export interface SeedSceneBlindAssignment {
  anonymousId: string
  blindLabel: string
  sampleIndex: number
}

export const buildSeedSceneBlindAssignments = (
  batchId: string,
  caseId: string,
  variants: readonly string[],
  repeatCount: number,
): SeedSceneBlindAssignment[] => {
  const assignments: SeedSceneBlindAssignment[] = []
  for (let sampleIndex = 1; sampleIndex <= Math.max(0, repeatCount); sampleIndex += 1) {
    const ordered = [...variants].sort((left, right) =>
      stableHash(`${batchId}:${caseId}:${sampleIndex}:${left}`).localeCompare(
        stableHash(`${batchId}:${caseId}:${sampleIndex}:${right}`),
        'en',
      )
    )
    ordered.forEach((variant, variantIndex) => {
      assignments.push({
        anonymousId: `blind_${stableHash(`${batchId}:${caseId}:${sampleIndex}:${variant}`)}`,
        blindLabel: `${String.fromCharCode(65 + variantIndex)}${sampleIndex}`,
        sampleIndex,
      })
    })
  }
  return assignments
}

export const buildSeedSceneBlindAnswerKey = (
  batchId: string,
  caseId: string,
  variants: readonly string[],
  repeatCount: number,
) => {
  const entries: Array<{ anonymousId: string; caseId: string; variant: string; sampleIndex: number }> = []
  for (let sampleIndex = 1; sampleIndex <= Math.max(0, repeatCount); sampleIndex += 1) {
    variants.forEach((variant) => {
      entries.push({
        anonymousId: `blind_${stableHash(`${batchId}:${caseId}:${sampleIndex}:${variant}`)}`,
        caseId,
        variant,
        sampleIndex,
      })
    })
  }
  return {
    schemaVersion: 'seed-scene-blind-answer-key-v1' as const,
    batchId,
    entries,
  }
}
