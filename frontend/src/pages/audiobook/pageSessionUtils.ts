import type {
  AudiobookPageSessionState,
  Chapter,
  DeleteChapterSessionTarget,
  StageKey,
} from './types'
import { STAGE_KEYS } from './constants'
import {
  DEFAULT_NARRATION_STYLE,
  normalizeNarrationStyleValue,
} from './narrationStyles'
import { normalizePositiveId } from './editorSessionUtils'
import { normalizeScriptReview, normalizeStageEntry } from './utils'
import { DEFAULT_CHARACTER_VOICE_PREVIEW_TEXT } from './voicePreviewText'

export const DEFAULT_DESIGN_PREVIEW_TEXT = DEFAULT_CHARACTER_VOICE_PREVIEW_TEXT

export const hasCustomDesignPreviewText = (value: unknown): boolean => {
  if (typeof value !== 'string') {
    return false
  }
  const trimmedValue = value.trim()
  return Boolean(trimmedValue) && trimmedValue !== DEFAULT_DESIGN_PREVIEW_TEXT.trim()
}

export const resolveDesignPreviewTextDraft = (value: unknown): string =>
  typeof value === 'string' && value.trim()
    ? value
    : DEFAULT_DESIGN_PREVIEW_TEXT

const normalizeAudioOutputFormat = (value: unknown) =>
  value === 'wav' || value === 'm4b' ? value : 'mp3'

const normalizeOptionalZeroBasedIndex = (value: unknown): number | null => {
  const index = Number(value)
  return Number.isFinite(index) && index >= 0 ? Math.trunc(index) : null
}

export const normalizeDeleteChapterSessionTarget = (
  raw: unknown,
): DeleteChapterSessionTarget | null => {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const target = raw as Partial<DeleteChapterSessionTarget>
  const targetId = normalizePositiveId(target.id)
  if (!targetId) {
    return null
  }

  return {
    id: targetId,
    chapterNumber:
      typeof target.chapterNumber === 'number' && Number.isFinite(target.chapterNumber)
        ? Math.max(0, Math.trunc(target.chapterNumber))
        : 0,
    title: typeof target.title === 'string' ? target.title : '',
    contentPreview: typeof target.contentPreview === 'string' ? target.contentPreview : '',
  }
}

export const buildDeleteChapterSessionTarget = (
  chapter: Chapter | null | undefined,
): DeleteChapterSessionTarget | null => {
  if (!chapter?.id) {
    return null
  }

  return {
    id: chapter.id,
    chapterNumber: chapter.chapter_number,
    title: chapter.title || '',
    contentPreview: chapter.content ? chapter.content.slice(0, 100) : '',
  }
}

export const normalizeAudiobookPageSessionState = (
  raw: unknown,
): AudiobookPageSessionState | null => {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const session = raw as AudiobookPageSessionState
  const normalizedDeleteChapterTarget = normalizeDeleteChapterSessionTarget(session.deleteChapterTarget)
  const normalizedScriptReviewData =
    session.scriptReviewData && typeof session.scriptReviewData === 'object'
      ? {
          report: normalizeScriptReview(session.scriptReviewData.report),
          segments: Array.isArray(session.scriptReviewData.segments)
            ? session.scriptReviewData.segments
            : [],
          chapterId: normalizePositiveId(session.scriptReviewData.chapterId),
        }
      : null

  const rawStageMetricsData = session.stageMetricsData
  const normalizedStageMetricsData =
    rawStageMetricsData
    && typeof rawStageMetricsData === 'object'
    && typeof rawStageMetricsData.stageKey === 'string'
    && STAGE_KEYS.includes(rawStageMetricsData.stageKey as StageKey)
      ? {
          stageKey: rawStageMetricsData.stageKey as StageKey,
          info: normalizeStageEntry(rawStageMetricsData.info),
        }
      : null

  return {
    projectId: normalizePositiveId(session.projectId),
    audiobookProjectId: normalizePositiveId(session.audiobookProjectId),
    browserPlayerOpen: Boolean(session.browserPlayerOpen),
    showHistory: Boolean(session.showHistory),
    scriptOnlyMode: Boolean(session.scriptOnlyMode),
    forceRegenerateScript: false,
    narrationStyle: normalizeNarrationStyleValue(session.narrationStyle),
    narrationStylePrompt: typeof session.narrationStylePrompt === 'string' ? session.narrationStylePrompt : '',
    outputFormat: normalizeAudioOutputFormat(session.outputFormat),
    scriptReviewDialogOpen: Boolean(session.scriptReviewDialogOpen),
    scriptReviewData: normalizedScriptReviewData,
    scriptReviewSelectedIssueIndex: normalizeOptionalZeroBasedIndex(session.scriptReviewSelectedIssueIndex),
    scriptReviewSelectedSegmentIndex: normalizeOptionalZeroBasedIndex(session.scriptReviewSelectedSegmentIndex),
    stageMetricsDialogOpen: Boolean(session.stageMetricsDialogOpen),
    stageMetricsData: normalizedStageMetricsData,
    deleteChapterDialogOpen: Boolean(session.deleteChapterDialogOpen),
    deleteChapterTarget: normalizedDeleteChapterTarget,
    deleteChapterReason: typeof session.deleteChapterReason === 'string' ? session.deleteChapterReason : '',
    deleteChapterFiles: Boolean(session.deleteChapterFiles),
    cloneRecordDialogOpen: Boolean(session.cloneRecordDialogOpen),
    cloneName: typeof session.cloneName === 'string' ? session.cloneName : '',
    cloneUrl: typeof session.cloneUrl === 'string' ? session.cloneUrl : '',
    designName: typeof session.designName === 'string' ? session.designName : '',
    designPrompt: typeof session.designPrompt === 'string' ? session.designPrompt : '',
    designPreviewText: typeof session.designPreviewText === 'string' ? session.designPreviewText : '',
    newProjectDialogOpen: Boolean(session.newProjectDialogOpen),
    newProjectTitle: typeof session.newProjectTitle === 'string' ? session.newProjectTitle : '',
    newProjectText: typeof session.newProjectText === 'string' ? session.newProjectText : '',
    updatedAt: typeof session.updatedAt === 'string' ? session.updatedAt : undefined,
  }
}

