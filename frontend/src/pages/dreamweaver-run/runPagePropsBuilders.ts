import type { TFunction } from 'i18next'

import { asObject } from './runPageDataTransforms'
import { formatPath, formatPaths } from './runPageFormatUtils'
import {
  VideoDiagnostics,
  computeVideoDiagnostics,
  TelemetryStageEntry,
  TelemetryChipItem,
  buildTelemetryStageEntries,
  buildTelemetryReworkChips,
  buildTelemetryCounterChips,
} from './runPageDiagnosticHelpers'

export interface VideoSummarySectionProps {
  mergedVideo: string | null | undefined
  viaSummary: string
  fallbackCount: number
  clipCount: number
}

export function buildVideoSummarySectionProps(
  mergedVideo: unknown,
  diagnostics: VideoDiagnostics,
): VideoSummarySectionProps {
  return {
    mergedVideo: typeof mergedVideo === 'string' ? mergedVideo : null,
    viaSummary: diagnostics.viaSummary,
    fallbackCount: diagnostics.fallbackCount,
    clipCount: diagnostics.clipCount,
  }
}

export interface ResultDerivedState {
  videoDiagnostics: VideoDiagnostics
  planText: string
  videoClipPaths: string[]
  candidateFrameUris: string[]
  keyframePaths: string[]
  midframePaths: string[]
  chapterCount: number
  keyframeCount: number
  midframeCount: number
  videoClipCount: number
}

export function extractResultPlanText(result: Record<string, unknown> | null): string {
  const plan = result?.plan
  if (!plan || typeof plan !== 'object') return ''
  const text = (plan as { text?: unknown }).text
  return typeof text === 'string' ? text : ''
}

export function computeResultDerivedState(result: Record<string, unknown> | null): ResultDerivedState {
  const videoClips = Array.isArray(result?.video_clips) ? result.video_clips : []
  const keyframes = Array.isArray(result?.keyframes) ? result.keyframes : []
  const midframes = Array.isArray(result?.midframes) ? result.midframes : []
  return {
    videoDiagnostics: computeVideoDiagnostics(videoClips),
    planText: extractResultPlanText(result),
    videoClipPaths: videoClips.map((clip: unknown) => {
      const meta = asObject(clip)
      return typeof meta?.path === 'string' ? meta.path : ''
    }).filter(Boolean),
    candidateFrameUris: [],
    keyframePaths: [],
    midframePaths: [],
    chapterCount: typeof result?.source_chapter_count === 'number' ? result.source_chapter_count : 0,
    keyframeCount: keyframes.length,
    midframeCount: midframes.length,
    videoClipCount: videoClips.length,
  }
}

export interface ArtifactChipItem {
  key: string
  label: string
  value: string | number
  variant?: 'outlined'
}

export interface ArtifactLineItem {
  key: string
  label: string | null
  content: string
}

export interface TaskArtifactsLike {
  storyboard_count?: number | null
  keyframes_count?: number | null
  midframes_count?: number | null
  video_clips_count?: number | null
  last_keyframe_path?: unknown
  last_midframe_path?: unknown
  last_video_clip_path?: unknown
  keyframes_tail_paths?: unknown
  midframes_tail_paths?: unknown
  video_clips_tail_paths?: unknown
  rework_reason?: unknown
  stage_artifacts?: Record<string, unknown> | null
}

