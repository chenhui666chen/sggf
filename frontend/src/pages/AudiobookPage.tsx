/**
 * 耳畔星河 - 有声小说生成页面
 * 
 * 功能：
 * 1. 项目选择与章节管理
 * 2. 音色配置
 * 3. 有声书生成
 * 4. 进度监控
 * 5. 音频播放与下载
 */
import { useMemo } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import BrowserPlayer from '../components/audiobook/BrowserPlayer'
import AudiobookCompletionStep from './audiobook/AudiobookCompletionStep'
import AudiobookPageHeader from './audiobook/AudiobookPageHeader'
import AudiobookProgressStep from './audiobook/AudiobookProgressStep'
import AudiobookSetupStep from './audiobook/AudiobookSetupStep'
import AudiobookSnackbar from './audiobook/AudiobookSnackbar'
import AudiobookWorkflowStatus from './audiobook/AudiobookWorkflowStatus'
import ChapterActionsMenu from './audiobook/ChapterActionsMenu'
import ChapterDeleteConfirmDialog from './audiobook/ChapterDeleteConfirmDialog'
import HistoryDialog from './audiobook/HistoryDialog'
import ScriptQualityReviewDialog from './audiobook/ScriptQualityReviewDialog'
import ScriptEditorDialog from './audiobook/ScriptEditorDialog'
import TextProjectImportDialog from './audiobook/TextProjectImportDialog'
import StageMetricsDialog from './audiobook/StageMetricsDialog'
import { useAudiobookActiveTasks } from './audiobook/useAudiobookActiveTasks'
import { useAudiobookBrowserPlayer } from './audiobook/useAudiobookBrowserPlayer'
import { useAudiobookChapterSelectionActions } from './audiobook/useAudiobookChapterSelectionActions'
import { useAudiobookCharacterVoicePreview } from './audiobook/useAudiobookCharacterVoicePreview'
import { useAudiobookCharacterVoiceState } from './audiobook/useAudiobookCharacterVoiceState'
import { useAudiobookCharacterVoiceSettings } from './audiobook/useAudiobookCharacterVoiceSettings'
import { useAudiobookChapterAudioActions } from './audiobook/useAudiobookChapterAudioActions'
import { useAudiobookChapterDeleteActions } from './audiobook/useAudiobookChapterDeleteActions'
import { useAudiobookEditorSessionSync } from './audiobook/useAudiobookEditorSessionSync'
import { useAudiobookGenerationActions } from './audiobook/useAudiobookGenerationActions'
import { useAudiobookGenerationState } from './audiobook/useAudiobookGenerationState'
import { useAudiobookHistoryActions } from './audiobook/useAudiobookHistoryActions'
import { useAudiobookAudioPlayback } from './audiobook/useAudiobookAudioPlayback'
import { useAudiobookNewProjectAction } from './audiobook/useAudiobookNewProjectAction'
import { useAudiobookPageSessionSync } from './audiobook/useAudiobookPageSessionSync'
import { useAudiobookPageRefs } from './audiobook/useAudiobookPageRefs'
import { useAudiobookProjectDetailActions } from './audiobook/useAudiobookProjectDetailActions'
import { useAudiobookProjectExport } from './audiobook/useAudiobookProjectExport'
import { useAudiobookProjectSelectionRefSync } from './audiobook/useAudiobookProjectSelectionRefSync'
import { useAudiobookProjectState } from './audiobook/useAudiobookProjectState'
import {
  useAudiobookProjectSelectionActions,
} from './audiobook/useAudiobookProjectSelectionActions'
import { useAudiobookReviewDialogs } from './audiobook/useAudiobookReviewDialogs'
import { useAudiobookResumeCheckpoints } from './audiobook/useAudiobookResumeCheckpoints'
import { useAudiobookRouteProjectLoader } from './audiobook/useAudiobookRouteProjectLoader'
import { useAudiobookRuntimeState } from './audiobook/useAudiobookRuntimeState'
import { useAudiobookEditorConflictPreview } from './audiobook/useAudiobookEditorConflictPreview'
import { useAudiobookScriptEditorActions } from './audiobook/useAudiobookScriptEditorActions'
import { useAudiobookScriptEditorDraftState } from './audiobook/useAudiobookScriptEditorDraftState'
import { useAudiobookScriptEditorState } from './audiobook/useAudiobookScriptEditorState'
import { useAudiobookScriptEditorTransientReset } from './audiobook/useAudiobookScriptEditorTransientReset'
import { useAudiobookScriptSegmentEditActions } from './audiobook/useAudiobookScriptSegmentEditActions'
import { useAudiobookSegmentPreview } from './audiobook/useAudiobookSegmentPreview'
import { useAudiobookSegmentReviewActions } from './audiobook/useAudiobookSegmentReviewActions'
import { useAudiobookSetupState } from './audiobook/useAudiobookSetupState'
import { useAudiobookSnackbarState } from './audiobook/useAudiobookSnackbarState'
import { useAudiobookSourceChapterFocus } from './audiobook/useAudiobookSourceChapterFocus'
import { useAudiobookTaskFocusActions } from './audiobook/useAudiobookTaskFocusActions'
import { useAudiobookTaskPolling } from './audiobook/useAudiobookTaskPolling'
import { useAudiobookTaskPointsPrecheckState } from './audiobook/useAudiobookTaskPointsPrecheckState'
import { useAudiobookTaskSessionSync } from './audiobook/useAudiobookTaskSessionSync'
import { useAudiobookTextProjectImport } from './audiobook/useAudiobookTextProjectImport'
import { useAudiobookTtsModelReadyGuard } from './audiobook/useAudiobookTtsModelReadyGuard'
import { useAudiobookVoiceActions } from './audiobook/useAudiobookVoiceActions'
import { useAudiobookVoiceCatalog } from './audiobook/useAudiobookVoiceCatalog'
import { useCosyVoiceWorkbench } from './audiobook/useCosyVoiceWorkbench'
import {
  AUDIOBOOK_SESSION_STORAGE_KEY,
  buildPendingTaskStatus,
} from './audiobook/utils'
import {
  readUserAssetSourceAudiobookRouteRequest,
} from '../utils/userAssetSourceNavigation'
import {
  Box,
  Container,
} from '@mui/material'

const AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY = 'audiobook_editor_session_v1'
const AUDIOBOOK_EDITOR_SYNC_STORAGE_KEY = 'audiobook_editor_sync_v1'
const AUDIOBOOK_PAGE_SESSION_STORAGE_KEY = 'audiobook_page_session_v1'

const AudiobookPage = () => {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId: string }>()
  const [searchParams] = useSearchParams()
  const routeProjectId = useMemo(() => {
    const id = Number(projectId)
    return Number.isFinite(id) ? id : null
  }, [projectId])
  const sourceRouteRequest = useMemo(
    () => readUserAssetSourceAudiobookRouteRequest(searchParams),
    [searchParams],
  )
  const requestedAudiobookProjectId = sourceRouteRequest.audiobookProjectId
  const requestedSourceChapterId = sourceRouteRequest.chapterId
  const requestedSourceFocus = sourceRouteRequest.focus

  const {
    selectedProject,
    setSelectedProject,
    selectedProjectId,
    chapters,
    setChapters,
    selectedChapters,
    setSelectedChapters,
    audiobookProject,
    setAudiobookProject,
  } = useAudiobookProjectState()
  const {
    characterVoices,
    setCharacterVoicesForCurrentModel,
    updateCharacterVoicesForCurrentModel,
  } = useAudiobookCharacterVoiceState()
  const {
    audioFxConfig,
    setAudioFxConfig,
    scriptOnlyMode,
    setScriptOnlyMode,
    ttsModel,
    setTtsModel,
    narrationStyle,
    setNarrationStyle,
    narrationStylePrompt,
    setNarrationStylePrompt,
    outputFormat,
    setOutputFormat,
    generateSubtitle,
    setGenerateSubtitle,
  } = useAudiobookSetupState()
  const {
    scriptEditorDialogOpen,
    setScriptEditorDialogOpen,
    scriptEditorChapter,
    setScriptEditorChapter,
    scriptEditorData,
    setScriptEditorData,
    scriptEditorLoading,
    setScriptEditorLoading,
    smartChunkPreview,
    setSmartChunkPreview,
    smartChunkPreviewLoading,
    setSmartChunkPreviewLoading,
    timelineEdits,
    setTimelineEdits,
    editorCrossTabConflict,
    setEditorCrossTabConflict,
  } = useAudiobookScriptEditorState()
  const {
    playingChapter,
    setPlayingChapter,
    resumingChapterId,
    setResumingChapterId,
  } = useAudiobookRuntimeState()
  const {
    snackbar,
    setSnackbar,
    handleCloseSnackbar,
  } = useAudiobookSnackbarState()
  const {
    taskPointsPrecheckError,
    setTaskPointsPrecheckError,
    clearTaskPointsPrecheckError,
  } = useAudiobookTaskPointsPrecheckState()

  const {
    generating,
    setGenerating,
    taskStatuses,
    setTaskStatuses,
    currentTaskId,
    setCurrentTaskId,
    currentAudiobookProjectId,
    setCurrentAudiobookProjectId,
    lastGenerationMode,
    setLastGenerationMode,
    activeStep,
    setActiveStep,
    clearActiveGenerationState,
  } = useAudiobookGenerationState()
  const {
    browserPlayerOpen,
    browserPlayerLoading,
    browserPlayerData,
    resetBrowserPlayer,
    handleOpenBrowserPlayer,
    handleCloseBrowserPlayer,
  } = useAudiobookBrowserPlayer({
    audiobookProjectId: audiobookProject?.id,
    setSnackbar,
  })

  const {
    chapterMenuAnchor,
    selectedChapterForMenu,
    setSelectedChapterForMenu,
    deleteChapterDialogOpen,
    setDeleteChapterDialogOpen,
    deleteChapterReason,
    setDeleteChapterReason,
    deleteChapterFiles,
    setDeleteChapterFiles,
    deletingChapter,
    resetChapterDeleteState,
    handleOpenChapterMenu,
    handleCloseChapterMenu,
    handleOpenDeleteChapterDialog,
    handleCloseDeleteChapterDialog,
    handleDeleteChapter,
  } = useAudiobookChapterDeleteActions({
    setChapters,
    setSelectedChapters,
    setSnackbar,
  })

  const {
    ttsModelOptions,
    voicePresets,
    voiceCatalogMeta,
    voiceLoading,
    voiceError,
    voicePresetsByModel,
    currentVoicePresets,
    customVoicePresets,
    currentTtsModelOption,
    currentModelRequiresCustomVoice,
    currentModelHasUsableVoice,
    currentModelCatalogUnavailable,
    currentModelRuntimeUnavailable,
    showCustomVoiceWorkbench,
    voiceCatalogSummary,
    voiceCatalogNotice,
    voiceCatalogNoticeSeverity,
    refreshVoiceCatalog,
    fetchVoiceCatalog,
  } = useAudiobookVoiceCatalog({
    ttsModel,
    characterVoices,
  })

  const {
    reviewMode,
    setReviewMode,
    segmentReviews,
    setSegmentReviews,
    regeneratingSegments,
    recordingSegmentIndex,
    pendingSegmentRegenerations,
    resetSegmentReviewState,
    handleToggleReviewMode,
    handleReviewSegment,
    handleRegenerateSegment,
    handleStartSegmentVoiceRecording,
    handleStopSegmentVoiceRecording,
    handleApplySegmentRegenerationCandidate,
    handleDiscardSegmentRegenerationCandidate,
  } = useAudiobookSegmentReviewActions({
    audiobookProjectId: audiobookProject?.id,
    chapterId: scriptEditorChapter?.chapterId,
    ttsModel,
    setSnackbar,
    setScriptEditorData,
  })

  const {
    segmentDetailsOpen,
    setSegmentDetailsOpen,
    resetSegmentDetailsOpen,
    handleToggleSegmentDetails,
    handleChangeScriptSegmentText,
    handleUpdateScriptSegment,
  } = useAudiobookScriptSegmentEditActions({
    setScriptEditorData,
    setSmartChunkPreview,
  })

  const {
    editorConflictTimeLabel,
    editorConflictPreview,
    visibleEditorConflictSegmentDiffs,
    hiddenEditorConflictSegmentDiffCount,
  } = useAudiobookEditorConflictPreview({
    chapterId: scriptEditorChapter?.chapterId,
    reviewMode,
    segmentDetailsOpen,
    segmentReviews,
    timelineEdits,
    scriptEditorData,
    editorCrossTabConflict,
  })

  const {
    playExternalUrl,
    playManagedBlob,
    stopManagedPlayback,
  } = useAudiobookAudioPlayback()

  const {
    collectingChapterIds,
    handleDownloadAudio,
    handleCollectChapterAudio,
    handlePlayAudio,
  } = useAudiobookChapterAudioActions({
    audiobookProject,
    selectedProject,
    routeProjectId,
    chapters,
    outputFormat,
    playingChapter,
    setPlayingChapter,
    playManagedBlob,
    stopManagedPlayback,
    setSnackbar,
  })

  const {
    previewingCharacterId,
    handlePreviewCharacterVoice,
  } = useAudiobookCharacterVoicePreview({
    ttsModel,
    playingChapter,
    setPlayingChapter,
    playManagedBlob,
    playExternalUrl,
    setSnackbar,
  })

  const {
    sessionHydratedRef,
    sessionTabIdRef,
    lastSessionTimestampRef,
    restoredEditorSessionKeyRef,
    restoredPageSessionProjectRef,
    restoredProjectBoundPageSessionKeyRef,
    handledSourceChapterKeyRef,
    skipNextPageSessionPersistRef,
    dismissedEditorConflictSignatureRef,
    ttsModelRef,
    handleSelectProjectRef,
    navigationTypeRef,
  } = useAudiobookPageRefs(ttsModel)
  const {
    segmentPreviewingIndex,
    segmentPreviewingType,
    segmentAudioUrls,
    resetSegmentPreviewState,
    handlePreviewScriptSegmentAudio,
  } = useAudiobookSegmentPreview({
    audiobookProjectId: audiobookProject?.id,
    chapterId: scriptEditorChapter?.chapterId,
    chapterAudioAvailable: scriptEditorData?.chapterAudioAvailable,
    segmentTimings: scriptEditorData?.segmentTimings,
    pendingSegmentRegenerations,
    playingChapter,
    setPlayingChapter,
    playExternalUrl,
    stopManagedPlayback,
    onResetSegmentDetails: resetSegmentDetailsOpen,
    setSnackbar,
  })

  const { resetScriptEditorTransientState } = useAudiobookScriptEditorTransientReset({
    resetSegmentPreviewState,
    resetSegmentReviewState,
    setEditorCrossTabConflict,
    dismissedEditorConflictSignatureRef,
  })

  const {
    loadingHistory,
    historyProjects,
    showHistory,
    setShowHistory,
    handleOpenHistoryPanel,
    handleCloseHistoryPanel,
    handleViewHistory,
    handleDeleteHistory,
  } = useAudiobookHistoryActions({
    selectedProjectId,
    clearActiveGenerationState,
    resetBrowserPlayer,
    setAudiobookProject,
    setCurrentAudiobookProjectId,
    setActiveStep,
    setSnackbar,
  })

  const {
    trackedAudiobookProjectIds,
    trackedAudiobookProjectIdKey,
    activeProjectTasks,
    hasActiveM4bExportTask,
    hasActiveAudacityExportTask,
    persistedActiveTaskRefs,
    activeTaskStatus,
  } = useAudiobookActiveTasks({
    historyProjects,
    audiobookProjectId: audiobookProject?.id,
    currentAudiobookProjectId,
    currentTaskId,
    taskStatuses,
  })

  const {
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
    handleOpenScriptReviewDialog,
    handleOpenScriptReviewFromApi,
    handleCloseScriptReviewDialog,
    handleOpenStageMetricsDialog,
    handleCloseStageMetricsDialog,
  } = useAudiobookReviewDialogs({
    activeTaskStatus,
    setSnackbar,
  })

  const progressTaskStatus = useMemo(
    () => activeTaskStatus ?? buildPendingTaskStatus({
      taskId: 'pending',
      audiobookProjectId: currentAudiobookProjectId || 0,
    }),
    [activeTaskStatus, currentAudiobookProjectId],
  )

  const {
    cloneName,
    setCloneName,
    cloneUrl,
    setCloneUrl,
    cloneLoading,
    cloneUploading,
    cloneRecording,
    cloneRecordDialogOpen,
    setCloneRecordDialogOpen,
    cloneDeletingId,
    cloneError,
    cloneSuccess,
    designName,
    setDesignName,
    designPrompt,
    setDesignPrompt,
    designPreviewText,
    setDesignPreviewText,
    designPreviewAudioUrl,
    designPreviewVoiceId,
    designLoading,
    designError,
    designSuccess,
    customVoicePreviewingId,
    autoAssigningVoices,
    handleCreateCloneVoice,
    handleCreateDesignVoice,
    handlePreviewDesignVoice,
    handlePreviewCustomVoice,
    handleDeleteCustomVoice,
    handleUploadCloneAudio,
    handleStartCloneRecording,
    handleStopCloneRecording,
    handleOpenCloneRecordDialog,
    handleCloseCloneRecordDialog,
    handleAutoAssignVoices,
  } = useAudiobookVoiceActions({
    selectedProjectId,
    routeProjectId,
    ttsModel,
    characterVoices,
    setCharacterVoicesForCurrentModel,
    updateCharacterVoicesForCurrentModel,
    refreshVoiceCatalog,
    playExternalUrl,
    playManagedBlob,
    setSnackbar,
  })
  const cosyVoiceWorkbench = useCosyVoiceWorkbench({
    cloneName,
    cloneUrl,
    cloneLoading,
    cloneUploading,
    cloneRecording,
    cloneDeletingId,
    cloneError,
    cloneSuccess,
    cloneRecordDialogOpen,
    designName,
    designPrompt,
    designPreviewAudioUrl,
    designPreviewVoiceId,
    designLoading,
    designError,
    designSuccess,
    customVoicePreviewingId,
    customVoicePresets,
    onCloneNameChange: setCloneName,
    onCloneUrlChange: setCloneUrl,
    onCreateCloneVoice: handleCreateCloneVoice,
    onOpenCloneRecordDialog: handleOpenCloneRecordDialog,
    onUploadCloneAudio: handleUploadCloneAudio,
    onDesignNameChange: setDesignName,
    onDesignPromptChange: setDesignPrompt,
    onCreateDesignVoice: handleCreateDesignVoice,
    onPreviewDesignVoice: handlePreviewDesignVoice,
    onPreviewCustomVoice: handlePreviewCustomVoice,
    onDeleteCustomVoice: handleDeleteCustomVoice,
    onCloseCloneRecordDialog: handleCloseCloneRecordDialog,
    onStartCloneRecording: handleStartCloneRecording,
    onStopCloneRecording: handleStopCloneRecording,
  })

  const { ensureCurrentTtsModelReady } = useAudiobookTtsModelReadyGuard({
    modelLabel: currentTtsModelOption?.name || ttsModel,
    requiresCustomVoice: currentModelRequiresCustomVoice,
    hasUsableVoice: currentModelHasUsableVoice,
    catalogUnavailable: currentModelCatalogUnavailable,
    catalogError: currentTtsModelOption?.catalogError,
    runtimeUnavailable: currentModelRuntimeUnavailable,
    runtimeError: currentTtsModelOption?.runtimeError,
    setSnackbar,
  })

  const { refreshAudiobookProjectDetail } = useAudiobookProjectDetailActions({
    setAudiobookProject,
  })

  const {
    formatActiveTaskLabel,
    handleFocusActiveProjectTask,
    focusAudiobookTask,
    activateQueuedAudiobookTask,
  } = useAudiobookTaskFocusActions({
    chapters,
    currentAudiobookProjectDetailId: audiobookProject?.id,
    refreshAudiobookProjectDetail,
    setCurrentTaskId,
    setCurrentAudiobookProjectId,
    setGenerating,
    setActiveStep,
    setTaskStatuses,
    setLastGenerationMode,
    setSnackbar,
  })

  const { handleCreateNewAudiobookProject } = useAudiobookNewProjectAction({
    clearActiveGenerationState,
    resetBrowserPlayer,
    stopManagedPlayback,
    setActiveStep,
    setSelectedProject,
    setAudiobookProject,
    setTaskPointsPrecheckError,
    setPlayingChapter,
  })

  const {
    currentChapterAudios,
    hasChapterAudios,
    resumeCheckpoints,
    setResumeCheckpoints,
    resumeCheckpointLoading,
    resumableChapterEntries,
  } = useAudiobookResumeCheckpoints({
    audiobookProject,
    chapters,
  })

  useAudiobookRouteProjectLoader({
    routeProjectId,
    navigateTo: navigate,
    editorSessionStorageKey: AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY,
    pageSessionStorageKey: AUDIOBOOK_PAGE_SESSION_STORAGE_KEY,
    navigationTypeRef,
    sessionHydratedRef,
    restoredEditorSessionKeyRef,
    restoredPageSessionProjectRef,
    restoredProjectBoundPageSessionKeyRef,
    lastSessionTimestampRef,
    ttsModelRef,
    handleSelectProjectRef,
    setTtsModel,
    setActiveStep,
    setTaskStatuses,
    setCurrentAudiobookProjectId,
    setAudiobookProject,
    setCurrentTaskId,
    setGenerating,
    setSnackbar,
  })

  const {
    loadingCharacters,
    handleSelectProject,
  } = useAudiobookProjectSelectionActions({
    ttsModel,
    voicePresetsByModel,
    clearActiveGenerationState,
    resetBrowserPlayer,
    resetChapterDeleteState,
    setSelectedProject,
    setTaskPointsPrecheckError,
    setCharacterVoicesForCurrentModel,
    setAudiobookProject,
    setChapters,
    setSelectedChapters,
    setAudioFxConfig,
    setActiveStep,
    setSnackbar,
  })

  const {
    newProjectDialogOpen,
    setNewProjectDialogOpen,
    newProjectTitle,
    setNewProjectTitle,
    newProjectText,
    setNewProjectText,
    creatingFromBook,
    handleOpenNewProjectDialog,
    handleCloseNewProjectDialog,
    handleCreateProjectFromText,
  } = useAudiobookTextProjectImport({
    handleSelectProject,
    setActiveStep,
    setSnackbar,
  })

  useAudiobookProjectSelectionRefSync(handleSelectProjectRef, handleSelectProject)

  const { removeCurrentEditorSyncEntry } = useAudiobookEditorSessionSync({
    editorSessionStorageKey: AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY,
    editorSyncStorageKey: AUDIOBOOK_EDITOR_SYNC_STORAGE_KEY,
    sessionHydratedRef,
    sessionTabIdRef,
    restoredEditorSessionKeyRef,
    dismissedEditorConflictSignatureRef,
    selectedProjectId,
    audiobookProjectId: audiobookProject?.id,
    scriptEditorDialogOpen,
    scriptEditorChapter,
    scriptEditorData,
    reviewMode,
    segmentDetailsOpen,
    segmentReviews,
    timelineEdits,
    setEditorCrossTabConflict,
  })

  const {
    handleOpenScriptEditor,
    handleCloseScriptEditorDialog,
    handleSaveScript,
    handlePreviewSmartChunking,
  } = useAudiobookScriptEditorActions({
    audiobookProject,
    chapters,
    scriptEditorChapter,
    scriptEditorData,
    timelineEdits,
    ttsModel,
    narrationStyle,
    narrationStylePrompt,
    outputFormat,
    generateSubtitle,
    ensureCurrentTtsModelReady,
    resetScriptEditorTransientState,
    resetSegmentPreviewState,
    removeCurrentEditorSyncEntry,
    stopManagedPlayback,
    activateQueuedAudiobookTask,
    setScriptEditorDialogOpen,
    setScriptEditorChapter,
    setScriptEditorData,
    setScriptEditorLoading,
    setSmartChunkPreview,
    setSmartChunkPreviewLoading,
    setTimelineEdits,
    setTaskPointsPrecheckError,
    setSnackbar,
  })

  const {
    handleApplyIncomingEditorDraft,
    handleKeepLocalEditorDraft,
  } = useAudiobookScriptEditorDraftState({
    editorSessionStorageKey: AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY,
    sessionHydratedRef,
    restoredEditorSessionKeyRef,
    dismissedEditorConflictSignatureRef,
    selectedProjectId,
    audiobookProjectId: audiobookProject?.id,
    chapters,
    scriptEditorDialogOpen,
    editorCrossTabConflict,
    setScriptEditorDialogOpen,
    setScriptEditorChapter,
    setScriptEditorData,
    setScriptEditorLoading,
    setReviewMode,
    setSegmentReviews,
    setSegmentDetailsOpen,
    setTimelineEdits,
    setEditorCrossTabConflict,
    setSnackbar,
  })

  const {
    exportingProjectM4b,
    exportingProjectAudacity,
    handleExportProjectM4b,
    handleExportProjectAudacity,
    downloadCompletedProjectExport,
  } = useAudiobookProjectExport({
    audiobookProject,
    projectTitle: selectedProject?.title,
    activateQueuedAudiobookTask,
    setSnackbar,
  })

  useAudiobookTaskSessionSync({
    sessionStorageKey: AUDIOBOOK_SESSION_STORAGE_KEY,
    sessionHydratedRef,
    sessionTabIdRef,
    lastSessionTimestampRef,
    ttsModelRef,
    selectedProjectId,
    currentAudiobookProjectId,
    currentTaskId,
    persistedActiveTaskRefs,
    selectedChapters,
    activeStep,
    generating,
    ttsModel,
    chapters,
    currentAudiobookProjectDetailId: audiobookProject?.id,
    setSelectedChapters,
    setActiveStep,
    setTaskStatuses,
    setCurrentTaskId,
    setCurrentAudiobookProjectId,
    setGenerating,
    setTtsModel,
    refreshAudiobookProjectDetail,
  })

  useAudiobookPageSessionSync({
    pageSessionStorageKey: AUDIOBOOK_PAGE_SESSION_STORAGE_KEY,
    sessionHydratedRef,
    restoredPageSessionProjectRef,
    restoredProjectBoundPageSessionKeyRef,
    skipNextPageSessionPersistRef,
    routeProjectId,
    selectedProjectId,
    audiobookProjectId: audiobookProject?.id,
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
    generateSubtitle,
    setGenerateSubtitle,
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
  })

  const {
    handleToggleChapter,
    handleToggleAll,
  } = useAudiobookChapterSelectionActions({
    chapters,
    selectedChapters,
    setSelectedChapters,
  })

  const {
    handleVoiceChange,
    handleTtsModelChangeForCharacter,
    handleVoiceCloneDataUrlChange,
  } = useAudiobookCharacterVoiceSettings({
    voicePresets,
    updateCharacterVoicesForCurrentModel,
  })

  useAudiobookSourceChapterFocus({
    selectedProjectId,
    requestedAudiobookProjectId,
    requestedSourceChapterId,
    requestedSourceFocus,
    loadedAudiobookProjectId: audiobookProject?.id ?? null,
    currentAudiobookProjectId,
    handledSourceChapterKeyRef,
    clearActiveGenerationState,
    resetBrowserPlayer,
    refreshAudiobookProjectDetail,
    handleOpenScriptEditor,
    setActiveStep,
    setShowHistory,
    setCurrentAudiobookProjectId,
    setSnackbar,
  })

  const {
    handleGenerateAudioForApprovedChapters,
    handleGenerate,
    handleResumeChapterGeneration,
  } = useAudiobookGenerationActions({
    audiobookProject,
    generating,
    selectedChapters,
    selectedProjectId,
    routeProjectId,
    characterVoices,
    audioFxConfig,
    ttsModel,
    currentVoicePresets,
    scriptOnlyMode,
    narrationStyle,
    narrationStylePrompt,
    outputFormat,
    generateSubtitle,
    ensureCurrentTtsModelReady,
    activateQueuedAudiobookTask,
    setGenerating,
    setActiveStep,
    setLastGenerationMode,
    setTaskPointsPrecheckError,
    setResumeCheckpoints,
    setResumingChapterId,
    setSnackbar,
  })

  useAudiobookTaskPolling({
    selectedProjectId,
    trackedAudiobookProjectIds,
    trackedAudiobookProjectIdKey,
    currentTaskId,
    currentAudiobookProjectId,
    currentAudiobookProjectDetailId: audiobookProject?.id,
    generating,
    activeStep,
    taskStatuses,
    setTaskStatuses,
    setCurrentTaskId,
    setCurrentAudiobookProjectId,
    setGenerating,
    setActiveStep,
    setSnackbar,
    focusAudiobookTask,
    refreshAudiobookProjectDetail,
    downloadCompletedProjectExport,
  })

  const setupGenerateDisabled = selectedChapters.length === 0
    || generating
    || !(selectedProject?.id ?? routeProjectId)
  const setupGenerateDisabledReason = generating
    ? '当前有声书任务正在生成中'
    : !(selectedProject?.id ?? routeProjectId)
      ? '请先选择项目'
      : selectedChapters.length === 0
        ? '请先选择至少一个章节'
        : ''

  return (
    <Box sx={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
      <AudiobookPageHeader
        hasSelectedProject={Boolean(selectedProject)}
        onBack={() => navigate('/home')}
        onCreateProject={handleOpenNewProjectDialog}
        onOpenHistory={handleOpenHistoryPanel}
      />

      <Container maxWidth="xl" sx={{ py: 4 }}>
        <AudiobookWorkflowStatus
          activeStep={activeStep}
          taskPointsPrecheckError={taskPointsPrecheckError}
          activeProjectTasks={activeProjectTasks}
          generating={generating}
          resumableChapterEntries={resumableChapterEntries}
          resumingChapterId={resumingChapterId}
          resumeCheckpointLoading={resumeCheckpointLoading}
          getTaskLabel={formatActiveTaskLabel}
          onCloseTaskPointsPrecheck={clearTaskPointsPrecheckError}
          onFocusActiveTask={handleFocusActiveProjectTask}
          onResumeChapterGeneration={handleResumeChapterGeneration}
        />

        {/* 步骤1: 配置音色（章节选择 + 角色音频设置） */}
        {activeStep === 0 && (
          <AudiobookSetupStep
            selectedChapterCount={selectedChapters.length}
            chapterCount={chapters.length}
            scriptOnlyMode={scriptOnlyMode}
            onScriptOnlyModeChange={setScriptOnlyMode}
            ttsModel={ttsModel}
            ttsModelOptions={ttsModelOptions}
            voiceCatalogMeta={voiceCatalogMeta}
            voiceCatalogSummary={voiceCatalogSummary}
            voiceCatalogNotice={voiceCatalogNotice}
            voiceCatalogNoticeSeverity={voiceCatalogNoticeSeverity}
            showCustomVoiceWorkbench={showCustomVoiceWorkbench}
            voiceError={voiceError}
            voiceLoading={voiceLoading}
            customVoicePresets={customVoicePresets}
            cosyVoiceWorkbench={cosyVoiceWorkbench}
            narrationStyle={narrationStyle}
            narrationStylePrompt={narrationStylePrompt}
            outputFormat={outputFormat}
            generateSubtitle={generateSubtitle}
            audioFxConfig={audioFxConfig}
            chapters={chapters}
            selectedChapters={selectedChapters}
            loadingCharacters={loadingCharacters}
            characterVoices={characterVoices}
            currentVoicePresets={currentVoicePresets}
            voicePresetsByModel={voicePresetsByModel}
            previewingCharacterId={previewingCharacterId}
            customVoicePreviewingId={customVoicePreviewingId}
            autoAssigningVoices={autoAssigningVoices}
            generateDisabled={setupGenerateDisabled}
            generateDisabledReason={setupGenerateDisabledReason}
            onFetchVoiceCatalog={fetchVoiceCatalog}
            onNarrationStyleChange={setNarrationStyle}
            onNarrationStylePromptChange={setNarrationStylePrompt}
            onOutputFormatChange={setOutputFormat}
            onGenerateSubtitleChange={setGenerateSubtitle}
            onAudioFxConfigChange={setAudioFxConfig}
            onTtsModelChange={setTtsModel}
            onToggleAllChapters={handleToggleAll}
            onToggleChapter={handleToggleChapter}
            onOpenChapterMenu={handleOpenChapterMenu}
            onVoiceChange={handleVoiceChange}
            onTtsModelChangeForCharacter={handleTtsModelChangeForCharacter}
            onVoiceCloneDataUrlChange={handleVoiceCloneDataUrlChange}
            onPreviewCustomVoice={handlePreviewCustomVoice}
            onPreviewCharacterVoice={handlePreviewCharacterVoice}
            onAutoAssignVoices={handleAutoAssignVoices}
            onGenerate={handleGenerate}
          />
        )}

        {/* 步骤2: 生成有声书 */}
        {activeStep === 1 && (
          <AudiobookProgressStep
            activeProjectTasks={activeProjectTasks}
            activeTaskId={activeTaskStatus?.task_id}
            progressTaskStatus={progressTaskStatus}
            getTaskLabel={formatActiveTaskLabel}
            onFocusTask={handleFocusActiveProjectTask}
            onOpenStageMetrics={handleOpenStageMetricsDialog}
            onOpenScriptReview={handleOpenScriptReviewDialog}
          />
        )}

        {/* 步骤3: 完成 */}
        {activeStep === 2 && (
          <AudiobookCompletionStep
            audiobookProject={audiobookProject}
            lastGenerationMode={lastGenerationMode}
            hasChapterAudios={hasChapterAudios}
            browserPlayerLoading={browserPlayerLoading}
            exportingProjectM4b={exportingProjectM4b}
            exportingProjectAudacity={exportingProjectAudacity}
            hasActiveM4bExportTask={hasActiveM4bExportTask}
            hasActiveAudacityExportTask={hasActiveAudacityExportTask}
            currentChapterAudios={currentChapterAudios}
            chapters={chapters}
            playingChapter={playingChapter}
            collectingChapterIds={collectingChapterIds}
            resumeCheckpoints={resumeCheckpoints}
            generating={generating}
            resumingChapterId={resumingChapterId}
            hasScriptReview={Boolean(activeTaskStatus?.stages?.quality_review)}
            ttsModel={ttsModel}
            projectId={audiobookProject?.id}
            audiobookProjectId={audiobookProject?.id}
            onOpenBrowserPlayer={handleOpenBrowserPlayer}
            onExportProjectM4b={handleExportProjectM4b}
            onExportProjectAudacity={handleExportProjectAudacity}
            onPlayAudio={handlePlayAudio}
            onDownloadAudio={handleDownloadAudio}
            onCollectChapterAudio={handleCollectChapterAudio}
            onOpenScriptEditor={handleOpenScriptEditor}
            onResumeChapterGeneration={handleResumeChapterGeneration}
            onOpenScriptReview={handleOpenScriptReviewDialog}
            onOpenScriptReviewFromApi={handleOpenScriptReviewFromApi}
            onGenerateApprovedChapterAudio={handleGenerateAudioForApprovedChapters}
            onCreateNewProject={handleCreateNewAudiobookProject}
          />
        )}
      </Container>

      <AudiobookSnackbar
        snackbar={snackbar}
        onClose={handleCloseSnackbar}
      />

      <TextProjectImportDialog
        open={newProjectDialogOpen}
        title={newProjectTitle}
        text={newProjectText}
        creating={creatingFromBook}
        onClose={handleCloseNewProjectDialog}
        onTitleChange={setNewProjectTitle}
        onTextChange={setNewProjectText}
        onCreate={handleCreateProjectFromText}
      />
      
      <ScriptQualityReviewDialog
        open={scriptReviewDialogOpen}
        data={scriptReviewData}
        audiobookProjectId={audiobookProject?.id}
        selectedIssueIndex={scriptReviewSelectedIssueIndex}
        selectedSegmentIndex={scriptReviewSelectedSegmentIndex}
        onClose={handleCloseScriptReviewDialog}
        onOpenScriptEditor={handleOpenScriptEditor}
        onSelectIssue={setScriptReviewSelectedIssueIndex}
        onSelectSegment={setScriptReviewSelectedSegmentIndex}
      />

      <StageMetricsDialog
        open={stageMetricsDialogOpen}
        data={stageMetricsData}
        onClose={handleCloseStageMetricsDialog}
      />

      {/* 章节剧本编辑弹窗 */}
      <ScriptEditorDialog
        open={scriptEditorDialogOpen}
        loading={scriptEditorLoading}
        chapter={scriptEditorChapter}
        data={scriptEditorData}
        onClose={handleCloseScriptEditorDialog}
        onChangeSegmentText={handleChangeScriptSegmentText}
        onSaveScript={handleSaveScript}
        onPreviewSegmentAudio={handlePreviewScriptSegmentAudio}
        onRegenerateSegment={handleRegenerateSegment}
        onStartSegmentVoiceRecording={handleStartSegmentVoiceRecording}
        onStopSegmentVoiceRecording={handleStopSegmentVoiceRecording}
        onApplySegmentRegeneration={handleApplySegmentRegenerationCandidate}
        onDiscardSegmentRegeneration={handleDiscardSegmentRegenerationCandidate}
        onReviewSegment={handleReviewSegment}
        segmentReviews={segmentReviews}
        pendingSegmentRegenerations={pendingSegmentRegenerations}
        recordingSegmentIndex={recordingSegmentIndex}
        segmentPreviewingIndex={segmentPreviewingIndex}
        segmentPreviewingType={segmentPreviewingType}
        segmentAudioUrls={segmentAudioUrls}
        segmentDetailsOpen={segmentDetailsOpen}
        onToggleSegmentDetails={handleToggleSegmentDetails}
        onUpdateSegment={handleUpdateScriptSegment}
        timelineEdits={timelineEdits}
        onChangeTimelineEdits={setTimelineEdits}
        reviewMode={reviewMode}
        onToggleReviewMode={handleToggleReviewMode}
        regeneratingSegments={regeneratingSegments}
        smartChunkPreview={smartChunkPreview}
        smartChunkPreviewLoading={smartChunkPreviewLoading}
        onPreviewSmartChunking={handlePreviewSmartChunking}
        editorConflict={editorCrossTabConflict}
        editorConflictTimeLabel={editorConflictTimeLabel}
        editorConflictPreview={editorConflictPreview}
        visibleEditorConflictSegmentDiffs={visibleEditorConflictSegmentDiffs}
        hiddenEditorConflictSegmentDiffCount={hiddenEditorConflictSegmentDiffCount}
        onApplyIncomingDraft={handleApplyIncomingEditorDraft}
        onKeepLocalDraft={handleKeepLocalEditorDraft}
        projectId={audiobookProject?.id}
      />
      
      {/* 新增：历史记录对话框 */}
      <HistoryDialog
        open={showHistory}
        loading={loadingHistory}
        historyProjects={historyProjects}
        selectedProject={selectedProject}
        onCloseHistory={handleCloseHistoryPanel}
        onViewHistory={handleViewHistory}
        onDeleteHistory={handleDeleteHistory}
      />

      {browserPlayerData && (
        <BrowserPlayer
          projectData={browserPlayerData}
          open={browserPlayerOpen}
          onClose={handleCloseBrowserPlayer}
        />
      )}

      <ChapterActionsMenu
        anchorEl={chapterMenuAnchor}
        onClose={handleCloseChapterMenu}
        onOpenDeleteDialog={handleOpenDeleteChapterDialog}
      />

      <ChapterDeleteConfirmDialog
        open={deleteChapterDialogOpen}
        chapter={selectedChapterForMenu}
        reason={deleteChapterReason}
        deleteFiles={deleteChapterFiles}
        deleting={deletingChapter}
        onClose={handleCloseDeleteChapterDialog}
        onReasonChange={setDeleteChapterReason}
        onDeleteFilesChange={setDeleteChapterFiles}
        onDelete={handleDeleteChapter}
      />
    </Box>
  )
}

export default AudiobookPage
