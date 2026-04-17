export type PendingRunningState = {
  queuedMessage: string | null
  snapshotShotEmptyText: string
  completionMessage: string
}

export function resolvePendingRunningState(input: {
  taskStatus: string | null | undefined
  taskQueue: string | null | undefined
}): PendingRunningState {
  const { taskStatus, taskQueue } = input

  return {
    queuedMessage:
      taskStatus === 'queued'
        ? `任务已入队排队中${taskQueue ? `（队列：${taskQueue}）` : ''}。若长期无进度，请确认 Celery worker 正在运行并监听该队列。`
        : null,
    snapshotShotEmptyText: '尚无可用分镜快照（可能仍在生成，或尚未落库）。',
    completionMessage: '任务执行中，完成后将自动展示分镜/首尾帧/视频产物。',
  }
}

export type PendingScriptApprovalState = {
  generationLabel: string
  showDirtyChip: boolean
  primaryAlertSeverity: 'success' | 'warning' | 'info'
  primaryAlertMessage: string
  showDirtyAlert: boolean
  fallbackError: string | null
  canLoadScript: boolean
  canSaveScript: boolean
  canApproveScript: boolean
  canRevokeScript: boolean
  canResume: boolean
  resumeButtonLabel: string
  runtimeError: string | null
  loading: boolean
  summaryText: string
}

export function resolvePendingScriptApprovalState(input: {
  scriptText: string
  scriptGenerationLabel: string
  scriptGenerationMode: string | null | undefined
  scriptGenerationError: string | null | undefined
  scriptRequiresReview: boolean
  scriptApproved: boolean
  scriptDirty: boolean
  currentRunId: string | null | undefined
  scriptLoading: boolean
  canResumeFromScript: boolean
  resumeLoading: boolean
  scriptError: string | null | undefined
  entitySummary: string
}): PendingScriptApprovalState {
  const {
    scriptText,
    scriptGenerationLabel,
    scriptGenerationMode,
    scriptGenerationError,
    scriptRequiresReview,
    scriptApproved,
    scriptDirty,
    currentRunId,
    scriptLoading,
    canResumeFromScript,
    resumeLoading,
    scriptError,
    entitySummary,
  } = input
  const hasScriptText = Boolean(scriptText.trim())
  const generationLabel = scriptGenerationLabel || ''
  const fallbackError = scriptGenerationMode === 'rule_fallback' && scriptGenerationError ? String(scriptGenerationError) : null
  const primaryAlertSeverity: PendingScriptApprovalState['primaryAlertSeverity'] = scriptRequiresReview
    ? scriptApproved
      ? 'success'
      : 'warning'
    : 'info'
  const primaryAlertMessage = scriptRequiresReview
    ? scriptApproved
      ? '剧本已通过：现在可以点击“继续生成”进入分镜与素材库阶段。'
      : '剧本待审核：请先加载/编辑剧本并点击“通过”，通过后再继续生成分镜与素材库。'
    : '当前配置无需剧本审核：可直接点击“继续生成”进入分镜与素材库阶段。'

  return {
    generationLabel,
    showDirtyChip: scriptDirty,
    primaryAlertSeverity,
    primaryAlertMessage,
    showDirtyAlert: scriptDirty,
    fallbackError,
    canLoadScript: Boolean(currentRunId) && !scriptLoading,
    canSaveScript: Boolean(currentRunId) && !scriptLoading && scriptDirty && hasScriptText,
    canApproveScript: Boolean(currentRunId) && !scriptLoading && !scriptDirty && hasScriptText,
    canRevokeScript: Boolean(currentRunId) && !scriptLoading && scriptApproved,
    canResume: canResumeFromScript,
    resumeButtonLabel: resumeLoading ? '继续生成中…' : '继续生成',
    runtimeError: scriptError || null,
    loading: scriptLoading,
    summaryText: `审核状态：${scriptRequiresReview ? (scriptApproved ? '已通过' : '待审核') : '无需审核'}${
      generationLabel ? `  生成：${generationLabel}` : ''
    }${entitySummary ? `  实体：${entitySummary}` : ''}`,
  }
}