export function buildArtifactChips(artifacts: TaskArtifactsLike | null | undefined): ArtifactChipItem[] {
  return [
    { key: 'sb', label: 'SB', value: artifacts?.storyboard_count },
    { key: 'kf', label: 'KF', value: artifacts?.keyframes_count },
    { key: 'mf', label: 'MF', value: artifacts?.midframes_count },
    { key: 'vc', label: 'VC', value: artifacts?.video_clips_count },
    { key: 'cam-tree', label: 'CamTree', value: artifacts?.stage_artifacts?.camera_tree_mode, variant: 'outlined' as const },
    { key: 'cam', label: 'Cam', value: artifacts?.stage_artifacts?.camera_count },
    { key: 'cam-state', label: 'CamState', value: artifacts?.stage_artifacts?.camera_states_count },
    { key: 'cam-scene', label: 'CamScene', value: artifacts?.stage_artifacts?.camera_scenes_count },
  ].flatMap((item) => {
    const v = item.value
    if (v == null || v === '') return []
    const typed = typeof v === 'string' || typeof v === 'number' ? v : String(v)
    return [{ ...item, value: typed }]
  })
}

export function buildArtifactLines(artifacts: TaskArtifactsLike | null | undefined): ArtifactLineItem[] {
  return [
    {
      key: 'last',
      label: 'Last',
      content: [
        formatPath(artifacts?.last_keyframe_path) ? `KF ${formatPath(artifacts?.last_keyframe_path)}` : '',
        formatPath(artifacts?.last_midframe_path) ? `MF ${formatPath(artifacts?.last_midframe_path)}` : '',
        formatPath(artifacts?.last_video_clip_path) ? `VC ${formatPath(artifacts?.last_video_clip_path)}` : '',
      ]
        .filter(Boolean)
        .join('  '),
    },
    {
      key: 'tail',
      label: null,
      content: [
        formatPaths(artifacts?.keyframes_tail_paths) ? `KF: ${formatPaths(artifacts?.keyframes_tail_paths)}` : '',
        formatPaths(artifacts?.midframes_tail_paths) ? `MF: ${formatPaths(artifacts?.midframes_tail_paths)}` : '',
        formatPaths(artifacts?.video_clips_tail_paths) ? `VC: ${formatPaths(artifacts?.video_clips_tail_paths)}` : '',
      ]
        .filter(Boolean)
        .join('  '),
    },
    {
      key: 'rework',
      label: 'Rework',
      content: artifacts?.rework_reason ? JSON.stringify(artifacts.rework_reason) : '',
    },
    {
      key: 'stage-artifacts',
      label: 'Stage artifacts',
      content: artifacts?.stage_artifacts ? JSON.stringify(artifacts.stage_artifacts) : '',
    },
  ].filter((item) => item.content)
}

export interface ArtifactDerivedState {
  chips: ArtifactChipItem[]
  lines: ArtifactLineItem[]
}

export function buildArtifactDerivedState(artifacts: TaskArtifactsLike | null | undefined): ArtifactDerivedState {
  return {
    chips: buildArtifactChips(artifacts),
    lines: buildArtifactLines(artifacts),
  }
}

export interface StrategyFieldItem {
  key: string
  title: string
  checked: boolean
  onChange: (value: boolean) => void
  enabledLabel: string
  disabledLabel: string
  description: string
}

export interface StrategyFieldsParams {
  highQuality: boolean
  setHighQuality: (v: boolean) => void
  smartTuning: boolean
  setSmartTuning: (v: boolean) => void
  videoRequireConfirmation: boolean
  setVideoRequireConfirmation: (v: boolean) => void
  promptReviewRequired: boolean
  setPromptReviewRequired: (v: boolean) => void
  qcAllowFail: boolean
  setQcAllowFail: (v: boolean) => void
}

export interface ModelFieldProps {
  imageModelValue: string
  onImageModelChange: (value: string) => void
  imageModelOptions: Array<{ value: string; label: string }>
  videoModelValue: string
  onVideoModelChange: (value: string) => void
  videoModelOptions: Array<{ value: string; label: string }>
  videoEditModelValue: string
  onVideoEditModelChange: (value: string) => void
  videoEditModelOptions: Array<{ value: string; label: string }>
  visionModelValue: string
  onVisionModelChange: (value: string) => void
  visionModelOptions: Array<{ value: string; label: string }>
}

