import type { TFunction } from 'i18next'

export type PendingRunningState = {
  queuedMessage: string | null
  snapshotShotEmptyText: string
  completionMessage: string
}

export function resolvePendingRunningState(
  input: {
    taskStatus: string | null | undefined
    taskQueue: string | null | undefined
  },
  t?: TFunction,
): PendingRunningState {
  const { taskStatus, taskQueue } = input

  return {
    queuedMessage:
      taskStatus === 'queued'
        ? (t ? (taskQueue ? t('dreamweaverRun.pvQueuedMessageWithQueue', { queue: taskQueue }) : t('dreamweaverRun.pvQueuedMessage')) : '任务已入队排队中' + (taskQueue ? '（队列：' + taskQueue + '）' : '') + '。若长期无进度，请确认 Celery worker 正在运行并监听该队列。')
        : null,
    snapshotShotEmptyText: t ? t('dreamweaverRun.pvSnapshotShotEmptyText') : '尚无可用分镜快照（可能仍在生成，或尚未落库）。',
    completionMessage: t ? t('dreamweaverRun.pvCompletionMessage') : '任务执行中，完成后将自动展示分镜/首尾帧/视频产物。',
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

export function resolvePendingScriptApprovalState(
  input: {
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
  },
  t?: TFunction,
): PendingScriptApprovalState {
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
      ? (t ? t('dreamweaverRun.pvScriptApprovedContinue') : '剧本已通过：现在可以点击“继续生成”进入分镜与素材库阶段。')
      : (t ? t('dreamweaverRun.pvScriptPendingReview') : '剧本待审核：请先加载/编辑剧本并点击“通过”，通过后再继续生成分镜与素材库。')
    : (t ? t('dreamweaverRun.pvScriptNoReviewNeeded') : '当前配置无需剧本审核：可直接点击“继续生成”进入分镜与素材库阶段。')

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
    resumeButtonLabel: resumeLoading ? (t ? t('dreamweaverRun.pvResumeGenerating') : '继续生成中…') : (t ? t('dreamweaverRun.pvResume') : '继续生成'),
    runtimeError: scriptError || null,
    loading: scriptLoading,
    summaryText: (t ? t('dreamweaverRun.pvSummaryStatusPrefix') : '审核状态：') + (scriptRequiresReview ? (scriptApproved ? (t ? t('dreamweaverRun.libraryStatusApproved') : '已通过') : (t ? t('dreamweaverRun.libraryStatusPendingReview') : '待审核')) : (t ? t('dreamweaverRun.pvStatusNoReview') : '无需审核')) + (generationLabel ? (t ? t('dreamweaverRun.pvSummaryGenerationPart', { label: generationLabel }) : '  生成：' + generationLabel) : '') + (entitySummary ? (t ? t('dreamweaverRun.pvSummaryEntityPart', { label: entitySummary }) : '  实体：' + entitySummary) : ''),
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

export function resolvePendingVideoConfirmationJobState(
  input: {
  job: {
    shot_id?: string | null
    desc?: string | null
    status?: string | null
    confirmed?: boolean | null
    requires_bridge?: boolean | null
    depends_on_shot_id?: string | null
  }
  shot: {
    head_frame?: unknown
    tail_frame?: unknown
  } | null
  running: boolean
  videoJobConfirmingShotId: string | null | undefined
  getShotFramePrompt: (frame: unknown) => string
  getShotVideoPromptOverride: (shot: unknown) => string
  snapshotShotById: Map<string, unknown>
  },
  t?: TFunction,
): PendingVideoConfirmationJobState {
  const sid = String(input.job.shot_id || '').trim()
  const desc = String(input.job.desc || '').trim()
  const dep = String(input.job.depends_on_shot_id || '').trim()
  const headPrompt = input.shot ? input.getShotFramePrompt(input.shot.head_frame) : ''
  const tailPrompt = input.shot ? input.getShotFramePrompt(input.shot.tail_frame) : ''
  const overridePrompt = input.shot ? input.getShotVideoPromptOverride(input.shot) : ''

  return resolvePendingVideoConfirmationJobStateFromFields({
    shotId: sid,
    desc,
    status: String(input.job.status || '').trim(),
    confirmed: Boolean(input.job.confirmed),
    requiresBridge: Boolean(input.job.requires_bridge),
    bridgeDependency: dep,
    hasPrompt: Boolean(headPrompt || tailPrompt || overridePrompt),
    headPrompt,
    tailPrompt,
    overridePrompt,
    running: input.running,
    videoJobConfirmingShotId: input.videoJobConfirmingShotId,
    hasShot: Boolean(input.shot),
  }, t)
}

function resolvePendingVideoConfirmationJobStateFromFields(
  input: {
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
  },
  t?: TFunction,
): PendingVideoConfirmationJobState {
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
      normalizedStatus === 'done'
        ? (t ? t('dreamweaverRun.libraryStatusGenerated') : '已生成')
        : normalizedStatus === 'blocked'
          ? (t ? t('dreamweaverRun.pvStatusBlocked') : '依赖未就绪')
          : normalizedStatus === 'confirmed'
            ? (t ? t('dreamweaverRun.pendingConfirmed') : '已确认')
            : (t ? t('dreamweaverRun.pvStatusPendingConfirm') : '待确认'),
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
        ? (t ? t('dreamweaverRun.libraryStatusGenerated') : '已生成')
        : confirming
          ? (t ? t('common.processing') : '处理中…')
          : confirmed
            ? (t ? t('dreamweaverRun.configStartGenerating') : '开始生成')
            : requiresBridge
              ? (t ? t('dreamweaverRun.pvConfirmBridge') : '确认（桥接）')
              : (t ? t('dreamweaverRun.pvConfirmGenerate') : '确认生成'),
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

export function resolvePendingVideoConfirmationState(
  input: {
    videoJobActionError: string | null | undefined
    persistedRunId: string | null | undefined
    runSnapshotLoading: boolean
    videoClipJobCount: number
  },
  t?: TFunction,
): PendingVideoConfirmationState {
  const { videoJobActionError, persistedRunId, runSnapshotLoading, videoClipJobCount } = input

  return {
    introMessage:
      t ? t('dreamweaverRun.pvIntroMessage') : '当前阶段启用“逐镜头确认生成”：点击卡片右侧按钮确认/触发生成；若镜头需要“上一镜头尾帧→本镜头首帧”桥接，依赖未就绪时会保持阻塞。',
    runtimeError: videoJobActionError || null,
    canRefresh: Boolean(persistedRunId) && !runSnapshotLoading,
    refreshLabel: runSnapshotLoading ? (t ? t('dreamweaverRun.pvRefreshLoading') : '刷新中…') : (t ? t('dreamweaverRun.pvRefreshTaskCards') : '刷新任务卡'),
    hasJobs: videoClipJobCount > 0,
    emptyMessage: t ? t('dreamweaverRun.pvEmptyVideoJobs') : '未找到视频任务卡（video_clip_jobs）。可点击“刷新任务卡”或重试生成到 VIDEO 阶段。',
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

export function resolvePendingPromptReviewState(
  input: {
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
  },
  t?: TFunction,
): PendingPromptReviewState {
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
        ? (t ? t('dreamweaverRun.pvAlertApprovedLibraryApproved') : '提示词已确认、素材库已通过：可继续生成进入镜头阶段。')
        : (t ? t('dreamweaverRun.pvAlertApprovedLibraryPending') : '提示词已确认，但素材库仍待审核。')
      : (t ? t('dreamweaverRun.pvAlertPromptPending') : '提示词待确认：请逐镜检查并修改，确认后再继续生成。'),
    canRefresh: Boolean(persistedRunId) && !runSnapshotLoading,
    refreshLabel: runSnapshotLoading ? (t ? t('dreamweaverRun.pvRefreshLoading') : '刷新中…') : (t ? t('dreamweaverRun.pvRefreshSnapshot') : '刷新快照'),
    canApprove: Boolean(currentRunId) && !promptReviewLoading,
    approveLabel: promptReviewLoading ? (t ? t('dreamweaverRun.pvApproveLoading') : '确认中…') : (t ? t('dreamweaverRun.pvApprovePrompts') : '确认提示词'),
    canRevoke: Boolean(currentRunId) && !promptReviewLoading && promptReviewApproved,
    canResume: canResumeFromLibrary,
    resumeLabel: resumeLoading ? (t ? t('dreamweaverRun.pvResumeGenerating') : '继续生成中…') : (t ? t('dreamweaverRun.pvResume') : '继续生成'),
    runtimeError: promptReviewError || null,
    hasShots: promptReviewShotCount > 0,
    emptyText: t ? t('dreamweaverRun.pvEmptyPromptShots') : '暂无可用镜头提示词快照（可能仍在生成或尚未落库）。',
    showListToggle: snapshotShotCount > 12,
    listToggleLabel: promptReviewShowAll ? (t ? t('dreamweaverRun.pvCollapseList') : '收起列表') : (t ? t('dreamweaverRun.pvShowAllCount', { count: snapshotShotCount }) : '显示全部(' + snapshotShotCount + ')'),
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
