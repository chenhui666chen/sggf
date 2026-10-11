import { describe, expect, it } from 'vitest'
import {
  DREAMWEAVER_STAGES,
  STYLE_PRESETS,
  STYLE_PRESET_LABELS,
  IMAGE_RATIOS,
  CHARACTER_VIEWS,
  CHARACTER_VIEW_ORDER,
  CHARACTER_VIEW_LABELS,
  PREVIEW_STEPS,
  stageToPreviewStep,
  isTerminalStage,
  isWaitingStage,
  isVideoStage,
} from '../dreamweaver'

describe('dreamweaver constants', () => {
  describe('DREAMWEAVER_STAGES', () => {
    it('应包含所有必要的阶段', () => {
      expect(DREAMWEAVER_STAGES.INIT).toBe('init')
      expect(DREAMWEAVER_STAGES.SCRIPT).toBe('script')
      expect(DREAMWEAVER_STAGES.WAITING_SCRIPT_APPROVAL).toBe('waiting_script_approval')
      expect(DREAMWEAVER_STAGES.STORYBOARD).toBe('storyboard')
      expect(DREAMWEAVER_STAGES.ASSET_LIBRARY).toBe('asset_library')
      expect(DREAMWEAVER_STAGES.WAITING_APPROVAL).toBe('waiting_approval')
      expect(DREAMWEAVER_STAGES.KEYFRAMES).toBe('keyframes')
      expect(DREAMWEAVER_STAGES.MIDFRAMES).toBe('midframes')
      expect(DREAMWEAVER_STAGES.VIDEO).toBe('video')
      expect(DREAMWEAVER_STAGES.WAITING_VIDEO_CONFIRMATION).toBe('waiting_video_confirmation')
      expect(DREAMWEAVER_STAGES.EDIT).toBe('edit')
      expect(DREAMWEAVER_STAGES.REVIEW).toBe('review')
      expect(DREAMWEAVER_STAGES.DONE).toBe('done')
      expect(DREAMWEAVER_STAGES.REWORK).toBe('rework')
      expect(DREAMWEAVER_STAGES.FAILED).toBe('failed')
    })
  })

  describe('STYLE_PRESETS', () => {
    it('应包含所有风格预设', () => {
      expect(STYLE_PRESETS.CINEMATIC_REALISTIC).toBe('cinematic_realistic')
      expect(STYLE_PRESETS.ANIME).toBe('anime')
      expect(STYLE_PRESETS.INK_WASH).toBe('ink_wash')
      expect(STYLE_PRESETS.CYBERPUNK).toBe('cyberpunk')
    })
  })

  describe('STYLE_PRESET_LABELS', () => {
    it('应正确映射风格预设标签', () => {
      expect(STYLE_PRESET_LABELS[STYLE_PRESETS.CINEMATIC_REALISTIC]).toBe('dreamweaverRun.stylePresetCinematicRealistic')
      expect(STYLE_PRESET_LABELS[STYLE_PRESETS.ANIME]).toBe('dreamweaverRun.stylePresetAnime')
      expect(STYLE_PRESET_LABELS[STYLE_PRESETS.INK_WASH]).toBe('dreamweaverRun.stylePresetInkWash')
      expect(STYLE_PRESET_LABELS[STYLE_PRESETS.CYBERPUNK]).toBe('dreamweaverRun.stylePresetCyberpunk')
    })
  })

  describe('IMAGE_RATIOS', () => {
    it('应包含所有图片比例', () => {
      expect(IMAGE_RATIOS.LANDSCAPE_16_9).toBe('16:9')
      expect(IMAGE_RATIOS.PORTRAIT_9_16).toBe('9:16')
    })
  })

  describe('CHARACTER_VIEW_ORDER', () => {
    it('应按正确顺序排列角色视角', () => {
      expect(CHARACTER_VIEW_ORDER).toHaveLength(6)
      expect(CHARACTER_VIEW_ORDER[0]).toBe(CHARACTER_VIEWS.FRONT)
      expect(CHARACTER_VIEW_ORDER[1]).toBe(CHARACTER_VIEWS.SIDE)
      expect(CHARACTER_VIEW_ORDER[2]).toBe(CHARACTER_VIEWS.BACK)
      expect(CHARACTER_VIEW_ORDER[3]).toBe(CHARACTER_VIEWS.HALF_FRONT)
      expect(CHARACTER_VIEW_ORDER[4]).toBe(CHARACTER_VIEWS.HALF_3_4)
      expect(CHARACTER_VIEW_ORDER[5]).toBe(CHARACTER_VIEWS.HALF_SIDE)
    })
  })

  describe('CHARACTER_VIEW_LABELS', () => {
    it('应正确映射角色视角标签', () => {
      expect(CHARACTER_VIEW_LABELS[CHARACTER_VIEWS.FRONT]).toBe('dreamweaverRun.characterViewFront')
      expect(CHARACTER_VIEW_LABELS[CHARACTER_VIEWS.SIDE]).toBe('dreamweaverRun.characterViewSide')
      expect(CHARACTER_VIEW_LABELS[CHARACTER_VIEWS.BACK]).toBe('dreamweaverRun.characterViewBack')
      expect(CHARACTER_VIEW_LABELS[CHARACTER_VIEWS.HALF_FRONT]).toBe('dreamweaverRun.characterViewHalfFront')
      expect(CHARACTER_VIEW_LABELS[CHARACTER_VIEWS.HALF_3_4]).toBe('dreamweaverRun.characterViewHalf3To4')
      expect(CHARACTER_VIEW_LABELS[CHARACTER_VIEWS.HALF_SIDE]).toBe('dreamweaverRun.characterViewHalfSide')
    })
  })
})

