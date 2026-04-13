import { useMemo } from 'react'
import { Box, Step, StepLabel, Stepper, Typography, Paper, Chip, Stack } from '@mui/material'
import { stageToPreviewStep } from '@/constants/dreamweaver'

const PREVIEW_STEPS = ['剧本', '分镜', '素材', '镜头', '合成'] as const

interface PreviewStepperProps {
  currentStep: number
  stage: string | null
  progress: number
  onStepClick?: (step: number) => void
  interactive?: boolean
}

export function PreviewStepper({
  currentStep,
  stage,
  progress,
  onStepClick,
  interactive = false,
}: PreviewStepperProps) {
  const stepFromStage = useMemo(() => stageToPreviewStep(stage), [stage])
  const activeStep = currentStep >= 0 ? currentStep : stepFromStage

  const getStepStatus = (stepIndex: number): 'completed' | 'active' | 'pending' => {
    if (stepIndex < activeStep) return 'completed'
    if (stepIndex === activeStep) return 'active'
    return 'pending'
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          生成进度
        </Typography>
        {stage && (
          <Chip
            size="small"
            label={stage}
            color="primary"
            variant="outlined"
          />
        )}
      </Stack>
      <Stepper activeStep={activeStep} alternativeLabel>
        {PREVIEW_STEPS.map((label, index) => {
          const status = getStepStatus(index)
          return (
            <Step
              key={label}
              completed={status === 'completed'}
              active={status === 'active'}
              onClick={() => interactive && onStepClick?.(index)}
              sx={{
                cursor: interactive ? 'pointer' : 'default',
                '&:hover': interactive ? { opacity: 0.8 } : {},
              }}
            >
              <StepLabel
                StepIconProps={{
                  sx: {
                    '&.MuiStepIcon-completed': {
                      color: 'success.main',
                    },
                    '&.MuiStepIcon-active': {
                      color: 'primary.main',
                    },
                  },
                }}
              >
                <Typography
                  variant="caption"
                  sx={{
                    fontWeight: status === 'active' ? 600 : 400,
                    color: status === 'active' ? 'primary.main' : 'text.secondary',
                  }}
                >
                  {label}
                </Typography>
              </StepLabel>
            </Step>
          )
        })}
      </Stepper>
      {progress > 0 && progress < 100 && (
        <Box sx={{ mt: 1.5 }}>
          <Box
            sx={{
              height: 4,
              bgcolor: 'grey.200',
              borderRadius: 2,
              overflow: 'hidden',
            }}
          >
            <Box
              sx={{
                height: '100%',
                width: `${progress}%`,
                bgcolor: 'primary.main',
                transition: 'width 0.3s ease',
              }}
            />
          </Box>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block', textAlign: 'center' }}>
            {Math.round(progress)}% 完成
          </Typography>
        </Box>
      )}
    </Paper>
  )
}