export function buildModelFieldProps(params: {
  imageModel: string
  setImageModel: (v: string) => void
  imageModelOptions: Array<{ value: string; label: string }>
  videoModel: string
  setVideoModel: (v: string) => void
  videoModelOptions: Array<{ value: string; label: string }>
  videoEditModel: string
  setVideoEditModel: (v: string) => void
  videoEditModelOptions: Array<{ value: string; label: string }>
  visionModel: string
  setVisionModel: (v: string) => void
  visionModelOptions: Array<{ value: string; label: string }>
}): ModelFieldProps {
  return {
    imageModelValue: params.imageModel,
    onImageModelChange: params.setImageModel,
    imageModelOptions: params.imageModelOptions,
    videoModelValue: params.videoModel,
    onVideoModelChange: params.setVideoModel,
    videoModelOptions: params.videoModelOptions,
    videoEditModelValue: params.videoEditModel,
    onVideoEditModelChange: params.setVideoEditModel,
    videoEditModelOptions: params.videoEditModelOptions,
    visionModelValue: params.visionModel,
    onVisionModelChange: params.setVisionModel,
    visionModelOptions: params.visionModelOptions,
  }
}

export interface VisualFieldProps {
  stylePresetValue: string
  onStylePresetChange: (value: string) => void
  stylePresetOptions: Array<{ value: string; label: string }>
  imageRatioValue: string
  onImageRatioChange: (value: string) => void
  imageRatioOptions: Array<{ value: string; label: string }>
  imageResolutionValue: string
  onImageResolutionChange: (value: string) => void
  imageResolutionOptions: Array<{ value: string; label: string }>
}

export function buildVisualFieldProps(params: {
  stylePreset: string
  setStylePreset: (v: string) => void
  stylePresetOptions: Array<{ value: string; label: string }>
  imageRatio: string
  setImageRatio: (v: string) => void
  imageRatioOptions: Array<{ value: string; label: string }>
  imageResolution: string
  setImageResolution: (v: string) => void
  imageResolutionOptions: Array<{ value: string; label: string }>
}): VisualFieldProps {
  return {
    stylePresetValue: params.stylePreset,
    onStylePresetChange: params.setStylePreset,
    stylePresetOptions: params.stylePresetOptions,
    imageRatioValue: params.imageRatio,
    onImageRatioChange: params.setImageRatio,
    imageRatioOptions: params.imageRatioOptions,
    imageResolutionValue: params.imageResolution,
    onImageResolutionChange: params.setImageResolution,
    imageResolutionOptions: params.imageResolutionOptions,
  }
}

export interface CameraAccordionProps {
  generationAccordion: React.ReactNode
  cameraTreeAccordion: React.ReactNode
  cameraStatesAccordion: React.ReactNode
  cameraScenesAccordion: React.ReactNode
}

export function buildCameraAccordionProps(
  data: { generation: unknown; cameraTree: unknown; cameraStates: unknown; cameraScenes: unknown },
  renderAccordion: (title: string, value: unknown) => React.ReactNode,
): CameraAccordionProps {
  return {
    generationAccordion: renderAccordion('camera_tree_generation', data.generation),
    cameraTreeAccordion: renderAccordion('camera_tree', data.cameraTree),
    cameraStatesAccordion: renderAccordion('camera_states', data.cameraStates),
    cameraScenesAccordion: renderAccordion('camera_scenes', data.cameraScenes),
  }
}

export interface ToggleFieldProps {
  enableVideoEdit: boolean
  onEnableVideoEditChange: (value: boolean) => void
  enableVisionReview: boolean
  onEnableVisionReviewChange: (value: boolean) => void
  enableSafetyAudit: boolean
  onEnableSafetyAuditChange: (value: boolean) => void
  safetyFailPolicyValue: string
  onSafetyFailPolicyChange: (value: string) => void
  safetyFailPolicyOptions: Array<{ value: string; label: string }>
}

