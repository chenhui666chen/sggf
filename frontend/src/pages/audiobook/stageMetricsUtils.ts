import type {
  PromptAudioQualityAsrAssist,
  PromptAudioQualityManualReviewFields,
  PromptAudioQualitySummary,
} from './types'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

const numberValue = (value: unknown): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : 0

const stringValue = (value: unknown): string =>
  typeof value === 'string' ? value.trim() : ''

const numberListValue = (value: unknown): number[] =>
  Array.isArray(value)
    ? value
        .map((item) => numberValue(item))
        .filter((item) => Number.isFinite(item))
    : []

const nullableNumberValue = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const nullableBooleanValue = (value: unknown): boolean | null =>
  typeof value === 'boolean' ? value : null

const getPromptAudioAsrAssist = (
  value: unknown,
): PromptAudioQualityAsrAssist | null => {
  if (!isRecord(value)) {
    return null
  }

  return {
    available: value.available === true,
    source: stringValue(value.source),
    segmentIndices: numberListValue(value.segment_indices),
    expectedText: stringValue(value.expected_text),
    transcriptText: stringValue(value.transcript_text),
    similarityScore: nullableNumberValue(value.similarity_score),
    wordErrorRate: nullableNumberValue(value.word_error_rate),
    detectedTagResidue: nullableBooleanValue(value.detected_tag_residue),
    matchedTags: Array.isArray(value.matched_tags)
      ? value.matched_tags.map((tag) => stringValue(tag)).filter(Boolean)
      : [],
    suggestedTextContamination: nullableBooleanValue(value.suggested_text_contamination),
    suggestedTagParseSuccess: nullableBooleanValue(value.suggested_tag_parse_success),
  }
}

const getPromptAudioManualReviewFields = (
  value: unknown,
): PromptAudioQualityManualReviewFields => {
  const fields = isRecord(value) ? value : {}

  return {
    tagParseSuccess: nullableBooleanValue(fields.tag_parse_success),
    textContamination: nullableBooleanValue(fields.text_contamination),
    score: nullableNumberValue(fields.score),
    notes: stringValue(fields.notes),
    asrTranscript: stringValue(fields.asr_transcript),
    asrAssist: getPromptAudioAsrAssist(fields.asr_assist),
    reviewedAt: stringValue(fields.reviewed_at),
    reviewedBy: nullableNumberValue(fields.reviewed_by),
  }
}

export const getPromptAudioQualitySummary = (
  metrics: Record<string, unknown> | null | undefined,
): PromptAudioQualitySummary | null => {
  if (!isRecord(metrics)) {
    return null
  }

  const feedback = metrics.prompt_audio_quality
  if (!isRecord(feedback) || feedback.available !== true) {
    return null
  }

  const coverage = isRecord(feedback.coverage) ? feedback.coverage : {}
  const byModel = isRecord(feedback.by_model) ? feedback.by_model : {}
  const models = Object.entries(byModel)
    .filter(([, rawModel]) => isRecord(rawModel))
    .map(([model, rawModel]) => {
      const modelData = rawModel as Record<string, unknown>
      return {
        model,
        modelFamily: stringValue(modelData.model_family),
        segmentsCount: numberValue(modelData.segments_count),
        audioSegmentsCount: numberValue(modelData.audio_segments_count),
        missingAudioCount: numberValue(modelData.missing_audio_count),
        providerPromptSnapshotCount: numberValue(modelData.provider_prompt_snapshot_count),
        inlineTagStrategyCount: numberValue(modelData.inline_tag_strategy_count),
        useTagParserCount: numberValue(modelData.use_tag_parser_count),
        tagCount: numberValue(modelData.tag_count),
        manualReviewSegmentIndices: numberListValue(modelData.manual_review_segment_indices),
        manualReviewFields: getPromptAudioManualReviewFields(modelData.manual_review_fields),
      }
    })

  if (models.length === 0) {
    return null
  }

  return {
    coverage: {
      segmentsCount: numberValue(coverage.segments_count),
      audioSegmentsCount: numberValue(coverage.audio_segments_count),
      missingAudioCount: numberValue(coverage.missing_audio_count),
      providerPromptSnapshotCount: numberValue(coverage.provider_prompt_snapshot_count),
      inlineTagStrategyCount: numberValue(coverage.inline_tag_strategy_count),
      manualReviewPendingCount: numberValue(coverage.manual_review_pending_count),
    },
    models,
  }
}
