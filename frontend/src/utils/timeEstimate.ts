import type { TFunction } from 'i18next'

export interface StageTimeEstimate {
  stage: string
  estimatedMinutes: number
  confidence: 'high' | 'medium' | 'low'
}

const STAGE_TIME_ESTIMATES: Record<string, { minMinutes: number; maxMinutes: number; avgMinutes: number }> = {
  init: { minMinutes: 0.1, maxMinutes: 0.5, avgMinutes: 0.2 },
  script: { minMinutes: 1, maxMinutes: 5, avgMinutes: 2 },
  waiting_script_approval: { minMinutes: 0, maxMinutes: 0, avgMinutes: 0 },
  storyboard: { minMinutes: 2, maxMinutes: 8, avgMinutes: 4 },
  asset_library: { minMinutes: 3, maxMinutes: 15, avgMinutes: 8 },
  waiting_approval: { minMinutes: 0, maxMinutes: 0, avgMinutes: 0 },
  keyframes: { minMinutes: 5, maxMinutes: 20, avgMinutes: 10 },
  midframes: { minMinutes: 3, maxMinutes: 12, avgMinutes: 6 },
  video: { minMinutes: 5, maxMinutes: 25, avgMinutes: 12 },
  waiting_video_confirmation: { minMinutes: 0, maxMinutes: 0, avgMinutes: 0 },
  edit: { minMinutes: 2, maxMinutes: 10, avgMinutes: 5 },
  review: { minMinutes: 1, maxMinutes: 5, avgMinutes: 2 },
}

const STAGE_ORDER = [
  'init',
  'script',
  'waiting_script_approval',
  'storyboard',
  'asset_library',
  'waiting_approval',
  'keyframes',
  'midframes',
  'video',
  'waiting_video_confirmation',
  'edit',
  'review',
]

export function estimateRemainingTime(
  currentStage: string | null | undefined,
  currentProgress: number | null | undefined
): StageTimeEstimate | null {
  const stage = (currentStage || '').trim().toLowerCase()
  if (!stage) return null

  const stageInfo = STAGE_TIME_ESTIMATES[stage]
  if (!stageInfo) return null

  const progress = typeof currentProgress === 'number' ? Math.max(0, Math.min(100, currentProgress)) : 0

  const stageIndex = STAGE_ORDER.indexOf(stage)
  if (stageIndex < 0) return null

  const remainingStages = STAGE_ORDER.slice(stageIndex + 1)

  let remainingMinutes = 0
  for (const s of remainingStages) {
    const info = STAGE_TIME_ESTIMATES[s]
    if (info) {
      remainingMinutes += info.avgMinutes
    }
  }

  const currentStageRemaining = stageInfo.avgMinutes * (1 - progress / 100)
  remainingMinutes += currentStageRemaining

  let confidence: 'high' | 'medium' | 'low' = 'medium'
  if (progress > 50) {
    confidence = 'high'
  } else if (remainingStages.length > 5) {
    confidence = 'low'
  }

  return {
    stage,
    estimatedMinutes: Math.max(0.1, Math.round(remainingMinutes * 10) / 10),
    confidence,
  }
}

const STAGE_NAME_LABELS: Record<string, { label: string; labelKey: string }> = {
  init: { label: '初始化', labelKey: 'timeEstimate.stageInit' },
  script: { label: '剧本生成', labelKey: 'timeEstimate.stageScript' },
  waiting_script_approval: { label: '剧本审核', labelKey: 'timeEstimate.stageWaitingScriptApproval' },
  storyboard: { label: '分镜生成', labelKey: 'timeEstimate.stageStoryboard' },
  asset_library: { label: '素材生成', labelKey: 'timeEstimate.stageAssetLibrary' },
  waiting_approval: { label: '素材审核', labelKey: 'timeEstimate.stageWaitingApproval' },
  keyframes: { label: '关键帧生成', labelKey: 'timeEstimate.stageKeyframes' },
  midframes: { label: '中间帧生成', labelKey: 'timeEstimate.stageMidframes' },
  video: { label: '视频生成', labelKey: 'timeEstimate.stageVideo' },
  waiting_video_confirmation: { label: '视频确认', labelKey: 'timeEstimate.stageWaitingVideoConfirmation' },
  edit: { label: '剪辑合成', labelKey: 'timeEstimate.stageEdit' },
  review: { label: '最终审核', labelKey: 'timeEstimate.stageReview' },
  done: { label: '完成', labelKey: 'timeEstimate.stageDone' },
  rework: { label: '返工', labelKey: 'timeEstimate.stageRework' },
  failed: { label: '失败', labelKey: 'timeEstimate.stageFailed' },
}

export function formatEstimatedTime(minutes: number, t?: TFunction): string {
  if (minutes < 1) {
    return t ? t('timeEstimate.lessThanMinute') : '不到1分钟'
  } else if (minutes < 60) {
    return t ? t('timeEstimate.aboutMinutes', { count: Math.round(minutes) }) : `约${Math.round(minutes)}分钟`
  } else {
    const hours = Math.floor(minutes / 60)
    const mins = Math.round(minutes % 60)
    if (mins > 0) {
      return t ? t('timeEstimate.aboutHoursMinutes', { hours, minutes: mins }) : `约${hours}小时${mins}分钟`
    }
    return t ? t('timeEstimate.aboutHours', { hours }) : `约${hours}小时`
  }
}

export function getStageDisplayName(stage: string, t?: TFunction): string {
  const entry = STAGE_NAME_LABELS[(stage || '').trim().toLowerCase()]
  if (entry) {
    return t ? t(entry.labelKey) : entry.label
  }
  return stage || (t ? t('timeEstimate.unknownStage') : '未知阶段')
}
