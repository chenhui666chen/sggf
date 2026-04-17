import type { ReactNode } from 'react'

import { Alert, Box, Stack, Typography } from '@mui/material'

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
