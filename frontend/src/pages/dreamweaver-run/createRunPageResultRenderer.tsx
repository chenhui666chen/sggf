import React from 'react'
import type { TFunction } from 'i18next'
import { Box, Divider } from '@mui/material'
import type { DreamweaverShotSnapshot, RunResult } from '@/types/dreamweaver'
import { DebugAccordion } from './diagnosticSections'
import { DreamweaverRunResultView, DreamweaverResultTextStageSection, DreamweaverResultStoryboardStageView, DreamweaverResultLibraryHint, DreamweaverResultVideoStageView, DreamweaverResultVideoSummarySection, DreamweaverResultVideoFallbackAlert, DreamweaverResultVideoClipPathSummary, DreamweaverResultSyncActionsBar, DreamweaverResultSyncStatusPanel } from './resultView'
import { RunSnapshotSectionStatus, RunSnapshotRefreshButton, RunSnapshotLoadedChip, RunSnapshotErrorAlert, RunSnapshotLoadingBar } from './runSnapshotPreviewPane'
import { ShotPromptSnapshotList } from './ShotPromptSnapshotList'
import { MergedVideoPanel, type MergedVideoPanelProps } from './MergedVideoPanel'
import type { RunSnapshotSectionStatusProps } from './runSnapshotPreviewPane'
import { buildVideoSummarySectionProps } from './runPagePropsBuilders'
import type { VideoDiagnostics } from './runPageDiagnosticHelpers'

interface CreateRunPageResultRendererDeps {
  safeJsonStringify: (value: unknown) => string
  taskArtifacts: unknown
  result: RunResult | null
  resultChapterCount: number
  resultKeyframeCount: number
  resultMidframeCount: number
  resultVideoClipCount: number
  resultKeyframePaths: string[]
  resultMidframePaths: string[]
  resultVideoClipPaths: string[]
  candidateFrameUris: string[]
  renderRunAssetPreviewGrid: (label: string, paths: string[], kind: 'image' | 'video') => React.ReactNode
  isStoryboardPreviewStep: boolean
  isScriptPreviewStep: boolean
  isAuditPreviewStep: boolean
  runSnapshotLoading: boolean
  snapshotShots: DreamweaverShotSnapshot[]
  snapshotStatusBaseProps: RunSnapshotSectionStatusProps
  videoDiagnostics: VideoDiagnostics
  snapshotStatusPropsWithChips: RunSnapshotSectionStatusProps
  mergedVideoPanelProps: MergedVideoPanelProps
  resultPlanText: string
  currentRunId: string | null
  eventSyncing: boolean
  eventCursor: number | null
  runSnapshotError: string | null
  eventSyncError: string | null
  loadRunSnapshot: () => void
  syncDreamweaverEvents: (runId: string) => void
  renderStreamingPreview: (step: number) => React.ReactNode
  previewStep: number
  snapshotRefreshDisabled: boolean
  runSnapshotLoaded: boolean
  t: TFunction
}

