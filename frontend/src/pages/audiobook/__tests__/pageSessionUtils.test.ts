import { describe, expect, it } from 'vitest'

import {
  DEFAULT_DESIGN_PREVIEW_TEXT,
  buildComparableAudiobookPageSessionPayload,
  buildDeleteChapterSessionTarget,
  hasCustomDesignPreviewText,
  hasDeleteChapterDialogPageSessionState,
  hasPersistableAudiobookPageSession,
  hasProjectBoundAudiobookPageSessionState,
  hasRouteScopedAudiobookPageSessionState,
  normalizeAudiobookPageSessionState,
  resolveDesignPreviewTextDraft,
} from '../pageSessionUtils'

describe('audiobook page session utils', () => {
  it('handles default design preview text consistently', () => {
    expect(hasCustomDesignPreviewText(DEFAULT_DESIGN_PREVIEW_TEXT)).toBe(false)
    expect(hasCustomDesignPreviewText('  ')).toBe(false)
    expect(hasCustomDesignPreviewText('自定义试听文本')).toBe(true)
    expect(resolveDesignPreviewTextDraft('')).toBe(DEFAULT_DESIGN_PREVIEW_TEXT)
    expect(resolveDesignPreviewTextDraft('自定义试听文本')).toBe('自定义试听文本')
  })

  it('builds delete chapter session targets with bounded previews', () => {
    const target = buildDeleteChapterSessionTarget({
      id: 7,
      chapter_number: 3,
      title: '暗河',
      content: 'A'.repeat(120),
    })

    expect(target).toEqual({
      id: 7,
      chapterNumber: 3,
      title: '暗河',
      contentPreview: 'A'.repeat(100),
    })
    expect(buildDeleteChapterSessionTarget(null)).toBeNull()
  })

  it('normalizes page session state defensively', () => {
    const normalized = normalizeAudiobookPageSessionState({
      projectId: '11',
      audiobookProjectId: 22,
      browserPlayerOpen: 1,
      showHistory: true,
      scriptOnlyMode: true,
      forceRegenerateScript: true,
      narrationStyle: 'cinematic-story',
      narrationStylePrompt: '  自定义旁白语气  ',
      outputFormat: 'wav',
      generateSubtitle: false,
      scriptReviewDialogOpen: true,
      scriptReviewData: {
        report: { overall_score: 8, issues: [] },
        segments: [{ text: '片段文本' }],
      },
      scriptReviewSelectedIssueIndex: '2',
      scriptReviewSelectedSegmentIndex: 3.8,
      stageMetricsDialogOpen: true,
      stageMetricsData: {
        stageKey: 'tts_synthesis',
        info: {
          status: 'running',
          progress: 50,
          metrics: { completed: 3 },
        },
      },
      deleteChapterDialogOpen: true,
      deleteChapterTarget: {
        id: '5',
        chapterNumber: 2.8,
        title: '旧章',
        contentPreview: '预览',
      },
      deleteChapterReason: '重复章节',
      deleteChapterFiles: 1,
      cloneName: '复刻音',
      designPreviewText: '自定义试听文本',
      updatedAt: '2026-04-30T12:00:00.000Z',
    })

    expect(normalized).toMatchObject({
      projectId: 11,
      audiobookProjectId: 22,
      browserPlayerOpen: true,
      showHistory: true,
      scriptOnlyMode: true,
      forceRegenerateScript: true,
      narrationStyle: 'cinematic-story',
      narrationStylePrompt: '  自定义旁白语气  ',
      outputFormat: 'wav',
      generateSubtitle: false,
      scriptReviewDialogOpen: true,
      scriptReviewData: {
        report: { overall_score: 8, issues_count: 0 },
        segments: [{ text: '片段文本' }],
      },
      scriptReviewSelectedIssueIndex: 2,
      scriptReviewSelectedSegmentIndex: 3,
      stageMetricsDialogOpen: true,
      stageMetricsData: {
        stageKey: 'tts_synthesis',
        info: {
          status: 'running',
          progress: 50,
          metrics: { completed: 3 },
        },
      },
      deleteChapterDialogOpen: true,
      deleteChapterTarget: {
        id: 5,
        chapterNumber: 2,
        title: '旧章',
        contentPreview: '预览',
      },
      deleteChapterReason: '重复章节',
      deleteChapterFiles: true,
      cloneName: '复刻音',
      designPreviewText: '自定义试听文本',
      updatedAt: '2026-04-30T12:00:00.000Z',
    })
  })

  it('normalizes invalid page session stage data to null', () => {
    const normalized = normalizeAudiobookPageSessionState({
      stageMetricsDialogOpen: true,
      stageMetricsData: {
        stageKey: 'unsupported_stage',
        info: { status: 'running', progress: 80 },
      },
    })

    expect(normalized?.stageMetricsDialogOpen).toBe(true)
    expect(normalized?.stageMetricsData).toBeNull()
  })

  it('builds comparable page session payloads with transient empty UI state removed', () => {
    const comparable = buildComparableAudiobookPageSessionPayload({
      deleteChapterDialogOpen: true,
      deleteChapterReason: '无目标时应忽略',
      deleteChapterFiles: true,
      scriptReviewSelectedIssueIndex: 1,
      scriptReviewSelectedSegmentIndex: 2,
      cloneRecordDialogOpen: true,
      designPreviewText: DEFAULT_DESIGN_PREVIEW_TEXT,
      newProjectDialogOpen: true,
      newProjectTitle: '新项目',
    })

    expect(comparable).toMatchObject({
      deleteChapterDialogOpen: false,
      deleteChapterTarget: null,
      deleteChapterReason: '',
      deleteChapterFiles: false,
      scriptReviewDialogOpen: false,
      scriptReviewData: null,
      scriptReviewSelectedIssueIndex: null,
      scriptReviewSelectedSegmentIndex: null,
      cloneRecordDialogOpen: true,
      designPreviewText: DEFAULT_DESIGN_PREVIEW_TEXT,
      newProjectDialogOpen: true,
      newProjectTitle: '新项目',
      narrationStylePrompt: '',
      outputFormat: 'mp3',
      generateSubtitle: true,
      forceRegenerateScript: false,
    })
  })

  it('keeps selected script review issue and segment only with review dialog data', () => {
    const comparable = buildComparableAudiobookPageSessionPayload({
      scriptReviewDialogOpen: true,
      scriptReviewData: {
        report: { overall_score: 8 },
        segments: [{ text: '片段文本' }],
        chapterId: 12,
      },
      scriptReviewSelectedIssueIndex: 1,
      scriptReviewSelectedSegmentIndex: 3,
    })

    expect(comparable.scriptReviewDialogOpen).toBe(true)
    expect(comparable.scriptReviewSelectedIssueIndex).toBe(1)
    expect(comparable.scriptReviewSelectedSegmentIndex).toBe(3)
  })

  it('detects whether a page session has persistable state', () => {
    expect(hasPersistableAudiobookPageSession({})).toBe(false)
    expect(hasPersistableAudiobookPageSession({ designPreviewText: DEFAULT_DESIGN_PREVIEW_TEXT })).toBe(false)
    expect(hasPersistableAudiobookPageSession({ designPreviewText: '自定义试听文本' })).toBe(true)
    expect(hasPersistableAudiobookPageSession({ outputFormat: 'wav' })).toBe(true)
    expect(hasPersistableAudiobookPageSession({ generateSubtitle: false })).toBe(true)
    expect(hasPersistableAudiobookPageSession({ forceRegenerateScript: true })).toBe(true)
    expect(hasPersistableAudiobookPageSession({ browserPlayerOpen: true })).toBe(true)
    expect(hasPersistableAudiobookPageSession({
      deleteChapterDialogOpen: true,
      deleteChapterTarget: {
        id: 9,
        chapterNumber: 1,
        title: '待删章节',
        contentPreview: '',
      },
    })).toBe(true)
  })

  it('separates route-scoped and project-bound restore state', () => {
    expect(hasRouteScopedAudiobookPageSessionState({ showHistory: true })).toBe(true)
    expect(hasRouteScopedAudiobookPageSessionState({ designPreviewText: DEFAULT_DESIGN_PREVIEW_TEXT })).toBe(false)
    expect(hasRouteScopedAudiobookPageSessionState({ narrationStylePrompt: '自定义语气' })).toBe(true)
    expect(hasRouteScopedAudiobookPageSessionState({ outputFormat: 'm4b' })).toBe(true)
    expect(hasRouteScopedAudiobookPageSessionState({ generateSubtitle: false })).toBe(true)
    expect(hasRouteScopedAudiobookPageSessionState({ forceRegenerateScript: true })).toBe(true)
    expect(hasRouteScopedAudiobookPageSessionState({ newProjectTitle: 'new project' })).toBe(true)

    expect(hasDeleteChapterDialogPageSessionState({
      deleteChapterDialogOpen: true,
      deleteChapterTarget: {
        id: 1,
        chapterNumber: 2,
        title: 'chapter',
        contentPreview: 'preview',
      },
    })).toBe(true)
    expect(hasDeleteChapterDialogPageSessionState({ deleteChapterDialogOpen: true })).toBe(false)

    expect(hasProjectBoundAudiobookPageSessionState({ browserPlayerOpen: true })).toBe(true)
    expect(hasProjectBoundAudiobookPageSessionState({
      scriptReviewDialogOpen: true,
      scriptReviewData: {
        report: { overall_score: 8 },
        segments: [],
      },
    })).toBe(true)
    expect(hasProjectBoundAudiobookPageSessionState({ showHistory: true })).toBe(false)
  })
})
