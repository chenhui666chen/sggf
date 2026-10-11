import { describe, expect, it } from 'vitest'

import {
  buildCreateAudiobookProjectPayload,
  extractQueuedAudiobookProjectTask,
  hasRecoverableSegmentFailure,
  markResumeCheckpointQueued,
  resolveAudiobookGenerationMode,
  resolveMissingSegments,
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
        voice_id: 'longsanshu_v3.1',
      }],
      ttsModel: 'qwen-audio-3.1-tts-flash',
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
        voice_id: 'longsanshu_v3.1',
      }],
      tts_model: 'qwen-audio-3.1-tts-flash',
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

  it('detects recoverable segment failures only when failed indices and cached audio exist', () => {
    expect(hasRecoverableSegmentFailure(buildCheckpoint({
      failed_segment_indices: [3],
      cached_audio_paths: { '0': 'temp.mp3' },
    }))).toBe(true)
    // 无缓存音频：不构成可恢复片段失败。
    expect(hasRecoverableSegmentFailure(buildCheckpoint({
      failed_segment_indices: [3],
    }))).toBe(false)
    // 无失败索引：普通可恢复进度，不是片段失败。
    expect(hasRecoverableSegmentFailure(buildCheckpoint({
      cached_audio_paths: { '0': 'temp.mp3' },
    }))).toBe(false)
    // 不可恢复（如已入队）：不提示片段失败。
    expect(hasRecoverableSegmentFailure(buildCheckpoint({
      can_resume: false,
      failed_segment_indices: [3],
      cached_audio_paths: { '0': 'temp.mp3' },
    }))).toBe(false)
  })

  it('resolves missing segments preferring backend report then falling back to indices', () => {
    const report = [{
      index: 3,
      source_segment_indices: [2],
      text: '第二段。',
      speaker: '旁白',
      voice: 'badao_shaoye',
      error_type: 'ReadTimeout',
      error_message: 'timed out',
    }]
    expect(resolveMissingSegments(buildCheckpoint({ missing_segments: report }))).toEqual(report)

    const fallback = resolveMissingSegments(buildCheckpoint({
      failed_segment_indices: [5],
      failed_segment_errors: { '5': { error_type: 'HTTPStatusError', error_message: 'HTTP 500' } },
    }))
    expect(fallback).toEqual([{
      index: 5,
      source_segment_indices: [],
      text: '',
      speaker: '',
      voice: '',
      segment_type: '',
      error_type: 'HTTPStatusError',
      error_message: 'HTTP 500',
    }])

    expect(resolveMissingSegments(buildCheckpoint())).toEqual([])
  })
})
