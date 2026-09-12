import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Alert, Box, Button, Chip, Stack, Typography } from '@mui/material'

type DreamweaverResultTextStageSectionProps = {
  title: string
  text?: string | null
  emptyText: string
  marginTop?: number
  marginBottom?: number
}

export function DreamweaverResultTextStageSection({
  title,
  text,
  emptyText,
  marginTop = 0,
  marginBottom = 1,
}: DreamweaverResultTextStageSectionProps) {
  return (
    <>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, ...(marginTop > 0 ? { mt: marginTop } : {}), mb: 0.5 }}>
        {title}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={marginBottom > 0 ? { mb: marginBottom } : undefined}>
        {text || emptyText}
      </Typography>
    </>
  )
}

type DreamweaverResultLibraryHintProps = {
  message: string
}

export function DreamweaverResultLibraryHint({ message }: DreamweaverResultLibraryHintProps) {
  return (
    <Alert severity="info" sx={{ mb: 1 }}>
      {message}
    </Alert>
  )
}

export type DreamweaverResultVideoSummarySectionProps = {
  mergedVideo?: string | null
  viaSummary?: string | null
  fallbackCount: number
  clipCount: number
}

export function DreamweaverResultVideoSummarySection({
  mergedVideo,
  viaSummary,
  fallbackCount,
  clipCount,
}: DreamweaverResultVideoSummarySectionProps) {
  const { t } = useTranslation()
  return (
    <>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mt: 1, mb: 0.5 }}>
        {t('dreamweaverRun.videoProducts')}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {mergedVideo ? t('dreamweaverRun.mergedVideoWithPath', { path: mergedVideo }) : t('dreamweaverRun.noMergedVideoRecord')}
      </Typography>
      {viaSummary && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {t('dreamweaverRun.generatedVia', { via: viaSummary })}
          {fallbackCount > 0 ? t('dreamweaverRun.fallbackRatio', { count: fallbackCount, total: clipCount }) : ''}
        </Typography>
      )}
    </>
  )
}

export function DreamweaverResultVideoFallbackAlert() {
  const { t } = useTranslation()
  return (
    <Alert severity="warning" sx={{ mt: 1 }}>
      {t('dreamweaverRun.videoFallbackAlert')}
    </Alert>
  )
}

type DreamweaverResultVideoClipPathSummaryProps = {
  paths: string[]
}

export function DreamweaverResultVideoClipPathSummary({
  paths,
}: DreamweaverResultVideoClipPathSummaryProps) {
  if (paths.length === 0) return null

  return (
    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
      {paths
        .map((path, idx) => `${idx + 1}. ${path}`)
        .filter(Boolean)
        .join('  ')}
    </Typography>
  )
}

type DreamweaverResultVideoStageViewProps = {
  assetPreviewSections?: ReactNode
  videoSummarySection?: ReactNode
  fallbackAlert?: ReactNode
  clipPathSummary?: ReactNode
  mergedVideoPanel?: ReactNode
  snapshotStatus?: ReactNode
}

export function DreamweaverResultVideoStageView({
  assetPreviewSections,
  videoSummarySection,
  fallbackAlert,
  clipPathSummary,
  mergedVideoPanel,
  snapshotStatus,
}: DreamweaverResultVideoStageViewProps) {
  return (
    <>
      {assetPreviewSections ?? null}
      {videoSummarySection ?? null}
      {fallbackAlert ?? null}
      {clipPathSummary ?? null}
      {mergedVideoPanel ?? null}
      {snapshotStatus ?? null}
    </>
  )
}

type DreamweaverResultStoryboardStageViewProps = {
  storyboardSummary: string
  snapshotSection?: ReactNode
}

export function DreamweaverResultStoryboardStageView({
  storyboardSummary,
  snapshotSection,
}: DreamweaverResultStoryboardStageViewProps) {
  const { t } = useTranslation()
  return (
    <>
      <DreamweaverResultTextStageSection
        title={t('dreamweaverRun.storyboardTitle')}
        text={storyboardSummary}
        emptyText={t('dreamweaverRun.none')}
        marginBottom={0}
      />
      {snapshotSection ?? null}
    </>
  )
}

type DreamweaverResultSummaryChipsProps = {
  chapterCount: number
  keyframeCount: number
  midframeCount: number
  videoClipCount?: number | null
}

export function DreamweaverResultSummaryChips({
  chapterCount,
  keyframeCount,
  midframeCount,
  videoClipCount,
}: DreamweaverResultSummaryChipsProps) {
  const { t } = useTranslation()
  return (
    <DreamweaverResultSummaryChipsRow
      chips={
        <>
          <Chip label={t('dreamweaverRun.chapterChip', { count: chapterCount })} size="small" />
          {keyframeCount > 0 && <Chip label={t('dreamweaverRun.keyframeChip', { count: keyframeCount })} size="small" />}
          {midframeCount > 0 && <Chip label={t('dreamweaverRun.midframeChip', { count: midframeCount })} size="small" />}
          {typeof videoClipCount === 'number' && <Chip label={t('dreamweaverRun.clipChip', { count: videoClipCount })} size="small" color="primary" />}
        </>
      }
    />
  )
}

