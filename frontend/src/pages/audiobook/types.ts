import type { NarrationStyleId } from './narrationStyles'
import type { AudiobookTtsModel } from '../../types/audiobook'

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

export interface ChapterAudio {
  id: number
  chapter_id: number
  chapter_number?: number | null
  audio_path?: string | null
  script_status?: string | null
  has_script?: boolean
  generation_time?: number | null
  tts_cost?: number | null
  prompt_audio_quality?: Record<string, unknown> | null
}

export interface AudiobookProjectDetail {
  id: number
  project_id?: number | null
  status?: string | null
  total_chapters?: number | null
  completed_chapters?: number | null
  failed_chapters?: number | null
  total_duration?: number | null
  total_cost?: number | null
  total_size?: number | null
  chapter_audios?: ChapterAudio[]
}

export interface GenerationCheckpoint {
  chapter_id: number
  total_segments: number
  completed_segments: number
  completed_segment_indices?: number[]
  cached_audio_paths?: Record<string, string>
  can_resume: boolean
  run_id?: number | null
  run_status?: string | null
  current_stage?: string | null
  celery_task_id?: string | null
  generate_subtitle?: boolean
  checkpoint_source?: string | null
  estimated_remaining_time?: number | null
}

export type StageStatus = 'pending' | 'running' | 'completed' | 'failed'

export type PreviewType = 'voice' | 'sfx' | 'bgm' | 'mix'

export interface SegmentPreviewPlaybackOptions {
  startRatio?: number
}

export interface ScriptSegmentTiming {
  index: number
  start: number
  end?: number | null
  duration?: number | null
}

export type TtsModel = AudiobookTtsModel

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
  | 'project_export'
  | 'asr_transcript_queued'
  | 'asr_transcript_provider_check'
  | 'asr_transcript_skipped'

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
  metrics?: Record<string, unknown>
  message?: string
}

export interface TaskStatus {
  task_id: string
  audiobook_project_id: number
  chapter_id?: number | null
  task_type?: string | null
  status: StageStatus
  current_stage?: string | null
  progress: number
  stages: Record<StageKey, StageInfo>
  created_at?: string
  updated_at?: string
  detail?: Record<string, unknown>
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
  voiceCloneDataUrl?: string
  voiceDesignPrompt?: string
  mimoVoiceAssetId?: string
  stepaudioVoiceAssetId?: string
  source?: 'user' | 'ai_suggest' | string | null
}

export interface AudioFxConfig {
  enable_sound_effects: boolean
  enable_music: boolean
  sound_effect_density: 'low' | 'medium' | 'high' | 'off'
  music_density: 'low' | 'medium' | 'high' | 'off'
  intelligent_balance?: boolean
  balance_strategy?: 'auto' | 'ducking' | 'sidechain' | 'none'
}

