import type { ChipProps } from '@mui/material'

import type { TtsModel } from './types'
import { findTtsModelOption, type TtsModelOption } from './ttsModels'

type ChipTone = Extract<ChipProps['color'], 'success' | 'warning' | 'info' | 'error' | 'default'>

export const TTS_MODEL_BADGES: Record<string, { label: string; color: ChipTone }> = {
  'qwen3-tts-instruct-flash': { label: '低价', color: 'success' },
  'cosyvoice-v3.5-plus': { label: '高音质', color: 'warning' },
  'minimax-speech-2.8-hd': { label: '高清', color: 'error' },
  'minimax-speech-2.8-turbo': { label: '低成本', color: 'info' },
}

export const getTtsModelBadge = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): { label: string; color: ChipTone } | null => {
  const option = findTtsModelOption(model, modelOptions)
  if (option?.costLevel === 'low') {
    return { label: '低价', color: 'success' }
  }
  if (option?.qualityLevel === 'premium') {
    return { label: '精品', color: 'warning' }
  }
  if (option?.qualityLevel === 'high') {
    return { label: '高清', color: 'error' }
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
