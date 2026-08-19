import { normalizeTtsModelValue } from './ttsModels'
import type { TtsModel, VoicePreset } from './types'

export const SEED_SCENE_TTS_MODEL: TtsModel = 'seed-tts-2.0-expressive'

// 与后端 voice_reference_resolver._provider_reference 的白名单保持一致：
// 1. 模型归一化为 seed-tts-2.0-expressive 且有 speaker/voice id → speaker 直传（原生音色）
// 2. referenceSource ∈ {user_private, public_pool} → 走音频参考（私有复刻/设计、公共音色池）
// 其余供应商官方音色（如 qwen3/minimax/mimo 官方音色）在场景生成模式会被后端拒绝。
export const isSeedSceneVoiceCompatible = (preset: VoicePreset): boolean => {
  if (preset.referenceSource === 'user_private' || preset.referenceSource === 'public_pool') {
    return true
  }
  const normalizedModel = preset.sourceModel ? normalizeTtsModelValue(preset.sourceModel) : null
  return normalizedModel === SEED_SCENE_TTS_MODEL && Boolean(preset.speaker || preset.id)
}

export const SEED_SCENE_INCOMPATIBLE_VOICE_REASON =
  '场景生成模式仅支持豆包 Seed-TTS 原生音色与音色池音色，请更换其他音色'

export const markSeedSceneIncompatibleVoicePresets = (presets: VoicePreset[]): VoicePreset[] =>
  presets.map((preset) => {
    if (isSeedSceneVoiceCompatible(preset)) {
      return preset
    }
    return {
      ...preset,
      disabled: true,
      disabledReason: preset.disabledReason || SEED_SCENE_INCOMPATIBLE_VOICE_REASON,
    }
  })