export function buildToggleFieldProps(params: {
  enableVideoEdit: boolean
  setEnableVideoEdit: (v: boolean) => void
  enableVisionReview: boolean
  setEnableVisionReview: (v: boolean) => void
  enableSafetyAudit: boolean
  setEnableSafetyAudit: (v: boolean) => void
  safetyFailPolicy: string
  setSafetyFailPolicy: (v: 'warn' | 'block') => void
  safetyFailPolicyOptions: Array<{ value: string; label: string }>
}): ToggleFieldProps {
  return {
    enableVideoEdit: params.enableVideoEdit,
    onEnableVideoEditChange: params.setEnableVideoEdit,
    enableVisionReview: params.enableVisionReview,
    onEnableVisionReviewChange: params.setEnableVisionReview,
    enableSafetyAudit: params.enableSafetyAudit,
    onEnableSafetyAuditChange: params.setEnableSafetyAudit,
    safetyFailPolicyValue: params.safetyFailPolicy,
    onSafetyFailPolicyChange: (value: string) => params.setSafetyFailPolicy(value === 'block' ? 'block' : 'warn'),
    safetyFailPolicyOptions: params.safetyFailPolicyOptions,
  }
}

export function buildStrategyFields(params: StrategyFieldsParams, t?: TFunction): StrategyFieldItem[] {
  return [
    {
      key: 'quality-mode',
      title: t ? t('dreamweaverRun.strategyTitleQuality') : '成本 / 质量',
      checked: params.highQuality,
      onChange: params.setHighQuality,
      enabledLabel: t ? t('dreamweaverRun.strategyEnabledHighQuality') : '最高质量',
      disabledLabel: t ? t('dreamweaverRun.strategyDisabledLowCost') : '低成本',
      description: params.highQuality
        ? (t ? t('dreamweaverRun.strategyDescQuality') : '多候选 + 语义评选 + 图片编辑 + 语义质检')
        : (t ? t('dreamweaverRun.strategyDescCost') : '单候选 + 关闭编辑/语义质检'),
    },
    {
      key: 'smart-tuning',
      title: t ? t('dreamweaverRun.strategyTitleSmartTuning') : '智能调参',
      checked: params.smartTuning,
      onChange: params.setSmartTuning,
      enabledLabel: t ? t('dreamweaverRun.strategyTitleSmartTuning') : '智能调参',
      disabledLabel: t ? t('dreamweaverRun.strategyDisabledManualTuning') : '手动调参',
      description: t ? t('dreamweaverRun.strategyDescSmartTuning') : '质量优先：按镜头规模自动调候选数与语义质检预算。',
    },
    {
      key: 'video-confirmation',
      title: t ? t('dreamweaverRun.strategyTitleVideoConfirmation') : '视频逐段确认',
      checked: params.videoRequireConfirmation,
      onChange: params.setVideoRequireConfirmation,
      enabledLabel: t ? t('dreamweaverRun.strategyEnabledConfirmPerShot') : '逐段确认',
      disabledLabel: t ? t('dreamweaverRun.strategyDisabledAuto') : '自动生成',
      description: t ? t('dreamweaverRun.strategyDescVideoConfirmation') : 'VIDEO 阶段先生成任务卡，确认后按镜头生成视频；桥接依赖会自动阻塞提示。',
    },
    {
      key: 'prompt-review',
      title: t ? t('dreamweaverRun.strategyTitlePromptReview') : '提示词审核',
      checked: params.promptReviewRequired,
      onChange: params.setPromptReviewRequired,
      enabledLabel: t ? t('dreamweaverRun.strategyEnabledReviewFirst') : '先审提示词',
      disabledLabel: t ? t('dreamweaverRun.strategyDisabledDirectGenerate') : '直接生成',
      description: t ? t('dreamweaverRun.strategyDescPromptReview') : '生成关键帧/视频前先停在提示词审核，可修改后再提交生成任务。',
    },
    {
      key: 'qc-allow-fail',
      title: t ? t('dreamweaverRun.strategyTitleQcFail') : '质检失败处理',
      checked: params.qcAllowFail,
      onChange: params.setQcAllowFail,
      enabledLabel: t ? t('dreamweaverRun.strategyEnabledWarnOnly') : '仅警告',
      disabledLabel: t ? t('dreamweaverRun.strategyDisabledStrictBlock') : '严格拦截',
      description: t ? t('dreamweaverRun.strategyDescQcFail') : 'AutoQC 失败可仅警告放行；文件校验（audit）仍会拦截。',
    },
  ]
}

