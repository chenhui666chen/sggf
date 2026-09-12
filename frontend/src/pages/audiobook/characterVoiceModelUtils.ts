import type { ChipProps } from '@mui/material'

import type { TtsModel } from './types'
import { findTtsModelOption, type TtsModelOption } from './ttsModels'

type ChipTone = Extract<ChipProps['color'], 'success' | 'warning' | 'info' | 'error' | 'default'>

export const TTS_MODEL_BADGES: Record<string, { labelKey: string; color: ChipTone }> = {
  'qwen3-tts-instruct-flash': { labelKey: 'audiobook.ttsModelBadges.lowPrice', color: 'success' },
  'cosyvoice-v3.5-plus': { labelKey: 'audiobook.ttsModelBadges.highQuality', color: 'warning' },
  'minimax-speech-2.8-hd': { labelKey: 'audiobook.ttsModelBadges.hd', color: 'error' },
  'minimax-speech-2.8-turbo': { labelKey: 'audiobook.ttsModelBadges.lowCost', color: 'info' },
}

export const getTtsModelBadge = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): { labelKey: string; color: ChipTone } | null => {
  const option = findTtsModelOption(model, modelOptions)
  if (option?.costLevel === 'low') {
    return { labelKey: 'audiobook.ttsModelBadges.lowPrice', color: 'success' }
  }
  if (option?.qualityLevel === 'premium') {
    return { labelKey: 'audiobook.ttsModelBadges.premium', color: 'warning' }
  }
  if (option?.qualityLevel === 'high') {
    return { labelKey: 'audiobook.ttsModelBadges.hd', color: 'error' }
  }
  return TTS_MODEL_BADGES[model] || null
}

export const getCharacterModelChipColor = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
) => {
  const option = findTtsModelOption(model, modelOptions)
  if (option?.qualityLevel === 'premium') {
    return 'warning'
  }
  if (option?.qualityLevel === 'high' || model.startsWith('minimax-')) {
    return 'info'
  }
  return 'default'
}
