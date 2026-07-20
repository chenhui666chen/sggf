import type {
  AudiobookEditorSessionState,
  AudiobookEditorSyncRegistry,
  EditorConflictDiffPreview,
  EditorConflictFieldDiffPreview,
  EditorConflictSegmentDiffPreview,
  ScriptEditorStateData,
  ScriptSegment,
  TimelineClipEditMap,
} from './types'
import { normalizeScriptReview } from './utils'

export const AUDIOBOOK_EDITOR_SYNC_TTL_MS = 10 * 60 * 1000
export const AUDIOBOOK_EDITOR_SYNC_HEARTBEAT_MS = 30 * 1000

const SCRIPT_EDITOR_CONFLICT_SEGMENT_FIELDS = [
  { key: 'text', label: '文本', maxLength: 96 },
  { key: 'performance_notes', label: '表演提示', maxLength: 72 },
  { key: 'pause_before', label: '前停顿', maxLength: 24 },
  { key: 'pause_after', label: '后停顿', maxLength: 24 },
  { key: 'instruct_emotion', label: '情绪指令', maxLength: 48 },
  { key: 'instruct_scene', label: '场景指令', maxLength: 48 },
  { key: 'instruct_role', label: '角色指令', maxLength: 48 },
  { key: 'instruct_identity', label: '身份指令', maxLength: 48 },
  { key: 'voice_params', label: '音色参数', maxLength: 72 },
  { key: 'sound_effects_simple', label: '简易音效', maxLength: 72 },
  { key: 'sound_effects', label: '详细音效', maxLength: 72 },
  { key: 'music_cue_simple', label: '简易配乐', maxLength: 56 },
  { key: 'music_cue', label: '详细配乐', maxLength: 72 },
] as const satisfies ReadonlyArray<{
  key: keyof ScriptSegment
  label: string
  maxLength: number
}>

const SCRIPT_STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  generated: '已生成',
  reviewed: '已审查',
  approved: '已通过',
}

export const parseSessionTimestamp = (value: unknown): number => {
  if (typeof value !== 'string' || !value.trim()) {
    return 0
  }
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : 0
}

export const pruneAudiobookEditorSyncEntries = (
  entries: Record<string, AudiobookEditorSessionState>,
  nowMs: number = Date.now(),
): Record<string, AudiobookEditorSessionState> => {
  const nextEntries: Record<string, AudiobookEditorSessionState> = {}

  for (const [entryKey, entry] of Object.entries(entries)) {
    const updatedAtMs = parseSessionTimestamp(entry.updatedAt)
    if (updatedAtMs <= 0) {
      continue
    }
    if (nowMs - updatedAtMs > AUDIOBOOK_EDITOR_SYNC_TTL_MS) {
      continue
    }
    nextEntries[entryKey] = entry
  }

  return nextEntries
}