export interface SmartDispatchSummaryProps {
  stage: string | null
  strategy: string | null
  intentModality: string | null
  intentConfidence: number | null
  parseErrorCount: number | null
  selectedModel: string | null
  resolvedModel: string | null
  fallbackCount: number | null
  candidateCount: number | null
  attemptedCount: number | null
  promptChanged: boolean | null
  timedOut: boolean | null
  phaseCount: number | null
  phaseStages: string[]
}

export function resolveSmartDispatchSummaryProps(
  summary: { stage?: string | null; strategy?: string | null; intentModality?: string | null; intentConfidence?: number | null; parseErrorCount?: number; selectedModel?: string | null; resolvedModel?: string | null; fallbackCount?: number; candidateCount?: number; attemptedCount?: number; promptChanged?: boolean | null; timedOut?: boolean | null; phaseCount?: number; phaseStages?: string[] } | null | undefined,
): SmartDispatchSummaryProps {
  if (!summary) {
    return {
      stage: null, strategy: null, intentModality: null, intentConfidence: null,
      parseErrorCount: null, selectedModel: null, resolvedModel: null, fallbackCount: null,
      candidateCount: null, attemptedCount: null, promptChanged: null, timedOut: null,
      phaseCount: null, phaseStages: [],
    }
  }
  return {
    stage: summary.stage ?? null,
    strategy: summary.strategy ?? null,
    intentModality: summary.intentModality ?? null,
    intentConfidence: summary.intentConfidence ?? null,
    parseErrorCount: summary.parseErrorCount ?? null,
    selectedModel: summary.selectedModel ?? null,
    resolvedModel: summary.resolvedModel ?? null,
    fallbackCount: summary.fallbackCount ?? null,
    candidateCount: summary.candidateCount ?? null,
    attemptedCount: summary.attemptedCount ?? null,
    promptChanged: summary.promptChanged ?? null,
    timedOut: summary.timedOut ?? null,
    phaseCount: summary.phaseCount ?? null,
    phaseStages: summary.phaseStages ?? [],
  }
}

export interface ProviderTraceSummaryProps {
  totalShots: number | null
  recommendedKling: number | null
  appliedKling: number | null
  shadowed: number | null
}

export function resolveProviderTraceSummaryProps(
  summary: { totalShots?: number | null; recommendedKling?: number | null; appliedKling?: number | null; shadowed?: number | null } | null | undefined,
): ProviderTraceSummaryProps {
  return {
    totalShots: summary?.totalShots ?? null,
    recommendedKling: summary?.recommendedKling ?? null,
    appliedKling: summary?.appliedKling ?? null,
    shadowed: summary?.shadowed ?? null,
  }
}