export interface ProjectAudioConfig {
  characters: {
    character_id: number
    name: string
    voice_id: string
    volume?: number | null
    speed?: number | null
    pitch?: number | null
    tts_model?: TtsModel | null
    voice_type?: string | null
    personality?: string | null
    emotion_tendency?: string | null
    voice_clone_data_url?: string | null
    voice_design_prompt?: string | null
    mimo_voice_asset_id?: string | null
    stepaudio_voice_asset_id?: string | null
    source?: string | null
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
  customType?: 'clone' | 'design'
  languages?: string[]
  description?: string
  recommended?: string[]
  default_params?: VoiceDefaultParams
  supportsInstruct?: boolean
  disabled?: boolean
  disabledReason?: string
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
  unresolved_effect_count?: number
  placeholder_effect_count?: number
  missing_effect_file_count?: number
}

export interface ScriptAudioWarning {
  code?: string
  level?: string
  message?: string
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
  audio_warnings?: ScriptAudioWarning[]
}

export interface ScriptSegmentVoiceParams {
  speaker?: string | null
  speed?: number | null
  rate?: number | null
  pitch?: number | null
  volume?: number | null
  emotion?: string | null
  voice_clone_data_url?: string | null
  voice_design_prompt?: string | null
  mimo_voice_asset_id?: string | null
  stepaudio_voice_asset_id?: string | null
  provider_prompt_snapshot?: ProviderPromptSnapshot | null
}

export interface InlineTagStrategySnapshot {
  model_family?: string | null
  placement?: string | null
  style_tags?: string[] | null
  inline_tags?: string[] | null
  use_tag_parser?: boolean | null
}

export interface ProviderPromptSnapshot {
  provider_prompt?: {
    inline_tag_strategy?: InlineTagStrategySnapshot | null
    [key: string]: unknown
  } | null
  [key: string]: unknown
}

export interface InlineTagStrategySummary {
  modelFamily: string
  placement: string
  tags: string[]
  useTagParser: boolean
}

export interface PromptAudioQualityCoverageSummary {
  segmentsCount: number
  audioSegmentsCount: number
  missingAudioCount: number
  providerPromptSnapshotCount: number
  inlineTagStrategyCount: number
  manualReviewPendingCount: number
}

export interface PromptAudioQualityModelSummary {
  model: string
  modelFamily: string
  segmentsCount: number
  audioSegmentsCount: number
  missingAudioCount: number
  providerPromptSnapshotCount: number
  inlineTagStrategyCount: number
  useTagParserCount: number
  tagCount: number
  manualReviewSegmentIndices: number[]
  manualReviewFields: PromptAudioQualityManualReviewFields
}

export interface PromptAudioQualityManualReviewFields {
  tagParseSuccess: boolean | null
  textContamination: boolean | null
  score: number | null
  notes: string
  asrTranscript: string
  asrAssist: PromptAudioQualityAsrAssist | null
  reviewedAt: string
  reviewedBy: number | null
}

export interface PromptAudioQualityAsrAssist {
  available: boolean
  source: string
  segmentIndices: number[]
  expectedText: string
  transcriptText: string
  similarityScore: number | null
  wordErrorRate: number | null
  detectedTagResidue: boolean | null
  matchedTags: string[]
  suggestedTextContamination: boolean | null
  suggestedTagParseSuccess: boolean | null
}

export interface PromptAudioQualitySummary {
  coverage: PromptAudioQualityCoverageSummary
  models: PromptAudioQualityModelSummary[]
}

export interface ScriptSegmentSoundEffectDetail {
  asset_id?: string | null
  id?: string | null
  effect_id?: string | null
  name?: string | null
}

export interface ScriptSegmentMusicCueDetail {
  asset_id?: string | null
  style?: string | null
  name?: string | null
  mood?: string | null
}

export interface AudioAssetSelection {
  id: string
  type: 'sfx' | 'music'
  label: string
  name?: string
  style?: string
  mood?: string
}

export interface ScriptSegment {
  index?: number | null
  type?: string | null
  speaker?: string | null
  speaker_name?: string | null
  character_name?: string | null
  role_name?: string | null
  emotion?: string | null
  text?: string | null
  audio_path?: string | null
  sfx_audio_path?: string | null
  bgm_audio_path?: string | null
  mix_audio_path?: string | null
  performance_notes?: string | null
  original_text?: string | null
  adaptation_reason?: string | null
  pause_before?: number | null
  pause_after?: number | null
  instruct_emotion?: string | null
  instruct_scene?: string | null
  instruct_role?: string | null
  instruct_identity?: string | null
  voice_params?: ScriptSegmentVoiceParams | null
  sound_effects_simple?: string[] | null
  sound_effects?: Array<ScriptSegmentSoundEffectDetail | string> | null
  music_cue_simple?: string | null
  music_cue?: ScriptSegmentMusicCueDetail | string | null
}

export interface PendingSegmentRegeneration {
  candidateAudioPath: string
  previewType: PreviewType
  segment: ScriptSegment
  generatedAt?: string
}

export type PendingSegmentRegenerationMap = Record<number, Partial<Record<PreviewType, PendingSegmentRegeneration>>>

export interface ScriptReviewDialogData {
  report: ScriptReviewDetail | null
  segments: ScriptSegment[]
  chapterId?: number | null
}

export interface ScriptEditorChapterRef {
  chapterId: number
  title: string
}

export interface ScriptEditorStateData {
  scriptStatus: string
  scriptSegments: ScriptSegment[]
  chapterAudioAvailable?: boolean
  chapterAudioUrl?: string
  segmentTimings?: ScriptSegmentTiming[]
  scriptReview: ScriptReviewDetail | null
}

export interface TimelineClipEdit {
  startUnit: number
  durationUnits: number
  volume?: number
}

export type TimelineClipEditMap = Record<string, TimelineClipEdit>

export type TimelineClipEditUpdater =
  | TimelineClipEditMap
  | ((current: TimelineClipEditMap) => TimelineClipEditMap)

export interface SmartChunkPreviewStats {
  total_chunks: number
  total_tokens: number
  avg_tokens_per_chunk: number
  max_tokens_in_chunk: number
  min_tokens_in_chunk: number
}

export interface SmartChunkPreviewResult {
  originalSegments: number
  chunkedSegments: number
  totalTokens: number
  chunks: ScriptSegment[]
  stats: SmartChunkPreviewStats
  changed: boolean
  oversizedChunkCount: number
}

export interface AudiobookEditorSessionState {
  projectId?: number | null
  audiobookProjectId?: number | null
  chapterId?: number | null
  reviewMode?: boolean
  openSegmentDetailIndices?: number[]
  segmentReviews?: Record<number, { quality_score?: number; needs_regenerate?: boolean }>
  timelineEdits?: TimelineClipEditMap
  data?: ScriptEditorStateData | null
  updatedAt?: string
  writerTabId?: string
}

export interface EditorConflictFieldDiffPreview {
  key: string
  label: string
  currentValue: string
  incomingValue: string
}

export interface EditorConflictSegmentDiffPreview {
  index: number
  speaker: string
  changeType: 'modified' | 'added' | 'removed'
  fieldDiffs: EditorConflictFieldDiffPreview[]
}

export interface EditorConflictDiffPreview {
  fieldDiffs: EditorConflictFieldDiffPreview[]
  segmentDiffs: EditorConflictSegmentDiffPreview[]
}

export interface AudiobookEditorSyncRegistry {
  entries?: Record<string, AudiobookEditorSessionState>
}

export interface DeleteChapterSessionTarget {
  id: number
  chapterNumber: number
  title: string
  contentPreview: string
}

export interface AudiobookPageSessionState {
  projectId?: number | null
  audiobookProjectId?: number | null
  browserPlayerOpen?: boolean
  showHistory?: boolean
  scriptOnlyMode?: boolean
  forceRegenerateScript?: boolean
  narrationStyle?: NarrationStyleId
  narrationStylePrompt?: string
  outputFormat?: AudioOutputFormat
  generateSubtitle?: boolean
  scriptReviewDialogOpen?: boolean
  scriptReviewData?: ScriptReviewDialogData | null
  scriptReviewSelectedIssueIndex?: number | null
  scriptReviewSelectedSegmentIndex?: number | null
  stageMetricsDialogOpen?: boolean
  stageMetricsData?: {
    stageKey: StageKey
    info: StageInfo
  } | null
  deleteChapterDialogOpen?: boolean
  deleteChapterTarget?: DeleteChapterSessionTarget | null
  deleteChapterReason?: string
  deleteChapterFiles?: boolean
  cloneRecordDialogOpen?: boolean
  cloneName?: string
  cloneUrl?: string
  designName?: string
  designPrompt?: string
  designPreviewText?: string
  newProjectDialogOpen?: boolean
  newProjectTitle?: string
  newProjectText?: string
  updatedAt?: string
}

export interface ScriptEditorDialogProps {
  open: boolean
  loading: boolean
  chapter: ScriptEditorChapterRef | null
  data: ScriptEditorStateData | null
  onClose: () => void
  onChangeSegmentText: (index: number, value: string) => void
  onSaveScript: (options: { nextStatus?: 'reviewed' | 'approved'; generateAudio?: boolean }) => void
  onPreviewSegmentAudio: (
    index: number,
    segment: ScriptSegment,
    previewType: PreviewType,
    options?: SegmentPreviewPlaybackOptions,
  ) => void
  onRegenerateSegment: (index: number, segment: ScriptSegment, previewType: PreviewType) => void
  onStartSegmentVoiceRecording: (index: number, segment: ScriptSegment) => void
  onStopSegmentVoiceRecording: () => void
  onApplySegmentRegeneration: (index: number, previewType: PreviewType) => void
  onDiscardSegmentRegeneration: (index: number, previewType: PreviewType) => void
  onReviewSegment: (index: number, score: number) => void
  segmentReviews: Record<number, { quality_score?: number; needs_regenerate?: boolean }>
  pendingSegmentRegenerations: PendingSegmentRegenerationMap
  recordingSegmentIndex: number | null
  segmentPreviewingIndex: number | null
  segmentPreviewingType: PreviewType | null
  segmentAudioUrls: Record<number, string>
  segmentDetailsOpen: Record<number, boolean>
  onToggleSegmentDetails: (index: number) => void
  onUpdateSegment: (index: number, patch: Partial<ScriptSegment>) => void
  timelineEdits: TimelineClipEditMap
  onChangeTimelineEdits: (updater: TimelineClipEditUpdater) => void
  reviewMode: boolean
  onToggleReviewMode: () => void
  regeneratingSegments: Set<number>
  smartChunkPreview: SmartChunkPreviewResult | null
  smartChunkPreviewLoading: boolean
  onPreviewSmartChunking: () => void
  editorConflict?: AudiobookEditorSessionState | null
  editorConflictTimeLabel?: string | null
  editorConflictPreview?: EditorConflictDiffPreview | null
  visibleEditorConflictSegmentDiffs?: EditorConflictSegmentDiffPreview[]
  hiddenEditorConflictSegmentDiffCount?: number
  onApplyIncomingDraft?: () => void
  onKeepLocalDraft?: () => void
  projectId?: number
}

export interface AudiobookProjectHistoryItem {
  id: number
  status?: string | null
  created_at?: string | null
  updated_at?: string | null
  completed_chapters?: number | null
  total_chapters?: number | null
  total_duration?: number | null
}

export interface HistoryDialogProps {
  open: boolean
  loading: boolean
  historyProjects: AudiobookProjectHistoryItem[]
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
