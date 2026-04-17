import type { ReactNode } from 'react'

import { Box, Chip, Stack, Typography } from '@mui/material'

type RunSnapshotPreviewPaneProps = {
  refreshControls?: ReactNode
  errorAlert?: ReactNode
  wsWarning?: ReactNode
  loadingBar?: ReactNode
  safetyBlockedAlert?: ReactNode
  streamingPreview?: ReactNode
  scriptStageSnapshot?: ReactNode
  shotList?: ReactNode
  assetPreview?: ReactNode
  mergedVideo?: ReactNode
}

export function RunSnapshotPreviewPane({
  refreshControls,
  errorAlert,
  wsWarning,
  loadingBar,
  safetyBlockedAlert,
  streamingPreview,
  scriptStageSnapshot,
  shotList,
  assetPreview,
  mergedVideo,
}: RunSnapshotPreviewPaneProps) {
  return (
    <>
      {refreshControls ?? null}
      {errorAlert ?? null}
      {wsWarning ?? null}
      {loadingBar ?? null}
      {safetyBlockedAlert ?? null}
      {streamingPreview ?? null}
      {scriptStageSnapshot ?? null}
      {shotList ?? null}
      {assetPreview ?? null}
      {mergedVideo ?? null}
    </>
  )
}

type RunSnapshotShotListProps = {
  visible: boolean
  title: string
  emptyText: string
  hasShots: boolean
  shotItems: ReactNode
}

export function RunSnapshotShotList({
  visible,
  title,
  emptyText,
  hasShots,
  shotItems,
}: RunSnapshotShotListProps) {
  if (!visible) return null

  return (
    <Box sx={{ mb: 1 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
        {title}
      </Typography>
      {hasShots ? shotItems : <Typography variant="body2" color="text.secondary">{emptyText}</Typography>}
    </Box>
  )
}

type RunSnapshotAssetPreviewSectionProps = {
  visible: boolean
  shotCount: number
  assetCount: number
  keyframeCount: number
  midframeCount: number
  videoClipCount: number
  pathSummary?: string | null
  keyframeGrid?: ReactNode
  midframeGrid?: ReactNode
  videoClipGrid?: ReactNode
}

export function RunSnapshotAssetPreviewSection({
  visible,
  shotCount,
  assetCount,
  keyframeCount,
  midframeCount,
  videoClipCount,
  pathSummary,
  keyframeGrid,
  midframeGrid,
  videoClipGrid,
}: RunSnapshotAssetPreviewSectionProps) {
  if (!visible) return null

  return (
    <Box sx={{ mb: 1 }}>
      <Stack direction="row" spacing={1} flexWrap="wrap" mb={0.5}>
        <Chip size="small" label={`镜头: ${shotCount}`} />
        <Chip size="small" label={`资产: ${assetCount}`} />
        <Chip size="small" label={`KF: ${keyframeCount}`} />
        <Chip size="small" label={`MF: ${midframeCount}`} />
        <Chip size="small" label={`VC: ${videoClipCount}`} />
      </Stack>

      {pathSummary ? (
        <Typography variant="caption" color="text.secondary" display="block">
          {pathSummary}
        </Typography>
      ) : null}

      {keyframeGrid ?? null}
      {midframeGrid ?? null}
      {videoClipGrid ?? null}
    </Box>
  )
}

type RunSnapshotMergedVideoSectionProps = {
  visible: boolean
  title: string
  description: string
  panel?: ReactNode
}

export function RunSnapshotMergedVideoSection({
  visible,
  title,
  description,
  panel,
}: RunSnapshotMergedVideoSectionProps) {
  if (!visible) return null

  return (
    <Box sx={{ mb: 1 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
        {title}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {description}
      </Typography>
      {panel ?? null}
    </Box>
  )
}
