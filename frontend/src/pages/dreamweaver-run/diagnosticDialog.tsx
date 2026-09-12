import type { ReactNode } from 'react'

import { useTranslation } from 'react-i18next'

import BugReportIcon from '@mui/icons-material/BugReport'
import CloseIcon from '@mui/icons-material/Close'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import RefreshIcon from '@mui/icons-material/Refresh'
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  LinearProgress,
  Stack,
  Typography,
} from '@mui/material'

type DreamweaverDiagnosticDialogHeaderProps = {
  runId?: string | null
  state?: string | null
  stage?: string | null
  onClose: () => void
}

export function DreamweaverDiagnosticDialogHeader({
  runId,
  state,
  stage,
  onClose,
}: DreamweaverDiagnosticDialogHeaderProps) {
  const { t } = useTranslation()
  return (
    <DialogTitle>
      <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <BugReportIcon color="primary" />
          <Typography variant="h6">{t('dreamweaverRun.workbenchDiagnostics')}</Typography>
          {runId && (
            <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
              {runId}
            </Typography>
          )}
          {state && <Chip size="small" label={`state: ${state}`} />}
          {stage && <Chip size="small" label={`stage: ${stage}`} />}
        </Stack>
        <IconButton onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </Stack>
    </DialogTitle>
  )
}

type DreamweaverDiagnosticDialogStatusSectionProps = {
  hasRunId: boolean
  hasDiagnosticResult: boolean
  error?: string | null
  loading: boolean
}

export function DreamweaverDiagnosticDialogStatusSection({
  hasRunId,
  hasDiagnosticResult,
  error,
  loading,
}: DreamweaverDiagnosticDialogStatusSectionProps) {
  const { t } = useTranslation()
  return (
    <>
      {!hasRunId && (
        <Alert severity="info" sx={{ mb: 1 }}>
          {t('dreamweaverRun.diagnosticNoRunId')}
        </Alert>
      )}
      {hasRunId && !hasDiagnosticResult && (
        <Alert severity="info" sx={{ mb: 1 }}>
          {t('dreamweaverRun.diagnosticNoSnapshot')}
        </Alert>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}
      {loading && <LinearProgress sx={{ mb: 1 }} />}
    </>
  )
}

type DreamweaverDiagnosticDialogToolbarProps = {
  shotCount: number
  keyframeCount?: number | null
  midframeCount?: number | null
  videoClipCount?: number | null
  refreshLabel: string
  refreshDisabled: boolean
  copyDisabled: boolean
  onRefresh: () => void
  onCopy: () => void
}

export function DreamweaverDiagnosticDialogToolbar({
  shotCount,
  keyframeCount,
  midframeCount,
  videoClipCount,
  refreshLabel,
  refreshDisabled,
  copyDisabled,
  onRefresh,
  onCopy,
}: DreamweaverDiagnosticDialogToolbarProps) {
  const { t } = useTranslation()
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
      <Chip size="small" label={t('dreamweaverRun.snapshotShotsChip', { count: shotCount })} />
      {typeof keyframeCount === 'number' && <Chip size="small" label={`KF: ${keyframeCount}`} />}
      {typeof midframeCount === 'number' && <Chip size="small" label={`MF: ${midframeCount}`} />}
      {typeof videoClipCount === 'number' && <Chip size="small" label={`VC: ${videoClipCount}`} />}
      <Button size="small" variant="outlined" startIcon={<RefreshIcon fontSize="small" />} onClick={onRefresh} disabled={refreshDisabled}>
        {refreshLabel}
      </Button>
      <Button size="small" variant="outlined" startIcon={<ContentCopyIcon fontSize="small" />} onClick={onCopy} disabled={copyDisabled}>
        {t('dreamweaverRun.diagnosticCopyRun')}
      </Button>
    </Stack>
  )
}

type DreamweaverDiagnosticDialogEmptyStateProps = {
  hasDiagnosticResult: boolean
  shotCount: number
}

export function DreamweaverDiagnosticDialogEmptyState({
  hasDiagnosticResult,
  shotCount,
}: DreamweaverDiagnosticDialogEmptyStateProps) {
  const { t } = useTranslation()
  return (
    <>
      {!hasDiagnosticResult && (
        <Typography variant="body2" color="text.secondary">
          {t('dreamweaverRun.diagnosticEmpty')}
        </Typography>
      )}

      {hasDiagnosticResult && shotCount === 0 && (
        <Typography variant="body2" color="text.secondary">
          {t('dreamweaverRun.diagnosticNoShots')}
        </Typography>
      )}
    </>
  )
}

type DreamweaverDiagnosticDialogShellProps = {
  open: boolean
  onClose: () => void
  header: ReactNode
  statusSection: ReactNode
  toolbar: ReactNode
  sections?: ReactNode
  emptyState?: ReactNode
  shotAccordions?: ReactNode
}

export function DreamweaverDiagnosticDialogShell({
  open,
  onClose,
  header,
  statusSection,
  toolbar,
  sections,
  emptyState,
  shotAccordions,
}: DreamweaverDiagnosticDialogShellProps) {
  const { t } = useTranslation()
  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      {header}
      <DialogContent dividers>
        {statusSection}
        {toolbar}

        <Divider sx={{ mb: 1 }} />

        {sections ?? null}
        {emptyState ?? null}
        {shotAccordions ?? null}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('action.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}

type DreamweaverRunDiagnosticDialogProps = {
  open: boolean
  onClose: () => void
  runId?: string | null
  state?: string | null
  stage?: string | null
  hasRunId: boolean
  hasDiagnosticResult: boolean
  error?: string | null
  loading: boolean
  shotCount: number
  keyframeCount?: number | null
  midframeCount?: number | null
  videoClipCount?: number | null
  refreshLabel: string
  refreshDisabled: boolean
  copyDisabled: boolean
  onRefresh: () => void
  onCopy: () => void
  sections?: ReactNode
  shotAccordions?: ReactNode
}

export function DreamweaverRunDiagnosticDialog({
  open,
  onClose,
  runId,
  state,
  stage,
  hasRunId,
  hasDiagnosticResult,
  error,
  loading,
  shotCount,
  keyframeCount,
  midframeCount,
  videoClipCount,
  refreshLabel,
  refreshDisabled,
  copyDisabled,
  onRefresh,
  onCopy,
  sections,
  shotAccordions,
}: DreamweaverRunDiagnosticDialogProps) {
  return (
    <DreamweaverDiagnosticDialogShell
      open={open}
      onClose={onClose}
      header={
        <DreamweaverDiagnosticDialogHeader
          runId={runId}
          state={state}
          stage={stage}
          onClose={onClose}
        />
      }
      statusSection={
        <DreamweaverDiagnosticDialogStatusSection
          hasRunId={hasRunId}
          hasDiagnosticResult={hasDiagnosticResult}
          error={error}
          loading={loading}
        />
      }
      toolbar={
        <DreamweaverDiagnosticDialogToolbar
          shotCount={shotCount}
          keyframeCount={keyframeCount}
          midframeCount={midframeCount}
          videoClipCount={videoClipCount}
          refreshLabel={refreshLabel}
          refreshDisabled={refreshDisabled}
          copyDisabled={copyDisabled}
          onRefresh={onRefresh}
          onCopy={onCopy}
        />
      }
      sections={sections}
      emptyState={
        <DreamweaverDiagnosticDialogEmptyState
          hasDiagnosticResult={hasDiagnosticResult}
          shotCount={shotCount}
        />
      }
      shotAccordions={shotAccordions}
    />
  )
}