export function resolveTelemetrySectionProps(params: {
  summary: {
    totalS: unknown
    terminalState: unknown
    reworkCount: unknown
    stageEntries: TelemetryStageEntry[]
    reworkByType: Record<string, unknown> | null | undefined
  }
  abVariant: string | undefined
  counters: Array<{ name: string; value: number | string }>
}): {
  totalSeconds: number | null
  terminalState: string | null
  reworkCount: number | null
  abVariant: string | null
  stageEntries: TelemetryChipItem[]
  reworkChips: TelemetryChipItem[]
  counterChips: TelemetryChipItem[]
} {
  const abVariantTrimmed = typeof params.abVariant === 'string' ? params.abVariant.trim() : ''
  return {
    totalSeconds: typeof params.summary.totalS === 'number' ? params.summary.totalS : null,
    terminalState: (params.summary.terminalState as string) || null,
    reworkCount: typeof params.summary.reworkCount === 'number' ? params.summary.reworkCount : null,
    abVariant: abVariantTrimmed || null,
    stageEntries: buildTelemetryStageEntries(params.summary.stageEntries),
    reworkChips: buildTelemetryReworkChips(params.summary.reworkByType),
    counterChips: buildTelemetryCounterChips(params.counters),
  }
}

export interface WorkbenchActionItem {
  key: string
  label: string
  onClick: () => void
  startIcon?: React.ReactNode
  disabled?: boolean
}

export function buildWorkbenchActionItems(params: {
  copyDebugInfo: () => void
  openDiagnosticDialog: () => void
  currentRunId: string | null
  openHistoryDialog: (projectId: number) => void
  selectedProjectId: number | null
  openConfigDialog: () => void
  copyDebugIcon: React.ReactNode
  diagnosticsIcon: React.ReactNode
  historyIcon: React.ReactNode
}, t?: TFunction): WorkbenchActionItem[] {
  return [
    {
      key: 'copy-debug',
      label: t ? t('dreamweaverRun.workbenchCopyDebug') : '复制调试信息',
      onClick: params.copyDebugInfo,
      startIcon: params.copyDebugIcon,
    },
    {
      key: 'diagnostics',
      label: t ? t('dreamweaverRun.workbenchDiagnostics') : '诊断面板',
      onClick: params.openDiagnosticDialog,
      disabled: !params.currentRunId,
      startIcon: params.diagnosticsIcon,
    },
    {
      key: 'history',
      label: t ? t('dreamweaverRun.workbenchHistory') : '历史记录',
      onClick: () => { if (params.selectedProjectId) params.openHistoryDialog(params.selectedProjectId) },
      disabled: !params.selectedProjectId,
      startIcon: params.historyIcon,
    },
    {
      key: 'config',
      label: t ? t('dreamweaverRun.workbenchConfig') : '配置',
      onClick: params.openConfigDialog,
    },
  ]
}

export function resolveRegenerateDialogLabels(params: {
  imageEditActive: boolean
  imageEditAutoCleared: boolean
  submitting: boolean
}, t?: TFunction): {
  modeHint: string
  promptPlaceholder: string | undefined
  submitLabel: string
} {
  return {
    modeHint: params.imageEditActive
      ? (t ? t('dreamweaverRun.regenModeHintImageEdit') : '图像编辑模式：将基于参考图生成，提交后状态变为"待审核"。')
      : (t ? t('dreamweaverRun.regenModeHintTextEdit') : '可在下方编辑提示词并重生成素材，生成后将变为待审核状态。'),
    promptPlaceholder: params.imageEditActive && params.imageEditAutoCleared
      ? (t ? t('dreamweaverRun.regenPlaceholderExample') : '示例：保持角色身份锚点不变，改为侧面全身，左肩数据接口更亮，背景保持纯灰色。')
      : undefined,
    submitLabel: params.submitting
      ? (t ? t('dreamweaverRun.regenSubmitGenerating') : '生成中...')
      : params.imageEditActive
        ? (t ? t('dreamweaverRun.regenSubmitImageEdit') : '开始生成（图像编辑）')
        : (t ? t('dreamweaverRun.regenSubmitPrompt') : '开始生成（提示词）'),
  }
}

export function resolveRegenerateSubmitDisabled(params: {
  submitting: boolean
  suggesting: boolean
  hasRole: boolean
  forceImageEdit: boolean
  hasImageBase: boolean
}): boolean {
  return params.submitting || params.suggesting || !params.hasRole || (params.forceImageEdit && !params.hasImageBase)
}

