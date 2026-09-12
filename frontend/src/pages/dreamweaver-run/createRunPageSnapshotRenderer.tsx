import { Alert } from '@mui/material'
import type { TFunction } from 'i18next'
import {
  RunSnapshotAssetPreviewSection,
  RunSnapshotErrorAlert,
  RunSnapshotLoadingBar,
  RunSnapshotMergedVideoSection,
  RunSnapshotPreviewPane,
  RunSnapshotRefreshControls,
  RunSnapshotShotList,
} from './runSnapshotPreviewPane'
import { MergedVideoPanel, type MergedVideoPanelProps } from './MergedVideoPanel'
import { ShotPromptSnapshotList } from './ShotPromptSnapshotList'
import { buildSnapshotAssetPreviewSectionProps, buildSnapshotStatusProps, type SnapshotStatusProps } from './runPagePropsBuilders'
import { isSnapshotRefreshDisabled } from './runPageDiagnosticHelpers'
import type { DreamweaverRunSnapshot, DreamweaverShotSnapshot } from '@/types/dreamweaver'
import type { ReactNode } from 'react'

interface SnapshotAssetSummary {
  keyframes: string[]
  midframes: string[]
  videoClips: Array<{ path: string; meta: Record<string, unknown> }>
}

interface CreateRunPageSnapshotRendererDeps {
  previewStep: number
  isScriptPreviewStep: boolean
  isStoryboardPreviewStep: boolean
  isAuditPreviewStep: boolean
  runSnapshotLoading: boolean
  snapshotShots: DreamweaverShotSnapshot[]
  snapshotAssetCount: number
  snapshotAssetSummary: SnapshotAssetSummary
  snapshotMergedVideo: string | null
  snapshotScriptStageSnapshot: ReactNode
  wsError: string | null
  persistedRunId: string | null
  runSnapshot: DreamweaverRunSnapshot | null
  runSnapshotError: string | null
  mergedVideoPanelProps: MergedVideoPanelProps
  renderRunAssetPreviewGrid: (title: string, uris: string[], kind: 'image' | 'video') => ReactNode
  renderSafetyBlockedAlert: () => ReactNode
  renderStreamingPreview: (step: number) => ReactNode
  loadRunSnapshot: () => Promise<void>
  setWsError: (v: string | null) => void
  t: TFunction
}

