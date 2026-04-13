export const DREAMWEAVER_STAGES = {
  INIT: 'init',
  SCRIPT: 'script',
  WAITING_SCRIPT_APPROVAL: 'waiting_script_approval',
  STORYBOARD: 'storyboard',
  ASSET_LIBRARY: 'asset_library',
  WAITING_APPROVAL: 'waiting_approval',
  KEYFRAMES: 'keyframes',
  MIDFRAMES: 'midframes',
  VIDEO: 'video',
  WAITING_VIDEO_CONFIRMATION: 'waiting_video_confirmation',
  EDIT: 'edit',
  REVIEW: 'review',
  DONE: 'done',
  REWORK: 'rework',
  FAILED: 'failed',
} as const

export const DREAMWEAVER_STATES = {
  PENDING: 'PENDING',
  RUNNING: 'RUNNING',
  PAUSED: 'PAUSED',
  DONE: 'DONE',
  FAILED: 'FAILED',
} as const

export const DREAMWEAVER_TASK_STATUS = {
  QUEUED: 'queued',
  RUNNING: 'running',
  COMPLETED: 'completed',
  FAILED: 'failed',
  WAITING: 'waiting',
} as const

export const QUALITY_MODES = {
  QUALITY: 'quality',
  COST: 'cost',
} as const

export const STYLE_PRESETS = {
  CINEMATIC_REALISTIC: 'cinematic_realistic',
  ANIME: 'anime',
  INK_WASH: 'ink_wash',
  CYBERPUNK: 'cyberpunk',
} as const

export const STYLE_PRESET_LABELS: Record<string, string> = {
  [STYLE_PRESETS.CINEMATIC_REALISTIC]: '电影写实',
  [STYLE_PRESETS.ANIME]: '二次元动画',
  [STYLE_PRESETS.INK_WASH]: '国风水墨',
  [STYLE_PRESETS.CYBERPUNK]: '赛博朋克',
}

export const IMAGE_RATIOS = {
  LANDSCAPE_16_9: '16:9',
  PORTRAIT_9_16: '9:16',
} as const

export const IMAGE_RATIOS_LABELS: Record<string, string> = {
  [IMAGE_RATIOS.LANDSCAPE_16_9]: '横屏 16:9',
  [IMAGE_RATIOS.PORTRAIT_9_16]: '竖屏 9:16',
}

export const IMAGE_RESOLUTIONS = {
  HD_720P: '720p',
  FHD_1080P: '1080p',
} as const

export const IMAGE_RESOLUTIONS_LABELS: Record<string, string> = {
  [IMAGE_RESOLUTIONS.HD_720P]: '720p (高清)',
  [IMAGE_RESOLUTIONS.FHD_1080P]: '1080p (全高清)',
}

export const CHARACTER_VIEWS = {
  FRONT: 'front',
  SIDE: 'side',
  BACK: 'back',
  HALF_FRONT: 'half_front',
  HALF_3_4: 'half_3_4',
  HALF_SIDE: 'half_side',
} as const

export const CHARACTER_VIEW_ORDER = [
  CHARACTER_VIEWS.FRONT,
  CHARACTER_VIEWS.SIDE,
  CHARACTER_VIEWS.BACK,
  CHARACTER_VIEWS.HALF_FRONT,
  CHARACTER_VIEWS.HALF_3_4,
  CHARACTER_VIEWS.HALF_SIDE,
] as const

export const CHARACTER_VIEW_LABELS: Record<string, string> = {
  [CHARACTER_VIEWS.FRONT]: '正面',
  [CHARACTER_VIEWS.SIDE]: '侧面',
  [CHARACTER_VIEWS.BACK]: '背面',
  [CHARACTER_VIEWS.HALF_FRONT]: '半身正面',
  [CHARACTER_VIEWS.HALF_3_4]: '半身3-4',
  [CHARACTER_VIEWS.HALF_SIDE]: '半身侧面',
}

export const LIBRARY_ENTITY_GROUPS = {
  CHARACTER: 'character',
  SCENE: 'scene',
  PROP: 'prop',
  OTHER: 'other',
} as const

export const ASSET_PLAN_STATUS = {
  PLANNED: 'planned',
  DONE: 'done',
  PROCESSING: 'processing',
} as const

export const PREVIEW_STEPS = {
  SCRIPT: 0,
  STORYBOARD: 1,
  ASSET_LIBRARY: 2,
  VIDEO: 3,
  COMPLETE: 4,
} as const

export const PREVIEW_STEPS_LABELS = ['剧本', '分镜', '素材', '镜头', '合成'] as const

export function stageToPreviewStep(stage: string | null | undefined): number {
  const value = (stage || '').trim().toLowerCase()
  if (!value) return PREVIEW_STEPS.SCRIPT
  if (value === DREAMWEAVER_STAGES.INIT || value === DREAMWEAVER_STAGES.SCRIPT || value === DREAMWEAVER_STAGES.WAITING_SCRIPT_APPROVAL) {
    return PREVIEW_STEPS.SCRIPT
  }
  if (value === DREAMWEAVER_STAGES.STORYBOARD) {
    return PREVIEW_STEPS.STORYBOARD
  }
  if (value === DREAMWEAVER_STAGES.ASSET_LIBRARY || value === DREAMWEAVER_STAGES.WAITING_APPROVAL) {
    return PREVIEW_STEPS.ASSET_LIBRARY
  }
  if (value === DREAMWEAVER_STAGES.KEYFRAMES || value === DREAMWEAVER_STAGES.MIDFRAMES || value === DREAMWEAVER_STAGES.VIDEO || value === DREAMWEAVER_STAGES.WAITING_VIDEO_CONFIRMATION) {
    return PREVIEW_STEPS.VIDEO
  }
  if (value === DREAMWEAVER_STAGES.EDIT || value === DREAMWEAVER_STAGES.REVIEW || value === DREAMWEAVER_STAGES.DONE || value === DREAMWEAVER_STAGES.REWORK || value === DREAMWEAVER_STAGES.FAILED) {
    return PREVIEW_STEPS.COMPLETE
  }
  return PREVIEW_STEPS.SCRIPT
}

export function isTerminalStage(stage: string | null | undefined): boolean {
  const value = (stage || '').trim().toLowerCase()
  return value === DREAMWEAVER_STAGES.DONE || value === DREAMWEAVER_STAGES.FAILED
}

export function isWaitingStage(stage: string | null | undefined): boolean {
  const value = (stage || '').trim().toLowerCase()
  return value === DREAMWEAVER_STAGES.WAITING_SCRIPT_APPROVAL || value === DREAMWEAVER_STAGES.WAITING_APPROVAL || value === DREAMWEAVER_STAGES.WAITING_VIDEO_CONFIRMATION
}

export function isVideoStage(stage: string | null | undefined): boolean {
  const value = (stage || '').trim().toLowerCase()
  return value === DREAMWEAVER_STAGES.VIDEO || value === DREAMWEAVER_STAGES.WAITING_VIDEO_CONFIRMATION
}
