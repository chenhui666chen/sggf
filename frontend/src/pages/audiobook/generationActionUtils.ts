import type {
  AudiobookQueuedTaskResponse,
  CreateAudiobookProjectPayload,
} from '../../services/api'
import type { NarrationStyleId } from './narrationStyles'
import type {
  AudiobookVoiceConfigPayloadItem,
} from './projectAudioConfigUtils'
import type {
  AudioOutputFormat,
  GenerationCheckpoint,
  MissingSegmentInfo,
  TtsModel,
} from './types'
import { extractQueuedAudiobookJobId } from './scriptEditorUtils'

export type AudiobookGenerationMode = 'full' | 'script_only'

export const resolveAudiobookGenerationMode = (
  _scriptOnlyMode: boolean,
): AudiobookGenerationMode => 'script_only'

export const resolveProjectIdForAudiobookGeneration = ({
  selectedProjectId,
  routeProjectId,
}: {
  selectedProjectId: number | null
  routeProjectId: number | null
}): number | null => selectedProjectId ?? routeProjectId

export const buildCreateAudiobookProjectPayload = ({
  projectId,
  chapterIds,
  voiceConfig,
  ttsModel,
  outputFormat,
}: {
  projectId: number
  chapterIds: readonly number[]
  voiceConfig: AudiobookVoiceConfigPayloadItem[]
  ttsModel: TtsModel
  generationMode: AudiobookGenerationMode
  narrationStyle: NarrationStyleId
  narrationStylePrompt: string
  outputFormat: AudioOutputFormat
}): CreateAudiobookProjectPayload => ({
  project_id: projectId,
  chapter_ids: [...chapterIds],
  tts_provider: 'aliyun',
  enable_cache: true,
  voice_config: voiceConfig,
  tts_model: ttsModel,
  output_format: outputFormat,
  generate_subtitle: true,
  generation_mode: 'script_only',
  force_regenerate_script: true,
})

export const extractQueuedAudiobookProjectTask = (
  data: Partial<AudiobookQueuedTaskResponse> | null | undefined,
): { audiobookProjectId: number | null; jobId: string | null } => ({
  audiobookProjectId: typeof data?.audiobook_project_id === 'number' ? data.audiobook_project_id : null,
  jobId: extractQueuedAudiobookJobId(data),
})

export const resolveResumeGenerationMode = (
  data: Pick<AudiobookQueuedTaskResponse, 'task_type'> | null | undefined,
): AudiobookGenerationMode => (data?.task_type === 'script_only' ? 'script_only' : 'full')

export const markResumeCheckpointQueued = ({
  checkpoints,
  chapterId,
  jobId,
}: {
  checkpoints: Record<number, GenerationCheckpoint>
  chapterId: number
  jobId: string
}): Record<number, GenerationCheckpoint> => {
  const current = checkpoints[chapterId]
  if (!current) {
    return checkpoints
  }

  return {
    ...checkpoints,
    [chapterId]: {
      ...current,
      can_resume: false,
      run_status: 'queued',
      celery_task_id: jobId,
    },
  }
}

/**
 * 识别“可恢复的片段失败”：运行失败/可恢复，且存在失败片段索引，
 * 且已有成功片段缓存（cached_audio_paths 非空）。这类失败可通过
 * resume_from_checkpoint 只重合成缺失片段，不应被视为普通失败。
 */
export const hasRecoverableSegmentFailure = (
  checkpoint: GenerationCheckpoint | null | undefined,
): boolean => {
  if (!checkpoint) {
    return false
  }
  const failedIndices = checkpoint.failed_segment_indices || []
  const cachedPaths = checkpoint.cached_audio_paths || {}
  return (
    failedIndices.length > 0 &&
    Object.keys(cachedPaths).length > 0 &&
    checkpoint.can_resume
  )
}

/**
 * 构造缺失片段展示列表：优先用后端 missing_segments 报告，
 * 否则从 failed_segment_indices + failed_segment_errors 降级拼装。
 */
export const resolveMissingSegments = (
  checkpoint: GenerationCheckpoint | null | undefined,
): MissingSegmentInfo[] => {
  if (!checkpoint) {
    return []
  }
  const report = checkpoint.missing_segments
  if (Array.isArray(report) && report.length > 0) {
    return report
  }
  const errors = checkpoint.failed_segment_errors || {}
  return (checkpoint.failed_segment_indices || []).map((index) => {
    const error = errors[String(index)] || {}
    return {
      index,
      source_segment_indices: [],
      text: '',
      speaker: '',
      voice: '',
      segment_type: '',
      error_type: error.error_type || 'TTSSegmentError',
      error_message: error.error_message || 'tts_segment_failed',
    }
  })
}