export function createRunPageResultRenderer(deps: CreateRunPageResultRendererDeps) {
  const {
    safeJsonStringify,
    taskArtifacts,
    result,
    resultChapterCount,
    resultKeyframeCount,
    resultMidframeCount,
    resultVideoClipCount,
    resultKeyframePaths,
    resultMidframePaths,
    resultVideoClipPaths,
    candidateFrameUris,
    renderRunAssetPreviewGrid,
    isStoryboardPreviewStep,
    isScriptPreviewStep,
    isAuditPreviewStep,
    runSnapshotLoading,
    snapshotShots,
    snapshotStatusBaseProps,
    videoDiagnostics,
    snapshotStatusPropsWithChips,
    mergedVideoPanelProps,
    resultPlanText,
    currentRunId,
    eventSyncing,
    eventCursor,
    runSnapshotError,
    eventSyncError,
    loadRunSnapshot,
    syncDreamweaverEvents,
    renderStreamingPreview,
    previewStep,
    snapshotRefreshDisabled,
    runSnapshotLoaded,
    t,
  } = deps

  const isVideoPreviewStep = previewStep === 3
  const isLibraryPreviewStep = previewStep === 2

  const renderDebugAccordion = ({
    title,
    value,
    marginTop = 0,
    marginBottom = 0,
  }: {
    title: string
    value: unknown
    marginTop?: number
    marginBottom?: number
  }) => (
    <DebugAccordion title={title} value={value} marginTop={marginTop} marginBottom={marginBottom} safeJsonStringify={safeJsonStringify} />
  )

  const renderArtifactsDebugPanel = () =>
    renderDebugAccordion({ title: t('dreamweaverRun.debugPanelArtifacts'), value: taskArtifacts, marginTop: 1 })

  const hasCandidateFrames = candidateFrameUris.length > 0

  const renderResultVideoAssetPreviewSections = () => (
    <>
      {renderRunAssetPreviewGrid(t('dreamweaverRun.keyframes'), resultKeyframePaths.slice(-6), 'image')}
      {renderRunAssetPreviewGrid(t('dreamweaverRun.midframes'), resultMidframePaths.slice(-6), 'image')}
      {hasCandidateFrames &&
        renderRunAssetPreviewGrid(t('dreamweaverRun.candidateFrames'), candidateFrameUris.slice(-12), 'image')}
      {renderRunAssetPreviewGrid(t('dreamweaverRun.videoClips'), resultVideoClipPaths.slice(-3), 'video')}
    </>
  )

  const showResultStoryboardShots = !runSnapshotLoading && snapshotShots.length > 0

  const renderResultStoryboardSnapshotSection = () => {
    if (!isStoryboardPreviewStep) return null

    return (
      <>
        <RunSnapshotSectionStatus {...snapshotStatusBaseProps} />
        {showResultStoryboardShots && (
          <Box sx={{ mt: 1 }}>
            <ShotPromptSnapshotList shots={snapshotShots} />
          </Box>
        )}
      </>
    )
  }

  const videoFallbackAlert = videoDiagnostics.fallbackCount > 0 ? <DreamweaverResultVideoFallbackAlert /> : null
  const videoClipPathSummary = resultVideoClipPaths.length > 0 ? <DreamweaverResultVideoClipPathSummary paths={resultVideoClipPaths} /> : null

  const showVideoSnapshotStatus = isVideoPreviewStep
  const videoSnapshotStatus = showVideoSnapshotStatus ? <RunSnapshotSectionStatus {...snapshotStatusPropsWithChips} /> : null

  const videoSummarySectionProps = buildVideoSummarySectionProps(result?.merged_video, videoDiagnostics)

  const hasMergedVideo = Boolean(result?.merged_video)
  const mergedVideoPanel = hasMergedVideo ? <MergedVideoPanel {...mergedVideoPanelProps} centeredPreview /> : null

  const renderResultVideoStageView = () => !result ? null : (
    <DreamweaverResultVideoStageView
      assetPreviewSections={renderResultVideoAssetPreviewSections()}
      videoSummarySection={
        <DreamweaverResultVideoSummarySection
          {...videoSummarySectionProps}
        />
      }
      fallbackAlert={videoFallbackAlert}
      clipPathSummary={videoClipPathSummary}
      mergedVideoPanel={mergedVideoPanel}
      snapshotStatus={videoSnapshotStatus}
    />
  )

  const renderResultPlanStageView = () => (
    <DreamweaverResultTextStageSection
      title={t('dreamweaverRun.planScriptSummary')}
      text={resultPlanText}
      emptyText={t('dreamweaverRun.noReturnedText')}
    />
  )

  const storyboardSummaryText = result?.storyboard ? t('dreamweaverRun.shotCount', { count: result.storyboard.length }) : t('dreamweaverRun.none')

  const renderResultStoryboardStageView = () => (
    <DreamweaverResultStoryboardStageView
      storyboardSummary={storyboardSummaryText}
      snapshotSection={renderResultStoryboardSnapshotSection()}
    />
  )

  const renderResultLibraryHintView = () => (
    <DreamweaverResultLibraryHint message={t('dreamweaverRun.libraryHintMessage')} />
  )

  const auditText = result?.audit ? JSON.stringify(result.audit) : ''

  const renderResultAuditStageView = () => (
    <DreamweaverResultTextStageSection
      title={t('dreamweaverRun.qualityCheck')}
      text={auditText}
      emptyText={t('dreamweaverRun.noAuditInfo')}
      marginTop={1}
      marginBottom={0}
    />
  )

  const handleSyncEvents = currentRunId ? () => syncDreamweaverEvents(currentRunId) : null

  const eventSyncDisabled = !currentRunId || eventSyncing

  const renderResultSyncActions = () => (
    <DreamweaverResultSyncActionsBar
      refreshButton={
        <RunSnapshotRefreshButton
          label={t('dreamweaverRun.refreshRunSnapshot')}
          onClick={loadRunSnapshot}
          disabled={snapshotRefreshDisabled}
          loading={runSnapshotLoading}
        />
      }
      onSync={handleSyncEvents}
      syncInProgress={eventSyncing}
      syncDisabled={eventSyncDisabled}
      loadedChip={<RunSnapshotLoadedChip visible={runSnapshotLoaded} />}
      eventCursor={eventCursor ?? 0}
    />
  )

  const snapshotErrorAlert = <RunSnapshotErrorAlert message={runSnapshotError} spacingKey="mb" spacingValue={1} />
  const snapshotLoadingBar = <RunSnapshotLoadingBar visible={runSnapshotLoading} spacingKey="mb" spacingValue={1} />

  const renderResultSyncStatus = () => (
    <DreamweaverResultSyncStatusPanel
      snapshotErrorAlert={snapshotErrorAlert}
      eventSyncError={eventSyncError}
      snapshotLoadingBar={snapshotLoadingBar}
    />
  )

  const renderResultDebugPanel = () => (
    <>
      {renderDebugAccordion({
        title: t('dreamweaverRun.debugPanelResult'),
        value: result,
        marginBottom: 1.5,
      })}
      <Divider sx={{ my: 1.5 }} />
    </>
  )

  const showResultPlanStage = isScriptPreviewStep || isAuditPreviewStep
  const showResultStoryboardStage = isStoryboardPreviewStep || isAuditPreviewStep
  const showResultLibraryStage = isLibraryPreviewStep
  const showResultVideoStage = isVideoPreviewStep || isAuditPreviewStep
  const showResultAuditStage = isAuditPreviewStep

  const renderResultView = () => !result ? null : (
    <DreamweaverRunResultView
      chapterCount={resultChapterCount}
      keyframeCount={resultKeyframeCount}
      midframeCount={resultMidframeCount}
      videoClipCount={resultVideoClipCount}
      debugPanel={renderResultDebugPanel()}
      syncActions={renderResultSyncActions()}
      syncStatus={renderResultSyncStatus()}
      streamingPreview={renderStreamingPreview(previewStep)}
      planStage={showResultPlanStage ? renderResultPlanStageView() : null}
      storyboardStage={showResultStoryboardStage ? renderResultStoryboardStageView() : null}
      libraryStage={showResultLibraryStage ? renderResultLibraryHintView() : null}
      videoStage={showResultVideoStage ? renderResultVideoStageView() : null}
      auditStage={showResultAuditStage ? renderResultAuditStageView() : null}
    />
  )

  return {
    renderArtifactsDebugPanel,
    renderResultView,
  }
}
