import type { ReactNode } from 'react'

import DeleteIcon from '@mui/icons-material/Delete'
import HistoryIcon from '@mui/icons-material/History'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  ListItem,
  Stack,
  Typography,
} from '@mui/material'

type DreamweaverHistoryDialogTitleProps = {
  projectTitle?: string | null
}

export function DreamweaverHistoryDialogTitle({ projectTitle }: DreamweaverHistoryDialogTitleProps) {
  return (
    <DialogTitle>
      <Stack direction="row" spacing={1} alignItems="center">
        <HistoryIcon color="primary" />
        <Typography variant="h6">历史记录</Typography>
        {projectTitle && (
          <Typography variant="body2" color="text.secondary">
            {projectTitle}
          </Typography>
        )}
      </Stack>
    </DialogTitle>
  )
}

type DreamweaverHistoryDialogToolbarProps = {
  filters: ReactNode
  actions: ReactNode
}

export function DreamweaverHistoryDialogToolbar({
  filters,
  actions,
}: DreamweaverHistoryDialogToolbarProps) {
  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 1 }}>
      {filters}
      <Box sx={{ flex: 1 }} />
      {actions}
    </Stack>
  )
}

type DreamweaverHistoryStatusFilterChipProps = {
  label: string
  count: number
  color: 'default' | 'primary' | 'success' | 'error' | 'warning' | 'info'
  selected: boolean
  onClick: () => void
}

export function DreamweaverHistoryStatusFilterChip({
  label,
  count,
  color,
  selected,
  onClick,
}: DreamweaverHistoryStatusFilterChipProps) {
  return (
    <Chip
      size="small"
      label={`${label} (${count})`}
      color={color}
      variant={selected ? 'filled' : 'outlined'}
      onClick={onClick}
    />
  )
}

type DreamweaverHistoryToolbarActionsProps = {
  onRefresh: () => void
  refreshDisabled: boolean
  onBulkDelete: () => void
  bulkDeleteDisabled: boolean
  bulkDeleteLabel: string
}

export function DreamweaverHistoryToolbarActions({
  onRefresh,
  refreshDisabled,
  onBulkDelete,
  bulkDeleteDisabled,
  bulkDeleteLabel,
}: DreamweaverHistoryToolbarActionsProps) {
  return (
    <>
      <Button size="small" variant="outlined" disabled={refreshDisabled} onClick={onRefresh}>
        刷新
      </Button>
      <Button size="small" variant="contained" color="error" disabled={bulkDeleteDisabled} onClick={onBulkDelete}>
        {bulkDeleteLabel}
      </Button>
    </>
  )
}

type DreamweaverHistoryRunItemSummaryProps = {
  statusLabel: string
  statusColor: 'default' | 'primary' | 'success' | 'error' | 'warning' | 'info'
  runId: string
  progressValue?: number | null
  stage?: string | null
  cameraTreeMode?: string | null
  cameraCount?: number | null
  cameraStatesCount?: number | null
  cameraScenesCount?: number | null
}

export function DreamweaverHistoryRunItemSummary({
  statusLabel,
  statusColor,
  runId,
  progressValue,
  stage,
  cameraTreeMode,
  cameraCount,
  cameraStatesCount,
  cameraScenesCount,
}: DreamweaverHistoryRunItemSummaryProps) {
  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
      <Chip size="small" label={statusLabel} color={statusColor} />
      <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
        {runId}
      </Typography>
      {typeof progressValue === 'number' && <Chip size="small" label={`进度: ${progressValue}%`} />}
      {stage && <Chip size="small" label={`阶段: ${stage}`} />}
      {cameraTreeMode && <Chip size="small" label={`CamTree: ${cameraTreeMode}`} variant="outlined" />}
      {typeof cameraCount === 'number' && <Chip size="small" label={`Cam: ${cameraCount}`} />}
      {typeof cameraStatesCount === 'number' && <Chip size="small" label={`CamState: ${cameraStatesCount}`} />}
      {typeof cameraScenesCount === 'number' && <Chip size="small" label={`CamScene: ${cameraScenesCount}`} />}
    </Stack>
  )
}

type DreamweaverHistoryRunItemActionsProps = {
  onView: () => void
  onDelete: () => void
}

export function DreamweaverHistoryRunItemActions({
  onView,
  onDelete,
}: DreamweaverHistoryRunItemActionsProps) {
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <Button size="small" variant="text" startIcon={<PlayArrowIcon fontSize="small" />} onClick={onView}>
        查看
      </Button>
      <Button size="small" variant="text" color="error" startIcon={<DeleteIcon fontSize="small" />} onClick={onDelete}>
        删除
      </Button>
    </Stack>
  )
}

type DreamweaverHistoryEmptyStateProps = {
  message: string
}

export function DreamweaverHistoryEmptyState({
  message,
}: DreamweaverHistoryEmptyStateProps) {
  return (
    <Typography variant="body2" color="text.secondary">
      {message}
    </Typography>
  )
}

type DreamweaverHistoryRunItemProps = {
  summary: ReactNode
  timeText?: string | null
  errorMessage?: string | null
  actions: ReactNode
}

export function DreamweaverHistoryRunItem({
  summary,
  timeText,
  errorMessage,
  actions,
}: DreamweaverHistoryRunItemProps) {
  return (
    <ListItem sx={{ border: '1px solid #eee', borderRadius: 2, mb: 1 }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        {summary}
        {timeText && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            {timeText}
          </Typography>
        )}
        {errorMessage && (
          <Typography variant="caption" color="error" display="block" sx={{ mt: 0.5 }}>
            {errorMessage}
          </Typography>
        )}
      </Box>
      {actions}
    </ListItem>
  )
}

type DreamweaverHistoryDialogContentProps = {
  error?: string | null
  loading: boolean
  toolbar: ReactNode
  emptyState?: ReactNode
  runList?: ReactNode
}

export function DreamweaverHistoryDialogContent({
  error,
  loading,
  toolbar,
  emptyState,
  runList,
}: DreamweaverHistoryDialogContentProps) {
  return (
    <DialogContent dividers>
      {error && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {error}
        </Alert>
      )}
      {loading && <LinearProgress sx={{ mb: 1 }} />}

      {toolbar}
      {emptyState ?? null}
      {runList ?? null}
    </DialogContent>
  )
}

type DreamweaverHistoryDialogShellProps = {
  open: boolean
  onClose: () => void
  title: ReactNode
  content: ReactNode
}

export function DreamweaverHistoryDialogShell({
  open,
  onClose,
  title,
  content,
}: DreamweaverHistoryDialogShellProps) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      {title}
      {content}
      <DialogActions>
        <Button onClick={onClose}>关闭</Button>
      </DialogActions>
    </Dialog>
  )
}
