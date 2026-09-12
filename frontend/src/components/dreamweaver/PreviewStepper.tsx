import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Box, Step, StepLabel, Stepper, Typography, Paper, Chip, Stack } from '@mui/material'
import { stageToPreviewStep } from '@/constants/dreamweaver'

const PREVIEW_STEP_KEYS = [
  'dreamweaverRun.previewStepScript',
  'dreamweaverRun.previewStepStoryboard',
  'dreamweaverRun.previewStepAssets',
  'dreamweaverRun.previewStepShots',
  'dreamweaverRun.previewStepMerged',
] as const

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
  const { t } = useTranslation()
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
          {t('dreamweaverRun.previewProgressTitle')}
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
        {PREVIEW_STEP_KEYS.map((labelKey, index) => {
          const status = getStepStatus(index)
          return (
            <Step
              key={labelKey}
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
                  {t(labelKey)}
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
            {t('dreamweaverRun.previewPercentComplete', { percent: Math.round(progress) })}
          </Typography>
        </Box>
      )}
    </Paper>
  )
}
