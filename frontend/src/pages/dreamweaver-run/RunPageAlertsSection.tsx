import { Alert, Button, Stack, Typography } from '@mui/material'

import { useTranslation } from 'react-i18next'

import TaskPointsPrecheckAlert from '@/components/common/TaskPointsPrecheckAlert'
import type { TaskPointsPrecheckErrorDetail } from '@/services/api'

export interface RunPageAlertsSectionProps {
  taskPointsPrecheckError: TaskPointsPrecheckErrorDetail | null
  onClearTaskPointsPrecheckError: () => void
  safetyAuditAlertState: {
    show: boolean
    summary: string
    categories: string[]
    canApprove: boolean
  }
  safetyAuditApproveLoading: boolean
  safetyAuditApproveError: string | null
  onApproveSafetyAudit: () => void
  error: string | null
  qcWarning: boolean
  diagnosticPreflight: {
    allowed: boolean
    warnings: { length: number }
    errors: { length: number }
  } | null
}

export function RunPageAlertsSection({
  taskPointsPrecheckError,
  onClearTaskPointsPrecheckError,
  safetyAuditAlertState,
  safetyAuditApproveLoading,
  safetyAuditApproveError,
  onApproveSafetyAudit,
  error,
  qcWarning,
  diagnosticPreflight,
}: RunPageAlertsSectionProps) {
  const { t } = useTranslation()
  const errorAlert = (() => {
    if (taskPointsPrecheckError) {
      return (
        <TaskPointsPrecheckAlert
          detail={taskPointsPrecheckError}
          onClose={onClearTaskPointsPrecheckError}
          sx={{ mb: 2 }}
        />
      )
    }

    if (safetyAuditAlertState.show) {
      return (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            safetyAuditAlertState.canApprove ? (
              <Button
                color="inherit"
                size="small"
                onClick={onApproveSafetyAudit}
                disabled={safetyAuditApproveLoading}
              >
                {safetyAuditApproveLoading ? t('dreamweaverRun.raApproveLoading') : t('dreamweaverRun.raApproveAndFinish')}
              </Button>
            ) : undefined
          }
        >
          <Stack spacing={0.5}>
            <Typography variant="body2">
              {safetyAuditAlertState.summary}
            </Typography>
            {safetyAuditAlertState.categories.length > 0 && (
              <Typography variant="body2" color="text.secondary">
                {t('dreamweaverRun.raRiskCategories', { categories: safetyAuditAlertState.categories.join('、') })}
              </Typography>
            )}
            {safetyAuditApproveError && (
              <Typography variant="body2" color="inherit">
                {safetyAuditApproveError}
              </Typography>
            )}
          </Stack>
        </Alert>
      )
    }

    if (error) {
      return (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )
    }

    return null
  })()

  const qcWarningAlert = qcWarning ? (
    <Alert severity="warning" sx={{ mb: 2 }}>
      {t('dreamweaverRun.raQcWarning')}
    </Alert>
  ) : null

  const preflightMessage = diagnosticPreflight
    ? diagnosticPreflight.allowed
      ? t('dreamweaverRun.raPreflightWarnings', { count: diagnosticPreflight.warnings.length })
      : t('dreamweaverRun.raPreflightErrors', { count: diagnosticPreflight.errors.length })
    : null

  const preflightAlert = diagnosticPreflight && !(diagnosticPreflight.allowed && diagnosticPreflight.warnings.length === 0)
    ? (
        <Alert severity={diagnosticPreflight.allowed ? 'warning' : 'error'} sx={{ mb: 2 }}>
          {preflightMessage}
        </Alert>
      )
    : null

  return (
    <>
      {errorAlert}
      {qcWarningAlert}
      {preflightAlert}
    </>
  )
}
