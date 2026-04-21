import type { StageConfig, StageKey, StageStatus, TtsModel } from './types'

export const DEFAULT_NARRATOR_BY_MODEL: Record<TtsModel, string> = {
  'qwen3-tts-instruct-flash': 'Neil',
  'cosyvoice-v3-plus': 'longanyang',
  'minimax-speech-2.8-hd': 'male-qn-jingying',
  'minimax-speech-2.8-turbo': 'male-qn-jingying',
}

export const TTS_MODEL_LABELS: Record<TtsModel, string> = {
  'qwen3-tts-instruct-flash': 'Qwen3-TTS Instruct Flash',
  'cosyvoice-v3-plus': 'CosyVoice v3-plus',
  'minimax-speech-2.8-hd': 'MiniMax HD',
  'minimax-speech-2.8-turbo': 'MiniMax Turbo',
}

export const isTtsModel = (value: unknown): value is TtsModel =>
  value === 'qwen3-tts-instruct-flash'
  || value === 'cosyvoice-v3-plus'
  || value === 'minimax-speech-2.8-hd'
  || value === 'minimax-speech-2.8-turbo'

export const getTtsModelLabel = (model: TtsModel) => TTS_MODEL_LABELS[model]

export const getDefaultNarratorId = (model: TtsModel) =>
  DEFAULT_NARRATOR_BY_MODEL[model] || 'Neil'

export const QWEN_FLASH_ONLY_TO_INSTRUCT: Record<string, string> = {
  Aiden: 'Ethan',
  Alek: 'Elias',
  Andre: 'Neil',
  Bodega: 'Ethan',
  Dolce: 'Vincent',
  Dylan: 'Ethan',
  Ebona: 'Bellona',
  Emilien: 'Ethan',
  Eric: 'Nofish',
  Jada: 'Mia',
  Jennifer: 'Bellona',
  Katerina: 'Vivian',
  Kiki: 'Nini',
  Lenn: 'Elias',
  Li: 'Vincent',
  Marcus: 'Vincent',
  'Ono Anna': 'Nini',
  Peter: 'Vincent',
  'Radio Gol': 'Ethan',
  Rocky: 'Kai',
  Roy: 'Vincent',
  Ryan: 'Neil',
  Sohee: 'Serena',
  Sonrisa: 'Stella',
  Sunny: 'Mia',
}

export const LEGACY_VOICE_ALIASES: Record<string, string> = {
  male_young_energetic: 'Ethan',
  male_young_gentle: 'Vincent',
  male_adult_calm: 'Neil',
  male_adult_energetic: 'Ethan',
  male_elder_wise: 'Eldric Sage',
  male_warm: 'Vincent',
  male_customer_service: 'Kai',
  male_refreshing: 'Kai',
  male_monkey: 'Nofish',
  male_narrator: 'Neil',
  male_villain_sinister: 'Vincent',
  female_villain_cold: 'Bellona',
  female_villain_cunning: 'Vivian',
  female_young_gentle: 'Cherry',
  female_young_energetic: 'Bunny',
  female_young_cute: 'Momo',
  female_adult_elegant: 'Bella',
  female_adult_intellectual: 'Vivian',
  female_capable: 'Bellona',
  female_elder: 'Chelsie',
  female_intimate: 'Mochi',
  female_lively: 'Mia',
  female_child: 'Momo',
}

export const normalizeVoiceId = (
  model: TtsModel,
  voiceId?: string | null,
) => {
  if (!voiceId) return ''
  if (model === 'qwen3-tts-instruct-flash') {
    const normalizedVoiceId = LEGACY_VOICE_ALIASES[voiceId] || voiceId
    return QWEN_FLASH_ONLY_TO_INSTRUCT[normalizedVoiceId] || normalizedVoiceId
  }
  const cosyvoiceV3PlusLegacyAliases: Record<string, string> = {
    longanzhi_v3: 'longanyang',
    longanyun_v3: 'longanyang',
    longyichen_v3: 'longanyang',
    longwanjun_v3: 'longanhuan',
    longanwen_v3: 'longanhuan',
  }
  return cosyvoiceV3PlusLegacyAliases[voiceId] || voiceId
}

export const STAGE_CONFIG: StageConfig[] = [
  { key: 'strategy', name: '策略制定', icon: '01', desc: '分析原文，制定改编策略' },
  { key: 'script_adaptation', name: '剧本改编', icon: '02', desc: '将小说改编为有声剧本' },
  { key: 'voice_design', name: '音色设计', icon: '03', desc: '为角色分配音色参数' },
  { key: 'sound_design', name: '音效设计', icon: '04', desc: '设计场景音效和环境音' },
  { key: 'music_composition', name: '音乐编曲', icon: '05', desc: '设计背景音乐方案' },
  { key: 'quality_review', name: '剧本评审', icon: '06', desc: 'TTS前质量检查' },
  { key: 'audio_prompt_review', name: '提示词审阅', icon: '07', desc: '审阅音频提示词并试听' },
  { key: 'tts_synthesis', name: 'TTS合成', icon: '08', desc: '语音合成生成音频' },
  { key: 'audio_mixing', name: '音频混合', icon: '09', desc: '混音与后期处理' },
  { key: 'final_audio_review', name: '最终评审', icon: '10', desc: '最终质量检查' },
]

export const STAGE_KEYS: StageKey[] = STAGE_CONFIG.map((stage) => stage.key)

export const STAGE_STATUS_LABELS: Record<StageStatus, string> = {
  pending: '等待中',
  running: '进行中',
  completed: '已完成',
  failed: '失败',
}