type DreamweaverResultSyncActionsBarProps = {
  refreshButton?: ReactNode
  onSync?: (() => void) | null
  syncInProgress?: boolean
  syncDisabled?: boolean
  loadedChip?: ReactNode
  eventCursor: number
}

export function DreamweaverResultSyncActionsBar({
  refreshButton,
  onSync,
  syncInProgress = false,
  syncDisabled = false,
  loadedChip,
  eventCursor,
}: DreamweaverResultSyncActionsBarProps) {
  const { t } = useTranslation()
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
      {refreshButton ?? null}
      <Button size="small" variant="outlined" onClick={onSync ?? undefined} disabled={syncDisabled}>
        {syncInProgress ? t('dreamweaverRun.syncing') : t('dreamweaverRun.syncEvents')}
      </Button>
      {loadedChip ?? null}
      {eventCursor > 0 && <Chip size="small" label={t('dreamweaverRun.eventCursorChip', { cursor: eventCursor })} variant="outlined" />}
    </Stack>
  )
}

type DreamweaverResultSyncStatusPanelProps = {
  snapshotErrorAlert?: ReactNode
  eventSyncError?: string | null
  snapshotLoadingBar?: ReactNode
}

export function DreamweaverResultSyncStatusPanel({
  snapshotErrorAlert,
  eventSyncError,
  snapshotLoadingBar,
}: DreamweaverResultSyncStatusPanelProps) {
  return (
    <>
      {snapshotErrorAlert ?? null}
      {eventSyncError && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {eventSyncError}
        </Alert>
      )}
      {snapshotLoadingBar ?? null}
    </>
  )
}

type DreamweaverResultStageContentProps = {
  planStage?: ReactNode
  storyboardStage?: ReactNode
  libraryStage?: ReactNode
  videoStage?: ReactNode
  auditStage?: ReactNode
}

export function DreamweaverResultStageContent({
  planStage,
  storyboardStage,
  libraryStage,
  videoStage,
  auditStage,
}: DreamweaverResultStageContentProps) {
  return (
    <>
      {planStage ?? null}
      {storyboardStage ?? null}
      {libraryStage ?? null}
      {videoStage ?? null}
      {auditStage ?? null}
    </>
  )
}

type DreamweaverResultSyncSectionProps = {
  actions: ReactNode
  status: ReactNode
}

export function DreamweaverResultSyncSection({
  actions,
  status,
}: DreamweaverResultSyncSectionProps) {
  return (
    <>
      {actions}
      {status}
    </>
  )
}

type DreamweaverResultViewShellProps = {
  summaryChips?: ReactNode
  debugPanel?: ReactNode
  syncSection?: ReactNode
  streamingPreview?: ReactNode
  stageContent?: ReactNode
}

export function DreamweaverResultViewShell({
  summaryChips,
  debugPanel,
  syncSection,
  streamingPreview,
  stageContent,
}: DreamweaverResultViewShellProps) {
  return (
    <Box>
      {summaryChips ?? null}
      {debugPanel ?? null}
      {syncSection ?? null}
      {streamingPreview ?? null}
      {stageContent ?? null}
    </Box>
  )
}

type DreamweaverResultSummaryChipsRowProps = {
  chips: ReactNode
}

export function DreamweaverResultSummaryChipsRow({
  chips,
}: DreamweaverResultSummaryChipsRowProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" mb={1.5} alignItems="center">
      {chips}
    </Stack>
  )
}

type DreamweaverRunResultViewProps = {
  chapterCount: number
  keyframeCount: number
  midframeCount: number
  videoClipCount?: number | null
  debugPanel?: ReactNode
  syncActions?: ReactNode
  syncStatus?: ReactNode
  streamingPreview?: ReactNode
  planStage?: ReactNode
  storyboardStage?: ReactNode
  libraryStage?: ReactNode
  videoStage?: ReactNode
  auditStage?: ReactNode
}

export function DreamweaverRunResultView({
  chapterCount,
  keyframeCount,
  midframeCount,
  videoClipCount,
  debugPanel,
  syncActions,
  syncStatus,
  streamingPreview,
  planStage,
  storyboardStage,
  libraryStage,
  videoStage,
  auditStage,
}: DreamweaverRunResultViewProps) {
  return (
    <DreamweaverResultViewShell
      summaryChips={
        <DreamweaverResultSummaryChips
          chapterCount={chapterCount}
          keyframeCount={keyframeCount}
          midframeCount={midframeCount}
          videoClipCount={videoClipCount}
        />
      }
      debugPanel={debugPanel}
      syncSection={
        <DreamweaverResultSyncSection
          actions={syncActions ?? null}
          status={syncStatus ?? null}
        />
      }
      streamingPreview={streamingPreview}
      stageContent={
        <DreamweaverResultStageContent
          planStage={planStage}
          storyboardStage={storyboardStage}
          libraryStage={libraryStage}
          videoStage={videoStage}
          auditStage={auditStage}
        />
      }
    />
  )
}
