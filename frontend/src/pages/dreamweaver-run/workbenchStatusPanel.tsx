import type { MouseEventHandler, ReactNode } from 'react'

import { Button, Card, CardContent, Chip, Grid, LinearProgress, Menu, MenuItem, Paper, Stack, Step, StepLabel, Stepper, Typography } from '@mui/material'

import { useTranslation } from 'react-i18next'

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

type DreamweaverWorkbenchStatusActionGroupProps = {
  items: Array<{
    key: string
    label: string
    onClick: () => void
    disabled?: boolean
    startIcon?: ReactNode
  }>
}

export function DreamweaverWorkbenchStatusActionGroup({
  items,
}: DreamweaverWorkbenchStatusActionGroupProps) {
  return (
    <>
      {items.map((item) => (
        <DreamweaverWorkbenchStatusActionButton
          key={item.key}
          label={item.label}
          onClick={item.onClick}
          disabled={item.disabled}
          startIcon={item.startIcon}
        />
      ))}
    </>
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
  const { t } = useTranslation()
  return (
    <>
      {runId && <Chip label={`RunID: ${runId}`} size="small" />}
      <Chip label={t('dreamweaverRun.chipProgress', { value: progressLabel })} size="small" color="primary" />
      {stateLabel && <Chip label={t('dreamweaverRun.chipStatus', { state: stateLabel })} size="small" />}
      {stageLabel && <Chip label={t('dreamweaverRun.chipStage', { stage: stageLabel })} size="small" />}
      {taskStatusLabel && (
        <Chip
          label={taskQueue ? t('dreamweaverRun.chipTaskWithQueue', { status: taskStatusLabel, queue: taskQueue }) : t('dreamweaverRun.chipTask', { status: taskStatusLabel })}
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

type DreamweaverWorkbenchRestartMenuItemsProps = {
  items: Array<{
    key: string
    label: string
    onClick: () => void
    disabled?: boolean
  }>
}

export function DreamweaverWorkbenchRestartMenuItems({
  items,
}: DreamweaverWorkbenchRestartMenuItemsProps) {
  return (
    <>
      {items.map((item) => (
        <MenuItem key={item.key} onClick={item.onClick} disabled={item.disabled}>
          {item.label}
        </MenuItem>
      ))}
    </>
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
  const { t } = useTranslation()
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" justifyContent="flex-end">
      {followVisible && (
        <Button size="small" variant="text" onClick={onFollow}>
          {t('dreamweaverRun.wbFollowProgress')}
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
    <Paper sx={{ p: 2, borderRadius: 2, bgcolor: 'background.paper', mb: 2 }}>
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
  const { t } = useTranslation()
  return (
    <Stack direction="row" spacing={1} alignItems="center" mb={1}>
      <Typography variant="h6" sx={{ fontWeight: 700 }}>
        {t('dreamweaverRun.wbCardTitle')}
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

type DreamweaverWorkbenchCardProps = {
  running: boolean
  taskProgress: number
  statusPanel: ReactNode
  taskHeader: ReactNode
  mainContent: ReactNode
  dialogs?: ReactNode
}

export function DreamweaverWorkbenchCard({
  running,
  taskProgress,
  statusPanel,
  taskHeader,
  mainContent,
  dialogs,
}: DreamweaverWorkbenchCardProps) {
  return (
    <DreamweaverWorkbenchCardShell
      header={<DreamweaverWorkbenchCardHeader running={running} taskProgress={taskProgress} />}
      statusPanel={statusPanel}
      taskHeader={taskHeader}
      mainContent={mainContent}
      dialogs={dialogs}
    />
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

type DreamweaverWorkbenchStatusScaffoldProps = {
  runId?: string | null
  progressLabel: number
  stateLabel?: string | null
  stageLabel?: string | null
  taskStatusLabel?: string | null
  taskQueue?: string | null
  taskStatusColor?: 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning'
  actionItems: Array<{
    key: string
    label: string
    onClick: () => void
    disabled?: boolean
    startIcon?: ReactNode
  }>
  restartActionLabel: string
  restartActionDisabled?: boolean
  restartActionStartIcon?: ReactNode
  onOpenRestartMenu: MouseEventHandler<HTMLButtonElement>
  restartAnchorEl: HTMLElement | null
  restartOpen: boolean
  onCloseRestartMenu: () => void
  restartMenuItems: Array<{
    key: string
    label: string
    onClick: () => void
    disabled?: boolean
  }>
  followVisible: boolean
  onFollow: () => void
  stepLabels: readonly string[]
  activeStep: number
  progressStep: number
  onStepClick: (idx: number) => void
}

export function DreamweaverWorkbenchStatusScaffold({
  runId,
  progressLabel,
  stateLabel,
  stageLabel,
  taskStatusLabel,
  taskQueue,
  taskStatusColor = 'default',
  actionItems,
  restartActionLabel,
  restartActionDisabled = false,
  restartActionStartIcon,
  onOpenRestartMenu,
  restartAnchorEl,
  restartOpen,
  onCloseRestartMenu,
  restartMenuItems,
  followVisible,
  onFollow,
  stepLabels,
  activeStep,
  progressStep,
  onStepClick,
}: DreamweaverWorkbenchStatusScaffoldProps) {
  return (
    <DreamweaverWorkbenchStatusPanel
      primarySection={
        <DreamweaverWorkbenchStatusPrimarySection
          chips={
            <DreamweaverWorkbenchStatusChipRow
              runId={runId}
              progressLabel={progressLabel}
              stateLabel={stateLabel}
              stageLabel={stageLabel}
              taskStatusLabel={taskStatusLabel}
              taskQueue={taskQueue}
              taskStatusColor={taskStatusColor}
            />
          }
          actions={<DreamweaverWorkbenchStatusActionGroup items={actionItems} />}
          restartAction={
            <DreamweaverWorkbenchRestartAction
              label={restartActionLabel}
              disabled={restartActionDisabled}
              startIcon={restartActionStartIcon}
              onClick={onOpenRestartMenu}
            />
          }
          restartMenu={
            <DreamweaverWorkbenchRestartMenu
              anchorEl={restartAnchorEl}
              open={restartOpen}
              onClose={onCloseRestartMenu}
              items={<DreamweaverWorkbenchRestartMenuItems items={restartMenuItems} />}
            />
          }
        />
      }
      rightActions={
        <DreamweaverWorkbenchStatusRightActions
          followVisible={followVisible}
          onFollow={onFollow}
        />
      }
      stepper={
        <DreamweaverWorkbenchStepper
          labels={stepLabels}
          activeStep={activeStep}
          progressStep={progressStep}
          onStepClick={onStepClick}
        />
      }
    />
  )
}