describe('stageToPreviewStep', () => {
  it('应正确映射剧本阶段', () => {
    expect(stageToPreviewStep('init')).toBe(PREVIEW_STEPS.SCRIPT)
    expect(stageToPreviewStep('script')).toBe(PREVIEW_STEPS.SCRIPT)
    expect(stageToPreviewStep('waiting_script_approval')).toBe(PREVIEW_STEPS.SCRIPT)
  })

  it('应正确映射分镜阶段', () => {
    expect(stageToPreviewStep('storyboard')).toBe(PREVIEW_STEPS.STORYBOARD)
  })

  it('应正确映射素材阶段', () => {
    expect(stageToPreviewStep('asset_library')).toBe(PREVIEW_STEPS.ASSET_LIBRARY)
    expect(stageToPreviewStep('waiting_approval')).toBe(PREVIEW_STEPS.ASSET_LIBRARY)
  })

  it('应正确映射视频阶段', () => {
    expect(stageToPreviewStep('keyframes')).toBe(PREVIEW_STEPS.VIDEO)
    expect(stageToPreviewStep('midframes')).toBe(PREVIEW_STEPS.VIDEO)
    expect(stageToPreviewStep('video')).toBe(PREVIEW_STEPS.VIDEO)
    expect(stageToPreviewStep('waiting_video_confirmation')).toBe(PREVIEW_STEPS.VIDEO)
  })

  it('应正确映射完成阶段', () => {
    expect(stageToPreviewStep('edit')).toBe(PREVIEW_STEPS.COMPLETE)
    expect(stageToPreviewStep('review')).toBe(PREVIEW_STEPS.COMPLETE)
    expect(stageToPreviewStep('done')).toBe(PREVIEW_STEPS.COMPLETE)
    expect(stageToPreviewStep('rework')).toBe(PREVIEW_STEPS.COMPLETE)
    expect(stageToPreviewStep('failed')).toBe(PREVIEW_STEPS.COMPLETE)
  })

  it('应处理空值和无效值', () => {
    expect(stageToPreviewStep(null)).toBe(PREVIEW_STEPS.SCRIPT)
    expect(stageToPreviewStep(undefined)).toBe(PREVIEW_STEPS.SCRIPT)
    expect(stageToPreviewStep('')).toBe(PREVIEW_STEPS.SCRIPT)
    expect(stageToPreviewStep('unknown')).toBe(PREVIEW_STEPS.SCRIPT)
  })

  it('应处理大小写不一致', () => {
    expect(stageToPreviewStep('SCRIPT')).toBe(PREVIEW_STEPS.SCRIPT)
    expect(stageToPreviewStep('Done')).toBe(PREVIEW_STEPS.COMPLETE)
    expect(stageToPreviewStep('WAITING_APPROVAL')).toBe(PREVIEW_STEPS.ASSET_LIBRARY)
  })
})

describe('isTerminalStage', () => {
  it('应正确识别终止阶段', () => {
    expect(isTerminalStage('done')).toBe(true)
    expect(isTerminalStage('failed')).toBe(true)
    expect(isTerminalStage('DONE')).toBe(true)
    expect(isTerminalStage('FAILED')).toBe(true)
  })

  it('应正确识别非终止阶段', () => {
    expect(isTerminalStage('init')).toBe(false)
    expect(isTerminalStage('script')).toBe(false)
    expect(isTerminalStage('video')).toBe(false)
    expect(isTerminalStage(null)).toBe(false)
    expect(isTerminalStage(undefined)).toBe(false)
  })
})

describe('isWaitingStage', () => {
  it('应正确识别等待阶段', () => {
    expect(isWaitingStage('waiting_script_approval')).toBe(true)
    expect(isWaitingStage('waiting_approval')).toBe(true)
    expect(isWaitingStage('waiting_video_confirmation')).toBe(true)
    expect(isWaitingStage('WAITING_SCRIPT_APPROVAL')).toBe(true)
  })

  it('应正确识别非等待阶段', () => {
    expect(isWaitingStage('init')).toBe(false)
    expect(isWaitingStage('done')).toBe(false)
    expect(isWaitingStage(null)).toBe(false)
    expect(isWaitingStage(undefined)).toBe(false)
  })
})

describe('isVideoStage', () => {
  it('应正确识别视频阶段', () => {
    expect(isVideoStage('video')).toBe(true)
    expect(isVideoStage('waiting_video_confirmation')).toBe(true)
    expect(isVideoStage('VIDEO')).toBe(true)
  })

  it('应正确识别非视频阶段', () => {
    expect(isVideoStage('init')).toBe(false)
    expect(isVideoStage('keyframes')).toBe(false)
    expect(isVideoStage('midframes')).toBe(false)
    expect(isVideoStage(null)).toBe(false)
    expect(isVideoStage(undefined)).toBe(false)
  })
})
