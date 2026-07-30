import type { ChapterAudio } from './types'

export type AudiobookCompletionMode = 'full' | 'script_only'
export type ScriptStatusTone = 'success' | 'warning' | 'neutral'

export interface ScriptCompletionSummary {
  scriptChapterCount: number
  segmentCount: number
  reviewedChapterCount: number
  approvedChapterCount: number
  pendingApprovalCount: number
}

export const hasPlayableChapterAudio = (
  chapterAudios: readonly ChapterAudio[],
): boolean => chapterAudios.some((item) => Boolean(String(item.audio_path || '').trim()))

export const resolveAudiobookCompletionMode = ({
  requestedMode,
  chapterAudios,
}: {
  requestedMode: AudiobookCompletionMode
  chapterAudios: readonly ChapterAudio[]
}): AudiobookCompletionMode => {
  if (requestedMode === 'script_only') {
    return 'script_only'
  }
  if (hasPlayableChapterAudio(chapterAudios)) {
    return 'full'
  }
  return chapterAudios.some((item) => Boolean(item.has_script)) ? 'script_only' : 'full'
}

export const buildScriptCompletionSummary = (
  chapterAudios: readonly ChapterAudio[],
): ScriptCompletionSummary => {
  const scriptChapters = chapterAudios.filter((item) => Boolean(item.has_script))
  const approvedChapterCount = scriptChapters.filter(
    (item) => String(item.script_status || '').trim().toLowerCase() === 'approved',
  ).length

  return {
    scriptChapterCount: scriptChapters.length,
    segmentCount: scriptChapters.reduce(
      (total, item) => total + Math.max(0, Number(item.segment_count) || 0),
      0,
    ),
    reviewedChapterCount: scriptChapters.filter((item) => Boolean(item.has_review)).length,
    approvedChapterCount,
    pendingApprovalCount: scriptChapters.length - approvedChapterCount,
  }
}

export const resolveScriptReviewTargetChapterId = (
  chapterAudios: readonly ChapterAudio[],
): number | null => {
  const scriptChapters = chapterAudios.filter((item) => Boolean(item.has_script))
  const pendingChapter = scriptChapters.find(
    (item) => String(item.script_status || '').trim().toLowerCase() !== 'approved',
  )
  return pendingChapter?.chapter_id ?? scriptChapters[0]?.chapter_id ?? null
}

export const resolveScriptStatusPresentation = (
  status: string | null | undefined,
): { label: string; tone: ScriptStatusTone } => {
  const normalizedStatus = String(status || '').trim().toLowerCase()
  if (normalizedStatus === 'approved') {
    return { label: '已批准', tone: 'success' }
  }
  if (normalizedStatus === 'reviewed') {
    return { label: '待确认批准', tone: 'warning' }
  }
  return { label: '待审阅', tone: 'neutral' }
}
