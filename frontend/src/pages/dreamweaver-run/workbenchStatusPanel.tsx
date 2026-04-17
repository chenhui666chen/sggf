import type { MouseEventHandler, ReactNode } from 'react'

import { Button, Menu, Paper, Stack, Step, StepLabel, Stepper } from '@mui/material'

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
