import type { ReactNode } from 'react'

import { Alert, Box, Button, Chip, LinearProgress, List, Stack, Typography } from '@mui/material'

import type {
  PendingPromptReviewState,
  PendingRunningState,
  PendingScriptApprovalState,
  PendingVideoConfirmationState,
} from './pendingViewState'

type PendingVideoConfirmationViewProps = {
  state: PendingVideoConfirmationState
  jobItems: ReactNode[]
  onRefresh: () => void
}

export function PendingVideoConfirmationView({
  state,
  jobItems,
  onRefresh,
}: PendingVideoConfirmationViewProps) {
  return (
    <Box>
      <Alert severity="info" sx={{ mb: 1 }}>
        {state.introMessage}
      </Alert>

      {state.runtimeError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {state.runtimeError}
        </Alert>
      )}

      <Stack direction="row" spacing={1} flexWrap="wrap" mb={1}>
        <Button size="small" variant="outlined" onClick={onRefresh} disabled={!state.canRefresh}>
          {state.refreshLabel}
        </Button>
      </Stack>

      {state.hasJobs ? (
        <List dense sx={{ bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
          {jobItems}
        </List>
      ) : (
        <Alert severity="warning">{state.emptyMessage}</Alert>
      )}
    </Box>
  )
}

type PendingRunningShellProps = {
  state: PendingRunningState
  stageHint?: ReactNode
  snapshotPreview?: ReactNode
  artifactsSummary?: ReactNode
  artifactDetails?: ReactNode
  debugPanel?: ReactNode
}

export function PendingRunningShell({
  state,
  stageHint,
  snapshotPreview,
  artifactsSummary,
  artifactDetails,
  debugPanel,
}: PendingRunningShellProps) {
  return (
    <Box>
      {state.queuedMessage && (
        <Alert severity="info" sx={{ mb: 1 }}>
          {state.queuedMessage}
        </Alert>
      )}
      {stageHint ?? null}
      {snapshotPreview ?? null}
      {artifactsSummary ?? null}
      {artifactDetails ?? null}
      <Typography variant="body2" color="text.secondary">
        {state.completionMessage}
      </Typography>
      {debugPanel ?? null}
    </Box>
  )
}

type PendingScriptApprovalShellProps = {
  state: PendingScriptApprovalState
  onLoadScript: () => void
  onSaveScript: () => void
  onApproveScript: () => void
  onRevokeScript: () => void
  onResume: () => void
  editor: ReactNode
  debugPanel?: ReactNode
}

export function PendingScriptApprovalShell({
  state,
  onLoadScript,
  onSaveScript,
  onApproveScript,
  onRevokeScript,
  onResume,
  editor,
  debugPanel,
}: PendingScriptApprovalShellProps) {
  const showStatusChips = Boolean(state.generationLabel || state.showDirtyChip)

  return (
    <Box>
      {showStatusChips && (
        <Stack direction="row" spacing={1} flexWrap="wrap" mb={1} alignItems="center">
          {state.generationLabel && <Chip label={`剧本生成: ${state.generationLabel}`} size="small" />}
          {state.showDirtyChip && <Chip label="未保存" size="small" color="warning" />}
        </Stack>
      )}

      <Alert severity={state.primaryAlertSeverity} sx={{ mb: 1 }}>
        {state.primaryAlertMessage}
      </Alert>

      {state.showDirtyAlert && (
        <Alert severity="info" sx={{ mb: 1 }}>
          剧本已修改但未保存：请先点击“保存”，再点击“通过”。
        </Alert>
      )}

      {state.fallbackError && (
        <Alert severity="info" sx={{ mb: 1 }}>
          LLM 调用失败，已回退为规则剧本：{state.fallbackError}
          <br />
          建议检查 `.env` 的 `DASHSCOPE_API_KEY` / `DASHSCOPE_API_BASE` 以及 `DREAMWEAVER_*_MODEL`，并重启后端与 Celery worker。
        </Alert>
      )}

      <Stack direction="row" spacing={1} flexWrap="wrap" mb={1}>
        <Button size="small" variant="contained" onClick={onLoadScript} disabled={!state.canLoadScript}>
          加载剧本
        </Button>
        <Button size="small" variant="outlined" onClick={onSaveScript} disabled={!state.canSaveScript}>
          保存
        </Button>
        <Button size="small" variant="contained" color="success" onClick={onApproveScript} disabled={!state.canApproveScript}>
          通过
        </Button>
        <Button size="small" variant="text" onClick={onRevokeScript} disabled={!state.canRevokeScript}>
          撤销通过
        </Button>
        <Button size="small" variant="contained" color="success" onClick={onResume} disabled={!state.canResume}>
          {state.resumeButtonLabel}
        </Button>
      </Stack>

      {state.runtimeError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {state.runtimeError}
        </Alert>
      )}
      {state.loading && <LinearProgress sx={{ mb: 1 }} />}

      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        {state.summaryText}
      </Typography>

      {editor}
      {debugPanel ?? null}
    </Box>
  )
}

