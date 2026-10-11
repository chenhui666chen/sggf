import { useState, useCallback } from 'react'
import { STYLE_PRESETS, IMAGE_RATIOS, IMAGE_RESOLUTIONS } from '../constants/dreamweaver'

export interface UseDreamweaverRunConfigReturn {
  highQuality: boolean
  setHighQuality: (v: boolean) => void
  qcAllowFail: boolean
  setQcAllowFail: (v: boolean) => void
  smartTuning: boolean
  setSmartTuning: (v: boolean) => void
  videoRequireConfirmation: boolean
  setVideoRequireConfirmation: (v: boolean) => void
  promptReviewRequired: boolean
  setPromptReviewRequired: (v: boolean) => void
  abVariant: string
  setAbVariant: (v: string) => void
  stylePreset: string
  setStylePreset: (v: string) => void
  imageRatio: string
  setImageRatio: (v: string) => void
  imageResolution: string
  setImageResolution: (v: string) => void
  imageModel: string
  setImageModel: (v: string) => void
  videoModel: string
  setVideoModel: (v: string) => void
  videoEditModel: string
  setVideoEditModel: (v: string) => void
  visionModel: string
  setVisionModel: (v: string) => void
  enableVideoEdit: boolean
  setEnableVideoEdit: (v: boolean) => void
  enableVisionReview: boolean
  setEnableVisionReview: (v: boolean) => void
  enableSafetyAudit: boolean
  setEnableSafetyAudit: (v: boolean) => void
  safetyFailPolicy: 'warn' | 'block'
  setSafetyFailPolicy: (v: 'warn' | 'block') => void
  resetConfig: () => void
}

const DEFAULTS = {
  highQuality: true,
  qcAllowFail: false,
  smartTuning: true,
  videoRequireConfirmation: true,
  promptReviewRequired: true,
  abVariant: '',
  stylePreset: STYLE_PRESETS.CINEMATIC_REALISTIC,
  imageRatio: IMAGE_RATIOS.LANDSCAPE_16_9,
  imageResolution: IMAGE_RESOLUTIONS.HD_720P,
  imageModel: 'qwen-image-3.0-pro',
  videoModel: 'wan3.0-video',
  videoEditModel: 'wan3.0-video',
  visionModel: 'qwen3-vl-plus',
  enableVideoEdit: true,
  enableVisionReview: true,
  enableSafetyAudit: false,
  safetyFailPolicy: 'warn' as const,
}

export function useDreamweaverRunConfig(): UseDreamweaverRunConfigReturn {
  const [highQuality, setHighQuality] = useState(DEFAULTS.highQuality)
  const [qcAllowFail, setQcAllowFail] = useState(DEFAULTS.qcAllowFail)
  const [smartTuning, setSmartTuning] = useState(DEFAULTS.smartTuning)
  const [videoRequireConfirmation, setVideoRequireConfirmation] = useState(DEFAULTS.videoRequireConfirmation)
  const [promptReviewRequired, setPromptReviewRequired] = useState(DEFAULTS.promptReviewRequired)
  const [abVariant, setAbVariant] = useState(DEFAULTS.abVariant)
  const [stylePreset, setStylePreset] = useState<string>(DEFAULTS.stylePreset)
  const [imageRatio, setImageRatio] = useState<string>(DEFAULTS.imageRatio)
  const [imageResolution, setImageResolution] = useState<string>(DEFAULTS.imageResolution)
  const [imageModel, setImageModel] = useState(DEFAULTS.imageModel)
  const [videoModel, setVideoModel] = useState(DEFAULTS.videoModel)
  const [videoEditModel, setVideoEditModel] = useState(DEFAULTS.videoEditModel)
  const [visionModel, setVisionModel] = useState(DEFAULTS.visionModel)
  const [enableVideoEdit, setEnableVideoEdit] = useState(DEFAULTS.enableVideoEdit)
  const [enableVisionReview, setEnableVisionReview] = useState(DEFAULTS.enableVisionReview)
  const [enableSafetyAudit, setEnableSafetyAudit] = useState(DEFAULTS.enableSafetyAudit)
  const [safetyFailPolicy, setSafetyFailPolicy] = useState<'warn' | 'block'>(DEFAULTS.safetyFailPolicy)

  const resetConfig = useCallback(() => {
    setHighQuality(DEFAULTS.highQuality)
    setQcAllowFail(DEFAULTS.qcAllowFail)
    setSmartTuning(DEFAULTS.smartTuning)
    setVideoRequireConfirmation(DEFAULTS.videoRequireConfirmation)
    setPromptReviewRequired(DEFAULTS.promptReviewRequired)
    setAbVariant(DEFAULTS.abVariant)
    setStylePreset(DEFAULTS.stylePreset)
    setImageRatio(DEFAULTS.imageRatio)
    setImageResolution(DEFAULTS.imageResolution)
    setImageModel(DEFAULTS.imageModel)
    setVideoModel(DEFAULTS.videoModel)
    setVideoEditModel(DEFAULTS.videoEditModel)
    setVisionModel(DEFAULTS.visionModel)
    setEnableVideoEdit(DEFAULTS.enableVideoEdit)
    setEnableVisionReview(DEFAULTS.enableVisionReview)
    setEnableSafetyAudit(DEFAULTS.enableSafetyAudit)
    setSafetyFailPolicy(DEFAULTS.safetyFailPolicy)
  }, [])

  return {
    highQuality,
    setHighQuality,
    qcAllowFail,
    setQcAllowFail,
    smartTuning,
    setSmartTuning,
    videoRequireConfirmation,
    setVideoRequireConfirmation,
    promptReviewRequired,
    setPromptReviewRequired,
    abVariant,
    setAbVariant,
    stylePreset,
    setStylePreset,
    imageRatio,
    setImageRatio,
    imageResolution,
    setImageResolution,
    imageModel,
    setImageModel,
    videoModel,
    setVideoModel,
    videoEditModel,
    setVideoEditModel,
    visionModel,
    setVisionModel,
    enableVideoEdit,
    setEnableVideoEdit,
    enableVisionReview,
    setEnableVisionReview,
    enableSafetyAudit,
    setEnableSafetyAudit,
    safetyFailPolicy,
    setSafetyFailPolicy,
    resetConfig,
  }
}
