import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import WarningIcon from '@mui/icons-material/Warning'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Stack,
  Typography,
} from '@mui/material'

import type { BulkDeleteProgress, BulkDeleteResult } from '@/types/dreamweaver'

type DreamweaverDangerDialogTitleProps = {
  title: string
}

function DreamweaverDangerDialogTitle({ title }: DreamweaverDangerDialogTitleProps) {
  return (
    <DialogTitle>
      <Stack direction="row" spacing={1} alignItems="center">
        <WarningIcon sx={{ color: 'error.main' }} />
        <Typography variant="h6">{title}</Typography>
      </Stack>
    </DialogTitle>
  )
}

type DreamweaverBulkDeleteProgressSectionProps = {
  progress?: BulkDeleteProgress | null
}

function DreamweaverBulkDeleteProgressSection({
  progress,
}: DreamweaverBulkDeleteProgressSectionProps) {
  const { t } = useTranslation()
  if (!progress) return null

  const progressValue =
    progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : undefined

  return (
    <Stack spacing={1} sx={{ mb: 1 }}>
      <LinearProgress
        variant={progress.total > 0 ? 'determinate' : 'indeterminate'}
        value={progressValue}
      />
      <Typography variant="caption" color="text.secondary">
        {t('dreamweaverDelete.progress', { current: progress.current, total: progress.total })}
      </Typography>
    </Stack>
  )
}

type DreamweaverBulkDeleteResultAlertProps = {
  result?: BulkDeleteResult | null
}

function DreamweaverBulkDeleteResultAlert({
  result,
}: DreamweaverBulkDeleteResultAlertProps) {
  const { t } = useTranslation()
  if (!result) return null

  return (
    <Alert severity={result.failed ? 'warning' : 'success'} sx={{ mt: 1 }}>
      {t('dreamweaverDelete.resultSummary', { deleted: result.deleted, skipped: result.skipped, failed: result.failed })}
      {result.errors.length > 0 && (
        <Box sx={{ mt: 1 }}>
          {result.errors.slice(0, 6).map((msg) => (
            <Typography key={msg} variant="caption" display="block" sx={{ fontFamily: 'monospace' }}>
              {msg}
            </Typography>
          ))}
          {result.errors.length > 6 && (
            <Typography variant="caption" display="block" color="text.secondary">
              {t('dreamweaverDelete.moreErrors', { count: result.errors.length - 6 })}
            </Typography>
          )}
        </Box>
      )}
    </Alert>
  )
}

type DreamweaverBulkDeleteDialogContentProps = {
  targetCount: number
  skippedCount: number
  progress?: BulkDeleteProgress | null
  error?: string | null
  result?: BulkDeleteResult | null
}

export function DreamweaverBulkDeleteDialogContent({
  targetCount,
  skippedCount,
  progress,
  error,
  result,
}: DreamweaverBulkDeleteDialogContentProps) {
  const { t } = useTranslation()
  return (
    <DialogContent dividers>
      <Alert severity="warning" sx={{ mb: 2 }}>
        {t('dreamweaverDelete.bulkDangerHint')}
      </Alert>
      <Typography variant="body2" sx={{ mb: 1 }}>
        {t('dreamweaverDelete.bulkTargetSummary', { targetCount, skippedCount })}
      </Typography>

      <DreamweaverBulkDeleteProgressSection progress={progress} />

      {error && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {error}
        </Alert>
      )}

      <DreamweaverBulkDeleteResultAlert result={result} />
    </DialogContent>
  )
}

type DreamweaverBulkDeleteDialogActionsProps = {
  submitting: boolean
  hasResult: boolean
  hasTargets: boolean
  onClose: () => void
  onConfirm: () => void
}

export function DreamweaverBulkDeleteDialogActions({
  submitting,
  hasResult,
  hasTargets,
  onClose,
  onConfirm,
}: DreamweaverBulkDeleteDialogActionsProps) {
  const { t } = useTranslation()
  return (
    <DialogActions>
      <Button onClick={onClose} disabled={submitting}>
        {hasResult ? t('action.close') : t('action.cancel')}
      </Button>
      {!hasResult && (
        <Button variant="contained" color="error" onClick={onConfirm} disabled={submitting || !hasTargets}>
          {submitting ? t('dreamweaverDelete.deleting') : t('dreamweaverDelete.confirmBulkDelete')}
        </Button>
      )}
    </DialogActions>
  )
}

