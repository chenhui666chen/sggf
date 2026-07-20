import { describe, expect, it } from 'vitest'

import {
  buildGenerateAudioFromScriptPayload,
  buildScriptEditorChapterRef,
  buildUpdateChapterScriptPayload,
  extractQueuedAudiobookJobId,
  normalizeAudiobookChapterScriptData,
  normalizeSmartChunkPreviewResponse,
} from '../scriptEditorUtils'
import type { ScriptSegment } from '../types'

describe('audiobook script editor utils', () => {
  it('builds chapter references with title fallback', () => {
    expect(buildScriptEditorChapterRef(2, [
      { id: 1, chapter_number: 1, title: 'Opening' },
      { id: 2, chapter_number: 7, title: 'Storm' },
    ])).toEqual({
      chapterId: 2,
      title: '第7章 - Storm',
    })

    expect(buildScriptEditorChapterRef(99, [])).toEqual({
      chapterId: 99,
      title: '章节 99',
    })
  })

  it('normalizes chapter script payloads from the API', () => {
    expect(normalizeAudiobookChapterScriptData({
      script_status: 'reviewed',
      script_segments: [
        { text: 'Line 1', speaker: 'Narrator' },
      ],
      chapter_audio_available: true,
      chapter_audio_url: '/api/v1/audiobook/download/3/9',
      segment_timings: [
        { index: 0, start: 1.2, end: 3.4, duration: 2.2 },
      ],
      script_review: {
        overall_score: 8.8,
        issues: [{ severity: 'minor', description: 'Can be tighter' }],
      },
    })).toMatchObject({
      scriptStatus: 'reviewed',
      scriptSegments: [
        { text: 'Line 1', speaker: 'Narrator' },
      ],
      chapterAudioAvailable: true,
      chapterAudioUrl: '/api/v1/audiobook/download/3/9',
      segmentTimings: [
        { index: 0, start: 1.2, end: 3.4, duration: 2.2 },
      ],
      scriptReview: {
        overall_score: 8.8,
        issues_count: 1,
      },
    })

    expect(normalizeAudiobookChapterScriptData(null)).toEqual({
      scriptStatus: 'pending',
      scriptSegments: [],
      chapterAudioAvailable: false,
      chapterAudioUrl: '',
      segmentTimings: [],
      scriptReview: null,
    })
  })

  it('builds update payloads without mutating editor segments', () => {
    const segments: ScriptSegment[] = [{ text: 'Line 1' }]
    const payload = buildUpdateChapterScriptPayload(segments, 'approved')

    expect(payload).toEqual({
      script_segments: [{ text: 'Line 1' }],
      script_status: 'approved',
    })
    expect(payload.script_segments).not.toBe(segments)
  })

  it('builds audio generation payloads for one chapter or approved chapters', () => {
    expect(buildGenerateAudioFromScriptPayload({
      chapterId: 8,
      ttsModel: 'qwen3-tts-instruct-flash',
      narrationStyle: 'dramatic',
      narrationStylePrompt: '',
      outputFormat: 'mp3',
      generateSubtitle: true,
      timelineEdits: {
        'sfx-0-0': { startUnit: 12, durationUnits: 48, volume: 0.35 },
      },
    })).toEqual({
      chapter_ids: [8],
      tts_model: 'qwen3-tts-instruct-flash',
      output_format: 'mp3',
      generate_subtitle: true,
      timeline_edits: {
        'sfx-0-0': { startUnit: 12, durationUnits: 48, volume: 0.35 },
      },
    })

    expect(buildGenerateAudioFromScriptPayload({
      ttsModel: 'cosyvoice-v3.5-plus',
      narrationStyle: 'custom',
      narrationStylePrompt: '  克制、冷静  ',
      outputFormat: 'm4b',
      generateSubtitle: false,
    })).toEqual({
      tts_model: 'cosyvoice-v3.5-plus',
      output_format: 'm4b',
      generate_subtitle: false,
    })

    expect(buildGenerateAudioFromScriptPayload({
      chapterId: 9,
      ttsModel: 'qwen3-tts-instruct-flash',
      narrationStyle: 'documentary',
      narrationStylePrompt: '这段只应由 custom 使用',
      outputFormat: 'wav',
      generateSubtitle: true,
    })).toEqual({
      chapter_ids: [9],
      tts_model: 'qwen3-tts-instruct-flash',
      output_format: 'wav',
      generate_subtitle: true,
    })
  })

  it('extracts queued job ids defensively', () => {
    expect(extractQueuedAudiobookJobId({ job_id: ' job-1 ' })).toBe('job-1')
    expect(extractQueuedAudiobookJobId({ job_id: '' })).toBeNull()
    expect(extractQueuedAudiobookJobId(null)).toBeNull()
  })

  it('normalizes smart chunk preview responses defensively', () => {
    expect(normalizeSmartChunkPreviewResponse({
      original_segments: 3,
      chunked_segments: 2,
      total_tokens: 120,
      chunks: [
        { text: 'A', estimated_tokens: 40 },
        { text: 'B', estimated_tokens: 1901 },
      ],
      stats: {
        total_chunks: 2,
        total_tokens: 120,
        avg_tokens_per_chunk: 60,
        max_tokens_in_chunk: 80,
        min_tokens_in_chunk: 40,
      },
    })).toMatchObject({
      originalSegments: 3,
      chunkedSegments: 2,
      totalTokens: 120,
      changed: true,
      oversizedChunkCount: 1,
      stats: {
        total_chunks: 2,
        avg_tokens_per_chunk: 60,
      },
    })

    expect(normalizeSmartChunkPreviewResponse(null)).toMatchObject({
      originalSegments: 0,
      chunkedSegments: 0,
      totalTokens: 0,
      changed: false,
      oversizedChunkCount: 0,
    })
  })
})