export const buildComparableAudiobookPageSessionPayload = (
  session: Partial<AudiobookPageSessionState> | null | undefined,
) => {
  const normalizedSession = normalizeAudiobookPageSessionState(session)
  const normalizedDeleteChapterTarget = normalizedSession?.deleteChapterTarget ?? null
  const hasScriptReviewDialogState = Boolean(
    normalizedSession?.scriptReviewDialogOpen && normalizedSession?.scriptReviewData,
  )
  const hasDeleteChapterDialogState = Boolean(
    normalizedSession?.deleteChapterDialogOpen && normalizedDeleteChapterTarget,
  )
  const hasVoiceWorkbenchDraftState = Boolean(
    normalizedSession?.cloneRecordDialogOpen
      || normalizedSession?.cloneName
      || normalizedSession?.cloneUrl
      || normalizedSession?.designName
      || normalizedSession?.designPrompt
      || hasCustomDesignPreviewText(normalizedSession?.designPreviewText),
  )

  return {
    projectId: normalizedSession?.projectId ?? null,
    audiobookProjectId: normalizedSession?.audiobookProjectId ?? null,
    browserPlayerOpen: normalizedSession?.browserPlayerOpen ?? false,
    showHistory: normalizedSession?.showHistory ?? false,
    scriptOnlyMode: normalizedSession?.scriptOnlyMode ?? false,
    forceRegenerateScript: false,
    narrationStyle: normalizedSession?.narrationStyle ?? DEFAULT_NARRATION_STYLE,
    narrationStylePrompt: normalizedSession?.narrationStylePrompt ?? '',
    outputFormat: normalizedSession?.outputFormat ?? 'mp3',
    scriptReviewDialogOpen: hasScriptReviewDialogState,
    scriptReviewData:
      hasScriptReviewDialogState
        ? normalizedSession?.scriptReviewData ?? null
        : null,
    scriptReviewSelectedIssueIndex: hasScriptReviewDialogState
      ? normalizedSession?.scriptReviewSelectedIssueIndex ?? null
      : null,
    scriptReviewSelectedSegmentIndex: hasScriptReviewDialogState
      ? normalizedSession?.scriptReviewSelectedSegmentIndex ?? null
      : null,
    stageMetricsDialogOpen:
      Boolean(normalizedSession?.stageMetricsDialogOpen && normalizedSession?.stageMetricsData),
    stageMetricsData:
      normalizedSession?.stageMetricsDialogOpen && normalizedSession?.stageMetricsData
        ? normalizedSession.stageMetricsData
        : null,
    deleteChapterDialogOpen: hasDeleteChapterDialogState,
    deleteChapterTarget: hasDeleteChapterDialogState ? normalizedDeleteChapterTarget : null,
    deleteChapterReason: hasDeleteChapterDialogState ? normalizedSession?.deleteChapterReason ?? '' : '',
    deleteChapterFiles: Boolean(hasDeleteChapterDialogState && normalizedSession?.deleteChapterFiles),
    cloneRecordDialogOpen: hasVoiceWorkbenchDraftState ? normalizedSession?.cloneRecordDialogOpen ?? false : false,
    cloneName: hasVoiceWorkbenchDraftState ? normalizedSession?.cloneName ?? '' : '',
    cloneUrl: hasVoiceWorkbenchDraftState ? normalizedSession?.cloneUrl ?? '' : '',
    designName: hasVoiceWorkbenchDraftState ? normalizedSession?.designName ?? '' : '',
    designPrompt: hasVoiceWorkbenchDraftState ? normalizedSession?.designPrompt ?? '' : '',
    designPreviewText: hasVoiceWorkbenchDraftState
      ? resolveDesignPreviewTextDraft(normalizedSession?.designPreviewText)
      : '',
    newProjectDialogOpen: normalizedSession?.newProjectDialogOpen ?? false,
    newProjectTitle: normalizedSession?.newProjectTitle ?? '',
    newProjectText: normalizedSession?.newProjectText ?? '',
  }
}

