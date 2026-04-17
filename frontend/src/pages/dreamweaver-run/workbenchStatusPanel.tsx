import type { MouseEventHandler, ReactNode } from 'react'

import { Button, Card, CardContent, Chip, Grid, LinearProgress, Menu, Paper, Stack, Step, StepLabel, Stepper, Typography } from '@mui/material'

type DreamweaverWorkbenchStatusActionButtonProps = {
  label: string
  onClick: () => void
  disabled?: boolean
  startIcon?: ReactNode
}

export function DreamweaverWorkbenchStatusActionButton({
  label,
  onClick,
  disabled,
  startIcon,
}: DreamweaverWorkbenchStatusActionButtonProps) {
  return (
    <Button size="small" variant="text" startIcon={startIcon} onClick={onClick} disabled={disabled}>
      {label}
    </Button>
  )
}

type DreamweaverWorkbenchStatusChipRowProps = {
  runId?: string | null
  progressLabel: number
  stateLabel?: string | null
  stageLabel?: string | null
  taskStatusLabel?: string | null
  taskQueue?: string | null
  taskStatusColor?: 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning'
}

export function DreamweaverWorkbenchStatusChipRow({
  runId,
  progressLabel,
  stateLabel,
  stageLabel,
  taskStatusLabel,
  taskQueue,
  taskStatusColor = 'default',
}: DreamweaverWorkbenchStatusChipRowProps) {
  return (
    <>
      {runId && <Chip label={`RunID: ${runId}`} size="small" />}
      <Chip label={`进度: ${progressLabel}%`} size="small" color="primary" />
      {stateLabel && <Chip label={`状态: ${stateLabel}`} size="small" />}
      {stageLabel && <Chip label={`阶段: ${stageLabel}`} size="small" />}
      {taskStatusLabel && (
        <Chip
          label={`任务: ${taskStatusLabel}${taskQueue ? `（${taskQueue}）` : ''}`}
          size="small"
          color={taskStatusColor}
        />
      )}
    </>
  )
}

type DreamweaverWorkbenchRestartActionProps = {
  label: string
  disabled?: boolean
  startIcon?: ReactNode
  onClick: MouseEventHandler<HTMLButtonElement>
}

export function DreamweaverWorkbenchRestartAction({
  label,
  disabled,
  startIcon,
  onClick,
}: DreamweaverWorkbenchRestartActionProps) {
  return (
    <Button size="small" variant="text" startIcon={startIcon} onClick={onClick} disabled={disabled}>
      {label}
    </Button>
  )
}

type DreamweaverWorkbenchRestartMenuProps = {
  anchorEl: HTMLElement | null
  open: boolean
  onClose: () => void
  items: ReactNode
}

export function DreamweaverWorkbenchRestartMenu({
  anchorEl,
  open,
  onClose,
  items,
}: DreamweaverWorkbenchRestartMenuProps) {
  return (
    <Menu
      anchorEl={anchorEl}
      open={open}
      onClose={onClose}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      transformOrigin={{ vertical: 'top', horizontal: 'left' }}
    >
      {items}
    </Menu>
  )
}

type DreamweaverWorkbenchStatusRightActionsProps = {
  followVisible: boolean
  onFollow: () => void
}

export function DreamweaverWorkbenchStatusRightActions({
  followVisible,
  onFollow,
}: DreamweaverWorkbenchStatusRightActionsProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" justifyContent="flex-end">
      {followVisible && (
        <Button size="small" variant="text" onClick={onFollow}>
          跟随进度
        </Button>
      )}
    </Stack>
  )
}

type DreamweaverWorkbenchStepperProps = {
  labels: readonly string[]
  activeStep: number
  progressStep: number
  onStepClick: (idx: number) => void
}

export function DreamweaverWorkbenchStepper({
  labels,
  activeStep,
  progressStep,
  onStepClick,
}: DreamweaverWorkbenchStepperProps) {
  return (
    <Stepper activeStep={activeStep}>
      {labels.map((label, idx) => (
        <Step
          key={label}
          completed={idx < progressStep}
          sx={{ cursor: 'pointer', px: 0.5 }}
          onClick={() => onStepClick(idx)}
        >
          <StepLabel
            sx={{
              '& .MuiStepLabel-label': {
                cursor: 'pointer',
                fontSize: '0.9rem',
                transition: 'color 0.2s, transform 0.2s',
                '&:hover': {
                  color: 'primary.main',
                  transform: 'scale(1.03)',
                },
              },
            }}
          >
            {label}
          </StepLabel>
        </Step>
      ))}
    </Stepper>
  )
}

type DreamweaverWorkbenchStatusPanelProps = {
  primarySection: ReactNode
  rightActions: ReactNode
  stepper: ReactNode
}

export function DreamweaverWorkbenchStatusPanel({
  primarySection,
  rightActions,
  stepper,
}: DreamweaverWorkbenchStatusPanelProps) {
  return (
    <Paper sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.95)', mb: 2 }}>
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" justifyContent="space-between" mb={1}>
        {primarySection}
        {rightActions}
      </Stack>
      {stepper}
    </Paper>
  )
}

type DreamweaverWorkbenchStatusPrimarySectionProps = {
  chips: ReactNode
  actions: ReactNode
  restartAction?: ReactNode
  restartMenu?: ReactNode
}

export function DreamweaverWorkbenchStatusPrimarySection({
  chips,
  actions,
  restartAction,
  restartMenu,
}: DreamweaverWorkbenchStatusPrimarySectionProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
      {chips}
      {actions}
      {restartAction ?? null}
      {restartMenu ?? null}
    </Stack>
  )
}

type DreamweaverWorkbenchCardHeaderProps = {
  running: boolean
  taskProgress: number
}

export function DreamweaverWorkbenchCardHeader({
  running,
  taskProgress,
}: DreamweaverWorkbenchCardHeaderProps) {
  return (
    <Stack direction="row" spacing={1} alignItems="center" mb={1}>
      <Typography variant="h6" sx={{ fontWeight: 700 }}>
        短剧工作台
      </Typography>
      {running && <LinearProgress variant="determinate" value={Math.max(0, Math.min(100, taskProgress))} sx={{ flex: 1 }} />}
    </Stack>
  )
}

type DreamweaverWorkbenchCardShellProps = {
  header: ReactNode
  statusPanel: ReactNode
  taskHeader: ReactNode
  mainContent: ReactNode
  dialogs?: ReactNode
}

export function DreamweaverWorkbenchCardShell({
  header,
  statusPanel,
  taskHeader,
  mainContent,
  dialogs,
}: DreamweaverWorkbenchCardShellProps) {
  return (
    <Card sx={{ borderRadius: 3 }}>
      <CardContent>
        {header}
        {statusPanel}
        {taskHeader}
        {mainContent}
        {dialogs ?? null}
      </CardContent>
    </Card>
  )
}

type DreamweaverWorkbenchSectionProps = {
  alerts?: ReactNode
  card: ReactNode
}

export function DreamweaverWorkbenchSection({
  alerts,
  card,
}: DreamweaverWorkbenchSectionProps) {
  return (
    <Grid container spacing={2.5}>
      <Grid item xs={12} md={12}>
        {alerts ?? null}
        {card}
      </Grid>
    </Grid>
  )
}