export function truncatePendingPromptText(value: string, ellipsis = '...') {
  return value.length > 120 ? `${value.slice(0, 120)}${ellipsis}` : value
}

export type PendingVideoConfirmationJobState = {
  shotId: string
  title: string
  desc: string
  status: string
  statusLabel: string
  statusColor: 'success' | 'warning' | 'default'
  confirmed: boolean
  showConfirmedChip: boolean
  requiresBridge: boolean
  bridgeDependency: string
  hasPrompt: boolean
  headPrompt: string
  tailPrompt: string
  overridePrompt: string
  confirming: boolean
  actionDisabled: boolean
  actionLabel: string
  promptActionDisabled: boolean
}

export function resolvePendingVideoConfirmationJobState(input: {
  shotId: string
  desc: string
  status: string
  confirmed: boolean
  requiresBridge: boolean
  bridgeDependency: string
  hasPrompt: boolean
  headPrompt: string
  tailPrompt: string
  overridePrompt: string
  running: boolean
  videoJobConfirmingShotId: string | null | undefined
  hasShot: boolean
}): PendingVideoConfirmationJobState {
  const {
    shotId,
    desc,
    status,
    confirmed,
    requiresBridge,
    bridgeDependency,
    hasPrompt,
    headPrompt,
    tailPrompt,
    overridePrompt,
    running,
    videoJobConfirmingShotId,
    hasShot,
  } = input
  const normalizedStatus = String(status || '').trim().toLowerCase()
  const confirming = videoJobConfirmingShotId === shotId

  return {
    shotId,
    title: shotId || '(unknown)',
    desc,
    status: normalizedStatus,
    statusLabel:
      normalizedStatus === 'done' ? '已生成' : normalizedStatus === 'blocked' ? '依赖未就绪' : normalizedStatus === 'confirmed' ? '已确认' : '待确认',
    statusColor: normalizedStatus === 'done' ? 'success' : normalizedStatus === 'blocked' ? 'warning' : 'default',
    confirmed,
    showConfirmedChip: confirmed && normalizedStatus !== 'done',
    requiresBridge,
    bridgeDependency,
    hasPrompt,
    headPrompt,
    tailPrompt,
    overridePrompt,
    confirming,
    actionDisabled: !shotId || running || confirming || normalizedStatus === 'done',
    actionLabel:
      normalizedStatus === 'done'
        ? '已生成'
        : confirming
          ? '处理中…'
          : confirmed
            ? '开始生成'
            : requiresBridge
              ? '确认（桥接）'
              : '确认生成',
    promptActionDisabled: !hasShot,
  }
}

export type PendingPromptReviewShotState = {
  shotId: string
  title: string
  headPrompt: string
  tailPrompt: string
  overridePrompt: string
  hasOverridePrompt: boolean
  promptActionDisabled: boolean
}

export function resolvePendingPromptReviewShotState(input: {
  shotId: string
  title: string
  shotIndex: number | null | undefined
  headPrompt: string
  tailPrompt: string
  overridePrompt: string
}): PendingPromptReviewShotState {
  const { shotId, title, shotIndex, headPrompt, tailPrompt, overridePrompt } = input

  return {
    shotId,
    title: `#${shotIndex ?? 0} ${title}`,
    headPrompt,
    tailPrompt,
    overridePrompt,
    hasOverridePrompt: Boolean(overridePrompt),
    promptActionDisabled: false,
  }
}

export type PendingVideoConfirmationState = {
  introMessage: string
  runtimeError: string | null
  canRefresh: boolean
  refreshLabel: string
  hasJobs: boolean
  emptyMessage: string
}