export const normalizePositiveId = (value: unknown): number | null => {
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

export const normalizeSegmentDetailIndices = (value: unknown): number[] =>
  Array.isArray(value)
    ? Array.from(
        new Set(
          value
            .map((item) => Number(item))
            .filter((item) => Number.isFinite(item) && item >= 0),
        ),
      ).sort((left, right) => left - right)
    : []

export const buildSegmentDetailsOpenState = (indices: number[]): Record<number, boolean> => {
  const nextState: Record<number, boolean> = {}
  for (const index of indices) {
    nextState[index] = true
  }
  return nextState
}

export const extractOpenSegmentDetailIndices = (segmentDetailsOpen: Record<number, boolean>): number[] =>
  Object.entries(segmentDetailsOpen)
    .filter(([, open]) => Boolean(open))
    .map(([index]) => Number(index))
    .filter((index) => Number.isFinite(index) && index >= 0)
    .sort((left, right) => left - right)

export const normalizeSegmentReviews = (
  reviews: unknown,
): Record<number, { quality_score?: number; needs_regenerate?: boolean }> => {
  if (!reviews || typeof reviews !== 'object') {
    return {}
  }

  const normalized: Record<number, { quality_score?: number; needs_regenerate?: boolean }> = {}
  for (const [rawIndex, rawReview] of Object.entries(reviews as Record<string, unknown>)) {
    const index = Number(rawIndex)
    if (!Number.isFinite(index) || index < 0 || !rawReview || typeof rawReview !== 'object') {
      continue
    }

    const review = rawReview as Record<string, unknown>
    const nextReview: { quality_score?: number; needs_regenerate?: boolean } = {}

    if (typeof review.quality_score === 'number' && !Number.isNaN(review.quality_score)) {
      nextReview.quality_score = review.quality_score
    }
    if (typeof review.needs_regenerate === 'boolean') {
      nextReview.needs_regenerate = review.needs_regenerate
    }

    if (Object.keys(nextReview).length > 0) {
      normalized[index] = nextReview
    }
  }

  return normalized
}

export const normalizeTimelineEdits = (edits: unknown): TimelineClipEditMap => {
  if (!edits || typeof edits !== 'object') {
    return {}
  }

  const normalized: TimelineClipEditMap = {}
  for (const [clipKey, rawEdit] of Object.entries(edits as Record<string, unknown>)) {
    if (!clipKey.trim() || !rawEdit || typeof rawEdit !== 'object') {
      continue
    }

    const edit = rawEdit as Record<string, unknown>
    const startUnit = Number(edit.startUnit)
    const durationUnits = Number(edit.durationUnits)
    if (
      !Number.isFinite(startUnit)
      || !Number.isFinite(durationUnits)
      || startUnit < 0
      || durationUnits <= 0
    ) {
      continue
    }

    const nextEdit: TimelineClipEditMap[string] = {
      startUnit,
      durationUnits,
    }
    const volume = Number(edit.volume)
    if (Number.isFinite(volume)) {
      nextEdit.volume = Math.max(0, Math.min(1, volume))
    }

    normalized[clipKey] = nextEdit
  }

  return normalized
}

export const normalizeScriptEditorStateData = (raw: unknown): ScriptEditorStateData | null => {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const data = raw as Partial<ScriptEditorStateData>
  return {
    scriptStatus:
      typeof data.scriptStatus === 'string' && data.scriptStatus.trim()
        ? data.scriptStatus
        : 'pending',
    scriptSegments: Array.isArray(data.scriptSegments) ? data.scriptSegments : [],
    chapterAudioAvailable: data.chapterAudioAvailable === true,
    chapterAudioUrl: typeof data.chapterAudioUrl === 'string' ? data.chapterAudioUrl : '',
    segmentTimings: Array.isArray(data.segmentTimings) ? data.segmentTimings : [],
    scriptReview: normalizeScriptReview(data.scriptReview),
  }
}

export const normalizeAudiobookEditorSessionState = (
  raw: unknown,
): AudiobookEditorSessionState | null => {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const session = raw as AudiobookEditorSessionState
  return {
    projectId: normalizePositiveId(session.projectId),
    audiobookProjectId: normalizePositiveId(session.audiobookProjectId),
    chapterId: normalizePositiveId(session.chapterId),
    reviewMode: Boolean(session.reviewMode),
    openSegmentDetailIndices: normalizeSegmentDetailIndices(session.openSegmentDetailIndices),
    segmentReviews: normalizeSegmentReviews(session.segmentReviews),
    timelineEdits: normalizeTimelineEdits(session.timelineEdits),
    data: normalizeScriptEditorStateData(session.data),
    updatedAt: typeof session.updatedAt === 'string' ? session.updatedAt : undefined,
    writerTabId: typeof session.writerTabId === 'string' && session.writerTabId.trim()
      ? session.writerTabId.trim()
      : undefined,
  }
}

export const normalizeAudiobookEditorSyncRegistry = (
  raw: unknown,
): Record<string, AudiobookEditorSessionState> => {
  if (!raw || typeof raw !== 'object') {
    return {}
  }

  const registry = raw as AudiobookEditorSyncRegistry
  const rawEntries = registry.entries
  if (!rawEntries || typeof rawEntries !== 'object') {
    return {}
  }

  const normalizedEntries: Record<string, AudiobookEditorSessionState> = {}
  for (const [entryKey, entryValue] of Object.entries(rawEntries)) {
    if (!entryKey.trim()) {
      continue
    }
    const normalizedEntry = normalizeAudiobookEditorSessionState(entryValue)
    if (!normalizedEntry?.writerTabId) {
      continue
    }
    normalizedEntries[entryKey] = normalizedEntry
  }

  return normalizedEntries
}

export const buildComparableAudiobookEditorSessionPayload = (
  session: Partial<AudiobookEditorSessionState> | null | undefined,
) => {
  const normalizedSession = normalizeAudiobookEditorSessionState(session)

  return {
    projectId: normalizedSession?.projectId ?? null,
    audiobookProjectId: normalizedSession?.audiobookProjectId ?? null,
    chapterId: normalizedSession?.chapterId ?? null,
    reviewMode: normalizedSession?.reviewMode ?? false,
    openSegmentDetailIndices: normalizedSession?.openSegmentDetailIndices ?? [],
    segmentReviews: normalizedSession?.segmentReviews ?? {},
    timelineEdits: normalizedSession?.timelineEdits ?? {},
    data: normalizedSession?.data ?? null,
  }
}

export const buildAudiobookEditorSessionPayload = ({
  projectId,
  audiobookProjectId,
  chapterId,
  reviewMode,
  segmentDetailsOpen,
  segmentReviews,
  timelineEdits,
  data,
  updatedAt,
  writerTabId,
}: {
  projectId: number
  audiobookProjectId: number
  chapterId: number
  reviewMode: boolean
  segmentDetailsOpen: Record<number, boolean>
  segmentReviews: Record<number, { quality_score?: number; needs_regenerate?: boolean }>
  timelineEdits?: TimelineClipEditMap
  data: ScriptEditorStateData
  updatedAt?: string
  writerTabId?: string
}): AudiobookEditorSessionState => ({
  projectId,
  audiobookProjectId,
  chapterId,
  reviewMode,
  openSegmentDetailIndices: extractOpenSegmentDetailIndices(segmentDetailsOpen),
  segmentReviews,
  timelineEdits: normalizeTimelineEdits(timelineEdits),
  data,
  updatedAt,
  writerTabId,
})

export const areAudiobookEditorSessionsEquivalent = (
  left: Partial<AudiobookEditorSessionState> | null | undefined,
  right: Partial<AudiobookEditorSessionState> | null | undefined,
): boolean =>
  JSON.stringify(buildComparableAudiobookEditorSessionPayload(left))
  === JSON.stringify(buildComparableAudiobookEditorSessionPayload(right))

export const shouldRefreshAudiobookEditorSyncHeartbeat = ({
  existingUpdatedAt,
  forceTouch = false,
  nowMs = Date.now(),
  heartbeatMs = AUDIOBOOK_EDITOR_SYNC_HEARTBEAT_MS,
}: {
  existingUpdatedAt?: string
  forceTouch?: boolean
  nowMs?: number
  heartbeatMs?: number
}): boolean => {
  if (forceTouch) {
    return true
  }

  const existingUpdatedAtMs = parseSessionTimestamp(existingUpdatedAt)
  return existingUpdatedAtMs <= 0 || nowMs - existingUpdatedAtMs >= heartbeatMs
}

export const selectLatestIncomingAudiobookEditorSyncEntry = (
  entries: Record<string, AudiobookEditorSessionState>,
  options: {
    writerTabId: string
    projectId: number
    audiobookProjectId: number
    chapterId: number
  },
): AudiobookEditorSessionState | null =>
  Object.values(entries)
    .filter((entry) => entry.writerTabId && entry.writerTabId !== options.writerTabId)
    .filter((entry) => entry.projectId === options.projectId)
    .filter((entry) => entry.audiobookProjectId === options.audiobookProjectId)
    .filter((entry) => entry.chapterId === options.chapterId)
    .sort((left, right) => parseSessionTimestamp(right.updatedAt) - parseSessionTimestamp(left.updatedAt))[0] || null

export const buildAudiobookEditorConflictSignature = (
  session: Partial<AudiobookEditorSessionState> | null | undefined,
) => {
  const normalizedSession = normalizeAudiobookEditorSessionState(session)
  if (!normalizedSession?.writerTabId) {
    return null
  }
  return `${normalizedSession.writerTabId}:${normalizedSession.updatedAt || ''}`
}

const normalizeEditorDiffComparableValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => normalizeEditorDiffComparableValue(item))
  }

  if (value && typeof value === 'object') {
    return Object.keys(value as Record<string, unknown>)
      .sort((left, right) => left.localeCompare(right))
      .reduce<Record<string, unknown>>((acc, key) => {
        const normalizedValue = normalizeEditorDiffComparableValue(
          (value as Record<string, unknown>)[key],
        )
        if (typeof normalizedValue !== 'undefined') {
          acc[key] = normalizedValue
        }
        return acc
      }, {})
  }

  if (typeof value === 'undefined') {
    return null
  }

  return value
}