export function createRunPageSnapshotRenderer(deps: CreateRunPageSnapshotRendererDeps) {
  const {
    previewStep,
    isScriptPreviewStep,
    isStoryboardPreviewStep,
    isAuditPreviewStep,
    runSnapshotLoading,
    snapshotShots,
    snapshotAssetCount,
    snapshotAssetSummary,
    snapshotMergedVideo,
    snapshotScriptStageSnapshot,
    wsError,
    persistedRunId,
    runSnapshot,
    runSnapshotError,
    mergedVideoPanelProps,
    renderRunAssetPreviewGrid,
    renderSafetyBlockedAlert,
    renderStreamingPreview,
    loadRunSnapshot,
    setWsError,
    t,
  } = deps

  const showSnapshotShotList = isStoryboardPreviewStep && !runSnapshotLoading
  const hasSnapshotShots = snapshotShots.length > 0

  const renderSnapshotShotList = (emptyText: string) => (
    <RunSnapshotShotList
      visible={showSnapshotShotList}
      title={t('dreamweaverRun.shotList')}
      emptyText={emptyText}
      hasShots={hasSnapshotShots}
      shotItems={<ShotPromptSnapshotList shots={snapshotShots} />}
    />
  )

  const renderSnapshotAssetPreviewSection = () => {
    const props = buildSnapshotAssetPreviewSectionProps({
      previewStep,
      runSnapshotLoading,
      snapshotShotsLength: snapshotShots.length,
      snapshotAssetCount,
      snapshotAssetSummary,
    }, t)

    return (
      <RunSnapshotAssetPreviewSection
        {...props}
        keyframeGrid={renderRunAssetPreviewGrid(t('dreamweaverRun.keyframeSnapshot'), snapshotAssetSummary.keyframes.slice(-6), 'image')}
        midframeGrid={renderRunAssetPreviewGrid(t('dreamweaverRun.midframeSnapshot'), snapshotAssetSummary.midframes.slice(-6), 'image')}
        videoClipGrid={renderRunAssetPreviewGrid(t('dreamweaverRun.videoClipSnapshot'), props.tailVideoClipPaths, 'video')}
      />
    )
  }

  const showSnapshotMergedVideo = isAuditPreviewStep && !runSnapshotLoading
  const hasSnapshotMergedVideo = Boolean(snapshotMergedVideo)

  const renderSnapshotMergedVideoSection = () => (
    <RunSnapshotMergedVideoSection
      visible={showSnapshotMergedVideo}
      title={t('dreamweaverRun.mergedVideoSnapshot')}
      description={hasSnapshotMergedVideo ? t('dreamweaverRun.mergedVideoWithPath', { path: snapshotMergedVideo }) : t('dreamweaverRun.noMergedVideoSnapshot')}
      panel={hasSnapshotMergedVideo ? <MergedVideoPanel {...mergedVideoPanelProps} /> : null}
    />
  )

  const showScriptStageSnapshot = isScriptPreviewStep && !runSnapshotLoading
  const scriptStageSnapshotElement = showScriptStageSnapshot ? snapshotScriptStageSnapshot : null

  const clearWsError = () => setWsError(null)

  const wsWarningAlert = wsError ? (
    <Alert severity="warning" sx={{ mb: 1 }} onClose={clearWsError}>
      {wsError}
    </Alert>
  ) : null

  const runSnapshotLoaded = Boolean(runSnapshot && runSnapshot.run_id === persistedRunId)
  const snapshotRefreshDisabled = isSnapshotRefreshDisabled(persistedRunId, runSnapshotLoading)

  const renderRunSnapshotPreviewPane = ({
    refreshLabel = t('dreamweaverRun.refreshRunSnapshot'),
    shotEmptyText,
    includeStreamingPreview = false,
    includeWsError = false,
  }: {
    refreshLabel?: string
    shotEmptyText: string
    includeStreamingPreview?: boolean
    includeWsError?: boolean
  }) => (
    <RunSnapshotPreviewPane
      refreshControls={
        <RunSnapshotRefreshControls
          visible={!!persistedRunId}
          label={refreshLabel}
          onRefresh={loadRunSnapshot}
          refreshDisabled={snapshotRefreshDisabled}
          refreshLoading={runSnapshotLoading}
          loaded={runSnapshotLoaded}
        />
      }
      errorAlert={<RunSnapshotErrorAlert message={runSnapshotError} spacingKey="mb" spacingValue={1} />}
      wsWarning={includeWsError ? wsWarningAlert : null}
      loadingBar={<RunSnapshotLoadingBar visible={runSnapshotLoading} spacingKey="mb" spacingValue={1} />}
      safetyBlockedAlert={renderSafetyBlockedAlert()}
      streamingPreview={includeStreamingPreview ? renderStreamingPreview(previewStep) : null}
      scriptStageSnapshot={scriptStageSnapshotElement}
      shotList={renderSnapshotShotList(shotEmptyText)}
      assetPreview={renderSnapshotAssetPreviewSection()}
      mergedVideo={renderSnapshotMergedVideoSection()}
    />
  )

  const snapshotStatusSharedParams = {
    persistedRunId,
    runSnapshotLoading,
    runSnapshot,
    runSnapshotError,
    snapshotShots,
    snapshotAssetCount,
    loadRunSnapshot,
  }
  const snapshotStatusBaseProps: SnapshotStatusProps = buildSnapshotStatusProps({ ...snapshotStatusSharedParams, includeChips: false }, t)
  const snapshotStatusPropsWithChips: SnapshotStatusProps = buildSnapshotStatusProps({ ...snapshotStatusSharedParams, includeChips: true }, t)

  return {
    renderSnapshotShotList,
    renderSnapshotAssetPreviewSection,
    renderSnapshotMergedVideoSection,
    renderRunSnapshotPreviewPane,
    snapshotStatusBaseProps,
    snapshotStatusPropsWithChips,
    snapshotRefreshDisabled,
    runSnapshotLoaded,
  }
}
