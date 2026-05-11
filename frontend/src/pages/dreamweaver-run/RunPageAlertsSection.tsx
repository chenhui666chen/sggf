import { Alert, Button, Stack, Typography } from '@mui/material'

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
                {safetyAuditApproveLoading ? '放行中...' : '人工放行并完成本次 run'}
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
                风险分类：{safetyAuditAlertState.categories.join('、')}
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
      质检未通过，已按"仅警告"策略完成出片。建议在「合成/质检」查看 AutoQC 详情并视情况覆盖重跑修复。
    </Alert>
  ) : null

  const preflightMessage = diagnosticPreflight
    ? diagnosticPreflight.allowed
      ? `运行预检给出了 ${diagnosticPreflight.warnings.length} 条提示，建议在"诊断面板"查看路由与参数建议。`
      : `运行预检包含 ${diagnosticPreflight.errors.length} 条错误，当前配置存在阻断项，请先修正。`
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