const isDiffValueEqual = (left: unknown, right: unknown): boolean =>
  JSON.stringify(normalizeEditorDiffComparableValue(left))
  === JSON.stringify(normalizeEditorDiffComparableValue(right))

const hasMeaningfulDiffValue = (value: unknown): boolean => {
  if (value === null || typeof value === 'undefined') {
    return false
  }

  if (typeof value === 'string') {
    return value.trim().length > 0
  }

  if (Array.isArray(value)) {
    return value.length > 0
  }

  if (typeof value === 'object') {
    return Object.keys(value as Record<string, unknown>).length > 0
  }

  return true
}

const formatDiffPreviewText = (value: unknown, maxLength: number = 72): string => {
  if (value === null || typeof value === 'undefined') {
    return '—'
  }

  let text = ''
  if (typeof value === 'string') {
    text = value
  } else if (typeof value === 'number' || typeof value === 'boolean') {
    text = String(value)
  } else {
    try {
      text = JSON.stringify(value)
    } catch {
      text = String(value)
    }
  }

  const normalizedText = text.replace(/\s+/g, ' ').trim()
  if (!normalizedText) {
    return '—'
  }

  return normalizedText.length > maxLength
    ? `${normalizedText.slice(0, maxLength).trimEnd()}...`
    : normalizedText
}

