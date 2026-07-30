import {
  useEffect,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from 'react'

import { STAGE_CONFIG } from './constants'
import { normalizeNarrationStyleValue, type NarrationStyleId } from './narrationStyles'
import type {
  AudioOutputFormat,
  Chapter,
  ScriptReviewDialogData,
  StageConfig,
  StageInfo,
} from './types'
import {
  buildComparableAudiobookPageSessionPayload,
  buildDeleteChapterSessionTarget,
  hasDeleteChapterDialogPageSessionState,
  hasPersistableAudiobookPageSession,
  hasProjectBoundAudiobookPageSessionState,
  hasRouteScopedAudiobookPageSessionState,
  resolveDesignPreviewTextDraft,
} from './pageSessionUtils'
import {
  buildStoredComparableAudiobookPageSessionPayload,
  readStoredAudiobookPageSession,
  removeStoredAudiobookPageSession,
  writeStoredAudiobookPageSession,
} from './pageSessionStorageUtils'

type StageMetricsDialogData = {
  stage: StageConfig
  info: StageInfo
} | null

interface UseAudiobookPageSessionSyncParams {
  pageSessionStorageKey: string
  sessionHydratedRef: MutableRefObject<boolean>
  restoredPageSessionProjectRef: MutableRefObject<number | null>
  restoredProjectBoundPageSessionKeyRef: MutableRefObject<string | null>
  skipNextPageSessionPersistRef: MutableRefObject<boolean>
  routeProjectId: number | null
  selectedProjectId: number | null
  audiobookProjectId?: number | null
  currentAudiobookProjectId: number | null
  chapters: Chapter[]
  browserPlayerOpen: boolean
  handleOpenBrowserPlayer: () => Promise<void> | void
  showHistory: boolean
  setShowHistory: Dispatch<SetStateAction<boolean>>
  scriptOnlyMode: boolean
  setScriptOnlyMode: Dispatch<SetStateAction<boolean>>
  narrationStyle: NarrationStyleId
  setNarrationStyle: Dispatch<SetStateAction<NarrationStyleId>>
  narrationStylePrompt: string
  setNarrationStylePrompt: Dispatch<SetStateAction<string>>
  outputFormat: AudioOutputFormat
  setOutputFormat: Dispatch<SetStateAction<AudioOutputFormat>>
  scriptReviewDialogOpen: boolean
  setScriptReviewDialogOpen: Dispatch<SetStateAction<boolean>>
  scriptReviewData: ScriptReviewDialogData | null
  setScriptReviewData: Dispatch<SetStateAction<ScriptReviewDialogData | null>>
  scriptReviewSelectedIssueIndex: number | null
  setScriptReviewSelectedIssueIndex: Dispatch<SetStateAction<number | null>>
  scriptReviewSelectedSegmentIndex: number | null
  setScriptReviewSelectedSegmentIndex: Dispatch<SetStateAction<number | null>>
  stageMetricsDialogOpen: boolean
  setStageMetricsDialogOpen: Dispatch<SetStateAction<boolean>>
  stageMetricsData: StageMetricsDialogData
  setStageMetricsData: Dispatch<SetStateAction<StageMetricsDialogData>>
  deleteChapterDialogOpen: boolean
  setDeleteChapterDialogOpen: Dispatch<SetStateAction<boolean>>
  selectedChapterForMenu: Chapter | null
  setSelectedChapterForMenu: Dispatch<SetStateAction<Chapter | null>>
  deleteChapterReason: string
  setDeleteChapterReason: Dispatch<SetStateAction<string>>
  deleteChapterFiles: boolean
  setDeleteChapterFiles: Dispatch<SetStateAction<boolean>>
  cloneRecordDialogOpen: boolean
  setCloneRecordDialogOpen: Dispatch<SetStateAction<boolean>>
  cloneName: string
  setCloneName: Dispatch<SetStateAction<string>>
  cloneUrl: string
  setCloneUrl: Dispatch<SetStateAction<string>>
  designName: string
  setDesignName: Dispatch<SetStateAction<string>>
  designPrompt: string
  setDesignPrompt: Dispatch<SetStateAction<string>>
  designPreviewText: string
  setDesignPreviewText: Dispatch<SetStateAction<string>>
  newProjectDialogOpen: boolean
  setNewProjectDialogOpen: Dispatch<SetStateAction<boolean>>
  newProjectTitle: string
  setNewProjectTitle: Dispatch<SetStateAction<string>>
  newProjectText: string
  setNewProjectText: Dispatch<SetStateAction<string>>
}

export const useAudiobookPageSessionSync = ({
  pageSessionStorageKey,
  sessionHydratedRef,
  restoredPageSessionProjectRef,
  restoredProjectBoundPageSessionKeyRef,
  skipNextPageSessionPersistRef,
  routeProjectId,
  selectedProjectId,
  audiobookProjectId,
  currentAudiobookProjectId,
  chapters,
  browserPlayerOpen,
  handleOpenBrowserPlayer,
  showHistory,
  setShowHistory,
  scriptOnlyMode,
  setScriptOnlyMode,
  narrationStyle,
  setNarrationStyle,
  narrationStylePrompt,
  setNarrationStylePrompt,
  outputFormat,
  setOutputFormat,
  scriptReviewDialogOpen,
  setScriptReviewDialogOpen,
  scriptReviewData,
  setScriptReviewData,
  scriptReviewSelectedIssueIndex,
  setScriptReviewSelectedIssueIndex,
  scriptReviewSelectedSegmentIndex,
  setScriptReviewSelectedSegmentIndex,
  stageMetricsDialogOpen,
  setStageMetricsDialogOpen,
  stageMetricsData,
  setStageMetricsData,
  deleteChapterDialogOpen,
  setDeleteChapterDialogOpen,
  selectedChapterForMenu,
  setSelectedChapterForMenu,
  deleteChapterReason,
  setDeleteChapterReason,
  deleteChapterFiles,
  setDeleteChapterFiles,
  cloneRecordDialogOpen,
  setCloneRecordDialogOpen,
  cloneName,
  setCloneName,
  cloneUrl,
  setCloneUrl,
  designName,
  setDesignName,
  designPrompt,
  setDesignPrompt,
  designPreviewText,
  setDesignPreviewText,
  newProjectDialogOpen,
  setNewProjectDialogOpen,
  newProjectTitle,
  setNewProjectTitle,
  newProjectText,
  setNewProjectText,
}: UseAudiobookPageSessionSyncParams) => {
  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !routeProjectId
    ) {
      return
    }

    if (restoredPageSessionProjectRef.current === routeProjectId) {
      return
    }

    const storedEntry = readStoredAudiobookPageSession(sessionStorage, pageSessionStorageKey)
    if (!storedEntry.hasStoredPayload) {
      restoredPageSessionProjectRef.current = routeProjectId
      return
    }

    const savedPageSession = storedEntry.session
    if (!savedPageSession || savedPageSession.projectId !== routeProjectId) {
      removeStoredAudiobookPageSession(sessionStorage, pageSessionStorageKey)
      restoredPageSessionProjectRef.current = routeProjectId
      return
    }

    if (hasRouteScopedAudiobookPageSessionState(savedPageSession)) {
      skipNextPageSessionPersistRef.current = true
    }

    setShowHistory(Boolean(savedPageSession.showHistory))
    setScriptOnlyMode(Boolean(savedPageSession.scriptOnlyMode))
    setNarrationStyle(normalizeNarrationStyleValue(savedPageSession.narrationStyle))
    setNarrationStylePrompt(savedPageSession.narrationStylePrompt || '')
    setOutputFormat(savedPageSession.outputFormat || 'mp3')
    setCloneRecordDialogOpen(Boolean(savedPageSession.cloneRecordDialogOpen))
    setCloneName(savedPageSession.cloneName || '')
    setCloneUrl(savedPageSession.cloneUrl || '')
    setDesignName(savedPageSession.designName || '')
    setDesignPrompt(savedPageSession.designPrompt || '')
    setDesignPreviewText(resolveDesignPreviewTextDraft(savedPageSession.designPreviewText))
    setNewProjectDialogOpen(Boolean(savedPageSession.newProjectDialogOpen))
    setNewProjectTitle(savedPageSession.newProjectTitle || '')
    setNewProjectText(savedPageSession.newProjectText || '')
    restoredPageSessionProjectRef.current = routeProjectId
  }, [
    pageSessionStorageKey,
    routeProjectId,
    selectedProjectId,
    sessionHydratedRef,
    restoredPageSessionProjectRef,
    skipNextPageSessionPersistRef,
    setShowHistory,
    setScriptOnlyMode,
    setNarrationStyle,
    setNarrationStylePrompt,
    setOutputFormat,
    setCloneRecordDialogOpen,
    setCloneName,
    setCloneUrl,
    setDesignName,
    setDesignPrompt,
    setDesignPreviewText,
    setNewProjectDialogOpen,
    setNewProjectTitle,
    setNewProjectText,
  ])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !routeProjectId
      || !audiobookProjectId
    ) {
      return
    }

    const restoreKey = `${routeProjectId}:${audiobookProjectId}`
    if (restoredProjectBoundPageSessionKeyRef.current === restoreKey) {
      return
    }

    const storedEntry = readStoredAudiobookPageSession(sessionStorage, pageSessionStorageKey)
    if (!storedEntry.hasStoredPayload) {
      restoredProjectBoundPageSessionKeyRef.current = restoreKey
      return
    }

    const savedPageSession = storedEntry.session
    if (
      !savedPageSession
      || savedPageSession.projectId !== routeProjectId
      || (
        savedPageSession.audiobookProjectId
        && savedPageSession.audiobookProjectId !== audiobookProjectId
      )
    ) {
      restoredProjectBoundPageSessionKeyRef.current = restoreKey
      return
    }

    const shouldRestoreDeleteChapterDialog = hasDeleteChapterDialogPageSessionState(savedPageSession)
    if (hasProjectBoundAudiobookPageSessionState(savedPageSession)) {
      skipNextPageSessionPersistRef.current = true
    }

    if (savedPageSession.scriptReviewDialogOpen && savedPageSession.scriptReviewData) {
      setScriptReviewData(savedPageSession.scriptReviewData)
      setScriptReviewSelectedIssueIndex(savedPageSession.scriptReviewSelectedIssueIndex ?? null)
      setScriptReviewSelectedSegmentIndex(savedPageSession.scriptReviewSelectedSegmentIndex ?? null)
      setScriptReviewDialogOpen(true)
    }

    if (savedPageSession.stageMetricsDialogOpen && savedPageSession.stageMetricsData) {
      const stage = STAGE_CONFIG.find((item) => item.key === savedPageSession.stageMetricsData?.stageKey)
      if (stage) {
        setStageMetricsData({
          stage,
          info: savedPageSession.stageMetricsData.info,
        })
        setStageMetricsDialogOpen(true)
      }
    }

    if (savedPageSession.browserPlayerOpen && !browserPlayerOpen) {
      void handleOpenBrowserPlayer()
    }

    if (shouldRestoreDeleteChapterDialog && savedPageSession.deleteChapterTarget) {
      const targetChapter = chapters.find((chapter) => chapter.id === savedPageSession.deleteChapterTarget?.id)
      setSelectedChapterForMenu(
        targetChapter ?? {
          id: savedPageSession.deleteChapterTarget.id,
          chapter_number: savedPageSession.deleteChapterTarget.chapterNumber,
          title: savedPageSession.deleteChapterTarget.title,
          content: savedPageSession.deleteChapterTarget.contentPreview,
        },
      )
      setDeleteChapterReason(savedPageSession.deleteChapterReason || '')
      setDeleteChapterFiles(Boolean(savedPageSession.deleteChapterFiles))
      setDeleteChapterDialogOpen(true)
    }

    restoredProjectBoundPageSessionKeyRef.current = restoreKey
  }, [
    pageSessionStorageKey,
    routeProjectId,
    audiobookProjectId,
    chapters,
    browserPlayerOpen,
    handleOpenBrowserPlayer,
    sessionHydratedRef,
    restoredProjectBoundPageSessionKeyRef,
    skipNextPageSessionPersistRef,
    setScriptReviewData,
    setScriptReviewSelectedIssueIndex,
    setScriptReviewSelectedSegmentIndex,
    setScriptReviewDialogOpen,
    setStageMetricsData,
    setStageMetricsDialogOpen,
    setSelectedChapterForMenu,
    setDeleteChapterReason,
    setDeleteChapterFiles,
    setDeleteChapterDialogOpen,
  ])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !routeProjectId
    ) {
      return
    }

    if (skipNextPageSessionPersistRef.current) {
      skipNextPageSessionPersistRef.current = false
      return
    }

    const comparablePayload = buildComparableAudiobookPageSessionPayload({
      projectId: routeProjectId,
      audiobookProjectId: currentAudiobookProjectId ?? audiobookProjectId,
      browserPlayerOpen,
      showHistory,
      scriptOnlyMode,
      narrationStyle,
      narrationStylePrompt,
      outputFormat,
      scriptReviewDialogOpen,
      scriptReviewData,
      scriptReviewSelectedIssueIndex,
      scriptReviewSelectedSegmentIndex,
      stageMetricsDialogOpen,
      stageMetricsData: stageMetricsData
        ? {
            stageKey: stageMetricsData.stage.key,
            info: stageMetricsData.info,
          }
        : null,
      deleteChapterDialogOpen,
      deleteChapterTarget: buildDeleteChapterSessionTarget(selectedChapterForMenu),
      deleteChapterReason,
      deleteChapterFiles,
      cloneRecordDialogOpen,
      cloneName,
      cloneUrl,
      designName,
      designPrompt,
      designPreviewText,
      newProjectDialogOpen,
      newProjectTitle,
      newProjectText,
    })

    if (!hasPersistableAudiobookPageSession(comparablePayload)) {
      removeStoredAudiobookPageSession(sessionStorage, pageSessionStorageKey)
      return
    }

    const comparableStoredPayload = buildStoredComparableAudiobookPageSessionPayload(
      sessionStorage,
      pageSessionStorageKey,
    )
    const serializedComparablePayload = JSON.stringify(comparablePayload)
    if (comparableStoredPayload === serializedComparablePayload) {
      return
    }

    writeStoredAudiobookPageSession(sessionStorage, pageSessionStorageKey, comparablePayload)
  }, [
    pageSessionStorageKey,
    routeProjectId,
    currentAudiobookProjectId,
    audiobookProjectId,
    browserPlayerOpen,
    showHistory,
    scriptOnlyMode,
    narrationStyle,
    narrationStylePrompt,
    outputFormat,
    scriptReviewDialogOpen,
    scriptReviewData,
    scriptReviewSelectedIssueIndex,
    scriptReviewSelectedSegmentIndex,
    stageMetricsDialogOpen,
    stageMetricsData,
    deleteChapterDialogOpen,
    selectedChapterForMenu,
    deleteChapterReason,
    deleteChapterFiles,
    cloneRecordDialogOpen,
    cloneName,
    cloneUrl,
    designName,
    designPrompt,
    designPreviewText,
    newProjectDialogOpen,
    newProjectTitle,
    newProjectText,
    sessionHydratedRef,
    skipNextPageSessionPersistRef,
  ])
}