type DreamweaverBulkDeleteDialogShellProps = {
  open: boolean
  onClose: () => void
  content: ReactNode
  actions: ReactNode
}

export function DreamweaverBulkDeleteDialogShell({
  open,
  onClose,
  content,
  actions,
}: DreamweaverBulkDeleteDialogShellProps) {
  const { t } = useTranslation()
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DreamweaverDangerDialogTitle title={t('dreamweaverDelete.confirmBulkDelete')} />
      {content}
      {actions}
    </Dialog>
  )
}

type DreamweaverDeleteRunDialogContentProps = {
  runId?: string | null
  error?: string | null
}

export function DreamweaverDeleteRunDialogContent({
  runId,
  error,
}: DreamweaverDeleteRunDialogContentProps) {
  const { t } = useTranslation()
  return (
    <DialogContent dividers>
      <Alert severity="warning" sx={{ mb: 2 }}>
        {t('dreamweaverDelete.singleDangerHint')}
      </Alert>
      <Typography variant="body2" sx={{ fontFamily: 'monospace', mb: 1 }}>
        RunID: {runId || '-'}
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {error}
        </Alert>
      )}
    </DialogContent>
  )
}

type DreamweaverDeleteRunDialogActionsProps = {
  submitting: boolean
  hasRunId: boolean
  onClose: () => void
  onConfirm: () => void
}

export function DreamweaverDeleteRunDialogActions({
  submitting,
  hasRunId,
  onClose,
  onConfirm,
}: DreamweaverDeleteRunDialogActionsProps) {
  const { t } = useTranslation()
  return (
    <DialogActions>
      <Button onClick={onClose} disabled={submitting}>
        {t('action.cancel')}
      </Button>
      <Button variant="contained" color="error" onClick={onConfirm} disabled={submitting || !hasRunId}>
        {submitting ? t('dreamweaverDelete.deleting') : t('dreamweaverDelete.confirmDelete')}
      </Button>
    </DialogActions>
  )
}

type DreamweaverDeleteRunDialogShellProps = {
  open: boolean
  onClose: () => void
  content: ReactNode
  actions: ReactNode
}

export function DreamweaverDeleteRunDialogShell({
  open,
  onClose,
  content,
  actions,
}: DreamweaverDeleteRunDialogShellProps) {
  const { t } = useTranslation()
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DreamweaverDangerDialogTitle title={t('dreamweaverDelete.confirmDelete')} />
      {content}
      {actions}
    </Dialog>
  )
}

type DreamweaverBulkDeleteDialogProps = {
  open: boolean
  onClose: () => void
  targetCount: number
  skippedCount: number
  progress?: BulkDeleteProgress | null
  error?: string | null
  result?: BulkDeleteResult | null
  submitting: boolean
  onConfirm: () => void
}

export function DreamweaverBulkDeleteDialog({
  open,
  onClose,
  targetCount,
  skippedCount,
  progress,
  error,
  result,
  submitting,
  onConfirm,
}: DreamweaverBulkDeleteDialogProps) {
  return (
    <DreamweaverBulkDeleteDialogShell
      open={open}
      onClose={onClose}
      content={
        <DreamweaverBulkDeleteDialogContent
          targetCount={targetCount}
          skippedCount={skippedCount}
          progress={progress}
          error={error}
          result={result}
        />
      }
      actions={
        <DreamweaverBulkDeleteDialogActions
          submitting={submitting}
          hasResult={Boolean(result)}
          hasTargets={targetCount > 0}
          onClose={onClose}
          onConfirm={onConfirm}
        />
      }
    />
  )
}

type DreamweaverDeleteRunDialogProps = {
  open: boolean
  onClose: () => void
  runId?: string | null
  error?: string | null
  submitting: boolean
  onConfirm: () => void
}

export function DreamweaverDeleteRunDialog({
  open,
  onClose,
  runId,
  error,
  submitting,
  onConfirm,
}: DreamweaverDeleteRunDialogProps) {
  return (
    <DreamweaverDeleteRunDialogShell
      open={open}
      onClose={onClose}
      content={<DreamweaverDeleteRunDialogContent runId={runId} error={error} />}
      actions={
        <DreamweaverDeleteRunDialogActions
          submitting={submitting}
          hasRunId={Boolean(runId)}
          onClose={onClose}
          onConfirm={onConfirm}
        />
      }
    />
  )
}
