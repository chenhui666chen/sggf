import type { ReactNode } from 'react'

import CloseIcon from '@mui/icons-material/Close'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  Grid,
  IconButton,
  InputLabel,
  LinearProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
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

type DreamweaverConfigDialogProjectAlertActionProps = {
  onClick: () => void
}

export function DreamweaverConfigDialogProjectAlertAction({
  onClick,
}: DreamweaverConfigDialogProjectAlertActionProps) {
  return (
    <Button size="small" variant="outlined" onClick={onClick}>
      去项目列表
    </Button>
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

type DreamweaverConfigDialogChapterToolbarProps = {
  toggleAllLabel: string
  onToggleAll: () => void
  toggleAllDisabled: boolean
  onRefresh: () => void
  refreshDisabled: boolean
  refreshStartIcon?: ReactNode
}

export function DreamweaverConfigDialogChapterToolbar({
  toggleAllLabel,
  onToggleAll,
  toggleAllDisabled,
  onRefresh,
  refreshDisabled,
  refreshStartIcon,
}: DreamweaverConfigDialogChapterToolbarProps) {
  return (
    <>
      <Button size="small" onClick={onToggleAll} disabled={toggleAllDisabled}>
        {toggleAllLabel}
      </Button>
      <Button size="small" startIcon={refreshStartIcon ?? undefined} onClick={onRefresh} disabled={refreshDisabled}>
        刷新
      </Button>
    </>
  )
}

type DreamweaverConfigDialogChapterItemProps = {
  chapterId: number
  title: string
  snippet: string
  checked: boolean
  disabled: boolean
  onToggle: (chapterId: number) => void
}

export function DreamweaverConfigDialogChapterItem({
  chapterId,
  title,
  snippet,
  checked,
  disabled,
  onToggle,
}: DreamweaverConfigDialogChapterItemProps) {
  return (
    <ListItem
      disablePadding
      secondaryAction={
        <Checkbox edge="end" size="small" disabled={disabled} checked={checked} onChange={() => onToggle(chapterId)} />
      }
    >
      <ListItemButton onClick={() => onToggle(chapterId)} disabled={disabled} sx={{ pr: 6 }}>
        <ListItemText primary={title} secondary={snippet} />
      </ListItemButton>
    </ListItem>
  )
}

type DreamweaverConfigDialogChapterListProps = {
  loading: boolean
  children: ReactNode
}

export function DreamweaverConfigDialogChapterList({
  loading,
  children,
}: DreamweaverConfigDialogChapterListProps) {
  if (loading) {
    return <LinearProgress />
  }

  return <List dense disablePadding>{children}</List>
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

type DreamweaverConfigDialogStrategyToggleFieldProps = {
  title: string
  checked: boolean
  onChange: (checked: boolean) => void
  enabledLabel: string
  disabledLabel: string
  description: string
  disabled?: boolean
}

export function DreamweaverConfigDialogStrategyToggleField({
  title,
  checked,
  onChange,
  enabledLabel,
  disabledLabel,
  description,
  disabled = false,
}: DreamweaverConfigDialogStrategyToggleFieldProps) {
  return (
    <Stack spacing={0.5}>
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography variant="body2" sx={{ fontWeight: 700 }}>
          {title}
        </Typography>
        <FormControlLabel
          sx={{ mr: 0 }}
          control={<Switch checked={checked} onChange={(e) => onChange(e.target.checked)} disabled={disabled} />}
          label={checked ? enabledLabel : disabledLabel}
        />
      </Stack>
      <Typography variant="caption" color="text.secondary">
        {description}
      </Typography>
    </Stack>
  )
}

type DreamweaverConfigDialogExperimentFieldProps = {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

export function DreamweaverConfigDialogExperimentField({
  value,
  onChange,
  disabled = false,
}: DreamweaverConfigDialogExperimentFieldProps) {
  return (
    <Stack spacing={0.5}>
      <Typography variant="body2" sx={{ fontWeight: 700 }}>
        实验标签（可选）
      </Typography>
      <TextField
        size="small"
        fullWidth
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder="例如 A / B / control / treatment"
        inputProps={{ maxLength: 32 }}
      />
      <Typography variant="caption" color="text.secondary">
        仅用于标记并对比不同策略效果，不会自动改变生成逻辑。
      </Typography>
    </Stack>
  )
}

type DreamweaverConfigDialogSelectFieldProps = {
  labelId: string
  label: string
  value: string
  onChange: (value: string) => void
  options: Array<{ value: string; label: string }>
  disabled?: boolean
}

export function DreamweaverConfigDialogSelectField({
  labelId,
  label,
  value,
  onChange,
  options,
  disabled = false,
}: DreamweaverConfigDialogSelectFieldProps) {
  return (
    <FormControl fullWidth size="small" disabled={disabled}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select labelId={labelId} value={value} label={label} onChange={(e) => onChange(String(e.target.value))}>
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value}>
            {option.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
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

type DreamweaverConfigDialogMainGridProps = {
  chapterSelection: ReactNode
  sidePanel: ReactNode
}

export function DreamweaverConfigDialogMainGrid({
  chapterSelection,
  sidePanel,
}: DreamweaverConfigDialogMainGridProps) {
  return (
    <Grid container spacing={2}>
      <Grid item xs={12} md={7}>
        {chapterSelection}
      </Grid>

      <Grid item xs={12} md={5}>
        <Stack spacing={2}>{sidePanel}</Stack>
      </Grid>
    </Grid>
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
