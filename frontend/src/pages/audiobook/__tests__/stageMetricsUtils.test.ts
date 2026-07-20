import { describe, expect, it } from 'vitest'

import {
  getPromptAudioQualitySummary,
} from '../stageMetricsUtils'

describe('stage metrics utils', () => {
  it('summarizes prompt audio quality feedback for final review display', () => {
    const summary = getPromptAudioQualitySummary({
      prompt_audio_quality: {
        available: true,
        coverage: {
          segments_count: 3,
          audio_segments_count: 2,
          missing_audio_count: 1,
          provider_prompt_snapshot_count: 3,
          inline_tag_strategy_count: 2,
          manual_review_pending_count: 2,
        },
        by_model: {
          'mimo-v2.5-tts': {
            model_family: 'mimo',
            segments_count: 1,
            audio_segments_count: 1,
            missing_audio_count: 0,
            provider_prompt_snapshot_count: 1,
            inline_tag_strategy_count: 1,
            use_tag_parser_count: 0,
            tag_count: 2,
            manual_review_segment_indices: [0],
            manual_review_fields: {
              tag_parse_success: null,
              text_contamination: null,
              score: null,
            },
          },
          'seed-tts-2.0-expressive': {
            model_family: 'doubao',
            segments_count: 2,
            audio_segments_count: 1,
            missing_audio_count: 1,
            provider_prompt_snapshot_count: 2,
            inline_tag_strategy_count: 1,
            use_tag_parser_count: 1,
            tag_count: 2,
            manual_review_segment_indices: [1],
          },
        },
      },
    })

    expect(summary).toEqual({
      coverage: {
        segmentsCount: 3,
        audioSegmentsCount: 2,
        missingAudioCount: 1,
        providerPromptSnapshotCount: 3,
        inlineTagStrategyCount: 2,
        manualReviewPendingCount: 2,
      },
      models: [
        {
          model: 'mimo-v2.5-tts',
          modelFamily: 'mimo',
          segmentsCount: 1,
          audioSegmentsCount: 1,
          missingAudioCount: 0,
          providerPromptSnapshotCount: 1,
          inlineTagStrategyCount: 1,
          useTagParserCount: 0,
          tagCount: 2,
          manualReviewSegmentIndices: [0],
          manualReviewFields: {
            tagParseSuccess: null,
            textContamination: null,
            score: null,
            notes: '',
            asrTranscript: '',
            asrAssist: null,
            reviewedAt: '',
            reviewedBy: null,
          },
        },
        {
          model: 'seed-tts-2.0-expressive',
          modelFamily: 'doubao',
          segmentsCount: 2,
          audioSegmentsCount: 1,
          missingAudioCount: 1,
          providerPromptSnapshotCount: 2,
          inlineTagStrategyCount: 1,
          useTagParserCount: 1,
          tagCount: 2,
          manualReviewSegmentIndices: [1],
          manualReviewFields: {
            tagParseSuccess: null,
            textContamination: null,
            score: null,
            notes: '',
            asrTranscript: '',
            asrAssist: null,
            reviewedAt: '',
            reviewedBy: null,
          },
        },
      ],
    })
  })

  it('normalizes prompt audio manual review fields for editable chapter results', () => {
    const summary = getPromptAudioQualitySummary({
      prompt_audio_quality: {
        available: true,
        coverage: {},
        by_model: {
          'minimax-speech-2.8-hd': {
            model_family: 'minimax',
            manual_review_segment_indices: [0],
            manual_review_fields: {
              tag_parse_success: true,
              text_contamination: false,
              score: 4.5,
              notes: '标签未污染正文',
              asr_transcript: 'tense whisper 第一段',
              asr_assist: {
                available: true,
                source: 'manual_transcript',
                segment_indices: [0],
                expected_text: '第一段',
                transcript_text: 'tense whisper 第一段',
                similarity_score: 0.82,
                word_error_rate: 0.18,
                detected_tag_residue: true,
                matched_tags: ['tense', 'whisper'],
                suggested_text_contamination: true,
                suggested_tag_parse_success: false,
              },
              reviewed_at: '2026-06-29T10:00:00+08:00',
              reviewed_by: 7,
            },
          },
        },
      },
    })

    expect(summary?.models[0].manualReviewFields).toEqual({
      tagParseSuccess: true,
      textContamination: false,
      score: 4.5,
      notes: '标签未污染正文',
      asrTranscript: 'tense whisper 第一段',
      asrAssist: {
        available: true,
        source: 'manual_transcript',
        segmentIndices: [0],
        expectedText: '第一段',
        transcriptText: 'tense whisper 第一段',
        similarityScore: 0.82,
        wordErrorRate: 0.18,
        detectedTagResidue: true,
        matchedTags: ['tense', 'whisper'],
        suggestedTextContamination: true,
        suggestedTagParseSuccess: false,
      },
      reviewedAt: '2026-06-29T10:00:00+08:00',
      reviewedBy: 7,
    })
  })

  it('returns null when prompt audio quality feedback is unavailable', () => {
    expect(getPromptAudioQualitySummary(null)).toBeNull()
    expect(getPromptAudioQualitySummary({})).toBeNull()
    expect(getPromptAudioQualitySummary({
      prompt_audio_quality: {
        available: false,
        reason: 'missing_script_segments',
      },
    })).toBeNull()
  })
})