const buildEditorConflictFieldDiffPreview = ({
  key,
  label,
  currentValue,
  incomingValue,
  maxLength = 72,
}: {
  key: string
  label: string
  currentValue: unknown
  incomingValue: unknown
  maxLength?: number
}): EditorConflictFieldDiffPreview => ({
  key,
  label,
  currentValue: formatDiffPreviewText(currentValue, maxLength),
  incomingValue: formatDiffPreviewText(incomingValue, maxLength),
})

const formatScriptStatusPreviewText = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim()) {
    return '—'
  }

  return SCRIPT_STATUS_LABELS[value.trim()] || value.trim()
}

const formatReviewModePreviewText = (value: unknown): string =>
  value ? '审查模式' : '普通编辑'

const formatOpenSegmentDetailIndicesSummary = (value: unknown): string => {
  const indices = normalizeSegmentDetailIndices(value)
  if (indices.length === 0) {
    return '无展开详情'
  }

  const preview = indices.slice(0, 4).map((index) => `#${index + 1}`).join('、')
  return indices.length > 4
    ? `${preview} 等 ${indices.length} 个片段已展开`
    : `${preview} 已展开`
}

const formatSegmentReviewSummary = (
  reviews: unknown,
): string => {
  const normalizedReviews = normalizeSegmentReviews(reviews)
  const entries = Object.entries(normalizedReviews)
    .map(([rawIndex, review]) => ({
      index: Number(rawIndex),
      review,
    }))
    .sort((left, right) => left.index - right.index)

  if (entries.length === 0) {
    return '无审查结果'
  }

  const ratedCount = entries.filter(({ review }) => typeof review.quality_score === 'number').length
  const regenerateCount = entries.filter(({ review }) => review.needs_regenerate).length
  const previewIndices = entries.slice(0, 4).map(({ index }) => `#${index + 1}`).join('、')

  return entries.length > 4
    ? `评分 ${ratedCount} 条，待重生成 ${regenerateCount} 条，涉及 ${previewIndices} 等 ${entries.length} 个片段`
    : `评分 ${ratedCount} 条，待重生成 ${regenerateCount} 条，涉及 ${previewIndices}`
}

