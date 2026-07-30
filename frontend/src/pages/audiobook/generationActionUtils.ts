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
