import type { ReactNode } from 'react'

import CloseIcon from '@mui/icons-material/Close'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Stack,
  Typography,
} from '@mui/material'

type DreamweaverConfigDialogTitleProps = {
  title: string
  subtitle: string
  onClose: () => void
}

export function DreamweaverConfigDialogTitle({
  title,
  subtitle,
  onClose,
}: DreamweaverConfigDialogTitleProps) {
  return (
    <DialogTitle sx={{ pb: 1 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h6" sx={{ fontWeight: 800 }}>
            {title}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {subtitle}
          </Typography>
        </Box>
        <IconButton onClick={onClose} size="small" aria-label="关闭">
          <CloseIcon fontSize="small" />
        </IconButton>
      </Stack>
    </DialogTitle>
  )
}

type DreamweaverConfigDialogProjectSectionProps = {
  lockedProjectId?: number | null
  projectTitle?: string | null
  action?: ReactNode
}

export function DreamweaverConfigDialogProjectSection({
  lockedProjectId,
  projectTitle,
  action,
}: DreamweaverConfigDialogProjectSectionProps) {
  if (lockedProjectId) {
    return (
      <Box
        sx={{
          p: 1.5,
          borderRadius: 2,
          border: '1px solid rgba(0,0,0,0.08)',
          bgcolor: 'rgba(0,0,0,0.04)',
        }}
      >
        <Typography variant="caption" color="text.secondary" display="block">
          当前项目
        </Typography>
        <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
          {projectTitle || `项目 #${lockedProjectId}`}
        </Typography>
      </Box>
    )
  }

  return (
    <Alert severity="info" action={action ?? undefined}>
      请先在项目列表选择一个项目，再进入生成配置。
    </Alert>
  )
}

type DreamweaverConfigDialogCardProps = {
  title: string
  children: ReactNode
  footer?: ReactNode
}

function DreamweaverConfigDialogCard({
  title,
  children,
  footer,
}: DreamweaverConfigDialogCardProps) {
  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 800, mb: 1 }}>
        {title}
      </Typography>
      {children}
      {footer ?? null}
    </Paper>
  )
}

type DreamweaverConfigDialogChapterSelectionCardProps = {
  toolbarActions: ReactNode
  listContent: ReactNode
  helperText: string
  maxHeight: string | number
}

export function DreamweaverConfigDialogChapterSelectionCard({
  toolbarActions,
  listContent,
  helperText,
  maxHeight,
}: DreamweaverConfigDialogChapterSelectionCardProps) {
  return (
    <DreamweaverConfigDialogCard title="章节选择" footer={<Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>{helperText}</Typography>}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
        <Box />
        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
          {toolbarActions}
        </Stack>
      </Stack>

      <Box
        sx={{
          maxHeight,
          overflow: 'auto',
          border: '1px solid rgba(0,0,0,0.08)',
          borderRadius: 2,
        }}
      >
        {listContent}
      </Box>
    </DreamweaverConfigDialogCard>
  )
}

type DreamweaverConfigDialogStrategyCardProps = {
  content: ReactNode
  helperText: string
}

export function DreamweaverConfigDialogStrategyCard({
  content,
  helperText,
}: DreamweaverConfigDialogStrategyCardProps) {
  return (
    <DreamweaverConfigDialogCard
      title="生成策略"
      footer={
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          {helperText}
        </Typography>
      }
    >
      <Stack spacing={1.5}>{content}</Stack>
    </DreamweaverConfigDialogCard>
  )
}

type DreamweaverConfigDialogVisualSettingsCardProps = {
  notices?: ReactNode
  fields: ReactNode
  helperText: string
}

export function DreamweaverConfigDialogVisualSettingsCard({
  notices,
  fields,
  helperText,
}: DreamweaverConfigDialogVisualSettingsCardProps) {
  return (
    <DreamweaverConfigDialogCard
      title="画面设置"
      footer={
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
          {helperText}
        </Typography>
      }
    >
      {notices ?? null}
      {fields}
    </DreamweaverConfigDialogCard>
  )
}

type DreamweaverConfigDialogContentProps = {
  errorNotice?: ReactNode
  projectSection: ReactNode
  mainGrid: ReactNode
}

export function DreamweaverConfigDialogContent({
  errorNotice,
  projectSection,
  mainGrid,
}: DreamweaverConfigDialogContentProps) {
  return (
    <DialogContent dividers sx={{ pt: 2 }}>
      {errorNotice ?? null}
      <Stack spacing={2}>
        {projectSection}
        {mainGrid}
      </Stack>
    </DialogContent>
  )
}

type DreamweaverConfigDialogActionsProps = {
  onClose: () => void
  onRun: () => void
  runDisabled: boolean
}

export function DreamweaverConfigDialogActions({
  onClose,
  onRun,
  runDisabled,
}: DreamweaverConfigDialogActionsProps) {
  return (
    <DialogActions>
      <Button onClick={onClose}>关闭</Button>
      <Button variant="contained" onClick={onRun} disabled={runDisabled}>
        开始生成
      </Button>
    </DialogActions>
  )
}

type DreamweaverConfigDialogShellProps = {
  open: boolean
  onClose: () => void
  fullScreen: boolean
  title: ReactNode
  content: ReactNode
  actions: ReactNode
}

export function DreamweaverConfigDialogShell({
  open,
  onClose,
  fullScreen,
  title,
  content,
  actions,
}: DreamweaverConfigDialogShellProps) {
  return (
    <Dialog open={open} onClose={onClose} fullScreen={fullScreen} maxWidth="md" fullWidth>
      {title}
      {content}
      {actions}
    </Dialog>
  )
}
