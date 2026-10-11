import type { NarrationStyleId } from './narrationStyles'
import type { AudiobookTtsModel } from '../../types/audiobook'
import type { RemixMissingSegment as ApiRemixMissingSegment } from '../../services/api'

/** 整章重新混音时缺失音频的片段信息（后端返回）。 */
export type RemixMissingSegment = ApiRemixMissingSegment

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
  has_review?: boolean
  duration?: number | null
  file_size?: number | null
  segment_count?: number | null
  dialogue_count?: number | null
  narration_count?: number | null
  character_count?: number | null
  generation_time?: number | null
  tts_cost?: number | null
  prompt_audio_quality?: Record<string, unknown> | null
  render_status?: string | null
  render_status_detail?: Record<string, unknown> | null
}

export interface AudiobookProjectDetail {
  id: number
  project_id?: number | null
  engine_mode?: 'legacy_stems' | 'seed_scene' | null
  status?: string | null
  total_chapters?: number | null
  completed_chapters?: number | null
  failed_chapters?: number | null
  total_duration?: number | null
  total_cost?: number | null
  total_size?: number | null
  chapter_audios?: ChapterAudio[]
}

/**
 * 章节渲染状态（§2.3 结构化状态，GUIDE 阶段 2）。
 *
 * - legacy_stems：renderStatus 来自 script_json/audio_path/script_status 完成条件；
 * - seed_scene：renderStatus 来自三维投影（published_render_status + desired_render_status）；
 * - executionStatus：进行中任务的 run 状态（queued/running/paused/succeeded/failed/cancelled）。
 */
export interface ChapterRenderState {
  renderStatus: string | null
  executionStatus: string | null
  audioUrl: string | null
  locked: boolean
  exportable: boolean
}

export const CHAPTER_RENDER_STATUS = {
  RENDERED_ALL_SEED: 'rendered_all_seed',
  RENDERED_WITH_FALLBACK: 'rendered_with_fallback',
  STALE: 'stale',
  MANUAL_REVIEW_REQUIRED: 'manual_review_required',
  FAILED: 'failed',
} as const

// ─── 场景编辑器（GUIDE 阶段 3.5） ──────────────────────────────────

/** 场景编辑 revision 链 head 投影（§2.9 last_revisions 元素）。 */
export interface SceneEditRevisionHead {
  revision_id: number
  revision_hash: string
  created_at?: string | null
}

/** 导演覆盖项（§2.6 stable_anchors 合同）。 */
export interface SceneDirectionOverrideItem {
  direction_type: 'performance' | 'sfx' | 'music' | 'acoustic' | string
  content: string
}

/** 场景编辑器场景条目（SceneEditorDocument.scenes 元素）。 */
export interface SceneEditorScene {
  scene_id: string
  status: string
  source_segment_indices?: number[]
  source_segment_keys?: string[]
  attempts?: number
  reused_checkpoint?: boolean
  fallback_reason?: string | null
  fallback_artifact?: Record<string, unknown> | null
  scene_audio_url?: string | null
  quality_report?: Record<string, unknown> | null
  metadata?: Record<string, unknown>
  /** 渲染时发送的完整提示词（旧 checkpoint 无记录时为空） */
  prompt?: string | null
  prompt_hash?: string | null
}

/** 场景编辑视图的稳定投影（§3.3）。 */
export interface SceneEditorDocument {
  chapter_id: number
  audiobook_project_id: number
  engine_mode: string
  execution_status: string
  published_render_status?: string | null
  desired_render_status?: string | null
  published_provenance?: string | null
  source_script_revision: string
  director_plan_revision?: string | null
  scene_topology_hash?: string | null
  scenes: SceneEditorScene[]
  editable_overrides: Record<string, unknown>
  /** 当前生效的音色绑定（voice_binding head payload），供音色编辑表单回显。 */
  voice_binding_current?: {
    tts_model?: string | null
    characters?: Array<Record<string, unknown>>
  } | null
  artifact_references: Record<string, unknown>
  last_revisions: Record<string, SceneEditRevisionHead | null>
  revision_set_hash?: string | null
  script_status?: string
  chapter_audio_available?: boolean
  chapter_audio_stale?: boolean
  chapter_audio_url?: string | null
  updated_at?: string | null
}