const formatTimelineEditsSummary = (edits: unknown): string => {
  const normalizedEdits = normalizeTimelineEdits(edits)
  const entries = Object.keys(normalizedEdits)

  if (entries.length === 0) {
    return '无时间线调整'
  }

  const previewKeys = entries.slice(0, 3).join('、')
  return entries.length > 3
    ? `${entries.length} 个片段已调整，包含 ${previewKeys} 等`
    : `${entries.length} 个片段已调整，包含 ${previewKeys}`
}

const resolveScriptSegmentSpeaker = (segment: ScriptSegment | null | undefined): string => {
  const speaker =
    segment?.speaker
    || segment?.speaker_name
    || segment?.character_name
    || segment?.role_name

  return typeof speaker === 'string' && speaker.trim() ? speaker.trim() : '旁白'
}

export const buildAudiobookEditorConflictPreview = (
  localSession: Partial<AudiobookEditorSessionState> | null | undefined,
  incomingSession: Partial<AudiobookEditorSessionState> | null | undefined,
): EditorConflictDiffPreview | null => {
  const normalizedLocalSession = normalizeAudiobookEditorSessionState(localSession)
  const normalizedIncomingSession = normalizeAudiobookEditorSessionState(incomingSession)

  if (!normalizedLocalSession?.data || !normalizedIncomingSession?.data) {
    return null
  }

  const fieldDiffs: EditorConflictFieldDiffPreview[] = []
  if (!isDiffValueEqual(normalizedLocalSession.data.scriptStatus, normalizedIncomingSession.data.scriptStatus)) {
    fieldDiffs.push(
      buildEditorConflictFieldDiffPreview({
        key: 'scriptStatus',
        label: '剧本状态',
        currentValue: formatScriptStatusPreviewText(normalizedLocalSession.data.scriptStatus),
        incomingValue: formatScriptStatusPreviewText(normalizedIncomingSession.data.scriptStatus),
        maxLength: 32,
      }),
    )
  }
  if (!isDiffValueEqual(normalizedLocalSession.reviewMode, normalizedIncomingSession.reviewMode)) {
    fieldDiffs.push(
      buildEditorConflictFieldDiffPreview({
        key: 'reviewMode',
        label: '编辑模式',
        currentValue: formatReviewModePreviewText(normalizedLocalSession.reviewMode),
        incomingValue: formatReviewModePreviewText(normalizedIncomingSession.reviewMode),
        maxLength: 24,
      }),
    )
  }
  if (
    !isDiffValueEqual(
      normalizedLocalSession.openSegmentDetailIndices,
      normalizedIncomingSession.openSegmentDetailIndices,
    )
  ) {
    fieldDiffs.push(
      buildEditorConflictFieldDiffPreview({
        key: 'openSegmentDetailIndices',
        label: '详情展开',
        currentValue: formatOpenSegmentDetailIndicesSummary(normalizedLocalSession.openSegmentDetailIndices),
        incomingValue: formatOpenSegmentDetailIndicesSummary(normalizedIncomingSession.openSegmentDetailIndices),
        maxLength: 56,
      }),
    )
  }
  if (!isDiffValueEqual(normalizedLocalSession.segmentReviews, normalizedIncomingSession.segmentReviews)) {
    fieldDiffs.push(
      buildEditorConflictFieldDiffPreview({
        key: 'segmentReviews',
        label: '片段审查',
        currentValue: formatSegmentReviewSummary(normalizedLocalSession.segmentReviews),
        incomingValue: formatSegmentReviewSummary(normalizedIncomingSession.segmentReviews),
        maxLength: 80,
      }),
    )
  }
  if (!isDiffValueEqual(normalizedLocalSession.timelineEdits, normalizedIncomingSession.timelineEdits)) {
    fieldDiffs.push(
      buildEditorConflictFieldDiffPreview({
        key: 'timelineEdits',
        label: '音频时间线',
        currentValue: formatTimelineEditsSummary(normalizedLocalSession.timelineEdits),
        incomingValue: formatTimelineEditsSummary(normalizedIncomingSession.timelineEdits),
        maxLength: 80,
      }),
    )
  }

  const localSegments = Array.isArray(normalizedLocalSession.data.scriptSegments)
    ? normalizedLocalSession.data.scriptSegments
    : []
  const incomingSegments = Array.isArray(normalizedIncomingSession.data.scriptSegments)
    ? normalizedIncomingSession.data.scriptSegments
    : []

  const segmentDiffs: EditorConflictSegmentDiffPreview[] = []
  const totalSegments = Math.max(localSegments.length, incomingSegments.length)

  for (let index = 0; index < totalSegments; index += 1) {
    const localSegment = localSegments[index]
    const incomingSegment = incomingSegments[index]

    if (!localSegment && !incomingSegment) {
      continue
    }

    const changeType: EditorConflictSegmentDiffPreview['changeType'] =
      !localSegment
        ? 'added'
        : !incomingSegment
          ? 'removed'
          : 'modified'

    const segmentFieldDiffs = SCRIPT_EDITOR_CONFLICT_SEGMENT_FIELDS.reduce<EditorConflictFieldDiffPreview[]>(
      (acc, field) => {
        const currentValue = localSegment?.[field.key]
        const nextValue = incomingSegment?.[field.key]

        if (changeType === 'modified' && isDiffValueEqual(currentValue, nextValue)) {
          return acc
        }

        if (changeType === 'added' && !hasMeaningfulDiffValue(nextValue)) {
          return acc
        }

        if (changeType === 'removed' && !hasMeaningfulDiffValue(currentValue)) {
          return acc
        }

        acc.push(
          buildEditorConflictFieldDiffPreview({
            key: field.key,
            label: field.label,
            currentValue,
            incomingValue: nextValue,
            maxLength: field.maxLength,
          }),
        )
        return acc
      },
      [],
    )

    if (segmentFieldDiffs.length === 0) {
      if (changeType === 'modified') {
        continue
      }

      segmentFieldDiffs.push(
        buildEditorConflictFieldDiffPreview({
          key: 'segment_presence',
          label: '片段存在状态',
          currentValue: localSegment ? '本页存在' : '本页缺失',
          incomingValue: incomingSegment ? '对方存在' : '对方缺失',
          maxLength: 24,
        }),
      )
    }

    segmentDiffs.push({
      index,
      speaker: resolveScriptSegmentSpeaker(incomingSegment || localSegment),
      changeType,
      fieldDiffs: segmentFieldDiffs,
    })
  }

  if (fieldDiffs.length === 0 && segmentDiffs.length === 0) {
    return null
  }

  return {
    fieldDiffs,
    segmentDiffs,
  }
}
