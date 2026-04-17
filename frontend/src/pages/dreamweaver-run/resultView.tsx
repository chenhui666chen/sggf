import type { ReactNode } from 'react'

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

type DreamweaverResultVideoSummarySectionProps = {
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
  return (
    <>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mt: 1, mb: 0.5 }}>
        视频产物
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {mergedVideo ? `合成视频：${mergedVideo}` : '无合成视频记录'}
      </Typography>
      {viaSummary && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          生成方式：{viaSummary}
          {fallbackCount > 0 ? `（降级: ${fallbackCount}/${clipCount}）` : ''}
        </Typography>
      )}
    </>
  )
}

export function DreamweaverResultVideoFallbackAlert() {
  return (
    <Alert severity="warning" sx={{ mt: 1 }}>
      检测到镜头视频生成失败并降级为幻灯片合成，建议检查 WAN_I2V_* 配置/网络，并适当增大 WAN_I2V_TIMEOUT。
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
  return (
    <>
      <DreamweaverResultTextStageSection
        title="分镜（storyboard）"
        text={storyboardSummary}
        emptyText="暂无"
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
  return (
    <DreamweaverResultSummaryChipsRow
      chips={
        <>
          <Chip label={`章节: ${chapterCount}`} size="small" />
          {keyframeCount > 0 && <Chip label={`关键帧: ${keyframeCount}`} size="small" />}
          {midframeCount > 0 && <Chip label={`中间帧: ${midframeCount}`} size="small" />}
          {typeof videoClipCount === 'number' && <Chip label={`片段: ${videoClipCount}`} size="small" color="primary" />}
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
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
      {refreshButton ?? null}
      <Button size="small" variant="outlined" onClick={onSync ?? undefined} disabled={syncDisabled}>
        {syncInProgress ? '同步中…' : '同步事件'}
      </Button>
      {loadedChip ?? null}
      {eventCursor > 0 && <Chip size="small" label={`事件#${eventCursor}`} variant="outlined" />}
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
