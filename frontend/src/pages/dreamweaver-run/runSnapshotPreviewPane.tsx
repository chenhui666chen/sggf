import type { ReactNode } from 'react'

import { Alert, Box, Button, Chip, LinearProgress, Stack, Typography } from '@mui/material'

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

type RunSnapshotRefreshButtonProps = {
  label: string
  onClick: () => void
  disabled?: boolean
  loading?: boolean
}

export function RunSnapshotRefreshButton({
  label,
  onClick,
  disabled = false,
  loading = false,
}: RunSnapshotRefreshButtonProps) {
  return (
    <Button size="small" variant="outlined" onClick={onClick} disabled={disabled}>
      {loading ? '加载中…' : label}
    </Button>
  )
}

type RunSnapshotLoadedChipProps = {
  visible: boolean
  label?: string
}

export function RunSnapshotLoadedChip({
  visible,
  label = '快照已加载',
}: RunSnapshotLoadedChipProps) {
  if (!visible) return null

  return <Chip size="small" label={label} color="success" />
}

type RunSnapshotErrorAlertProps = {
  message?: string | null
  spacingKey?: 'mb' | 'mt'
  spacingValue?: number
}

export function RunSnapshotErrorAlert({
  message,
  spacingKey = 'mb',
  spacingValue = 1,
}: RunSnapshotErrorAlertProps) {
  if (!message) return null

  return (
    <Alert severity="error" sx={{ [spacingKey]: spacingValue }}>
      {message}
    </Alert>
  )
}

type RunSnapshotLoadingBarProps = {
  visible: boolean
  spacingKey?: 'mb' | 'mt'
  spacingValue?: number
}

export function RunSnapshotLoadingBar({
  visible,
  spacingKey = 'mb',
  spacingValue = 1,
}: RunSnapshotLoadingBarProps) {
  if (!visible) return null

  return <LinearProgress sx={{ [spacingKey]: spacingValue }} />
}

type RunSnapshotRefreshControlsProps = {
  visible: boolean
  label: string
  onRefresh: () => void
  refreshDisabled?: boolean
  refreshLoading?: boolean
  loaded: boolean
}

export function RunSnapshotRefreshControls({
  visible,
  label,
  onRefresh,
  refreshDisabled = false,
  refreshLoading = false,
  loaded,
}: RunSnapshotRefreshControlsProps) {
  if (!visible) return null

  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" mb={1}>
      <RunSnapshotRefreshButton
        label={label}
        onClick={onRefresh}
        disabled={refreshDisabled}
        loading={refreshLoading}
      />
      <RunSnapshotLoadedChip visible={loaded} />
    </Stack>
  )
}

type RunSnapshotSectionStatusProps = {
  label: string
  onRefresh: () => void
  refreshDisabled?: boolean
  refreshLoading?: boolean
  loaded: boolean
  loading: boolean
  errorMessage?: string | null
  chips?: Array<{ key: string; label: string }>
  marginTop?: number
}

export function RunSnapshotSectionStatus({
  label,
  onRefresh,
  refreshDisabled = false,
  refreshLoading = false,
  loaded,
  loading,
  errorMessage,
  chips = [],
  marginTop = 1,
}: RunSnapshotSectionStatusProps) {
  return (
    <>
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: marginTop }}>
        <RunSnapshotRefreshButton
          label={label}
          onClick={onRefresh}
          disabled={refreshDisabled}
          loading={refreshLoading}
        />
        <RunSnapshotLoadedChip visible={loaded} />
        {chips.map((chip) => (
          <Chip key={chip.key} size="small" label={chip.label} />
        ))}
      </Stack>
      <RunSnapshotErrorAlert message={errorMessage} spacingKey="mt" spacingValue={marginTop} />
      <RunSnapshotLoadingBar visible={loading} spacingKey="mt" spacingValue={marginTop} />
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