/** 场景编辑保存响应（revision_heads + revision_set_hash）。 */
export interface SceneEditSaveResponse {
  success: boolean
  revision_heads: Record<string, SceneEditRevisionHead | null>
  revision_set_hash?: string | null
  script_status?: string
  semantic_changed?: boolean
}

/** 引擎分支配置（§2.1 engines.{mode}，场景编辑器音色编辑用）。 */
export interface EngineBranchConfig {
  tts_models?: Record<string, {
    characters?: Record<string, unknown>
  }>
  scene_generation_preferences?: Record<string, unknown>
}

export type SceneEditType = 'dialogue' | 'director_override' | 'voice_binding'

export interface GenerationCheckpoint {
  chapter_id: number
  total_segments: number
  completed_segments: number
  completed_segment_indices?: number[]
  cached_audio_paths?: Record<string, string>
  /** 合成失败的 render chunk 索引（可断点重试）。 */
  failed_segment_indices?: number[]
  /** render chunk 索引 -> { error_type, error_message }。 */
  failed_segment_errors?: Record<string, MissingSegmentError>
  /** 缺失片段人类可读报告（含源剧本索引/角色/请求音色/错误类型）。 */
  missing_segments?: MissingSegmentInfo[]
  can_resume: boolean
  run_id?: number | null
  run_status?: string | null
  current_stage?: string | null
  celery_task_id?: string | null
  generate_subtitle?: boolean
  checkpoint_source?: string | null
  estimated_remaining_time?: number | null
}

export interface MissingSegmentError {
  error_type?: string | null
  error_message?: string | null
}

export interface MissingSegmentInfo {
  /** render chunk 索引。 */
  index: number
  /** 映射回源剧本片段的索引（长文本拆块后可能多个）。 */
  source_segment_indices?: number[]
  text?: string | null
  speaker?: string | null
  voice?: string | null
  segment_type?: string | null
  error_type?: string | null
  error_message?: string | null
}

// ─── Phase 2: 换音色恢复 ─────────────────────────────────────────────

export interface VoiceOverride {
  voice_id: string
  tts_model?: string | null
  reference_source?: string | null
  reference_audio_url?: string | null
  voice_reference_asset_id?: string | null
  voice_pool_publication_id?: string | null
}

export type RecoverAction = 'retry_missing' | 'replace_voice_missing' | 'replace_voice_all'

export interface RecoverSegmentsRequest {
  action: RecoverAction
  voice_overrides: Record<string, VoiceOverride>
  target_characters?: string[] | null
}

export interface RecoverSegmentsResponse {
  message: string
  action: RecoverAction
  job_id: string
  voice_overrides_applied?: string[]
  affected_segment_indices?: string[]
  temporary_voice_substitution?: boolean
  resumed_from_run_id?: number | null
}

export type StageStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'paused'
  | 'pause_requested'
  | 'cancelled'
  | 'completed_with_partial_failure'

export type PreviewType = 'voice' | 'sfx' | 'bgm' | 'mix'

export type SegmentSourceMode = 'library' | 'ai_generate'

