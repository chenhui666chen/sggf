import type { ReactNode } from 'react'

import HistoryIcon from '@mui/icons-material/History'
import {
  Alert,
  Box,
  Button,
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
