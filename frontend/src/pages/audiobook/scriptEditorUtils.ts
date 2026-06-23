import type {
  GenerateAudioFromScriptsPayload,
  UpdateAudiobookChapterScriptPayload,
} from '../../services/api'
import type {
  Chapter,
  AudioOutputFormat,
  ScriptEditorChapterRef,
  ScriptEditorStateData,
  ScriptSegment,
  ScriptSegmentTiming,
  SmartChunkPreviewResult,
  SmartChunkPreviewStats,
  TimelineClipEditMap,
  TtsModel,
} from './types'
import type { NarrationStyleId } from './narrationStyles'
import { normalizeScriptReview } from './utils'

type ScriptSaveStatus = NonNullable<UpdateAudiobookChapterScriptPayload['script_status']>

const normalizeSegmentTimings = (raw: unknown): ScriptSegmentTiming[] => {
  if (!Array.isArray(raw)) {
    return []
  }

  return raw.flatMap((item) => {
    const timing = item && typeof item === 'object' ? item as Record<string, unknown> : {}
    const index = Number(timing.index)
    const start = Number(timing.start)
    if (!Number.isInteger(index) || index < 0 || !Number.isFinite(start) || start < 0) {
      return []
    }

    const end = Number(timing.end)
    const duration = Number(timing.duration)
    return [{
      index,
      start,
      end: Number.isFinite(end) && end >= start ? end : null,
      duration: Number.isFinite(duration) && duration > 0 ? duration : null,
    }]
  })
}

export const buildScriptEditorChapterRef = (
  chapterId: number,
  chapters: readonly Pick<Chapter, 'id' | 'chapter_number' | 'title'>[],
): ScriptEditorChapterRef => {
  const chapter = chapters.find((item) => item.id === chapterId)
  return chapter
    ? { chapterId, title: `第${chapter.chapter_number}章 - ${chapter.title}` }
    : { chapterId, title: `章节 ${chapterId}` }
}

export const normalizeAudiobookChapterScriptData = (
  raw: unknown,
): ScriptEditorStateData => {
  const data = raw && typeof raw === 'object'
    ? raw as {
        script_status?: unknown
        script_segments?: unknown
        script_review?: unknown
        chapter_audio_available?: unknown
        chapter_audio_url?: unknown
        segment_timings?: unknown
      }
    : {}

  return {
    scriptStatus: typeof data.script_status === 'string' && data.script_status
      ? data.script_status
      : 'pending',
    scriptSegments: Array.isArray(data.script_segments)
      ? data.script_segments as ScriptSegment[]
      : [],
    chapterAudioAvailable: data.chapter_audio_available === true,
    chapterAudioUrl: typeof data.chapter_audio_url === 'string'
      ? data.chapter_audio_url
      : '',
    segmentTimings: normalizeSegmentTimings(data.segment_timings),
    scriptReview: normalizeScriptReview(data.script_review),
  }
}

export const buildUpdateChapterScriptPayload = (
  scriptSegments: readonly ScriptSegment[],
  nextStatus?: ScriptSaveStatus,
): UpdateAudiobookChapterScriptPayload => {
  const payload: UpdateAudiobookChapterScriptPayload = {
    script_segments: [...scriptSegments],
  }
  if (nextStatus) {
    payload.script_status = nextStatus
  }
  return payload
}

export const buildGenerateAudioFromScriptPayload = ({
  chapterId,
  ttsModel,
  narrationStyle,
  narrationStylePrompt,
  outputFormat,
  generateSubtitle,
  timelineEdits,
}: {
  chapterId?: number
  ttsModel: TtsModel
  narrationStyle: NarrationStyleId
  narrationStylePrompt: string
  outputFormat: AudioOutputFormat
  generateSubtitle: boolean
  timelineEdits?: TimelineClipEditMap
}): GenerateAudioFromScriptsPayload => ({
  ...(chapterId ? { chapter_ids: [chapterId] } : {}),
  tts_model: ttsModel,
  narration_style: narrationStyle,
  narration_style_prompt: narrationStyle === 'custom' && narrationStylePrompt.trim()
    ? narrationStylePrompt.trim()
    : undefined,
  output_format: outputFormat,
  generate_subtitle: generateSubtitle,
  ...(timelineEdits && Object.keys(timelineEdits).length > 0
    ? { timeline_edits: timelineEdits }
    : {}),
})

export const extractQueuedAudiobookJobId = (raw: unknown): string | null => {
  if (!raw || typeof raw !== 'object') {
    return null
  }
  const jobId = (raw as { job_id?: unknown }).job_id
  const normalizedJobId = typeof jobId === 'string' ? jobId.trim() : ''
  return normalizedJobId || null
}

const getNumberValue = (
  source: Record<string, unknown>,
  key: string,
  fallback = 0,
): number => {
  const value = source[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

const normalizeSmartChunkStats = (raw: unknown): SmartChunkPreviewStats => {
  const stats = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  return {
    total_chunks: getNumberValue(stats, 'total_chunks'),
    total_tokens: getNumberValue(stats, 'total_tokens'),
    avg_tokens_per_chunk: getNumberValue(stats, 'avg_tokens_per_chunk'),
    max_tokens_in_chunk: getNumberValue(stats, 'max_tokens_in_chunk'),
    min_tokens_in_chunk: getNumberValue(stats, 'min_tokens_in_chunk'),
  }
}

export const normalizeSmartChunkPreviewResponse = (
  raw: unknown,
): SmartChunkPreviewResult => {
  const data = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const chunks = Array.isArray(data.chunks) ? data.chunks as ScriptSegment[] : []
  const originalSegments = getNumberValue(data, 'original_segments')
  const chunkedSegments = getNumberValue(data, 'chunked_segments', chunks.length)
  const stats = normalizeSmartChunkStats(data.stats)
  const oversizedChunkCount = chunks.filter((chunk) => {
    const estimatedTokens = typeof (chunk as { estimated_tokens?: unknown }).estimated_tokens === 'number'
      ? (chunk as { estimated_tokens: number }).estimated_tokens
      : 0
    return estimatedTokens > 1800
  }).length

  return {
    originalSegments,
    chunkedSegments,
    totalTokens: getNumberValue(data, 'total_tokens', stats.total_tokens),
    chunks,
    stats,
    changed: originalSegments > 0 && chunkedSegments !== originalSegments,
    oversizedChunkCount,
  }
}
