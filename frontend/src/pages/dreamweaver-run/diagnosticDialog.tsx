import type { ReactNode } from 'react'

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
  return (
    <DialogTitle>
      <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <BugReportIcon color="primary" />
          <Typography variant="h6">诊断面板</Typography>
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
  return (
    <>
      {!hasRunId && (
        <Alert severity="info" sx={{ mb: 1 }}>
          暂无 run_id，无法加载产物预览与诊断信息。
        </Alert>
      )}
      {hasRunId && !hasDiagnosticResult && (
        <Alert severity="info" sx={{ mb: 1 }}>
          暂无可用的套路快照/镜头信息。可尝试点击“刷新运行快照”，或等待任务落库后再查看。
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
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
      <Chip size="small" label={`镜头: ${shotCount}`} />
      {typeof keyframeCount === 'number' && <Chip size="small" label={`KF: ${keyframeCount}`} />}
      {typeof midframeCount === 'number' && <Chip size="small" label={`MF: ${midframeCount}`} />}
      {typeof videoClipCount === 'number' && <Chip size="small" label={`VC: ${videoClipCount}`} />}
      <Button size="small" variant="outlined" startIcon={<RefreshIcon fontSize="small" />} onClick={onRefresh} disabled={refreshDisabled}>
        {refreshLabel}
      </Button>
      <Button size="small" variant="outlined" startIcon={<ContentCopyIcon fontSize="small" />} onClick={onCopy} disabled={copyDisabled}>
        复制 Run 诊断
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
  return (
    <>
      {!hasDiagnosticResult && (
        <Typography variant="body2" color="text.secondary">
          无可展示内容
        </Typography>
      )}

      {hasDiagnosticResult && shotCount === 0 && (
        <Typography variant="body2" color="text.secondary">
          暂无镜头数据（storyboard 未落库或尚未生成）。
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
        <Button onClick={onClose}>关闭</Button>
      </DialogActions>
    </Dialog>
  )
}
