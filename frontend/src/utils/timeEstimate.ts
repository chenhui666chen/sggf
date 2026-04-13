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

export function formatEstimatedTime(minutes: number): string {
  if (minutes < 1) {
    return '不到1分钟'
  } else if (minutes < 60) {
    return `约${Math.round(minutes)}分钟`
  } else {
    const hours = Math.floor(minutes / 60)
    const mins = Math.round(minutes % 60)
    if (mins > 0) {
      return `约${hours}小时${mins}分钟`
    }
    return `约${hours}小时`
  }
}

export function getStageDisplayName(stage: string): string {
  const names: Record<string, string> = {
    init: '初始化',
    script: '剧本生成',
    waiting_script_approval: '剧本审核',
    storyboard: '分镜生成',
    asset_library: '素材生成',
    waiting_approval: '素材审核',
    keyframes: '关键帧生成',
    midframes: '中间帧生成',
    video: '视频生成',
    waiting_video_confirmation: '视频确认',
    edit: '剪辑合成',
    review: '最终审核',
    done: '完成',
    rework: '返工',
    failed: '失败',
  }
  return names[(stage || '').trim().toLowerCase()] || stage || '未知阶段'
}
