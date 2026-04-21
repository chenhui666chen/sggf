export interface Project {
  id: number
  title: string
  description?: string
  genre?: string
}

export interface Chapter {
  id: number
  chapter_number: number
  title: string
  content: string
}

export type StageStatus = 'pending' | 'running' | 'completed' | 'failed'

export type PreviewType = 'voice' | 'sfx' | 'bgm' | 'mix'

export type TtsModel =
  | 'qwen3-tts-instruct-flash'
  | 'cosyvoice-v3.5-plus'
  | 'minimax-speech-2.8-hd'
  | 'minimax-speech-2.8-turbo'

export type AudioOutputFormat = 'mp3' | 'wav' | 'm4b'

export type StageKey =
  | 'strategy'
  | 'script_adaptation'
  | 'voice_design'
  | 'sound_design'
  | 'music_composition'
  | 'quality_review'
  | 'audio_prompt_review'
  | 'tts_synthesis'
  | 'audio_mixing'
  | 'final_audio_review'

export interface StageConfig {
  key: StageKey
  name: string
  icon: string
  desc: string
}

export interface StageInfo {
  status: StageStatus
  progress: number
  start_time?: string
  end_time?: string
  error_message?: string
  metrics?: Record<string, any>
  message?: string
}

export interface TaskStatus {
  task_id: string
  audiobook_project_id: number
  chapter_id?: number | null
  status: StageStatus
  current_stage?: string | null
  progress: number
  stages: Record<StageKey, StageInfo>
  created_at?: string
  updated_at?: string
  detail?: Record<string, any>
  overall_progress?: number
}

export interface CharacterVoiceSetting {
  characterId: number
  name: string
  gender?: string | null
  role?: string | null
  voiceId: string
  volume: number
  speed?: number
  pitch?: number
  ttsModel?: TtsModel
  voiceType?: string
  personality?: string
  emotionTendency?: string
}

export interface AudioFxConfig {
  enable_sound_effects: boolean
  enable_music: boolean
  sound_effect_density: 'low' | 'medium' | 'high' | 'off'
  music_density: 'low' | 'medium' | 'high' | 'off'
}

export interface ProjectAudioConfig {
  characters: {
    character_id: number
    name: string
    voice_id: string
    volume: number
    speed?: number | null
    pitch?: number | null
    tts_model?: TtsModel | null
    voice_type?: string | null
    personality?: string | null
    emotion_tendency?: string | null
  }[]
  audio_fx?: AudioFxConfig | null
}

export interface VoiceDefaultParams {
  pitch?: number
  speed?: number
  volume?: number
}

export interface VoicePreset {
  id: string
  speaker: string
  label: string
  gender?: string
  style?: string
  category?: string
  languages?: string[]
  description?: string
  recommended?: string[]
  default_params?: VoiceDefaultParams
  supportsInstruct?: boolean
}

export interface VoiceCatalogMeta {
  model?: string
  updated_at?: string
  source?: string
  voice_count?: number
}

export interface ScriptReviewIssue {
  location?: string
  severity?: string
  category?: string
  description?: string
  suggestion?: string
}

export interface ScriptQualityMetrics {
  naturalness_score?: number
  clarity_score?: number
  engagement_score?: number
  total_segments?: number
  average_segment_length?: number
}

export interface ScriptAudioBalanceMetrics {
  sound_effects?: string
  music?: string
  voice_differentiation?: string
  total_effects?: number
  total_music_cues?: number
  effects_per_minute?: number
}

export interface ScriptPacingMetrics {
  estimated_duration?: string
  pacing_issues?: string[]
  average_segment_duration?: string
  total_segments?: number
}

export interface ScriptReviewDetail {
  overall_score?: number
  overall_grade?: string
  issues_count?: number
  script_quality?: ScriptQualityMetrics
  audio_balance?: ScriptAudioBalanceMetrics
  pacing?: ScriptPacingMetrics
  revision_suggestions?: string[]
  issues?: ScriptReviewIssue[]
}

export interface ScriptEditorDialogProps {
  open: boolean
  loading: boolean
  chapter: {
    chapterId: number
    title: string
  } | null
  data: {
    scriptStatus: string
    scriptSegments: any[]
    scriptReview: ScriptReviewDetail | null
  } | null
  onClose: () => void
  onChangeSegmentText: (index: number, value: string) => void
  onSaveScript: (options: { nextStatus?: 'reviewed' | 'approved'; generateAudio?: boolean }) => void
  onPreviewSegmentAudio: (index: number, segment: any, previewType: PreviewType) => void
  onRegenerateSegment: (index: number, segment: any) => void
  onReviewSegment: (index: number, score: number) => void
  segmentReviews: Record<number, { quality_score?: number; needs_regenerate?: boolean }>
  segmentPreviewingIndex: number | null
  segmentPreviewingType: PreviewType | null
  segmentAudioUrls: Record<number, string>
  segmentDetailsOpen: Record<number, boolean>
  onToggleSegmentDetails: (index: number) => void
  onUpdateSegment: (index: number, patch: Record<string, any>) => void
  reviewMode: boolean
  onToggleReviewMode: () => void
  regeneratingSegments: Set<number>
}

export interface HistoryDialogProps {
  open: boolean
  loading: boolean
  historyProjects: any[]
  selectedProject: Project | null
  onCloseHistory: () => void
  onViewHistory: (audiobookProjectId: number) => Promise<void>
  onDeleteHistory: (audiobookProjectId: number) => Promise<void>
}

export type NavigationType =
  | PerformanceNavigationTiming['type']
  | 'navigate'
  | 'reload'
  | 'back_forward'
  | null
