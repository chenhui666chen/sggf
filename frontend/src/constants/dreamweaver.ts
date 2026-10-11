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
  [STYLE_PRESETS.CINEMATIC_REALISTIC]: 'dreamweaverRun.stylePresetCinematicRealistic',
  [STYLE_PRESETS.ANIME]: 'dreamweaverRun.stylePresetAnime',
  [STYLE_PRESETS.INK_WASH]: 'dreamweaverRun.stylePresetInkWash',
  [STYLE_PRESETS.CYBERPUNK]: 'dreamweaverRun.stylePresetCyberpunk',
}

export const IMAGE_RATIOS = {
  LANDSCAPE_16_9: '16:9',
  PORTRAIT_9_16: '9:16',
} as const

export const IMAGE_RATIOS_LABELS: Record<string, string> = {
  [IMAGE_RATIOS.LANDSCAPE_16_9]: 'dreamweaverRun.regenRatioLandscape',
  [IMAGE_RATIOS.PORTRAIT_9_16]: 'dreamweaverRun.regenRatioPortrait',
}

export const IMAGE_RESOLUTIONS = {
  HD_720P: '720p',
  FHD_1080P: '1080p',
} as const

export const IMAGE_RESOLUTIONS_LABELS: Record<string, string> = {
  [IMAGE_RESOLUTIONS.HD_720P]: 'dreamweaverRun.imageResolutionHd720',
  [IMAGE_RESOLUTIONS.FHD_1080P]: 'dreamweaverRun.imageResolutionFhd1080',
}

export const IMAGE_MODEL_OPTIONS = [
  { value: 'qwen-image-3.0-pro', label: 'dreamweaverRun.modelImageQwen30Pro' },
  { value: 'qwen-image-3.0', label: 'dreamweaverRun.modelImageQwen30' },
  { value: 'wan2.7-image-pro', label: 'dreamweaverRun.modelImageWan27Pro' },
  { value: 'doubao-seedream-5-0', label: 'dreamweaverRun.modelImageDoubaoSeedream50' },
  { value: 'doubao-seedream-5-0-pro', label: 'Doubao Seedream 5.0 Pro' },
  { value: 'kling/kling-v3-image-generation', label: 'dreamweaverRun.modelImageKlingV3' },
  { value: 'kling/kling-v3-omni-image-generation', label: 'dreamweaverRun.modelImageKlingV3Omni' },
  { value: 'qwen-image-edit-plus', label: 'dreamweaverRun.modelImageQwenEditPlus' },
]

export const VIDEO_MODEL_OPTIONS = [
  { value: 'wan3.0-video', label: 'dreamweaverRun.modelVideoWan30' },
  { value: 'doubao-seedance-2-5', label: 'Doubao Seedance 2.5' },
  { value: 'doubao-seedance-2-0', label: 'Doubao Seedance 2.0（SOTA）' },
  { value: 'doubao-seedance-2-0-fast', label: 'Doubao Seedance 2.0 Fast' },
  { value: 'kling/kling-v3-video-generation', label: 'dreamweaverRun.modelVideoKlingV3' },
  { value: 'kling/kling-v3-omni-video-generation', label: 'dreamweaverRun.modelVideoKlingV3Omni' },
  { value: 'pixverse-v6-t2v', label: 'PixVerse V6' },
  { value: 'vidu-q3-pro-text2video', label: 'dreamweaverRun.modelVideoViduQ3Text2Video' },
  { value: 'vidu-q3-pro-img2video', label: 'dreamweaverRun.modelVideoViduQ3Img2Video' },
  { value: 'vidu-q3-pro-start-end2video', label: 'dreamweaverRun.modelVideoViduQ3StartEnd2Video' },
]

export const VIDEO_EDIT_MODEL_OPTIONS = [
  { value: 'wan3.0-video', label: 'dreamweaverRun.modelVideoWan30' },
  { value: 'doubao-seedance-2-5', label: 'Doubao Seedance 2.5' },
  { value: 'doubao-seedance-2-0', label: 'Doubao Seedance 2.0' },
  { value: 'doubao-seedance-2-0-fast', label: 'Doubao Seedance 2.0 Fast' },
]

export const VISION_MODEL_OPTIONS = [
  { value: 'qwen3-vl-plus', label: 'dreamweaverRun.modelVisionQwen3VlPlus' },
  { value: 'qwen3.5-omni-plus', label: 'dreamweaverRun.modelVisionQwen35OmniPlus' },
]

export const SAFETY_FAIL_POLICY_OPTIONS = [
  { value: 'warn', label: 'dreamweaverRun.safetyPolicyWarn' },
  { value: 'block', label: 'dreamweaverRun.safetyPolicyBlock' },
]

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
  [CHARACTER_VIEWS.FRONT]: 'dreamweaverRun.characterViewFront',
  [CHARACTER_VIEWS.SIDE]: 'dreamweaverRun.characterViewSide',
  [CHARACTER_VIEWS.BACK]: 'dreamweaverRun.characterViewBack',
  [CHARACTER_VIEWS.HALF_FRONT]: 'dreamweaverRun.characterViewHalfFront',
  [CHARACTER_VIEWS.HALF_3_4]: 'dreamweaverRun.characterViewHalf3To4',
  [CHARACTER_VIEWS.HALF_SIDE]: 'dreamweaverRun.characterViewHalfSide',
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

export const PREVIEW_STEPS_LABELS = ['dreamweaverRun.previewStepScript', 'dreamweaverRun.previewStepStoryboard', 'dreamweaverRun.previewStepAssets', 'dreamweaverRun.previewStepShots', 'dreamweaverRun.previewStepMerged'] as const

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