type PendingPromptReviewViewProps = {
  state: PendingPromptReviewState
  shotItems: ReactNode[]
  revokeLabel: string
  onRefresh: () => void
  onApprove: () => void
  onRevoke: () => void
  onResume: () => void
  onToggleShowAll: () => void
}

export function PendingPromptReviewView({
  state,
  shotItems,
  revokeLabel,
  onRefresh,
  onApprove,
  onRevoke,
  onResume,
  onToggleShowAll,
}: PendingPromptReviewViewProps) {
  return (
    <Box>
      <Alert severity={state.alertSeverity} sx={{ mb: 1 }}>
        {state.alertMessage}
      </Alert>

      <Stack direction="row" spacing={1} flexWrap="wrap" mb={1} alignItems="center">
        <Button size="small" variant="outlined" onClick={onRefresh} disabled={!state.canRefresh}>
          {state.refreshLabel}
        </Button>
        <Button size="small" variant="contained" color="success" onClick={onApprove} disabled={!state.canApprove}>
          {state.approveLabel}
        </Button>
        <Button size="small" variant="text" onClick={onRevoke} disabled={!state.canRevoke}>
          {revokeLabel}
        </Button>
        <Button size="small" variant="contained" color="success" onClick={onResume} disabled={!state.canResume}>
          {state.resumeLabel}
        </Button>
      </Stack>

      {state.runtimeError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {state.runtimeError}
        </Alert>
      )}

      {state.hasShots ? (
        <List dense sx={{ bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
          {shotItems}
        </List>
      ) : (
        <Typography variant="body2" color="text.secondary">
          {state.emptyText}
        </Typography>
      )}

      {state.showListToggle && (
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
          <Button size="small" variant="text" onClick={onToggleShowAll}>
            {state.listToggleLabel}
          </Button>
        </Stack>
      )}
    </Box>
  )
}

type PendingLibraryNoticeProps = {
  severity: 'success' | 'warning' | 'info'
  message: string
  action?: ReactNode
}

export function PendingLibraryNotice({ severity, message, action }: PendingLibraryNoticeProps) {
  return (
    <Alert severity={severity} sx={{ mb: 1 }} action={action ?? undefined}>
      {message}
    </Alert>
  )
}

type PendingLibraryReviewShellProps = {
  notice: ReactNode
  controls: ReactNode
  runtimeStatus: ReactNode
  summarySection: ReactNode
  debugPanel?: ReactNode
}

export function PendingLibraryReviewShell({
  notice,
  controls,
  runtimeStatus,
  summarySection,
  debugPanel,
}: PendingLibraryReviewShellProps) {
  return (
    <Box>
      {notice}
      {controls}
      {runtimeStatus}
      {summarySection}
      {debugPanel ?? null}
    </Box>
  )
}

type PendingLibraryReadyShellProps = {
  notice: ReactNode
  snapshotPreview: ReactNode
}

export function PendingLibraryReadyShell({ notice, snapshotPreview }: PendingLibraryReadyShellProps) {
  return (
    <Box>
      {notice}
      {snapshotPreview}
    </Box>
  )
}

type PendingEmptyStateProps = {
  description: string
}

export function PendingEmptyState({ description }: PendingEmptyStateProps) {
  return (
    <Typography variant="body2" color="text.secondary">
      {description}
    </Typography>
  )
}
