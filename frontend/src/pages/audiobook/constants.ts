import type { StageConfig, StageKey, StageStatus } from './types'

export {
  DEFAULT_NARRATOR_BY_MODEL,
  DEFAULT_TTS_MODEL,
  TTS_MODEL_LABELS,
  TTS_MODELS,
  createTtsModelRecord,
  getDefaultNarratorId,
  getFallbackVoiceId,
  getTtsModelLabel,
  isTtsModel,
  normalizeTtsModelValue,
  normalizeVoiceId,
} from './ttsModels'

export const GENERATION_STAGE_CONFIG: readonly StageConfig[] = [
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

export const EXPORT_STAGE_CONFIG: readonly StageConfig[] = [
  { key: 'project_export', name: '项目导出', icon: '11', desc: '打包整本输出文件' },
]

export const PROMPT_AUDIO_ASR_STAGE_CONFIG: readonly StageConfig[] = [
  { key: 'asr_transcript_queued', name: 'ASR 排队', icon: 'A1', desc: '等待手动转写任务启动' },
  { key: 'asr_transcript_provider_check', name: '配置检查', icon: 'A2', desc: '检查 ASR provider 与成本控制' },
  { key: 'asr_transcript_skipped', name: '转写结果', icon: 'A3', desc: '记录转写状态或跳过原因' },
]

export const STAGE_CONFIG: readonly StageConfig[] = [
  ...GENERATION_STAGE_CONFIG,
  ...EXPORT_STAGE_CONFIG,
  ...PROMPT_AUDIO_ASR_STAGE_CONFIG,
]

export const STAGE_KEYS: StageKey[] = STAGE_CONFIG.map((stage) => stage.key)

export const STAGE_STATUS_LABELS: Record<StageStatus, string> = {
  pending: '等待中',
  running: '进行中',
  completed: '已完成',
  failed: '失败',
}