export interface SnapshotStatusProps {
  label: string
  onRefresh: () => void
  refreshDisabled: boolean
  refreshLoading: boolean
  loaded: boolean
  loading: boolean
  errorMessage: string | null
  chips?: Array<{ key: string; label: string }>
}

export function buildSnapshotStatusProps(params: {
  persistedRunId: string | null
  runSnapshotLoading: boolean
  runSnapshot: { run_id?: string } | null
  runSnapshotError: string | null
  snapshotShots: unknown[]
  snapshotAssetCount: number
  loadRunSnapshot: () => void
  includeChips: boolean
}, t?: TFunction): SnapshotStatusProps {
  return {
    label: t ? t('dreamweaverRun.snapshotLoad') : '加载运行快照',
    onRefresh: params.loadRunSnapshot,
    refreshDisabled: !params.persistedRunId || params.runSnapshotLoading,
    refreshLoading: params.runSnapshotLoading,
    loaded: Boolean(params.runSnapshot && params.runSnapshot.run_id === params.persistedRunId),
    loading: params.runSnapshotLoading,
    errorMessage: params.runSnapshotError,
    ...(params.includeChips
      ? {
          chips: [
            ...(params.snapshotShots.length > 0 ? [{ key: 'shots', label: t ? t('dreamweaverRun.snapshotShotsChip', { count: params.snapshotShots.length }) : `镜头: ${params.snapshotShots.length}` }] : []),
            ...(params.snapshotAssetCount > 0 ? [{ key: 'assets', label: t ? t('dreamweaverRun.snapshotAssetsChip', { count: params.snapshotAssetCount }) : `资产: ${params.snapshotAssetCount}` }] : []),
          ],
        }
      : {}),
  }
}

export function buildSnapshotAssetPreviewSectionProps(params: {
  previewStep: number
  runSnapshotLoading: boolean
  snapshotShotsLength: number
  snapshotAssetCount: number
  snapshotAssetSummary: {
    keyframes: string[]
    midframes: string[]
    videoClips: Array<{ path: string; meta: Record<string, unknown> }>
  }
}, t?: TFunction): {
  visible: boolean
  shotCount: number
  assetCount: number
  keyframeCount: number
  midframeCount: number
  videoClipCount: number
  tailVideoClipPaths: string[]
  pathSummary: string | null
} {
  const tailVideoClipPaths = params.snapshotAssetSummary.videoClips.slice(-3).map((v) => v.path)
  const keyframePaths = params.snapshotAssetSummary.keyframes.slice(-3)
  const midframePaths = params.snapshotAssetSummary.midframes.slice(-3)
  return {
    visible: params.previewStep === 3 && !params.runSnapshotLoading && params.snapshotShotsLength > 0,
    shotCount: params.snapshotShotsLength,
    assetCount: params.snapshotAssetCount,
    keyframeCount: params.snapshotAssetSummary.keyframes.length,
    midframeCount: params.snapshotAssetSummary.midframes.length,
    videoClipCount: params.snapshotAssetSummary.videoClips.length,
    tailVideoClipPaths,
    pathSummary: buildSnapshotAssetPreviewPathSummary(formatPaths(keyframePaths), formatPaths(midframePaths), formatPaths(tailVideoClipPaths), t),
  }
}

export function buildSnapshotAssetPreviewPathSummary(
  keyframePaths: string | null,
  midframePaths: string | null,
  videoClipPaths: string | null,
  t?: TFunction,
): string | null {
  if (!keyframePaths && !midframePaths && !videoClipPaths) return null
  const parts = [
    keyframePaths ? `KF ${keyframePaths}` : '',
    midframePaths ? `MF ${midframePaths}` : '',
    videoClipPaths ? `VC ${videoClipPaths}` : '',
  ].filter(Boolean).join('  ')
  return t ? t('dreamweaverRun.snapshotPathSummary', { parts }) : `快照路径：${parts}`
}
