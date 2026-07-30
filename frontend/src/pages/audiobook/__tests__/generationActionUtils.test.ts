import { describe, expect, it } from 'vitest'

import {
  buildCreateAudiobookProjectPayload,
  extractQueuedAudiobookProjectTask,
  markResumeCheckpointQueued,
  resolveAudiobookGenerationMode,
  resolveProjectIdForAudiobookGeneration,
  resolveResumeGenerationMode,
} from '../generationActionUtils'
import type { GenerationCheckpoint } from '../types'

const buildCheckpoint = (
  patch: Partial<GenerationCheckpoint> = {},
): GenerationCheckpoint => ({
  chapter_id: 1,
  total_segments: 10,
  completed_segments: 4,
  can_resume: true,
  ...patch,
})

describe('audiobook generation action utils', () => {
  it('resolves generation mode and request project ids', () => {
    expect(resolveAudiobookGenerationMode(true)).toBe('script_only')
    expect(resolveAudiobookGenerationMode(false)).toBe('script_only')
    expect(resolveProjectIdForAudiobookGeneration({
      selectedProjectId: 7,
      routeProjectId: 8,
    })).toBe(7)
    expect(resolveProjectIdForAudiobookGeneration({
      selectedProjectId: null,
      routeProjectId: 8,
    })).toBe(8)
    expect(resolveProjectIdForAudiobookGeneration({
      selectedProjectId: null,
      routeProjectId: null,
    })).toBeNull()
  })

  it('builds create audiobook project payloads without mutating chapter ids', () => {
    const chapterIds = [1, 2]
    const payload = buildCreateAudiobookProjectPayload({
      projectId: 9,
      chapterIds,
      voiceConfig: [{
        character_name: '旁白',
        voice_id: 'Neil',
      }],
      ttsModel: 'qwen3-tts-instruct-flash',
      generationMode: 'full',
      narrationStyle: 'dramatic',
      narrationStylePrompt: '',
      outputFormat: 'wav',
    })

    expect(payload).toEqual({
      project_id: 9,
      chapter_ids: [1, 2],
      tts_provider: 'aliyun',
      enable_cache: true,
      voice_config: [{
        character_name: '旁白',
        voice_id: 'Neil',
      }],
      tts_model: 'qwen3-tts-instruct-flash',
      output_format: 'wav',
      generate_subtitle: true,
      generation_mode: 'script_only',
      force_regenerate_script: true,
    })
    expect(payload.chapter_ids).not.toBe(chapterIds)
  })

  it('omits narration style fields from create payloads', () => {
    const customStylePayload = buildCreateAudiobookProjectPayload({
      projectId: 9,
      chapterIds: [1],
      voiceConfig: [],
      ttsModel: 'cosyvoice-v3.5-plus',
      generationMode: 'full',
      narrationStyle: 'custom',
      narrationStylePrompt: '  慢速、温柔，并保留长停顿  ',
      outputFormat: 'mp3',
    })
    expect(customStylePayload).toEqual(expect.objectContaining({
      generation_mode: 'script_only',
      output_format: 'mp3',
      generate_subtitle: true,
      force_regenerate_script: true,
    }))

    const payloadWithoutNarrationStyle = buildCreateAudiobookProjectPayload({
      projectId: 9,
      chapterIds: [1],
      voiceConfig: [],
      ttsModel: 'cosyvoice-v3.5-plus',
      generationMode: 'script_only',
      narrationStyle: 'dramatic',
      narrationStylePrompt: '这段不应透传',
      outputFormat: 'mp3',
    })
    expect(payloadWithoutNarrationStyle).not.toHaveProperty('narration_style')
    expect(payloadWithoutNarrationStyle).not.toHaveProperty('narration_style_prompt')
  })

  it('extracts queued audiobook project task identifiers defensively', () => {
    expect(extractQueuedAudiobookProjectTask({
      audiobook_project_id: 12,
      job_id: ' job-1 ',
    })).toEqual({
      audiobookProjectId: 12,
      jobId: 'job-1',
    })
    expect(extractQueuedAudiobookProjectTask({
      audiobook_project_id: '12' as never,
      job_id: '',
    })).toEqual({
      audiobookProjectId: null,
      jobId: null,
    })
  })

  it('resolves resume generation modes from queued task data', () => {
    expect(resolveResumeGenerationMode({ task_type: 'script_only' })).toBe('script_only')
    expect(resolveResumeGenerationMode({ task_type: 'full' })).toBe('full')
    expect(resolveResumeGenerationMode(null)).toBe('full')
  })

  it('marks a resume checkpoint as queued without changing missing chapters', () => {
    const checkpoints = {
      3: buildCheckpoint({ chapter_id: 3 }),
    }
    const queued = markResumeCheckpointQueued({
      checkpoints,
      chapterId: 3,
      jobId: 'job-3',
    })

    expect(queued).toEqual({
      3: {
        ...checkpoints[3],
        can_resume: false,
        run_status: 'queued',
        celery_task_id: 'job-3',
      },
    })
    expect(markResumeCheckpointQueued({
      checkpoints,
      chapterId: 9,
      jobId: 'job-9',
    })).toBe(checkpoints)
  })
})
