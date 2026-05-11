import type { ReactNode } from 'react'

import BugReportIcon from '@mui/icons-material/BugReport'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { Alert, Box, Button, Chip, LinearProgress, List, Stack, TextField, Typography } from '@mui/material'

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

type PendingRunningStageHintProps = {
  message: string
}

export function PendingRunningStageHint({
  message,
}: PendingRunningStageHintProps) {
  return (
    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
      {message}
    </Typography>
  )
}

type PendingRunningArtifactsSummaryProps = {
  chips: Array<{
    key: string
    label: string
    value: string | number
    variant?: 'filled' | 'outlined'
  }>
  onCopyDebug: () => void
  onOpenDiagnostic: () => void
  diagnosticDisabled: boolean
}

export function PendingRunningArtifactsSummary({
  chips,
  onCopyDebug,
  onOpenDiagnostic,
  diagnosticDisabled,
}: PendingRunningArtifactsSummaryProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" mb={1} alignItems="center">
      {chips.map((item) => (
        <Chip key={item.key} label={`${item.label}: ${item.value}`} size="small" variant={item.variant ?? 'filled'} />
      ))}
      <Button size="small" variant="text" startIcon={<ContentCopyIcon fontSize="small" />} onClick={onCopyDebug}>
        复制调试信息
      </Button>
      <Button
        size="small"
        variant="text"
        startIcon={<BugReportIcon fontSize="small" />}
        onClick={onOpenDiagnostic}
        disabled={diagnosticDisabled}
      >
        诊断面板
      </Button>
    </Stack>
  )
}

type PendingArtifactDetailsProps = {
  lines: Array<{
    key: string
    label?: string | null
    content: string
  }>
}

export function PendingArtifactDetails({ lines }: PendingArtifactDetailsProps) {
  return (
    <>
      {lines.map((line) => (
        <Typography key={line.key} variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
          {line.label ? `${line.label}: ${line.content}` : line.content}
        </Typography>
      ))}
    </>
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

type PendingScriptApprovalEditorProps = {
  value: string
  onChange: (value: string) => void
  disabled: boolean
}

export function PendingScriptApprovalEditor({
  value,
  onChange,
  disabled,
}: PendingScriptApprovalEditorProps) {
  return (
    <TextField
      label="剧本（可编辑）"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      fullWidth
      multiline
      minRows={10}
      maxRows={22}
      disabled={disabled}
      sx={{ bgcolor: '#fff' }}
    />
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

type PendingLibraryControlsProps = {
  onLoadLibrary: () => void
  loadDisabled: boolean
  onApproveAll: () => void
  approveDisabled: boolean
  onResume: () => void
  resumeDisabled: boolean
  resumeLoading: boolean
}

export function PendingLibraryControls({
  onLoadLibrary,
  loadDisabled,
  onApproveAll,
  approveDisabled,
  onResume,
  resumeDisabled,
  resumeLoading,
}: PendingLibraryControlsProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" mb={1}>
      <Button size="small" variant="contained" onClick={onLoadLibrary} disabled={loadDisabled}>
        加载素材库
      </Button>
      <Button size="small" variant="outlined" onClick={onApproveAll} disabled={approveDisabled}>
        全部通过
      </Button>
      <Button size="small" variant="contained" color="success" onClick={onResume} disabled={resumeDisabled}>
        {resumeLoading ? '继续生成中…' : '继续生成'}
      </Button>
    </Stack>
  )
}

type PendingLibraryReviewStatusProps = {
  missingCount: number
  unapprovedCount: number
}

export function PendingLibraryReviewStatus({
  missingCount,
  unapprovedCount,
}: PendingLibraryReviewStatusProps) {
  return (
    <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
      审核状态：缺失 {missingCount}，未通过 {unapprovedCount}
    </Typography>
  )
}

type PendingLibraryRuntimeStatusProps = {
  libraryError: string | null
  libraryLoading: boolean
  missingCount: number
  unapprovedCount: number
  hasReview: boolean
}

export function PendingLibraryRuntimeStatus({
  libraryError,
  libraryLoading,
  missingCount,
  unapprovedCount,
  hasReview,
}: PendingLibraryRuntimeStatusProps) {
  return (
    <>
      {libraryError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {libraryError}
        </Alert>
      )}
      {libraryLoading && <LinearProgress sx={{ mb: 1 }} />}
      {hasReview && (
        <PendingLibraryReviewStatus missingCount={missingCount} unapprovedCount={unapprovedCount} />
      )}
    </>
  )
}

type PendingLibraryReadyActionsProps = {
  onViewLibrary: () => void
  showPromptReviewAction: boolean
  onViewPromptReview: () => void
  onResume: () => void
  resumeDisabled: boolean
  resumeLoading: boolean
}

export function PendingLibraryReadyActions({
  onViewLibrary,
  showPromptReviewAction,
  onViewPromptReview,
  onResume,
  resumeDisabled,
  resumeLoading,
}: PendingLibraryReadyActionsProps) {
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <Button size="small" variant="text" onClick={onViewLibrary}>
        查看素材库
      </Button>
      {showPromptReviewAction && (
        <Button size="small" variant="text" onClick={onViewPromptReview}>
          查看提示词
        </Button>
      )}
      <Button size="small" variant="contained" color="success" onClick={onResume} disabled={resumeDisabled}>
        {resumeLoading ? '继续生成中…' : '继续生成'}
      </Button>
    </Stack>
  )
}

type PendingLibrarySummarySectionProps = {
  emptyText: string
  summaryChips?: ReactNode
  groups?: ReactNode
}

export function PendingLibrarySummarySection({
  emptyText,
  summaryChips,
  groups,
}: PendingLibrarySummarySectionProps) {
  if (!groups) {
    return (
      <Typography variant="body2" color="text.secondary">
        {emptyText}
      </Typography>
    )
  }

  return (
    <Box>
      {summaryChips ?? null}
      {groups}
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