export interface SegmentPreviewPlaybackOptions {
  startRatio?: number
  /** 候选生成成功后自动播放时传入，绕过 state 异步更新的闭包旧值 */
  candidateId?: string
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
  | 'scene_rendering'
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
  referenceSource?: 'user_private' | 'public_pool'
  referenceAudioUrl?: string
  voiceReferenceAssetId?: string
  voicePoolPublicationId?: string
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

export type AudioEngineMode = 'legacy_stems' | 'seed_scene'

export interface ProjectCharacterAudioConfig {
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
  reference_source?: 'user_private' | 'public_pool' | null
  reference_audio_url?: string | null
  voice_reference_asset_id?: string | null
  voice_pool_publication_id?: string | null
  source?: string | null
}

export interface ProjectEngineTtsModelConfig {
  characters: ProjectCharacterAudioConfig[]
}

/** 引擎分支配置（GUIDE §2.2 engines.{mode}） */
export interface ProjectEngineBranchConfig {
  tts_models?: Record<string, ProjectEngineTtsModelConfig>
  audio_fx?: AudioFxConfig | null
  scene_generation_preferences?: {
    music_enabled?: boolean
    music_style?: string | null
    soundscape_intensity?: string
    performance_style?: string
    timeline_mode?: string
    terminal_policy?: string
    semantic_review_enabled?: boolean
    semantic_review_mode?: string
  } | null
  // 旧分支形态（无 tts_models 归组时的兼容读取）
  characters?: ProjectCharacterAudioConfig[]
}

export interface ProjectAudioConfig {
  characters: ProjectCharacterAudioConfig[]
  audio_fx?: AudioFxConfig | null
  audio_engine_mode?: 'legacy_stems' | 'seed_scene' | 'auto'
  // 阶段 1 起开放两个 Seed Audio 模型；新任务默认 multilingual。
  seed_audio_model?: 'seed-audio-1.0' | 'seed-audio-1.0-multilingual'
  // 引擎分支持久化（GUIDE §2.2）：engines.{mode}.tts_models.{model}.characters
  engines?: Record<string, ProjectEngineBranchConfig>
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
  provider?: string
  languages?: string[]
  description?: string
  recommended?: string[]
  default_params?: VoiceDefaultParams
  supportsInstruct?: boolean
  disabled?: boolean
  disabledReason?: string
  sourceModel?: TtsModel
  referenceSource?: 'user_private' | 'public_pool'
  referenceAudioUrl?: string
  voiceReferenceAssetId?: string
  voicePoolPublicationId?: string
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
  dimension?: string
  fix_type?: string
  target_fields?: string[]
  segment_index?: number
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

export interface LLMDimensionScore {
  score?: number
  label?: string
  category?: string
  comment?: string
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
  llm_dimensions?: Record<string, LLMDimensionScore>
}

export interface ScriptSegmentVoiceParams {
  speaker?: string | null
  tts_model?: string | null
  resolved_tts_model?: string | null
  speed?: number | null
  rate?: number | null
  character_base_speed?: number | null
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
  layer?: string | null
  volume?: number | null
  timing?: string | null
  position_3d?: string | null
  duration?: number | null
  fade_in?: number | null
  fade_out?: number | null
  delay?: number | null
}

export interface ScriptSegmentMusicCueDetail {
  asset_id?: string | null
  style?: string | null
  name?: string | null
  mood?: string | null
  volume?: number | null
  fade_in?: number | null
  fade_out?: number | null
  duration?: number | null
  start_time?: number | null
  emotion_follow?: boolean | null
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
  segment_key?: string | null
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
  candidateId: string
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
  /** 应用人声候选后本地标记：整章混音已过期，禁用整章试听直至重新混音 */
  chapterAudioStale?: boolean
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
  labelKey?: string
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
  initialSegmentIndex?: number | null
  onInitialSegmentIndexConsumed?: () => void
  onClose: () => void
  onChangeSegmentText: (index: number, value: string) => void
  onSaveScript: (options: { nextStatus?: 'reviewed' | 'approved' }) => void
  /** 批准当前剧本后立即提交已批准章节生成音频（页面层编排，缩短跳转链路）。 */
  onApproveAndGenerateAudio?: () => void
  onPreviewSegmentAudio: (
    index: number,
    segment: ScriptSegment,
    previewType: PreviewType,
    options?: SegmentPreviewPlaybackOptions,
  ) => void
  onRegenerateSegment: (
    index: number,
    segment: ScriptSegment,
    previewType: PreviewType,
    sourceMode?: SegmentSourceMode,
  ) => void
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
  // 整章重新混音
  onRemixChapter?: () => void
  remixingChapter?: boolean
  remixError?: string | null
  remixMissingDialogOpen?: boolean
  remixMissingSegments?: RemixMissingSegment[]
  onForceRemixChapter?: () => void
  onCloseRemixMissingDialog?: () => void
}

export interface AudiobookProjectHistoryItem {
  id: number
  status?: string | null
  engine_mode?: 'legacy_stems' | 'seed_scene' | null
  created_at?: string | null
  updated_at?: string | null
  completed_chapters?: number | null
  total_chapters?: number | null
  // 音频已落盘（audio_path）章节数：区分"剧本完成、音频未生成"与"全部完成"
  audio_completed_chapters?: number | null
  total_duration?: number | null
}

export interface HistoryDialogProps {
  open: boolean
  loading: boolean
  historyProjects: AudiobookProjectHistoryItem[]
  selectedProject: Project | null
  onCloseHistory: () => void
  onViewHistory: (audiobookProjectId: number) => Promise<void>
  onDeleteHistory: (audiobookProjectId: number, options?: { delete_reason?: string; delete_files?: boolean }) => Promise<void>
}

export type NavigationType =
  | PerformanceNavigationTiming['type']
  | 'navigate'
  | 'reload'
  | 'back_forward'
  | null