export function resolvePendingVideoConfirmationState(input: {
  videoJobActionError: string | null | undefined
  persistedRunId: string | null | undefined
  runSnapshotLoading: boolean
  videoClipJobCount: number
}): PendingVideoConfirmationState {
  const { videoJobActionError, persistedRunId, runSnapshotLoading, videoClipJobCount } = input

  return {
    introMessage:
      '当前阶段启用“逐镜头确认生成”：点击卡片右侧按钮确认/触发生成；若镜头需要“上一镜头尾帧→本镜头首帧”桥接，依赖未就绪时会保持阻塞。',
    runtimeError: videoJobActionError || null,
    canRefresh: Boolean(persistedRunId) && !runSnapshotLoading,
    refreshLabel: runSnapshotLoading ? '刷新中…' : '刷新任务卡',
    hasJobs: videoClipJobCount > 0,
    emptyMessage: '未找到视频任务卡（video_clip_jobs）。可点击“刷新任务卡”或重试生成到 VIDEO 阶段。',
  }
}

export type PendingPromptReviewState = {
  alertSeverity: 'success' | 'warning'
  alertMessage: string
  canRefresh: boolean
  refreshLabel: string
  canApprove: boolean
  approveLabel: string
  canRevoke: boolean
  canResume: boolean
  resumeLabel: string
  runtimeError: string | null
  hasShots: boolean
  emptyText: string
  showListToggle: boolean
  listToggleLabel: string
}

export function resolvePendingPromptReviewState(input: {
  promptReviewApproved: boolean
  libraryApproved: boolean
  persistedRunId: string | null | undefined
  runSnapshotLoading: boolean
  currentRunId: string | null | undefined
  promptReviewLoading: boolean
  canResumeFromLibrary: boolean
  resumeLoading: boolean
  promptReviewError: string | null | undefined
  promptReviewShotCount: number
  snapshotShotCount: number
  promptReviewShowAll: boolean
}): PendingPromptReviewState {
  const {
    promptReviewApproved,
    libraryApproved,
    persistedRunId,
    runSnapshotLoading,
    currentRunId,
    promptReviewLoading,
    canResumeFromLibrary,
    resumeLoading,
    promptReviewError,
    promptReviewShotCount,
    snapshotShotCount,
    promptReviewShowAll,
  } = input

  return {
    alertSeverity: promptReviewApproved ? 'success' : 'warning',
    alertMessage: promptReviewApproved
      ? libraryApproved
        ? '提示词已确认、素材库已通过：可继续生成进入镜头阶段。'
        : '提示词已确认，但素材库仍待审核。'
      : '提示词待确认：请逐镜检查并修改，确认后再继续生成。',
    canRefresh: Boolean(persistedRunId) && !runSnapshotLoading,
    refreshLabel: runSnapshotLoading ? '刷新中…' : '刷新快照',
    canApprove: Boolean(currentRunId) && !promptReviewLoading,
    approveLabel: promptReviewLoading ? '确认中…' : '确认提示词',
    canRevoke: Boolean(currentRunId) && !promptReviewLoading && promptReviewApproved,
    canResume: canResumeFromLibrary,
    resumeLabel: resumeLoading ? '继续生成中…' : '继续生成',
    runtimeError: promptReviewError || null,
    hasShots: promptReviewShotCount > 0,
    emptyText: '暂无可用镜头提示词快照（可能仍在生成或尚未落库）。',
    showListToggle: snapshotShotCount > 12,
    listToggleLabel: promptReviewShowAll ? '收起列表' : `显示全部(${snapshotShotCount})`,
  }
}

export type PendingViewMode =
  | 'running'
  | 'script_approval'
  | 'video_confirmation'
  | 'prompt_review'
  | 'library_review'
  | 'library_ready'
  | 'empty'

export function resolvePendingViewMode(input: {
  running: boolean
  waitingScriptApproval: boolean
  waitingVideoConfirmation: boolean
  promptReviewRequiredSnapshot: boolean
  previewStep: number
  currentRunId: string | null | undefined
}): PendingViewMode {
  const { running, waitingScriptApproval, waitingVideoConfirmation, promptReviewRequiredSnapshot, previewStep, currentRunId } = input

  if (running) return 'running'
  if (waitingScriptApproval && previewStep === 0) return 'script_approval'
  if (waitingVideoConfirmation && previewStep === 3) return 'video_confirmation'
  if (promptReviewRequiredSnapshot && previewStep === 1) return 'prompt_review'
  if (currentRunId) {
    if (previewStep === 2) return 'library_review'
    return 'library_ready'
  }
  return 'empty'
}
