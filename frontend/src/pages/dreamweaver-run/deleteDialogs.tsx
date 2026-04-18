import type { ReactNode } from 'react'

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
        <WarningIcon sx={{ color: '#f44336' }} />
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
        进度：{progress.current}/{progress.total}
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
  if (!result) return null

  return (
    <Alert severity={result.failed ? 'warning' : 'success'} sx={{ mt: 1 }}>
      已删除：{result.deleted}；跳过：{result.skipped}；失败：{result.failed}
      {result.errors.length > 0 && (
        <Box sx={{ mt: 1 }}>
          {result.errors.slice(0, 6).map((msg) => (
            <Typography key={msg} variant="caption" display="block" sx={{ fontFamily: 'monospace' }}>
              {msg}
            </Typography>
          ))}
          {result.errors.length > 6 && (
            <Typography variant="caption" display="block" color="text.secondary">
              ...还有 {result.errors.length - 6} 条错误
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
  return (
    <DialogContent dividers>
      <Alert severity="warning" sx={{ mb: 2 }}>
        此操作将级联删除筛选出的 runs 的数据库记录与 runs/{'{run_id}'} 产物文件，不可恢复；不会删除项目公共素材库，可复用。运行中或排队中的 run 将自动跳过。
      </Alert>
      <Typography variant="body2" sx={{ mb: 1 }}>
        本次将删除：{targetCount} 个 run；跳过：{skippedCount} 个（运行中/排队中）。
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
  return (
    <DialogActions>
      <Button onClick={onClose} disabled={submitting}>
        {hasResult ? '关闭' : '取消'}
      </Button>
      {!hasResult && (
        <Button variant="contained" color="error" onClick={onConfirm} disabled={submitting || !hasTargets}>
          {submitting ? '删除中...' : '确认批量删除'}
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
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DreamweaverDangerDialogTitle title="确认批量删除" />
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
  return (
    <DialogContent dividers>
      <Alert severity="warning" sx={{ mb: 2 }}>
        此操作将级联删除该次 run 的数据库记录与 runs/{'{run_id}'} 产物文件，不可恢复；不会删除项目公共素材库，可复用。
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
  return (
    <DialogActions>
      <Button onClick={onClose} disabled={submitting}>
        取消
      </Button>
      <Button variant="contained" color="error" onClick={onConfirm} disabled={submitting || !hasRunId}>
        {submitting ? '删除中...' : '确认删除'}
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
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DreamweaverDangerDialogTitle title="确认删除" />
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