export const hasRouteScopedAudiobookPageSessionState = (
  session: Partial<AudiobookPageSessionState> | null | undefined,
): boolean => {
  const normalizedSession = normalizeAudiobookPageSessionState(session)
  if (!normalizedSession) {
    return false
  }

  return Boolean(
    normalizedSession.showHistory
      || normalizedSession.scriptOnlyMode
      || normalizedSession.narrationStyle !== DEFAULT_NARRATION_STYLE
      || Boolean(normalizedSession.narrationStylePrompt)
      || normalizedSession.outputFormat !== 'mp3'
      || normalizedSession.cloneRecordDialogOpen
      || normalizedSession.cloneName
      || normalizedSession.cloneUrl
      || normalizedSession.designName
      || normalizedSession.designPrompt
      || hasCustomDesignPreviewText(normalizedSession.designPreviewText)
      || normalizedSession.newProjectDialogOpen
      || normalizedSession.newProjectTitle
      || normalizedSession.newProjectText,
  )
}

export const hasDeleteChapterDialogPageSessionState = (
  session: Partial<AudiobookPageSessionState> | null | undefined,
): boolean => {
  const normalizedSession = normalizeAudiobookPageSessionState(session)
  return Boolean(normalizedSession?.deleteChapterDialogOpen && normalizedSession.deleteChapterTarget)
}

export const hasProjectBoundAudiobookPageSessionState = (
  session: Partial<AudiobookPageSessionState> | null | undefined,
): boolean => {
  const normalizedSession = normalizeAudiobookPageSessionState(session)
  if (!normalizedSession) {
    return false
  }

  return Boolean(
    (normalizedSession.scriptReviewDialogOpen && normalizedSession.scriptReviewData)
      || (normalizedSession.stageMetricsDialogOpen && normalizedSession.stageMetricsData)
      || normalizedSession.browserPlayerOpen
      || hasDeleteChapterDialogPageSessionState(normalizedSession),
  )
}

export const hasPersistableAudiobookPageSession = (
  session: Partial<AudiobookPageSessionState> | null | undefined,
) => {
  const normalizedSession = normalizeAudiobookPageSessionState(session)
  if (!normalizedSession) {
    return false
  }

  return Boolean(
    normalizedSession.browserPlayerOpen
      || normalizedSession.showHistory
      || normalizedSession.scriptOnlyMode
      || normalizedSession.narrationStyle !== DEFAULT_NARRATION_STYLE
      || Boolean(normalizedSession.narrationStylePrompt)
      || normalizedSession.outputFormat !== 'mp3'
      || (normalizedSession.scriptReviewDialogOpen && normalizedSession.scriptReviewData)
      || (normalizedSession.stageMetricsDialogOpen && normalizedSession.stageMetricsData)
      || (normalizedSession.deleteChapterDialogOpen && normalizedSession.deleteChapterTarget)
      || normalizedSession.cloneRecordDialogOpen
      || normalizedSession.cloneName
      || normalizedSession.cloneUrl
      || normalizedSession.designName
      || normalizedSession.designPrompt
      || hasCustomDesignPreviewText(normalizedSession.designPreviewText)
      || normalizedSession.newProjectDialogOpen
      || normalizedSession.newProjectTitle
      || normalizedSession.newProjectText,
  )
}
